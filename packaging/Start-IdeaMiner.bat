@echo off
setlocal
set "IDEAMINER_DB=%LOCALAPPDATA%\IdeaMiner\data\ideaminer.db"
set "PYTHON=%~dp0runtime\python.exe"
set "PYTHONPATH=%~dp0;%~dp0runtime\site-packages"

if not exist "%PYTHON%" (
  echo IdeaMiner's private Python environment is missing. Run Update-IdeaMiner.bat to repair it.
  pause
  exit /b 1
)

"%PYTHON%" "%~dp0launcher.py"
if errorlevel 1 pause