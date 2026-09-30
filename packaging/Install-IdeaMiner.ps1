[CmdletBinding()]
param(
    [string]$PackageUrl = 'https://github.com/dykuang/idea-manager/releases/latest/download/ideaminer-windows.zip',
    [string]$PythonVersion = '3.12.10',
    [string]$InstallRoot = '',
    [switch]$LaunchAfterUpdate
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

if (-not $env:LOCALAPPDATA) { throw 'This installer requires a Windows user account with Local AppData.' }

$installRoot = if ($InstallRoot.Trim()) { [Environment]::ExpandEnvironmentVariables($InstallRoot).TrimEnd('\') } else { Join-Path $env:LOCALAPPDATA 'Programs\IdeaMiner' }
$appRoot = Join-Path $installRoot 'app'
$work = Join-Path ([System.IO.Path]::GetTempPath()) ("ideaminer-install-" + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $work -Force | Out-Null

try {
    $launcherPath = Join-Path $appRoot 'launcher.py'
    $runningApp = Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
        Where-Object { $_.CommandLine -and $_.CommandLine.IndexOf($launcherPath, [StringComparison]::OrdinalIgnoreCase) -ge 0 }
    if ($runningApp) { throw 'Close IdeaMiner before installing or updating it.' }

    Write-Host 'Downloading the IdeaMiner release...'
    $zipPath = Join-Path $work 'ideaminer-windows.zip'
    $checksumPath = "$zipPath.sha256"
    Invoke-WebRequest -UseBasicParsing -Uri $PackageUrl -OutFile $zipPath
    Invoke-WebRequest -UseBasicParsing -Uri "$PackageUrl.sha256" -OutFile $checksumPath

    $checksumText = Get-Content $checksumPath -Raw
    if ($checksumText -notmatch '^([0-9a-fA-F]{64})') { throw 'The release checksum file is invalid.' }
    $expectedHash = $Matches[1].ToLowerInvariant()
    $actualHash = (Get-FileHash $zipPath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actualHash -ne $expectedHash) { throw 'The downloaded release did not match its SHA-256 checksum.' }

    $stage = Join-Path $work 'app'
    Expand-Archive -Path $zipPath -DestinationPath $stage
    if (-not (Test-Path (Join-Path $stage 'launcher.py')) -or -not (Test-Path (Join-Path $stage 'web-dist\index.html')) -or -not (Test-Path (Join-Path $stage 'runtime\python.exe')) -or -not (Test-Path (Join-Path $stage 'Uninstall-IdeaMiner.ps1'))) {
        throw 'The downloaded archive is not a valid IdeaMiner release.'
    }

    New-Item -ItemType Directory -Path $installRoot -Force | Out-Null
    $backup = Join-Path $installRoot ("app-previous-" + [guid]::NewGuid().ToString('N'))
    if (Test-Path $appRoot) { Move-Item $appRoot $backup }
    try {
        Move-Item $stage $appRoot
    }
    catch {
        if (Test-Path $backup) { Move-Item $backup $appRoot }
        throw
    }
    if (Test-Path $backup) { Remove-Item $backup -Recurse -Force }

    $runtimePython = Join-Path $appRoot 'runtime\python.exe'
    $env:PYTHONPATH = "$appRoot;$appRoot\runtime\site-packages"
    & $runtimePython -c "import fastapi, mcp; print('IdeaMiner runtime verified')"
    if ($LASTEXITCODE -ne 0) { throw 'The bundled Python runtime could not import IdeaMiner dependencies.' }

    $startMenu = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\IdeaMiner'
    New-Item -ItemType Directory -Path $startMenu -Force | Out-Null
    $shell = New-Object -ComObject WScript.Shell
    $startShortcut = $shell.CreateShortcut((Join-Path $startMenu 'IdeaMiner.lnk'))
    $startShortcut.TargetPath = Join-Path $appRoot 'Start-IdeaMiner.bat'
    $startShortcut.WorkingDirectory = $appRoot
    $startShortcut.Save()
    $updateShortcut = $shell.CreateShortcut((Join-Path $startMenu 'Update IdeaMiner.lnk'))
    $updateShortcut.TargetPath = Join-Path $appRoot 'Update-IdeaMiner.bat'
    $updateShortcut.WorkingDirectory = $appRoot
    $updateShortcut.Save()
    $mcpShortcut = $shell.CreateShortcut((Join-Path $startMenu 'Connect Codex MCP.lnk'))
    $mcpShortcut.TargetPath = Join-Path $appRoot 'Configure-Codex-MCP.bat'
    $mcpShortcut.WorkingDirectory = $appRoot
    $mcpShortcut.Save()

    Write-Host ''
    Write-Host 'IdeaMiner is installed. Launch it from the Start Menu.'
    Write-Host 'Your library is stored separately in %LOCALAPPDATA%\IdeaMiner\data.'
    if ($LaunchAfterUpdate) {
        Start-Process -FilePath (Join-Path $appRoot 'Start-IdeaMiner.bat') -WorkingDirectory $appRoot
    }
}
finally {
    if (Test-Path $work) { Remove-Item $work -Recurse -Force }
}
