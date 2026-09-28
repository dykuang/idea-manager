from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


ROOT = Path(__file__).resolve().parents[2]
DB_PATH = Path(os.environ.get("IDEAMINER_DB", ROOT / "data" / "ideaminer.db"))


SCHEMA = """
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS project_groups (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL COLLATE NOCASE UNIQUE,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL COLLATE NOCASE UNIQUE,
    description TEXT NOT NULL DEFAULT '',
    group_id INTEGER REFERENCES project_groups(id) ON DELETE SET NULL,
    workspace_mode TEXT NOT NULL DEFAULT 'library',
    workspace_path TEXT NOT NULL DEFAULT '',
    system_key TEXT UNIQUE CHECK(system_key IS NULL OR system_key IN ('random_chat', 'recycle')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS attachments (
    id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    display_name TEXT NOT NULL,
    path TEXT NOT NULL,
    storage_mode TEXT NOT NULL CHECK(storage_mode IN ('linked', 'managed')),
    mime_type TEXT NOT NULL DEFAULT '',
    size_bytes INTEGER NOT NULL DEFAULT 0,
    modified_at REAL,
    content_hash TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE(project_id, path)
);

CREATE TABLE IF NOT EXISTS idea_attachments (
    idea_id INTEGER NOT NULL REFERENCES ideas(id) ON DELETE CASCADE,
    attachment_id INTEGER NOT NULL REFERENCES attachments(id) ON DELETE CASCADE,
    asset_role TEXT NOT NULL DEFAULT 'attachment' CHECK(asset_role IN ('attachment', 'figure')),
    caption TEXT NOT NULL DEFAULT '',
    sort_order INTEGER NOT NULL DEFAULT 0,
    is_cover INTEGER NOT NULL DEFAULT 0 CHECK(is_cover IN (0, 1)),
    PRIMARY KEY (idea_id, attachment_id)
);

CREATE TABLE IF NOT EXISTS ideas (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL CHECK(length(trim(title)) > 0),
    content TEXT NOT NULL DEFAULT '',
    raw_text TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'seed' CHECK(status IN ('seed', 'exploring', 'promising', 'parked')),
    project_id INTEGER REFERENCES projects(id),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS tags (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL COLLATE NOCASE UNIQUE
);

CREATE TABLE IF NOT EXISTS tag_settings (
    tag_id INTEGER PRIMARY KEY REFERENCES tags(id) ON DELETE CASCADE,
    group_name TEXT NOT NULL DEFAULT '',
    is_hidden INTEGER NOT NULL DEFAULT 0 CHECK(is_hidden IN (0, 1))
);

CREATE TABLE IF NOT EXISTS idea_tags (
    idea_id INTEGER NOT NULL REFERENCES ideas(id) ON DELETE CASCADE,
    tag_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY (idea_id, tag_id)
);

CREATE TABLE IF NOT EXISTS relations (
    id INTEGER PRIMARY KEY,
    source_id INTEGER NOT NULL REFERENCES ideas(id) ON DELETE CASCADE,
    target_id INTEGER NOT NULL REFERENCES ideas(id) ON DELETE CASCADE,
    relation_type TEXT NOT NULL CHECK(length(trim(relation_type)) > 0),
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    CHECK(source_id <> target_id),
    UNIQUE(source_id, target_id, relation_type)
);

CREATE TABLE IF NOT EXISTS idea_revisions (
    id INTEGER PRIMARY KEY,
    idea_id INTEGER NOT NULL REFERENCES ideas(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    saved_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS idea_embeddings (
    idea_id INTEGER NOT NULL REFERENCES ideas(id) ON DELETE CASCADE,
    model TEXT NOT NULL,
    dimensions INTEGER NOT NULL,
    vector BLOB NOT NULL,
    content_hash TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    PRIMARY KEY (idea_id, model)
);

CREATE TABLE IF NOT EXISTS agent_runs (
    id INTEGER PRIMARY KEY,
    provider TEXT NOT NULL DEFAULT 'openai',
    model TEXT NOT NULL,
    prompt TEXT NOT NULL,
    mode TEXT NOT NULL,
    scope_type TEXT NOT NULL,
    scope_id INTEGER,
    idea_id INTEGER REFERENCES ideas(id) ON DELETE SET NULL,
    context_json TEXT NOT NULL DEFAULT '{}',
    response_text TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL CHECK(status IN ('completed', 'failed')),
    error TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS agent_proposals (
    id INTEGER PRIMARY KEY,
    run_id INTEGER NOT NULL REFERENCES agent_runs(id) ON DELETE CASCADE,
    action_type TEXT NOT NULL CHECK(action_type IN ('create_idea', 'update_idea', 'create_relation')),
    title TEXT NOT NULL,
    rationale TEXT NOT NULL DEFAULT '',
    payload_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending', 'applied', 'dismissed')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    resolved_at TEXT
);

CREATE TABLE IF NOT EXISTS agent_run_saves (
    run_id INTEGER PRIMARY KEY REFERENCES agent_runs(id) ON DELETE CASCADE,
    action TEXT NOT NULL CHECK(action IN ('update_original', 'create_child')),
    idea_id INTEGER NOT NULL REFERENCES ideas(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS external_actions (
    idempotency_key TEXT PRIMARY KEY,
    action_type TEXT NOT NULL,
    response_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS library_state (
    id INTEGER PRIMARY KEY CHECK(id = 1),
    revision INTEGER NOT NULL DEFAULT 0
);
INSERT OR IGNORE INTO library_state(id, revision) VALUES (1, 0);

CREATE VIRTUAL TABLE IF NOT EXISTS ideas_fts USING fts5(
    title, content, raw_text,
    content='ideas', content_rowid='id',
    tokenize='porter unicode61'
);

CREATE TRIGGER IF NOT EXISTS ideas_ai AFTER INSERT ON ideas BEGIN
    INSERT INTO ideas_fts(rowid, title, content, raw_text)
    VALUES (new.id, new.title, new.content, new.raw_text);
END;
CREATE TRIGGER IF NOT EXISTS ideas_ad AFTER DELETE ON ideas BEGIN
    INSERT INTO ideas_fts(ideas_fts, rowid, title, content, raw_text)
    VALUES ('delete', old.id, old.title, old.content, old.raw_text);
END;
CREATE TRIGGER IF NOT EXISTS ideas_au AFTER UPDATE OF title, content ON ideas BEGIN
    INSERT INTO ideas_fts(ideas_fts, rowid, title, content, raw_text)
    VALUES ('delete', old.id, old.title, old.content, old.raw_text);
    INSERT INTO ideas_fts(rowid, title, content, raw_text)
    VALUES (new.id, new.title, new.content, new.raw_text);
END;

CREATE TRIGGER IF NOT EXISTS library_ideas_ai AFTER INSERT ON ideas BEGIN
    UPDATE library_state SET revision=revision+1 WHERE id=1;
END;
CREATE TRIGGER IF NOT EXISTS library_ideas_au AFTER UPDATE ON ideas BEGIN
    UPDATE library_state SET revision=revision+1 WHERE id=1;
END;
CREATE TRIGGER IF NOT EXISTS library_ideas_ad AFTER DELETE ON ideas BEGIN
    UPDATE library_state SET revision=revision+1 WHERE id=1;
END;
CREATE TRIGGER IF NOT EXISTS library_idea_tags_ai AFTER INSERT ON idea_tags BEGIN
    UPDATE library_state SET revision=revision+1 WHERE id=1;
END;
CREATE TRIGGER IF NOT EXISTS library_idea_tags_ad AFTER DELETE ON idea_tags BEGIN
    UPDATE library_state SET revision=revision+1 WHERE id=1;
END;
CREATE TRIGGER IF NOT EXISTS library_tag_settings_ai AFTER INSERT ON tag_settings BEGIN
    UPDATE library_state SET revision=revision+1 WHERE id=1;
END;
CREATE TRIGGER IF NOT EXISTS library_tag_settings_au AFTER UPDATE ON tag_settings BEGIN
    UPDATE library_state SET revision=revision+1 WHERE id=1;
END;
CREATE TRIGGER IF NOT EXISTS library_tag_settings_ad AFTER DELETE ON tag_settings BEGIN
    UPDATE library_state SET revision=revision+1 WHERE id=1;
END;
CREATE TRIGGER IF NOT EXISTS library_relations_ai AFTER INSERT ON relations BEGIN
    UPDATE library_state SET revision=revision+1 WHERE id=1;
END;
CREATE TRIGGER IF NOT EXISTS library_relations_ad AFTER DELETE ON relations BEGIN
    UPDATE library_state SET revision=revision+1 WHERE id=1;
END;
CREATE TRIGGER IF NOT EXISTS library_attachments_ai AFTER INSERT ON attachments BEGIN
    UPDATE library_state SET revision=revision+1 WHERE id=1;
END;
CREATE TRIGGER IF NOT EXISTS library_attachments_au AFTER UPDATE ON attachments BEGIN
    UPDATE library_state SET revision=revision+1 WHERE id=1;
END;
CREATE TRIGGER IF NOT EXISTS library_attachments_ad AFTER DELETE ON attachments BEGIN
    UPDATE library_state SET revision=revision+1 WHERE id=1;
END;
CREATE TRIGGER IF NOT EXISTS library_idea_attachments_ai AFTER INSERT ON idea_attachments BEGIN
    UPDATE library_state SET revision=revision+1 WHERE id=1;
END;
CREATE TRIGGER IF NOT EXISTS library_idea_attachments_ad AFTER DELETE ON idea_attachments BEGIN
    UPDATE library_state SET revision=revision+1 WHERE id=1;
END;
CREATE TRIGGER IF NOT EXISTS library_idea_attachments_au AFTER UPDATE ON idea_attachments BEGIN
    UPDATE library_state SET revision=revision+1 WHERE id=1;
END;
CREATE TRIGGER IF NOT EXISTS library_projects_ai AFTER INSERT ON projects BEGIN
    UPDATE library_state SET revision=revision+1 WHERE id=1;
END;
CREATE TRIGGER IF NOT EXISTS library_projects_au AFTER UPDATE ON projects BEGIN
    UPDATE library_state SET revision=revision+1 WHERE id=1;
END;
CREATE TRIGGER IF NOT EXISTS library_projects_ad AFTER DELETE ON projects BEGIN
    UPDATE library_state SET revision=revision+1 WHERE id=1;
END;
CREATE TRIGGER IF NOT EXISTS library_project_groups_ai AFTER INSERT ON project_groups BEGIN
    UPDATE library_state SET revision=revision+1 WHERE id=1;
END;
CREATE TRIGGER IF NOT EXISTS library_project_groups_au AFTER UPDATE ON project_groups BEGIN
    UPDATE library_state SET revision=revision+1 WHERE id=1;
END;
CREATE TRIGGER IF NOT EXISTS library_project_groups_ad AFTER DELETE ON project_groups BEGIN
    UPDATE library_state SET revision=revision+1 WHERE id=1;
END;
CREATE TRIGGER IF NOT EXISTS library_agent_proposals_ai AFTER INSERT ON agent_proposals BEGIN
    UPDATE library_state SET revision=revision+1 WHERE id=1;
END;
CREATE TRIGGER IF NOT EXISTS library_agent_proposals_au AFTER UPDATE ON agent_proposals BEGIN
    UPDATE library_state SET revision=revision+1 WHERE id=1;
END;
CREATE TRIGGER IF NOT EXISTS library_agent_proposals_ad AFTER DELETE ON agent_proposals BEGIN
    UPDATE library_state SET revision=revision+1 WHERE id=1;
END;

CREATE INDEX IF NOT EXISTS idx_ideas_updated ON ideas(updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_relations_source ON relations(source_id);
CREATE INDEX IF NOT EXISTS idx_relations_target ON relations(target_id);
CREATE INDEX IF NOT EXISTS idx_relations_source_type_target ON relations(source_id, relation_type, target_id);
CREATE INDEX IF NOT EXISTS idx_relations_target_type_source ON relations(target_id, relation_type, source_id);
CREATE INDEX IF NOT EXISTS idx_agent_runs_created ON agent_runs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_run_saves_idea ON agent_run_saves(idea_id);
CREATE INDEX IF NOT EXISTS idx_agent_proposals_run ON agent_proposals(run_id, status);
CREATE INDEX IF NOT EXISTS idx_attachments_project ON attachments(project_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_idea_attachments_attachment ON idea_attachments(attachment_id);
"""

