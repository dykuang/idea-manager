"""Stable entry point for the IdeaMiner Codex MCP server."""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if "IDEAMINER_DB" not in os.environ and (ROOT / "web-dist" / "index.html").is_file():
    local_app_data = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    os.environ["IDEAMINER_DB"] = str(local_app_data / "IdeaMiner" / "data" / "ideaminer.db")

from backend.app.mcp_server import main


if __name__ == "__main__":
    main()
