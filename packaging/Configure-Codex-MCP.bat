@echo off
setlocal
set "PYTHON=%~dp0runtime\python.exe"
set "MCP_ENTRY=%~dp0ideaminer_mcp.py"
set "PYTHONPATH=%~dp0;%~dp0runtime\site-packages"

where codex >nul 2>&1
if errorlevel 1 goto missing_codex
if not exist "%PYTHON%" goto missing_python

codex mcp add ideaminer -- "%PYTHON%" "%MCP_ENTRY%"
if errorlevel 1 goto configure_failed
echo IdeaMiner MCP is connected to Codex.
pause
exit /b 0

:missing_codex
echo Codex CLI was not found. Install Codex CLI, then run this helper again.
goto failed

:missing_python
echo IdeaMiner's private Python environment was not found. Run Update-IdeaMiner.bat first.
goto failed

:configure_failed
echo Codex could not add the MCP server. If it is already configured, run "codex mcp remove ideaminer" and try again.

:failed
pause
exit /b 1