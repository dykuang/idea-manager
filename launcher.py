"""Coordinated local launcher for IdeaMiner's API and web UI."""

from __future__ import annotations

import os
import socket
import shutil
import signal
import subprocess
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
WEB_DIST = ROOT / "web-dist"
if "IDEAMINER_DB" not in os.environ:
    if (WEB_DIST / "index.html").is_file():
        local_app_data = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        os.environ["IDEAMINER_DB"] = str(local_app_data / "IdeaMiner" / "data" / "ideaminer.db")
    else:
        os.environ["IDEAMINER_DB"] = str(ROOT / "data" / "ideaminer.db")

import uvicorn

from backend.app.main import app


shutdown_requested = threading.Event()


def _wait_for(url: str, timeout: float = 30.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and not shutdown_requested.is_set():
        try:
            with urllib.request.urlopen(url, timeout=1):
                return True
        except Exception:
            time.sleep(0.25)
    return False


def _available_port(preferred: int, excluded: set[int] | None = None) -> int:
    excluded = excluded or set()
    candidates = [preferred, 0]
    for candidate in candidates:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            try:
                probe.bind(("127.0.0.1", candidate))
            except OSError:
                continue
            port = int(probe.getsockname()[1])
            if port not in excluded:
                return port
    raise RuntimeError("Could not find an available local port")


def _stop_frontend(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        try:
            process.send_signal(signal.CTRL_BREAK_EVENT)
            process.wait(timeout=3)
            return
        except (OSError, subprocess.TimeoutExpired):
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                check=False,
            )
    else:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()


def _run_packaged() -> int:
    api_port = _available_port(8000)
    app_url = f"http://127.0.0.1:{api_port}"
    start_path = os.environ.get("IDEAMINER_START_PATH", "/")
    if not start_path.startswith("/") or start_path.startswith("//"):
        start_path = "/"
    start_url = f"{app_url}{start_path}"
    local_app_data = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    server_url_file = local_app_data / "IdeaMiner" / "server.url"
    server_url_file.parent.mkdir(parents=True, exist_ok=True)
    server_url_file.write_text(app_url, encoding="utf-8")
    app.state.shutdown_handler = shutdown_requested.set
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=api_port, log_level="info")
    )
    api_thread = threading.Thread(target=server.run, name="ideaminer-api")
    api_thread.start()

    print("\nIdeaMiner is starting. Keep this window open while you work.")
    print(f"Library: {os.environ['IDEAMINER_DB']}")
    print(f"Web:     {app_url}")
    print("Use the Quit button in the app, or press Ctrl+C here, to stop.\n")

    try:
        if _wait_for(f"{app_url}/api/health"):
            webbrowser.open(start_url)
        else:
            print("IdeaMiner did not become ready in time. Check the messages above.")
            shutdown_requested.set()

        while not shutdown_requested.wait(0.5):
            if not api_thread.is_alive():
                print("The IdeaMiner server stopped unexpectedly.")
                shutdown_requested.set()
    except KeyboardInterrupt:
        print("\nStopping IdeaMiner...")
        shutdown_requested.set()
    finally:
        server.should_exit = True
        api_thread.join(timeout=8)
        if server_url_file.is_file() and server_url_file.read_text(encoding="utf-8") == app_url:
            server_url_file.unlink()
        print("IdeaMiner stopped. Your ideas are safely stored.")

    return 0


def main() -> int:
    if (WEB_DIST / "index.html").is_file():
        return _run_packaged()

    npm = shutil.which("npm.cmd" if os.name == "nt" else "npm")
    if npm is None:
        print("npm was not found. Install Node.js and try again.")
        return 1

    api_port = _available_port(8000)
    web_port = _available_port(5173, {api_port})
    api_url = f"http://127.0.0.1:{api_port}"
    app_url = f"http://127.0.0.1:{web_port}"
    start_url = os.environ.get("IDEAMINER_START_URL", app_url)

    app.state.shutdown_handler = shutdown_requested.set
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=api_port, log_level="info")
    )
    api_thread = threading.Thread(target=server.run, name="ideaminer-api")
    api_thread.start()

    frontend_command = [npm, "run", "dev", "--", "--host", "127.0.0.1", "--port", str(web_port), "--strictPort"]
    frontend_environment = os.environ.copy()
    frontend_environment["IDEAMINER_API_PORT"] = str(api_port)
    frontend = subprocess.Popen(
        frontend_command,
        cwd=ROOT,
        env=frontend_environment,
        creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
    )

    print("\nIdeaMiner is starting. Keep this window open while you work.")
    print(f"Library: {os.environ['IDEAMINER_DB']}")
    print(f"Web:     {app_url}")
    print(f"API:     {api_url}")
    print("Use the Quit button in the app, or press Ctrl+C here, to stop.\n")

    try:
        api_ready = _wait_for(f"{api_url}/api/health")
        web_ready = _wait_for(app_url)
        if api_ready and web_ready:
            webbrowser.open(start_url)
        else:
            print("IdeaMiner did not become ready in time. Check the messages above.")
            shutdown_requested.set()

        while not shutdown_requested.wait(0.5):
            if frontend.poll() is not None or not api_thread.is_alive():
                print("A server stopped unexpectedly; shutting down IdeaMiner.")
                shutdown_requested.set()
    except KeyboardInterrupt:
        print("\nStopping IdeaMiner...")
        shutdown_requested.set()
    finally:
        server.should_exit = True
        api_thread.join(timeout=8)
        _stop_frontend(frontend)
        print("IdeaMiner stopped. Your ideas are safely stored.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
