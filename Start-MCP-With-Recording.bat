@echo off
cd /d "%~dp0"
echo Screen and microphone recording tools will be available in this session.
echo Recording starts only when requested through the connected plugin.
call Start-MCP.bat --allow-recording
