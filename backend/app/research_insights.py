"""Deterministic, local research development gap radar and feedback memory."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .database import db

router = APIRouter(prefix="/api/research-intelligence", tags=["research-intelligence"])

DEFAULT_SETTINGS: dict[str, Any] = {"experiments_enabled": True, "gap_radar_enabled": True, "serendipity_enabled": True, "stalled_days": 30, "serendipity_limit": 4, "cross_project": True, "evidence_checks": True, "experiment_fields": []}


class SettingsPatch(BaseModel):
    experiments_enabled: bool | None = None
    gap_radar_enabled: bool | None = None
    serendipity_enabled: bool | None = None
    stalled_days: int | None = Field(default=None, ge=7, le=365)
    serendipity_limit: int | None = Field(default=None, ge=1, le=10)
    cross_project: bool | None = None
    evidence_checks: bool | None = None
    experiment_fields: list[str] | None = Field(default=None, max_length=30)


class FeedbackInput(BaseModel):
    concept: Literal["serendipity", "research-gap", "experiment-repeat"]
    subject_key: str = Field(min_length=1, max_length=300)
    action: Literal["dismissed", "saved", "resolved", "snoozed", "accepted"]
    snooze_until: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


@router.get("/settings")
def get_settings() -> dict[str, Any]:
    with db() as connection:
        row = connection.execute("SELECT settings_json FROM research_intelligence_settings WHERE id=1").fetchone()
        return {**DEFAULT_SETTINGS, **json.loads(row[0] if row else "{}")}


@router.put("/settings")
def update_settings(payload: SettingsPatch) -> dict[str, Any]:
    with db() as connection:
        row = connection.execute("SELECT settings_json FROM research_intelligence_settings WHERE id=1").fetchone()
        settings = {**DEFAULT_SETTINGS, **json.loads(row[0] if row else "{}"), **payload.model_dump(exclude_none=True)}
        connection.execute("UPDATE research_intelligence_settings SET settings_json=?,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=1", (json.dumps(settings, ensure_ascii=False),))
        return settings


@router.post("/feedback")
def save_feedback(payload: FeedbackInput) -> dict[str, Any]:
    if payload.action == "snoozed" and not payload.snooze_until:
        raise HTTPException(400, "A snooze date is required")
    with db() as connection:
        connection.execute("""INSERT INTO insight_feedback(concept,subject_key,action,snooze_until,metadata_json)
            VALUES(?,?,?,?,?) ON CONFLICT(concept,subject_key) DO UPDATE SET action=excluded.action,snooze_until=excluded.snooze_until,metadata_json=excluded.metadata_json,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')""",
            (payload.concept,payload.subject_key,payload.action,payload.snooze_until,json.dumps(payload.metadata, ensure_ascii=False)))
        row = connection.execute("SELECT * FROM insight_feedback WHERE concept=? AND subject_key=?", (payload.concept,payload.subject_key)).fetchone()
        return dict(row)


def _scope_clause(project_id: int | None, group_id: int | None) -> tuple[str, list[Any]]:
    if project_id is not None:
        return "i.project_id=?", [project_id]
    if group_id is not None:
        return "i.project_id IN (SELECT id FROM projects WHERE group_id=?)", [group_id]
    return "p.system_key IS NULL", []


def _feedback_active(connection: sqlite3.Connection, key: str) -> bool:
    row = connection.execute("SELECT action,snooze_until FROM insight_feedback WHERE concept='research-gap' AND subject_key=?", (key,)).fetchone()
    if not row:
        return False
    if row["action"] == "snoozed":
        return bool(row["snooze_until"] and row["snooze_until"] > datetime.now(timezone.utc).isoformat())
    return row["action"] in ("dismissed", "resolved", "accepted", "saved")


def _gap(connection: sqlite3.Connection, kind: str, key: str, title: str, detail: str, target: dict[str, Any], priority: int) -> dict[str, Any] | None:
    subject = f"{kind}:{key}"
    if _feedback_active(connection, subject):
        return None
    return {"id": subject, "type": kind, "title": title, "detail": detail, "target": target, "priority": priority}


