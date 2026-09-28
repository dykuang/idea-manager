"""Micro-experiment capture, search, and repeat detection."""
from __future__ import annotations

import json
import re
import sqlite3
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from .database import db

router = APIRouter(prefix="/api/experiments", tags=["experiments"])
Status = Literal["planned", "running", "completed", "failed", "inconclusive", "needs_follow_up"]
Role = Literal["tests", "supports", "contradicts", "motivated-by", "follow-up"]


class ExperimentInput(BaseModel):
    what_tried: str = Field(min_length=1, max_length=4000)
    result: str = Field(default="", max_length=8000)
    takeaway: str = Field(default="", max_length=4000)
    status: Status = "planned"
    dataset_material: str = Field(default="", max_length=2000)
    metrics: dict[str, Any] = Field(default_factory=dict)
    code_ref: str = Field(default="", max_length=2000)
    metadata: dict[str, Any] = Field(default_factory=dict)
    idea_links: list[dict[str, Any]] = Field(default_factory=list)
    attachment_ids: list[int] = Field(default_factory=list)


class LinkInput(BaseModel):
    idea_id: int
    role: Role = "tests"


class ExperimentUpdate(ExperimentInput):
    pass


def _experiment(connection: sqlite3.Connection, experiment_id: int) -> dict[str, Any] | None:
    row = connection.execute("SELECT * FROM micro_experiments WHERE id=?", (experiment_id,)).fetchone()
    if not row:
        return None
    item = dict(row)
    item["metrics"] = json.loads(item.pop("metrics_json"))
    item["metadata"] = json.loads(item.pop("metadata_json"))
    item["ideas"] = [dict(link) for link in connection.execute(
        "SELECT i.id AS idea_id,i.title,i.project_id,ei.role FROM experiment_ideas ei JOIN ideas i ON i.id=ei.idea_id WHERE ei.experiment_id=? ORDER BY i.title", (experiment_id,)
    )]
    item["attachments"] = [dict(file) for file in connection.execute(
        "SELECT a.id,a.display_name,a.mime_type,a.content_hash,ea.asset_role,ea.caption,ea.sort_order FROM experiment_attachments ea JOIN attachments a ON a.id=ea.attachment_id WHERE ea.experiment_id=? ORDER BY ea.sort_order,a.id", (experiment_id,)
    )]
    return item


def _write_links(connection: sqlite3.Connection, experiment_id: int, payload: ExperimentInput) -> None:
    connection.execute("DELETE FROM experiment_ideas WHERE experiment_id=?", (experiment_id,))
    for link in payload.idea_links:
        idea_id = int(link.get("idea_id", 0))
        role = str(link.get("role", "tests"))
        if role not in ("tests", "supports", "contradicts", "motivated-by", "follow-up"):
            raise HTTPException(400, f"Invalid experiment link role: {role}")
        if not connection.execute("SELECT 1 FROM ideas WHERE id=?", (idea_id,)).fetchone():
            raise HTTPException(404, f"Idea {idea_id} not found")
        connection.execute("INSERT OR IGNORE INTO experiment_ideas(experiment_id,idea_id,role) VALUES (?,?,?)", (experiment_id, idea_id, role))
    connection.execute("DELETE FROM experiment_attachments WHERE experiment_id=?", (experiment_id,))
    for attachment_id in sorted(set(payload.attachment_ids)):
        if not connection.execute("SELECT 1 FROM attachments WHERE id=?", (attachment_id,)).fetchone():
            raise HTTPException(404, f"Attachment {attachment_id} not found")
        connection.execute("INSERT OR IGNORE INTO experiment_attachments(experiment_id,attachment_id) VALUES (?,?)", (experiment_id, attachment_id))


@router.get("")
def search_experiments(q: str = Query(default="", max_length=500), status: Status | None = None, idea_id: int | None = None, limit: int = Query(default=100, ge=1, le=300)) -> list[dict[str, Any]]:
    with db() as connection:
        ids: list[int] | None = None
        terms = re.findall(r"[\w-]+", q.strip())
        if terms:
            expression = " AND ".join('"' + token.replace('"', '') + '"*' for token in terms)
            try:
                ids = [row[0] for row in connection.execute("SELECT rowid FROM experiments_fts WHERE experiments_fts MATCH ? ORDER BY bm25(experiments_fts) LIMIT ?", (expression, limit)).fetchall()]
            except sqlite3.OperationalError:
                ids = []
        clauses: list[str] = []
        args: list[Any] = []
        if status:
            clauses.append("e.status=?"); args.append(status)
        if idea_id is not None:
            clauses.append("EXISTS (SELECT 1 FROM experiment_ideas ei WHERE ei.experiment_id=e.id AND ei.idea_id=?)"); args.append(idea_id)
        if ids is not None:
            if not ids:
                return []
            clauses.append("e.id IN (" + ",".join("?" for _ in ids) + ")"); args.extend(ids)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        rows = connection.execute(f"SELECT e.id FROM micro_experiments e{where} ORDER BY e.updated_at DESC LIMIT ?", [*args, limit]).fetchall()
        return [item for row in rows if (item := _experiment(connection, row["id"])) is not None]


