"""Integration tests for the Pixel-Art AI Council Office HTTP & WebSocket backend."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from peer_consult.config import load_config
from peer_consult.office_server import build_task_board, create_office_app, map_agent_states
from peer_consult.state import CouncilStore

FAKE = str(Path(__file__).with_name("fake_cli.py"))
PY = sys.executable


def test_office_retry_replaces_old_failure_and_preserves_completed_peers():
    cfg = load_config()
    failed = {"stage": "proposal", "agent": "agy", "status": "error", "error": {"message": "old missing executable"}}
    success = {"stage": "proposal", "agent": "claude", "status": "ok", "output": {"summary": "saved"}}
    run = {"status": "PROPOSING", "current_stage": "proposal", "mode": "discuss"}
    events = [{"stage": "proposal", "agent": "agy", "event_type": "proposal.agent_failed"},
              {"stage": "proposal", "agent": "agy", "event_type": "proposal.agent_started"}]
    agents = map_agent_states(cfg, run, [success, failed], events)
    assert agents["agy"]["animation"] == "thinking"
    assert "old missing" not in agents["agy"]["current_task"]
    assert agents["claude"]["animation"] == "waiting"
    board = build_task_board(run, [success, failed], events)
    retry = next(i for i in board[0]["items"] if i["provider"] == "agy")
    assert retry["status"] == "IN_PROGRESS"
    assert retry["error"] is None
    events.append({"stage": "proposal", "agent": "agy", "event_type": "proposal.agent_failed"})
    run["status"] = "FAILED"
    agents = map_agent_states(cfg, run, [success, failed], events)
    assert agents["agy"]["animation"] == "failed"
    assert agents["agy"]["room"] == "review_room"
    assert agents["agy"]["seat_id"] == "doubts-agy"
    assert agents["claude"]["animation"] == "waiting"
    assert agents["claude"]["status_badge"] == "READY"


def test_office_cancelled_run_is_paused_instead_of_failed():
    agents = map_agent_states(load_config(), {"status": "CANCELLED", "current_stage": "proposal"}, [], [])
    assert all(agent["animation"] == "waiting" and agent["status_badge"] == "PAUSED" for agent in agents.values())


def _init_git_repo(repo_dir: Path) -> None:
    repo_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init"], cwd=str(repo_dir), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(repo_dir), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Office Tester"], cwd=str(repo_dir), check=True, capture_output=True)
    (repo_dir / "app.py").write_text("def compute() -> int:\n    return 1\n", encoding="utf-8")
    (repo_dir / "test_app.py").write_text(
        "from app import compute\n\ndef test_compute():\n    assert compute() == 42\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "app.py", "test_app.py"], cwd=str(repo_dir), check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=str(repo_dir), check=True, capture_output=True)


@pytest.fixture
def office_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    record_dir = tmp_path / "records"
    record_dir.mkdir()
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    worktree_root = tmp_path / "worktrees"
    repo_dir = tmp_path / "repo"
    _init_git_repo(repo_dir)

    py_escaped = PY.replace("\\", "\\\\")
    fake_escaped = FAKE.replace("\\", "\\\\")
    wt_escaped = str(worktree_root).replace("\\", "\\\\")

    cfg_path = home_dir / "config.toml"
    cfg_path.write_text(
        f"""
[limits]
timeout_seconds = 20
max_request_chars = 20000
max_stdout_bytes = 2000000
max_stderr_bytes = 200000
transient_retries = 0
retry_backoff_seconds = 0.05
heartbeat_seconds = 60

[budget]
max_consultations_per_task = 5

[codex]
command = ["{py_escaped}", "{fake_escaped}", "codex"]
model = "gpt-6-astra"
effort = "max"

[claude]
command = ["{py_escaped}", "{fake_escaped}", "claude"]
model = "claude-fable-5-1"
effort = "max"
auth = "subscription"

[agy]
command = ["{py_escaped}", "{fake_escaped}", "agy"]
model = "gemini-4-argon"
effort = "high"

[council]
chair = "claude"
quorum = 3
max_concurrency = 3
stage_timeout_seconds = 20
anonymize_proposals = true

[execute]
default_writer = "claude"
max_repairs = 2
require_approval = true
worktree_base_dir = "{wt_escaped}"

