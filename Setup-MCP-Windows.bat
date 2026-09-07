@echo off
setlocal
cd /d "%~dp0"
py -3.12 -c "import sys; assert sys.maxsize > 2**32" >nul 2>&1
if errorlevel 1 (
  echo Install Python 3.12, 64-bit, with the Python launcher first.
  pause
  exit /b 1
)
if not exist ".venv\Scripts\python.exe" (
  py -3.12 -m venv .venv
  if errorlevel 1 goto failed
)
.venv\Scripts\python.exe -m pip install -r requirements-mcp.txt
if errorlevel 1 goto failed
.venv\Scripts\python.exe mcp_main.py --check
if errorlevel 1 goto failed
echo Setup complete. Open Start-MCP.bat, then Connect-ChatGPT.bat.
pause
exit /b 0
:failed
echo MCP setup failed. Check the message above.
pause
exit /b 1
