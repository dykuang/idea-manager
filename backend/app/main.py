from __future__ import annotations

import json
import hashlib
import mimetypes
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import uuid
import xml.etree.ElementTree as ET
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from fastapi import BackgroundTasks, FastAPI, File, HTTPException, Query, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from .agent_profiles import CredentialStoreError, credential_store_available, delete_api_key, get_api_key, load_store, reset_profile, save_api_key, save_profile, set_active_provider
from .agent_sessions import router as agent_sessions_router, save_chat_turn
from .database import DB_PATH, db, init_db
from .experiments import router as experiments_router
from .research_insights import router as research_insights_router
from .serendipity import router as serendipity_router
from .schemas import AgentConnectionCreate, AgentProposalResolution, AgentResultSave, AgentRunRequest, AttachmentCreate, CodexCheckpointCreate, DreamRunRequest, ImportPreviewRequest, ImportRequest, IdeaAttachmentUpdate, IdeaCreate, IdeaUpdate, PathChoice, ProjectAssignment, ProjectCreate, ProjectGroupCreate, RelationCreate, TagBulkUpdate, TagMerge, TagRename, TagSettingsUpdate
from .semantic import DIMENSIONS as SEMANTIC_DIMENSIONS, MODEL as SEMANTIC_MODEL, rebuild as rebuild_semantic_index, similarity as semantic_similarity


def _tags(connection: sqlite3.Connection, idea_id: int) -> list[str]:
    rows = connection.execute(
        "SELECT t.name FROM tags t JOIN idea_tags it ON t.id=it.tag_id WHERE it.idea_id=? ORDER BY CASE WHEN t.name='dreams' THEN 0 ELSE 1 END, t.name",
        (idea_id,),
    ).fetchall()
    return [row["name"] for row in rows]


def _idea(connection: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    result["tags"] = _tags(connection, row["id"])
    result["figure_count"] = connection.execute(
        "SELECT COUNT(*) FROM idea_attachments WHERE idea_id=? AND asset_role='figure'", (row["id"],)
    ).fetchone()[0]
    return result


def _set_tags(connection: sqlite3.Connection, idea_id: int, tags: list[str]) -> None:
    clean = sorted({tag.strip().lower() for tag in tags if tag.strip()})
    connection.execute("DELETE FROM idea_tags WHERE idea_id=?", (idea_id,))
    for tag in clean:
        connection.execute("INSERT OR IGNORE INTO tags(name) VALUES (?)", (tag,))
        tag_id = connection.execute("SELECT id FROM tags WHERE name=? COLLATE NOCASE", (tag,)).fetchone()["id"]
        connection.execute("INSERT INTO idea_tags(idea_id, tag_id) VALUES (?, ?)", (idea_id, tag_id))
    _prune_orphan_tags(connection)


def _prune_orphan_tags(connection: sqlite3.Connection) -> int:
    cursor = connection.execute("DELETE FROM tags WHERE NOT EXISTS (SELECT 1 FROM idea_tags WHERE idea_tags.tag_id=tags.id)")
    return cursor.rowcount


def _fts_query(value: str) -> str:
    tokens = re.findall(r"[\w-]+", value, flags=re.UNICODE)
    return " AND ".join(f'"{token}"*' for token in tokens)


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolved_attachment_path(row: sqlite3.Row) -> Path:
    path = Path(row["path"])
    if row["storage_mode"] == "managed":
        if path.as_posix().startswith("assets/"):
            path = DB_PATH.parent / path
        else:
            path = Path(row["workspace_path"]) / path
    return path.resolve()


def _attachment(row: sqlite3.Row) -> dict[str, Any]:
    path = _resolved_attachment_path(row)
    result = {
        "id": row["id"], "project_id": row["project_id"], "display_name": row["display_name"],
        "storage_mode": row["storage_mode"], "mime_type": row["mime_type"],
        "size_bytes": row["size_bytes"], "content_hash": row["content_hash"],
        "created_at": row["created_at"], "absolute_path": str(path), "exists": path.is_file(),
    }
    if "asset_role" in row.keys():
        result.update({
            "asset_role": row["asset_role"], "caption": row["caption"],
            "sort_order": row["sort_order"], "is_cover": bool(row["is_cover"]),
            "preview_url": f"/api/attachments/{row['id']}/content" if row["asset_role"] == "figure" else None,
        })
    return result


def _attachment_rows(connection: sqlite3.Connection, where: str, params: list[Any]) -> list[dict[str, Any]]:
    rows = connection.execute(
        f"""SELECT DISTINCT a.*, p.workspace_path, ia.asset_role, ia.caption, ia.sort_order, ia.is_cover FROM attachments a
            JOIN projects p ON p.id=a.project_id
            JOIN idea_attachments ia ON ia.attachment_id=a.id
            JOIN ideas i ON i.id=ia.idea_id WHERE {where}
            ORDER BY CASE ia.asset_role WHEN 'figure' THEN 0 ELSE 1 END, ia.sort_order, a.display_name COLLATE NOCASE""",
        params,
    ).fetchall()
    return [_attachment(row) for row in rows]


def _pick_path(kind: str, initial_path: str = "") -> str:
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        initial = initial_path if initial_path and Path(initial_path).exists() else None
        selected = filedialog.askdirectory(initialdir=initial, title="Choose an IdeaMiner project folder") if kind == "folder" else filedialog.askopenfilename(initialdir=initial, title="Choose a file to attach")
        root.destroy()
        return str(selected or "")
    except Exception as error:
        raise HTTPException(501, f"The Windows file picker is unavailable: {error}") from error


AGENT_MODES = {
    "explore": "Explore the material, surface promising directions, hidden assumptions, and useful questions.",
    "elaborate": "Develop the selected material into clearer, more actionable research ideas.",
    "critique": "Stress-test the material. Identify weak assumptions, counterarguments, risks, and missing evidence.",
    "connect": "Find meaningful connections among the ideas and propose only relations that have a clear justification.",
    "synthesize": "Synthesize the material into a coherent research direction without erasing important disagreements.",
}

AGENT_PROVIDERS: dict[str, dict[str, Any]] = {
    "openai": {
        "label": "OpenAI", "base_url": "https://api.openai.com/v1", "model": "gpt-5.6-luna",
        "models": ["gpt-5.6-luna", "gpt-5.6-terra", "gpt-5.6-sol"],
        "reasoning_efforts": ["none", "low", "medium", "high", "xhigh", "max"],
        "default_effort": "medium", "api_style": "responses", "api_key_required": True,
        "key_env": "OPENAI_API_KEY", "model_env": "IDEAMINER_OPENAI_MODEL", "web_search": True,
    },
    "anthropic": {
        "label": "Anthropic", "base_url": "https://api.anthropic.com/v1", "model": "claude-sonnet-5",
        "models": ["claude-sonnet-5", "claude-opus-5"],
        "reasoning_efforts": ["none", "low", "medium", "high", "max"],
        "default_effort": "medium", "api_style": "anthropic", "api_key_required": True,
        "key_env": "ANTHROPIC_API_KEY", "model_env": "IDEAMINER_ANTHROPIC_MODEL", "web_search": False,
    },
    "deepseek": {
        "label": "DeepSeek", "base_url": "https://api.deepseek.com", "model": "deepseek-flash",
        "models": ["deepseek-flash", "deepseek-v4-pro"],
        "reasoning_efforts": ["none", "low", "high", "max"],
        "default_effort": "none", "api_style": "responses", "api_key_required": True,
        "key_env": "DEEPSEEK_API_KEY", "model_env": "IDEAMINER_DEEPSEEK_MODEL", "web_search": True,
    },
    "qwen": {
        "label": "Qwen", "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "model": "qwen3.8-flash",
        "models": ["qwen3.8-flash", "qwen3.8-max", "qwen3.7-plus"],
        "reasoning_efforts": ["none", "low", "medium", "xhigh"],
        "default_effort": "medium", "api_style": "responses", "api_key_required": True,
        "key_env": "DASHSCOPE_API_KEY", "model_env": "IDEAMINER_QWEN_MODEL", "web_search": False,
    },
    "local": {
        "label": "Local", "base_url": "http://127.0.0.1:11434/v1", "model": "gpt-oss:20b",
        "models": [], "reasoning_efforts": ["none"], "default_effort": "none",
        "api_style": "responses", "api_key_required": False,
        "key_env": "IDEAMINER_LOCAL_API_KEY", "model_env": "IDEAMINER_LOCAL_MODEL", "web_search": False,
    },
}


def _valid_base_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc) and not parsed.username and not parsed.password


def _agent_config_for(requested_provider: str) -> dict[str, Any]:
    store = load_store()
    if requested_provider == "custom":
        requested_provider = "local"
    if requested_provider not in AGENT_PROVIDERS:
        requested_provider = "openai"
    definition = AGENT_PROVIDERS[requested_provider]
    session = getattr(app.state, "agent_configs", {}).get(requested_provider, {})
    saved = store.get("profiles", {}).get(requested_provider, {})
    api_key = str(session.get("api_key", "")).strip()
    source = "session" if api_key else "none"
    if not api_key:
        api_key = get_api_key(requested_provider).strip()
        source = "secure_storage" if api_key else "none"
    if not api_key:
        api_key = os.environ.get(str(definition["key_env"]), "").strip()
        source = "environment" if api_key else "none"
    model = str(session.get("model") or saved.get("model") or os.environ.get(str(definition["model_env"]), "").strip() or definition["model"])
    base_url = str(session.get("base_url") or saved.get("base_url") or (os.environ.get("IDEAMINER_AGENT_BASE_URL", "").strip() if requested_provider == os.environ.get("IDEAMINER_AGENT_PROVIDER", "").strip().lower() else "") or definition["base_url"])
    reasoning_effort = str(session.get("reasoning_effort") or saved.get("reasoning_effort") or definition["default_effort"])
    key_required = bool(definition["api_key_required"])
    local_explicit = bool(session or saved or os.environ.get("IDEAMINER_LOCAL_MODEL", "").strip() or os.environ.get("IDEAMINER_AGENT_PROVIDER", "").strip().lower() == "local")
    configured = bool(model and base_url and (api_key or not key_required) and (requested_provider != "local" or local_explicit))
    return {
        "provider": requested_provider, "label": definition["label"], "api_key": api_key,
        "model": model, "base_url": base_url, "reasoning_effort": reasoning_effort,
        "web_search": definition["web_search"], "api_style": definition["api_style"],
        "source": source if configured else "none", "configured": configured,
    }


def _active_agent_config() -> dict[str, Any]:
    store = load_store()
    requested_provider = str(getattr(app.state, "active_agent_provider", "") or store.get("active_provider") or os.environ.get("IDEAMINER_AGENT_PROVIDER", "")).strip().lower()
    if requested_provider not in AGENT_PROVIDERS and requested_provider != "custom":
        requested_provider = "deepseek" if os.environ.get("DEEPSEEK_API_KEY", "").strip() and not os.environ.get("OPENAI_API_KEY", "").strip() else "openai"
    return _agent_config_for(requested_provider)


def _agent_context(connection: sqlite3.Connection, payload: AgentRunRequest) -> dict[str, Any]:
    clauses = ["COALESCE(p.system_key, '') <> 'recycle'"]
    params: list[Any] = []
    if payload.scope_type == "project":
        if payload.scope_id is None or not connection.execute("SELECT 1 FROM projects WHERE id=?", (payload.scope_id,)).fetchone():
            raise HTTPException(400, "Choose a valid project for the agent context")
        clauses = ["i.project_id=?"]
        params.append(payload.scope_id)
    elif payload.scope_type == "group":
        if payload.scope_id is None or not connection.execute("SELECT 1 FROM project_groups WHERE id=?", (payload.scope_id,)).fetchone():
            raise HTTPException(400, "Choose a valid project group for the agent context")
        clauses.append("p.group_id=?")
        params.append(payload.scope_id)
    rows = connection.execute(
        f"""SELECT i.*, p.name project_name FROM ideas i
            LEFT JOIN projects p ON p.id=i.project_id
            WHERE {' AND '.join(clauses)} ORDER BY i.updated_at DESC LIMIT 40""",
        params,
    ).fetchall()
    ideas = [
        {
            "id": row["id"],
            "title": row["title"],
            "content": row["content"],
            "status": row["status"],
            "tags": _tags(connection, row["id"]),
            "project_id": row["project_id"],
            "project": row["project_name"],
        }
        for row in rows
    ]
    if payload.idea_id is not None and not any(item["id"] == payload.idea_id for item in ideas):
        selected = connection.execute(
            """SELECT i.*, p.name project_name FROM ideas i
               LEFT JOIN projects p ON p.id=i.project_id WHERE i.id=?""",
            (payload.idea_id,),
        ).fetchone()
        if not selected:
            raise HTTPException(404, "Selected idea not found")
        ideas.insert(0, {
            "id": selected["id"], "title": selected["title"], "content": selected["content"],
            "status": selected["status"], "tags": _tags(connection, selected["id"]),
            "project_id": selected["project_id"], "project": selected["project_name"],
        })
    additional_ids = list(dict.fromkeys(payload.context_idea_ids))[:20]
    if additional_ids:
        marks = ",".join("?" for _ in additional_ids)
        selected_rows = connection.execute(
            f"""SELECT i.*, p.name project_name FROM ideas i
                LEFT JOIN projects p ON p.id=i.project_id
                WHERE i.id IN ({marks}) AND COALESCE(p.system_key, '') <> 'recycle'""",
            additional_ids,
        ).fetchall()
        selected_by_id = {int(row["id"]): row for row in selected_rows}
        if set(additional_ids) != set(selected_by_id):
            raise HTTPException(404, "One or more selected context ideas were not found")
        for selected_id in additional_ids:
            if any(item["id"] == selected_id for item in ideas):
                continue
            selected = selected_by_id[selected_id]
            ideas.append({
                "id": selected["id"], "title": selected["title"], "content": selected["content"],
                "status": selected["status"], "tags": _tags(connection, selected["id"]),
                "project_id": selected["project_id"], "project": selected["project_name"],
            })
    idea_ids = [item["id"] for item in ideas]
    relations: list[dict[str, Any]] = []
    if idea_ids:
        marks = ",".join("?" for _ in idea_ids)
        relation_rows = connection.execute(
            f"""SELECT r.id, r.source_id, r.target_id, r.relation_type, r.note,
                       s.title source_title, t.title target_title
                FROM relations r JOIN ideas s ON s.id=r.source_id JOIN ideas t ON t.id=r.target_id
                WHERE r.source_id IN ({marks}) AND r.target_id IN ({marks}) LIMIT 120""",
            [*idea_ids, *idea_ids],
        ).fetchall()
        relations = [dict(row) for row in relation_rows]
    files: list[dict[str, Any]] = []
    if payload.attachment_ids:
        unique_ids = list(dict.fromkeys(payload.attachment_ids))[:12]
        if not idea_ids:
            raise HTTPException(400, "No ideas are available for the selected file context")
        attachment_marks = ",".join("?" for _ in unique_ids)
        idea_marks = ",".join("?" for _ in idea_ids)
        attachment_rows = connection.execute(
            f"""SELECT DISTINCT a.*, p.workspace_path FROM attachments a
                JOIN projects p ON p.id=a.project_id
                JOIN idea_attachments ia ON ia.attachment_id=a.id
                WHERE a.id IN ({attachment_marks}) AND ia.idea_id IN ({idea_marks})""",
            [*unique_ids, *idea_ids],
        ).fetchall()
        found_ids = {row["id"] for row in attachment_rows}
        if found_ids != set(unique_ids):
            raise HTTPException(400, "One or more selected files are outside the current idea scope")
        text_extensions = {".txt", ".md", ".markdown", ".csv", ".tsv", ".json", ".yaml", ".yml", ".py", ".r", ".js", ".ts", ".tsx", ".jsx", ".tex", ".log"}
        remaining = 1_500_000
        for row in attachment_rows:
            path = _resolved_attachment_path(row)
            item: dict[str, Any] = {"id": row["id"], "name": row["display_name"], "path": str(path), "sha256": row["content_hash"]}
            if not path.is_file():
                item["note"] = "File is currently missing and its contents were not included."
            elif path.suffix.lower() not in text_extensions and not str(row["mime_type"]).startswith("text/"):
                item["note"] = "Binary file metadata only; content extraction is not supported yet."
            elif remaining <= 0:
                item["note"] = "File omitted because the selected-file context limit was reached."
            else:
                data = path.read_bytes()[: min(500_000, remaining)]
                remaining -= len(data)
                item["content"] = data.decode("utf-8", errors="replace")
                if path.stat().st_size > len(data):
                    item["note"] = "Content was truncated for this agent run."
            files.append(item)
    return {
        "selected_idea_id": payload.idea_id,
        "scope": {"type": payload.scope_type, "id": payload.scope_id},
        "ideas": ideas,
        "relations": relations,
        "files": files,
        "privacy_note": "Original raw captures are not included. Attached file contents are sent only when explicitly selected for this run.",
    }