[office]
host = "127.0.0.1"
port = 4173
""",
        encoding="utf-8",
    )

    monkeypatch.setenv("PEER_CONSULT_HOME", str(home_dir))
    monkeypatch.setenv("PEER_CONSULT_CONFIG", str(cfg_path))
    monkeypatch.setenv("FAKE_RECORD_DIR", str(record_dir))
    monkeypatch.setenv("FAKE_MODE", "ok")
    monkeypatch.setenv("FAKE_COUNCIL_BEHAVIOR", "ok")
    monkeypatch.delenv("PEER_CONSULT_DEPTH", raising=False)

    cfg = load_config(cfg_path)
    store = CouncilStore()
    token = "test-office-secret-token-123456"
    app = create_office_app(cfg, store, token=token)
    return {
        "app": app,
        "token": token,
        "repo": repo_dir,
        "store": store,
        "cfg": cfg,
    }


def test_office_auth_and_health(office_env):
    client = TestClient(office_env["app"])

    # Health is public
    r_health = client.get("/api/health")
    assert r_health.status_code == 200
    assert r_health.json()["ok"] is True

    # /api/state without token -> 401
    r_unauth = client.get("/api/state")
    assert r_unauth.status_code == 401

    # /api/state with wrong token -> 401
    r_bad = client.get("/api/state?token=wrong-token")
    assert r_bad.status_code == 401

    # /api/state with valid Bearer header -> 200
    r_ok = client.get("/api/state", headers={"Authorization": f"Bearer {office_env['token']}"})
    assert r_ok.status_code == 200
    snap = r_ok.json()
    assert snap["demo_mode"] is False
    assert set(snap["agents"].keys()) == {"claude", "codex", "agy"}
    for ag in snap["agents"].values():
        assert ag["animation"] == "idle"
        assert ag["room"] == "desks"


def test_office_model_settings_are_authenticated_persisted_and_do_not_launch_runs(office_env):
    client = TestClient(office_env["app"])
    headers = {"Authorization": f"Bearer {office_env['token']}"}
    assert client.get("/api/settings/models").status_code == 401
    assert client.post("/api/settings/models", json={"models": {"claude": "claude-opus-5-5"}}).status_code == 401
    before = office_env["cfg"]["agy"]["command"]
    response = client.post("/api/settings/models", headers=headers, json={"models": {"claude": "claude-opus-5-5", "agy": "gemini-3.8-flash"}})
    assert response.status_code == 200, response.text
    settings = response.json()
    assert next(p for p in settings["providers"] if p["id"] == "claude")["model"] == "claude-opus-5-5"
    persisted = load_config(Path(office_env["cfg"]["_path"]))
    assert persisted["claude"]["model"] == "claude-opus-5-5"
    assert persisted["agy"]["command"] == before
    assert persisted["agy"]["model"] == "gemini-3.8-flash"
    assert office_env["store"].list_runs() == []
    snapshot = client.get("/api/state", headers=headers).json()
    assert snapshot["agents"]["claude"]["model"] == "claude-opus-5-5"
    invalid = client.post("/api/settings/models", headers=headers, json={"models": {"claude": "x; bad"}})
    assert invalid.status_code == 400
    assert load_config(Path(office_env["cfg"]["_path"]))["claude"]["model"] == "claude-opus-5-5"
    unknown = client.post("/api/settings/models", headers=headers, json={"models": {"other": "gpt-6-astra"}})
    assert unknown.status_code == 400


def test_office_model_changes_reject_active_runs(office_env):
    store = office_env["store"]
    store.create_run(task_id="model-settings-test", mode="discuss", question="test", caller="user", chair="claude", writer=None,
                     base_dir=office_env["repo"], cfg=office_env["cfg"], packet={}, context_meta={})
    client = TestClient(office_env["app"])
    headers = {"Authorization": f"Bearer {office_env['token']}"}
    assert client.get("/api/settings/models", headers=headers).json()["busy"] is True
    response = client.post("/api/settings/models", headers=headers, json={"models": {"claude": "claude-opus-5-5"}})
    assert response.status_code == 409
    assert "Pause" in response.json()["message"]


def test_office_websocket_rejects_unauthenticated_and_streams_snapshot(office_env):
    client = TestClient(office_env["app"])

    # Unauthenticated WebSocket connection must be closed with 1008
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect("/ws/events?token=invalid"):
            pass
    assert exc_info.value.code == 1008

    # Authenticated WebSocket receives initial snapshot and responds to ping
    with client.websocket_connect(f"/ws/events?token={office_env['token']}") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "snapshot"
        assert set(msg["data"]["agents"].keys()) == {"claude", "codex", "agy"}

        ws.send_json({"action": "ping"})
        pong = ws.receive_json()
        assert pong["type"] == "pong"


def test_office_plan_approval_and_execution_workflow(office_env):
    client = TestClient(office_env["app"])
    headers = {"Authorization": f"Bearer {office_env['token']}"}

    # 1. Start a council plan run via REST API (wait=True for deterministic test)
    r_start = client.post(
        "/api/runs/start",
        headers=headers,
        json={
            "mode": "plan",
            "question": "Implement compute() == 42 in app.py",
            "chair": "claude",
            "cwd": str(office_env["repo"]),
            "files": ["app.py"],
            "wait": True,
        },
    )
    assert r_start.status_code == 200, r_start.text
    start_data = r_start.json()
    assert start_data["ok"] is True
    run_id = start_data["run_id"]
    snap = start_data["snapshot"]
    assert snap["run"]["state"] == "AWAITING_APPROVAL"
    assert snap["run"]["approved"] is False
    assert len(snap["meeting"]["proposals"]) == 3
    assert len(snap["meeting"]["critiques"]) == 3
    assert snap["meeting"]["synthesis"]["recommended_writer"] == "claude"

    # All 3 agents should be waiting in the meeting_room during AWAITING_APPROVAL
    for ag in snap["agents"].values():
        assert ag["room"] == "meeting_room"
        assert ag["animation"] == "waiting"

    # 2. Approve and execute the plan via /api/runs/{run_id}/approve
    r_appr = client.post(
        f"/api/runs/{run_id}/approve",
        headers=headers,
        json={
            "writer": "claude",
            "create_pr": True,
            "wait": True,
        },
    )
    assert r_appr.status_code == 200, r_appr.text
    appr_data = r_appr.json()
    assert appr_data["ok"] is True
    assert appr_data["approved"] is True
    exec_snap = appr_data["snapshot"]
    assert exec_snap["run"]["state"] == "COMPLETED"
    assert exec_snap["execution"]["test_passed"] is True
    assert "def compute() -> int:" in exec_snap["execution"]["git_diff"]
    assert len(exec_snap["execution"]["peer_reviews"]) == 2

    # 3. Verify event replay via WebSocket
    with client.websocket_connect(f"/ws/events?token={office_env['token']}&run_id={run_id}") as ws:
        init_msg = ws.receive_json()
        assert init_msg["type"] == "snapshot"
        assert init_msg["data"]["active_run_id"] == run_id

        ws.send_json({"action": "replay", "run_id": run_id})
        rep_msg = ws.receive_json()
        assert rep_msg["type"] == "replay"
        assert rep_msg["run_id"] == run_id
        assert len(rep_msg["events"]) >= 10
