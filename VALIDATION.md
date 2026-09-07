# Validation — 7 September 2026

## Completed locally

**16 automated tests passed** on Python 3.12 / Linux, using the bundled imageio-ffmpeg encoder and PySide6 with an offscreen Qt platform.

- Project save/load with relative media paths, undo/redo, invalid value rejection.
- Splitting at non-unit speed and X/Y motion continuity; SRT import/export round trips.
- Real MP4 exports with transparent logos, multiple video layers, title overlays, source audio and an additional audio track.
- Source trimming and speeds 0.25×, 0.5×, 2× and 4×, checked against exported duration.
- Timeline gaps, fades, brightness/contrast/saturation, rotation, crop, blur, green screen and motion.
- Source-file protection; cancelled/failed renders preserve an existing export destination.
- Draft preview duration and audio-only projects.
- Inspector changes, timeline split, undo/redo, autosave and project saving through Qt widgets.
- Visible timeline scrollbar and both-direction scrolling on smaller windows; recording dialog initialization.
- Windows capture command construction, including negative monitor coordinates and microphone selection.
- Actual recording process start/stop and MP4 finalization using a synthetic live video source.

The application screenshot was visually inspected. This caught and fixed a blank canvas-size selector. Export pixel checks caught and fixed a green-screen alpha bug affecting transparent PNG logos.

## Windows build

The GitHub Actions workflow runs the same tests on Windows, packages a portable EXE, and smoke-tests packaged startup. Check the current Actions run for its result. A successful automated build does not establish physical monitor/microphone capture quality or playback performance.

## Still requires manual validation

- Real Windows monitor capture, microphone capture, mixed-DPI/multiple-monitor setups and playback on the user's hardware.
- Optional Whisper model download and end-to-end automatic transcription.
- Long projects, large numbers of concurrent layers/subtitles and 4K throughput.
- Third-party LUT varieties and multilingual font shaping.

CPU encoding and rendered previews are implemented. GPU export, live composited previews, system-audio capture and a standalone voice-only recorder are not implemented.


## Version 0.2 MCP integration

32 automated tests pass locally after the MCP update. Added checks cover 24-tool discovery and real calls through stdio and Streamable HTTP, structured responses, unsupported operations, hostile Origin rejection, path traversal and embedded project-path restrictions, disguised playlist rejection, opt-in recording, revision checks, undo protection across external edits, GUI refresh/conflict behavior, and verified tunnel ZIP extraction. The existing real video/audio export and screen-recording process tests remain in the suite.

The updated Windows workflow repeats all tests, builds both the editor and MCP executable, starts the GUI, and verifies the frozen MCP server by initializing it, listing tools and creating a project through its stdio transport.

OpenAI tunnel account association, runtime-key permissions and end-to-end calls from the user's ChatGPT account to their physical Windows PC cannot be verified from this cloud workspace. The connection wizard and MCP-SETUP.md complete the handoff for that local step. No tunnel credentials or registered account connection were created here.
