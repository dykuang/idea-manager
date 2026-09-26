"""Local MCP tools for using IdeaMiner from any Codex task."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal, TypeVar
from urllib.parse import urlparse

from fastapi import HTTPException
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from .database import db, init_db
from .main import (
    _fts_query,
    attach_file as api_attach_file,
    copy_idea as api_copy_idea,
    create_codex_checkpoint as api_create_codex_checkpoint,
    create_idea as api_create_idea,
    create_project as api_create_project,
    create_project_group as api_create_project_group,
    create_relation as api_create_relation,
    get_idea as api_get_idea,
    list_ideas as api_list_ideas,
    list_projects as api_list_projects,
    move_idea as api_move_idea,
    update_idea as api_update_idea,
)
from .schemas import AttachmentCreate, CodexCheckpointCreate, CodexCheckpointProposal, IdeaCreate, IdeaUpdate, ProjectAssignment, ProjectCreate, ProjectGroupCreate, RelationCreate


ROOT = Path(__file__).resolve().parents[2]
APP_URL = "http://127.0.0.1:5173"
API_HEALTH_URL = "http://127.0.0.1:8000/api/health"
T = TypeVar("T")

READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
LOCAL_WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False)

mcp = FastMCP(
    "ideaminer",
    instructions=(
        "IdeaMiner is the user's local research-idea library. Resolve projects and ideas before writing. "
        "Preserve verbatim source wording in raw_text when creating an idea. Before updating, read the idea "
        "and pass its updated_at value. Never imply that a discussion was saved unless a write tool succeeded."
    ),
)

init_db()


def _friendly_error(error: Exception) -> ValueError:
    if isinstance(error, HTTPException):
        return ValueError(str(error.detail))
    if isinstance(error, sqlite3.Error):
        return ValueError(f"IdeaMiner database error: {error}")
    return ValueError(str(error))


def _resolve_project(reference: str, *, allow_recycle: bool = False) -> dict[str, Any]:
    value = reference.strip()
    if not value:
        with db() as connection:
            row = connection.execute("SELECT * FROM projects WHERE system_key='random_chat'").fetchone()
    elif value.isdigit():
        with db() as connection:
            row = connection.execute("SELECT * FROM projects WHERE id=?", (int(value),)).fetchone()
    else:
        with db() as connection:
            row = connection.execute("SELECT * FROM projects WHERE name=? COLLATE NOCASE", (value,)).fetchone()
    if not row:
        choices = ", ".join(project["name"] for project in api_list_projects() if project["system_key"] != "recycle")
        raise ValueError(f"Project '{reference}' was not found. Available projects: {choices}")
    project = dict(row)
    if project["system_key"] == "recycle" and not allow_recycle:
        raise ValueError("Recycle cannot be used as a destination project")
    return project


def _resolve_group(reference: str) -> dict[str, Any]:
    value = reference.strip()
    with db() as connection:
        if value.isdigit():
            row = connection.execute("SELECT * FROM project_groups WHERE id=?", (int(value),)).fetchone()
        else:
            row = connection.execute("SELECT * FROM project_groups WHERE name=? COLLATE NOCASE", (value,)).fetchone()
    if not row:
        raise ValueError(f"Project group '{reference}' was not found")
    return dict(row)


def _resolve_idea(reference: str) -> dict[str, Any]:
    value = reference.strip()
    match = re.fullmatch(r"(?:\[\[idea:|idea\s*#?)?(\d+)(?:\]\])?", value, flags=re.IGNORECASE)
    if match:
        try:
            return api_get_idea(int(match.group(1)))
        except Exception as error:
            raise _friendly_error(error) from error

    with db() as connection:
        exact = connection.execute("SELECT id FROM ideas WHERE title=? COLLATE NOCASE ORDER BY updated_at DESC", (value,)).fetchall()
        if len(exact) == 1:
            return api_get_idea(exact[0]["id"])
        if len(exact) > 1:
            options = ", ".join(f"[[idea:{row['id']}]]" for row in exact[:8])
            raise ValueError(f"Several ideas have that title. Use a stable reference: {options}")

        query = _fts_query(value)
        rows = connection.execute(
            "SELECT i.id, i.title FROM ideas_fts f JOIN ideas i ON i.id=f.rowid WHERE ideas_fts MATCH ? ORDER BY bm25(ideas_fts) LIMIT 8",
            (query,),
        ).fetchall() if query else []
    if len(rows) == 1:
        return api_get_idea(rows[0]["id"])
    if rows:
        options = "; ".join(f"[[idea:{row['id']}]] {row['title']}" for row in rows)
        raise ValueError(f"Idea reference is ambiguous. Choose one of: {options}")
    raise ValueError(f"Idea '{reference}' was not found")


def _idempotent(action_type: str, idempotency_key: str, operation: Callable[[], T]) -> T:
    key = idempotency_key.strip()
    if not key:
        return operation()
    with db() as connection:
        saved = connection.execute(
            "SELECT action_type, response_json FROM external_actions WHERE idempotency_key=?", (key,)
        ).fetchone()
    if saved:
        if saved["action_type"] != action_type:
            raise ValueError("That idempotency key was already used for a different IdeaMiner action")
        return json.loads(saved["response_json"])
    result = operation()
    try:
        with db() as connection:
            connection.execute(
                "INSERT INTO external_actions(idempotency_key, action_type, response_json) VALUES (?, ?, ?)",
                (key, action_type, json.dumps(result, ensure_ascii=False)),
            )
    except sqlite3.IntegrityError:
        with db() as connection:
            saved = connection.execute(
                "SELECT action_type, response_json FROM external_actions WHERE idempotency_key=?", (key,)
            ).fetchone()
        if not saved or saved["action_type"] != action_type:
            raise ValueError("That idempotency key conflicted with another IdeaMiner action")
        return json.loads(saved["response_json"])
    return result


@mcp.tool(title="List IdeaMiner projects", annotations=READ_ONLY)
def list_projects(include_recycle: bool = False) -> dict[str, Any]:
    """List projects so a project ID or exact name can be chosen before storing or moving an idea."""
    projects = [project for project in api_list_projects() if include_recycle or project["system_key"] != "recycle"]
    return {"projects": projects}


@mcp.tool(title="Search IdeaMiner ideas", annotations=READ_ONLY)
def search_ideas(
    query: str = "",
    project: str = "",
    tags: list[str] | None = None,
    status: Literal["", "seed", "exploring", "promising", "parked"] = "",
    include_recycle: bool = False,
    limit: int = 25,
) -> dict[str, Any]:
    """Find ideas by keyword, project, tags, or status before reading, editing, or linking them."""
    if limit < 1 or limit > 100:
        raise ValueError("limit must be between 1 and 100")
    project_id = _resolve_project(project, allow_recycle=True)["id"] if project.strip() else None
    try:
        ideas = api_list_ideas(
            q=query,
            tag=tags or [],
            status=status or None,
            relation_type=None,
            project_id=project_id,
            group_id=None,
            include_recycle=include_recycle,
        )[:limit]
    except Exception as error:
        raise _friendly_error(error) from error
    summaries = [
        {
            "id": idea["id"],
            "reference": f"[[idea:{idea['id']}]]",
            "title": idea["title"],
            "content": idea["content"][:1200],
            "status": idea["status"],
            "tags": idea["tags"],
            "project_id": idea["project_id"],
            "updated_at": idea["updated_at"],
        }
        for idea in ideas
    ]
    return {"count": len(summaries), "ideas": summaries}


@mcp.tool(title="Read an IdeaMiner idea", annotations=READ_ONLY)
def get_idea(reference: str) -> dict[str, Any]:
    """Read one idea using its stable reference, numeric ID, or unambiguous title."""
    return {"idea": _resolve_idea(reference)}


@mcp.tool(title="Create an IdeaMiner project", annotations=LOCAL_WRITE)
def create_project(
    name: str,
    description: str = "",
    group: str = "",
    workspace_mode: Literal["library", "linked", "managed"] = "library",
    workspace_path: str = "",
    idempotency_key: str = "",
) -> dict[str, Any]:
    """Create a project when the user explicitly asks; linked and managed modes may use a local folder path."""
    group_id = _resolve_group(group)["id"] if group.strip() else None

    def operation() -> dict[str, Any]:
        try:
            return api_create_project(ProjectCreate(
                name=name,
                description=description,
                group_id=group_id,
                workspace_mode=workspace_mode,
                workspace_path=workspace_path,
            ))
        except Exception as error:
            raise _friendly_error(error) from error

    return {"project": _idempotent("create_project", idempotency_key, operation)}


@mcp.tool(title="Create an IdeaMiner project group", annotations=LOCAL_WRITE)
def create_project_group(name: str, idempotency_key: str = "") -> dict[str, Any]:
    """Create a project group when the user explicitly asks to organize projects together."""
    def operation() -> dict[str, Any]:
        try:
            return api_create_project_group(ProjectGroupCreate(name=name))
        except Exception as error:
            raise _friendly_error(error) from error

    return {"group": _idempotent("create_project_group", idempotency_key, operation)}


@mcp.tool(title="Create an IdeaMiner idea", annotations=LOCAL_WRITE)
def create_idea(
    title: str,
    content: str,
    raw_text: str,
    project: str = "",
    tags: list[str] | None = None,
    status: Literal["seed", "exploring", "promising", "parked"] = "seed",
    parent_reference: str = "",
    idempotency_key: str = "",
) -> dict[str, Any]:
    """Store a new idea. Pass the user's verbatim source wording as raw_text; parent_reference creates a descendant link."""
    parent = _resolve_idea(parent_reference) if parent_reference.strip() else None
    project_id = _resolve_project(project)["id"] if project.strip() else (parent["project_id"] if parent else None)

    def operation() -> dict[str, Any]:
        try:
            idea = api_create_idea(IdeaCreate(
                title=title,
                content=content,
                raw_text=raw_text,
                status=status,
                tags=tags or [],
                project_id=project_id,
            ))
            relation = None
            if parent:
                relation = api_create_relation(RelationCreate(
                    source_id=parent["id"], target_id=idea["id"], relation_type="develops-into",
                    note="Created as a descendant from Codex",
                ))
            return {"idea": idea, "relation": relation}
        except Exception as error:
            raise _friendly_error(error) from error

    return _idempotent("create_idea", idempotency_key, operation)


