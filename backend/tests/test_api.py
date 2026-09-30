import json
import os
import sqlite3
import stat
import tempfile
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

handle = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
handle.close()
os.environ["IDEAMINER_DB"] = handle.name
os.environ.pop("OPENAI_API_KEY", None)
os.environ.pop("DEEPSEEK_API_KEY", None)
os.environ.pop("IDEAMINER_AGENT_PROVIDER", None)
os.environ.pop("IDEAMINER_AGENT_API_KEY", None)
os.environ.pop("IDEAMINER_AGENT_BASE_URL", None)

from fastapi.testclient import TestClient
from backend.app.database import db
from backend.app import database as database_module
from backend.app.main import _agent_context, app
from backend.app import main as main_module
from backend.app import remote_sync as remote_sync_module
from backend.app.schemas import AgentRunRequest
from backend.app.mcp_server import (
    copy_idea as mcp_copy_idea,
    create_codex_checkpoint as mcp_create_codex_checkpoint,
    create_idea as mcp_create_idea,
    create_project as mcp_create_project,
    get_idea as mcp_get_idea,
    move_idea as mcp_move_idea,
    search_ideas as mcp_search_ideas,
    update_idea as mcp_update_idea,
)
from backend.app.mcp_server import log_micro_experiment as mcp_log_micro_experiment, search_micro_experiments as mcp_search_micro_experiments


def test_deepseek_responses_provider(monkeypatch):
    captured = {}

    class FakeResponse:
        status_code = 200
        text = ""

        @staticmethod
        def json():
            return {"output": [{"type": "function_call", "name": "submit_research_result", "arguments": json.dumps({"answer": "# Refined agent idea\n\nDeveloped content", "proposals": []})}]}

    class FakeClient:
        def __init__(self, **_):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            pass

        async def post(self, url, headers, json):
            captured.update({"url": url, "headers": headers, "body": json})
            return FakeResponse()

    monkeypatch.setattr("backend.app.main.httpx.AsyncClient", FakeClient)
    with TestClient(app) as client:
        client.post("/api/agent/config", json={"provider": "deepseek", "api_key": "deepseek-test-key", "model": "deepseek-v4-flash"})
        parent = client.post("/api/ideas", json={"title": "Original agent idea", "content": "Original working content", "raw_text": "Immutable capture", "tags": ["agent-save"]}).json()
        result = client.post("/api/agent/runs", json={"prompt": "Elaborate", "mode": "elaborate", "scope_type": "all", "idea_id": parent["id"], "web_search": True})
        assert result.status_code == 200
        assert result.json()["provider"] == "deepseek"
        assert captured["url"] == "https://api.deepseek.com/responses"
        assert captured["body"]["reasoning"] == {"effort": "none"}
        assert captured["body"]["tools"][0] == {"type": "web_search"}
        assert "Never expose a raw reference" in captured["body"]["instructions"]
        assert captured["headers"]["Authorization"] == "Bearer deepseek-test-key"
        child_save = client.post(f"/api/agent/runs/{result.json()['id']}/save", json={"action": "create_child"})
        assert child_save.status_code == 200
        child = child_save.json()["idea"]
        assert child["title"] == "Refined agent idea"
        assert child["content"] == "Developed content"
        assert child["tags"] == ["agent-save"]
        assert child["project_id"] == parent["project_id"]
        assert client.post(f"/api/agent/runs/{result.json()['id']}/save", json={"action": "update_original"}).status_code == 409
        relation = next(item for item in client.get("/api/relations").json() if item["id"] == child_save.json()["relation_id"])
        assert (relation["source_id"], relation["target_id"], relation["relation_type"]) == (parent["id"], child["id"], "develops-into")

        update_run = client.post("/api/agent/runs", json={"prompt": "Elaborate again", "mode": "elaborate", "scope_type": "all", "idea_id": parent["id"]}).json()
        updated = client.post(f"/api/agent/runs/{update_run['id']}/save", json={"action": "update_original"})
        assert updated.status_code == 200
        refreshed_parent = client.get(f"/api/ideas/{parent['id']}").json()
        assert refreshed_parent["title"] == "Refined agent idea"
        assert refreshed_parent["content"] == "Developed content"
        assert refreshed_parent["raw_text"] == "Immutable capture"
        client.delete(f"/api/ideas/{child['id']}", params={"permanent": True})
        client.delete(f"/api/ideas/{parent['id']}", params={"permanent": True})
        client.delete("/api/agent/config")


def test_micro_experiment_crud_fts_repeat_and_round_trip():
    with TestClient(app) as client:
        idea = client.post("/api/ideas", json={"title":"SEED-V calibration study", "content":"Evaluate label smoothing for the new image model", "raw_text":"seed v calibration original"}).json()
        created = client.post("/api/experiments", json={
            "what_tried":"SEED-V label smoothing at 0.1", "result":"Failed to improve validation accuracy", "takeaway":"The baseline remains stronger", "status":"failed",
            "dataset_material":"SEED-V held-out validation split", "metrics":{"accuracy":0.72}, "code_ref":"abc123",
            "idea_links":[{"idea_id":idea["id"],"role":"tests"}], "attachment_ids":[], "metadata":{"lab":"pilot"}
        })
        assert created.status_code == 200, created.text
        experiment = created.json()
        assert experiment["ideas"][0]["role"] == "tests"
        assert experiment["metrics"] == {"accuracy":0.72}
        assert client.get("/api/experiments", params={"q":"SEED-V"}).json()[0]["id"] == experiment["id"]
        assert client.get("/api/experiments", params={"q":"label smoothing", "status":"failed"}).json()[0]["id"] == experiment["id"]
        assert client.get("/api/experiments", params={"idea_id":idea["id"]}).json()[0]["id"] == experiment["id"]
        matches = client.get("/api/experiments/repeat-detection/matches", params={"q":"SEED-V label smoothing","idea_id":idea["id"]}).json()
        assert matches and matches[0]["id"] == experiment["id"]
        dismissed = client.post("/api/research-intelligence/feedback", json={"concept":"experiment-repeat","subject_key":matches[0]["feedback_key"],"action":"dismissed"})
        assert dismissed.status_code == 200
        assert all(item["id"] != experiment["id"] for item in client.get("/api/experiments/repeat-detection/matches", params={"q":"SEED-V label smoothing","idea_id":idea["id"]}).json())
        updated = client.put(f"/api/experiments/{experiment['id']}", json={**{key:experiment[key] for key in ("what_tried","result","takeaway","status","dataset_material","code_ref","metrics","metadata")}, "takeaway":"Keep the established baseline", "idea_links":[{"idea_id":idea["id"],"role":"supports"}], "attachment_ids":[]})
        assert updated.status_code == 200
        assert "established baseline" in client.get("/api/experiments", params={"q":"established baseline"}).json()[0]["takeaway"]
        exported = client.get("/api/export/json").json()
        assert exported["version"] == 4 and exported["experiments"]
        preview = client.post("/api/import/preview", json={"data":exported})
        assert preview.status_code == 200 and preview.json()["counts"]["experiments"] >= 1
        review = client.get("/api/research-intelligence/weekly-review")
        assert review.status_code == 200
        radar = client.get("/api/research-intelligence/gaps")
        assert radar.status_code == 200 and isinstance(radar.json(), list)
        assert client.delete(f"/api/experiments/{experiment['id']}").status_code == 200
        assert client.delete(f"/api/ideas/{idea['id']}", params={"permanent": True}).status_code == 200


