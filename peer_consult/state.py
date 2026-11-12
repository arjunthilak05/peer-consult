"""Durable SQLite state machine persistence and JSONL event bus for Council runs.

All text persisted to SQLite or ``events.jsonl`` is scrubbed through
``request.redact()`` so credentials are never written to disk or broadcast over
the Pixel Office WebSocket.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import threading
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .config import home_dir
from .request import redact
from .schemas import CharacterAnimationState, CouncilEvent, OfficeRoomName

_SCHEMA_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    mode TEXT NOT NULL,
    status TEXT NOT NULL,
    current_stage TEXT NOT NULL,
    question TEXT NOT NULL,
    caller TEXT NOT NULL,
    chair TEXT NOT NULL,
    writer TEXT,
    base_dir TEXT NOT NULL,
    worktree_path TEXT,
    base_revision TEXT,
    approval_token_hash TEXT,
    approved_at TEXT,
    repair_attempts INTEGER NOT NULL DEFAULT 0,
    cancel_requested INTEGER NOT NULL DEFAULT 0,
    config_snapshot_json TEXT NOT NULL,
    packet_json TEXT NOT NULL,
    context_meta_json TEXT NOT NULL,
    anonymization_map_json TEXT,
    synthesis_json TEXT,
    execution_json TEXT,
    error_json TEXT,
    warnings_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS stage_outputs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    stage TEXT NOT NULL,
    attempt INTEGER NOT NULL DEFAULT 1,
    agent TEXT NOT NULL,
    anonymous_label TEXT,
    status TEXT NOT NULL,
    model_requested TEXT,
    model_reported TEXT,
    effort_requested TEXT,
    effort_observed TEXT,
    elapsed_seconds REAL,
    usage_json TEXT,
    cost_usd REAL,
    output_json TEXT,
    error_json TEXT,
    warnings_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    UNIQUE(run_id, stage, attempt, agent)
);

CREATE TABLE IF NOT EXISTS events (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL,
    run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    timestamp TEXT NOT NULL,
    stage TEXT NOT NULL,
    agent TEXT NOT NULL,
    event_type TEXT NOT NULL,
    animation_state TEXT NOT NULL DEFAULT 'idle',
    room TEXT NOT NULL DEFAULT 'desks',
    message TEXT NOT NULL DEFAULT '',
    payload_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_events_run_seq ON events(run_id, seq);
CREATE INDEX IF NOT EXISTS idx_stage_outputs_run ON stage_outputs(run_id, stage, attempt);
"""


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def restrict_to_owner(path: Path, mode: int = 0o600) -> None:
    """Best-effort chmod to owner-only on POSIX (Windows profile ACLs already restrict access)."""
    if os.name != "nt":
        try:
            os.chmod(path, mode)
        except OSError:
            pass


def ensure_private_dir(path: Path) -> None:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    restrict_to_owner(path, 0o700)


def create_private_file(path: Path, data: bytes) -> bool:
    """Create ``path`` with owner-only permissions; False if it already exists (never overwrites)."""
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
    except FileExistsError:
        return False
    try:
        os.write(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)
    return True


def scrub_data(val: Any) -> Any:
    """Recursively redact secret-looking strings before persistence or broadcast."""
    if isinstance(val, str):
        s, _ = redact(val)
        return s
    if isinstance(val, list):
        return [scrub_data(x) for x in val]
    if isinstance(val, dict):
        return {str(k): scrub_data(v) for k, v in val.items()}
    return val