@mcp.tool(title="Update an IdeaMiner idea", annotations=LOCAL_WRITE)
def update_idea(
    reference: str,
    expected_updated_at: str,
    title: str | None = None,
    content: str | None = None,
    tags: list[str] | None = None,
    status: Literal["seed", "exploring", "promising", "parked"] | None = None,
    idempotency_key: str = "",
) -> dict[str, Any]:
    """Update working fields after reading the idea. expected_updated_at prevents overwriting a newer edit; raw_text is immutable."""
    current = _resolve_idea(reference)

    def operation() -> dict[str, Any]:
        try:
            return api_update_idea(current["id"], IdeaUpdate(
                title=title if title is not None else current["title"],
                content=content if content is not None else current["content"],
                tags=tags if tags is not None else current["tags"],
                status=status if status is not None else current["status"],
                expected_updated_at=expected_updated_at,
            ))
        except Exception as error:
            raise _friendly_error(error) from error

    return {"idea": _idempotent("update_idea", idempotency_key, operation)}


@mcp.tool(title="Move an IdeaMiner idea", annotations=LOCAL_WRITE)
def move_idea(reference: str, project: str, idempotency_key: str = "") -> dict[str, Any]:
    """Move an idea to an active project when the user explicitly requests the move."""
    idea = _resolve_idea(reference)
    destination = _resolve_project(project)

    def operation() -> dict[str, Any]:
        try:
            return api_move_idea(idea["id"], ProjectAssignment(project_id=destination["id"]))
        except Exception as error:
            raise _friendly_error(error) from error

    return {"idea": _idempotent("move_idea", idempotency_key, operation)}


