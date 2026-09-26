import asyncio
import os
import sys
import tempfile
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


ROOT = Path(__file__).resolve().parents[2]


def test_stdio_mcp_protocol_lists_and_calls_tools():
    handle = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    handle.close()

    async def exercise_server():
        environment = os.environ.copy()
        environment["IDEAMINER_DB"] = handle.name
        parameters = StdioServerParameters(
            command=sys.executable,
            args=[str(ROOT / "ideaminer_mcp.py")],
            env=environment,
        )
        async with stdio_client(parameters) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                tools = await session.list_tools()
                names = {tool.name for tool in tools.tools}
                assert {"search_ideas", "create_idea", "update_idea", "open_ideaminer", "create_codex_checkpoint"} <= names
                result = await session.call_tool("list_projects", arguments={})
                assert result.isError is False
                assert result.structuredContent["projects"][0]["name"] == "random_chat"

    try:
        asyncio.run(exercise_server())
    finally:
        try:
            os.unlink(handle.name)
        except PermissionError:
            pass


def test_packaged_open_ideaminer_discovers_runtime_url(monkeypatch, tmp_path):
    from backend.app import mcp_server

    app_root = tmp_path / "app"
    (app_root / "web-dist").mkdir(parents=True)
    (app_root / "web-dist" / "index.html").write_text("", encoding="utf-8")
    (app_root / "launcher.py").write_text("", encoding="utf-8")
    local_app_data = tmp_path / "local"
    monkeypatch.setenv("LOCALAPPDATA", str(local_app_data))
    monkeypatch.setattr(mcp_server, "ROOT", app_root)
    monkeypatch.setattr(mcp_server, "_resolve_idea", lambda _: {"id": 42})
    monkeypatch.setattr(mcp_server.time, "sleep", lambda _: None)
    monkeypatch.setattr(mcp_server, "webbrowser", type("Browser", (), {"open": staticmethod(lambda _: None)}))

    def fake_popen(_args, **options):
        assert options["env"]["IDEAMINER_START_PATH"] == "/?idea=42"
        server_url_file = local_app_data / "IdeaMiner" / "server.url"
        server_url_file.parent.mkdir(parents=True)
        server_url_file.write_text("http://127.0.0.1:8123", encoding="utf-8")

    monkeypatch.setattr(mcp_server.subprocess, "Popen", fake_popen)
    readiness = iter([False, True])
    monkeypatch.setattr(mcp_server, "_api_is_ready", lambda _url=None: next(readiness))

    result = mcp_server.open_ideaminer("42")

    assert result["started"] is True
    assert result["url"] == "http://127.0.0.1:8123/?idea=42"
