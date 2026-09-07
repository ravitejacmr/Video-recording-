@echo off
setlocal
cd /d "%~dp0"
py -3.12 -c "import sys; assert sys.maxsize > 2**32" >nul 2>&1
if errorlevel 1 (
  echo Install Python 3.12, 64-bit, from https://www.python.org/downloads/windows/
  echo Include the Python launcher during installation, then run this file again.
  pause
  exit /b 1
)
if not exist ".venv\Scripts\python.exe" (
  py -3.12 -m venv .venv
  if errorlevel 1 goto failed
)
.venv\Scripts\python.exe -m pip install --upgrade pip
if errorlevel 1 goto failed
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto failed
.venv\Scripts\python.exe -c "from studio.engine import ffmpeg_path; from studio.app import MainWindow; print('Ready:', ffmpeg_path())"
if errorlevel 1 goto failed
echo.
echo Setup complete. Double-click Start-Editor.bat to open Softenant Video Studio.
pause
exit /b 0
:failed
echo Setup failed. Review the error above and check your internet connection.
pause
exit /b 1