def test_research_settings_feedback_and_mcp_experiment_tools():
    with TestClient(app) as client:
        idea = client.post("/api/ideas", json={"title":"Local MCP experiment utility", "content":"Study a new local baseline", "raw_text":"mcp experiment source"}).json()
        saved = client.post("/api/research-intelligence/feedback", json={"concept":"serendipity","subject_key":"pair:900001:900002","action":"dismissed"})
        assert saved.status_code == 200
        updated = client.put("/api/research-intelligence/settings", json={"stalled_days":45,"serendipity_limit":3,"cross_project":False})
        assert updated.status_code == 200 and updated.json()["stalled_days"] == 45
        logged = mcp_log_micro_experiment("Compare a local baseline", f"[[idea:{idea['id']}]]", status="planned")
        assert logged["experiment"]["ideas"][0]["idea_id"] == idea["id"]
        found = mcp_search_micro_experiments(query="local baseline", idea=f"[[idea:{idea['id']}]]")
        assert found["count"] == 1
        client.delete(f"/api/experiments/{logged['experiment']['id']}")
        client.delete(f"/api/ideas/{idea['id']}", params={"permanent": True})
        client.put("/api/research-intelligence/settings", json={"stalled_days":30,"serendipity_limit":4,"cross_project":True})


def test_import_v4_restores_experiment_and_idea_link():
    with TestClient(app) as client:
        package={"version":4,"project_groups":[],"projects":[],"ideas":[{"id":881021,"title":"portable experiment idea","content":"","raw_text":"portable original","status":"promising","tags":[]}],"relations":[],"experiments":[{"id":900101,"what_tried":"Portable test","result":"Result","takeaway":"Takeaway","status":"completed","dataset_material":"sample","metrics":{"score":0.9},"metadata":{"temperature":"cold"},"idea_links":[{"idea_id":881021,"role":"supports"}],"attachments":[]}]}
        result=client.post("/api/import/json",json={"data":package,"duplicate_strategy":"skip","project_strategy":"merge"})
        assert result.status_code==200 and result.json()["experiments_created"]==1
        imported=client.get("/api/experiments",params={"q":"Portable test"}).json()[0]
        assert imported["ideas"][0]["role"]=="supports" and imported["metrics"]=={"score":0.9}
        client.delete(f"/api/experiments/{imported['id']}")
        client.delete(f"/api/ideas/{imported['ideas'][0]['idea_id']}",params={"permanent":True})


def test_anthropic_messages_provider(monkeypatch):
    captured = {}

    class FakeResponse:
        status_code = 200
        text = ""

        @staticmethod
        def json():
            return {"content": [{"type": "tool_use", "name": "submit_research_result", "input": {"answer": "# Claude synthesis\n\nA structured result.", "proposals": []}}]}

    class FakeClient:
        def __init__(self, **_): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *_): pass
        async def post(self, url, headers, json):
            captured.update({"url": url, "headers": headers, "body": json})
            return FakeResponse()

    monkeypatch.setattr("backend.app.main.httpx.AsyncClient", FakeClient)
    with TestClient(app) as client:
        configured = client.post("/api/agent/config", json={
            "provider": "anthropic", "api_key": "anthropic-test-key", "model": "claude-sonnet-5",
            "reasoning_effort": "high", "remember_api_key": False,
        })
        assert configured.status_code == 200
        result = client.post("/api/agent/runs", json={"prompt": "Synthesize", "mode": "synthesize", "scope_type": "all"})
        assert result.status_code == 200
        assert result.json()["provider"] == "anthropic"
        assert captured["url"] == "https://api.anthropic.com/v1/messages"
        assert captured["headers"]["x-api-key"] == "anthropic-test-key"
        assert captured["body"]["thinking"] == {"type": "adaptive"}
        assert captured["body"]["output_config"] == {"effort": "high"}
        assert captured["body"]["tools"][0]["input_schema"]["required"] == ["answer", "proposals"]
        client.delete("/api/agent/config/anthropic")


def test_multiple_agent_profiles_switch_without_retyping_keys():
    with TestClient(app) as client:
        assert client.post("/api/agent/config", json={
            "provider": "openai", "api_key": "openai-test-key", "model": "gpt-5.6-terra",
            "reasoning_effort": "low", "remember_api_key": False,
        }).status_code == 200
        assert client.post("/api/agent/config", json={
            "provider": "local", "api_key": "", "model": "local-research-model",
            "base_url": "http://127.0.0.1:11434/v1", "reasoning_effort": "none",
        }).status_code == 200
        switched = client.post("/api/agent/activate/openai").json()
        assert switched["provider"] == "openai"
        assert switched["configured"] is True
        assert switched["default_model"] == "gpt-5.6-terra"
        profiles = {item["id"]: item for item in switched["providers"]}
        assert profiles["openai"]["configured"] is True
        assert profiles["local"]["configured"] is True
        assert profiles["openai"]["reasoning_effort"] == "low"
        client.delete("/api/agent/config/openai")
        client.delete("/api/agent/config/local")


