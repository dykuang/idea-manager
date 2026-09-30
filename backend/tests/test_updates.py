import asyncio
import json
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from backend.app import updates


def test_current_version_uses_packaged_metadata_and_marks_source_build(monkeypatch):
    with tempfile.TemporaryDirectory(dir=updates.ROOT) as directory:
        root = Path(directory)
        monkeypatch.setattr(updates, "ROOT", root)
        (root / "package.json").write_text(json.dumps({"version": "0.4.0"}), encoding="utf-8")
        assert updates.current_version() == "0.4.0-dev"
        (root / "version.json").write_text(json.dumps({"version": "0.5.0"}), encoding="utf-8")
        assert updates.current_version() == "0.5.0"


def test_release_version_comparison_handles_tags_and_prereleases():
    assert updates._version_key("v1.2.3") > updates._version_key("1.2.3-rc.1")
    assert updates._version_key("1.3.0") > updates._version_key("1.2.99")


def test_update_check_reports_latest_release(monkeypatch):
    class Response:
        def raise_for_status(self):
            pass

        @staticmethod
        def json():
            return {"tag_name": "v0.9.0", "html_url": "https://github.com/dykuang/idea-manager/releases/tag/v0.9.0", "body": "Release notes", "published_at": "2026-09-30T00:00:00Z"}

    class Client:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, _url):
            return Response()

    monkeypatch.setattr(updates.httpx, "AsyncClient", Client)
    monkeypatch.setattr(updates, "current_version", lambda: "0.8.0")
    monkeypatch.setattr(updates, "_packaged", lambda: False)
    monkeypatch.setattr(updates, "_cache", {"checked_at": 0.0, "payload": None})
    result = asyncio.run(updates.check_for_updates())
    assert result["status"] == "available"
    assert result["latest_version"] == "0.9.0"
    assert result["update_available"] is True
    assert result["can_update"] is False


def test_uninstall_refuses_source_builds():
    with pytest.raises(HTTPException) as error:
        asyncio.run(updates.uninstall(SimpleNamespace(), keep_database=True))
    assert error.value.status_code == 501


def test_uninstall_starts_packaged_helper_and_closes_app(monkeypatch):
    with tempfile.TemporaryDirectory(dir=updates.ROOT) as directory:
        root = Path(directory)
        (root / "web-dist").mkdir()
        (root / "web-dist" / "index.html").write_text("ok", encoding="utf-8")
        (root / "Update-IdeaMiner.bat").write_text("", encoding="utf-8")
        (root / "Uninstall-IdeaMiner.ps1").write_text("", encoding="utf-8")
        monkeypatch.setattr(updates, "ROOT", root)
        monkeypatch.setattr(updates, "_packaged", lambda: True)
        monkeypatch.setattr(updates, "os", SimpleNamespace(name="nt", environ=os.environ, getpid=os.getpid, devnull=os.devnull))
        monkeypatch.setattr(updates.subprocess, "Popen", lambda *args, **kwargs: SimpleNamespace(args=args))
        closed = []
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(shutdown_handler=lambda: closed.append(True))))
        result = asyncio.run(updates.uninstall(request, keep_database=True))
        assert result == {"status": "uninstalling"}
        assert closed == [True]
