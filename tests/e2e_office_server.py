"""Launch a real Pixel Office server for end-to-end browser tests.

The orchestrator, SQLite store, event bus, worktree sandbox and test runner are all REAL;
only the three provider CLIs are replaced by the deterministic fake adapters in
``tests/fake_cli.py`` so CI does not need authenticated accounts. The UI is NOT in demo
mode: every event it renders is emitted by the real orchestrator.

Usage: python tests/e2e_office_server.py <port> <token>
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main() -> int:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 4199
    token = sys.argv[2] if len(sys.argv) > 2 else "e2e-office-token-0123456789"
    tmp = Path(tempfile.mkdtemp(prefix="pc-office-e2e-"))
    home, repo, records = tmp / "home", tmp / "repo", tmp / "records"
    for d in (home, repo, records):
        d.mkdir(parents=True)

    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "e2e@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "E2E"], cwd=repo, check=True)
    (repo / "app.py").write_text("def compute() -> int:\n    return 1\n", encoding="utf-8")
    (repo / "test_app.py").write_text("from app import compute\n\ndef test_compute():\n    assert compute() == 42\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)

    py = sys.executable.replace("\\", "\\\\")
    fake = str(ROOT / "tests" / "fake_cli.py").replace("\\", "\\\\")
    wt = str(tmp / "worktrees").replace("\\", "\\\\")
    cfg = home / "config.toml"
    cfg.write_text(f"""
[limits]
timeout_seconds = 30
transient_retries = 0
retry_backoff_seconds = 0.05
heartbeat_seconds = 60
[codex]
command = ["{py}", "{fake}", "codex"]
[claude]
command = ["{py}", "{fake}", "claude"]
auth = "subscription"
[agy]
command = ["{py}", "{fake}", "agy"]
[council]
stage_timeout_seconds = 30
[execute]
worktree_base_dir = "{wt}"
[office]
port = {port}
""", encoding="utf-8")

    os.environ["PEER_CONSULT_HOME"] = str(home)
    os.environ["PEER_CONSULT_CONFIG"] = str(cfg)
    os.environ["FAKE_RECORD_DIR"] = str(records)
    os.environ.pop("PEER_CONSULT_DEPTH", None)
    (tmp / "repo_path.txt").write_text(str(repo), encoding="utf-8")
    e2e_marker = ROOT / "tests" / ".e2e_repo_path"
    e2e_marker.write_text(str(repo), encoding="utf-8")
    os.chdir(repo)
    print(f"E2E_REPO={repo}", flush=True)

    import uvicorn

    from peer_consult.config import load_config
    from peer_consult.office_server import create_office_app
    from peer_consult.state import CouncilStore

    app = create_office_app(load_config(cfg), CouncilStore(), token=token)
    try:
        uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
    finally:
        try:
            e2e_marker.unlink(missing_ok=True)
        except Exception:
            pass
        shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