def test_core_workflow():
    with TestClient(app) as client:
        agent_status = client.get("/api/agent/status").json()
        assert agent_status["configured"] is False
        assert "raw captures" in agent_status["privacy"]
        connected = client.post("/api/agent/config", json={"provider": "deepseek", "api_key": "sk-test-session-key", "model": "deepseek-test"}).json()
        assert connected["configured"] is True
        assert connected["provider"] == "deepseek"
        assert connected["provider_label"] == "DeepSeek"
        assert connected["base_url"] == "https://api.deepseek.com"
        assert connected["web_search_supported"] is True
        assert connected["configuration_source"] == "session"
        assert "sk-test-session-key" not in str(connected)
        disconnected = client.delete("/api/agent/config").json()
        assert disconnected["configured"] is False
        invalid_custom = client.post("/api/agent/config", json={"provider": "custom", "model": "local-model", "base_url": "file:///tmp/model"})
        assert invalid_custom.status_code == 400
        disposable = client.post("/api/ideas", json={"title": "Disposable", "tags": ["only-on-disposable"]}).json()
        assert any(tag["name"] == "only-on-disposable" for tag in client.get("/api/tags").json())
        assert client.delete(f"/api/ideas/{disposable['id']}", params={"permanent": True}).json()["action"] == "deleted"
        assert all(tag["name"] != "only-on-disposable" for tag in client.get("/api/tags").json())
        with db() as connection:
            assert connection.execute("SELECT COUNT(*) count FROM tags WHERE name='only-on-disposable'").fetchone()["count"] == 0
        recyclable = client.post("/api/ideas", json={"title": "Recyclable", "tags": ["recycle-only"]}).json()
        client.delete(f"/api/ideas/{recyclable['id']}")
        recycle_id = next(item["id"] for item in client.get("/api/projects").json() if item["system_key"] == "recycle")
        assert all(tag["name"] != "recycle-only" for tag in client.get("/api/tags").json())
        assert any(tag["name"] == "recycle-only" for tag in client.get("/api/tags", params={"project_id": recycle_id}).json())
        client.delete(f"/api/ideas/{recyclable['id']}")
        one = client.post("/api/ideas", json={"title": "Graph memory", "content": "Use graphs for research notes", "raw_text": "messy original", "tags": ["Graphs", "memory"]})
        assert one.status_code == 201
        idea = one.json()
        two = client.post("/api/ideas", json={"title": "Memory retrieval", "content": "Graph based retrieval", "tags": ["memory"]}).json()
        assert len(client.get("/api/ideas", params={"q": "graph"}).json()) == 2
        assert len(client.get("/api/ideas", params={"tag": "memory"}).json()) == 2
        updated = client.put(f"/api/ideas/{idea['id']}", json={"title": "Graph memory revised", "content": f"Build with Idea #{two['id']}", "status": "promising", "tags": ["memory"]}).json()
        assert updated["raw_text"] == "messy original"
        assert "develops-into" in client.get("/api/relation-types").json()
        relation = client.post("/api/relations", json={"source_id": idea["id"], "target_id": two["id"], "relation_type": "builds-on"})
        assert relation.status_code == 201
        lineage = client.post("/api/relations", json={"source_id": idea["id"], "target_id": two["id"], "relation_type": "develops-into"})
        assert lineage.status_code == 201
        cycle = client.post("/api/relations", json={"source_id": two["id"], "target_id": idea["id"], "relation_type": "develops-into"})
        assert cycle.status_code == 409
        assert "cycle" in cycle.json()["detail"]
        assert client.get(f"/api/ideas/{idea['id']}/suggestions").json()[0]["id"] == two["id"]
        markdown_export = client.get("/api/export/markdown").text
        assert "Graph memory revised" in markdown_export
        assert f"[Memory retrieval](#idea-{two['id']})" in markdown_export
        assert len(client.get("/api/export/json").json()["relations"]) == 2

        group = client.post("/api/project-groups", json={"name": "Active research"}).json()
        project = client.post("/api/projects", json={"name": "Graph studies", "description": "Focused work", "group_id": group["id"]}).json()
        with db() as connection:
            run_id = connection.execute(
                """INSERT INTO agent_runs(model, prompt, mode, scope_type, context_json, response_text, status)
                   VALUES ('test-model', 'Develop this', 'elaborate', 'project', '{}', 'A useful direction', 'completed')"""
            ).lastrowid
            proposal_id = connection.execute(
                """INSERT INTO agent_proposals(run_id, action_type, title, rationale, payload_json)
                   VALUES (?, 'create_idea', 'Agent draft', 'Worth testing', ?)""",
                (run_id, __import__('json').dumps({"idea_title": "Agent-created lead", "content": "A proposed experiment", "status": "exploring", "tags": ["agent"], "project_id": project["id"]})),
            ).lastrowid
        applied = client.post(f"/api/agent/proposals/{proposal_id}", json={"action": "apply"})
        assert applied.status_code == 200
        agent_idea = client.get(f"/api/ideas/{applied.json()['created_idea_id']}").json()
        assert agent_idea["raw_text"].startswith("AI-generated proposal")
        assert agent_idea["project_id"] == project["id"]
        client.delete(f"/api/ideas/{agent_idea['id']}", params={"permanent": True})
        copied = client.post(f"/api/ideas/{idea['id']}/copy", json={"project_id": project["id"]})
        assert copied.status_code == 201
        assert copied.json()["project_id"] == project["id"]
        assert [item["id"] for item in client.get("/api/ideas", params={"group_id": group["id"]}).json()] == [copied.json()["id"]]

        recycled = client.delete(f"/api/ideas/{copied.json()['id']}")
        assert recycled.json()["action"] == "recycled"
        recycle = next(item for item in client.get("/api/projects").json() if item["system_key"] == "recycle")
        assert client.get("/api/ideas", params={"project_id": recycle["id"]}).json()[0]["id"] == copied.json()["id"]
        assert client.delete(f"/api/ideas/{copied.json()['id']}").json()["action"] == "deleted"

        client.post(f"/api/ideas/{idea['id']}/move", json={"project_id": project["id"]})
        client.post(f"/api/ideas/{two['id']}/move", json={"project_id": project["id"]})
        cleared = client.delete(f"/api/projects/{project['id']}/ideas").json()
        assert cleared == {"action": "recycled", "count": 2}
        emptied = client.delete(f"/api/projects/{recycle['id']}/ideas").json()
        assert emptied == {"action": "deleted", "count": 2}

        imported_one = client.post("/api/ideas", json={"title": "Portable one", "content": "First", "raw_text": "original one", "project_id": project["id"], "tags": ["portable"]}).json()
        imported_two = client.post("/api/ideas", json={"title": "Portable two", "content": "Second", "raw_text": "original two", "project_id": project["id"], "tags": ["portable"]}).json()
        client.post("/api/relations", json={"source_id": imported_one["id"], "target_id": imported_two["id"], "relation_type": "related-to"})
        portable = client.get("/api/export/json").json()
        preview = client.post("/api/import/preview", json={"data": portable})
        assert preview.status_code == 200
        assert preview.json()["duplicate_topics"] == 2
        assert "Graph studies" in preview.json()["project_conflicts"]

        skipped = client.post("/api/import/json", json={"data": portable, "duplicate_strategy": "skip", "project_strategy": "merge"})
        assert skipped.status_code == 200
        assert skipped.json()["ideas_skipped"] == 2
        copied_import = client.post("/api/import/json", json={"data": portable, "duplicate_strategy": "copy", "project_strategy": "rename"})
        assert copied_import.status_code == 200
        assert copied_import.json()["ideas_created"] == 2
        assert copied_import.json()["relations_created"] == 1

        groups_before = len(client.get("/api/project-groups").json())
        broken = {"version": 2, "project_groups": [{"id": 99, "name": "Must roll back"}], "projects": [{"id": "bad", "name": "Broken"}], "ideas": [], "relations": []}
        assert client.post("/api/import/json", json={"data": broken}).status_code == 400
        assert len(client.get("/api/project-groups").json()) == groups_before


