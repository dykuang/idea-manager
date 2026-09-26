[CmdletBinding()]
param(
    [string]$Version
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$package = Get-Content (Join-Path $repoRoot 'package.json') -Raw | ConvertFrom-Json
if (-not $Version) { $Version = [string]$package.version }
if ($Version -notmatch '^\d+\.\d+\.\d+([-.][A-Za-z0-9.-]+)?$') {
    throw "Version '$Version' is not a valid release version."
}

Push-Location $repoRoot
$stage = Join-Path ([System.IO.Path]::GetTempPath()) ("ideaminer-release-" + [guid]::NewGuid().ToString('N'))
try {
    if (-not (Get-Command npm -ErrorAction SilentlyContinue)) { throw 'Node.js and npm are required to build a release.' }
    if (-not (Get-Command python -ErrorAction SilentlyContinue)) { throw 'Python is required on the maintainer machine to assemble the offline runtime.' }
    npm ci
    if ($LASTEXITCODE -ne 0) { throw 'npm ci failed.' }
    npm run build
    if ($LASTEXITCODE -ne 0) { throw 'The frontend build failed.' }

    $frontendDist = Join-Path $repoRoot 'dist'
    if (-not (Test-Path (Join-Path $frontendDist 'index.html'))) { throw 'Vite did not produce dist/index.html.' }

    New-Item -ItemType Directory -Path (Join-Path $stage 'backend\app') -Force | Out-Null
    Get-ChildItem (Join-Path $repoRoot 'backend\app') -Filter '*.py' -File |
        Copy-Item -Destination (Join-Path $stage 'backend\app')
    Copy-Item (Join-Path $repoRoot 'backend\__init__.py') (Join-Path $stage 'backend\__init__.py')
    Copy-Item (Join-Path $repoRoot 'launcher.py') (Join-Path $stage 'launcher.py')
    Copy-Item (Join-Path $repoRoot 'ideaminer_mcp.py') (Join-Path $stage 'ideaminer_mcp.py')
    Copy-Item (Join-Path $repoRoot 'packaging\requirements-web.txt') (Join-Path $stage 'requirements-web.txt')
    Copy-Item (Join-Path $repoRoot 'packaging\Start-IdeaMiner.bat') (Join-Path $stage 'Start-IdeaMiner.bat')
    Copy-Item (Join-Path $repoRoot 'packaging\Update-IdeaMiner.bat') (Join-Path $stage 'Update-IdeaMiner.bat')
    Copy-Item (Join-Path $repoRoot 'packaging\Install-IdeaMiner.bat') (Join-Path $stage 'Install-IdeaMiner.bat')
    Copy-Item (Join-Path $repoRoot 'packaging\Configure-Codex-MCP.bat') (Join-Path $stage 'Configure-Codex-MCP.bat')
    Copy-Item $frontendDist (Join-Path $stage 'web-dist') -Recurse
    $runtime = Join-Path $stage 'runtime'
    $runtimeZip = Join-Path $stage 'python-3.12-embed-amd64.zip'
    Write-Host 'Downloading the portable Python runtime for the release...'
    Invoke-WebRequest -UseBasicParsing -Uri 'https://www.python.org/ftp/python/3.12.10/python-3.12.10-embed-amd64.zip' -OutFile $runtimeZip
    Expand-Archive -Path $runtimeZip -DestinationPath $runtime
    Remove-Item $runtimeZip -Force
    $pthFile = Get-ChildItem $runtime -Filter '*._pth' -File | Select-Object -First 1
    if (-not $pthFile) { throw 'The portable Python archive did not contain a _pth file.' }
    $pthLines = Get-Content $pthFile.FullName
    if ($pthLines -notcontains 'site-packages') { $pthLines += 'site-packages' }
    if ($pthLines -notcontains 'import site') { $pthLines += 'import site' }
    Set-Content $pthFile.FullName $pthLines -Encoding ASCII
    New-Item -ItemType Directory -Path (Join-Path $runtime 'site-packages') -Force | Out-Null
    Write-Host 'Preparing offline Python and MCP dependencies...'
    python -m pip install --disable-pip-version-check --only-binary=:all: --platform win_amd64 --python-version 3.12 --implementation cp --abi cp312 --target (Join-Path $runtime 'site-packages') -r (Join-Path $repoRoot 'packaging\requirements-web.txt')
    if ($LASTEXITCODE -ne 0) { throw 'Could not prepare the offline Python dependencies.' }
    $pywin32Dlls = Join-Path $runtime 'site-packages\pywin32_system32'
    Get-ChildItem $pywin32Dlls -Filter '*.dll' -File | Copy-Item -Destination $runtime
    Copy-Item (Join-Path $runtime 'site-packages\win32\lib\pywintypes.py') (Join-Path $runtime 'site-packages\pywintypes.py')
    Get-ChildItem (Join-Path $runtime 'site-packages\win32') -Filter '*.pyd' -File | Copy-Item -Destination (Join-Path $runtime 'site-packages')
    Copy-Item (Join-Path $runtime 'site-packages\win32\lib\win32con.py') (Join-Path $runtime 'site-packages\win32con.py')
    @{ version = $Version } | ConvertTo-Json | Set-Content (Join-Path $stage 'version.json') -Encoding UTF8

    $releaseDir = Join-Path $repoRoot 'release'
    New-Item -ItemType Directory -Path $releaseDir -Force | Out-Null
    $versionedZip = Join-Path $releaseDir "ideaminer-$Version-windows.zip"
    $latestZip = Join-Path $releaseDir 'ideaminer-windows.zip'
    Compress-Archive -Path (Join-Path $stage '*') -DestinationPath $versionedZip -Force
    Copy-Item $versionedZip $latestZip -Force

    foreach ($zipPath in @($versionedZip, $latestZip)) {
        $hash = (Get-FileHash $zipPath -Algorithm SHA256).Hash.ToLowerInvariant()
        Set-Content -Path "$zipPath.sha256" -Value "$hash  $(Split-Path $zipPath -Leaf)" -Encoding ASCII
    }
    Copy-Item (Join-Path $repoRoot 'packaging\Install-IdeaMiner.bat') (Join-Path $releaseDir 'Install-IdeaMiner.bat') -Force

    Write-Host "Release package created: $versionedZip"
    Write-Host "Upload ideaminer-windows.zip, ideaminer-windows.zip.sha256, and Install-IdeaMiner.bat to the GitHub release."
}
finally {
    if (Test-Path $stage) { Remove-Item $stage -Recurse -Force }
    Pop-Location
}