@mcp.tool(title="Copy an IdeaMiner idea", annotations=LOCAL_WRITE)
def copy_idea(reference: str, project: str, idempotency_key: str = "") -> dict[str, Any]:
    """Copy an idea into another active project while preserving its original raw capture."""
    idea = _resolve_idea(reference)
    destination = _resolve_project(project)

    def operation() -> dict[str, Any]:
        try:
            return api_copy_idea(idea["id"], ProjectAssignment(project_id=destination["id"]))
        except Exception as error:
            raise _friendly_error(error) from error

    return {"idea": _idempotent("copy_idea", idempotency_key, operation)}


@mcp.tool(title="Link two IdeaMiner ideas", annotations=LOCAL_WRITE)
def create_relation(
    source_reference: str,
    target_reference: str,
    relation_type: str,
    note: str = "",
    idempotency_key: str = "",
) -> dict[str, Any]:
    """Create a typed idea-to-idea relation after resolving both endpoints to stable IDs."""
    source = _resolve_idea(source_reference)
    target = _resolve_idea(target_reference)

    def operation() -> dict[str, Any]:
        try:
            return api_create_relation(RelationCreate(
                source_id=source["id"], target_id=target["id"], relation_type=relation_type, note=note,
            ))
        except Exception as error:
            raise _friendly_error(error) from error

    return {"relation": _idempotent("create_relation", idempotency_key, operation)}


