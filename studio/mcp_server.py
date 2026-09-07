"""MCP transport: loopback Streamable HTTP or stdio behind Secure MCP Tunnel."""
from __future__ import annotations
from typing import Any
import argparse
import json
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from mcp.server.fastmcp import FastMCP, Image
from mcp.types import ToolAnnotations
from .mcp_service import StudioService, workspace_path

INSTRUCTIONS = ('Use list_media and list_projects first. Read get_project before changes and pass its revision. '
                'All media paths are relative to the dedicated workspace; no arbitrary file access. '
                'Tracks: 0=V1,1=V2,2=A1,3=A2,4=Titles. Poll get_job after preview/export; use get_preview_frame '
                'to inspect results. Only start screen/microphone capture when the user explicitly requests it. '
                'The PC must remain awake and the service running.')


def build_server(service,port=8765):
    @asynccontextmanager
    async def lifespan(server):
        try: yield {}
        finally: service.close()
    server = FastMCP('Softenant Video Studio',instructions=INSTRUCTIONS,
                     host='127.0.0.1',port=port,json_response=True,stateless_http=True,
                     max_request_body_size=262144,lifespan=lifespan)
    read = ToolAnnotations(readOnlyHint=True,destructiveHint=False,idempotentHint=True,openWorldHint=False)
    write = ToolAnnotations(readOnlyHint=False,destructiveHint=False,idempotentHint=False,openWorldHint=False)
    remove = ToolAnnotations(readOnlyHint=False,destructiveHint=True,idempotentHint=False,openWorldHint=False)
    capture = ToolAnnotations(readOnlyHint=False,destructiveHint=False,idempotentHint=False,openWorldHint=True)

    @server.tool(annotations=read)
    def studio_status() -> dict[str, Any]:
        """Get connection status, the Windows workspace location, and recording availability."""
        return {'status':'ready','version':'0.2.0','workspace':str(service.root),
                'recording_enabled':service.allow_recording,'media_folder':'Media',
                'projects_folder':'Projects','exports_folder':'Exports'}

    @server.tool(annotations=read)
    def list_media(offset: int=0,limit: int=100) -> dict[str, Any]:
        """List videos, audio, logos, SRT, fonts and LUTs the user placed in the workspace Media folder."""
        return service.list_media(offset,limit)

    @server.tool(annotations=read)
    def list_projects() -> dict[str, Any]:
        """Find projects available to this plugin. Returns stable project IDs."""
        return service.list_projects()

    @server.tool(annotations=read)
    def get_project(project_id: str) -> dict[str, Any]:
        """Inspect timeline clips and revision before editing. Use this revision in the next mutation."""
        return service.get_project(project_id)

    @server.tool(annotations=write)
    def open_project_in_editor(project_id: str) -> dict[str, Any]:
        """Open the saved project in the Windows editor. Saved MCP changes refresh there unless local edits are unsaved."""
        return service.open_in_editor(project_id)

    @server.tool(annotations=write)
    def create_project(name: str,width: int=1920,height: int=1080,fps: int=30) -> dict[str, Any]:
        """Create and save a new empty project. Supports even canvas sizes up to 4096 and 24/25/30/60fps."""
        return service.create_project(name,width,height,fps)

    @server.tool(annotations=write)
    def add_media_clip(project_id: str,expected_revision: str,media_path: str,start: float=0,
                       track: int=0,source_in: float=0,source_out: float | None=None) -> dict[str, Any]:
        """Add an existing workspace video, audio or image. Use tracks 2/3 for audio, 0/1 for video or logos. Times are seconds."""
        return service.add_media(project_id,expected_revision,media_path,start,track,source_in,source_out)

    @server.tool(annotations=write)
    def add_title(project_id: str,expected_revision: str,text: str,start: float=0,duration: float=5) -> dict[str, Any]:
        """Add a title or subtitle to the top track. Style and position it with update_clip."""
        return service.add_title(project_id,expected_revision,text,start,duration)

    @server.tool(annotations=write)
    def update_clip(project_id: str,expected_revision: str,clip_id: str,changes: dict) -> dict[str, Any]:
        """Edit clip fields: source_in/out, start, track, speed(.25–4), volume(0–4), muted, fade_in/out,
        scale(.05–2), x/y(-2–2 canvas fractions), animate, end_x/y, opacity(0–1), rotation(0/90/180/270),
        crop(0–.45), brightness(-1–1), contrast/saturation(0–3), blur(0–20), chroma, key_color(#RRGGBB),
        similarity(.01–1), lut/font(workspace Media paths), text, font_size(8–240), color and text_box.
        Cannot change clip ID, kind or source path. Every change is validated and saved atomically."""
        return service.update_clip(project_id,expected_revision,clip_id,changes)

    @server.tool(annotations=write)
    def split_clip(project_id: str,expected_revision: str,clip_id: str,timeline_seconds: float) -> dict[str, Any]:
        """Split a clip at a project timeline time, preserving source trim and playback speed."""
        return service.split(project_id,expected_revision,clip_id,timeline_seconds)

    @server.tool(annotations=remove)
    def remove_clip(project_id: str,expected_revision: str,clip_id: str) -> dict[str, Any]:
        """Remove a clip from the timeline. The original media file remains intact. Can be undone this session."""
        return service.remove(project_id,expected_revision,clip_id)

    @server.tool(annotations=write)
    def set_project_settings(project_id: str,expected_revision: str,width: int,height: int,fps: int=30) -> dict[str, Any]:
        """Change output resolution and frame rate, including portrait and 4K."""
        return service.settings(project_id,expected_revision,width,height,fps)

    @server.tool(annotations=write)
    def import_subtitles(project_id: str,expected_revision: str,media_path: str) -> dict[str, Any]:
        """Import an SRT from the Media folder as editable text clips. Timestamps use project time zero."""
        return service.captions(project_id,expected_revision,media_path)

    @server.tool(annotations=write)
    def undo_edit(project_id: str,expected_revision: str) -> dict[str, Any]:
        """Undo the most recent MCP edit in this service session (up to 50 steps)."""
        return service.undo(project_id,expected_revision)

    @server.tool(annotations=write)
    def redo_edit(project_id: str,expected_revision: str) -> dict[str, Any]:
        """Redo the most recently undone MCP edit in this service session."""
        return service.undo(project_id,expected_revision,True)

    @server.tool(annotations=write)
    def render_preview(project_id: str,expected_revision: str,start: float=0,length: float=12) -> dict[str, Any]:
        """Start a draft preview render (up to 60 seconds). Returns a job ID; poll get_job until completed."""
        return service.render(project_id,expected_revision,True,start,length)

    @server.tool(annotations=write)
    def export_video(project_id: str,expected_revision: str) -> dict[str, Any]:
        """Start H.264/AAC MP4 export to a new file under Exports. Returns a job ID; poll get_job."""
        return service.render(project_id,expected_revision)

    @server.tool(annotations=read)
    def get_job(job_id: str) -> dict[str, Any]:
        """Read rendering progress, completion, output path or failure. Jobs persist for the service session."""
        return service.job_status(job_id)

    @server.tool(annotations=write)
    def cancel_job(job_id: str) -> dict[str, Any]:
        """Request cancellation of a render. Poll get_job until status is cancelled or completed."""
        return service.cancel(job_id)

    @server.tool(annotations=read,structured_output=False)
    def get_preview_frame(job_id: str,seconds: float=0) -> Image:
        """Return a JPEG frame from a completed preview/export for visual inspection inside chat."""
        return Image(data=service.preview_frame(job_id,seconds),format='jpeg')

    @server.tool(annotations=read)
    def list_recording_devices() -> dict[str, Any]:
        """List Windows monitors and microphones when recording has been enabled locally."""
        return service.recording_devices()

    @server.tool(annotations=capture)
    def start_screen_recording(monitor_id: int,microphone_id: int | None=None,max_minutes: int=10) -> dict[str, Any]:
        """Start recording a Windows monitor, optionally with microphone. Requires an explicit user request
        and the recording-enabled local launcher. Auto-stops after max_minutes (1–60). No system audio.
        Returns recording_id. Use stop_screen_recording to finish, then add its Media path to a project."""
        return service.start_recording(monitor_id,microphone_id,max_minutes)

    @server.tool(annotations=read)
    def get_recording_status() -> dict[str, Any]:
        """Read current recording status and, after completion, its workspace Media path."""
        return service.recording_status()

    @server.tool(annotations=write)
    def stop_screen_recording(recording_id: str) -> dict[str, Any]:
        """Stop and finalize screen/microphone recording. Poll status until completed before importing."""
        return service.stop_recording(recording_id)

    return server


