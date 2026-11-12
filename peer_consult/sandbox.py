"""Sandboxed Git worktree management, single-writer lock, scope verification, and deterministic testing."""
from __future__ import annotations

import fnmatch
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import procutil
from .config import home_dir
from .request import is_sensitive_path, redact

_CONTROL_DIRS = {".git", ".agents", ".claude", ".codex", ".gemini"}


class SandboxError(Exception):
    def __init__(self, kind: str, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.kind = kind
        self.details = details or {}


@dataclass
class ScopeCheckResult:
    ok: bool
    modified_files: list[str]
    violations: list[dict[str, str]]
    diff_text: str


@dataclass
class VerificationResult:
    passed: bool
    returncode: int | None
    command: list[str]
    stdout: str
    stderr: str
    elapsed_seconds: float
    security_passed: bool
    security_issues: list[str]


def _git(argv: list[str], cwd: Path, timeout: float = 60.0) -> tuple[int, str, str]:
    try:
        p = subprocess.run(
            ["git", *argv],
            cwd=str(cwd),
            capture_output=True,
            timeout=timeout,
            shell=False,
        )
        return (
            p.returncode,
            p.stdout.decode("utf-8", errors="replace"),
            p.stderr.decode("utf-8", errors="replace"),
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, "", str(e)


def matches_scope_pattern(rel_path: str, patterns: list[str]) -> bool:
    norm = rel_path.replace("\\", "/").lstrip("./")
    for raw in patterns:
        pat = raw.replace("\\", "/").lstrip("./")
        if not pat:
            continue
        if norm == pat or fnmatch.fnmatch(norm, pat):
            return True
        if pat.endswith("/") and norm.startswith(pat):
            return True
    return False


class WorktreeSandbox:
    """Manages an isolated Git worktree, single-writer lock, and scope/test verification."""

    def __init__(self, run_id: str, base_dir: Path, worktree_base_dir: str = ""):
        self.run_id = run_id
        self.base_dir = base_dir.resolve()
        rc, top, err = _git(["rev-parse", "--show-toplevel"], self.base_dir)
        if rc != 0 or not top.strip():
            raise SandboxError("not_a_git_repo", f"execution requires a Git repository at {self.base_dir}: {err.strip()}")
        self.repo_root = Path(top.strip()).resolve()
        rc, rev, err = _git(["rev-parse", "HEAD"], self.repo_root)
        if rc != 0 or not rev.strip():
            raise SandboxError("git_error", f"cannot resolve HEAD revision in {self.repo_root}: {err.strip()}")
        self.base_revision = rev.strip()
        wt_root = Path(worktree_base_dir).resolve() if worktree_base_dir else (home_dir() / "worktrees")
        wt_root.mkdir(parents=True, exist_ok=True)
        self.worktree_path = (wt_root / run_id).resolve()
        self.branch_name = f"council/{run_id}"
        self.lock_file = home_dir() / "state" / "runs" / run_id / "writer.lock"

    def prepare_worktree(self) -> Path:
        """Create or reset the dedicated Git worktree for this council run."""
        if self.worktree_path.exists():
            _git(["worktree", "remove", "--force", str(self.worktree_path)], self.repo_root)
            if self.worktree_path.exists():
                shutil.rmtree(self.worktree_path, ignore_errors=True)
        rc, out, err = _git(
            ["worktree", "add", "-B", self.branch_name, str(self.worktree_path), self.base_revision],
            self.repo_root,
        )
        if rc != 0:
            raise SandboxError(
                "worktree_creation_failed",
                f"failed to create Git worktree at {self.worktree_path}: {(err or out).strip()}",
            )
        return self.worktree_path

    def acquire_writer_lock(self, writer: str) -> None:
        """Ensure only a single writer agent can ever operate on this worktree."""
        self.lock_file.parent.mkdir(parents=True, exist_ok=True)
        if self.lock_file.exists():
            try:
                existing = json.loads(self.lock_file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                existing = {}
            existing_writer = existing.get("writer")
            existing_active = existing.get("active", False)
            if existing_active:
                raise SandboxError(
                    "writer_lock_conflict",
                    f"worktree for {self.run_id} is already locked by active writer '{existing_writer}'",
                    existing,
                )
            if existing_writer and existing_writer != writer:
                raise SandboxError(
                    "writer_lock_conflict",
                    f"worktree for {self.run_id} is bound to single writer '{existing_writer}'; "
                    f"refusing second writer '{writer}'",
                    existing,
                )
        self.lock_file.write_text(
            json.dumps({"run_id": self.run_id, "writer": writer, "pid": os.getpid(), "active": True}),
            encoding="utf-8",
        )

    def release_writer_lock(self, writer: str) -> None:
        if self.lock_file.exists():
            try:
                data = json.loads(self.lock_file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                data = {"run_id": self.run_id, "writer": writer}
            data["active"] = False
            self.lock_file.write_text(json.dumps(data), encoding="utf-8")

    def apply_structured_patches(
        self,
        patches: list[dict[str, Any]],
        authorized_files: list[str],
        forbidden_paths: list[str],
    ) -> list[str]:
        """Safely apply structured file patches inside the worktree with pre-write scope checks."""
        applied: list[str] = []
        for item in patches or []:
            raw_path = str(item.get("path") or "").strip()
            action = str(item.get("action") or "modify")
            content = str(item.get("content") or "")
            if not raw_path:
                continue
            target = (self.worktree_path / raw_path).resolve()
            try:
                rel = target.relative_to(self.worktree_path).as_posix()
            except ValueError as e:
                raise SandboxError(
                    "scope_violation",
                    f"writer attempted path traversal outside worktree: {raw_path}",
                    {"path": raw_path},
                ) from e
            violation = self._check_single_path(rel, target, authorized_files, forbidden_paths)
            if violation:
                raise SandboxError(
                    "scope_violation",
                    f"unauthorized file modification refused before write: {rel} ({violation['reason']})",
                    violation,
                )
            if action == "delete":
                if target.exists():
                    target.unlink()
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
            applied.append(rel)
        return applied

    def _check_single_path(
        self,
        rel: str,
        resolved: Path,
        authorized_files: list[str],
        forbidden_paths: list[str],
    ) -> dict[str, str] | None:
        try:
            resolved.relative_to(self.worktree_path)
        except ValueError:
            return {"path": rel, "reason": "escapes worktree root"}
        parts = {p.lower() for p in Path(rel).parts}
        if parts & _CONTROL_DIRS:
            return {"path": rel, "reason": "modifies protected control/hook directory"}
        if is_sensitive_path(resolved) or is_sensitive_path(Path(rel)):
            return {"path": rel, "reason": "credential or sensitive file path"}
        if forbidden_paths and matches_scope_pattern(rel, forbidden_paths):
            return {"path": rel, "reason": f"matches forbidden_paths ({forbidden_paths})"}
        if authorized_files and not matches_scope_pattern(rel, authorized_files):
            return {"path": rel, "reason": f"outside authorized_files scope ({authorized_files})"}
        return None

    def verify_scope_and_collect_diff(
        self,
        authorized_files: list[str],
        forbidden_paths: list[str],
        revert_on_violation: bool = True,
    ) -> ScopeCheckResult:
        """Inspect worktree changes after writer execution and reject any out-of-scope edits."""
        # Remove temporary .agents hook directory if created by orchestrator for agy,
        # as well as bytecode/test-runner caches generated by deterministic test runs.
        dot_agents = self.worktree_path / ".agents"
        if dot_agents.is_dir() and (dot_agents / "peer_consult_gate.py").exists():
            shutil.rmtree(dot_agents, ignore_errors=True)
        for cache_dir in list(self.worktree_path.rglob("__pycache__")) + list(self.worktree_path.rglob(".pytest_cache")):
            if cache_dir.is_dir():
                shutil.rmtree(cache_dir, ignore_errors=True)

        rc, status_out, _ = _git(["status", "--porcelain", "-uall"], self.worktree_path)
        modified: list[str] = []
        for line in status_out.splitlines():
            if len(line) < 4:
                continue
            raw_p = line[3:].strip()
            if " -> " in raw_p:
                raw_p = raw_p.split(" -> ", 1)[1].strip()
            raw_p = raw_p.strip('"').replace("\\", "/")
            if raw_p and raw_p not in modified:
                modified.append(raw_p)

        violations: list[dict[str, str]] = []
        for rel in modified:
            candidate = self.worktree_path / rel
            resolved = candidate.resolve() if candidate.exists() else (self.worktree_path / rel)
            v = self._check_single_path(rel, resolved, authorized_files, forbidden_paths)
            if v:
                violations.append(v)

        # Stage intent-to-add for untracked files only when no violations so diff captures new files
        if not violations and modified:
            _git(["add", "-N", "--", *modified], self.worktree_path)
        _, diff_text, _ = _git(["diff", self.base_revision], self.worktree_path)

        if violations and revert_on_violation:
            _git(["reset", "--hard", self.base_revision], self.worktree_path)
            _git(["clean", "-fd"], self.worktree_path)

        return ScopeCheckResult(
            ok=len(violations) == 0,
            modified_files=modified,
            violations=violations,
            diff_text=diff_text,
        )

    async def run_deterministic_checks(
        self,
        test_argv: list[str] | None,
        diff_text: str,
        timeout: float = 300.0,
    ) -> VerificationResult:
        """Run deterministic test commands inside the worktree and scan diff for leaked secrets."""
        sec_issues: list[str] = []
        _, redaction_counts = redact(diff_text or "")
        for kind, count in redaction_counts.items():
            sec_issues.append(f"diff contains {count} potential hardcoded secret(s) matching '{kind}'")

        cmd = test_argv or [sys.executable, "-m", "pytest", "-q"]
        env = dict(os.environ)
        env["PEER_CONSULT_DEPTH"] = "1"
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        res = await procutil.async_run(
            cmd,
            stdin_text="",
            env=env,
            cwd=str(self.worktree_path),
            timeout=timeout,
            max_stdout=2_000_000,
            max_stderr=1_000_000,
            heartbeat=30.0,
            label="worktree-tests",
        )
        tests_ok = (res.returncode == 0) and (not res.timed_out) and (not res.cancelled)
        return VerificationResult(
            passed=tests_ok and len(sec_issues) == 0,
            returncode=res.returncode,
            command=cmd,
            stdout=res.stdout,
            stderr=res.stderr,
            elapsed_seconds=res.elapsed,
            security_passed=len(sec_issues) == 0,
            security_issues=sec_issues,
        )
