"""A separate, conservative cross-lineage serendipity candidate generator."""
from __future__ import annotations

import json
import re
from collections import defaultdict
from typing import Any

from fastapi import APIRouter, Query

from .database import db
from .research_insights import DEFAULT_SETTINGS
from .semantic import MODEL, similarity

router = APIRouter(prefix="/api/serendipity", tags=["serendipity"])
_METHODS = {"ablation", "baseline", "contrastive", "clustering", "embedding", "evaluation", "finetuning", "fine-tuning", "interview", "longitudinal", "normalization", "normalisation", "regression", "replication", "sampling", "simulation", "transfer", "validation", "visualization", "visualisation"}
_WORD = re.compile(r"[\w-]{3,}", re.UNICODE)


def _words(text: str) -> set[str]:
    return {word.casefold() for word in _WORD.findall(text)}


@router.get("")
def suggestions(limit: int | None = Query(default=None, ge=1, le=10), project_id: int | None = None) -> list[dict[str, Any]]:
    with db() as connection:
        cfg_row = connection.execute("SELECT settings_json FROM research_intelligence_settings WHERE id=1").fetchone()
        settings = {**DEFAULT_SETTINGS, **json.loads(cfg_row[0] if cfg_row else "{}")}
        if not settings["serendipity_enabled"]:
            return []
        wanted = min(10, max(1, limit or settings["serendipity_limit"]))
        rows = connection.execute("""SELECT i.id,i.title,i.content,i.status,i.project_id,i.created_at,p.name project_name
            FROM ideas i JOIN projects p ON p.id=i.project_id WHERE COALESCE(p.system_key,'') <> 'recycle' ORDER BY i.id""").fetchall()
        ideas = {int(row["id"]): dict(row) for row in rows}
        tags: dict[int, set[str]] = defaultdict(set)
        for row in connection.execute("SELECT it.idea_id,t.name FROM idea_tags it JOIN tags t ON t.id=it.tag_id"):
            tags[row["idea_id"]].add(row["name"].casefold())
        edges: set[tuple[int,int]] = set()
        degree: dict[int,int] = defaultdict(int)
        for row in connection.execute("SELECT source_id,target_id FROM relations"):
            edge=(min(row[0],row[1]),max(row[0],row[1])); edges.add(edge); degree[row[0]]+=1; degree[row[1]]+=1
        vectors = {int(row["idea_id"]): row for row in connection.execute("SELECT idea_id,dimensions,vector FROM idea_embeddings WHERE model=?",(MODEL,))}
        dismissed = {row["subject_key"] for row in connection.execute("SELECT subject_key FROM insight_feedback WHERE concept='serendipity' AND (action IN ('dismissed','saved','accepted') OR action='snoozed' AND (snooze_until IS NULL OR snooze_until>strftime('%Y-%m-%dT%H:%M:%fZ','now')))" )}
        candidates=[]
        ids=sorted(ideas)
        for index, left_id in enumerate(ids):
            left=ideas[left_id]
            left_text=f"{left['title']} {left['content']}"
            left_words=_words(left_text)
            for right_id in ids[index+1:]:
                right=ideas[right_id]
                if project_id is not None and project_id not in (left["project_id"],right["project_id"]):
                    continue
                if not settings["cross_project"] and left["project_id"] != right["project_id"]:
                    continue
                pair_key=f"pair:{left_id}:{right_id}"
                if (left_id,right_id) in edges or pair_key in dismissed:
                    continue
                right_words=_words(f"{right['title']} {right['content']}")
                union=left_words|right_words
                lexical=len(left_words&right_words)/max(1,len(union))
                semantic=0.0
                if left_id in vectors and right_id in vectors:
                    semantic=max(0.0,similarity(vectors[left_id]["vector"],vectors[right_id]["vector"],vectors[left_id]["dimensions"]))
                # Do not introduce obvious neighbors or duplicate-like records.
                if lexical > .72 or semantic > .82:
                    continue
                # Method words provide an interpretable bridge, while score rewards a middle distance.
                shared_methods=sorted((left_words&right_words)&_METHODS)
                if semantic < .12 and lexical < .05 and not shared_methods:
                    continue
                tag_union=tags[left_id]|tags[right_id]
                tag_overlap=len(tags[left_id]&tags[right_id])/max(1,len(tag_union))
                moderate=max(0.0,1-abs(semantic-.42)/.48) if semantic else max(0.0,1-abs(lexical-.12)/.35)
                cross=left["project_id"] != right["project_id"]
                age_days=abs((__import__('datetime').datetime.fromisoformat(left["created_at"].replace('Z','+00:00'))-__import__('datetime').datetime.fromisoformat(right["created_at"].replace('Z','+00:00'))).days)
                older_bonus=min(age_days/730,1)*.12
                score=.50*moderate+.18*(1-tag_overlap)+.18*float(cross)+.12*float(bool(shared_methods))+.10*(1 if min(degree[left_id],degree[right_id]) else .5)+older_bonus
                if score < .25:
                    continue
                if shared_methods:
                    reason=f"Both touch {', '.join(shared_methods[:2])}; their topics and lineages differ."
                elif cross:
                    reason="A lower-similarity idea from another project may offer a useful method or structure."
                else:
                    reason="A lower-similarity idea with a different graph position may offer a useful bridge."
                candidates.append({"source_id":left_id,"source_title":left["title"],"source_project":left["project_name"],"target_id":right_id,"target_title":right["title"],"target_project":right["project_name"],"score":round(score,3),"semantic_similarity":round(semantic,3),"reason":reason,"feedback_key":pair_key})
        candidates.sort(key=lambda item:(-item["score"],item["source_id"],item["target_id"]))
        # Show a handful of distinct ideas rather than several near-identical pairings.
        chosen=[]; used=set()
        for item in candidates:
            if item["source_id"] in used or item["target_id"] in used: continue
            chosen.append(item); used.update((item["source_id"],item["target_id"]))
            if len(chosen)>=wanted: break
        return chosen