@router.get("/gaps")
def gaps(project_id: int | None = None, group_id: int | None = None, limit: int = 40) -> list[dict[str, Any]]:
    with db() as connection:
        settings = {**DEFAULT_SETTINGS, **json.loads(connection.execute("SELECT settings_json FROM research_intelligence_settings WHERE id=1").fetchone()[0])}
        if not settings["gap_radar_enabled"]:
            return []
        clause, args = _scope_clause(project_id, group_id)
        ideas = connection.execute(f"SELECT i.* FROM ideas i JOIN projects p ON p.id=i.project_id WHERE {clause} ORDER BY i.updated_at DESC", args).fetchall()
        project_ideas = {int(i["id"]): dict(i) for i in ideas}
        idea_ids = set(project_ideas)
        result: list[dict[str, Any]] = []
        if idea_ids:
            marks=",".join("?" for _ in idea_ids)
            scoped_ids=sorted(idea_ids)
            relations = connection.execute(f"SELECT r.* FROM relations r WHERE r.source_id IN ({marks}) OR r.target_id IN ({marks})", [*scoped_ids,*scoped_ids]).fetchall()
        else:
            relations=[]
        incident: dict[int, list[sqlite3.Row]] = {idea_id: [] for idea_id in idea_ids}
        for relation in relations:
            incident.setdefault(relation["source_id"], []).append(relation); incident.setdefault(relation["target_id"], []).append(relation)
            if relation["relation_type"] == "contradicts":
                pair_key = f"relation:{min(relation['source_id'],relation['target_id'])}:{max(relation['source_id'],relation['target_id'])}"
                resolution = connection.execute("SELECT 1 FROM insight_feedback WHERE concept='research-gap' AND subject_key=? AND action='resolved'", (f"unresolved-contradiction:{pair_key}",)).fetchone()
                if not resolution:
                    gap = _gap(connection,"unresolved-contradiction",pair_key,"Unresolved contradiction","Record whether this evidence is reconciled or still open.",{"idea_id":relation["source_id"],"relation_id":relation["id"]},95)
                    if gap: result.append(gap)
        linked_experiments: dict[int, list[sqlite3.Row]] = {idea_id: [] for idea_id in idea_ids}
        if idea_ids:
            marks=",".join("?" for _ in idea_ids)
            exp_rows = connection.execute(f"""SELECT e.*,ei.idea_id,ei.role FROM micro_experiments e JOIN experiment_ideas ei ON ei.experiment_id=e.id
                WHERE ei.idea_id IN ({marks})""", sorted(idea_ids)).fetchall()
        else:
            exp_rows=[]
        for exp in exp_rows:
            linked_experiments.setdefault(exp["idea_id"], []).append(exp)
            if exp["status"] in ("completed","failed","inconclusive") and not exp["takeaway"].strip():
                gap = _gap(connection,"experiment-without-takeaway",str(exp["id"]),"Result needs a takeaway",exp["what_tried"],{"experiment_id":exp["id"],"idea_id":exp["idea_id"]},90)
                if gap: result.append(gap)
            if exp["status"] == "needs_follow_up":
                follow = connection.execute("SELECT 1 FROM experiment_ideas WHERE experiment_id=? AND role='follow-up'", (exp["id"],)).fetchone()
                if not follow:
                    gap = _gap(connection,"experiment-without-follow-up",str(exp["id"]),"Experiment needs a follow-up",exp["what_tried"],{"experiment_id":exp["id"],"idea_id":exp["idea_id"]},85)
                    if gap: result.append(gap)
        for idea_id, idea in project_ideas.items():
            promising = idea["status"] == "promising"
            experiments = linked_experiments.get(idea_id, [])
            if promising and not experiments:
                gap = _gap(connection,"promising-untested",str(idea_id),"Promising idea has no experiment",idea["title"],{"idea_id":idea_id},100)
                if gap: result.append(gap)
            if settings["evidence_checks"] and promising:
                evidence = connection.execute("SELECT 1 FROM relations WHERE (source_id=? OR target_id=?) AND relation_type='evidence-for' LIMIT 1",(idea_id,idea_id)).fetchone()
                supporting = any(e["status"] == "completed" and e["role"] == "supports" for e in experiments)
                contradicting = any(e["status"] in ("failed","inconclusive") and e["role"] == "contradicts" for e in experiments)
                if not evidence and not supporting and not contradicting:
                    gap = _gap(connection,"needs-evidence",str(idea_id),"Promising idea needs evidence",idea["title"],{"idea_id":idea_id},80)
                    if gap: result.append(gap)
            if idea["status"] in ("seed","exploring","promising"):
                descendants = connection.execute("""WITH RECURSIVE lineage(id) AS (
                    SELECT target_id FROM relations WHERE source_id=? AND relation_type IN ('develops-into','follow-up','extends','refines')
                    UNION SELECT r.target_id FROM relations r JOIN lineage l ON r.source_id=l.id WHERE r.relation_type IN ('develops-into','follow-up','extends','refines')
                    ) SELECT MAX(i.updated_at) FROM lineage JOIN ideas i ON i.id=lineage.id""",(idea_id,)).fetchone()[0]
                meaningful = connection.execute("SELECT MAX(updated_at) FROM micro_experiments e JOIN experiment_ideas ei ON ei.experiment_id=e.id WHERE ei.idea_id=? AND e.status IN ('running','completed','failed','inconclusive','needs_follow_up')",(idea_id,)).fetchone()[0]
                last_activity=max([value for value in (idea["updated_at"],descendants,meaningful) if value] or [idea["updated_at"]])
                old = connection.execute("SELECT julianday('now')-julianday(?)>=?",(last_activity,settings["stalled_days"])).fetchone()[0]
                if old:
                    gap = _gap(connection,"stalled-branch",str(idea_id),"Branch stopped developing",idea["title"],{"idea_id":idea_id},65)
                    if gap: result.append(gap)
            if promising and not incident.get(idea_id):
                gap = _gap(connection,"isolated-high-value",str(idea_id),"Promising idea is isolated",idea["title"],{"idea_id":idea_id},55)
                if gap: result.append(gap)
        # A shared tag across several ideas is a deterministic local theme signal.
        # Suppress themes already synthesized by a combines-with/merges-into edge.
        tag_ideas: dict[str, list[int]] = {}
        for row in connection.execute("SELECT it.idea_id,t.name FROM idea_tags it JOIN tags t ON t.id=it.tag_id"):
            if row["idea_id"] in project_ideas:
                tag_ideas.setdefault(row["name"].casefold(), []).append(row["idea_id"])
        for tag, members in tag_ideas.items():
            members=sorted(set(members))
            if len(members)<3:
                continue
            marks=",".join("?" for _ in members)
            synthesized=connection.execute(f"SELECT 1 FROM relations WHERE relation_type IN ('combines-with','merges-into','synthesizes') AND source_id IN ({marks}) AND target_id IN ({marks}) LIMIT 1",[*members,*members]).fetchone()
            if not synthesized:
                key=f"tag:{tag}:"+",".join(map(str,members))
                gap=_gap(connection,"repeated-theme",key,"Repeated theme needs synthesis",f"{len(members)} ideas share #{tag} without a synthesis connection.",{"idea_id":members[0]},45)
                if gap: result.append(gap)
        return sorted(result,key=lambda item:(-item["priority"],item["id"]))[:max(1,min(limit,100))]