RESEARCH_SCHEMA = """
CREATE TABLE IF NOT EXISTS micro_experiments (
    id INTEGER PRIMARY KEY,
    what_tried TEXT NOT NULL,
    result TEXT NOT NULL DEFAULT '',
    takeaway TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'planned' CHECK(status IN ('planned','running','completed','failed','inconclusive','needs_follow_up')),
    dataset_material TEXT NOT NULL DEFAULT '',
    metrics_json TEXT NOT NULL DEFAULT '{}',
    code_ref TEXT NOT NULL DEFAULT '',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    completed_at TEXT
);
CREATE TABLE IF NOT EXISTS experiment_ideas (
    experiment_id INTEGER NOT NULL REFERENCES micro_experiments(id) ON DELETE CASCADE,
    idea_id INTEGER NOT NULL REFERENCES ideas(id) ON DELETE CASCADE,
    role TEXT NOT NULL DEFAULT 'tests' CHECK(role IN ('tests','supports','contradicts','motivated-by','follow-up')),
    PRIMARY KEY(experiment_id, idea_id, role)
);
CREATE TABLE IF NOT EXISTS experiment_attachments (
    experiment_id INTEGER NOT NULL REFERENCES micro_experiments(id) ON DELETE CASCADE,
    attachment_id INTEGER NOT NULL REFERENCES attachments(id) ON DELETE CASCADE,
    asset_role TEXT NOT NULL DEFAULT 'figure' CHECK(asset_role IN ('attachment','figure')),
    caption TEXT NOT NULL DEFAULT '',
    sort_order INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(experiment_id, attachment_id)
);
CREATE VIRTUAL TABLE IF NOT EXISTS experiments_fts USING fts5(what_tried, result, takeaway, dataset_material, metrics, code_ref, content='');
CREATE TABLE IF NOT EXISTS insight_feedback (
    id INTEGER PRIMARY KEY,
    concept TEXT NOT NULL CHECK(concept IN ('serendipity','research-gap','experiment-repeat')),
    subject_key TEXT NOT NULL,
    action TEXT NOT NULL CHECK(action IN ('dismissed','saved','resolved','snoozed','accepted')),
    snooze_until TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE(concept, subject_key)
);
CREATE TABLE IF NOT EXISTS research_intelligence_settings (
    id INTEGER PRIMARY KEY CHECK(id=1),
    settings_json TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
INSERT OR IGNORE INTO research_intelligence_settings(id, settings_json) VALUES (1, '{"experiments_enabled":true,"gap_radar_enabled":true,"serendipity_enabled":true,"stalled_days":30,"serendipity_limit":4,"cross_project":true,"evidence_checks":true,"experiment_fields":[]}');
CREATE INDEX IF NOT EXISTS idx_experiments_updated ON micro_experiments(updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_experiment_ideas_idea ON experiment_ideas(idea_id, role);
CREATE INDEX IF NOT EXISTS idx_feedback_action ON insight_feedback(concept, action, snooze_until);
CREATE TRIGGER IF NOT EXISTS experiments_fts_ai AFTER INSERT ON micro_experiments BEGIN
 INSERT INTO experiments_fts(rowid,what_tried,result,takeaway,dataset_material,metrics,code_ref) VALUES(new.id,new.what_tried,new.result,new.takeaway,new.dataset_material,new.metrics_json,new.code_ref);
END;
CREATE TRIGGER IF NOT EXISTS experiments_fts_ad AFTER DELETE ON micro_experiments BEGIN
 INSERT INTO experiments_fts(experiments_fts,rowid,what_tried,result,takeaway,dataset_material,metrics,code_ref) VALUES('delete',old.id,old.what_tried,old.result,old.takeaway,old.dataset_material,old.metrics_json,old.code_ref);
END;
CREATE TRIGGER IF NOT EXISTS experiments_fts_au AFTER UPDATE ON micro_experiments BEGIN
 INSERT INTO experiments_fts(experiments_fts,rowid,what_tried,result,takeaway,dataset_material,metrics,code_ref) VALUES('delete',old.id,old.what_tried,old.result,old.takeaway,old.dataset_material,old.metrics_json,old.code_ref);
 INSERT INTO experiments_fts(rowid,what_tried,result,takeaway,dataset_material,metrics,code_ref) VALUES(new.id,new.what_tried,new.result,new.takeaway,new.dataset_material,new.metrics_json,new.code_ref);
END;
CREATE TRIGGER IF NOT EXISTS library_experiments_ai AFTER INSERT ON micro_experiments BEGIN UPDATE library_state SET revision=revision+1 WHERE id=1; END;
CREATE TRIGGER IF NOT EXISTS library_experiments_au AFTER UPDATE ON micro_experiments BEGIN UPDATE library_state SET revision=revision+1 WHERE id=1; END;
CREATE TRIGGER IF NOT EXISTS library_experiments_ad AFTER DELETE ON micro_experiments BEGIN UPDATE library_state SET revision=revision+1 WHERE id=1; END;
CREATE TRIGGER IF NOT EXISTS library_experiment_ideas_ai AFTER INSERT ON experiment_ideas BEGIN UPDATE library_state SET revision=revision+1 WHERE id=1; END;
CREATE TRIGGER IF NOT EXISTS library_experiment_ideas_ad AFTER DELETE ON experiment_ideas BEGIN UPDATE library_state SET revision=revision+1 WHERE id=1; END;
CREATE TRIGGER IF NOT EXISTS library_experiment_attachments_ai AFTER INSERT ON experiment_attachments BEGIN UPDATE library_state SET revision=revision+1 WHERE id=1; END;
CREATE TRIGGER IF NOT EXISTS library_experiment_attachments_ad AFTER DELETE ON experiment_attachments BEGIN UPDATE library_state SET revision=revision+1 WHERE id=1; END;
"""


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def init_db() -> None:
    with connect() as connection:
        connection.executescript(SCHEMA)
        connection.executescript(RESEARCH_SCHEMA)
        attachment_columns = {row["name"] for row in connection.execute("PRAGMA table_info(idea_attachments)")}
        for name, definition in (
            ("asset_role", "TEXT NOT NULL DEFAULT 'attachment' CHECK(asset_role IN ('attachment', 'figure'))"),
            ("caption", "TEXT NOT NULL DEFAULT ''"),
            ("sort_order", "INTEGER NOT NULL DEFAULT 0"),
            ("is_cover", "INTEGER NOT NULL DEFAULT 0 CHECK(is_cover IN (0, 1))"),
        ):
            if name not in attachment_columns:
                connection.execute(f"ALTER TABLE idea_attachments ADD COLUMN {name} {definition}")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_idea_attachments_figures ON idea_attachments(idea_id, sort_order) WHERE asset_role='figure'")
        connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_idea_attachments_one_cover ON idea_attachments(idea_id) WHERE is_cover=1")
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(ideas)")}
        if "project_id" not in columns:
            connection.execute("ALTER TABLE ideas ADD COLUMN project_id INTEGER REFERENCES projects(id)")
        project_columns = {row["name"] for row in connection.execute("PRAGMA table_info(projects)")}
        if "workspace_mode" not in project_columns:
            connection.execute("ALTER TABLE projects ADD COLUMN workspace_mode TEXT NOT NULL DEFAULT 'library'")
        if "workspace_path" not in project_columns:
            connection.execute("ALTER TABLE projects ADD COLUMN workspace_path TEXT NOT NULL DEFAULT ''")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_ideas_project ON ideas(project_id, updated_at DESC)")
        connection.execute(
            "INSERT OR IGNORE INTO projects(name, description, system_key) VALUES ('random_chat', 'Quick captures and uncategorized ideas', 'random_chat')"
        )
        connection.execute(
            "INSERT OR IGNORE INTO projects(name, description, system_key) VALUES ('recycle', 'Deleted ideas waiting for permanent removal', 'recycle')"
        )
        default_id = connection.execute("SELECT id FROM projects WHERE system_key='random_chat'").fetchone()["id"]
        connection.execute("UPDATE ideas SET project_id=? WHERE project_id IS NULL", (default_id,))
        connection.execute("DELETE FROM tags WHERE NOT EXISTS (SELECT 1 FROM idea_tags WHERE idea_tags.tag_id=tags.id)")


@contextmanager
def db() -> Iterator[sqlite3.Connection]:
    connection = connect()
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
