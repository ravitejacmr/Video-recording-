# Use Softenant Video Studio from ChatGPT Work

Version 0.2 adds **24 MCP tools** to the Windows editor. You can create projects, add video/music/images, trim and split, control audio/effects, add text and SRT subtitles, undo/redo, render previews, inspect a preview frame inside chat, export MP4 and control screen recording.

The code and Windows packages are ready for local setup. **The plugin is not connected to your PC until you run the service and register its tunnel in your own ChatGPT account.**

## Windows setup — portable package

1. Download the newest successful **SoftenantVideoStudio-Windows-x64** artifact from this repository's Actions page and extract the entire ZIP.
2. Open **Start-MCP.bat**. To enable screen/microphone tools, use **Start-MCP-With-Recording.bat** instead. Keep this window open.
3. In the editor, use **File → Open MCP workspace**. Put the videos, music, logos, SRT files, fonts or LUTs you want ChatGPT to use inside **Media**. The default workspace is `%USERPROFILE%\Documents\SoftenantStudio`.
4. Open **Connect-ChatGPT.bat**. The wizard downloads the official Windows OpenAI tunnel client and checks the release SHA-256 checksum.
5. The wizard shows links to [Platform tunnel settings](https://platform.openai.com/settings/organization/tunnels) and [runtime API keys](https://platform.openai.com/settings/organization/api-keys). Create/select your tunnel and associate it with your ChatGPT workspace. Enter its tunnel ID and runtime key **in the local wizard**. The key is hidden while typing and is not saved by this app. Do not paste it into chat or GitHub.
6. Keep the connection window running. In **ChatGPT → Plugins → +**, choose **Tunnel** under Connection and select/paste your tunnel ID. Name the connection **Softenant Video Studio** and create it.
7. Start a new chat, select the plugin, and ask: **“List my media and create a video project.”**

The PC must be on, awake and connected. The service binds only to `127.0.0.1:8765`; do not publish that unauthenticated local port. The official tunnel handles the authenticated private connection. The MCP service has no public endpoint and this package is not a public plugin-directory submission.

OpenAI requires a runtime API key plus tunnel permissions for this connection; ChatGPT developer-mode access is separate. Creating/managing a tunnel needs **Tunnels Read + Manage**; running/using it needs **Tunnels Read + Use**. Developer mode and tunnel access depend on your account/workspace. If the Tunnel option is unavailable, use the local Codex plugin option below or resolve access with your workspace/Platform administrator. The wizard cannot grant these permissions.

Official references: [Secure MCP Tunnel](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels), [connect and test a plugin](https://developers.openai.com/plugins/deploy/connect-chatgpt).

## Use it

Example requests:

- “Show the video and audio files in my Media folder.”
- “Create a 1080p project and add classroom.mp4. Remove its first 10 seconds.”
- “Add music.mp3 on Audio 1 at 20% volume and fade it out over two seconds.”
- “Put our logo on Video 2, small, near the top-right.”
- “Add the title Softenant Technologies for five seconds.”
- “Render a preview and show me a frame.”
- “Export the video and check its progress.”
- “List my monitors and microphones, then record monitor 0 for at most five minutes.”
- “Stop the recording and add the saved clip to my project.”
- “Open this project in the Windows editor.”

Tracks: **V1=0, V2=1, A1=2, A2=3, Titles=4**. Times use seconds. Volume `0.2` means 20%; `1` means original volume.

MCP edits automatically save under **Projects**. Exports use unique filenames under **Exports**. Open a plugin-created project through **File → Open MCP project** or the `open_project_in_editor` tool. The GUI refreshes saved MCP changes every two seconds while there are no unsaved local edits. If both sides edit, revision checks prevent silently overwriting the other side. Reopen the saved project, or save local changes as another project.

Use the latest `revision` returned by `get_project` for each editing/export call. Every successful edit returns a new revision. Undo/redo covers up to 50 MCP edits in the current service session. Render jobs and their IDs last for that service session; completed MP4 files remain on disk.

Screen recording requires the recording-enabled launcher and an interactive Windows desktop. Microphone selection is optional; system audio and webcam capture are not implemented. A recording auto-stops after its requested limit (1–60 minutes). The local console displays recording status. Stop recording before closing the service or signing out.

Automatic Whisper transcription remains an optional editor feature; the MCP toolset imports SRT subtitles and does not run Whisper itself. The chat can inspect JPEG preview frames; there is no embedded live video editor/player in the plugin.

## Run from source

Install Python 3.12 x64, run **Setup-MCP-Windows.bat**, then follow the same service/wizard steps above. The regular **Setup-Windows.bat** installs only the editor dependencies.

For a custom media location, set `SOFTENANT_WORKSPACE` in the local environment before starting both the editor and MCP service, or pass `--workspace` to the service. Do not point it at a whole drive. Media must remain within its **Media** subfolder, including files referenced by imported project JSON.

## Local Codex plugin

`plugins/softenant-video-studio` contains a validated plugin manifest and `.mcp.json` for a **local desktop Codex client** on the same Windows PC. Its URL is `http://127.0.0.1:8765/mcp`. Start the MCP service before loading this plugin in a client that supports local/repository plugins. This loopback manifest cannot connect ChatGPT Work on the web to your PC; use the tunnel flow for web/mobile Work.

No registered connection ID is embedded in `.app.json`: registration belongs to your account and must happen after the Windows tunnel is running. Once registered, the MCP-only personal plugin can be selected in ChatGPT without a custom UI.

## Tests and troubleshooting

Run `python -m pytest -q` after installing `requirements-mcp.txt`. Tests cover real MCP initialization, discovery/calls over stdio and HTTP, structured outputs, scope enforcement, blocked traversal, disabled recording, stale-write protection, media edits and export.

- **Connection refused:** open Start-MCP.bat and keep it running.
- **Port already in use:** stop the older MCP service before starting another.
- **Tunnel not listed:** verify the ChatGPT workspace association and Tunnels Read + Use permissions.
- **No media:** copy files into the Media folder shown by `studio_status`.
- **Project changed:** call get_project again and use the fresh revision.
- **Recording disabled:** restart with Start-MCP-With-Recording.bat.
- **Recording cannot find screen/mic:** run in your signed-in Windows desktop and check microphone permissions.
- **Wizard download blocked:** obtain the Windows tunnel client from the official release linked by the tunnel documentation and configure it manually using its `help quickstart` instructions. Do not disable security controls to install it.

The wizard's nonsecret tunnel ID/profile information is stored under local app data, outside the project. It checks the latest official tunnel-client release each time. It needs internet and your runtime key each session. No OAuth server or public hosting is included; authenticated connectivity is provided by Secure MCP Tunnel.