@router.get("/{experiment_id}")
def get_experiment(experiment_id: int) -> dict[str, Any]:
    with db() as connection:
        item = _experiment(connection, experiment_id)
        if not item:
            raise HTTPException(404, "Experiment not found")
        return item


@router.post("")
def create_experiment(payload: ExperimentInput) -> dict[str, Any]:
    tried = payload.what_tried.strip()
    if not tried:
        raise HTTPException(400, "Describe what you tried")
    with db() as connection:
        cursor = connection.execute(
            """INSERT INTO micro_experiments(what_tried,result,takeaway,status,dataset_material,metrics_json,code_ref,metadata_json,completed_at)
               VALUES(?,?,?,?,?,?,?,?,CASE WHEN ? IN ('completed','failed','inconclusive') THEN strftime('%Y-%m-%dT%H:%M:%fZ','now') ELSE NULL END)""",
            (tried,payload.result,payload.takeaway,payload.status,payload.dataset_material,json.dumps(payload.metrics,ensure_ascii=False),payload.code_ref,json.dumps(payload.metadata,ensure_ascii=False),payload.status),
        )
        _write_links(connection, cursor.lastrowid, payload)
        return _experiment(connection, cursor.lastrowid) or {}


@router.put("/{experiment_id}")
def update_experiment(experiment_id: int, payload: ExperimentUpdate) -> dict[str, Any]:
    with db() as connection:
        if not connection.execute("SELECT 1 FROM micro_experiments WHERE id=?", (experiment_id,)).fetchone():
            raise HTTPException(404, "Experiment not found")
        connection.execute(
            """UPDATE micro_experiments SET what_tried=?,result=?,takeaway=?,status=?,dataset_material=?,metrics_json=?,code_ref=?,metadata_json=?,
               updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now'),completed_at=CASE WHEN ? IN ('completed','failed','inconclusive') THEN COALESCE(completed_at,strftime('%Y-%m-%dT%H:%M:%fZ','now')) ELSE NULL END WHERE id=?""",
            (payload.what_tried.strip(),payload.result,payload.takeaway,payload.status,payload.dataset_material,json.dumps(payload.metrics,ensure_ascii=False),payload.code_ref,json.dumps(payload.metadata,ensure_ascii=False),payload.status,experiment_id),
        )
        _write_links(connection, experiment_id, payload)
        return _experiment(connection, experiment_id) or {}


@router.delete("/{experiment_id}")
def delete_experiment(experiment_id: int) -> dict[str, str]:
    with db() as connection:
        cursor = connection.execute("DELETE FROM micro_experiments WHERE id=?", (experiment_id,))
        if not cursor.rowcount:
            raise HTTPException(404, "Experiment not found")
    return {"status": "deleted"}


def _tokens(text: str) -> set[str]:
    return {word.casefold() for word in re.findall(r"[\w-]{2,}", text) if word.casefold() not in {"with", "from", "that", "this", "were", "into", "using"}}


@router.get("/repeat-detection/matches")
def repeat_detection(q: str = Query(min_length=2, max_length=500), idea_id: int | None = None, limit: int = Query(default=5, ge=1, le=20)) -> list[dict[str, Any]]:
    query_tokens = _tokens(q)
    if not query_tokens:
        return []
    with db() as connection:
        rows = connection.execute("SELECT id,what_tried,result,takeaway,dataset_material,status,updated_at FROM micro_experiments ORDER BY updated_at DESC LIMIT 500").fetchall()
        matches = []
        for row in rows:
            feedback_key=f"idea:{idea_id or 0}:experiment:{row['id']}"
            feedback=connection.execute("SELECT action,snooze_until FROM insight_feedback WHERE concept='experiment-repeat' AND subject_key=?",(feedback_key,)).fetchone()
            if feedback and (feedback["action"] in ("dismissed","saved","accepted") or feedback["action"]=="snoozed" and feedback["snooze_until"] and feedback["snooze_until"]>__import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat()):
                continue
            text = " ".join(str(row[key] or "") for key in ("what_tried", "result", "takeaway", "dataset_material"))
            tokens = _tokens(text)
            score = len(tokens & query_tokens) / max(1, len(query_tokens | tokens) ** 0.5 * len(query_tokens) ** 0.5)
            linked = connection.execute("SELECT 1 FROM experiment_ideas WHERE experiment_id=? AND idea_id=?", (row["id"], idea_id)).fetchone() if idea_id is not None else None
            if score >= 0.18 or linked:
                matches.append({**dict(row), "score": round(max(score, 0.5 if linked else 0), 3), "linked_to_idea": bool(linked), "feedback_key":feedback_key})
        return sorted(matches, key=lambda item: (-item["score"], item["updated_at"]))[:limit]
