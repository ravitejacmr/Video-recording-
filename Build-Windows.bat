@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Run Setup-Windows.bat first.
  pause
  exit /b 1
)
.venv\Scripts\python.exe -m pip install pyinstaller==6.16.0
if errorlevel 1 goto failed
.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --windowed --onedir --name SoftenantVideoStudio --collect-all imageio_ffmpeg main.py
if errorlevel 1 goto failed
echo Build complete: dist\SoftenantVideoStudio\SoftenantVideoStudio.exe
echo Keep the entire SoftenantVideoStudio folder together.
pause
exit /b 0
:failed
echo Build failed. Review the error above.
pause
exit /b 1
