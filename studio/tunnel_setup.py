"""Interactive Windows setup; runtime keys stay in memory, never in project files."""
from pathlib import Path
import getpass
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import urllib.request
import urllib.error
import zipfile

RELEASES = 'https://api.github.com/repos/openai/tunnel-client/releases/latest'


def unpack_verified(data,checksums,asset_name,target):
    expected = None
    for line in checksums.splitlines():
        parts = line.split()
        if len(parts)>=2 and parts[-1].lstrip('*')==asset_name:
            expected = parts[0].lower()
    if not expected or hashlib.sha256(data).hexdigest()!=expected:
        raise ValueError('Tunnel download checksum did not match the official release.')
    target = Path(target).resolve()
    target.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for info in archive.infolist():
            path = (target/info.filename).resolve()
            if not path.is_relative_to(target) or ':' in info.filename or '\\' in info.filename:
                raise ValueError('Invalid path inside tunnel download.')
            if info.is_dir(): path.mkdir(parents=True,exist_ok=True)
            else:
                path.parent.mkdir(parents=True,exist_ok=True)
                path.write_bytes(archive.read(info))
    matches = [p for p in target.rglob('tunnel-client.exe') if p.is_file()]
    if len(matches)!=1: raise ValueError('The download did not contain one Windows tunnel-client.exe.')
    return matches[0]


def fetch(url):
    request = urllib.request.Request(url,headers={'User-Agent':'SoftenantVideoStudio/0.2'})
    with urllib.request.urlopen(request,timeout=60) as response: return response.read()


def install_client(cache):
    print('Checking the official OpenAI tunnel-client release…')
    release = json.loads(fetch(RELEASES))
    assets = release['assets']
    asset = next(a for a in assets if re.fullmatch(r'tunnel-client-v[\w.\-]+-windows-amd64\.zip',a['name']))
    sums = next(a for a in assets if a['name']=='SHA256SUMS.txt')
    target = cache/'client'/release['tag_name']
    # Verify cached executables against a digest retained after official ZIP validation.
    marker = target/'verified-client.json'
    if marker.is_file():
        try:
            info = json.loads(marker.read_text())
            exe = (target/info['path']).resolve()
            if exe.is_relative_to(target.resolve()) and hashlib.sha256(exe.read_bytes()).hexdigest()==info['sha256']:
                return exe
        except (ValueError,OSError,KeyError): pass
    print('Downloading the Windows tunnel client…')
    exe = unpack_verified(fetch(asset['browser_download_url']),fetch(sums['browser_download_url']).decode(),asset['name'],target)
    marker.write_text(json.dumps({'path':exe.relative_to(target.resolve()).as_posix(),
                                 'sha256':hashlib.sha256(exe.read_bytes()).hexdigest()}))
    return exe


def check_service():
    # The endpoint is fixed loopback; never send this local health check through an external proxy.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    payload = {'jsonrpc':'2.0','id':1,'method':'initialize','params':{
        'protocolVersion':'2025-06-18','capabilities':{},'clientInfo':{'name':'softenant-setup','version':'0.2.0'}}}
    request = urllib.request.Request('http://127.0.0.1:8765/mcp',data=json.dumps(payload).encode(),
                                    headers={'Content-Type':'application/json','Accept':'application/json, text/event-stream'})
    try:
        with opener.open(request,timeout=5) as response: data = json.load(response)
        if data['result']['serverInfo']['name']!='Softenant Video Studio': raise ValueError('Unexpected local service.')
    except Exception as error:
        raise ValueError('First open Start-MCP.bat and leave it running, then run Connect-ChatGPT.bat.') from error


def main():
    if os.name!='nt':
        print('This connection wizard is intended for Windows. See MCP-SETUP.md for other clients.')
        return 1
    key = None
    child_env = None
    try:
        check_service()
        cache = Path(os.environ.get('LOCALAPPDATA',str(Path.home())))/'Softenant'/'VideoStudioTunnel'
        cache.mkdir(parents=True,exist_ok=True)
        exe = install_client(cache)
        print('\nCreate or select a tunnel at:')
        print('https://platform.openai.com/settings/organization/tunnels')
        print('Associate it with the ChatGPT workspace you use. You need Tunnels Read + Use to run it.')
        metadata = cache/'connection.json'
        previous = json.loads(metadata.read_text()) if metadata.is_file() else {}
        saved_id = previous.get('tunnel_id','')
        id_ = input(f'Tunnel ID [{saved_id}]: ').strip() or saved_id
        if not re.fullmatch(r'tunnel_[A-Za-z0-9_-]{8,100}',id_): raise ValueError('Enter the tunnel ID from Platform settings.')
        print('Create a runtime API key at https://platform.openai.com/settings/organization/api-keys')
        key = getpass.getpass('Runtime API key (hidden; not saved): ').strip()
        if not key: raise ValueError('A runtime API key is required by OpenAI Secure MCP Tunnel.')
        child_env = os.environ.copy()
        child_env['CONTROL_PLANE_API_KEY'] = key
        profile = previous.get('profile') if saved_id==id_ else None
        if not profile:
            # Fresh name avoids replacing any existing tunnel profile.
            import secrets
            profile = 'softenant-video-'+secrets.token_hex(4)
            subprocess.run([str(exe),'init','--sample','sample_mcp_remote_no_auth','--profile',profile,
                            '--tunnel-id',id_,'--mcp-server-url','http://127.0.0.1:8765/mcp'],env=child_env,check=True)
            metadata.write_text(json.dumps({'tunnel_id':id_,'profile':profile},indent=2))
        subprocess.run([str(exe),'doctor','--profile',profile,'--explain'],env=child_env,check=True)
        print('\nKeep this window and the MCP service running.')
        print('In ChatGPT: Plugins > + > Connection: Tunnel. Select or paste: '+id_)
        print('Use the name Softenant Video Studio, then start a new chat and select the plugin.')
        return subprocess.call([str(exe),'run','--profile',profile],env=child_env)
    except KeyboardInterrupt:
        print('\nTunnel stopped.')
        return 0
    except Exception as error:
        # Do not include subprocess environment or key values in failure details.
        print(f'Connection setup could not finish: {error}',file=sys.stderr)
        return 1
    finally:
        if child_env: child_env.pop('CONTROL_PLANE_API_KEY',None)
        key = None