def test_weekly_review_semantic_discovery_and_codex_checkpoint():
    with TestClient(app) as client:
        project = client.post("/api/projects", json={"name": "Review study", "description": "", "group_id": None, "workspace_mode": "library", "workspace_path": ""}).json()
        parent = client.post("/api/ideas", json={"title": "EEG temporal scale prediction", "content": "EEG neural temporal prediction multiscale signal transition repeated EEG neural temporal prediction", "raw_text": "parent raw", "project_id": project["id"], "tags": ["eeg"]}).json()
        peer = client.post("/api/ideas", json={"title": "Multiscale neural EEG forecast", "content": "EEG neural temporal prediction multiscale signal transition repeated EEG neural temporal prediction", "raw_text": "peer raw", "project_id": project["id"], "tags": ["forecast"]}).json()
        linked = client.post("/api/ideas", json={"title": "Directly linked EEG concept", "content": "EEG neural temporal prediction multiscale signal", "raw_text": "linked raw", "project_id": project["id"]}).json()
        assert client.post("/api/relations", json={"source_id": parent["id"], "target_id": linked["id"], "relation_type": "builds-on", "note": "already related"}).status_code == 201
        rebuilt = client.post("/api/semantic/rebuild")
        assert rebuilt.status_code == 200 and rebuilt.json()["indexed_ideas"] >= 3
        suggestions = client.get(f"/api/ideas/{parent['id']}/semantic-suggestions").json()
        assert any(item["id"] == peer["id"] for item in suggestions)
        assert not any(item["id"] == linked["id"] for item in suggestions)

        checkpoint = client.post("/api/codex/checkpoints", json={"project_id": project["id"], "task_title": "EEG analysis task", "summary": "Distilled an experiment direction.", "proposals": [{"title": "Test cross-scale EEG transition", "content": "Compare forecasting across temporal scales.", "tags": ["eeg", "experiment"], "parent_id": parent["id"]}]}).json()
        assert len(checkpoint["proposals"]) == 1
        review = client.get("/api/review", params={"project_id": project["id"]}).json()
        assert review["summary"]["pending_proposals"] == 1
        proposal_id = checkpoint["proposals"][0]["id"]
        applied = client.post(f"/api/agent/proposals/{proposal_id}", json={"action": "apply"}).json()
        child = client.get(f"/api/ideas/{applied['created_idea_id']}").json()
        assert child["title"] == "Test cross-scale EEG transition"
        assert child["project_id"] == project["id"]
        relation = next(item for item in client.get("/api/relations").json() if item["id"] == applied["created_relation_id"])
        assert (relation["source_id"], relation["target_id"], relation["relation_type"]) == (parent["id"], child["id"], "develops-into")
        checkpoint_mcp = mcp_create_codex_checkpoint("MCP review queue", project["name"], [{"title": "Queued only", "content": "No immediate write"}], "MCP task", "checkpoint-idempotent")
        assert checkpoint_mcp["proposals"][0]["status"] == "pending"


