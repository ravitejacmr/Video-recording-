@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Run Setup-Windows.bat first. Optional captions use the source launcher.
  pause
  exit /b 1
)
.venv\Scripts\python.exe -m pip install faster-whisper==1.2.1
if errorlevel 1 (
  echo Installation failed. Review the error above.
  pause
  exit /b 1
)
echo Captions enabled. Open Start-Editor.bat, select a clip, then Edit / Automatic captions.
echo The first transcription downloads the Whisper base model. Later runs use the cached model.
pause
