# Windows Web Installer

This packaging path gives users a click-to-install bootstrapper. The release contains a portable Python runtime and the app's pinned Python/MCP dependencies, so users do not need Python, Node.js, or PyPI access. Node.js and Python are only needed by the maintainer to build a release.

## Build a Release

On the maintainer's Windows machine, install Node.js LTS, then run from the repository root:

```powershell
.\packaging\Build-WebRelease.ps1 -Version 0.4.0
```

The script runs `npm ci` and `npm run build`, then creates:

- `release/ideaminer-0.4.0-windows.zip` and its `.sha256` checksum
- `release/ideaminer-windows.zip` and its `.sha256` checksum
- `release/Install-IdeaMiner.bat`

Create a full, non-prerelease GitHub release and upload `ideaminer-windows.zip`, `ideaminer-windows.zip.sha256`, and `Install-IdeaMiner.bat`. The bootstrapper uses GitHub's `releases/latest/download` URL, so keep the stable asset names exactly as shown. The versioned archive is useful for keeping a release-specific copy.

## Install and Update

Users download and double-click `Install-IdeaMiner.bat`. The installer needs access to the GitHub release, but does not download Python or PyPI dependencies. It verifies the app ZIP against its SHA-256 asset before installing it, and does not need admin rights or a preinstalled Python or Node.js. To choose a location, run `Install-IdeaMiner.bat "D:\Apps\IdeaMiner"` from a terminal or shortcut target.

The default install path is `%LOCALAPPDATA%\Programs\IdeaMiner`. The installer adds **IdeaMiner**, **Update IdeaMiner**, and **Connect Codex MCP** shortcuts to the Start Menu. The update shortcut detects the installed app directory and preserves a custom install path. The SQLite library remains at `%LOCALAPPDATA%\IdeaMiner\data\ideaminer.db`, outside the replaceable app directory.

The in-app **Version and updates** panel also provides **Uninstall IdeaMiner**. Users can remove the app and all local IdeaMiner data, or remove the app while keeping only the SQLite database (including any SQLite journal files needed to preserve it). Project workspace files are left untouched in either case.

The Codex helper requires Codex CLI to be installed. It registers the packaged MCP server with Codex, using the same Python environment and SQLite library as the app. Alternatively, run this in PowerShell:

```powershell
$root = "$env:LOCALAPPDATA\Programs\IdeaMiner"
codex mcp add ideaminer -- "$root\app\runtime\python.exe" "$root\app\ideaminer_mcp.py"
```

The MCP server can read and write the library while the web app is closed; it does not open the app window. The release builder pins Python `3.12.10` through the embedded-runtime URL and packages all runtime dependencies, including MCP, in `requirements-web.txt`.

## Release Checklist

1. Update the app version in `package.json` and make sure the bootstrapper's GitHub URLs match the repository's default branch.
2. Run the release builder with that version.
3. Test `Install-IdeaMiner.bat` on a clean Windows user account, then test **Update IdeaMiner** after publishing a newer release. Confirm the database remains intact.
4. Publish a full GitHub release with the stable ZIP, its checksum, and the batch installer assets.

The batch bootstrapper and PowerShell installer are plain text and can be reviewed before distribution. For broader public distribution, consider signing the installer scripts and publishing a signed native installer later.
