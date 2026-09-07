@echo off
setlocal
cd /d "%~dp0"
if exist "MCP\SoftenantStudioMCP.exe" (
  "MCP\SoftenantStudioMCP.exe" %*
) else (
  if not exist ".venv\Scripts\python.exe" (
    echo Run Setup-MCP-Windows.bat first, or download the complete portable package.
    pause
    exit /b 1
  )
  .venv\Scripts\python.exe mcp_main.py %*
)
if errorlevel 1 pause