@router.get("/weekly-review")
def experiment_review(project_id: int | None = None, group_id: int | None = None) -> dict[str, Any]:
    if project_id is not None:
        scoped = "i.project_id=?"; args: list[Any] = [project_id]
    elif group_id is not None:
        scoped = "i.project_id IN (SELECT id FROM projects WHERE group_id=?)"; args = [group_id]
    else:
        scoped = "(i.project_id IS NULL OR p.system_key IS NULL)"; args = []
    with db() as connection:
        cfg=connection.execute("SELECT settings_json FROM research_intelligence_settings WHERE id=1").fetchone()
        if not {**DEFAULT_SETTINGS,**json.loads(cfg[0] if cfg else "{}")}["experiments_enabled"]:
            return {"recently_completed":[],"inconclusive":[],"failed":[],"untouched_planned":[]}
        rows=connection.execute(f"""SELECT DISTINCT e.* FROM micro_experiments e LEFT JOIN experiment_ideas ei ON ei.experiment_id=e.id
            LEFT JOIN ideas i ON i.id=ei.idea_id LEFT JOIN projects p ON p.id=i.project_id
            WHERE {scoped} ORDER BY e.updated_at DESC""", args).fetchall()
        data=[]
        for row in rows:
            item=dict(row)
            item["ideas"]=[dict(link) for link in connection.execute("SELECT i.id idea_id,i.title,ei.role FROM experiment_ideas ei JOIN ideas i ON i.id=ei.idea_id WHERE ei.experiment_id=?",(row["id"],))]
            data.append(item)
        return {"recently_completed":[e for e in data if e["status"] in ("completed","failed","inconclusive") and e["completed_at"] and connection.execute("SELECT julianday(?)>=julianday('now')-7",(e["completed_at"],)).fetchone()[0]],
            "inconclusive":[e for e in data if e["status"]=="inconclusive"],"failed":[e for e in data if e["status"]=="failed"],
            "untouched_planned":[e for e in data if e["status"]=="planned" and connection.execute("SELECT julianday('now')-julianday(?)>=7",(e["created_at"],)).fetchone()[0]]}