def test_dream_combines_cross_project_sources_with_dreams_tag(monkeypatch):
    captured = {}

    class FakeResponse:
        status_code = 200
        text = ""

        @staticmethod
        def json():
            return {"output": [{"type": "function_call", "name": "submit_research_result", "arguments": json.dumps({"answer": "# Dream synthesis\n\nA bridge between both sources.", "proposals": [{"action": "create_idea", "title": "Cross-project prediction bridge", "rationale": "Combines both source mechanisms.", "idea_id": 0, "project_id": 0, "idea_title": "Cross-project prediction bridge", "content": "Test a unified cross-project prediction mechanism.", "status": "exploring", "tags": ["hypothesis"], "source_id": 0, "target_id": 0, "relation_type": "", "note": ""}]})}]}

    class FakeClient:
        def __init__(self, **_): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *_): pass
        async def post(self, url, headers, json):
            captured.update({"url": url, "body": json})
            return FakeResponse()

    monkeypatch.setattr("backend.app.main.httpx.AsyncClient", FakeClient)
    with TestClient(app) as client:
        first_project = client.post("/api/projects", json={"name": "Dream source A"}).json()
        second_project = client.post("/api/projects", json={"name": "Dream source B"}).json()
        destination = client.post("/api/projects", json={"name": "Dream destination"}).json()
        first = client.post("/api/ideas", json={"title": "Oscillatory prediction", "content": "First source note", "raw_text": "private original one", "project_id": first_project["id"]}).json()
        second = client.post("/api/ideas", json={"title": "Semantic aggregation", "content": "Second source note", "raw_text": "private original two", "project_id": second_project["id"]}).json()
        client.post("/api/agent/config", json={"provider": "deepseek", "api_key": "dream-test-key", "model": "dream-model"})
        response = client.post("/api/dreams", json={"idea_ids": [first["id"], second["id"]], "project_id": destination["id"], "prompt": "Find an unexpected experimental bridge."})
        assert response.status_code == 200
        dream = response.json()
        assert dream["proposals"][0]["payload"]["tags"][0] == "dreams"
        assert dream["proposals"][0]["payload"]["source_ids"] == [first["id"], second["id"]]
        assert "private original" not in captured["body"]["input"]
        applied = client.post(f"/api/agent/proposals/{dream['proposals'][0]['id']}", json={"action": "apply"}).json()
        born = client.get(f"/api/ideas/{applied['created_idea_id']}").json()
        assert born["project_id"] == destination["id"]
        assert born["tags"][0] == "dreams"
        relations = client.get("/api/relations").json()
        born_links = [item for item in relations if item["target_id"] == born["id"] and item["relation_type"] == "inspired-by"]
        assert {item["source_id"] for item in born_links} == {first["id"], second["id"]}
        client.delete("/api/agent/config")


def test_tag_management_and_bulk_updates():
    with TestClient(app) as client:
        first = client.post("/api/ideas", json={"title": "Tag manager one", "tags": ["legacy", "method"]}).json()
        second = client.post("/api/ideas", json={"title": "Tag manager two", "tags": ["legacy", "dataset"]}).json()
        settings = client.put("/api/tags/legacy/settings", json={"group_name": "Vocabulary", "is_hidden": True})
        assert settings.status_code == 200
        assert "legacy" not in {item["name"] for item in client.get("/api/tags").json()}
        managed = {item["name"]: item for item in client.get("/api/tags/manage").json()}
        assert managed["legacy"]["group_name"] == "Vocabulary" and managed["legacy"]["is_hidden"] == 1
        renamed = client.post("/api/tags/legacy/rename", json={"name": "foundation"})
        assert renamed.status_code == 200
        merged = client.post("/api/tags/dataset/merge", json={"target_name": "foundation"})
        assert merged.status_code == 200 and merged.json()["merged"] is True
        bulk = client.post("/api/tags/bulk", json={"idea_ids": [first["id"], second["id"]], "add_tags": ["review"], "remove_tags": ["method"]})
        assert bulk.status_code == 200 and bulk.json()["ideas_updated"] == 2
        first_tags = client.get(f"/api/ideas/{first['id']}").json()["tags"]
        second_tags = client.get(f"/api/ideas/{second['id']}").json()["tags"]
        assert "foundation" in first_tags and "review" in first_tags and "method" not in first_tags
        assert "foundation" in second_tags and "review" in second_tags
        client.put("/api/tags/foundation/settings", json={"group_name": "Vocabulary", "is_hidden": False})
        tag_map = client.get("/api/tags/map").json()
        mapped_nodes = {node["name"]: node for node in tag_map["nodes"]}
        assert mapped_nodes["foundation"]["group_name"] == "Vocabulary"
        assert any(
            {edge["source"], edge["target"]} == {"foundation", "review"} and edge["weight"] == 2
            for edge in tag_map["edges"]
        )


def test_project_workspaces_and_attachments():
    with tempfile.TemporaryDirectory() as directory, TestClient(app) as client:
        root = Path(directory)
        source = root / "notes.md"
        source.write_text("Local evidence for the research idea", encoding="utf-8")

        linked = client.post("/api/projects", json={
            "name": "Linked file study", "workspace_mode": "linked", "workspace_path": str(root),
        })
        assert linked.status_code == 201
        assert linked.json()["workspace_path"] == str(root.resolve())
        idea = client.post("/api/ideas", json={"title": "File-aware idea", "project_id": linked.json()["id"]}).json()
        attachment = client.post(f"/api/ideas/{idea['id']}/attachments", json={"path": str(source), "storage_mode": "linked"})
        assert attachment.status_code == 201
        assert attachment.json()["exists"] is True
        assert attachment.json()["content_hash"]
        assert client.get(f"/api/ideas/{idea['id']}").json()["attachments"][0]["display_name"] == "notes.md"
        assert client.get("/api/attachments", params={"idea_id": idea["id"]}).json()[0]["id"] == attachment.json()["id"]
        with db() as connection:
            context = _agent_context(connection, AgentRunRequest(prompt="Use this file", idea_id=idea["id"], attachment_ids=[attachment.json()["id"]]))
        assert context["files"][0]["path"] == str(source.resolve())
        assert client.delete(f"/api/ideas/{idea['id']}/attachments/{attachment.json()['id']}").status_code == 204
        assert source.exists(), "unlinking must never delete the external file"

        managed = client.post("/api/projects", json={
            "name": "Managed file study", "workspace_mode": "managed", "workspace_path": str(root),
        })
        assert managed.status_code == 201
        workspace = Path(managed.json()["workspace_path"])
        assert (workspace / ".ideaminer" / "project.json").is_file()
        managed_idea = client.post("/api/ideas", json={"title": "Managed-file idea", "project_id": managed.json()["id"]}).json()
        copied = client.post(f"/api/ideas/{managed_idea['id']}/attachments", json={"path": str(source), "storage_mode": "managed"})
        assert copied.status_code == 201
        assert copied.json()["storage_mode"] == "managed"
        assert Path(copied.json()["absolute_path"]).is_file()


