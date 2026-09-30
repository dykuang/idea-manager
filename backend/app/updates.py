from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import time
from pathlib import Path
from threading import Lock
from typing import Any

import httpx
from fastapi import APIRouter, Body, HTTPException, Request

router = APIRouter(prefix="/api/updates", tags=["updates"])
ROOT = Path(__file__).resolve().parents[2]
RELEASE_API = "https://api.github.com/repos/dykuang/idea-manager/releases/latest"
_cache: dict[str, Any] = {"checked_at": 0.0, "payload": None}
_cache_lock = Lock()


def current_version() -> str:
    version_file = ROOT / "version.json"
    package_file = ROOT / "package.json"
    try:
        if version_file.is_file():
            value = json.loads(version_file.read_text(encoding="utf-8-sig")).get("version")
        else:
            value = json.loads(package_file.read_text(encoding="utf-8")).get("version")
        version = str(value or "0.0.0")
        return version if version_file.is_file() else f"{version}-dev"
    except (OSError, ValueError, TypeError):
        return "0.0.0"


def _version_key(value: str) -> tuple[int, int, int, int, str]:
    normalized = value.strip().lstrip("vV")
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?", normalized)
    if not match:
        raise ValueError("Invalid version")
    major, minor, patch, prerelease = match.groups()
    # Stable releases sort above prereleases at the same numeric version.
    return int(major), int(minor), int(patch), 1 if prerelease is None else 0, prerelease or ""


def _packaged() -> bool:
    return (ROOT / "web-dist" / "index.html").is_file() and (ROOT / "Update-IdeaMiner.bat").is_file()


@router.get("/current")
async def get_current_version() -> dict[str, Any]:
    return {"current_version": current_version(), "can_update": _packaged() and os.name == "nt"}


@router.get("/check")
async def check_for_updates() -> dict[str, Any]:
    now = time.time()
    with _cache_lock:
        cached = _cache["payload"]
        if cached and now - float(_cache["checked_at"]) < 3600:
            return cached
    current = current_version()
    try:
        async with httpx.AsyncClient(timeout=8.0, headers={"Accept": "application/vnd.github+json", "User-Agent": "IdeaMiner-update-check"}) as client:
            response = await client.get(RELEASE_API)
            response.raise_for_status()
            release = response.json()
        tag = str(release.get("tag_name") or "").strip()
        latest = tag.lstrip("vV")
        if not latest:
            raise ValueError("Release has no version tag")
        available = _version_key(latest) > _version_key(current)
        payload = {
            "current_version": current,
            "latest_version": latest,
            "update_available": available,
            "status": "available" if available else "up_to_date",
            "release_url": str(release.get("html_url") or "https://github.com/dykuang/idea-manager/releases/latest"),
            "release_notes": str(release.get("body") or ""),
            "published_at": release.get("published_at"),
            "can_update": _packaged() and os.name == "nt",
        }
    except (httpx.HTTPError, ValueError, TypeError, KeyError):
        payload = {
            "current_version": current,
            "latest_version": None,
            "update_available": False,
            "status": "unavailable",
            "release_url": "https://github.com/dykuang/idea-manager/releases/latest",
            "release_notes": "",
            "published_at": None,
            "can_update": _packaged() and os.name == "nt",
        }
    with _cache_lock:
        _cache["checked_at"] = now if payload["status"] != "unavailable" else 0.0
        _cache["payload"] = payload if payload["status"] != "unavailable" else None
    return payload


@router.post("/apply")
async def apply_update(request: Request) -> dict[str, str]:
    if not (_packaged() and os.name == "nt"):
        raise HTTPException(status_code=501, detail="In-app installation is available in the Windows packaged app.")
    release = await check_for_updates()
    if release["status"] == "unavailable":
        raise HTTPException(status_code=503, detail="Could not verify the latest release. Check again when online.")
    if not release["update_available"]:
        raise HTTPException(status_code=409, detail="IdeaMiner is already up to date.")
    launcher_pid = os.getpid()
    updater = ROOT / "Update-IdeaMiner.bat"
    shutdown = getattr(request.app.state, "shutdown_handler", None)
    if not callable(shutdown):
        raise HTTPException(status_code=503, detail="The application launcher cannot be restarted automatically.")
    updater_path = str(updater).replace("'", "''")
    root_path = str(ROOT).replace("'", "''")
    # Wait for the parent launcher to finish shutting down before invoking its installer.
    script = (
        "$ErrorActionPreference='SilentlyContinue'; "
        f"Wait-Process -Id {launcher_pid} -Timeout 120; "
        f"while (Get-Process -Id {launcher_pid} -ErrorAction SilentlyContinue) {{ Start-Sleep -Milliseconds 500 }}; "
        f"Start-Process -FilePath '{updater_path}' -WorkingDirectory '{root_path}' -WindowStyle Hidden"
    )
    encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    try:
        subprocess.Popen(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-EncodedCommand", encoded],
            cwd=str(ROOT), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), close_fds=True,
        )
    except OSError as error:
        raise HTTPException(status_code=500, detail="Could not start the updater.") from error
    shutdown()
    return {"status": "updating"}


@router.post("/uninstall")
async def uninstall(request: Request, keep_database: bool = Body(..., embed=True)) -> dict[str, str]:
    if not (_packaged() and os.name == "nt"):
        raise HTTPException(status_code=501, detail="In-app uninstall is available in the Windows packaged app.")
    uninstaller = ROOT / "Uninstall-IdeaMiner.ps1"
    if not uninstaller.is_file():
        raise HTTPException(status_code=503, detail="The uninstaller is missing from this package.")
    shutdown = getattr(request.app.state, "shutdown_handler", None)
    if not callable(shutdown):
        raise HTTPException(status_code=503, detail="The application launcher cannot be closed for uninstall.")
    launcher_pid = os.getpid()
    script_path = str(uninstaller).replace("'", "''")
    install_root = str(ROOT.parent).replace("'", "''")
    local_app_data = str(Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "IdeaMiner").replace("'", "''")
    preserve_database = "$true" if keep_database else "$false"
    # Run outside the install tree so Windows can remove the app directory after the launcher exits.
    script = (
        "$ErrorActionPreference='SilentlyContinue'; "
        f"Wait-Process -Id {launcher_pid} -Timeout 120; "
        f"while (Get-Process -Id {launcher_pid} -ErrorAction SilentlyContinue) {{ Start-Sleep -Milliseconds 500 }}; "
        "Set-Location $env:TEMP; "
        f"& '{script_path}' -InstallRoot '{install_root}' -LibraryRoot '{local_app_data}' -KeepDatabase:${preserve_database}"
    )
    encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    try:
        subprocess.Popen(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-EncodedCommand", encoded],
            cwd=os.environ.get("TEMP", str(ROOT.parent)), stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), close_fds=True,
        )
    except OSError as error:
        raise HTTPException(status_code=500, detail="Could not start the uninstaller.") from error
    shutdown()
    return {"status": "uninstalling"}