def _agent_tool() -> dict[str, Any]:
    proposal_properties: dict[str, Any] = {
        "action": {"type": "string", "enum": ["create_idea", "update_idea", "create_relation"]},
        "title": {"type": "string"},
        "rationale": {"type": "string"},
        "idea_id": {"type": "integer"},
        "project_id": {"type": "integer"},
        "idea_title": {"type": "string"},
        "content": {"type": "string"},
        "status": {"type": "string", "enum": ["seed", "exploring", "promising", "parked"]},
        "tags": {"type": "array", "items": {"type": "string"}},
        "source_id": {"type": "integer"},
        "target_id": {"type": "integer"},
        "relation_type": {"type": "string"},
        "note": {"type": "string"},
    }
    return {
        "type": "function",
        "name": "submit_research_result",
        "description": "Return the research response and zero to five optional, user-reviewable IdeaMiner proposals.",
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "answer": {"type": "string"},
                "proposals": {
                    "type": "array", "maxItems": 5,
                    "items": {
                        "type": "object", "properties": proposal_properties,
                        "required": list(proposal_properties), "additionalProperties": False,
                    },
                },
            },
            "required": ["answer", "proposals"],
            "additionalProperties": False,
        },
    }


def _response_result(result: dict[str, Any], provider_label: str) -> tuple[str, list[dict[str, Any]]]:
    text_parts: list[str] = []
    for item in result.get("output", []):
        if item.get("type") == "function_call" and item.get("name") == "submit_research_result":
            try:
                arguments = item.get("arguments", {})
                structured = json.loads(arguments) if isinstance(arguments, str) else arguments
                proposals = structured.get("proposals", [])
                return str(structured.get("answer", "")), proposals[:5] if isinstance(proposals, list) else []
            except (AttributeError, TypeError, ValueError) as error:
                raise HTTPException(502, f"{provider_label} returned an unreadable structured result") from error
        if item.get("type") == "message":
            for content in item.get("content", []):
                if content.get("type") in {"output_text", "text"} and content.get("text"):
                    text_parts.append(str(content["text"]))
    if result.get("output_text"):
        text_parts.append(str(result["output_text"]))
    if text_parts:
        return "\n\n".join(text_parts), []
    raise HTTPException(502, f"{provider_label} did not return a readable research result")


def _anthropic_result(result: dict[str, Any], provider_label: str) -> tuple[str, list[dict[str, Any]]]:
    text_parts: list[str] = []
    for item in result.get("content", []):
        if item.get("type") == "tool_use" and item.get("name") == "submit_research_result":
            structured = item.get("input", {})
            if not isinstance(structured, dict):
                raise HTTPException(502, f"{provider_label} returned an unreadable structured result")
            proposals = structured.get("proposals", [])
            return str(structured.get("answer", "")), proposals[:5] if isinstance(proposals, list) else []
        if item.get("type") == "text" and item.get("text"):
            text_parts.append(str(item["text"]))
    if text_parts:
        return "\n\n".join(text_parts), []
    raise HTTPException(502, f"{provider_label} did not return a readable research result")


async def _call_agent_provider(config: dict[str, Any], *, model: str, reasoning_effort: str, instructions: str, input_text: str, web_search: bool = False) -> tuple[str, list[dict[str, Any]]]:
    provider, provider_label = str(config["provider"]), str(config["label"])
    api_key = str(config.get("api_key", "")).strip()
    endpoint = str(config["base_url"]).rstrip("/")
    headers = {"Content-Type": "application/json"}
    if config["api_style"] == "anthropic":
        if not endpoint.endswith("/messages"):
            endpoint += "/messages"
        headers.update({"x-api-key": api_key, "anthropic-version": "2023-06-01"})
        tool = _agent_tool()
        body: dict[str, Any] = {
            "model": model, "max_tokens": 8192, "system": instructions,
            "messages": [{"role": "user", "content": input_text}],
            "tools": [{"name": tool["name"], "description": tool["description"], "input_schema": tool["parameters"], "strict": True}],
            "tool_choice": {"type": "tool", "name": "submit_research_result", "disable_parallel_tool_use": True},
        }
        if reasoning_effort and reasoning_effort != "none":
            body["thinking"] = {"type": "adaptive"}
            body["output_config"] = {"effort": reasoning_effort}
    else:
        if not endpoint.endswith("/responses"):
            endpoint += "/responses"
        tools: list[dict[str, Any]] = [_agent_tool()]
        if web_search:
            tools.insert(0, {"type": "web_search"})
        body = {"model": model, "instructions": instructions, "input": input_text, "tools": tools, "store": False}
        if reasoning_effort:
            body["reasoning"] = {"effort": reasoning_effort}
        if provider == "openai":
            body["tool_choice"] = {"type": "function", "name": "submit_research_result"}
        elif provider == "qwen":
            body["tool_choice"] = "required"
        elif provider == "deepseek" and reasoning_effort == "none":
            body["tool_choice"] = {"type": "function", "name": "submit_research_result"}
        elif provider == "local":
            body["tool_choice"] = "auto"
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
    try:
        async with httpx.AsyncClient(timeout=90) as client:
            response = await client.post(endpoint, headers=headers, json=body)
    except httpx.RequestError as error:
        raise HTTPException(502, f"Could not reach {provider_label}: {error}") from error
    if response.status_code >= 400:
        try:
            error_body = response.json().get("error", {})
            message = error_body.get("message", response.text) if isinstance(error_body, dict) else str(error_body)
        except ValueError:
            message = response.text
        raise HTTPException(502, f"{provider_label} request failed: {message}")
    result = response.json()
    return _anthropic_result(result, provider_label) if config["api_style"] == "anthropic" else _response_result(result, provider_label)


async def _provider_agent(payload: AgentRunRequest, context: dict[str, Any]) -> tuple[str, list[dict[str, Any]], str, str]:
    config = _active_agent_config()
    if not config["configured"]:
        raise HTTPException(409, "No agent provider is configured. Connect one in Agent Workspace first.")
    provider = str(config["provider"])
    provider_label = str(config["label"])
    model = payload.model.strip() or str(config["model"])
    reasoning_effort = payload.reasoning_effort or str(config["reasoning_effort"])
    if payload.web_search and not config["web_search"]:
        raise HTTPException(400, f"{provider_label} is not configured for server-side web search")
    instructions = f"""You are IdeaMiner's research partner. {AGENT_MODES[payload.mode]}
Use only IDs that exist in the supplied context. Do not claim to have changed the database.
Proposals are optional and must be concrete. For unused proposal fields use 0 or an empty string/list.
For create_idea, provide idea_title, content, status, tags, and a valid project_id.
For update_idea, provide a valid idea_id and the complete proposed title/content/status/tags.
For create_relation, provide valid distinct source_id/target_id, relation_type, and note.
Never expose a raw reference such as "Idea #4" in the answer. Refer to a supplied idea with the stable token [[idea:4]]; IdeaMiner will display its current title. When the reference represents a meaningful dependency, also include a create_relation proposal so the graph remains the source of truth.
When referring to an explicitly supplied local file, use its stable token [[file:ID]] instead of a machine-specific path.
When elaborating, make the answer a self-contained research note suitable for saving. Start it with one level-one Markdown heading containing a concise refined title.
Always finish by calling submit_research_result. Write the answer in clear Markdown."""
    conversation = "\n\n".join(
        f"{message.role.title()}: {message.content}" for message in payload.conversation
    )
    chat_input = f"Conversation so far:\n{conversation}\n\n" if conversation else ""
    answer, proposals = await _call_agent_provider(
        config, model=model, reasoning_effort=reasoning_effort, instructions=instructions,
        input_text=f"{chat_input}User message:\n{payload.prompt}\n\nIdeaMiner context:\n{json.dumps(context, ensure_ascii=False)}",
        web_search=payload.web_search,
    )
    return answer, proposals, model, provider


def _dream_context(connection: sqlite3.Connection, idea_ids: list[int]) -> dict[str, Any]:
    marks = ",".join("?" for _ in idea_ids)
    rows = connection.execute(
        f"""SELECT i.*, p.name project_name FROM ideas i JOIN projects p ON p.id=i.project_id
            WHERE i.id IN ({marks}) AND COALESCE(p.system_key, '') <> 'recycle'""", idea_ids,
    ).fetchall()
    found = {int(row["id"]): row for row in rows}
    if len(found) != len(idea_ids):
        raise HTTPException(400, "One or more dream source ideas are missing or in recycle")
    selected = [{"id": row["id"], "title": row["title"], "content": row["content"], "status": row["status"],
                 "tags": _tags(connection, row["id"]), "project_id": row["project_id"], "project": row["project_name"]}
                for row in (found[idea_id] for idea_id in idea_ids)]
    relation_rows = connection.execute(
        f"""SELECT r.id, r.source_id, r.target_id, r.relation_type, r.note FROM relations r
            WHERE r.source_id IN ({marks}) AND r.target_id IN ({marks})""", [*idea_ids, *idea_ids],
    ).fetchall()
    return {"selected_idea_ids": idea_ids, "ideas": selected, "relations": [dict(row) for row in relation_rows],
            "privacy_note": "Original raw captures and local file contents are excluded from Dream."}


async def _provider_dream(payload: DreamRunRequest, context: dict[str, Any], destination_project: dict[str, Any]) -> tuple[str, list[dict[str, Any]], str, str]:
    config = _active_agent_config()
    if not config["configured"]:
        raise HTTPException(409, "No agent provider is configured. Connect one in Agent Workspace first.")
    provider = str(config["provider"])
    model = payload.model.strip() or str(config["model"])
    instructions = f"""You are IdeaMiner's Dream partner. Combine the selected research ideas into surprising but rigorous, testable descendant directions.
The selected ideas may come from different projects; treat their tensions and complementarities as useful material. Do not claim to have changed the database.
Return two to five distinct create_idea proposals, each with a concise title, a self-contained Markdown note, status, and optional additional tags. The destination project is {destination_project['name']} (ID {destination_project['id']}). Do not make updates or relations yourself.
Every proposed idea will be tagged DREAMS and linked to every selected source by IdeaMiner after the user reviews and applies it. Refer to sources only with stable tokens such as [[idea:12]], never plain "Idea #12".
The user's optional dream guidance is: {payload.prompt or 'None — look for the most promising unexpected combinations.'}
Always finish by calling submit_research_result. Write a brief Markdown synthesis in answer, followed by structured proposals."""
    answer, proposals = await _call_agent_provider(
        config, model=model, reasoning_effort=str(config["reasoning_effort"]), instructions=instructions,
        input_text=f"Dream source context:\n{json.dumps(context, ensure_ascii=False)}",
    )
    return answer, proposals, model, provider


def _agent_document(response_text: str, fallback_title: str) -> tuple[str, str]:
    text = response_text.strip()
    lines = text.splitlines()
    if lines:
        heading = re.match(r"^#\s+(.+?)\s*$", lines[0])
        if heading:
            title = heading.group(1).strip()[:240]
            body = "\n".join(lines[1:]).strip()
            return title or fallback_title[:240], body or text
    return fallback_title[:240], text


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title="IdeaMiner API", version="0.1.0", lifespan=lifespan)
app.include_router(agent_sessions_router)
app.include_router(experiments_router)
app.include_router(research_insights_router)
app.include_router(serendipity_router)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/library-state")
def library_state() -> dict[str, int]:
    with db() as connection:
        row = connection.execute("SELECT revision FROM library_state WHERE id=1").fetchone()
        return {"revision": row["revision"]}


def _active_scope_clause(project_id: int | None, group_id: int | None) -> tuple[str, list[Any]]:
    if project_id is not None:
        return "i.project_id=? AND COALESCE(p.system_key, '')<>'recycle'", [project_id]
    if group_id is not None:
        return "p.group_id=? AND COALESCE(p.system_key, '')<>'recycle'", [group_id]
    return "COALESCE(p.system_key, '')<>'recycle'", []


