from __future__ import annotations

import sqlite3
import json
from typing import Any

from fastapi import APIRouter, HTTPException

from .database import db

router = APIRouter(prefix="/api/agent/sessions", tags=["agent sessions"])


def save_chat_turn(
    connection: sqlite3.Connection,
    *,
    session_id: int | None,
    run_id: int,
    prompt: str,
    answer: str,
    provider: str,
    model: str,
    scope_type: str,
    scope_id: int | None,
    idea_id: int | None,
    context_idea_ids: list[int],
    attachment_ids: list[int],
) -> int:
    context_json = json.dumps(list(dict.fromkeys(context_idea_ids))[:20])
    attachments_json = json.dumps(list(dict.fromkeys(attachment_ids))[:12])
    if session_id is None:
        title = " ".join(prompt.split())[:80] or "New chat"
        cursor = connection.execute(
            """INSERT INTO agent_chat_sessions(title, provider, model, scope_type, scope_id, idea_id, context_idea_ids_json, attachment_ids_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (title, provider, model, scope_type, scope_id, idea_id, context_json, attachments_json),
        )
        session_id = int(cursor.lastrowid)
    else:
        session = connection.execute("SELECT id, title FROM agent_chat_sessions WHERE id=?", (session_id,)).fetchone()
        if not session:
            raise HTTPException(404, "Agent chat session not found")
        if session["title"] == "New chat":
            title = " ".join(prompt.split())[:80] or "New chat"
        else:
            title = session["title"]
        connection.execute(
            """UPDATE agent_chat_sessions SET title=?, provider=?, model=?, scope_type=?, scope_id=?, idea_id=?, context_idea_ids_json=?, attachment_ids_json=?,
                      updated_at=strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id=?""",
            (title, provider, model, scope_type, scope_id, idea_id, context_json, attachments_json, session_id),
        )

    connection.execute(
        "INSERT INTO agent_chat_messages(session_id, role, content) VALUES (?, 'user', ?)",
        (session_id, prompt),
    )
    connection.execute(
        """INSERT INTO agent_chat_messages(session_id, role, content, run_id)
           VALUES (?, 'assistant', ?, ?)""",
        (session_id, answer, run_id),
    )
    return session_id


def _session(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "title": str(row["title"]),
        "provider": str(row["provider"]),
        "model": str(row["model"]),
        "scope_type": str(row["scope_type"]),
        "scope_id": row["scope_id"],
        "idea_id": row["idea_id"],
        "context_idea_ids": json.loads(row["context_idea_ids_json"] or "[]") if "context_idea_ids_json" in row.keys() else [],
        "attachment_ids": json.loads(row["attachment_ids_json"] or "[]") if "attachment_ids_json" in row.keys() else [],
        "created_at": str(row["created_at"]),
        "updated_at": str(row["updated_at"]),
        "message_count": int(row["message_count"]) if "message_count" in row.keys() else 0,
    }


@router.get("")
def list_sessions(limit: int = 50) -> list[dict[str, Any]]:
    limit = max(1, min(limit, 100))
    with db() as connection:
        rows = connection.execute(
            """SELECT s.*, (SELECT COUNT(*) FROM agent_chat_messages m WHERE m.session_id=s.id) message_count
               FROM agent_chat_sessions s ORDER BY s.updated_at DESC LIMIT ?""",
            (limit,),
        ).fetchall()
    return [_session(row) for row in rows]


@router.get("/{session_id}")
def get_session(session_id: int) -> dict[str, Any]:
    with db() as connection:
        row = connection.execute(
            """SELECT s.*, (SELECT COUNT(*) FROM agent_chat_messages m WHERE m.session_id=s.id) message_count
               FROM agent_chat_sessions s WHERE s.id=?""",
            (session_id,),
        ).fetchone()
        if not row:
            raise HTTPException(404, "Agent chat session not found")
        messages = connection.execute(
            "SELECT role, content, created_at FROM agent_chat_messages WHERE session_id=? ORDER BY id",
            (session_id,),
        ).fetchall()
    return {"session": _session(row), "messages": [dict(message) for message in messages]}


@router.delete("/{session_id}")
def delete_session(session_id: int) -> dict[str, int]:
    with db() as connection:
        cursor = connection.execute("DELETE FROM agent_chat_sessions WHERE id=?", (session_id,))
        if not cursor.rowcount:
            raise HTTPException(404, "Agent chat session not found")
    return {"id": session_id}
