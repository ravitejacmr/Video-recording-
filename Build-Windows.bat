@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Run Setup-Windows.bat first.
  pause
  exit /b 1
)
.venv\Scripts\python.exe -m pip install -r requirements-mcp.txt pyinstaller==6.16.0
if errorlevel 1 goto failed
.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --windowed --onedir --name SoftenantVideoStudio --collect-all imageio_ffmpeg main.py
if errorlevel 1 goto failed
.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --console --onedir --name SoftenantStudioMCP --collect-all imageio_ffmpeg --collect-data mcp --copy-metadata mcp --collect-submodules uvicorn --hidden-import anyio._backends._asyncio mcp_main.py
if errorlevel 1 goto failed
.venv\Scripts\python.exe scripts\smoke_mcp_exe.py dist\SoftenantStudioMCP\SoftenantStudioMCP.exe
if errorlevel 1 goto failed
xcopy /e /i /y dist\SoftenantStudioMCP dist\SoftenantVideoStudio\MCP >nul
copy /y Start-MCP.bat dist\SoftenantVideoStudio >nul
copy /y Start-MCP-With-Recording.bat dist\SoftenantVideoStudio >nul
copy /y Connect-ChatGPT.bat dist\SoftenantVideoStudio >nul
copy /y MCP-SETUP.md dist\SoftenantVideoStudio >nul
echo Build complete: dist\SoftenantVideoStudio\SoftenantVideoStudio.exe
echo Keep the entire SoftenantVideoStudio folder together.
pause
exit /b 0
:failed
echo Build failed. Review the error above.
pause
exit /b 1