def test_figure_metadata_upload_preview_cover_and_export(tmp_path, monkeypatch):
    database_path = tmp_path / "ideaminer.db"
    monkeypatch.setattr(database_module, "DB_PATH", database_path)
    monkeypatch.setattr(main_module, "DB_PATH", database_path)
    png = bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000b49444154789c636000020000050001a5f645400000000049454e44ae426082")
    with TestClient(app) as client:
        idea = client.post("/api/ideas", json={"title": "Figure test", "raw_text": "Verbatim capture"}).json()
        first = client.post(f"/api/ideas/{idea['id']}/figures", files={"file": ("plot.png", png, "image/png")})
        assert first.status_code == 201, first.text
        first_id = first.json()["id"]
        updated = client.patch(f"/api/ideas/{idea['id']}/attachments/{first_id}", json={
            "caption": "Temporal effect plot", "is_cover": True,
        })
        assert updated.status_code == 200
        assert updated.json()["is_cover"] is True

        svg = b'<svg xmlns="http://www.w3.org/2000/svg" width="2" height="1"><rect width="2" height="1" fill="green"/></svg>'
        second = client.post(f"/api/ideas/{idea['id']}/figures", files={"file": ("diagram.svg", svg, "image/svg+xml")})
        assert second.status_code == 201, second.text
        second_id = second.json()["id"]
        assert client.patch(f"/api/ideas/{idea['id']}/attachments/{second_id}", json={"is_cover": True, "caption": "Diagram cover"}).json()["is_cover"] is True
        figures = client.get(f"/api/ideas/{idea['id']}").json()["attachments"]
        assert sum(item["is_cover"] for item in figures) == 1
        assert next(item for item in figures if item["id"] == first_id)["is_cover"] is False

        preview = client.get(f"/api/attachments/{second_id}/content")
        assert preview.status_code == 200
        assert preview.content == svg
        assert preview.headers["content-type"].startswith("image/svg+xml")
        assert preview.headers["x-content-type-options"] == "nosniff"
        assert "sandbox" in preview.headers["content-security-policy"]
        assert client.get("/api/attachments/999999/content").status_code == 404
        export = client.get("/api/export/json").json()
        assert export["ideas"][0]["figure_assets"][0]["content_hash"]
        imported = client.post("/api/import/json", json={
            "data": export, "duplicate_strategy": "copy", "project_strategy": "merge",
        })
        assert imported.status_code == 200, imported.text
        copies = [item for item in client.get("/api/ideas").json() if item["title"] == "Figure test"]
        assert len(copies) == 2
        copied_id = next(item["id"] for item in copies if item["id"] != idea["id"])
        copied_figures = client.get(f"/api/ideas/{copied_id}").json()["attachments"]
        assert len([item for item in copied_figures if item["asset_role"] == "figure"]) == 2
        assert next(item for item in copied_figures if item["is_cover"])["caption"] == "Diagram cover"
        assert client.post(f"/api/ideas/{idea['id']}/figures", files={
            "file": ("bad.svg", b'<svg><script>alert(1)</script></svg>', "image/svg+xml"),
        }).status_code == 400


def test_figure_association_migration_is_idempotent(tmp_path, monkeypatch):
    database_path = tmp_path / "legacy.db"
    monkeypatch.setattr(database_module, "DB_PATH", database_path)
    with sqlite3.connect(database_path) as connection:
        connection.executescript("""
            CREATE TABLE projects (id INTEGER PRIMARY KEY, name TEXT NOT NULL COLLATE NOCASE UNIQUE, description TEXT NOT NULL DEFAULT '', group_id INTEGER, workspace_mode TEXT NOT NULL DEFAULT 'library', workspace_path TEXT NOT NULL DEFAULT '', system_key TEXT UNIQUE, created_at TEXT NOT NULL DEFAULT '');
            CREATE TABLE ideas (id INTEGER PRIMARY KEY, title TEXT NOT NULL, content TEXT NOT NULL DEFAULT '', raw_text TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'seed', project_id INTEGER, created_at TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL DEFAULT '');
            CREATE TABLE attachments (id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL, display_name TEXT NOT NULL, path TEXT NOT NULL, storage_mode TEXT NOT NULL, mime_type TEXT NOT NULL DEFAULT '', size_bytes INTEGER NOT NULL DEFAULT 0, modified_at REAL, content_hash TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL DEFAULT '');
            CREATE TABLE idea_attachments (idea_id INTEGER NOT NULL, attachment_id INTEGER NOT NULL, PRIMARY KEY (idea_id, attachment_id));
            INSERT INTO projects(id, name) VALUES (1, 'Legacy');
            INSERT INTO ideas(id, title, raw_text, project_id) VALUES (1, 'Legacy idea', 'original', 1);
            INSERT INTO attachments(id, project_id, display_name, path, storage_mode) VALUES (1, 1, 'notes.txt', 'notes.txt', 'linked');
            INSERT INTO idea_attachments(idea_id, attachment_id) VALUES (1, 1);
        """)
    database_module.init_db()
    database_module.init_db()
    with sqlite3.connect(database_path) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(idea_attachments)")}
        row = connection.execute("SELECT asset_role, caption, sort_order, is_cover FROM idea_attachments WHERE idea_id=1 AND attachment_id=1").fetchone()
    assert {"asset_role", "caption", "sort_order", "is_cover"}.issubset(columns)
    assert row == ("attachment", "", 0, 0)


