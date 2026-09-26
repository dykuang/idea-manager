@echo off
setlocal
set "INSTALLER=%TEMP%\IdeaMiner-Install.ps1"
set "CUSTOM_ROOT=%~1"

powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; [Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -UseBasicParsing -Uri 'https://raw.githubusercontent.com/dykuang/idea-manager/main/packaging/Install-IdeaMiner.ps1' -OutFile '%TEMP%\IdeaMiner-Install.ps1'"
if errorlevel 1 goto failed

if "%CUSTOM_ROOT%"=="" (
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%INSTALLER%"
) else (
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%INSTALLER%" -InstallRoot "%CUSTOM_ROOT%"
)
if errorlevel 1 goto failed
exit /b 0

:failed
echo IdeaMiner could not be installed. Check your internet connection and try again.
pause
exit /b 1