"""Unit, integration, end-to-end, and failure-injection tests for the 3-Agent Council."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from peer_consult.cli import main
from peer_consult.core import EXIT_OK, EXIT_PROVIDER, EXIT_REFUSED, EXIT_TIMEOUT
from peer_consult.sandbox import SandboxError, WorktreeSandbox
from peer_consult.schemas import (
    CouncilEvent,
    CritiqueOutput,
    PeerReviewOutput,
    ProposalOutput,
    SynthesisOutput,
    WriterOutput,
    strict_json_schema,
)
from peer_consult.state import CouncilStore

FAKE = str(Path(__file__).with_name("fake_cli.py"))
PY = sys.executable


def _init_git_repo(repo_dir: Path) -> None:
    """Create a real git repository with app.py and test_app.py for worktree sandbox tests."""
    repo_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init"], cwd=str(repo_dir), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(repo_dir), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Council Tester"], cwd=str(repo_dir), check=True, capture_output=True)

    (repo_dir / "app.py").write_text("def compute() -> int:\n    return 1\n", encoding="utf-8")
    (repo_dir / "test_app.py").write_text(
        "from app import compute\n\ndef test_compute():\n    assert compute() == 42\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "app.py", "test_app.py"], cwd=str(repo_dir), check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=str(repo_dir), check=True, capture_output=True)


@pytest.fixture
def council_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
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
    for k in (
        "FAKE_MODE_CODEX",
        "FAKE_MODE_CLAUDE",
        "FAKE_MODE_AGY",
        "FAKE_MODE_PROPOSAL_CODEX",
        "FAKE_MODE_CRITIQUE_AGY",
        "FAKE_MODE_SYNTHESIS_CLAUDE",
    ):
        monkeypatch.delenv(k, raising=False)

    def read_records() -> list[dict]:
        return [
            json.loads(p.read_text(encoding="utf-8"))
            for p in sorted(record_dir.glob("*.json"))
        ]

    return {
        "tmp": tmp_path,
        "home": home_dir,
        "cfg_path": cfg_path,
        "repo": repo_dir,
        "state_dir": home_dir / "state",
        "worktree_root": worktree_root,
        "record_dir": record_dir,
        "records": read_records,
    }


def _run_cli(args: list[str], capsys) -> tuple[int, dict, str]:
    rc = main(args)
    cap = capsys.readouterr()
    out = cap.out.strip()
    data = json.loads(out) if out.startswith("{") else {}
    return rc, data, cap.err


# ---------------------------------------------------------------------------
# 1. Schema & strict_json_schema tests
# ---------------------------------------------------------------------------

def test_council_schemas_and_strict_json_schema():
    for model_cls in (
        ProposalOutput,
        CritiqueOutput,
        SynthesisOutput,
        WriterOutput,
        PeerReviewOutput,
        CouncilEvent,
    ):
        schema = strict_json_schema(model_cls)
        assert "$defs" not in json.dumps(schema)
        assert "$ref" not in json.dumps(schema)
        assert schema.get("additionalProperties") is False
        props = schema.get("properties", {})
        assert set(schema.get("required", [])) == set(props.keys())


# ---------------------------------------------------------------------------
# 2. Council Discuss & Plan end-to-end tests
# ---------------------------------------------------------------------------

def test_council_discuss_end_to_end(council_env, capsys):
    rc, data, err = _run_cli(
        [
            "council",
            "discuss",
            "--chair",
            "claude",
            "--base-dir",
            str(council_env["repo"]),
            "--file",
            "app.py",
            "--question",
            "How should we update compute() in app.py?",
        ],
        capsys,
    )
    assert rc == 0, err
    assert data["mode"] == "discuss"
    assert data["run_status"] == "COMPLETED"
    assert data["chair"] == "claude"
    assert set(data["proposals"].keys()) == {"claude", "codex", "agy"}
    assert set(data["critiques"].keys()) == {"claude", "codex", "agy"}
    assert set(data["anonymization_map"].keys()) == {"Proposal A", "Proposal B", "Proposal C"}
    assert set(data["anonymization_map"].values()) == {"claude", "codex", "agy"}

    synthesis = data["synthesis"]
    assert synthesis["recommended_writer"] == "claude"
    assert synthesis["authorized_files"] == ["app.py"]
    assert len(synthesis["unresolved_disagreements"]) == 1
    assert len(synthesis["evidence_ledger"]) >= 1
    assert len(synthesis["assumptions_ledger"]) >= 1

    report_path = Path(data["report_markdown_path"])
    assert report_path.exists()
    md = report_path.read_text(encoding="utf-8")
    assert "Council" in md
    assert "Unresolved Disagreements" in md
    assert "Evidence Ledger" in md

    # Verify 3 proposals + 3 critiques + 1 synthesis = 7 read-only invocations
    recs = council_env["records"]()
    assert len(recs) == 7
    assert sum(1 for r in recs if r["schema_kind"] == "proposal") == 3
    assert sum(1 for r in recs if r["schema_kind"] == "critique") == 3
    assert sum(1 for r in recs if r["schema_kind"] == "synthesis") == 1


def test_council_synthesis_schema_repair_once(council_env, capsys, monkeypatch):
    """A chair answer that misses a required field gets exactly one bounded repair re-ask."""
    monkeypatch.setenv("FAKE_COUNCIL_BEHAVIOR", "schema_missing_once")
    rc, data, err = _run_cli(
        ["council", "discuss", "--base-dir", str(council_env["repo"]), "--question", "How should compute() change?"],
        capsys,
    )
    assert rc == 0, err
    assert data["run_status"] == "COMPLETED"
    assert data["synthesis"]["steps"][0]["title"]
    recs = council_env["records"]()
    assert sum(1 for r in recs if r["schema_kind"] == "synthesis") == 2


def test_council_synthesis_schema_failure_is_not_silently_accepted(council_env, capsys, monkeypatch):
    monkeypatch.setenv("FAKE_COUNCIL_BEHAVIOR", "schema_missing_always")
    rc, data, err = _run_cli(
        ["council", "discuss", "--base-dir", str(council_env["repo"]), "--question", "How should compute() change?"],
        capsys,
    )
    assert rc != 0
    assert data["run_status"] == "FAILED"
    assert not data.get("synthesis")
    recs = council_env["records"]()
    assert sum(1 for r in recs if r["schema_kind"] == "synthesis") == 2  # original + one repair, then stop


def test_council_plan_requires_approval_gate(council_env, capsys):
    rc, plan_data, err = _run_cli(
        [
            "council",
            "plan",
            "--chair",
            "codex",
            "--base-dir",
            str(council_env["repo"]),
            "--question",
            "Plan update to compute() in app.py",
        ],
        capsys,
    )
    assert rc == 0, err
    assert plan_data["run_status"] == "AWAITING_APPROVAL"
    assert plan_data["chair"] == "codex"
    assert "approval_token" in plan_data
    run_id = plan_data["run_id"]

    # Attempting to execute without --approve or --approval-token MUST fail closed
    rc2, exec_err_data, err2 = _run_cli(
        ["council", "execute", "--run-id", run_id],
        capsys,
    )
    assert rc2 == EXIT_REFUSED
    assert exec_err_data["error"]["kind"] == "approval_required"


def test_approval_token_is_bound_to_the_plan_it_approves(council_env, capsys):
    from peer_consult.state import CouncilStore

    rc, plan_data, err = _run_cli(
        ["council", "plan", "--base-dir", str(council_env["repo"]), "--question", "Plan update to compute()"],
        capsys,
    )
    assert rc == 0, err
    run_id, token = plan_data["run_id"], plan_data["approval_token"]
    assert len(token.rsplit("-", 1)[1]) == 32  # 128-bit random suffix

    store = CouncilStore()
    tampered = dict(store.get_run(run_id)["synthesis"])
    tampered["authorized_files"] = ["app.py", "deploy.sh"]
    store.update_run(run_id, synthesis=tampered)
    assert store.verify_approval(run_id, token=token) is False  # plan changed after the token was issued
    assert store.verify_approval(run_id, token="appr-forged") is False
    assert store.get_run(run_id)["approved_at"] is None

    original = plan_data["synthesis"]
    store.update_run(run_id, synthesis=original)
    assert store.verify_approval(run_id, token=token) is True


def test_approval_key_is_created_once_with_owner_only_permissions(council_env):
    from peer_consult.state import CouncilStore

    store = CouncilStore()
    k1 = store._secret_key()
    k2 = CouncilStore()._secret_key()
    assert k1 == k2 and len(k1) == 32
    key_file = store.state_root / "approval.key"
    if os.name != "nt":
        assert (key_file.stat().st_mode & 0o777) == 0o600


# ---------------------------------------------------------------------------
# 3. Council Execute end-to-end (Worktree, Single Writer, Tests, Peer Reviews)
# ---------------------------------------------------------------------------

def test_council_execute_end_to_end_with_pr_draft(council_env, capsys):
    rc, plan_data, err = _run_cli(
        [
            "council",
            "plan",
            "--base-dir",
            str(council_env["repo"]),
            "--question",
            "Implement compute() == 42 in app.py",
        ],
        capsys,
    )
    assert rc == 0, err
    run_id = plan_data["run_id"]

    rc_exec, exec_data, err_exec = _run_cli(
        [
            "council",
            "execute",
            "--run-id",
            run_id,
            "--writer",
            "claude",
            "--approve",
            "--create-pr",
        ],
        capsys,
    )
    assert rc_exec == 0, err_exec
    assert exec_data["run_status"] == "COMPLETED"
    assert exec_data["writer"] == "claude"
    assert exec_data["execution"]["branch"] == f"council/{run_id}"
    assert set(exec_data["execution"]["peer_review_verdicts"].keys()) == {"codex", "agy"}
    for v in exec_data["execution"]["peer_review_verdicts"].values():
        assert v == "approve"

    wt_path = Path(exec_data["execution"]["worktree_path"])
    assert wt_path.exists()
    assert (wt_path / "app.py").read_text(encoding="utf-8") == "def compute() -> int:\n    return 42\n"
    # Main repo must remain untouched (no automatic merge!)
    assert (council_env["repo"] / "app.py").read_text(encoding="utf-8") == "def compute() -> int:\n    return 1\n"

    pr_draft = Path(exec_data["execution"]["pr_draft_path"])
    assert pr_draft.exists()
    assert f"council/{run_id}" in pr_draft.read_text(encoding="utf-8")


def test_council_execute_with_codex_writer_structured_patches(council_env, capsys):
    """Verify Codex writer (read-only patch mode on Windows) applies structured patches cleanly."""
    rc, plan_data, _ = _run_cli(
        [
            "council",
            "plan",
            "--base-dir",
            str(council_env["repo"]),
            "--question",
            "Implement compute() == 42 using codex writer",
        ],
        capsys,
    )
    assert rc == 0
    run_id = plan_data["run_id"]

    rc_exec, exec_data, err_exec = _run_cli(
        [
            "council",
            "execute",
            "--run-id",
            run_id,
            "--writer",
            "codex",
            "--approval-token",
            plan_data["approval_token"],
        ],
        capsys,
    )
    assert rc_exec == 0, err_exec
    assert exec_data["run_status"] == "COMPLETED"
    assert exec_data["writer"] == "codex"
    assert set(exec_data["execution"]["peer_review_verdicts"].keys()) == {"claude", "agy"}


# ---------------------------------------------------------------------------
# 4. All 12 Failure-Injection Scenarios (Phase 6)
# ---------------------------------------------------------------------------

def test_failure_1_unavailable_provider(council_env, capsys):
    py_escaped = PY.replace("\\", "\\\\")
    fake_escaped = FAKE.replace("\\", "\\\\")
    txt = council_env["cfg_path"].read_text(encoding="utf-8").replace(
        f'command = ["{py_escaped}", "{fake_escaped}", "agy"]',
        'command = ["/nonexistent/binary/agy-missing"]',
    )
    council_env["cfg_path"].write_text(txt, encoding="utf-8")
    rc, data, _ = _run_cli(
        ["council", "discuss", "--base-dir", str(council_env["repo"]), "--question", "test unavailable"],
        capsys,
    )
    assert rc == EXIT_PROVIDER
    assert data["run_status"] == "FAILED"
    assert data["error"]["kind"] == "missing_executable"


def test_failure_2_authentication_failure(council_env, monkeypatch, capsys):
    monkeypatch.setenv("FAKE_MODE_CODEX", "auth")
    rc, data, _ = _run_cli(
        ["council", "discuss", "--base-dir", str(council_env["repo"]), "--question", "test auth error"],
        capsys,
    )
    assert rc == EXIT_PROVIDER
    assert data["error"]["kind"] == "auth_error"


def test_failure_3_quota_exhaustion(council_env, monkeypatch, capsys):
    monkeypatch.setenv("FAKE_MODE_CLAUDE", "quota")
    rc, data, _ = _run_cli(
        ["council", "discuss", "--base-dir", str(council_env["repo"]), "--question", "test quota exhaustion"],
        capsys,
    )
    assert rc == EXIT_PROVIDER
    assert data["error"]["kind"] == "billing_error"


def test_failure_4_malformed_json(council_env, monkeypatch, capsys):
    monkeypatch.setenv("FAKE_MODE_CRITIQUE_AGY", "bad_json")
    rc, data, _ = _run_cli(
        ["council", "discuss", "--base-dir", str(council_env["repo"]), "--question", "test bad json"],
        capsys,
    )
    assert rc == EXIT_PROVIDER
    assert data["error"]["kind"] in ("malformed_output", "missing_answer")


def test_failure_5_incorrect_model_silent_fallback(council_env, monkeypatch, capsys):
    monkeypatch.setenv("FAKE_MODE_CLAUDE", "fallback")
    rc, data, _ = _run_cli(
        ["council", "discuss", "--base-dir", str(council_env["repo"]), "--question", "test model fallback"],
        capsys,
    )
    assert rc == EXIT_PROVIDER
    assert data["error"]["kind"] == "model_fallback"


def test_failure_6_timeout_kills_process_tree(council_env, monkeypatch, capsys):
    pids_file = council_env["tmp"] / "hang_pids.json"
    monkeypatch.setenv("FAKE_PIDS", str(pids_file))
    monkeypatch.setenv("FAKE_MODE_PROPOSAL_CODEX", "hang")

    rc, data, _ = _run_cli(
        [
            "council",
            "discuss",
            "--base-dir",
            str(council_env["repo"]),
            "--timeout",
            "1.5",
            "--question",
            "test timeout",
        ],
        capsys,
    )
    assert rc == EXIT_TIMEOUT
    assert data["error"]["kind"] == "timeout"


def test_failure_7_interrupted_execution_and_resume_skips_completed_stages(council_env, monkeypatch, capsys):
    # Fail during CRITIQUE on first run; Proposals for all 3 providers are already saved in SQLite!
    monkeypatch.setenv("FAKE_MODE_CRITIQUE_AGY", "bad_json")
    rc, data, _ = _run_cli(
        ["council", "discuss", "--base-dir", str(council_env["repo"]), "--question", "test resume checkpointing"],
        capsys,
    )
    assert rc == EXIT_PROVIDER
    run_id = data["run_id"]
    assert data["run_status"] == "FAILED"

    store = CouncilStore()
    stages = store.get_stage_outputs(run_id, stage="proposal", attempt=1)
    completed_proposals = [s for s in stages if s["status"] == "ok"]
    assert len(completed_proposals) == 3

    # Clear record_dir and fix FAKE_MODE_CRITIQUE_AGY so resume succeeds
    for p in council_env["record_dir"].glob("*.json"):
        p.unlink()
    monkeypatch.delenv("FAKE_MODE_CRITIQUE_AGY", raising=False)

    rc_res, res_data, err_res = _run_cli(["council", "resume", "--run-id", run_id], capsys)
    assert rc_res == EXIT_OK, err_res
    assert res_data["run_status"] == "COMPLETED"

    # Resume MUST NOT re-run any of the 3 completed PROPOSAL stages!
    resumed_records = council_env["records"]()
    assert sum(1 for r in resumed_records if r["schema_kind"] == "proposal") == 0
    # Only the 1 missing critique (agy) + 1 synthesis (claude) should have executed!
    assert sum(1 for r in resumed_records if r["schema_kind"] == "critique") == 1
    assert sum(1 for r in resumed_records if r["schema_kind"] == "synthesis") == 1


def test_resume_claude_proposal_preserves_other_agents_and_streams_safe_progress(council_env, monkeypatch, capsys):
    monkeypatch.setenv("FAKE_MODE_PROPOSAL_CLAUDE", "bad_json")
    rc, data, _ = _run_cli(
        ["council", "discuss", "--base-dir", str(council_env["repo"]), "--question", "research only"], capsys,
    )
    assert rc == EXIT_PROVIDER
    run_id = data["run_id"]
    for path in council_env["record_dir"].glob("*.json"):
        path.unlink()
    monkeypatch.delenv("FAKE_MODE_PROPOSAL_CLAUDE")
    rc, resumed, _ = _run_cli(["council", "resume", "--run-id", run_id], capsys)
    assert rc == EXIT_OK
    proposals = [r for r in council_env["records"]() if r["schema_kind"] == "proposal"]
    assert [r["kind"] for r in proposals] == ["claude"]
    assert proposals[0]["argv"][proposals[0]["argv"].index("--output-format") + 1] == "stream-json"
    events = Path(resumed["events_jsonl_path"]).read_text(encoding="utf-8")
    assert 'agent.response_progress' in events
    assert 'private reasoning must not be published' not in events


def test_failure_8_unauthorized_file_writes_rejected_and_reverted(council_env, monkeypatch, capsys):
    rc, plan_data, _ = _run_cli(
        ["council", "plan", "--base-dir", str(council_env["repo"]), "--question", "Plan scoped change"],
        capsys,
    )
    assert rc == EXIT_OK
    run_id = plan_data["run_id"]

    monkeypatch.setenv("FAKE_COUNCIL_BEHAVIOR", "unauthorized_write")
    rc_exec, exec_data, _ = _run_cli(
        ["council", "execute", "--run-id", run_id, "--approve", "--writer", "claude"],
        capsys,
    )
    assert rc_exec == EXIT_REFUSED
    assert exec_data["error"]["kind"] == "scope_violation"

    # Verify unauthorized_file.py was rejected/reverted in the worktree
    store = CouncilStore()
    run_row = store.get_run(run_id)
    wt_path = Path(run_row["worktree_path"])
    sandbox = WorktreeSandbox(run_id, council_env["repo"], str(council_env["worktree_root"]))
    sandbox.verify_scope_and_collect_diff(["app.py"], [".env"], revert_on_violation=True)
    assert not (wt_path / "unauthorized_file.py").exists()


def test_failure_9_recursive_invocation_refused(council_env, monkeypatch, capsys):
    monkeypatch.setenv("PEER_CONSULT_DEPTH", "1")
    rc, data, _ = _run_cli(
        ["council", "discuss", "--base-dir", str(council_env["repo"]), "--question", "test recursion guard"],
        capsys,
    )
    assert rc == EXIT_REFUSED
    assert data["error"]["kind"] == "recursion_refused"
    assert len(council_env["records"]()) == 0


def test_failure_10_prompt_injection_and_secret_redaction(council_env, monkeypatch, capsys):
    monkeypatch.setenv("FAKE_COUNCIL_BEHAVIOR", "prompt_injection")
    secret_val = "sk-proj-ABCDEFGHIJKLMNOPQRSTUV1234567890"
    rc, data, err = _run_cli(
        [
            "council",
            "plan",
            "--base-dir",
            str(council_env["repo"]),
            "--question",
            f"Review auth module with token {secret_val}",
        ],
        capsys,
    )
    assert rc == 0, err
    # Prompt injection in codex proposal must NOT bypass AWAITING_APPROVAL gate
    assert data["run_status"] == "AWAITING_APPROVAL"
    # Secret in question must be redacted in persisted SQLite state and output envelope
    assert secret_val not in json.dumps(data)


def test_failure_11_failed_tests_controlled_repair_and_max_repairs(council_env, monkeypatch, capsys):
    # Case A: flaky_test_once fails on attempt 1, repairs on attempt 2, and completes
    rc, plan_data, _ = _run_cli(
        ["council", "plan", "--base-dir", str(council_env["repo"]), "--question", "Test repair loop"],
        capsys,
    )
    assert rc == 0
    monkeypatch.setenv("FAKE_COUNCIL_BEHAVIOR", "flaky_test_once")
    rc_exec, exec_data, err_exec = _run_cli(
        ["council", "execute", "--run-id", plan_data["run_id"], "--approve"],
        capsys,
    )
    assert rc_exec == 0, err_exec
    assert exec_data["run_status"] == "COMPLETED"
    assert exec_data["execution"]["repair_attempts"] == 1

    # Case B: always_fail_tests exhausts max_repairs (2) and fails closed
    rc2, plan_data2, _ = _run_cli(
        ["council", "plan", "--base-dir", str(council_env["repo"]), "--question", "Test max repairs exhausted"],
        capsys,
    )
    assert rc2 == 0
    monkeypatch.setenv("FAKE_COUNCIL_BEHAVIOR", "always_fail_tests")
    rc_exec2, exec_data2, _ = _run_cli(
        ["council", "execute", "--run-id", plan_data2["run_id"], "--approve"],
        capsys,
    )
    assert rc_exec2 == EXIT_PROVIDER
    assert exec_data2["error"]["kind"] == "repair_budget_exhausted"


def test_failure_12_conflicting_reviews_repair_and_halt(council_env, monkeypatch, capsys):
    # Case A: review_conflict_once triggers 1 repair pass and then both reviewers approve
    rc, plan_data, _ = _run_cli(
        ["council", "plan", "--base-dir", str(council_env["repo"]), "--question", "Test conflicting review recovery"],
        capsys,
    )
    assert rc == 0
    monkeypatch.setenv("FAKE_COUNCIL_BEHAVIOR", "review_conflict_once")
    rc_exec, exec_data, err_exec = _run_cli(
        ["council", "execute", "--run-id", plan_data["run_id"], "--approve"],
        capsys,
    )
    assert rc_exec == 0, err_exec
    assert exec_data["run_status"] == "COMPLETED"
    assert exec_data["execution"]["repair_attempts"] == 1

    # Case B: always_reject_review halts after max_repairs
    rc2, plan_data2, _ = _run_cli(
        ["council", "plan", "--base-dir", str(council_env["repo"]), "--question", "Test persistent review rejection"],
        capsys,
    )
    assert rc2 == 0
    monkeypatch.setenv("FAKE_COUNCIL_BEHAVIOR", "always_reject_review")
    rc_exec2, exec_data2, _ = _run_cli(
        ["council", "execute", "--run-id", plan_data2["run_id"], "--approve"],
        capsys,
    )
    assert rc_exec2 == EXIT_PROVIDER
    assert exec_data2["error"]["kind"] == "repair_budget_exhausted"


# ---------------------------------------------------------------------------
# 5. Single-Writer Lock & CLI Status/Cancel/Report/Doctor Tests
# ---------------------------------------------------------------------------

def test_single_writer_lock_prevents_concurrent_writers(council_env):
    sandbox = WorktreeSandbox("run-lock-test", council_env["repo"], str(council_env["worktree_root"]))
    sandbox.prepare_worktree()
    sandbox.acquire_writer_lock("claude")
    try:
        with pytest.raises(SandboxError) as exc_info:
            sandbox.acquire_writer_lock("codex")
        assert exc_info.value.kind == "writer_lock_conflict"
    finally:
        sandbox.release_writer_lock("claude")
    # Even after release, a second DIFFERENT writer is refused for the same run worktree
    with pytest.raises(SandboxError) as exc_info2:
        sandbox.acquire_writer_lock("codex")
    assert exc_info2.value.kind == "writer_lock_conflict"


def test_cli_status_report_cancel_and_doctor(council_env, capsys):
    rc, plan_data, _ = _run_cli(
        ["council", "plan", "--base-dir", str(council_env["repo"]), "--question", "Check CLI commands"],
        capsys,
    )
    assert rc == 0
    run_id = plan_data["run_id"]

    # status --run-id
    rc_st, st_data, _ = _run_cli(["council", "status", "--run-id", run_id], capsys)
    assert rc_st == 0
    assert st_data["run_id"] == run_id

    # report --run-id --format json
    rc_rep, rep_data, _ = _run_cli(["council", "report", "--run-id", run_id, "--format", "json"], capsys)
    assert rc_rep == 0
    assert rep_data["run_id"] == run_id

    # cancel --run-id
    rc_can, can_data, _ = _run_cli(["council", "cancel", "--run-id", run_id], capsys)
    assert rc_can == 0
    assert can_data["cancel_requested"] is True

    # council doctor (verify structured report includes council checks)
    _, doc_data, _ = _run_cli(["council", "doctor"], capsys)
    check_names = [c["name"] for c in doc_data.get("checks", [])]
    assert "council: git worktree support" in check_names
    assert "council: SQLite WAL state store" in check_names