def main():
    parser = argparse.ArgumentParser(description='Softenant Video Studio MCP service')
    parser.add_argument('--stdio',action='store_true',help='Use stdio instead of loopback HTTP')
    parser.add_argument('--workspace',type=Path,default=workspace_path())
    parser.add_argument('--port',type=int,default=8765)
    parser.add_argument('--allow-recording',action='store_true')
    parser.add_argument('--check',action='store_true',help='Check server creation without listening')
    args = parser.parse_args()
    if not 1024<=args.port<=65535: parser.error('Port must be 1024–65535.')
    service = StudioService(args.workspace,args.allow_recording)
    server = build_server(service,args.port)
    if args.check:
        print(json.dumps({'status':'ready','workspace':str(service.root)}))
        service.close()
        return 0
    print(f'Softenant MCP ready. Workspace: {service.root}',file=sys.stderr)
    print('Recording enabled.' if args.allow_recording else 'Recording disabled. Use --allow-recording to enable locally.',file=sys.stderr)
    if not args.stdio:
        print(f'Local endpoint: http://127.0.0.1:{args.port}/mcp — connect through Secure MCP Tunnel, not a public port.',file=sys.stderr)
    try:
        server.run(transport='stdio' if args.stdio else 'streamable-http')
    finally:
        service.close()
    return 0
