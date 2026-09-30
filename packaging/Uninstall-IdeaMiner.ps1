[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$InstallRoot,
    [Parameter(Mandatory = $true)][string]$LibraryRoot,
    [switch]$KeepDatabase
)

$ErrorActionPreference = 'Stop'
$installPath = [System.IO.Path]::GetFullPath([Environment]::ExpandEnvironmentVariables($InstallRoot))
$libraryPath = [System.IO.Path]::GetFullPath([Environment]::ExpandEnvironmentVariables($LibraryRoot))
if (-not [System.IO.Directory]::GetParent($installPath)) { throw 'The installation path cannot be a drive root.' }
if ((Split-Path $libraryPath -Leaf) -ne 'IdeaMiner') { throw 'The library path is not an IdeaMiner data folder.' }
$appRoot = Join-Path $installPath 'app'
if (-not (Test-Path -LiteralPath $appRoot -PathType Container)) { throw 'The IdeaMiner application folder was not found.' }
$appPath = (Resolve-Path -LiteralPath $appRoot).Path
if ((Split-Path $appPath -Leaf) -ne 'app' -or (Split-Path $appPath -Parent) -ne $installPath.TrimEnd('\')) {
    throw 'The application path did not pass uninstall safety checks.'
}

$dataPath = Join-Path $libraryPath 'data'
$databasePath = Join-Path $dataPath 'ideaminer.db'
if (Test-Path -LiteralPath $libraryPath -PathType Container) {
    $foldersToCheck = [System.Collections.Generic.Stack[string]]::new()
    $foldersToCheck.Push($libraryPath)
    while ($foldersToCheck.Count -gt 0) {
        foreach ($item in Get-ChildItem -LiteralPath $foldersToCheck.Pop() -Force) {
            if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
                throw 'A linked item was found in the IdeaMiner data folder. Uninstall was cancelled to protect external files.'
            }
            if ($item.PSIsContainer) { $foldersToCheck.Push($item.FullName) }
        }
    }
}
if ($KeepDatabase -and (Test-Path -LiteralPath $dataPath -PathType Container)) {
    $dataChildren = @(Get-ChildItem -LiteralPath $dataPath -Force)
    if ($dataChildren | Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint }) {
        throw 'A linked item was found in the library folder. Uninstall was cancelled to protect external files.'
    }
    foreach ($preservedPath in @($databasePath, "$databasePath-wal", "$databasePath-shm")) {
        if ((Test-Path -LiteralPath $preservedPath) -and -not (Test-Path -LiteralPath $preservedPath -PathType Leaf)) {
            throw 'A database file path is not a regular file. Uninstall was cancelled.'
        }
    }
}
$python = Join-Path $appRoot 'runtime\python.exe'
if (Test-Path -LiteralPath $python -PathType Leaf) {
    $env:PYTHONPATH = "$appRoot;$appRoot\runtime\site-packages"
    $env:IDEAMINER_DB = $databasePath
    & $python -c "from backend.app.agent_profiles import delete_api_key, reset_profile; from backend.app.main import AGENT_PROVIDERS; [delete_api_key(provider) for provider in AGENT_PROVIDERS]; [reset_profile(provider) for provider in AGENT_PROVIDERS]" 2>$null
}

$startMenu = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\IdeaMiner'
if ((Test-Path -LiteralPath $startMenu -PathType Container) -and (Split-Path $startMenu -Leaf) -eq 'IdeaMiner') {
    Remove-Item -LiteralPath $startMenu -Recurse -Force
}
if (Get-Command codex -ErrorAction SilentlyContinue) {
    & codex mcp remove ideaminer *> $null
}

Set-Location $env:TEMP
Remove-Item -LiteralPath $appPath -Recurse -Force

if ($KeepDatabase) {
    if (Test-Path -LiteralPath $libraryPath -PathType Container) {
        if (Test-Path -LiteralPath $dataPath -PathType Container) {
            foreach ($item in Get-ChildItem -LiteralPath $dataPath -Force) {
                if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'A linked item was found in the library folder. It was left untouched.' }
                if ($item.FullName -notin @($databasePath, "$databasePath-wal", "$databasePath-shm")) {
                    Remove-Item -LiteralPath $item.FullName -Recurse -Force
                }
            }
            Get-ChildItem -LiteralPath $dataPath -Directory -Force | Where-Object { -not (Get-ChildItem -LiteralPath $_.FullName -Force) } | Remove-Item -Force
        }
        foreach ($item in Get-ChildItem -LiteralPath $libraryPath -Force) {
            if ($item.FullName -ne $dataPath) {
                if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'A linked item was found in the IdeaMiner data folder. It was left untouched.' }
                Remove-Item -LiteralPath $item.FullName -Recurse -Force
            }
        }
        Get-ChildItem -LiteralPath $libraryPath -Directory -Force | Where-Object { -not (Get-ChildItem -LiteralPath $_.FullName -Force) } | Remove-Item -Force
    }
    $message = "IdeaMiner has been removed. Your library database is kept at:`n$databasePath`n`nProject workspace files were left untouched."
}
else {
    if (Test-Path -LiteralPath $libraryPath) {
        if ((Split-Path $libraryPath -Leaf) -ne 'IdeaMiner') { throw 'The library path did not pass uninstall safety checks.' }
        Remove-Item -LiteralPath $libraryPath -Recurse -Force
    }
    $message = 'IdeaMiner and its local library data have been removed. Project workspace files were left untouched.'
}

if ((Test-Path -LiteralPath $installPath -PathType Container) -and -not (Get-ChildItem -LiteralPath $installPath -Force)) {
    Remove-Item -LiteralPath $installPath -Force
}
Add-Type -AssemblyName System.Windows.Forms
[void][System.Windows.Forms.MessageBox]::Show($message, 'IdeaMiner uninstalled', 'OK', 'Information')