@mcp.tool(title="Checkpoint a Codex session in IdeaMiner", annotations=LOCAL_WRITE)
def create_codex_checkpoint(
    summary: str,
    project: str = "",
    proposals: list[dict[str, Any]] | None = None,
    task_title: str = "",
    idempotency_key: str = "",
) -> dict[str, Any]:
    """Queue up to five reviewed session insights as pending IdeaMiner proposals; this does not create ideas immediately."""
    destination = _resolve_project(project) if project.strip() else _resolve_project("")
    parsed: list[CodexCheckpointProposal] = []
    for proposal in (proposals or [])[:5]:
        if not isinstance(proposal, dict):
            raise ValueError("Each checkpoint proposal must be an object")
        parent_reference = str(proposal.get("parent_reference") or "").strip()
        parent_id = _resolve_idea(parent_reference)["id"] if parent_reference else None
        try:
            parsed.append(CodexCheckpointProposal(
                title=str(proposal.get("title") or ""), content=str(proposal.get("content") or ""),
                tags=[str(tag) for tag in proposal.get("tags", [])] if isinstance(proposal.get("tags", []), list) else [],
                status=str(proposal.get("status") or "seed"), parent_id=parent_id,
            ))
        except Exception as error:
            raise _friendly_error(error) from error

    def operation() -> dict[str, Any]:
        try:
            return api_create_codex_checkpoint(CodexCheckpointCreate(
                summary=summary, task_title=task_title, project_id=destination["id"], proposals=parsed,
            ))
        except Exception as error:
            raise _friendly_error(error) from error

    return _idempotent("create_codex_checkpoint", idempotency_key, operation)


@mcp.tool(title="Attach a local file to an IdeaMiner idea", annotations=LOCAL_WRITE)
def attach_file(
    reference: str,
    path: str,
    storage_mode: Literal["linked", "managed"] = "linked",
    idempotency_key: str = "",
) -> dict[str, Any]:
    """Attach a local file when explicitly requested. Managed mode copies it into the project's managed workspace."""
    idea = _resolve_idea(reference)

    def operation() -> dict[str, Any]:
        try:
            return api_attach_file(idea["id"], AttachmentCreate(path=path, storage_mode=storage_mode))
        except Exception as error:
            raise _friendly_error(error) from error

    return {"attachment": _idempotent("attach_file", idempotency_key, operation)}


def _app_base_url() -> str:
    if not (ROOT / "web-dist" / "index.html").is_file():
        return APP_URL

    local_app_data = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    server_url_file = local_app_data / "IdeaMiner" / "server.url"
    try:
        candidate = server_url_file.read_text(encoding="utf-8").strip()
        parsed = urlparse(candidate)
        if parsed.scheme == "http" and parsed.hostname == "127.0.0.1" and parsed.port:
            return f"http://127.0.0.1:{parsed.port}"
    except (OSError, ValueError):
        pass
    return "http://127.0.0.1:8000"


def _api_is_ready(base_url: str | None = None) -> bool:
    try:
        health_url = f"{base_url}/api/health" if base_url else API_HEALTH_URL
        with urllib.request.urlopen(health_url, timeout=1) as response:
            return response.status == 200
    except (OSError, urllib.error.URLError):
        return False


@mcp.tool(
    title="Open the IdeaMiner app",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False),
)
def open_ideaminer(reference: str = "") -> dict[str, Any]:
    """Start the local IdeaMiner browser app if needed and open it, optionally focused on one idea."""
    idea = _resolve_idea(reference) if reference.strip() else None
    packaged = (ROOT / "web-dist" / "index.html").is_file()
    base_url = _app_base_url() if packaged else APP_URL
    start_path = f"/?idea={idea['id']}" if idea else "/"
    url = f"{base_url}{start_path}"
    started = False
    if not _api_is_ready(base_url if packaged else None):
        launcher = ROOT / "launcher.py"
        if not launcher.is_file():
            raise ValueError(f"IdeaMiner launcher was not found at {launcher}")
        creation_flags = 0
        if os.name == "nt":
            creation_flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "CREATE_NO_WINDOW", 0)
        launcher_environment = os.environ.copy()
        if packaged:
            launcher_environment["IDEAMINER_START_PATH"] = start_path
        else:
            launcher_environment["IDEAMINER_START_URL"] = url
        subprocess.Popen(
            [sys.executable, str(launcher)],
            cwd=ROOT,
            env=launcher_environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creation_flags,
            close_fds=True,
        )
        started = True
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            base_url = _app_base_url() if packaged else APP_URL
            if _api_is_ready(base_url if packaged else None):
                break
            time.sleep(0.25)
        url = f"{base_url}{start_path}"
    if not started:
        webbrowser.open(url)
    return {"status": "opened", "started": started, "url": url, "idea_id": idea["id"] if idea else None}


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