def test_codex_mcp_bridge_and_external_revision():
    with TestClient(app) as client:
        before = client.get("/api/library-state").json()["revision"]
        project_result = mcp_create_project(
            name="Codex bridge study",
            description="Created through the local MCP bridge",
            idempotency_key="test-create-project",
        )
        project = project_result["project"]
        repeated_project = mcp_create_project(
            name="Codex bridge study",
            description="Created through the local MCP bridge",
            idempotency_key="test-create-project",
        )
        assert repeated_project["project"]["id"] == project["id"]

        parent_result = mcp_create_idea(
            title="MCP parent",
            content="Working interpretation",
            raw_text="verbatim parent capture",
            project=project["name"],
            tags=["mcp"],
            idempotency_key="test-create-parent",
        )
        parent = parent_result["idea"]
        child_result = mcp_create_idea(
            title="MCP descendant",
            content="A testable child direction",
            raw_text="verbatim child capture",
            parent_reference=f"[[idea:{parent['id']}]]",
            idempotency_key="test-create-child",
        )
        child = child_result["idea"]
        assert child["project_id"] == project["id"]
        assert child_result["relation"]["relation_type"] == "develops-into"
        assert mcp_get_idea(f"[[idea:{child['id']}]]")["idea"]["raw_text"] == "verbatim child capture"
        assert mcp_search_ideas(query="descendant", project=project["name"])["ideas"][0]["id"] == child["id"]

        updated = mcp_update_idea(
            reference=f"[[idea:{parent['id']}]]",
            expected_updated_at=parent["updated_at"],
            content="Revised through Codex",
            status="promising",
            idempotency_key="test-update-parent",
        )["idea"]
        assert updated["raw_text"] == "verbatim parent capture"
        assert updated["content"] == "Revised through Codex"
        try:
            mcp_update_idea(
                reference=f"[[idea:{parent['id']}]]",
                expected_updated_at=parent["updated_at"],
                content="Stale overwrite",
                idempotency_key="test-stale-update",
            )
            assert False, "a stale MCP update must be rejected"
        except ValueError as error:
            assert "changed after it was read" in str(error)

        random_chat = next(item for item in client.get("/api/projects").json() if item["system_key"] == "random_chat")
        moved = mcp_move_idea(f"[[idea:{child['id']}]]", random_chat["name"], "test-move-child")["idea"]
        assert moved["project_id"] == random_chat["id"]
        copied = mcp_copy_idea(f"[[idea:{child['id']}]]", project["name"], "test-copy-child")["idea"]
        assert copied["project_id"] == project["id"]

        after = client.get("/api/library-state").json()["revision"]
        assert after > before
        client.delete(f"/api/ideas/{copied['id']}", params={"permanent": True})
        client.delete(f"/api/ideas/{child['id']}", params={"permanent": True})
        client.delete(f"/api/ideas/{parent['id']}", params={"permanent": True})


class FakeSFTP:
    def __init__(self):
        self.directories = {"/", "/home", "/home/test", "/sync"}
        self.files = {}
        self.fail_upload = False

    def normalize(self, path):
        return "/home/test" if path == "." else path

    def lstat(self, path):
        if path in self.directories:
            return SimpleNamespace(st_mode=stat.S_IFDIR, st_size=0)
        if path in self.files:
            return SimpleNamespace(st_mode=stat.S_IFREG, st_size=len(self.files[path]))
        raise FileNotFoundError(2, "No such file", path)

    def listdir_attr(self, directory):
        entries = []
        prefix = directory.rstrip("/") + "/"
        direct_dirs = {path[len(prefix):].split("/")[0] for path in self.directories if path.startswith(prefix) and path != directory}
        direct_files = {path[len(prefix):] for path in self.files if path.startswith(prefix) and "/" not in path[len(prefix):]}
        for name in direct_dirs:
            entries.append(SimpleNamespace(filename=name, st_mode=stat.S_IFDIR, st_size=0))
        for name in direct_files:
            entries.append(SimpleNamespace(filename=name, st_mode=stat.S_IFREG, st_size=len(self.files[prefix + name])))
        return entries

    def open(self, path, mode="rb"):
        return BytesIO(self.files[path])

    def mkdir(self, path, _mode=0o755):
        self.directories.add(path)

    def put(self, local_path, remote_path):
        self.files[remote_path] = Path(local_path).read_bytes()[:3] if self.fail_upload else Path(local_path).read_bytes()
        if self.fail_upload:
            raise OSError("simulated interrupted transfer")

    def get(self, remote_path, local_path):
        Path(local_path).write_bytes(self.files[remote_path])

    def posix_rename(self, old, new):
        self.files[new] = self.files.pop(old)

    def rename(self, old, new):
        self.files[new] = self.files.pop(old)

    def remove(self, path):
        if path not in self.files:
            raise FileNotFoundError(2, "No such file", path)
        del self.files[path]

    def close(self):
        pass


class FakeSSHClient:
    def __init__(self, sftp):
        self.sftp = sftp

    def close(self):
        pass