def _semantic_rows(connection: sqlite3.Connection, project_id: int | None = None, group_id: int | None = None) -> list[sqlite3.Row]:
    clause, params = _active_scope_clause(project_id, group_id)
    return connection.execute(
        f"""SELECT i.*, p.name project_name, e.dimensions, e.vector
            FROM idea_embeddings e JOIN ideas i ON i.id=e.idea_id JOIN projects p ON p.id=i.project_id
            WHERE e.model=? AND {clause}""",
        [SEMANTIC_MODEL, *params],
    ).fetchall()


def _linked_pairs(connection: sqlite3.Connection) -> set[tuple[int, int]]:
    return {tuple(sorted((int(row["source_id"]), int(row["target_id"])))) for row in connection.execute("SELECT source_id, target_id FROM relations")}


def _semantic_opportunities(connection: sqlite3.Connection, project_id: int | None, group_id: int | None, limit: int) -> list[dict[str, Any]]:
    rows = _semantic_rows(connection, project_id, group_id)
    linked = _linked_pairs(connection)
    opportunities: list[dict[str, Any]] = []
    for left_index, left in enumerate(rows):
        for right in rows[left_index + 1:]:
            pair = tuple(sorted((int(left["id"]), int(right["id"]))))
            if pair in linked:
                continue
            score = semantic_similarity(left["vector"], right["vector"], left["dimensions"])
            if score >= 0.24:
                opportunities.append({
                    "source_id": left["id"], "source_title": left["title"], "target_id": right["id"],
                    "target_title": right["title"], "score": round(score, 3),
                    "reason": "local semantic similarity; no direct relation",
                })
    return sorted(opportunities, key=lambda item: (-item["score"], item["source_title"], item["target_title"]))[:limit]


@app.get("/api/semantic/status")
def semantic_status() -> dict[str, Any]:
    with db() as connection:
        row = connection.execute(
            "SELECT COUNT(*) count, MAX(created_at) created_at FROM idea_embeddings WHERE model=?", (SEMANTIC_MODEL,)
        ).fetchone()
        return {"ready": bool(row["count"]), "model": SEMANTIC_MODEL, "dimensions": SEMANTIC_DIMENSIONS,
                "indexed_ideas": row["count"], "created_at": row["created_at"]}


@app.post("/api/semantic/rebuild")
def rebuild_semantic() -> dict[str, Any]:
    with db() as connection:
        rebuilt = rebuild_semantic_index(connection)
        row = connection.execute(
            "SELECT COUNT(*) count, MAX(created_at) created_at FROM idea_embeddings WHERE model=?", (SEMANTIC_MODEL,)
        ).fetchone()
        return {"ready": bool(row["count"]), **rebuilt, "created_at": row["created_at"]}


@app.get("/api/semantic/opportunities")
def semantic_opportunities(project_id: int | None = None, group_id: int | None = None, limit: int = Query(default=8, ge=1, le=40)) -> list[dict[str, Any]]:
    with db() as connection:
        return _semantic_opportunities(connection, project_id, group_id, limit)


@app.get("/api/ideas/{idea_id}/semantic-suggestions")
def semantic_suggestions(idea_id: int, project_id: int | None = None, limit: int = Query(default=5, ge=1, le=20)) -> list[dict[str, Any]]:
    with db() as connection:
        source = connection.execute("SELECT vector, dimensions FROM idea_embeddings WHERE idea_id=? AND model=?", (idea_id, SEMANTIC_MODEL)).fetchone()
        if not source:
            return []
        related_ids = {idea_id}
        related_ids.update(row["target_id"] for row in connection.execute("SELECT target_id FROM relations WHERE source_id=?", (idea_id,)))
        related_ids.update(row["source_id"] for row in connection.execute("SELECT source_id FROM relations WHERE target_id=?", (idea_id,)))
        candidates = _semantic_rows(connection, project_id, None)
        suggestions = []
        for row in candidates:
            if row["id"] in related_ids:
                continue
            score = semantic_similarity(source["vector"], row["vector"], source["dimensions"])
            if score >= 0.18:
                idea_row = connection.execute("SELECT * FROM ideas WHERE id=?", (row["id"],)).fetchone()
                suggestions.append({**_idea(connection, idea_row), "score": round(score, 3), "reason": "local semantic similarity"})
        return sorted(suggestions, key=lambda item: (-item["score"], item["title"]))[:limit]


@app.get("/api/review")
def weekly_review(project_id: int | None = None, group_id: int | None = None) -> dict[str, Any]:
    clause, params = _active_scope_clause(project_id, group_id)
    with db() as connection:
        rows = connection.execute(f"SELECT i.* FROM ideas i JOIN projects p ON p.id=i.project_id WHERE {clause} ORDER BY i.updated_at DESC", params).fetchall()
        ideas = [_idea(connection, row) for row in rows]
        ids = [item["id"] for item in ideas]
        marks = ",".join("?" for _ in ids)
        linked = set()
        if ids:
            for row in connection.execute(f"SELECT source_id, target_id FROM relations WHERE source_id IN ({marks}) OR target_id IN ({marks})", [*ids, *ids]):
                linked.add(row["source_id"]); linked.add(row["target_id"])
        new_captures = [item for item in ideas if connection.execute("SELECT julianday('now') - julianday(?) <= 7", (item["created_at"],)).fetchone()[0]]
        stale_seeds = [item for item in ideas if item["status"] == "seed" and connection.execute("SELECT julianday('now') - julianday(?) >= 14", (item["updated_at"],)).fetchone()[0]]
        run_scope = "1=1"
        run_params: list[Any] = []
        if project_id is not None:
            run_scope = "(r.scope_type='project' AND r.scope_id=?)"
            run_params = [project_id]
        elif group_id is not None:
            run_scope = "(r.scope_type='group' AND r.scope_id=? OR r.scope_type='project' AND EXISTS (SELECT 1 FROM projects rp WHERE rp.id=r.scope_id AND rp.group_id=?))"
            run_params = [group_id, group_id]
        proposal_rows = connection.execute(
            f"""SELECT ap.*, r.provider, r.model, r.created_at run_created_at FROM agent_proposals ap
                JOIN agent_runs r ON r.id=ap.run_id WHERE ap.status='pending' AND {run_scope}
                ORDER BY ap.created_at DESC""", run_params,
        ).fetchall()
        proposals = [{**dict(row), "payload": json.loads(row["payload_json"])} for row in proposal_rows]
        opportunities = _semantic_opportunities(connection, project_id, group_id, 8)
        return {
            "summary": {"active_ideas": len(ideas), "new_captures": len(new_captures), "unlinked": len([item for item in ideas if item["id"] not in linked]),
                        "stale_seeds": len(stale_seeds), "pending_proposals": len(proposals), "semantic_opportunities": len(opportunities)},
            "new_captures": new_captures[:12], "unlinked": [item for item in ideas if item["id"] not in linked][:12],
            "stale_seeds": stale_seeds[:12], "pending_proposals": proposals, "semantic_opportunities": opportunities,
        }


@app.get("/api/agent/status")
def agent_status() -> dict[str, Any]:
    config = _active_agent_config()
    profiles = []
    for provider, definition in AGENT_PROVIDERS.items():
        profile = _agent_config_for(provider)
        profiles.append({
            "id": provider, "label": definition["label"], "configured": profile["configured"],
            "configuration_source": profile["source"], "credential_stored": profile["source"] == "secure_storage",
            "model": profile["model"], "base_url": profile["base_url"], "reasoning_effort": profile["reasoning_effort"],
            "models": definition["models"], "reasoning_efforts": definition["reasoning_efforts"],
            "default_model": definition["model"], "default_base_url": definition["base_url"],
            "api_key_required": definition["api_key_required"], "web_search_supported": definition["web_search"],
        })
    return {
        "provider": config["provider"],
        "provider_label": config["label"],
        "configured": config["configured"],
        "configuration_source": config["source"],
        "default_model": config["model"],
        "base_url": config["base_url"],
        "reasoning_effort": config["reasoning_effort"],
        "web_search_supported": config["web_search"],
        "providers": profiles,
        "credential_store_available": credential_store_available(),
        "capabilities": ["idea-context", "structured-proposals"] + (["web-search"] if config["web_search"] else []),
        "privacy": "Your chat messages and only the selected IdeaMiner context are sent. Original raw captures are excluded; local files require explicit selection. Remembered API keys stay in the operating system credential vault.",
    }


@app.post("/api/agent/config")
def configure_agent(payload: AgentConnectionCreate) -> dict[str, Any]:
    provider = "local" if payload.provider == "custom" else payload.provider
    definition = AGENT_PROVIDERS[provider]
    existing = _agent_config_for(provider)
    api_key = payload.api_key.get_secret_value().strip() or str(existing.get("api_key", "")).strip()
    model = payload.model or str(definition["model"])
    base_url = payload.base_url or str(definition["base_url"])
    reasoning_effort = payload.reasoning_effort or str(definition["default_effort"])
    if definition["api_key_required"] and len(api_key) < 8:
        raise HTTPException(400, f"Enter a valid {definition['label']} API key")
    if not model:
        raise HTTPException(400, "Enter a model name")
    if not _valid_base_url(base_url):
        raise HTTPException(400, "Enter a valid HTTP or HTTPS base URL without embedded credentials")
    if reasoning_effort not in definition["reasoning_efforts"]:
        raise HTTPException(400, f"Choose a reasoning effort supported by {definition['label']}")
    if payload.remember_api_key and api_key:
        try:
            save_api_key(provider, api_key)
        except CredentialStoreError as error:
            raise HTTPException(503, str(error)) from error
    configs = getattr(app.state, "agent_configs", {})
    configs[provider] = {
        "provider": provider, "api_key": "" if payload.remember_api_key else api_key,
        "model": model, "base_url": base_url, "reasoning_effort": reasoning_effort,
    }
    app.state.agent_configs = configs
    app.state.active_agent_provider = provider
    save_profile(provider, {"model": model, "base_url": base_url, "reasoning_effort": reasoning_effort})
    return agent_status()


@app.post("/api/agent/activate/{provider}")
def activate_agent_provider(provider: str) -> dict[str, Any]:
    if provider not in AGENT_PROVIDERS:
        raise HTTPException(404, "Unknown agent provider")
    app.state.active_agent_provider = provider
    set_active_provider(provider)
    return agent_status()


@app.delete("/api/agent/config")
def clear_agent_config() -> dict[str, Any]:
    provider = str(_active_agent_config()["provider"])
    configs = getattr(app.state, "agent_configs", {})
    configs.pop(provider, None)
    app.state.agent_configs = configs
    return agent_status()


@app.delete("/api/agent/config/{provider}")
def forget_agent_profile(provider: str) -> dict[str, Any]:
    if provider not in AGENT_PROVIDERS:
        raise HTTPException(404, "Unknown agent provider")
    configs = getattr(app.state, "agent_configs", {})
    configs.pop(provider, None)
    app.state.agent_configs = configs
    delete_api_key(provider)
    reset_profile(provider)
    return agent_status()


@app.post("/api/agent/runs")
async def run_agent(payload: AgentRunRequest) -> dict[str, Any]:
    with db() as connection:
        context = _agent_context(connection, payload)
    answer, raw_proposals, model, provider = await _provider_agent(payload, context)
    allowed_actions = {"create_idea", "update_idea", "create_relation"}
    stored_context = {**context, "files": [{key: value for key, value in item.items() if key != "content"} for item in context["files"]]}
    with db() as connection:
        cursor = connection.execute(
            """INSERT INTO agent_runs(provider, model, prompt, mode, scope_type, scope_id, idea_id,
                                      context_json, response_text, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'completed')""",
            (provider, model, payload.prompt, payload.mode, payload.scope_type, payload.scope_id, payload.idea_id,
             json.dumps(stored_context, ensure_ascii=False), answer),
        )
        run_id = cursor.lastrowid
        proposals: list[dict[str, Any]] = []
        for proposal in raw_proposals:
            if not isinstance(proposal, dict) or proposal.get("action") not in allowed_actions:
                continue
            action = proposal["action"]
            title = str(proposal.get("title") or action.replace("_", " ").title())[:240]
            rationale = str(proposal.get("rationale", ""))[:1000]
            proposal_payload = {
                key: proposal.get(key)
                for key in ("idea_id", "project_id", "idea_title", "content", "status", "tags", "source_id", "target_id", "relation_type", "note")
            }
            proposal_cursor = connection.execute(
                "INSERT INTO agent_proposals(run_id, action_type, title, rationale, payload_json) VALUES (?, ?, ?, ?, ?)",
                (run_id, action, title, rationale, json.dumps(proposal_payload, ensure_ascii=False)),
            )
            proposals.append({
                "id": proposal_cursor.lastrowid, "run_id": run_id, "action_type": action,
                "title": title, "rationale": rationale, "payload": proposal_payload, "status": "pending",
            })
        session_id = save_chat_turn(
            connection,
            session_id=payload.session_id,
            run_id=int(run_id),
            prompt=payload.prompt,
            answer=answer,
            provider=provider,
            model=model,
            scope_type=payload.scope_type,
            scope_id=payload.scope_id,
            idea_id=payload.idea_id,
            context_idea_ids=payload.context_idea_ids,
            attachment_ids=payload.attachment_ids,
        )
    return {
        "id": run_id, "session_id": session_id, "provider": provider, "model": model, "answer": answer,
        "proposals": proposals,
        "context_summary": {"ideas": len(context["ideas"]), "relations": len(context["relations"]), "files": len(context["files"]), "raw_text_shared": False},
    }


