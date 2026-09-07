# Softenant Video Studio

A Windows desktop video editor built for layered course videos, promotional clips and social posts. **Version 0.2.0 is an early working release**, with a native Qt interface and an FFmpeg rendering engine.

## ChatGPT Work plugin / MCP

Version 0.2 adds 24 MCP tools for video/audio editing, previews, export and optional recording. See [MCP-SETUP.md](MCP-SETUP.md). The updated portable package includes the MCP service and connection wizard. Final connection requires setup on your Windows PC and your OpenAI tunnel credentials.

## Start on Windows

**Portable application (when the GitHub build is green):**

1. Open this repository's **Actions → Windows editor build**.
2. Open the latest successful run and download **SoftenantVideoStudio-Windows-x64** under Artifacts. GitHub sign-in is required to download artifacts.
3. Extract the ZIP completely and open **SoftenantVideoStudio.exe**. Keep its `_internal` folder alongside the EXE. No separate Python installation is needed for this build.

**Run from source:**

1. Install **Python 3.12, 64-bit** from [python.org](https://www.python.org/downloads/windows/), including its Python launcher.
2. Download this repository using **Code → Download ZIP**, then extract it.
3. Double-click **Setup-Windows.bat** once. Setup downloads dependencies, including FFmpeg.
4. Double-click **Start-Editor.bat**.

Internet is required for setup. Standard editing and export run locally after setup. Automatic captions are optional and download a model on first use.

## Make your first edit

1. Click **Import video / audio / image**. Videos append on V1. Audio and images begin at the playhead.
2. Select a clip. In **Timing**, enter source in/out times, timeline start, speed, volume and fades. Click **Apply clip changes**.
3. Click the timeline ruler to position the playhead. Use **Split**, **Duplicate**, **Delete**, **Undo** and **Redo**.
4. Drag a clip horizontally to change its start, or vertically to another compatible track. Moves snap to a frame. Empty spaces render black/silent; deleting does not ripple later clips.
5. Put a second video or logo on **V2**. Reduce **Scale** to make picture-in-picture; adjust X/Y to position it. X/Y are fractions of canvas size; `(0, 0)` is centred.
6. Use **Animate X/Y** and end X/Y values for linear motion between the clip's start and end. Scale, rotation and opacity are static controls in this release.
7. Apply colour controls, a `.cube` LUT, blur or green screen. Crop removes the same fraction from all four edges. Rotation supports 90-degree increments.
8. Add a title or import SRT captions. Text uses a lower-centre layout by default. Change its font, size, colour, background and position in the inspector.
9. Click **Render 12-second preview** to preview the edited region starting at the playhead. **Play selected source** plays original media and does not show effects.
10. Choose landscape, portrait, square or 4K; select 24/25/30/60 fps; click **Export MP4**.

### Tracks and transitions

There are two video tracks, two audio tracks and a top title track. Visual order is V1 → V2 → Titles. Later clips on the same track appear above earlier clips while they overlap. All audible clips mix together, with a limiter to reduce clipping.

Use clip fade-in/out controls for fades to/from black or transparency. For a dissolve, overlap a V2 clip with a V1 clip and fade V2 in or out. Audio fades follow the same durations. There is no one-click transition library yet.

### Screen recording and audio

Click **Record screen** (or Ctrl+R), choose a monitor and optionally a microphone, then choose a new MP4 filename. Press **Stop and add to timeline** to finish and import the recording onto V1. You can minimize the recording dialog while recording. Recording captures the chosen monitor, including visible windows and the mouse pointer.

The recorder uses Windows desktop capture and a software H.264 encoder. Choose 1080p, 720p or native size. Microphone audio is supported; system/desktop audio and webcam capture are not included. A real Windows desktop session is required.

Use **Import media** for MP3, WAV, M4A, AAC, FLAC and OGG audio. Audio clips have two dedicated tracks (A1/A2), independent positioning, trimming, speed, volume, mute and fades. For a repeating music bed, duplicate the music clip. Recording captures microphone narration along with the screen; voice-only recording is not yet a separate mode.

The timeline has a visible horizontal scrollbar. Inspector tabs scroll vertically, and the whole editor scrolls horizontally/vertically when the window is too small.

### Captions

- Import and export `.srt` files from the File menu. SRT times refer to project time zero. Export includes every text clip.
- For optional automatic speech captions, run **Enable-Auto-Captions.bat**, restart with **Start-Editor.bat**, select a video/audio clip and choose **Edit → Automatic captions**.
- Automatic captions use the local Whisper base model on CPU. First use downloads the model; the optional caption package is not bundled in the portable EXE. Review spelling and timing before export. Choose a compatible custom font for Telugu or other scripts.

### Projects and recovery

Projects use readable `.svs` JSON and store paths relative to the project where possible. Keep your original media. Saving a project does not embed or copy videos. Use **Relink selected media** when files move. Autosave runs every 30 seconds into the Windows app-data folder; the next launch offers recovery after an unexpected exit.

Undo/redo retains up to 100 editing operations in the current session. Use **Ctrl+S** to save, **Ctrl+B** to split, **Ctrl+D** to duplicate and **Ctrl+E** to export.

### Export behaviour

MP4 output uses H.264 video and AAC stereo audio. Export uses CPU encoding, with fixed CRF 20 quality. Source files are read-only to the renderer. A cancelled or failed render leaves an existing destination intact; successful export replaces a destination the user selected. Output is staged beside the destination, so allow room for an additional copy during rendering.

## Current limits

- This is an early editor, not a full Premiere/Resolve replacement.
- Composited previews render first at draft resolution; there is no real-time multitrack playback, waveform view, proxy manager, GPU export or hardware performance validation.
- Keyframes currently support two-point linear X/Y movement. Animated scale/rotation/opacity and curve editing are future work.
- Basic fades and overlapping-layer dissolves are available. No transition/effect preset library or motion tracking is included.
- No standalone voice-only recorder, audio denoising, beat detection or automatic background removal is included.
- Long projects and many simultaneous inputs/subtitles increase memory and rendering time. 4K export is supported by the settings/renderer but has not been performance-tested on a user's Windows PC.
- The portable application is unsigned. Automatic captions require the source launcher and optional installation.
- See [VALIDATION.md](VALIDATION.md) for the checks actually performed and outstanding Windows checks.

## Development

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt pytest==8.4.2
.venv\Scripts\python -m pytest -q
.venv\Scripts\python main.py
```

Double-click **Build-Windows.bat** to build the portable EXE locally. GitHub Actions tests the model, real video exports and the interface on Windows, then packages and smoke-tests the EXE.

Architecture: `studio/model.py` (project/history), `engine.py` (compositor), `timeline.py` (timeline canvas), `app.py` (UI/background tasks), `captions.py` (subtitle interchange and optional transcription).

Reference documentation: [Qt media player](https://doc.qt.io/qtforpython-6/PySide6/QtMultimedia/QMediaPlayer.html), [FFmpeg filters](https://ffmpeg.org/ffmpeg-filters.html), [imageio-ffmpeg](https://github.com/imageio/imageio-ffmpeg), [faster-whisper](https://github.com/SYSTRAN/faster-whisper). Third-party components retain their own licenses; see [THIRD_PARTY.md](THIRD_PARTY.md).