def test_remote_sync_push_pull_and_preserves_destination_only(monkeypatch, tmp_path):
    workspace = tmp_path / "project folder"
    workspace.mkdir()
    (workspace / "new file.txt").write_text("new payload", encoding="utf-8")
    (workspace / "same.txt").write_text("unchanged", encoding="utf-8")
    (workspace / "conflict.txt").write_text("local edit", encoding="utf-8")
    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    try:
        (workspace / "outside-link.txt").symlink_to(outside)
    except OSError:
        pass

    fake_sftp = FakeSFTP()
    remote_project = "/sync/Research project"
    fake_sftp.directories.update({remote_project})
    fake_sftp.files.update({
        f"{remote_project}/same.txt": b"unchanged",
        f"{remote_project}/conflict.txt": b"remote edit",
        f"{remote_project}/remote only.txt": b"keep me",
    })
    monkeypatch.setattr(remote_sync_module, "_open_sftp", lambda _machine: (FakeSSHClient(fake_sftp), fake_sftp))
    with TestClient(app) as client:
        project = client.post("/api/projects", json={"name": "Research project", "workspace_mode": "linked", "workspace_path": str(workspace)}).json()
        machine = client.post("/api/remotes", json={"name": "Ubuntu test", "host": "ubuntu", "username": "test", "root_path": "/sync"}).json()
        assert client.post(f"/api/remotes/{machine['id']}/check").json()["status"] == "connected"
        preview = client.post("/api/project-sync/preview", json={"machine_id": machine["id"], "project_id": project["id"], "direction": "push"}).json()
        statuses = {row["path"]: row["status"] for row in preview["items"]}
        assert statuses["new file.txt"] == "new"
        assert statuses["same.txt"] == "same"
        assert statuses["conflict.txt"] == "conflict"
        assert statuses["remote only.txt"] == "destination_only"
        assert "outside-link.txt" not in statuses

        done = client.post("/api/project-sync/execute", json={"preview_id": preview["preview_id"], "selected_paths": ["new file.txt"], "delete_paths": []})
        assert done.status_code == 200, done.text
        assert fake_sftp.files[f"{remote_project}/new file.txt"] == b"new payload"
        assert fake_sftp.files[f"{remote_project}/conflict.txt"] == b"remote edit"
        assert fake_sftp.files[f"{remote_project}/remote only.txt"] == b"keep me"

        deletion_preview = client.post("/api/project-sync/preview", json={"machine_id": machine["id"], "project_id": project["id"], "direction": "push"}).json()
        assert client.post("/api/project-sync/execute", json={"preview_id": deletion_preview["preview_id"], "selected_paths": [], "delete_paths": ["remote only.txt"]}).status_code == 200
        assert f"{remote_project}/remote only.txt" not in fake_sftp.files

        conflict_preview = client.post("/api/project-sync/preview", json={"machine_id": machine["id"], "project_id": project["id"], "direction": "push"}).json()
        overwrite = client.post("/api/project-sync/execute", json={"preview_id": conflict_preview["preview_id"], "selected_paths": ["conflict.txt"], "delete_paths": []})
        assert overwrite.status_code == 200, overwrite.text
        assert fake_sftp.files[f"{remote_project}/conflict.txt"] == b"local edit"

        pull_source = f"{remote_project}/pull file.txt"
        fake_sftp.files[pull_source] = b"from ubuntu"
        pull_preview = client.post("/api/project-sync/preview", json={"machine_id": machine["id"], "project_id": project["id"], "direction": "pull"}).json()
        pull_rows = {row["path"]: row["status"] for row in pull_preview["items"]}
        assert pull_rows["pull file.txt"] == "new"
        pulled = client.post("/api/project-sync/execute", json={"preview_id": pull_preview["preview_id"], "selected_paths": ["pull file.txt"], "delete_paths": []})
        assert pulled.status_code == 200, pulled.text
        assert (workspace / "pull file.txt").read_bytes() == b"from ubuntu"
        assert client.post("/api/project-sync/execute", json={"preview_id": pull_preview["preview_id"], "selected_paths": ["../escape"], "delete_paths": []}).status_code == 410


def test_remote_sync_interrupted_transfer_and_host_key_status(monkeypatch, tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "data file.txt").write_text("full content", encoding="utf-8")
    fake_sftp = FakeSFTP()
    fake_sftp.fail_upload = True
    monkeypatch.setattr(remote_sync_module, "_open_sftp", lambda _machine: (FakeSSHClient(fake_sftp), fake_sftp))
    with TestClient(app) as client:
        project = client.post("/api/projects", json={"name": "Interrupted project", "workspace_mode": "linked", "workspace_path": str(workspace)}).json()
        machine = client.post("/api/remotes", json={"name": "Ubuntu interrupted", "host": "ubuntu", "root_path": "/sync"}).json()
        preview = client.post("/api/project-sync/preview", json={"machine_id": machine["id"], "project_id": project["id"], "direction": "push"}).json()
        result = client.post("/api/project-sync/execute", json={"preview_id": preview["preview_id"], "selected_paths": ["data file.txt"], "delete_paths": []})
        assert result.status_code == 502
        assert "Sync stopped after 0 files" in result.json()["detail"]
        assert not any(path.endswith(".tmp") for path in fake_sftp.files)
        assert f"/sync/Interrupted project/data file.txt" not in fake_sftp.files

        def untrusted(_machine):
            raise remote_sync_module.paramiko.SSHException("Server not found in known_hosts")
        monkeypatch.setattr(remote_sync_module, "_open_sftp", untrusted)
        status = client.post(f"/api/remotes/{machine['id']}/check").json()
        assert status["status"] == "host_key_attention", status
        assert client.post("/api/project-sync/execute", json={"preview_id": preview["preview_id"], "selected_paths": ["../escape"], "delete_paths": []}).status_code == 400

        monkeypatch.setattr(remote_sync_module, "_open_sftp", lambda _machine: (_ for _ in ()).throw(OSError("connection refused")))
        assert client.post(f"/api/remotes/{machine['id']}/check").json()["status"] == "offline"


def test_remote_sync_rejects_unknown_host_key(monkeypatch, tmp_path):
    class RejectingSSHClient:
        policy = None

        def load_system_host_keys(self): pass
        def load_host_keys(self, _path): pass
        def set_missing_host_key_policy(self, policy): self.policy = policy
        def connect(self, **_options):
            assert isinstance(self.policy, remote_sync_module.paramiko.RejectPolicy)
            raise remote_sync_module.paramiko.SSHException("Server not found in known_hosts")
        def close(self): pass

    monkeypatch.setattr(remote_sync_module, "_ssh_options", lambda _host: {})
    monkeypatch.setattr(remote_sync_module.paramiko, "SSHClient", RejectingSSHClient)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    with TestClient(app) as client:
        machine = client.post("/api/remotes", json={"name": "Unknown key", "host": "not-trusted", "root_path": "/sync"}).json()
        status = client.post(f"/api/remotes/{machine['id']}/check").json()
        assert status["status"] == "host_key_attention", status


def test_remote_sync_dependency_missing_does_not_disable_library(monkeypatch):
    monkeypatch.setattr(remote_sync_module.paramiko, "_ideaminer_missing", True, raising=False)
    with TestClient(app) as client:
        machine = client.post("/api/remotes", json={"name": "No SSH dependency", "host": "ubuntu", "root_path": "/sync"}).json()
        status = client.post(f"/api/remotes/{machine['id']}/check")
        assert status.status_code == 503
        assert "Paramiko is installed" in status.json()["detail"]


def teardown_module():
    try:
        os.unlink(handle.name)
    except PermissionError:
        pass