@app.post("/api/dreams")
async def dream_ideas(payload: DreamRunRequest) -> dict[str, Any]:
    with db() as connection:
        context = _dream_context(connection, payload.idea_ids)
        project_id = payload.project_id
        if project_id is None:
            project_id = connection.execute("SELECT id FROM projects WHERE system_key='random_chat'").fetchone()["id"]
        project = connection.execute("SELECT id, name, system_key FROM projects WHERE id=?", (project_id,)).fetchone()
        if not project or project["system_key"] == "recycle":
            raise HTTPException(400, "Choose an active project for Dream ideas")
    answer, raw_proposals, model, provider = await _provider_dream(payload, context, project)
    with db() as connection:
        cursor = connection.execute(
            """INSERT INTO agent_runs(provider, model, prompt, mode, scope_type, scope_id, context_json, response_text, status)
               VALUES (?, ?, ?, 'dream', 'dream', ?, ?, ?, 'completed')""",
            (provider, model, payload.prompt or "Dream selected ideas", project_id, json.dumps(context, ensure_ascii=False), answer),
        )
        run_id = int(cursor.lastrowid)
        proposals: list[dict[str, Any]] = []
        for raw in raw_proposals:
            if not isinstance(raw, dict) or raw.get("action") != "create_idea":
                continue
            title = str(raw.get("idea_title") or raw.get("title") or "Dream direction").strip()[:240]
            extra_tags = raw.get("tags") if isinstance(raw.get("tags"), list) else []
            tags = list(dict.fromkeys(["dreams", *[str(tag).strip().lower() for tag in extra_tags if str(tag).strip()]]))
            proposal_payload = {"project_id": project_id, "idea_title": title, "content": str(raw.get("content") or ""),
                                "status": raw.get("status") if raw.get("status") in ("seed", "exploring", "promising", "parked") else "seed",
                                "tags": tags, "source_ids": payload.idea_ids}
            proposal_cursor = connection.execute(
                "INSERT INTO agent_proposals(run_id, action_type, title, rationale, payload_json) VALUES (?, 'create_idea', ?, ?, ?)",
                (run_id, title, str(raw.get("rationale") or "A Dream combination of the selected ideas.")[:1000], json.dumps(proposal_payload, ensure_ascii=False)),
            )
            proposals.append({"id": proposal_cursor.lastrowid, "run_id": run_id, "action_type": "create_idea", "title": title,
                              "rationale": str(raw.get("rationale") or "A Dream combination of the selected ideas.")[:1000], "payload": proposal_payload, "status": "pending"})
    return {"id": run_id, "provider": provider, "model": model, "answer": answer, "proposals": proposals,
            "context_summary": {"ideas": len(context["ideas"]), "relations": len(context["relations"]), "files": 0, "raw_text_shared": False}}


@app.post("/api/agent/runs/{run_id}/save")
def save_agent_result(run_id: int, save: AgentResultSave) -> dict[str, Any]:
    with db() as connection:
        run = connection.execute("SELECT * FROM agent_runs WHERE id=?", (run_id,)).fetchone()
        if not run:
            raise HTTPException(404, "Agent run not found")
        if run["mode"] != "elaborate" or run["idea_id"] is None:
            raise HTTPException(409, "Only an idea-focused elaboration can be saved directly")
        existing = connection.execute("SELECT action, idea_id FROM agent_run_saves WHERE run_id=?", (run_id,)).fetchone()
        if existing:
            raise HTTPException(409, f"This result was already saved with {existing['action']}")
        parent = connection.execute("SELECT * FROM ideas WHERE id=?", (run["idea_id"],)).fetchone()
        if not parent:
            raise HTTPException(404, "The original idea no longer exists")
        if not str(run["response_text"]).strip():
            raise HTTPException(409, "This agent run has no response to save")

        fallback = parent["title"] if save.action == "update_original" else f"{parent['title']} — elaborated"
        title, content = _agent_document(str(run["response_text"]), fallback)
        relation_id: int | None = None
        if save.action == "update_original":
            connection.execute(
                "INSERT INTO idea_revisions(idea_id, title, content) VALUES (?, ?, ?)",
                (parent["id"], parent["title"], parent["content"]),
            )
            connection.execute(
                "UPDATE ideas SET title=?, content=?, updated_at=strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id=?",
                (title, content, parent["id"]),
            )
            saved_id = int(parent["id"])
        else:
            provenance = f"Agent-generated descendant of idea #{parent['id']} via {run['provider']}/{run['model']} (run #{run_id}).\n\n{run['response_text']}"
            cursor = connection.execute(
                "INSERT INTO ideas(title, content, raw_text, status, project_id) VALUES (?, ?, ?, 'exploring', ?)",
                (title, content, provenance, parent["project_id"]),
            )
            saved_id = int(cursor.lastrowid)
            connection.execute(
                "INSERT INTO idea_tags(idea_id, tag_id) SELECT ?, tag_id FROM idea_tags WHERE idea_id=?",
                (saved_id, parent["id"]),
            )
            relation_cursor = connection.execute(
                "INSERT INTO relations(source_id, target_id, relation_type, note) VALUES (?, ?, 'develops-into', ?)",
                (parent["id"], saved_id, f"Created from agent elaboration run #{run_id}"),
            )
            relation_id = int(relation_cursor.lastrowid)

        connection.execute(
            "INSERT INTO agent_run_saves(run_id, action, idea_id) VALUES (?, ?, ?)",
            (run_id, save.action, saved_id),
        )
        saved = connection.execute("SELECT * FROM ideas WHERE id=?", (saved_id,)).fetchone()
        return {"action": save.action, "idea": _idea(connection, saved), "parent_id": int(parent["id"]), "relation_id": relation_id}


@app.post("/api/codex/checkpoints")
def create_codex_checkpoint(payload: CodexCheckpointCreate) -> dict[str, Any]:
    """Queue carefully selected Codex-session insights for explicit review in IdeaMiner."""
    with db() as connection:
        project_id = payload.project_id
        if project_id is None:
            project_id = connection.execute("SELECT id FROM projects WHERE system_key='random_chat'").fetchone()["id"]
        project = connection.execute("SELECT id, name, system_key FROM projects WHERE id=?", (project_id,)).fetchone()
        if not project or project["system_key"] == "recycle":
            raise HTTPException(400, "Choose an active project for a Codex checkpoint")
        for item in payload.proposals:
            if item.parent_id is not None and not connection.execute("SELECT 1 FROM ideas WHERE id=?", (item.parent_id,)).fetchone():
                raise HTTPException(400, f"Parent idea #{item.parent_id} no longer exists")
        task_title = payload.task_title or "Codex session checkpoint"
        cursor = connection.execute(
            """INSERT INTO agent_runs(provider, model, prompt, mode, scope_type, scope_id, context_json, response_text, status)
               VALUES ('codex', 'local-session', ?, 'checkpoint', 'project', ?, ?, ?, 'completed')""",
            (task_title, project_id, json.dumps({"origin": "codex_checkpoint"}), payload.summary),
        )
        run_id = int(cursor.lastrowid)
        proposals: list[dict[str, Any]] = []
        for item in payload.proposals:
            data = {"project_id": project_id, "idea_title": item.title, "content": item.content, "status": item.status, "tags": item.tags, "parent_id": item.parent_id}
            proposal_cursor = connection.execute(
                "INSERT INTO agent_proposals(run_id, action_type, title, rationale, payload_json) VALUES (?, 'create_idea', ?, ?, ?)",
                (run_id, item.title, "Proposed during a Codex session checkpoint; review before saving.", json.dumps(data, ensure_ascii=False)),
            )
            proposals.append({"id": proposal_cursor.lastrowid, "run_id": run_id, "action_type": "create_idea", "title": item.title,
                              "rationale": "Proposed during a Codex session checkpoint; review before saving.", "payload": data, "status": "pending"})
        return {"id": run_id, "project": {"id": project["id"], "name": project["name"]}, "summary": payload.summary, "proposals": proposals}


@app.post("/api/agent/proposals/{proposal_id}")
def resolve_agent_proposal(proposal_id: int, resolution: AgentProposalResolution) -> dict[str, Any]:
    with db() as connection:
        proposal = connection.execute("SELECT * FROM agent_proposals WHERE id=?", (proposal_id,)).fetchone()
        if not proposal:
            raise HTTPException(404, "Agent proposal not found")
        if proposal["status"] != "pending":
            raise HTTPException(409, f"This proposal is already {proposal['status']}")
        if resolution.action == "dismiss":
            connection.execute(
                "UPDATE agent_proposals SET status='dismissed', resolved_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
                (proposal_id,),
            )
            return {"id": proposal_id, "status": "dismissed"}

        data = json.loads(proposal["payload_json"])
        action = proposal["action_type"]
        result: dict[str, Any]
        if action == "create_idea":
            title = str(data.get("idea_title") or proposal["title"]).strip()[:240]
            content = str(data.get("content") or "")
            status = data.get("status") if data.get("status") in ("seed", "exploring", "promising", "parked") else "seed"
            project_id = int(data.get("project_id") or 0)
            project = connection.execute("SELECT id, system_key FROM projects WHERE id=?", (project_id,)).fetchone()
            if not project or project["system_key"] == "recycle":
                project_id = connection.execute("SELECT id FROM projects WHERE system_key='random_chat'").fetchone()["id"]
            raw_text = f"AI-generated proposal from agent run {proposal['run_id']}\n\n{title}\n\n{content}".strip()
            cursor = connection.execute(
                "INSERT INTO ideas(title, content, raw_text, status, project_id) VALUES (?, ?, ?, ?, ?)",
                (title, content, raw_text, status, project_id),
            )
            idea_id = cursor.lastrowid
            tags = data.get("tags") if isinstance(data.get("tags"), list) else []
            _set_tags(connection, idea_id, [str(tag) for tag in tags])
            result = {"created_idea_id": idea_id}
            source_ids = data.get("source_ids") if isinstance(data.get("source_ids"), list) else []
            dream_relations: list[int] = []
            for source_id in dict.fromkeys(int(item) for item in source_ids if isinstance(item, int) or str(item).isdigit()):
                if source_id == idea_id or not connection.execute("SELECT 1 FROM ideas WHERE id=?", (source_id,)).fetchone():
                    continue
                try:
                    relation = connection.execute(
                        "INSERT INTO relations(source_id, target_id, relation_type, note) VALUES (?, ?, 'inspired-by', ?)",
                        (source_id, idea_id, f"Spawned from Dream run #{proposal['run_id']}"),
                    )
                    dream_relations.append(int(relation.lastrowid))
                except sqlite3.IntegrityError:
                    continue
            if dream_relations:
                result["created_relation_ids"] = dream_relations
            parent_id = int(data.get("parent_id") or 0)
            if parent_id:
                parent = connection.execute("SELECT id FROM ideas WHERE id=?", (parent_id,)).fetchone()
                if parent:
                    try:
                        relation = connection.execute(
                            "INSERT INTO relations(source_id, target_id, relation_type, note) VALUES (?, ?, 'develops-into', ?)",
                            (parent_id, idea_id, f"Created from checkpoint proposal #{proposal_id}"),
                        )
                        result["created_relation_id"] = relation.lastrowid
                    except sqlite3.IntegrityError:
                        pass
        elif action == "update_idea":
            idea_id = int(data.get("idea_id") or 0)
            idea = connection.execute("SELECT * FROM ideas WHERE id=?", (idea_id,)).fetchone()
            if not idea:
                raise HTTPException(400, "The idea targeted by this proposal no longer exists")
            title = str(data.get("idea_title") or idea["title"]).strip()[:240]
            content = str(data.get("content") or "")
            status = data.get("status") if data.get("status") in ("seed", "exploring", "promising", "parked") else idea["status"]
            connection.execute("INSERT INTO idea_revisions(idea_id, title, content) VALUES (?, ?, ?)", (idea_id, idea["title"], idea["content"]))
            connection.execute(
                "UPDATE ideas SET title=?, content=?, status=?, updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
                (title, content, status, idea_id),
            )
            tags = data.get("tags") if isinstance(data.get("tags"), list) else []
            _set_tags(connection, idea_id, [str(tag) for tag in tags])
            result = {"updated_idea_id": idea_id}
        else:
            source_id, target_id = int(data.get("source_id") or 0), int(data.get("target_id") or 0)
            relation_type = str(data.get("relation_type") or "related-to").strip().lower()[:60]
            if source_id == target_id or not connection.execute("SELECT 1 FROM ideas WHERE id=?", (source_id,)).fetchone() or not connection.execute("SELECT 1 FROM ideas WHERE id=?", (target_id,)).fetchone():
                raise HTTPException(400, "The relation targets are invalid or no longer exist")
            try:
                cursor = connection.execute(
                    "INSERT INTO relations(source_id, target_id, relation_type, note) VALUES (?, ?, ?, ?)",
                    (source_id, target_id, relation_type, str(data.get("note") or "")[:500]),
                )
            except sqlite3.IntegrityError as error:
                raise HTTPException(409, "That relation already exists") from error
            result = {"created_relation_id": cursor.lastrowid}
        connection.execute(
            "UPDATE agent_proposals SET status='applied', resolved_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
            (proposal_id,),
        )
        return {"id": proposal_id, "status": "applied", **result}


@app.post("/api/system/quit")
def quit_application(background_tasks: BackgroundTasks) -> dict[str, str]:
    """Request a coordinated shutdown when running under the desktop launcher."""
    shutdown_handler = getattr(app.state, "shutdown_handler", None)
    if shutdown_handler is None:
        raise HTTPException(409, "Quit is available when IdeaMiner is started with start-ideaminer.bat")
    background_tasks.add_task(shutdown_handler)
    return {"status": "shutting_down"}