class CouncilStore:
    """Thread-safe, WAL-backed SQLite store and per-run JSONL event logger."""

    def __init__(self, db_path: Path | None = None):
        self.state_root = home_dir() / "state"
        self.runs_dir = self.state_root / "runs"
        ensure_private_dir(self.state_root)
        self.runs_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.db_path = db_path or (self.state_root / "council.db")
        self._lock = threading.RLock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=30.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA busy_timeout=30000;")
        conn.execute("PRAGMA foreign_keys=ON;")
        return conn

    def _init_db(self) -> None:
        with self._lock:
            conn = self._connect()
            try:
                conn.executescript(_SCHEMA_SQL)
            finally:
                conn.close()

    def run_dir(self, run_id: str) -> Path:
        d = self.runs_dir / run_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def events_jsonl_path(self, run_id: str) -> Path:
        return self.run_dir(run_id) / "events.jsonl"

    def report_markdown_path(self, run_id: str) -> Path:
        return self.run_dir(run_id) / "report.md"

    # ------------------------------------------------------------------
    # Approval token management
    # ------------------------------------------------------------------

    def _secret_key(self) -> bytes:
        """Per-installation HMAC key, created atomically with owner-only permissions."""
        key_file = self.state_root / "approval.key"
        if not create_private_file(key_file, secrets.token_bytes(32)):
            restrict_to_owner(key_file)  # tighten keys written by older releases
        for _ in range(100):
            key = key_file.read_bytes()
            if len(key) >= 32:
                return key
            time.sleep(0.02)  # a concurrent process created the file and is still writing it
        raise RuntimeError(f"approval key {key_file} is truncated; delete it to regenerate")

    @staticmethod
    def _plan_digest(plan: Any) -> str:
        canonical = json.dumps(plan, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _approval_mac(self, token: str, plan: Any) -> str:
        """HMAC over the token AND the stored plan, so a token approves exactly the plan it was issued for."""
        msg = f"{token}\n{self._plan_digest(plan)}".encode()
        return hmac.new(self._secret_key(), msg, hashlib.sha256).hexdigest()

    def issue_approval_token(self, run_id: str) -> str:
        run = self.get_run(run_id)
        if not run or not run.get("synthesis"):
            raise ValueError(f"run '{run_id}' has no stored plan; store the synthesis before issuing a token")
        token = f"appr-{run_id}-{secrets.token_hex(16)}"
        digest = self._approval_mac(token, run["synthesis"])
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    "UPDATE runs SET approval_token_hash = ?, updated_at = ? WHERE run_id = ?",
                    (digest, _now_iso(), run_id),
                )
            finally:
                conn.close()
        return token

    def verify_approval(self, run_id: str, token: str | None = None, explicit_approve_flag: bool = False) -> bool:
        run = self.get_run(run_id)
        if not run:
            return False
        if run.get("approved_at"):
            return True
        if token:
            stored = run.get("approval_token_hash") or ""
            plan = run.get("synthesis")
            if stored and plan is not None and hmac.compare_digest(self._approval_mac(token, plan), stored):
                self.mark_approved(run_id)
                return True
            return False
        if explicit_approve_flag:
            self.mark_approved(run_id)
            return True
        return False

    def mark_approved(self, run_id: str) -> None:
        now = _now_iso()
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    "UPDATE runs SET approved_at = ?, updated_at = ? WHERE run_id = ?",
                    (now, now, run_id),
                )
            finally:
                conn.close()

    # ------------------------------------------------------------------
    # Run CRUD & State Transitions
    # ------------------------------------------------------------------

    def create_run(
        self,
        *,
        run_id: str | None = None,
        task_id: str,
        mode: str,
        question: str,
        caller: str,
        chair: str,
        writer: str | None,
        base_dir: Path,
        cfg: dict[str, Any],
        packet: dict[str, Any],
        context_meta: dict[str, Any],
    ) -> str:
        rid = run_id or f"run-{datetime.now(UTC):%Y%m%d}-{uuid.uuid4().hex[:8]}"
        now = _now_iso()
        safe_cfg = scrub_data({k: v for k, v in cfg.items() if not str(k).startswith("_")})
        safe_packet = scrub_data(packet)
        safe_ctx = scrub_data(context_meta)
        q_redacted, _ = redact(question)
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    INSERT INTO runs (
                        run_id, task_id, mode, status, current_stage, question, caller,
                        chair, writer, base_dir, config_snapshot_json, packet_json,
                        context_meta_json, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        rid,
                        task_id,
                        mode,
                        "CREATED",
                        "init",
                        q_redacted,
                        caller,
                        chair,
                        writer,
                        str(base_dir.resolve()),
                        json.dumps(safe_cfg, ensure_ascii=False),
                        json.dumps(safe_packet, ensure_ascii=False),
                        json.dumps(safe_ctx, ensure_ascii=False),
                        now,
                        now,
                    ),
                )
            finally:
                conn.close()
        self.emit_event(
            run_id=rid,
            stage="init",
            agent="orchestrator",
            event_type="run.created",
            animation_state="idle",
            room="desks",
            message=f"Council {mode} run {rid} initialized (chair={chair})",
            payload={"mode": mode, "chair": chair, "writer": writer, "task_id": task_id},
        )
        return rid

    def update_run(self, run_id: str, **fields: Any) -> None:
        if not fields:
            return
        cols: list[str] = []
        vals: list[Any] = []
        json_Map = {
            "anonymization_map": "anonymization_map_json",
            "synthesis": "synthesis_json",
            "execution": "execution_json",
            "error": "error_json",
            "warnings": "warnings_json",
        }
        for k, v in fields.items():
            if k in json_Map:
                cols.append(f"{json_Map[k]} = ?")
                vals.append(json.dumps(scrub_data(v), ensure_ascii=False) if v is not None else None)
            else:
                cols.append(f"{k} = ?")
                vals.append(v)
        cols.append("updated_at = ?")
        vals.append(_now_iso())
        vals.append(run_id)
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(f"UPDATE runs SET {', '.join(cols)} WHERE run_id = ?", vals)
            finally:
                conn.close()

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
            finally:
                conn.close()
        return self._decode_run_row(row) if row else None

    def list_runs(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(
                    "SELECT * FROM runs ORDER BY created_at DESC LIMIT ?", (int(limit),)
                ).fetchall()
            finally:
                conn.close()
        return [self._decode_run_row(r) for r in rows]

    @staticmethod
    def _decode_run_row(row: sqlite3.Row) -> dict[str, Any]:
        d = dict(row)
        for jcol, target in (
            ("config_snapshot_json", "config_snapshot"),
            ("packet_json", "packet"),
            ("context_meta_json", "context_meta"),
            ("anonymization_map_json", "anonymization_map"),
            ("synthesis_json", "synthesis"),
            ("execution_json", "execution"),
            ("error_json", "error"),
            ("warnings_json", "warnings"),
        ):
            raw = d.pop(jcol, None)
            d[target] = json.loads(raw) if raw else ([] if target == "warnings" else None)
        d["cancel_requested"] = bool(d.get("cancel_requested"))
        return d

    # ------------------------------------------------------------------
    # Stage Outputs & Checkpointing
    # ------------------------------------------------------------------

    def record_stage_output(
        self,
        *,
        run_id: str,
        stage: str,
        attempt: int = 1,
        agent: str,
        anonymous_label: str | None = None,
        status: str,
        model_requested: str | None = None,
        model_reported: str | None = None,
        effort_requested: str | None = None,
        effort_observed: str | None = None,
        elapsed_seconds: float | None = None,
        usage: dict[str, Any] | None = None,
        cost_usd: float | None = None,
        output: dict[str, Any] | None = None,
        error: dict[str, Any] | None = None,
        warnings: list[str] | None = None,
    ) -> None:
        now = _now_iso()
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    INSERT INTO stage_outputs (
                        run_id, stage, attempt, agent, anonymous_label, status,
                        model_requested, model_reported, effort_requested, effort_observed,
                        elapsed_seconds, usage_json, cost_usd, output_json, error_json,
                        warnings_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(run_id, stage, attempt, agent) DO UPDATE SET
                        anonymous_label = excluded.anonymous_label,
                        status = excluded.status,
                        model_requested = excluded.model_requested,
                        model_reported = excluded.model_reported,
                        effort_requested = excluded.effort_requested,
                        effort_observed = excluded.effort_observed,
                        elapsed_seconds = excluded.elapsed_seconds,
                        usage_json = excluded.usage_json,
                        cost_usd = excluded.cost_usd,
                        output_json = excluded.output_json,
                        error_json = excluded.error_json,
                        warnings_json = excluded.warnings_json,
                        created_at = excluded.created_at
                    """,
                    (
                        run_id,
                        stage,
                        attempt,
                        agent,
                        anonymous_label,
                        status,
                        model_requested,
                        model_reported,
                        effort_requested,
                        effort_observed,
                        elapsed_seconds,
                        json.dumps(scrub_data(usage), ensure_ascii=False) if usage is not None else None,
                        cost_usd,
                        json.dumps(scrub_data(output), ensure_ascii=False) if output is not None else None,
                        json.dumps(scrub_data(error), ensure_ascii=False) if error is not None else None,
                        json.dumps(scrub_data(warnings or []), ensure_ascii=False),
                        now,
                    ),
                )
            finally:
                conn.close()

    def get_stage_outputs(self, run_id: str, stage: str | None = None, attempt: int | None = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM stage_outputs WHERE run_id = ?"
        params: list[Any] = [run_id]
        if stage is not None:
            query += " AND stage = ?"
            params.append(stage)
        if attempt is not None:
            query += " AND attempt = ?"
            params.append(attempt)
        query += " ORDER BY id ASC"
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(query, params).fetchall()
            finally:
                conn.close()
        out = []
        for r in rows:
            d = dict(r)
            for jcol, target in (
                ("usage_json", "usage"),
                ("output_json", "output"),
                ("error_json", "error"),
                ("warnings_json", "warnings"),
            ):
                raw = d.pop(jcol, None)
                d[target] = json.loads(raw) if raw else ([] if target == "warnings" else None)
            out.append(d)
        return out

    # ------------------------------------------------------------------
    # Cancellation
    # ------------------------------------------------------------------

    def request_cancel(self, run_id: str) -> bool:
        run = self.get_run(run_id)
        if not run:
            return False
        self.update_run(run_id, cancel_requested=1)
        self.emit_event(
            run_id=run_id,
            stage=run.get("current_stage") or "unknown",
            agent="orchestrator",
            event_type="run.cancel_requested",
            animation_state="waiting",
            room="desks",
            message=f"Cancellation requested for run {run_id}",
            payload={},
        )
        return True

    def is_cancel_requested(self, run_id: str) -> bool:
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute("SELECT cancel_requested FROM runs WHERE run_id = ?", (run_id,)).fetchone()
            finally:
                conn.close()
        return bool(row and row["cancel_requested"])

    # ------------------------------------------------------------------
    # Event Bus (SQLite + JSONL)
    # ------------------------------------------------------------------

    def emit_event(
        self,
        *,
        run_id: str,
        stage: str,
        agent: str,
        event_type: str,
        animation_state: CharacterAnimationState = "idle",
        room: OfficeRoomName = "desks",
        message: str = "",
        payload: dict[str, Any] | None = None,
    ) -> CouncilEvent:
        now = _now_iso()
        ev_id = f"ev-{uuid.uuid4().hex[:12]}"
        safe_msg, _ = redact(message or "")
        safe_payload = scrub_data(payload or {})
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute(
                    """
                    INSERT INTO events (
                        event_id, run_id, timestamp, stage, agent, event_type,
                        animation_state, room, message, payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        ev_id,
                        run_id,
                        now,
                        stage,
                        agent,
                        event_type,
                        animation_state,
                        room,
                        safe_msg,
                        json.dumps(safe_payload, ensure_ascii=False),
                    ),
                )
                seq = int(cur.lastrowid or 0)
            finally:
                conn.close()
            ev = CouncilEvent(
                seq=seq,
                event_id=ev_id,
                run_id=run_id,
                timestamp=now,
                stage=stage,
                agent=agent,
                event_type=event_type,
                animation_state=animation_state,
                room=room,
                message=safe_msg,
                payload=safe_payload,
            )
            jsonl_file = self.events_jsonl_path(run_id)
            with open(jsonl_file, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(ev.model_dump(mode="json"), ensure_ascii=False) + "\n")
        return ev

    def get_events(self, run_id: str | None = None, after_seq: int = 0, limit: int = 500) -> list[dict[str, Any]]:
        query = "SELECT * FROM events WHERE seq > ?"
        params: list[Any] = [int(after_seq)]
        if run_id:
            query += " AND run_id = ?"
            params.append(run_id)
        query += " ORDER BY seq ASC LIMIT ?"
        params.append(int(limit))
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(query, params).fetchall()
            finally:
                conn.close()
        out = []
        for r in rows:
            d = dict(r)
            raw = d.pop("payload_json", "{}")
            d["payload"] = json.loads(raw) if raw else {}
            out.append(d)
        return out
