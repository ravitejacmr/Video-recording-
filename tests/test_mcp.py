import asyncio
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import pytest
from PIL import Image as PILImage
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamablehttp_client
from studio.mcp_service import StudioService
from studio.mcp_server import build_server
from studio.model import Project, Clip


def test_scoped_editing_revision_history_and_export(tmp_path):
    service = StudioService(tmp_path)
    logo = tmp_path/'Media'/'logo.png'
    PILImage.new('RGB',(80,50),'blue').save(logo)
    result = service.create_project('MCP demo',320,180)
    id_,rev = result['project_id'],result['revision']
    assert service.list_media()['files'][0]['media_path']=='Media/logo.png'
    result = service.add_media(id_,rev,'Media/logo.png',source_out=1)
    with pytest.raises(ValueError,match='changed'):
        service.add_title(id_,rev,'stale',0,1)
    clip_id = result['clips'][0]['id']
    result = service.update_clip(id_,result['revision'],clip_id,{'volume':.2,'scale':.5})
    result = service.undo(id_,result['revision'])
    assert result['clips'][0]['scale']==1
    result = service.undo(id_,result['revision'],True)
    assert result['clips'][0]['scale']==.5
    result = service.add_title(id_,result['revision'],'Hello',0,1)
    job = service.render(id_,result['revision'],True,0,1)
    for _ in range(100):
        job = service.job_status(job['job_id'])
        if job['status'] in ('completed','failed'): break
        time.sleep(.05)
    assert job['status']=='completed',job
    assert service.preview_frame(job['job_id'],.1).startswith(b'\xff\xd8')
    service.close()


@pytest.mark.parametrize('path',['../secret.mp4','Media/../../secret.mp4','C:/secret.mp4',
                                 '//server/share/file.mp4','Media\\video.mp4','https://example.com/x.mp4'])
def test_path_escape_rejected(tmp_path,path):
    service = StudioService(tmp_path)
    with pytest.raises(ValueError): service.scoped(path)


def test_project_cannot_escape_via_embedded_path(tmp_path):
    service = StudioService(tmp_path/'workspace')
    result = service.create_project('Test')
    path = service.project_file(result['project_id'])
    Project(clips=[Clip(path=str(tmp_path/'private.mp4'))]).save(path)
    with pytest.raises(ValueError,match='outside'): service.get_project(result['project_id'])


def test_recording_requires_local_opt_in(tmp_path):
    service = StudioService(tmp_path)
    with pytest.raises(ValueError,match='disabled'): service.start_recording(0)
    with pytest.raises(ValueError,match='disabled'): service.recording_devices()
    assert service.recording_status()['status']=='idle'


def test_atomic_save_rejects_stale_writer(tmp_path):
    service = StudioService(tmp_path)
    data = service.create_project('Original')
    path = service.project_file(data['project_id'])
    stale = Project.load(path)
    service.add_title(data['project_id'],data['revision'],'Fresh title',0,1)
    with pytest.raises(ValueError,match='changed'): stale.save(path,expected_revision=data['revision'])
    assert Project.load(path).clips[0].text=='Fresh title'


def test_stdio_protocol_tools_and_error_results(tmp_path):
    async def run():
        parameters = StdioServerParameters(command=sys.executable,args=[str(Path(__file__).parents[1]/'mcp_main.py'),
                                            '--stdio','--workspace',str(tmp_path)])
        async with stdio_client(parameters) as (read,write):
            async with ClientSession(read,write) as session:
                await session.initialize()
                tools = await session.list_tools()
                names = {t.name:t for t in tools.tools}
                assert len(names)==24
                assert names['get_project'].annotations.readOnlyHint
                assert names['start_screen_recording'].annotations.openWorldHint
                result = await session.call_tool('create_project',{'name':'Protocol test','width':320,'height':180})
                assert not result.isError
                data = result.structuredContent
                result = await session.call_tool('add_title',{'project_id':data['project_id'],
                      'expected_revision':data['revision'],'text':'Hello MCP','duration':1})
                assert not result.isError
                data = result.structuredContent
                assert data['clips'][0]['text']=='Hello MCP'
                bad = await session.call_tool('start_screen_recording',{'monitor_id':0})
                assert bad.isError
                bad = await session.call_tool('update_clip',{'project_id':data['project_id'],
                    'expected_revision':data['revision'],'clip_id':data['clips'][0]['id'],
                    'changes':{'font':'../secret.ttf'}})
                assert bad.isError
    asyncio.run(run())


def test_http_protocol_and_origin_rejection(tmp_path):
    import httpx
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0));port = sock.getsockname()[1]
    proc = subprocess.Popen([sys.executable,str(Path(__file__).parents[1]/'mcp_main.py'),
                             '--workspace',str(tmp_path),'--port',str(port)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    url = f'http://127.0.0.1:{port}/mcp'
    try:
        for _ in range(100):
            try:
                response = httpx.get(url,timeout=.2,trust_env=False)
                break
            except httpx.TransportError: time.sleep(.05)
        else: pytest.fail('MCP HTTP service did not start')
        response = httpx.post(url,trust_env=False,headers={'Origin':'https://untrusted.example',
                              'Accept':'application/json, text/event-stream'},json={'jsonrpc':'2.0','id':1,'method':'initialize'})
        assert response.status_code in (400,403,421)
        async def run():
            async with streamablehttp_client(url,httpx_client_factory=lambda **kwargs:httpx.AsyncClient(trust_env=False,**kwargs)) as (read,write,_):
                async with ClientSession(read,write) as session:
                    await session.initialize()
                    response = await session.call_tool('studio_status',{})
                    assert not response.isError
                    assert response.structuredContent['status']=='ready'
        asyncio.run(run())
    finally:
        proc.terminate()
        proc.wait(timeout=15)


def test_disguised_playlist_is_not_followed(tmp_path):
    from studio.engine import probe
    service = StudioService(tmp_path)
    playlist = tmp_path/'Media'/'not-a-video.mp4'
    playlist.write_text("ffconcat version 1.0\nfile '../outside.wav'\n")
    info = probe(str(playlist))
    assert not info['video'] and not info['audio']


def test_undo_cannot_discard_external_editor_changes(tmp_path):
    service = StudioService(tmp_path)
    data = service.create_project('History')
    data = service.add_title(data['project_id'],data['revision'],'MCP title',0,1)
    path = service.project_file(data['project_id'])
    p = Project.load(path)
    p.clips[0].text = 'User changed this in the editor'
    p.save(path)
    data = service.get_project(data['project_id'])
    with pytest.raises(ValueError,match='outside this MCP history'):
        service.undo(data['project_id'],data['revision'])
    assert Project.load(path).clips[0].text=='User changed this in the editor'