@app.get("/api/ideas")
def list_ideas(
    q: str = "",
    tag: list[str] = Query(default=[]),
    status: str | None = None,
    relation_type: str | None = None,
    project_id: int | None = None,
    group_id: int | None = None,
    include_recycle: bool = False,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    joins = ""
    if q.strip() and _fts_query(q):
        joins += " JOIN ideas_fts f ON f.rowid=i.id"
        clauses.append("ideas_fts MATCH ?")
        params.append(_fts_query(q))
    if status:
        clauses.append("i.status=?")
        params.append(status)
    for index, name in enumerate(tag):
        alias = f"tf{index}"
        joins += f" JOIN idea_tags it{index} ON it{index}.idea_id=i.id JOIN tags {alias} ON {alias}.id=it{index}.tag_id"
        clauses.append(f"{alias}.name=? COLLATE NOCASE")
        params.append(name)
    if relation_type:
        clauses.append("EXISTS (SELECT 1 FROM relations r WHERE (r.source_id=i.id OR r.target_id=i.id) AND r.relation_type=?)")
        params.append(relation_type)
    if project_id is not None:
        clauses.append("i.project_id=?")
        params.append(project_id)
    if group_id is not None:
        clauses.append("EXISTS (SELECT 1 FROM projects gp WHERE gp.id=i.project_id AND gp.group_id=?)")
        params.append(group_id)
    if project_id is None and group_id is None and not include_recycle:
        clauses.append("EXISTS (SELECT 1 FROM projects ap WHERE ap.id=i.project_id AND COALESCE(ap.system_key, '')<>'recycle')")
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    order = " ORDER BY bm25(ideas_fts), i.updated_at DESC" if q.strip() and _fts_query(q) else " ORDER BY i.updated_at DESC"
    with db() as connection:
        rows = connection.execute(f"SELECT DISTINCT i.* FROM ideas i{joins}{where}{order}", params).fetchall()
        return [_idea(connection, row) for row in rows]


@app.post("/api/ideas", status_code=201)
def create_idea(payload: IdeaCreate) -> dict[str, Any]:
    raw_text = payload.raw_text if payload.raw_text is not None else f"{payload.title}\n\n{payload.content}".strip()
    with db() as connection:
        project_id = payload.project_id
        if project_id is None:
            project_id = connection.execute("SELECT id FROM projects WHERE system_key='random_chat'").fetchone()["id"]
        project = connection.execute("SELECT id, system_key FROM projects WHERE id=?", (project_id,)).fetchone()
        if not project or project["system_key"] == "recycle":
            raise HTTPException(400, "Choose an active project")
        cursor = connection.execute(
            "INSERT INTO ideas(title, content, raw_text, status, project_id) VALUES (?, ?, ?, ?, ?)",
            (payload.title, payload.content, raw_text, payload.status, project_id),
        )
        idea_id = cursor.lastrowid
        _set_tags(connection, idea_id, payload.tags)
        row = connection.execute("SELECT * FROM ideas WHERE id=?", (idea_id,)).fetchone()
        return _idea(connection, row)


@app.get("/api/ideas/{idea_id}")
def get_idea(idea_id: int) -> dict[str, Any]:
    with db() as connection:
        row = connection.execute("SELECT * FROM ideas WHERE id=?", (idea_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Idea not found")
        result = _idea(connection, row)
        result["relations"] = [dict(item) for item in connection.execute(
            """SELECT r.*, s.title source_title, t.title target_title FROM relations r
               JOIN ideas s ON s.id=r.source_id JOIN ideas t ON t.id=r.target_id
               WHERE r.source_id=? OR r.target_id=? ORDER BY r.created_at DESC""",
            (idea_id, idea_id),
        ).fetchall()]
        result["attachments"] = _attachment_rows(connection, "ia.idea_id=?", [idea_id])
        return result


@app.put("/api/ideas/{idea_id}")
def update_idea(idea_id: int, payload: IdeaUpdate) -> dict[str, Any]:
    with db() as connection:
        connection.execute("BEGIN IMMEDIATE")
        old = connection.execute("SELECT * FROM ideas WHERE id=?", (idea_id,)).fetchone()
        if not old:
            raise HTTPException(404, "Idea not found")
        if payload.expected_updated_at is not None and payload.expected_updated_at != old["updated_at"]:
            raise HTTPException(409, "This idea changed after it was read. Reload it before updating.")
        connection.execute(
            "INSERT INTO idea_revisions(idea_id, title, content) VALUES (?, ?, ?)",
            (idea_id, old["title"], old["content"]),
        )
        connection.execute(
            "UPDATE ideas SET title=?, content=?, status=?, updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
            (payload.title, payload.content, payload.status, idea_id),
        )
        _set_tags(connection, idea_id, payload.tags)
        row = connection.execute("SELECT * FROM ideas WHERE id=?", (idea_id,)).fetchone()
        return _idea(connection, row)


@app.delete("/api/ideas/{idea_id}")
def delete_idea(idea_id: int, permanent: bool = False) -> dict[str, str]:
    with db() as connection:
        row = connection.execute(
            "SELECT i.id, p.system_key FROM ideas i LEFT JOIN projects p ON p.id=i.project_id WHERE i.id=?",
            (idea_id,),
        ).fetchone()
        if not row:
            raise HTTPException(404, "Idea not found")
        if permanent or row["system_key"] == "recycle":
            connection.execute("DELETE FROM ideas WHERE id=?", (idea_id,))
            _prune_orphan_tags(connection)
            return {"action": "deleted"}
        recycle_id = connection.execute("SELECT id FROM projects WHERE system_key='recycle'").fetchone()["id"]
        connection.execute(
            "UPDATE ideas SET project_id=?, updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
            (recycle_id, idea_id),
        )
        return {"action": "recycled"}


@app.post("/api/ideas/{idea_id}/move")
def move_idea(idea_id: int, payload: ProjectAssignment) -> dict[str, Any]:
    with db() as connection:
        idea = connection.execute("SELECT id FROM ideas WHERE id=?", (idea_id,)).fetchone()
        project = connection.execute("SELECT id, system_key FROM projects WHERE id=?", (payload.project_id,)).fetchone()
        if not idea:
            raise HTTPException(404, "Idea not found")
        if not project:
            raise HTTPException(404, "Project not found")
        connection.execute(
            "UPDATE ideas SET project_id=?, updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
            (payload.project_id, idea_id),
        )
        row = connection.execute("SELECT * FROM ideas WHERE id=?", (idea_id,)).fetchone()
        return _idea(connection, row)


@app.post("/api/ideas/{idea_id}/copy", status_code=201)
def copy_idea(idea_id: int, payload: ProjectAssignment) -> dict[str, Any]:
    with db() as connection:
        source = connection.execute("SELECT * FROM ideas WHERE id=?", (idea_id,)).fetchone()
        project = connection.execute("SELECT id, system_key FROM projects WHERE id=?", (payload.project_id,)).fetchone()
        if not source:
            raise HTTPException(404, "Idea not found")
        if not project or project["system_key"] == "recycle":
            raise HTTPException(400, "Choose an active project")
        cursor = connection.execute(
            "INSERT INTO ideas(title, content, raw_text, status, project_id) VALUES (?, ?, ?, ?, ?)",
            (source["title"], source["content"], source["raw_text"], source["status"], payload.project_id),
        )
        new_id = cursor.lastrowid
        connection.execute(
            "INSERT INTO idea_tags(idea_id, tag_id) SELECT ?, tag_id FROM idea_tags WHERE idea_id=?",
            (new_id, idea_id),
        )
        connection.execute(
            """INSERT INTO idea_attachments(idea_id, attachment_id, asset_role, caption, sort_order, is_cover)
               SELECT ?, attachment_id, asset_role, caption, sort_order, is_cover FROM idea_attachments WHERE idea_id=?""",
            (new_id, idea_id),
        )
        row = connection.execute("SELECT * FROM ideas WHERE id=?", (new_id,)).fetchone()
        return _idea(connection, row)


@app.get("/api/projects")
def list_projects() -> list[dict[str, Any]]:
    with db() as connection:
        rows = connection.execute(
            """SELECT p.*, g.name group_name, COUNT(i.id) idea_count
               FROM projects p LEFT JOIN project_groups g ON g.id=p.group_id
               LEFT JOIN ideas i ON i.project_id=p.id
               GROUP BY p.id ORDER BY CASE p.system_key WHEN 'random_chat' THEN 0 WHEN 'recycle' THEN 2 ELSE 1 END, p.name"""
        ).fetchall()
        return [dict(row) for row in rows]


@app.post("/api/projects", status_code=201)
def create_project(payload: ProjectCreate) -> dict[str, Any]:
    try:
        with db() as connection:
            if payload.group_id is not None and not connection.execute("SELECT id FROM project_groups WHERE id=?", (payload.group_id,)).fetchone():
                raise HTTPException(404, "Project group not found")
            if connection.execute("SELECT id FROM projects WHERE name=? COLLATE NOCASE", (payload.name,)).fetchone():
                raise HTTPException(409, "A project with that name already exists")
            workspace_path = payload.workspace_path.strip()
            if payload.workspace_mode != "library":
                selected = Path(workspace_path).expanduser()
                if not selected.is_dir():
                    raise HTTPException(400, "Choose an existing folder")
                if payload.workspace_mode == "managed":
                    safe_name = re.sub(r'[<>:"/\\|?*]+', "-", payload.name).strip(" .") or "IdeaMiner project"
                    project_folder = selected / safe_name
                    suffix = 2
                    while project_folder.exists():
                        project_folder = selected / f"{safe_name} ({suffix})"
                        suffix += 1
                    (project_folder / ".ideaminer" / "attachments").mkdir(parents=True)
                    (project_folder / ".ideaminer" / "exports").mkdir()
                    (project_folder / ".ideaminer" / "project.json").write_text(
                        json.dumps({"name": payload.name, "format": "IdeaMiner workspace", "version": 1}, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                    workspace_path = str(project_folder.resolve())
                else:
                    workspace_path = str(selected.resolve())
            cursor = connection.execute(
                "INSERT INTO projects(name, description, group_id, workspace_mode, workspace_path) VALUES (?, ?, ?, ?, ?)",
                (payload.name, payload.description, payload.group_id, payload.workspace_mode, workspace_path),
            )
            return dict(connection.execute(
                """SELECT p.*, g.name group_name, 0 idea_count FROM projects p
                   LEFT JOIN project_groups g ON g.id=p.group_id WHERE p.id=?""",
                (cursor.lastrowid,),
            ).fetchone())
    except sqlite3.IntegrityError as error:
        raise HTTPException(409, "A project with that name already exists") from error


@app.post("/api/system/pick-folder")
def pick_folder(payload: PathChoice) -> dict[str, str]:
    return {"path": _pick_path("folder", payload.initial_path)}


@app.post("/api/system/pick-file")
def pick_file(payload: PathChoice) -> dict[str, str]:
    return {"path": _pick_path("file", payload.initial_path)}


@app.get("/api/attachments")
def list_attachments(idea_id: int | None = None, project_id: int | None = None, group_id: int | None = None, idea_ids: list[int] = Query(default=[])) -> list[dict[str, Any]]:
    with db() as connection:
        selected_ids = list(dict.fromkeys(([idea_id] if idea_id is not None else []) + idea_ids))[:21]
        if selected_ids:
            marks = ",".join("?" for _ in selected_ids)
            extra = f"ia.idea_id IN ({marks})"
            extra_params: list[Any] = selected_ids
            if project_id is not None:
                extra = f"(i.project_id=? OR {extra})"; extra_params.insert(0, project_id)
            elif group_id is not None:
                extra = f"(i.project_id IN (SELECT id FROM projects WHERE group_id=?) OR {extra})"; extra_params.insert(0, group_id)
            elif idea_id is None:
                extra = f"(COALESCE(p.system_key, '') <> 'recycle' OR {extra})"
            return _attachment_rows(connection, extra, extra_params)
        if idea_id is not None:
            return _attachment_rows(connection, "ia.idea_id=?", [idea_id])
        if project_id is not None:
            return _attachment_rows(connection, "i.project_id=?", [project_id])
        if group_id is not None:
            return _attachment_rows(connection, "i.project_id IN (SELECT id FROM projects WHERE group_id=?)", [group_id])
        return _attachment_rows(connection, "i.project_id IN (SELECT id FROM projects WHERE COALESCE(system_key, '') <> 'recycle')", [])


@app.post("/api/ideas/{idea_id}/attachments", status_code=201)
def attach_file(idea_id: int, payload: AttachmentCreate) -> dict[str, Any]:
    source = Path(payload.path).expanduser().resolve()
    if not source.is_file():
        raise HTTPException(400, "Choose an existing file")
    with db() as connection:
        idea = connection.execute(
            """SELECT i.id, i.project_id, p.system_key, p.workspace_mode, p.workspace_path
               FROM ideas i JOIN projects p ON p.id=i.project_id WHERE i.id=?""",
            (idea_id,),
        ).fetchone()
        if not idea:
            raise HTTPException(404, "Idea not found")
        if idea["system_key"] == "recycle":
            raise HTTPException(409, "Restore this idea before attaching files")
        stored_path = str(source)
        if payload.storage_mode == "managed":
            if idea["workspace_mode"] != "managed" or not idea["workspace_path"]:
                raise HTTPException(409, "This project does not have a managed workspace")
            destination_dir = Path(idea["workspace_path"]) / ".ideaminer" / "attachments"
            destination_dir.mkdir(parents=True, exist_ok=True)
            destination = destination_dir / f"{uuid.uuid4().hex[:12]}-{source.name}"
            shutil.copy2(source, destination)
            stored_path = destination.relative_to(Path(idea["workspace_path"])).as_posix()
            measured = destination
        else:
            measured = source
        mime_type = mimetypes.guess_type(source.name)[0] or "application/octet-stream"
        connection.execute(
            """INSERT INTO attachments(project_id, display_name, path, storage_mode, mime_type, size_bytes, modified_at, content_hash)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(project_id, path) DO UPDATE SET display_name=excluded.display_name,
                 mime_type=excluded.mime_type, size_bytes=excluded.size_bytes,
                 modified_at=excluded.modified_at, content_hash=excluded.content_hash""",
            (idea["project_id"], source.name, stored_path, payload.storage_mode, mime_type,
             measured.stat().st_size, measured.stat().st_mtime, _file_hash(measured)),
        )
        attachment_id = connection.execute(
            "SELECT id FROM attachments WHERE project_id=? AND path=?", (idea["project_id"], stored_path)
        ).fetchone()["id"]
        connection.execute("INSERT OR IGNORE INTO idea_attachments(idea_id, attachment_id) VALUES (?, ?)", (idea_id, attachment_id))
        row = connection.execute(
            """SELECT a.*, p.workspace_path FROM attachments a JOIN projects p ON p.id=a.project_id WHERE a.id=?""",
            (attachment_id,),
        ).fetchone()
        return _attachment(row)


FIGURE_TYPES = {
    ".png": ("image/png", "png"), ".jpg": ("image/jpeg", "jpg"), ".jpeg": ("image/jpeg", "jpg"),
    ".webp": ("image/webp", "webp"), ".gif": ("image/gif", "gif"), ".svg": ("image/svg+xml", "svg"),
}
MAX_FIGURE_BYTES = 20 * 1024 * 1024


@app.post("/api/ideas/{idea_id}/figures", status_code=201)
async def upload_figure(idea_id: int, file: UploadFile = File(...)) -> dict[str, Any]:
    display_name = Path(file.filename or "figure").name
    suffix = Path(display_name).suffix.lower()
    figure_type = FIGURE_TYPES.get(suffix)
    if not figure_type:
        raise HTTPException(415, "Supported image types are PNG, JPEG, WebP, GIF, and SVG")
    content = await file.read(MAX_FIGURE_BYTES + 1)
    if not content:
        raise HTTPException(400, "The image file is empty")
    if len(content) > MAX_FIGURE_BYTES:
        raise HTTPException(413, "Images must be 20 MB or smaller")
    mime_type, extension = figure_type
    signatures = {
        "png": content.startswith(b"\x89PNG\r\n\x1a\n"),
        "jpg": content.startswith(b"\xff\xd8\xff"),
        "webp": content.startswith(b"RIFF") and content[8:12] == b"WEBP",
        "gif": content.startswith((b"GIF87a", b"GIF89a")),
    }
    if extension != "svg" and not signatures.get(extension, False):
        raise HTTPException(400, "The file contents do not match the selected image type")
    if extension == "svg":
        if b"<!DOCTYPE" in content.upper() or b"<!ENTITY" in content.upper():
            raise HTTPException(400, "SVG document types and entities are not supported")
        try:
            root = ET.fromstring(content)
            if root.tag.rsplit("}", 1)[-1].lower() != "svg":
                raise ValueError("Not an SVG document")
            for element in root.iter():
                tag = element.tag.rsplit("}", 1)[-1].lower()
                if tag in {"script", "foreignobject"}:
                    raise ValueError("Active SVG element")
                text_value = (element.text or "").lower()
                if tag == "style" and ("@import" in text_value or re.search(r"url\(\s*(['\"]?)(?!#)", text_value)):
                    raise ValueError("External SVG style reference")
                for key, value in element.attrib.items():
                    name = key.rsplit("}", 1)[-1].lower()
                    normalized = value.strip().lower()
                    if name.startswith("on") or (name in {"href", "src"} and normalized and not normalized.startswith("#")):
                        raise ValueError("Active or external SVG reference")
                    if "@import" in normalized or re.search(r"url\(\s*(['\"]?)(?!#)", normalized):
                        raise ValueError("External SVG style reference")
        except (ET.ParseError, ValueError) as error:
            raise HTTPException(400, "This SVG is malformed or contains active content") from error

    with db() as connection:
        idea = connection.execute(
            "SELECT i.id, i.project_id, p.workspace_mode, p.system_key FROM ideas i JOIN projects p ON p.id=i.project_id WHERE i.id=?",
            (idea_id,),
        ).fetchone()
        if not idea:
            raise HTTPException(404, "Idea not found")
        if idea["system_key"] == "recycle":
            raise HTTPException(409, "Restore this idea before adding figures")
        folder = DB_PATH.parent / "assets" / "ideas" / str(idea_id)
        folder.mkdir(parents=True, exist_ok=True)
        filename = f"{uuid.uuid4().hex}.{extension}"
        destination = folder / filename
        destination.write_bytes(content)
        relative_path = (Path("assets") / "ideas" / str(idea_id) / filename).as_posix()
        digest = hashlib.sha256(content).hexdigest()
        connection.execute(
            "INSERT INTO attachments(project_id, display_name, path, storage_mode, mime_type, size_bytes, content_hash) VALUES (?, ?, ?, 'managed', ?, ?, ?)",
            (idea["project_id"], display_name or f"figure.{extension}", relative_path, mime_type, len(content), digest),
        )
        attachment_id = connection.execute("SELECT last_insert_rowid()").fetchone()[0]
        order = connection.execute("SELECT COALESCE(MAX(sort_order), -1)+1 FROM idea_attachments WHERE idea_id=? AND asset_role='figure'", (idea_id,)).fetchone()[0]
        connection.execute(
            "INSERT INTO idea_attachments(idea_id, attachment_id, asset_role, sort_order) VALUES (?, ?, 'figure', ?)",
            (idea_id, attachment_id, order),
        )
        row = connection.execute(
            "SELECT a.*, p.workspace_path, ia.asset_role, ia.caption, ia.sort_order, ia.is_cover FROM attachments a JOIN projects p ON p.id=a.project_id JOIN idea_attachments ia ON ia.attachment_id=a.id WHERE a.id=? AND ia.idea_id=?",
            (attachment_id, idea_id),
        ).fetchone()
        return _attachment(row)


@app.patch("/api/ideas/{idea_id}/attachments/{attachment_id}")
def update_idea_attachment(idea_id: int, attachment_id: int, payload: IdeaAttachmentUpdate) -> dict[str, Any]:
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(400, "Provide figure metadata to update")
    with db() as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT a.*, p.workspace_path, ia.asset_role, ia.caption, ia.sort_order, ia.is_cover FROM attachments a JOIN projects p ON p.id=a.project_id JOIN idea_attachments ia ON ia.attachment_id=a.id WHERE ia.idea_id=? AND ia.attachment_id=?",
            (idea_id, attachment_id),
        ).fetchone()
        if not row:
            raise HTTPException(404, "Attachment link not found")
        role = changes.get("asset_role", row["asset_role"])
        is_cover = changes.get("is_cover", bool(row["is_cover"]))
        if role == "figure" and row["mime_type"] not in {value[0] for value in FIGURE_TYPES.values()}:
            raise HTTPException(400, "Only supported image attachments can be figures")
        if is_cover and role != "figure":
            raise HTTPException(400, "Only figures can be used as a cover")
        if is_cover and row["mime_type"] not in {value[0] for value in FIGURE_TYPES.values()}:
            raise HTTPException(400, "Only image attachments can be used as a cover")
        if is_cover:
            connection.execute("UPDATE idea_attachments SET is_cover=0 WHERE idea_id=? AND is_cover=1", (idea_id,))
        if role != "figure":
            changes["is_cover"] = False
        assignments = ", ".join(f"{key}=?" for key in changes)
        connection.execute(
            f"UPDATE idea_attachments SET {assignments} WHERE idea_id=? AND attachment_id=?",
            (*changes.values(), idea_id, attachment_id),
        )
        updated = connection.execute(
            "SELECT a.*, p.workspace_path, ia.asset_role, ia.caption, ia.sort_order, ia.is_cover FROM attachments a JOIN projects p ON p.id=a.project_id JOIN idea_attachments ia ON ia.attachment_id=a.id WHERE ia.idea_id=? AND ia.attachment_id=?",
            (idea_id, attachment_id),
        ).fetchone()
        return _attachment(updated)


@app.get("/api/attachments/{attachment_id}/content")
def attachment_content(attachment_id: int) -> FileResponse:
    with db() as connection:
        row = connection.execute(
            "SELECT a.*, p.workspace_path FROM attachments a JOIN projects p ON p.id=a.project_id WHERE a.id=?",
            (attachment_id,),
        ).fetchone()
        if not row:
            raise HTTPException(404, "Attachment not found")
        path = _resolved_attachment_path(row)
        if not path.is_file():
            raise HTTPException(404, "The attached file is missing")
        mime_type = row["mime_type"]
        if mime_type not in {value[0] for value in FIGURE_TYPES.values()}:
            raise HTTPException(415, "This attachment is not a supported image")
    return FileResponse(
        path, media_type=mime_type, filename=None,
        headers={
            "Content-Disposition": "inline",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; sandbox",
        },
    )


@app.delete("/api/ideas/{idea_id}/attachments/{attachment_id}", status_code=204)
def detach_file(idea_id: int, attachment_id: int) -> Response:
    with db() as connection:
        cursor = connection.execute("DELETE FROM idea_attachments WHERE idea_id=? AND attachment_id=?", (idea_id, attachment_id))
        if cursor.rowcount == 0:
            raise HTTPException(404, "Attachment link not found")
    return Response(status_code=204)


def _attachment_for_action(attachment_id: int) -> Path:
    with db() as connection:
        row = connection.execute(
            """SELECT a.*, p.workspace_path FROM attachments a JOIN projects p ON p.id=a.project_id WHERE a.id=?""",
            (attachment_id,),
        ).fetchone()
        if not row:
            raise HTTPException(404, "Attachment not found")
        path = _resolved_attachment_path(row)
    if not path.is_file():
        raise HTTPException(404, "The attached file is missing. It may have been moved or renamed.")
    return path


@app.post("/api/attachments/{attachment_id}/open")
def open_attachment(attachment_id: int) -> dict[str, str]:
    path = _attachment_for_action(attachment_id)
    if sys.platform != "win32":
        raise HTTPException(501, "Opening files is currently supported on Windows")
    os.startfile(str(path))  # type: ignore[attr-defined]
    return {"status": "opened"}


@app.post("/api/attachments/{attachment_id}/reveal")
def reveal_attachment(attachment_id: int) -> dict[str, str]:
    path = _attachment_for_action(attachment_id)
    if sys.platform != "win32":
        raise HTTPException(501, "Revealing files is currently supported on Windows")
    subprocess.Popen(["explorer.exe", f"/select,{path}"])
    return {"status": "revealed"}


@app.delete("/api/projects/{project_id}/ideas")
def delete_project_ideas(project_id: int) -> dict[str, Any]:
    with db() as connection:
        project = connection.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
        if not project:
            raise HTTPException(404, "Project not found")
        count = connection.execute("SELECT COUNT(*) count FROM ideas WHERE project_id=?", (project_id,)).fetchone()["count"]
        if project["system_key"] == "recycle":
            connection.execute("DELETE FROM ideas WHERE project_id=?", (project_id,))
            _prune_orphan_tags(connection)
            return {"action": "deleted", "count": count}
        recycle_id = connection.execute("SELECT id FROM projects WHERE system_key='recycle'").fetchone()["id"]
        connection.execute(
            "UPDATE ideas SET project_id=?, updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE project_id=?",
            (recycle_id, project_id),
        )
        return {"action": "recycled", "count": count}


@app.get("/api/project-groups")
def list_project_groups() -> list[dict[str, Any]]:
    with db() as connection:
        return [dict(row) for row in connection.execute(
            """SELECT g.id, g.name, COUNT(DISTINCT p.id) project_count, COUNT(i.id) idea_count
               FROM project_groups g LEFT JOIN projects p ON p.group_id=g.id
               LEFT JOIN ideas i ON i.project_id=p.id GROUP BY g.id ORDER BY g.name"""
        ).fetchall()]


@app.post("/api/project-groups", status_code=201)
def create_project_group(payload: ProjectGroupCreate) -> dict[str, Any]:
    try:
        with db() as connection:
            cursor = connection.execute("INSERT INTO project_groups(name) VALUES (?)", (payload.name,))
            return {"id": cursor.lastrowid, "name": payload.name, "project_count": 0, "idea_count": 0}
    except sqlite3.IntegrityError as error:
        raise HTTPException(409, "A project group with that name already exists") from error


@app.get("/api/tags")
def list_tags(
    project_id: int | None = None,
    group_id: int | None = None,
    include_recycle: bool = False,
    include_hidden: bool = False,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if project_id is not None:
        clauses.append("i.project_id=?")
        params.append(project_id)
    elif group_id is not None:
        clauses.append("p.group_id=?")
        params.append(group_id)
    elif not include_recycle:
        clauses.append("COALESCE(p.system_key, '')<>'recycle'")
    if not include_hidden:
        clauses.append("COALESCE(ts.is_hidden, 0)=0")
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    with db() as connection:
        return [dict(row) for row in connection.execute(
            f"""SELECT t.name, COUNT(DISTINCT i.id) count, COALESCE(ts.group_name, '') group_name FROM tags t
                JOIN idea_tags it ON t.id=it.tag_id JOIN ideas i ON i.id=it.idea_id
                LEFT JOIN projects p ON p.id=i.project_id LEFT JOIN tag_settings ts ON ts.tag_id=t.id{where}
                GROUP BY t.id ORDER BY count DESC, t.name""",
            params,
        ).fetchall()]


@app.get("/api/tags/manage")
def manage_tags() -> list[dict[str, Any]]:
    with db() as connection:
        return [dict(row) for row in connection.execute(
            """SELECT t.name, COUNT(DISTINCT CASE WHEN COALESCE(p.system_key, '')<>'recycle' THEN i.id END) count,
                      COALESCE(ts.group_name, '') group_name, COALESCE(ts.is_hidden, 0) is_hidden
               FROM tags t JOIN idea_tags it ON it.tag_id=t.id JOIN ideas i ON i.id=it.idea_id
               LEFT JOIN projects p ON p.id=i.project_id LEFT JOIN tag_settings ts ON ts.tag_id=t.id
               GROUP BY t.id ORDER BY is_hidden, group_name, count DESC, t.name"""
        ).fetchall()]


@app.get("/api/tags/map")
def tag_map(
    project_id: int | None = None,
    group_id: int | None = None,
    include_recycle: bool = False,
    limit: int = Query(default=50, ge=5, le=100),
) -> dict[str, list[dict[str, Any]]]:
    """Return the most-used visible tags and their same-idea co-occurrences."""
    scope_clauses: list[str] = []
    scope_params: list[Any] = []
    if project_id is not None:
        scope_clauses.append("i.project_id=?")
        scope_params.append(project_id)
    elif group_id is not None:
        scope_clauses.append("p.group_id=?")
        scope_params.append(group_id)
    elif not include_recycle:
        scope_clauses.append("COALESCE(p.system_key, '')<>'recycle'")

    node_clauses = [*scope_clauses, "COALESCE(ts.is_hidden, 0)=0"]
    node_where = " WHERE " + " AND ".join(node_clauses)
    with db() as connection:
        node_rows = connection.execute(
            f"""SELECT t.id, t.name, COUNT(DISTINCT i.id) count,
                       COALESCE(ts.group_name, '') group_name
                FROM tags t JOIN idea_tags it ON t.id=it.tag_id
                JOIN ideas i ON i.id=it.idea_id
                LEFT JOIN projects p ON p.id=i.project_id
                LEFT JOIN tag_settings ts ON ts.tag_id=t.id{node_where}
                GROUP BY t.id ORDER BY count DESC, t.name LIMIT ?""",
            [*scope_params, limit],
        ).fetchall()
        if not node_rows:
            return {"nodes": [], "edges": []}

        tag_ids = [row["id"] for row in node_rows]
        marks = ",".join("?" for _ in tag_ids)
        edge_clauses = ["ia.tag_id<ib.tag_id", *scope_clauses, f"ia.tag_id IN ({marks})", f"ib.tag_id IN ({marks})"]
        edge_rows = connection.execute(
            f"""SELECT ia.tag_id source_id, ib.tag_id target_id,
                       COUNT(DISTINCT i.id) weight
                FROM idea_tags ia JOIN idea_tags ib ON ib.idea_id=ia.idea_id
                JOIN ideas i ON i.id=ia.idea_id
                LEFT JOIN projects p ON p.id=i.project_id
                WHERE {' AND '.join(edge_clauses)}
                GROUP BY ia.tag_id, ib.tag_id
                ORDER BY weight DESC, source_id, target_id""",
            [*scope_params, *tag_ids, *tag_ids],
        ).fetchall()
        names = {row["id"]: row["name"] for row in node_rows}
        return {
            "nodes": [{key: row[key] for key in ("name", "count", "group_name")} for row in node_rows],
            "edges": [
                {"source": names[row["source_id"]], "target": names[row["target_id"]], "weight": row["weight"]}
                for row in edge_rows
            ],
        }


def _tag(connection: sqlite3.Connection, name: str) -> sqlite3.Row:
    row = connection.execute("SELECT * FROM tags WHERE name=? COLLATE NOCASE", (name.strip(),)).fetchone()
    if not row:
        raise HTTPException(404, f"Tag '{name}' was not found")
    return row


@app.put("/api/tags/{tag_name}/settings")
def update_tag_settings(tag_name: str, payload: TagSettingsUpdate) -> dict[str, Any]:
    with db() as connection:
        tag = _tag(connection, tag_name)
        connection.execute(
            """INSERT INTO tag_settings(tag_id, group_name, is_hidden) VALUES (?, ?, ?)
               ON CONFLICT(tag_id) DO UPDATE SET group_name=excluded.group_name, is_hidden=excluded.is_hidden""",
            (tag["id"], payload.group_name, int(payload.is_hidden)),
        )
        return {"name": tag["name"], "group_name": payload.group_name, "is_hidden": payload.is_hidden}


@app.post("/api/tags/{tag_name}/rename")
def rename_tag(tag_name: str, payload: TagRename) -> dict[str, Any]:
    with db() as connection:
        source = _tag(connection, tag_name)
        existing = connection.execute("SELECT * FROM tags WHERE name=? COLLATE NOCASE", (payload.name,)).fetchone()
        if existing and existing["id"] != source["id"]:
            connection.execute("INSERT OR IGNORE INTO idea_tags(idea_id, tag_id) SELECT idea_id, ? FROM idea_tags WHERE tag_id=?", (existing["id"], source["id"]))
            source_settings = connection.execute("SELECT * FROM tag_settings WHERE tag_id=?", (source["id"],)).fetchone()
            if source_settings:
                connection.execute("INSERT OR IGNORE INTO tag_settings(tag_id, group_name, is_hidden) VALUES (?, ?, ?)", (existing["id"], source_settings["group_name"], source_settings["is_hidden"]))
            connection.execute("DELETE FROM tags WHERE id=?", (source["id"],))
            return {"name": existing["name"], "merged": True}
        connection.execute("UPDATE tags SET name=? WHERE id=?", (payload.name, source["id"]))
        return {"name": payload.name, "merged": False}


@app.post("/api/tags/{tag_name}/merge")
def merge_tag(tag_name: str, payload: TagMerge) -> dict[str, Any]:
    if tag_name.strip().lower() == payload.target_name:
        raise HTTPException(400, "Choose a different tag to merge into")
    return rename_tag(tag_name, TagRename(name=payload.target_name))


@app.post("/api/tags/bulk")
def bulk_update_tags(payload: TagBulkUpdate) -> dict[str, Any]:
    with db() as connection:
        idea_ids = list(dict.fromkeys(payload.idea_ids))
        marks = ",".join("?" for _ in idea_ids)
        rows = connection.execute(f"SELECT id FROM ideas WHERE id IN ({marks})", idea_ids).fetchall()
        if len(rows) != len(idea_ids):
            raise HTTPException(400, "One or more selected ideas no longer exist")
        additions = {tag.strip().lower() for tag in payload.add_tags if tag.strip()}
        removals = {tag.strip().lower() for tag in payload.remove_tags if tag.strip()}
        for idea_id in idea_ids:
            current = set(_tags(connection, idea_id))
            _set_tags(connection, idea_id, sorted((current | additions) - removals))
        return {"ideas_updated": len(idea_ids), "added": sorted(additions), "removed": sorted(removals)}


@app.get("/api/relation-types")
def relation_types() -> list[str]:
    with db() as connection:
        custom = [row["relation_type"] for row in connection.execute("SELECT DISTINCT relation_type FROM relations ORDER BY relation_type")]
    return sorted(set(["builds-on", "contradicts", "combines-with", "develops-into", "evidence-for", "inspired-by", "related-to"] + custom))


@app.get("/api/relations")
def list_relations() -> list[dict[str, Any]]:
    with db() as connection:
        return [dict(row) for row in connection.execute("SELECT * FROM relations ORDER BY created_at DESC").fetchall()]


@app.post("/api/relations", status_code=201)
def create_relation(payload: RelationCreate) -> dict[str, Any]:
    if payload.source_id == payload.target_id:
        raise HTTPException(400, "An idea cannot relate to itself")
    relation_type = payload.relation_type.strip().lower()
    try:
        with db() as connection:
            if relation_type == "develops-into":
                creates_cycle = connection.execute(
                    """WITH RECURSIVE descendants(id) AS (
                           SELECT target_id FROM relations
                           WHERE source_id=? AND relation_type='develops-into'
                           UNION
                           SELECT relation.target_id FROM relations relation
                           JOIN descendants ON relation.source_id=descendants.id
                           WHERE relation.relation_type='develops-into'
                       )
                       SELECT 1 FROM descendants WHERE id=? LIMIT 1""",
                    (payload.target_id, payload.source_id),
                ).fetchone()
                if creates_cycle:
                    raise HTTPException(409, "That lineage link would create a cycle")
            cursor = connection.execute(
                "INSERT INTO relations(source_id, target_id, relation_type, note) VALUES (?, ?, ?, ?)",
                (payload.source_id, payload.target_id, relation_type, payload.note),
            )
            return dict(connection.execute("SELECT * FROM relations WHERE id=?", (cursor.lastrowid,)).fetchone())
    except sqlite3.IntegrityError as error:
        raise HTTPException(409, "That relation already exists or references an unknown idea") from error


@app.delete("/api/relations/{relation_id}", status_code=204)
def delete_relation(relation_id: int) -> Response:
    with db() as connection:
        cursor = connection.execute("DELETE FROM relations WHERE id=?", (relation_id,))
        if not cursor.rowcount:
            raise HTTPException(404, "Relation not found")
    return Response(status_code=204)


@app.get("/api/ideas/{idea_id}/suggestions")
def suggestions(idea_id: int, limit: int = Query(default=5, ge=1, le=20)) -> list[dict[str, Any]]:
    with db() as connection:
        idea = connection.execute("SELECT * FROM ideas WHERE id=?", (idea_id,)).fetchone()
        if not idea:
            raise HTTPException(404, "Idea not found")
        tag_rows = connection.execute("SELECT tag_id FROM idea_tags WHERE idea_id=?", (idea_id,)).fetchall()
        tag_ids = [row["tag_id"] for row in tag_rows]
        words = re.findall(r"\b[\w-]{4,}\b", f"{idea['title']} {idea['content']}".lower())[:12]
        scores: dict[int, dict[str, Any]] = {}
        if tag_ids:
            marks = ",".join("?" for _ in tag_ids)
            rows = connection.execute(
                f"""SELECT i.*, COUNT(*) shared_tags FROM ideas i JOIN idea_tags it ON i.id=it.idea_id
                    WHERE it.tag_id IN ({marks}) AND i.id<>? GROUP BY i.id""",
                [*tag_ids, idea_id],
            ).fetchall()
            for row in rows:
                scores[row["id"]] = {**_idea(connection, row), "score": row["shared_tags"] * 3, "reason": f"{row['shared_tags']} shared tag(s)"}
        if words:
            fts = " OR ".join(f'"{word}"' for word in dict.fromkeys(words))
            for row in connection.execute(
                "SELECT i.*, bm25(ideas_fts) rank FROM ideas_fts JOIN ideas i ON i.id=ideas_fts.rowid WHERE ideas_fts MATCH ? AND i.id<>? LIMIT 20",
                (fts, idea_id),
            ).fetchall():
                if row["id"] in scores:
                    scores[row["id"]]["score"] += 1
                    scores[row["id"]]["reason"] += " + keyword overlap"
                else:
                    scores[row["id"]] = {**_idea(connection, row), "score": 1, "reason": "keyword overlap"}
        return sorted(scores.values(), key=lambda item: (-item["score"], item["title"]))[:limit]


def _export_data() -> dict[str, Any]:
    with db() as connection:
        ideas = [_idea(connection, row) for row in connection.execute("SELECT * FROM ideas ORDER BY created_at").fetchall()]
        for idea in ideas:
            idea["figure_assets"] = [{**dict(row), "is_cover": bool(row["is_cover"])} for row in connection.execute(
                """SELECT a.content_hash, a.display_name, a.mime_type, ia.asset_role, ia.caption, ia.sort_order, ia.is_cover
                   FROM idea_attachments ia JOIN attachments a ON a.id=ia.attachment_id
                   WHERE ia.idea_id=? AND ia.asset_role='figure' ORDER BY ia.sort_order, a.id""",
                (idea["id"],),
            ).fetchall()]
        relations = [dict(row) for row in connection.execute("SELECT * FROM relations ORDER BY created_at").fetchall()]
        projects = [dict(row) for row in connection.execute("SELECT * FROM projects ORDER BY id").fetchall()]
        groups = [dict(row) for row in connection.execute("SELECT * FROM project_groups ORDER BY id").fetchall()]
        experiments = []
        for row in connection.execute("SELECT * FROM micro_experiments ORDER BY created_at").fetchall():
            item = dict(row)
            item["metrics"] = json.loads(item.pop("metrics_json"))
            item["metadata"] = json.loads(item.pop("metadata_json"))
            item["idea_links"] = [dict(link) for link in connection.execute("SELECT idea_id,role FROM experiment_ideas WHERE experiment_id=?", (row["id"],))]
            item["attachments"] = [dict(file) for file in connection.execute(
                "SELECT a.content_hash,a.display_name,a.mime_type,a.project_id,ea.asset_role,ea.caption,ea.sort_order FROM experiment_attachments ea JOIN attachments a ON a.id=ea.attachment_id WHERE ea.experiment_id=? ORDER BY ea.sort_order,a.id", (row["id"],)
            )]
            experiments.append(item)
    return {"version": 4, "project_groups": groups, "projects": projects, "ideas": ideas, "relations": relations, "experiments": experiments}


def _expand_export_references(text: str, by_id: dict[int, dict[str, Any]]) -> str:
    pattern = re.compile(r"\[\[idea:(\d+)(?:\|[^\]]*)?\]\]|\bIdea\s+#(\d+)\b", re.IGNORECASE)

    def replace(match: re.Match[str]) -> str:
        idea_id = int(match.group(1) or match.group(2))
        title = str(by_id.get(idea_id, {}).get("title", f"Unavailable idea #{idea_id}"))
        label = re.sub(r"([\\\[\]])", r"\\\1", title)
        return f"[{label}](#idea-{idea_id})"

    fenced = False
    lines: list[str] = []
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            fenced = not fenced
            lines.append(line)
        else:
            lines.append(line if fenced else pattern.sub(replace, line))
    return "\n".join(lines)


def _validated_import(data: dict[str, Any]) -> dict[str, Any]:
    version = data.get("version", 1)
    if version not in (1, 2, 3, 4):
        raise HTTPException(400, f"Unsupported IdeaMiner export version: {version}")
    for key in ("ideas", "relations"):
        if not isinstance(data.get(key, []), list):
            raise HTTPException(400, f"Import field '{key}' must be a list")
    if version >= 2:
        for key in ("projects", "project_groups"):
            if not isinstance(data.get(key, []), list):
                raise HTTPException(400, f"Import field '{key}' must be a list")
    if version >= 4 and not isinstance(data.get("experiments", []), list):
        raise HTTPException(400, "Import field 'experiments' must be a list")
    seen_ids: set[int] = set()
    for index, idea in enumerate(data.get("ideas", [])):
        if not isinstance(idea, dict):
            raise HTTPException(400, f"Idea {index + 1} is invalid")
        try:
            idea_id = int(idea["id"])
        except (KeyError, TypeError, ValueError) as error:
            raise HTTPException(400, f"Idea {index + 1} has no valid id") from error
        if idea_id in seen_ids:
            raise HTTPException(400, f"Duplicate idea id in import: {idea_id}")
        seen_ids.add(idea_id)
        if not isinstance(idea.get("title"), str) or not idea["title"].strip():
            raise HTTPException(400, f"Idea {idea_id} has no title")
        if not isinstance(idea.get("raw_text"), str):
            raise HTTPException(400, f"Idea {idea_id} has no original raw text")
        if idea.get("status", "seed") not in ("seed", "exploring", "promising", "parked"):
            raise HTTPException(400, f"Idea {idea_id} has an invalid status")
        if not isinstance(idea.get("tags", []), list) or not all(isinstance(tag, str) for tag in idea.get("tags", [])):
            raise HTTPException(400, f"Idea {idea_id} has invalid tags")
        if not isinstance(idea.get("figure_assets", []), list):
            raise HTTPException(400, f"Idea {idea_id} has invalid figure metadata")
        for figure in idea.get("figure_assets", []):
            if not isinstance(figure, dict):
                raise HTTPException(400, f"Idea {idea_id} has invalid figure metadata")
            if figure.get("asset_role", "figure") not in ("attachment", "figure"):
                raise HTTPException(400, f"Idea {idea_id} has an invalid figure role")
            if not isinstance(figure.get("content_hash", ""), str) or not isinstance(figure.get("caption", ""), str) or len(figure.get("caption", "")) > 500:
                raise HTTPException(400, f"Idea {idea_id} has invalid figure metadata")
            if not isinstance(figure.get("sort_order", 0), int) or not 0 <= figure.get("sort_order", 0) <= 100000:
                raise HTTPException(400, f"Idea {idea_id} has invalid figure ordering")
            if not isinstance(figure.get("is_cover", False), bool):
                raise HTTPException(400, f"Idea {idea_id} has invalid cover metadata")
    experiments = data.get("experiments", [])
    valid_statuses = {"planned", "running", "completed", "failed", "inconclusive", "needs_follow_up"}
    for index, experiment in enumerate(experiments):
        if not isinstance(experiment, dict) or not isinstance(experiment.get("what_tried"), str) or not experiment["what_tried"].strip():
            raise HTTPException(400, f"Experiment {index + 1} has no valid description")
        if experiment.get("status", "planned") not in valid_statuses:
            raise HTTPException(400, f"Experiment {index + 1} has an invalid status")
        if not isinstance(experiment.get("idea_links", []), list) or not isinstance(experiment.get("attachments", []), list):
            raise HTTPException(400, f"Experiment {index + 1} has invalid links or attachments")
        if not isinstance(experiment.get("metrics", {}), dict) or not isinstance(experiment.get("metadata", {}), dict):
            raise HTTPException(400, f"Experiment {index + 1} has invalid metadata")
    return {
        "version": version,
        "project_groups": data.get("project_groups", []),
        "projects": data.get("projects", []),
        "ideas": data.get("ideas", []),
        "relations": data.get("relations", []),
        "experiments": experiments,
    }


def _unique_name(connection: sqlite3.Connection, table: str, requested: str) -> str:
    candidate = f"{requested} (imported)"
    counter = 2
    while connection.execute(f"SELECT 1 FROM {table} WHERE name=? COLLATE NOCASE", (candidate,)).fetchone():
        candidate = f"{requested} (imported {counter})"
        counter += 1
    return candidate


@app.post("/api/import/preview")
def preview_import(payload: ImportPreviewRequest) -> dict[str, Any]:
    data = _validated_import(payload.data)
    with db() as connection:
        duplicate_topics = sum(
            1 for idea in data["ideas"]
            if connection.execute(
                "SELECT 1 FROM ideas WHERE title=? AND raw_text=? LIMIT 1",
                (idea["title"].strip(), idea["raw_text"]),
            ).fetchone()
        )
        project_conflicts = [
            project.get("name", "") for project in data["projects"]
            if not project.get("system_key") and isinstance(project.get("name"), str)
            and connection.execute("SELECT 1 FROM projects WHERE name=? COLLATE NOCASE", (project["name"],)).fetchone()
        ]
        group_conflicts = [
            group.get("name", "") for group in data["project_groups"]
            if isinstance(group.get("name"), str)
            and connection.execute("SELECT 1 FROM project_groups WHERE name=? COLLATE NOCASE", (group["name"],)).fetchone()
        ]
    idea_ids = {int(idea["id"]) for idea in data["ideas"]}
    valid_relations = sum(
        1 for relation in data["relations"] if isinstance(relation, dict)
        and relation.get("source_id") in idea_ids and relation.get("target_id") in idea_ids
    )
    return {
        "version": data["version"],
        "counts": {
            "groups": len(data["project_groups"]),
            "projects": len(data["projects"]),
            "ideas": len(data["ideas"]),
            "relations": valid_relations,
            "experiments": len(data["experiments"]),
        },
        "duplicate_topics": duplicate_topics,
        "project_conflicts": project_conflicts,
        "group_conflicts": group_conflicts,
    }


@app.post("/api/import/json")
def import_json(payload: ImportRequest) -> dict[str, Any]:
    data = _validated_import(payload.data)
    result = {"groups_created": 0, "projects_created": 0, "ideas_created": 0, "ideas_skipped": 0, "ideas_updated": 0, "relations_created": 0}
    result["experiments_created"] = 0
    with db() as connection:
        default_id = connection.execute("SELECT id FROM projects WHERE system_key='random_chat'").fetchone()["id"]
        group_map: dict[int, int] = {}
        for group in data["project_groups"]:
            if not isinstance(group, dict) or not isinstance(group.get("name"), str) or not group["name"].strip():
                raise HTTPException(400, "Every project group must have an id and name")
            try:
                old_id = int(group["id"])
            except (KeyError, TypeError, ValueError) as error:
                raise HTTPException(400, "Every project group must have a valid id") from error
            name = group["name"].strip()
            existing = connection.execute("SELECT id FROM project_groups WHERE name=? COLLATE NOCASE", (name,)).fetchone()
            if existing and payload.project_strategy == "merge":
                group_map[old_id] = existing["id"]
            else:
                if existing:
                    name = _unique_name(connection, "project_groups", name)
                cursor = connection.execute("INSERT INTO project_groups(name) VALUES (?)", (name,))
                group_map[old_id] = cursor.lastrowid
                result["groups_created"] += 1

        project_map: dict[int, int] = {}
        for project in data["projects"]:
            if not isinstance(project, dict) or not isinstance(project.get("name"), str) or not project["name"].strip():
                raise HTTPException(400, "Every project must have an id and name")
            try:
                old_id = int(project["id"])
            except (KeyError, TypeError, ValueError) as error:
                raise HTTPException(400, "Every project must have a valid id") from error
            system_key = project.get("system_key")
            if system_key in ("random_chat", "recycle"):
                project_map[old_id] = connection.execute("SELECT id FROM projects WHERE system_key=?", (system_key,)).fetchone()["id"]
                continue
            name = project["name"].strip()
            existing = connection.execute("SELECT id FROM projects WHERE name=? COLLATE NOCASE", (name,)).fetchone()
            if existing and payload.project_strategy == "merge":
                project_map[old_id] = existing["id"]
            else:
                if existing:
                    name = _unique_name(connection, "projects", name)
                imported_group_id = project.get("group_id")
                group_id = group_map.get(int(imported_group_id)) if imported_group_id is not None else None
                cursor = connection.execute(
                    "INSERT INTO projects(name, description, group_id) VALUES (?, ?, ?)",
                    (name, str(project.get("description", "")), group_id),
                )
                project_map[old_id] = cursor.lastrowid
                result["projects_created"] += 1

        idea_map: dict[int, int] = {}
        for idea in data["ideas"]:
            old_id = int(idea["id"])
            title = idea["title"].strip()
            raw_text = idea["raw_text"]
            existing = connection.execute(
                "SELECT * FROM ideas WHERE title=? AND raw_text=? ORDER BY id LIMIT 1",
                (title, raw_text),
            ).fetchone()
            if existing and payload.duplicate_strategy == "skip":
                idea_map[old_id] = existing["id"]
                result["ideas_skipped"] += 1
                continue
            imported_project_id = idea.get("project_id")
            project_id = project_map.get(int(imported_project_id), default_id) if imported_project_id is not None else default_id
            content = str(idea.get("content", ""))
            status = idea.get("status", "seed")
            created_at = idea.get("created_at") if isinstance(idea.get("created_at"), str) else None
            updated_at = idea.get("updated_at") if isinstance(idea.get("updated_at"), str) else None
            if existing and payload.duplicate_strategy == "update":
                connection.execute("INSERT INTO idea_revisions(idea_id, title, content) VALUES (?, ?, ?)", (existing["id"], existing["title"], existing["content"]))
                connection.execute(
                    "UPDATE ideas SET content=?, status=?, project_id=?, updated_at=COALESCE(?, strftime('%Y-%m-%dT%H:%M:%fZ','now')) WHERE id=?",
                    (content, status, project_id, updated_at, existing["id"]),
                )
                new_id = existing["id"]
                result["ideas_updated"] += 1
            else:
                cursor = connection.execute(
                    """INSERT INTO ideas(title, content, raw_text, status, project_id, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, COALESCE(?, strftime('%Y-%m-%dT%H:%M:%fZ','now')), COALESCE(?, strftime('%Y-%m-%dT%H:%M:%fZ','now')))""",
                    (title, content, raw_text, status, project_id, created_at, updated_at),
                )
                new_id = cursor.lastrowid
                result["ideas_created"] += 1
            _set_tags(connection, new_id, idea.get("tags", []))
            idea_map[old_id] = new_id

        for idea in data["ideas"]:
            new_id = idea_map.get(int(idea["id"]))
            if not new_id:
                continue
            project_row = connection.execute("SELECT project_id FROM ideas WHERE id=?", (new_id,)).fetchone()
            for figure in idea.get("figure_assets", []):
                if not isinstance(figure, dict) or not isinstance(figure.get("content_hash"), str):
                    continue
                attachment = connection.execute(
                    "SELECT id FROM attachments WHERE project_id=? AND content_hash=? AND mime_type LIKE 'image/%' ORDER BY id LIMIT 1",
                    (project_row["project_id"], figure["content_hash"]),
                ).fetchone()
                if not attachment:
                    continue
                role = "figure" if figure.get("asset_role") == "figure" else "attachment"
                connection.execute(
                    """INSERT OR IGNORE INTO idea_attachments(idea_id, attachment_id, asset_role, caption, sort_order)
                       VALUES (?, ?, ?, ?, ?)""",
                    (new_id, attachment["id"], role, str(figure.get("caption", ""))[:500], max(0, int(figure.get("sort_order", 0) or 0))),
                )
                if role == "figure" and figure.get("is_cover"):
                    connection.execute("UPDATE idea_attachments SET is_cover=0 WHERE idea_id=? AND is_cover=1", (new_id,))
                    connection.execute("UPDATE idea_attachments SET is_cover=1 WHERE idea_id=? AND attachment_id=?", (new_id, attachment["id"]))

        for relation in data["relations"]:
            if not isinstance(relation, dict):
                continue
            source_id = idea_map.get(relation.get("source_id"))
            target_id = idea_map.get(relation.get("target_id"))
            relation_type = relation.get("relation_type")
            if not source_id or not target_id or source_id == target_id or not isinstance(relation_type, str) or not relation_type.strip():
                continue
            cursor = connection.execute(
                "INSERT OR IGNORE INTO relations(source_id, target_id, relation_type, note) VALUES (?, ?, ?, ?)",
                (source_id, target_id, relation_type.strip().lower(), str(relation.get("note", ""))),
            )
            result["relations_created"] += cursor.rowcount
        idea_ids = {int(idea["id"]) for idea in data["ideas"]}
        for experiment in data["experiments"]:
            cursor = connection.execute(
                """INSERT INTO micro_experiments(what_tried,result,takeaway,status,dataset_material,metrics_json,code_ref,metadata_json,created_at,updated_at,completed_at)
                   VALUES(?,?,?,?,?,?,?, ?,COALESCE(?,strftime('%Y-%m-%dT%H:%M:%fZ','now')),COALESCE(?,strftime('%Y-%m-%dT%H:%M:%fZ','now')),?)""",
                (experiment["what_tried"].strip(),str(experiment.get("result", "")),str(experiment.get("takeaway", "")),experiment.get("status", "planned"),str(experiment.get("dataset_material", "")),json.dumps(experiment.get("metrics", {}), ensure_ascii=False),str(experiment.get("code_ref", "")),json.dumps(experiment.get("metadata", {}), ensure_ascii=False),experiment.get("created_at") or None,experiment.get("updated_at") or None,experiment.get("completed_at") or None),
            )
            experiment_id = cursor.lastrowid
            for link in experiment.get("idea_links", []):
                if not isinstance(link, dict):
                    continue
                try: old_idea_id = int(link.get("idea_id"))
                except (TypeError, ValueError): continue
                new_idea_id = idea_map.get(old_idea_id)
                role = link.get("role", "tests")
                if old_idea_id in idea_ids and new_idea_id and role in ("tests", "supports", "contradicts", "motivated-by", "follow-up"):
                    connection.execute("INSERT OR IGNORE INTO experiment_ideas(experiment_id,idea_id,role) VALUES(?,?,?)", (experiment_id,new_idea_id,role))
            for asset in experiment.get("attachments", []):
                if not isinstance(asset, dict) or not isinstance(asset.get("content_hash"),str) or not asset["content_hash"]:
                    continue
                old_project = asset.get("project_id")
                try: mapped_project = project_map.get(int(old_project)) if old_project is not None else None
                except (TypeError,ValueError): mapped_project = None
                if mapped_project is None:
                    continue
                attachment = connection.execute("SELECT id FROM attachments WHERE project_id=? AND content_hash=? ORDER BY id LIMIT 1", (mapped_project,asset["content_hash"])).fetchone()
                if attachment:
                    connection.execute("INSERT OR IGNORE INTO experiment_attachments(experiment_id,attachment_id,asset_role,caption,sort_order) VALUES(?,?,?,?,?)", (experiment_id,attachment["id"],asset.get("asset_role","figure") if asset.get("asset_role") in ("attachment","figure") else "figure",str(asset.get("caption",""))[:500],max(0,int(asset.get("sort_order",0) or 0))))
            result["experiments_created"] += 1
    return {"status": "imported", **result}


@app.get("/api/export/json")
def export_json() -> Response:
    return Response(
        json.dumps(_export_data(), ensure_ascii=False, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=ideaminer-export.json"},
    )


@app.get("/api/export/markdown")
def export_markdown() -> Response:
    data = _export_data()
    by_id = {idea["id"]: idea for idea in data["ideas"]}
    projects = {project["id"]: project for project in data["projects"]}
    lines = ["# IdeaMiner export", ""]
    for idea in data["ideas"]:
        project_name = projects.get(idea["project_id"], {}).get("name", "Unknown")
        readable_content = _expand_export_references(idea["content"], by_id) if idea["content"] else "_No notes yet._"
        lines += [f"<a id=\"idea-{idea['id']}\"></a>", f"## {idea['title']}", "", f"**Project:** {project_name}  ", f"**Status:** {idea['status']}  ", f"**Tags:** {', '.join(idea['tags']) or '—'}", "", readable_content, "", "### Original capture", "", idea["raw_text"], ""]
        related = [r for r in data["relations"] if r["source_id"] == idea["id"] or r["target_id"] == idea["id"]]
        if related:
            lines += ["### Relations", ""]
            for relation in related:
                other_id = relation["target_id"] if relation["source_id"] == idea["id"] else relation["source_id"]
                lines.append(f"- **{relation['relation_type']}** → {by_id.get(other_id, {}).get('title', 'Unknown')}" + (f" — {relation['note']}" if relation["note"] else ""))
            lines.append("")
    return Response("\n".join(lines), media_type="text/markdown", headers={"Content-Disposition": "attachment; filename=ideaminer-export.md"})


WEB_DIST = Path(__file__).resolve().parents[2] / "web-dist"
if (WEB_DIST / "index.html").is_file():
    app.mount("/", StaticFiles(directory=WEB_DIST, html=True), name="web")
