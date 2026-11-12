"""Authenticated Starlette + Uvicorn HTTP & WebSocket backend for the Pixel-Art AI Council Office."""

from __future__ import annotations

import asyncio
import hmac
import json
import secrets
import time
from pathlib import Path
from typing import Any

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import FileResponse, HTMLResponse, JSONResponse
from starlette.routing import Mount, Route, WebSocketRoute
from starlette.staticfiles import StaticFiles
from starlette.websockets import WebSocket, WebSocketDisconnect

from .config import PROVIDERS, ConfigError, home_dir
from .council import CouncilOrchestrator
from .office_settings import model_settings, save_models
from .request import load_request
from .state import CouncilStore, create_private_file, ensure_private_dir, restrict_to_owner, scrub_data

AGENT_METADATA: dict[str, dict[str, Any]] = {
    "claude": {
        "id": "claude",
        "name": "Claude Code",
        "color": "#d97757",
        "palette": 0,
        "desk_seat": "desk-claude",
        "meeting_seat": "meeting-claude",
    },
    "codex": {
        "id": "codex",
        "name": "OpenAI Codex",
        "color": "#10a37f",
        "palette": 1,
        "desk_seat": "desk-codex",
        "meeting_seat": "meeting-codex",
    },
    "agy": {
        "id": "agy",
        "name": "Google Antigravity",
        "color": "#4285f4",
        "palette": 2,
        "desk_seat": "desk-agy",
        "meeting_seat": "meeting-agy",
    },
}


def load_or_create_office_token(state_dir: Path | None = None, explicit_token: str | None = None) -> str:
    """Return a persistent random bearer token for the local Pixel Office server."""
    if explicit_token:
        return explicit_token
    base = state_dir or (home_dir() / "state")
    ensure_private_dir(base)
    token_file = base / "office-token"
    if token_file.exists():
        restrict_to_owner(token_file)  # tighten tokens written by older releases
        existing = token_file.read_text(encoding="utf-8").strip()
        if len(existing) >= 16:
            return existing
        token_file.unlink(missing_ok=True)  # truncated or corrupt: regenerate
    token = secrets.token_urlsafe(24)
    if not create_private_file(token_file, token.encode("utf-8")):
        return token_file.read_text(encoding="utf-8").strip()  # a concurrent server created it first
    return token


def _verify_token(candidate: str | None, expected: str) -> bool:
    if not candidate or not expected:
        return False
    return hmac.compare_digest(candidate.encode("utf-8"), expected.encode("utf-8"))


def _extract_request_token(request: Request) -> str | None:
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    header_tok = request.headers.get("X-Office-Token")
    if header_tok:
        return header_tok.strip()
    q_tok = request.query_params.get("token")
    if q_tok:
        return q_tok.strip()
    return None


def map_agent_states(
    cfg: dict[str, Any],
    run_row: dict[str, Any] | None,
    stage_outputs: list[dict[str, Any]],
    events: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Deterministically map backend run/stage/event state to the 3 pixel-art agents."""
    agents: dict[str, dict[str, Any]] = {}
    for p in PROVIDERS:
        meta = AGENT_METADATA[p]
        pcfg = cfg.get(p) or {}
        agents[p] = {
            "id": p,
            "name": meta["name"],
            "color": meta["color"],
            "palette": meta["palette"],
            "model": pcfg.get("model", "unknown"),
            "reasoning_effort": pcfg.get("effort", "high"),
            "role": "adviser",
            "room": "desks",
            "seat_id": meta["desk_seat"],
            "animation": "idle",
            "current_task": "Ready for a research question or project",
            "tool_calls": [],
            "elapsed_ms": 0,
            "usage": {
                "input_tokens": 0,
                "output_tokens": 0,
                "cost_usd": None,
                "duration_ms": 0,
            },
            "latest_output": None,
            "status_badge": "IDLE",
        }

    if not run_row:
        return agents

    chair = run_row.get("chair") or "claude"
    writer = run_row.get("writer")
    run_status = run_row.get("status", "CREATED")
    if chair in agents:
        agents[chair]["role"] = "chair"
    if writer and writer in agents and (run_status in ("WORKTREE_READY", "EXECUTING", "VERIFYING", "REVIEWING", "REPAIRING") or run_row.get("execution")):
        agents[writer]["role"] = "writer"

    for ev in events:
        actor = ev.get("agent")
        if actor in agents:
            agents[actor]["tool_calls"].append(
                {
                    "seq": ev.get("seq", 0),
                    "timestamp": ev.get("timestamp", ""),
                    "stage": ev.get("stage", ""),
                    "event_type": ev.get("event_type", ""),
                    "summary": ev.get("message") or f"[{ev.get('stage')}] {ev.get('event_type')}",
                    "animation_state": ev.get("animation_state", "idle"),
                    "room": ev.get("room", "desks"),
                }
            )

    for st in stage_outputs:
        p = st.get("agent")
        if p not in agents:
            continue
        dur_ms = int(float(st.get("elapsed_seconds") or 0.0) * 1000)
        agents[p]["elapsed_ms"] += dur_ms
        agents[p]["usage"]["duration_ms"] += dur_ms
        usage_raw = st.get("usage")
        if isinstance(usage_raw, dict):
            for k in ("input_tokens", "prompt_tokens"):
                if isinstance(usage_raw.get(k), int):
                    agents[p]["usage"]["input_tokens"] += usage_raw[k]
            for k in ("output_tokens", "completion_tokens"):
                if isinstance(usage_raw.get(k), int):
                    agents[p]["usage"]["output_tokens"] += usage_raw[k]
        if isinstance(st.get("cost_usd"), (int, float)):
            cur = agents[p]["usage"]["cost_usd"] or 0.0
            agents[p]["usage"]["cost_usd"] = round(cur + float(st["cost_usd"]), 6)
        if st.get("output"):
            agents[p]["latest_output"] = st["output"]

    stage_by_key = {(s["stage"], s["agent"]): s for s in stage_outputs}
    latest_activity = {}
    for event in events:
        if event.get("agent") in agents and event.get("event_type", "").endswith(
            (".agent_started", ".agent_completed", ".agent_failed", ".agent_timeout", ".agent_cancelled")
        ):
            latest_activity[(event.get("stage"), event["agent"])] = event

    def is_running(stage: str, provider: str) -> bool:
        return latest_activity.get((stage, provider), {}).get("event_type", "").endswith(".agent_started")

    if run_status in ("CREATED", "CONTEXT_BUILT", "PROPOSING"):
        for p in PROVIDERS:
            st = stage_by_key.get(("proposal", p))
            agents[p]["room"] = "desks"
            agents[p]["seat_id"] = AGENT_METADATA[p]["desk_seat"]
            if not st or is_running("proposal", p):
                agents[p]["animation"] = "thinking"
                agents[p]["current_task"] = "Generating independent read-only proposal"
                agents[p]["status_badge"] = "THINKING"
            elif st["status"] == "ok":
                agents[p]["animation"] = "waiting"
                agents[p]["current_task"] = "Proposal submitted; awaiting peers"
                agents[p]["status_badge"] = "READY"
            else:
                agents[p]["animation"] = "failed"
                err_msg = (st.get("error") or {}).get("message", "error")
                agents[p]["current_task"] = f"Proposal failed: {err_msg}"
                agents[p]["status_badge"] = "FAILED"

    elif run_status == "CRITIQUING":
        for p in PROVIDERS:
            st = stage_by_key.get(("critique", p))
            agents[p]["room"] = "meeting_room"
            agents[p]["seat_id"] = AGENT_METADATA[p]["meeting_seat"]
            if not st or is_running("critique", p):
                agents[p]["animation"] = "reading"
                agents[p]["current_task"] = "Cross-critiquing anonymized proposals (Proposal A, B, C)"
                agents[p]["status_badge"] = "CRITIQUING"
            elif st["status"] == "ok":
                agents[p]["animation"] = "waiting"
                agents[p]["current_task"] = "Critique submitted in Council Room"
                agents[p]["status_badge"] = "READY"
            else:
                agents[p]["animation"] = "failed"
                agents[p]["current_task"] = "Critique failed"
                agents[p]["status_badge"] = "FAILED"

    elif run_status == "SYNTHESIZING":
        for p in PROVIDERS:
            agents[p]["room"] = "meeting_room"
            agents[p]["seat_id"] = AGENT_METADATA[p]["meeting_seat"]
            if p == chair:
                agents[p]["animation"] = "working"
                agents[p]["current_task"] = "Chair synthesizing consensus plan & evidence ledger"
                agents[p]["status_badge"] = "SYNTHESIZING"
            else:
                agents[p]["animation"] = "waiting"
                agents[p]["current_task"] = f"Waiting for Chair ({chair}) synthesis"
                agents[p]["status_badge"] = "WAITING"

    elif run_status == "AWAITING_APPROVAL":
        for p in PROVIDERS:
            agents[p]["room"] = "meeting_room"
            agents[p]["seat_id"] = AGENT_METADATA[p]["meeting_seat"]
            agents[p]["animation"] = "waiting"
            agents[p]["current_task"] = "Awaiting human approval to execute plan in sandbox"
            agents[p]["status_badge"] = "AWAITING APPROVAL"

    elif run_status in ("WORKTREE_READY", "EXECUTING", "REPAIRING"):
        active_writer = writer or chair
        reviewers = [p for p in PROVIDERS if p != active_writer]
        for p in PROVIDERS:
            if p == active_writer:
                agents[p]["role"] = "writer"
                agents[p]["room"] = "coding_room"
                agents[p]["seat_id"] = "coding-writer"
                agents[p]["animation"] = "coding"
                agents[p]["current_task"] = (
                    "Repairing implementation after review/test feedback"
                    if run_status == "REPAIRING"
                    else "Implementing approved plan in isolated Git worktree"
                )
                agents[p]["status_badge"] = run_status
            else:
                idx = reviewers.index(p) + 1
                agents[p]["role"] = "reviewer"
                agents[p]["room"] = "review_room"
                agents[p]["seat_id"] = f"review-{idx}"
                agents[p]["animation"] = "waiting"
                agents[p]["current_task"] = f"Monitoring single writer ({active_writer}) from Review Room"
                agents[p]["status_badge"] = "STANDBY"

    elif run_status in ("VERIFYING", "REVIEWING"):
        active_writer = writer or chair
        reviewers = [p for p in PROVIDERS if p != active_writer]
        for p in PROVIDERS:
            if p == active_writer:
                agents[p]["role"] = "writer"
                agents[p]["room"] = "coding_room"
                agents[p]["seat_id"] = "coding-writer"
                agents[p]["animation"] = "waiting"
                agents[p]["current_task"] = (
                    "Running deterministic test suite & scope checks"
                    if run_status == "VERIFYING"
                    else "Awaiting independent read-only peer reviews"
                )
                agents[p]["status_badge"] = run_status
            else:
                idx = reviewers.index(p) + 1
                agents[p]["role"] = "reviewer"
                agents[p]["room"] = "review_room"
                agents[p]["seat_id"] = f"review-{idx}"
                agents[p]["animation"] = "reviewing" if run_status == "REVIEWING" else "reading"
                agents[p]["current_task"] = (
                    "Performing independent read-only code & diff review"
                    if run_status == "REVIEWING"
                    else "Inspecting test output in Review Room"
                )
                agents[p]["status_badge"] = "REVIEWING"

    elif run_status == "COMPLETED":
        has_exec = bool(run_row.get("execution"))
        active_writer = writer
        reviewers = [p for p in PROVIDERS if p != active_writer] if active_writer else []
        for p in PROVIDERS:
            if has_exec and active_writer:
                if p == active_writer:
                    agents[p]["role"] = "writer"
                    agents[p]["room"] = "coding_room"
                    agents[p]["seat_id"] = "coding-writer"
                else:
                    idx = reviewers.index(p) + 1
                    agents[p]["role"] = "reviewer"
                    agents[p]["room"] = "review_room"
                    agents[p]["seat_id"] = f"review-{idx}"
            else:
                agents[p]["room"] = "meeting_room"
                agents[p]["seat_id"] = AGENT_METADATA[p]["meeting_seat"]
            agents[p]["animation"] = "completed"
            agents[p]["current_task"] = "Council workflow completed"
            agents[p]["status_badge"] = "COMPLETED"

    elif run_status in ("FAILED", "CANCELLED"):
        stage = {"executing": "writer", "reviewing": "review", "verifying": "verification"}.get(
            run_row.get("current_stage"), run_row.get("current_stage") or "proposal"
        )
        for p in PROVIDERS:
            st = stage_by_key.get((stage, p))
            failed = run_status == "FAILED" and bool(st and st["status"] not in ("ok", "cancelled"))
            agents[p]["animation"] = "failed" if failed else "waiting"
            agents[p]["status_badge"] = "FAILED" if failed else "PAUSED" if run_status == "CANCELLED" else "READY"
            if failed:
                agents[p]["room"] = "review_room"
                agents[p]["seat_id"] = f"doubts-{p}"
                err_msg = (st.get("error") or run_row.get("error") or {}).get("message", "Provider needs attention")
                agents[p]["current_task"] = err_msg
            else:
                agents[p]["current_task"] = "Work saved; run paused" if run_status == "CANCELLED" else "Work saved; waiting for the blocked step"

    return agents


def build_task_board(run_row: dict[str, Any] | None, stage_outputs: list[dict[str, Any]], events: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Construct the workflow kanban/task board columns for the UI."""
    if not run_row:
        return [
            {"id": "PROPOSING", "title": "1. Independent Proposals", "status": "PENDING", "items": []},
            {"id": "CRITIQUING", "title": "2. Cross-Critique (Anonymized)", "status": "PENDING", "items": []},
            {"id": "SYNTHESIZING", "title": "3. Chair Synthesis", "status": "PENDING", "items": []},
            {"id": "AWAITING_APPROVAL", "title": "4. Approval Gate", "status": "PENDING", "items": []},
            {"id": "EXECUTING", "title": "5. Single-Writer Execution", "status": "PENDING", "items": []},
            {"id": "REVIEWING", "title": "6. Dual Peer Review & Tests", "status": "PENDING", "items": []},
        ]

    run_status = run_row.get("status", "CREATED")
    mode = run_row.get("mode", "discuss")
    latest_activity = {}
    for event in events or []:
        if event.get("event_type", "").endswith((".agent_started", ".agent_completed", ".agent_failed", ".agent_timeout", ".agent_cancelled")):
            latest_activity[(event.get("stage"), event.get("agent"))] = event

    def _stage_items(stage_name: str) -> list[dict[str, Any]]:
        out = []
        for s in stage_outputs:
            if s["stage"] == stage_name:
                retrying = run_status not in ("FAILED", "CANCELLED", "COMPLETED") and latest_activity.get(
                    (stage_name, s["agent"]), {}
                ).get("event_type", "").endswith(".agent_started")
                out.append(
                    {
                        "stage": s["stage"],
                        "attempt": s.get("attempt", 1),
                        "provider": s["agent"],
                        "status": "IN_PROGRESS" if retrying else "COMPLETED" if s["status"] == "ok" else "CANCELLED" if s["status"] == "cancelled" else "FAILED",
                        "duration_ms": int(float(s.get("elapsed_seconds") or 0.0) * 1000),
                        "error": (s.get("error") or {}).get("message") if s.get("error") and not retrying else None,
                    }
                )
        return out

    prop_items = _stage_items("proposal")
    crit_items = _stage_items("critique")
    syn_items = _stage_items("synthesis")
    exec_items = _stage_items("writer")
    rev_items = _stage_items("review")

    def _col_status(items: list[dict[str, Any]], active_states: tuple[str, ...]) -> str:
        if run_status in active_states:
            return "IN_PROGRESS"
        if any(i["status"] == "FAILED" for i in items):
            return "FAILED"
        if items and all(i["status"] == "COMPLETED" for i in items):
            return "COMPLETED"
        return "PENDING"

    board = [
        {
            "id": "PROPOSING",
            "title": "1. Independent Proposals",
            "status": _col_status(prop_items, ("CREATED", "CONTEXT_BUILT", "PROPOSING")),
            "items": prop_items,
        },
        {
            "id": "CRITIQUING",
            "title": "2. Cross-Critique (Anonymized)",
            "status": _col_status(crit_items, ("CRITIQUING",)),
            "items": crit_items,
        },
        {
            "id": "SYNTHESIZING",
            "title": "3. Chair Synthesis",
            "status": _col_status(syn_items, ("SYNTHESIZING",)),
            "items": syn_items,
        },
    ]

    if mode in ("plan", "execute") or exec_items or run_status in (
        "AWAITING_APPROVAL",
        "WORKTREE_READY",
        "EXECUTING",
        "VERIFYING",
        "REVIEWING",
        "REPAIRING",
    ):
        approved = bool(run_row.get("approved_at"))
        board.append(
            {
                "id": "AWAITING_APPROVAL",
                "title": "4. Approval Gate",
                "status": "COMPLETED" if approved else ("IN_PROGRESS" if run_status == "AWAITING_APPROVAL" else "PENDING"),
                "items": [
                    {
                        "stage": "approval",
                        "attempt": 1,
                        "provider": "human",
                        "status": "COMPLETED" if approved else ("WAITING" if run_status == "AWAITING_APPROVAL" else "PENDING"),
                        "duration_ms": 0,
                        "error": None,
                    }
                ],
            }
        )
        board.append(
            {
                "id": "EXECUTING",
                "title": "5. Single-Writer Execution",
                "status": _col_status(exec_items, ("WORKTREE_READY", "EXECUTING", "REPAIRING")),
                "items": exec_items,
            }
        )
        board.append(
            {
                "id": "REVIEWING",
                "title": "6. Dual Peer Review & Tests",
                "status": _col_status(rev_items, ("VERIFYING", "REVIEWING")),
                "items": rev_items,
            }
        )

    return board


def compute_office_snapshot(
    cfg: dict[str, Any],
    store: CouncilStore,
    orchestrator: CouncilOrchestrator,
    run_id: str | None = None,
    *,
    demo_mode: bool = False,
) -> dict[str, Any]:
    """Compute a complete, sanitized state snapshot for the Pixel Office UI."""
    runs = store.list_runs(limit=30)
    target_run_id = run_id or (runs[0]["run_id"] if runs else None)

    if not target_run_id:
        return {
            "timestamp": time.time(),
            "demo_mode": demo_mode,
            "active_run_id": None,
            "run": None,
            "runs": [],
            "agents": map_agent_states(cfg, None, [], []),
            "task_board": build_task_board(None, []),
            "meeting": {
                "chair": cfg["council"]["chair"],
                "anonymized_map": {},
                "proposals": {},
                "critiques": {},
                "synthesis": None,
                "unresolved_disagreements": [],
            },
            "execution": None,
            "events": [],
        }

    run_row = store.get_run(target_run_id)
    if not run_row:
        return {
            "timestamp": time.time(),
            "demo_mode": demo_mode,
            "active_run_id": None,
            "run": None,
            "runs": [],
            "agents": map_agent_states(cfg, None, [], []),
            "task_board": build_task_board(None, []),
            "meeting": {
                "chair": cfg["council"]["chair"],
                "anonymized_map": {},
                "proposals": {},
                "critiques": {},
                "synthesis": None,
                "unresolved_disagreements": [],
            },
            "execution": None,
            "events": [],
            "error": {"kind": "run_not_found", "message": f"run '{target_run_id}' not found"},
        }

    stage_outputs = store.get_stage_outputs(target_run_id)
    events = store.get_events(target_run_id)
    envelope = orchestrator.format_run_envelope(target_run_id)
    agents = map_agent_states(cfg, run_row, stage_outputs, events)
    task_board = build_task_board(run_row, stage_outputs, events)

    synthesis = envelope.get("synthesis")
    unresolved = synthesis.get("unresolved_disagreements", []) if isinstance(synthesis, dict) else []
    exec_meta = envelope.get("execution") or {}

    return scrub_data(
        {
            "timestamp": time.time(),
            "demo_mode": demo_mode,
            "active_run_id": target_run_id,
            "run": {
                "run_id": envelope["run_id"],
                "task_id": envelope["task_id"],
                "mode": envelope["mode"],
                "state": envelope["run_status"],
                "current_stage": envelope["current_stage"],
                "question": run_row["question"],
                "cwd": run_row["base_dir"],
                "chair": envelope["chair"],
                "writer": envelope["writer"],
                "approved": bool(run_row.get("approved_at")),
                "worktree_path": run_row.get("worktree_path"),
                "branch_name": exec_meta.get("branch") or (f"council/{target_run_id}" if run_row.get("worktree_path") else None),
                "repair_attempts": run_row.get("repair_attempts", 0),
                "error": envelope["error"],
                "created_at": envelope["created_at"],
                "updated_at": envelope["updated_at"],
                "report_path": envelope["report_markdown_path"],
            },
            "runs": [
                {
                    "run_id": r["run_id"],
                    "mode": r["mode"],
                    "state": r["status"],
                    "question": r["question"][:120],
                    "chair": r["chair"],
                    "writer": r["writer"],
                    "created_at": r["created_at"],
                    "updated_at": r["updated_at"],
                }
                for r in runs
            ],
            "agents": agents,
            "task_board": task_board,
            "meeting": {
                "chair": envelope["chair"],
                "anonymized_map": envelope["anonymization_map"] or {},
                "proposals": envelope["proposals"],
                "critiques": envelope["critiques"],
                "synthesis": synthesis,
                "unresolved_disagreements": unresolved,
            },
            "execution": {
                "writer": envelope["writer"] or (synthesis.get("recommended_writer") if isinstance(synthesis, dict) else None),
                "approved": bool(run_row.get("approved_at")),
                "worktree_path": run_row.get("worktree_path"),
                "branch_name": exec_meta.get("branch"),
                "repair_attempts": run_row.get("repair_attempts", 0),
                "authorized_files": synthesis.get("authorized_files", []) if isinstance(synthesis, dict) else [],
                "forbidden_paths": synthesis.get("forbidden_paths", []) if isinstance(synthesis, dict) else [],
                "acceptance_criteria": synthesis.get("acceptance_criteria", []) if isinstance(synthesis, dict) else [],
                "changed_files": exec_meta.get("modified_files", []),
                "git_diff": exec_meta.get("diff", ""),
                "test_passed": exec_meta.get("tests_passed"),
                "test_output": exec_meta.get("test_output", ""),
                "peer_reviews": envelope["peer_reviews"],
                "pr_draft_path": exec_meta.get("pr_draft_path"),
            },
            "events": events,
        }
    )


def find_office_dist() -> Path | None:
    """The built office UI, shipped inside the package (`npm run build` in office-ui/ writes it there)."""
    dist = Path(__file__).resolve().parent / "office_dist"
    return dist if (dist / "index.html").is_file() else None


def create_office_app(
    cfg: dict[str, Any],
    store: CouncilStore | None = None,
    *,
    token: str | None = None,
    static_dir: Path | None = None,
) -> Starlette:
    """Create the Starlette ASGI application for the Pixel-Art AI Council Office."""
    store = store or CouncilStore()
    office_token = load_or_create_office_token(store.state_root, explicit_token=token)
    orchestrator = CouncilOrchestrator(cfg, store)
    background_tasks: dict[str, asyncio.Task[Any]] = {}
    writer_execution_lock = asyncio.Lock()

    if static_dir is None:
        static_dir = find_office_dist()

    def _require_auth(request: Request) -> JSONResponse | None:
        tok = _extract_request_token(request)
        if not _verify_token(tok, office_token):
            return JSONResponse(
                {"error": "unauthorized", "message": "Valid office bearer token required"},
                status_code=401,
            )
        return None

    async def api_health(request: Request) -> JSONResponse:
        return JSONResponse({"ok": True, "service": "peer-consult-office"})

    async def api_state(request: Request) -> JSONResponse:
        err = _require_auth(request)
        if err:
            return err
        run_id = request.query_params.get("run_id")
        snap = compute_office_snapshot(cfg, store, orchestrator, run_id=run_id)
        return JSONResponse(snap)

    def models_busy() -> bool:
        return any(not task.done() for task in background_tasks.values()) or any(
            run.get("status") not in ("COMPLETED", "FAILED", "CANCELLED") for run in store.list_runs(limit=50)
        )

    async def api_model_settings(request: Request) -> JSONResponse:
        err = _require_auth(request)
        if err:
            return err
        if request.method == "GET":
            return JSONResponse(model_settings(cfg, busy=models_busy()))
        if models_busy():
            return JSONResponse({"error": "run_active", "message": "Pause the active run before changing models."}, status_code=409)
        try:
            body = await request.json()
            updated = save_models(cfg, body.get("models") if isinstance(body, dict) else None)
        except (ValueError, TypeError, ConfigError) as exc:
            return JSONResponse({"error": "invalid_models", "message": str(exc)}, status_code=400)
        except OSError:
            return JSONResponse({"error": "config_write_failed", "message": "Could not save the model settings. Check config file permissions."}, status_code=500)
        cfg.clear()
        cfg.update(updated)
        return JSONResponse(model_settings(cfg))

    async def api_list_runs(request: Request) -> JSONResponse:
        err = _require_auth(request)
        if err:
            return err
        runs = store.list_runs(limit=50)
        return JSONResponse({"runs": scrub_data(runs)})

    async def api_get_run(request: Request) -> JSONResponse:
        err = _require_auth(request)
        if err:
            return err
        run_id = request.path_params["run_id"]
        if not store.get_run(run_id):
            return JSONResponse({"error": "run_not_found", "message": f"Unknown run_id: {run_id}"}, status_code=404)
        snap = compute_office_snapshot(cfg, store, orchestrator, run_id=run_id)
        return JSONResponse(snap)

    async def api_get_events(request: Request) -> JSONResponse:
        err = _require_auth(request)
        if err:
            return err
        run_id = request.path_params["run_id"]
        after_seq = int(request.query_params.get("after_seq", request.query_params.get("after_id", "0")))
        events = store.get_events(run_id, after_seq=after_seq)
        return JSONResponse({"run_id": run_id, "events": scrub_data(events)})

    async def api_start_run(request: Request) -> JSONResponse:
        err = _require_auth(request)
        if err:
            return err
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "bad_request", "message": "Invalid JSON body"}, status_code=400)

        question = str(body.get("question", "")).strip()
        if not question:
            return JSONResponse({"error": "bad_request", "message": "question is required"}, status_code=400)
        mode = str(body.get("mode", "plan")).strip()
        if mode not in ("discuss", "plan"):
            return JSONResponse({"error": "bad_request", "message": "mode must be discuss or plan"}, status_code=400)
        chair = body.get("chair") or cfg["council"]["chair"]
        writer = body.get("writer")
        cwd_str = body.get("cwd") or str(Path.cwd())
        files = body.get("files") or []
        wait_sync = bool(body.get("wait", False))

        def _loader() -> dict:
            req_dict: dict[str, Any] = {
                "question": question,
                "help_type": body.get("help_type", "design_critique"),
            }
            if files:
                req_dict["files"] = [{"path": f} if isinstance(f, str) else f for f in files]
            return load_request(json.dumps(req_dict, ensure_ascii=False))

        if wait_sync:
            code, out = await orchestrator.start_council_run(
                _loader,
                mode=mode,
                caller="user",
                chair_override=chair,
                writer_override=writer,
                base_dir=Path(cwd_str),
            )
            run_id = out.get("run_id")
            snap = compute_office_snapshot(cfg, store, orchestrator, run_id=run_id)
            return JSONResponse(
                {"ok": code == 0, "exit_code": code, "run_id": run_id, "snapshot": snap},
                status_code=200 if code == 0 else 422,
            )

        async def _bg_runner() -> None:
            try:
                await orchestrator.start_council_run(
                    _loader,
                    mode=mode,
                    caller="user",
                    chair_override=chair,
                    writer_override=writer,
                    base_dir=Path(cwd_str),
                )
            except Exception:
                pass

        task = asyncio.create_task(_bg_runner())
        # Give start_council_run a brief moment to insert the row in SQLite
        await asyncio.sleep(0.05)
        latest = store.list_runs(limit=1)
        run_id = latest[0]["run_id"] if latest else None
        if run_id:
            background_tasks[run_id] = task
        snap = compute_office_snapshot(cfg, store, orchestrator, run_id=run_id)
        return JSONResponse({"ok": True, "run_id": run_id, "snapshot": snap})

    async def api_approve_execute(request: Request) -> JSONResponse:
        err = _require_auth(request)
        if err:
            return err
        run_id = request.path_params["run_id"]
        try:
            body = await request.json()
        except Exception:
            body = {}

        writer = body.get("writer")
        create_pr = bool(body.get("create_pr", False))
        test_argv = body.get("test_argv")
        wait_sync = bool(body.get("wait", False))

        if writer_execution_lock.locked():
            return JSONResponse(
                {
                    "error": "writer_lock_conflict",
                    "message": "Another single-writer execution is already active.",
                },
                status_code=409,
            )

        run_row = store.get_run(run_id)
        if not run_row:
            return JSONResponse({"error": "not_found", "message": f"Unknown run_id: {run_id}"}, status_code=404)

        store.mark_approved(run_id)
        store.emit_event(
            run_id=run_id,
            stage="approval",
            agent="orchestrator",
            event_type="plan.approved",
            animation_state="working",
            room="coding_room",
            message=f"Execution approved via Pixel Office UI for single writer '{writer or run_row.get('writer') or run_row.get('chair')}'",
            payload={"writer": writer or run_row.get("writer") or run_row.get("chair")},
        )

        if wait_sync:
            async with writer_execution_lock:
                code, _ = await orchestrator.execute_plan(
                    run_id,
                    approve=True,
                    writer_override=writer,
                    test_argv=test_argv,
                    create_pr=create_pr,
                )
            snap = compute_office_snapshot(cfg, store, orchestrator, run_id=run_id)
            return JSONResponse(
                {"ok": code == 0, "exit_code": code, "run_id": run_id, "approved": True, "snapshot": snap},
                status_code=200 if code == 0 else 422,
            )

        async def _exec_runner() -> None:
            async with writer_execution_lock:
                try:
                    await orchestrator.execute_plan(
                        run_id,
                        approve=True,
                        writer_override=writer,
                        test_argv=test_argv,
                        create_pr=create_pr,
                    )
                except Exception:
                    pass

        task = asyncio.create_task(_exec_runner())
        background_tasks[f"exec-{run_id}"] = task
        snap = compute_office_snapshot(cfg, store, orchestrator, run_id=run_id)
        return JSONResponse({"ok": True, "run_id": run_id, "approved": True, "snapshot": snap})

    async def api_cancel_run(request: Request) -> JSONResponse:
        err = _require_auth(request)
        if err:
            return err
        run_id = request.path_params["run_id"]
        run_row = store.get_run(run_id)
        if not run_row:
            return JSONResponse({"error": "not_found", "message": f"Unknown run_id: {run_id}"}, status_code=404)
        store.request_cancel(run_id)
        if run_row["status"] not in ("COMPLETED", "FAILED", "CANCELLED"):
            store.update_run(run_id, status="CANCELLED")
        snap = compute_office_snapshot(cfg, store, orchestrator, run_id=run_id)
        return JSONResponse({"ok": True, "run_id": run_id, "state": "CANCELLED", "snapshot": snap})

    async def api_resume_run(request: Request) -> JSONResponse:
        err = _require_auth(request)
        if err:
            return err
        run_id = request.path_params["run_id"]
        try:
            body = await request.json()
        except Exception:
            body = {}
        wait_sync = bool(body.get("wait", False))

        if wait_sync:
            code, _ = await orchestrator.resume_run(run_id)
            snap = compute_office_snapshot(cfg, store, orchestrator, run_id=run_id)
            return JSONResponse(
                {"ok": code == 0, "exit_code": code, "run_id": run_id, "snapshot": snap},
                status_code=200 if code == 0 else 422,
            )

        async def _resume_runner() -> None:
            try:
                await orchestrator.resume_run(run_id)
            except Exception:
                pass

        task = asyncio.create_task(_resume_runner())
        background_tasks[f"resume-{run_id}"] = task
        snap = compute_office_snapshot(cfg, store, orchestrator, run_id=run_id)
        return JSONResponse({"ok": True, "run_id": run_id, "snapshot": snap})

    async def ws_events(websocket: WebSocket) -> None:
        tok = websocket.query_params.get("token") or websocket.headers.get("X-Office-Token")
        if not _verify_token(tok, office_token):
            await websocket.close(code=1008, reason="Unauthorized office token")
            return

        await websocket.accept()
        selected_run_id: str | None = websocket.query_params.get("run_id")
        last_seq = 0
        last_state_sig = ""

        initial_snap = compute_office_snapshot(cfg, store, orchestrator, run_id=selected_run_id)
        if initial_snap.get("active_run_id"):
            selected_run_id = initial_snap["active_run_id"]
            evs = initial_snap.get("events", [])
            if evs:
                last_seq = max(int(e.get("seq", 0)) for e in evs)
        await websocket.send_json({"type": "snapshot", "data": initial_snap})

        try:
            while True:
                try:
                    msg_raw = await asyncio.wait_for(websocket.receive_text(), timeout=0.35)
                    msg = json.loads(msg_raw)
                    action = msg.get("action")
                    if action == "select_run":
                        selected_run_id = msg.get("run_id")
                        last_seq = 0
                        snap = compute_office_snapshot(cfg, store, orchestrator, run_id=selected_run_id)
                        evs = snap.get("events", [])
                        if evs:
                            last_seq = max(int(e.get("seq", 0)) for e in evs)
                        await websocket.send_json({"type": "snapshot", "data": snap})
                    elif action == "replay":
                        rep_run_id = msg.get("run_id") or selected_run_id
                        if rep_run_id:
                            rep_events = store.get_events(rep_run_id, after_seq=0)
                            await websocket.send_json(
                                {
                                    "type": "replay",
                                    "run_id": rep_run_id,
                                    "events": scrub_data(rep_events),
                                }
                            )
                    elif action == "ping":
                        await websocket.send_json({"type": "pong", "timestamp": time.time()})
                except TimeoutError:
                    pass

                runs = store.list_runs(limit=1)
                if not selected_run_id and runs:
                    selected_run_id = runs[0]["run_id"]
                    last_seq = 0

                if selected_run_id:
                    new_events = store.get_events(selected_run_id, after_seq=last_seq)
                    run_row = store.get_run(selected_run_id)
                    cur_sig = f"{run_row.get('status') if run_row else ''}:{run_row.get('updated_at') if run_row else ''}:{len(new_events)}"
                    if new_events or cur_sig != last_state_sig:
                        last_state_sig = cur_sig
                        if new_events:
                            last_seq = max(int(e.get("seq", 0)) for e in new_events)
                        snap = compute_office_snapshot(cfg, store, orchestrator, run_id=selected_run_id)
                        await websocket.send_json(
                            {
                                "type": "events",
                                "run_id": selected_run_id,
                                "events": scrub_data(new_events),
                                "snapshot": snap,
                            }
                        )
        except WebSocketDisconnect:
            return
        except Exception:
            return

    async def index_page(request: Request) -> Any:
        if static_dir and (static_dir / "index.html").exists():
            return FileResponse(static_dir / "index.html")
        return HTMLResponse(
            "<html><body><h1>Peer-Consult Pixel Office</h1>"
            "<p>This installation has no office UI bundle. Install a release build "
            "(<code>pipx install peer-consult</code>) or, in a source checkout, run "
            "<code>npm ci &amp;&amp; npm run build</code> in <code>office-ui/</code>.</p>"
            "</body></html>"
        )

    routes: list[Any] = [
        Route("/api/health", api_health, methods=["GET"]),
        Route("/api/state", api_state, methods=["GET"]),
        Route("/api/settings/models", api_model_settings, methods=["GET", "POST"]),
        Route("/api/runs", api_list_runs, methods=["GET"]),
        Route("/api/runs/start", api_start_run, methods=["POST"]),
        Route("/api/runs/{run_id}", api_get_run, methods=["GET"]),
        Route("/api/runs/{run_id}/events", api_get_events, methods=["GET"]),
        Route("/api/runs/{run_id}/approve", api_approve_execute, methods=["POST"]),
        Route("/api/runs/{run_id}/cancel", api_cancel_run, methods=["POST"]),
        Route("/api/runs/{run_id}/resume", api_resume_run, methods=["POST"]),
        WebSocketRoute("/ws/events", ws_events),
    ]

    if static_dir and static_dir.exists():
        assets_dir = static_dir / "assets"
        if assets_dir.exists():
            routes.append(Mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets"))
        routes.append(Route("/", index_page, methods=["GET"]))
        routes.append(Mount("/", StaticFiles(directory=str(static_dir), html=True), name="static"))
    else:
        routes.append(Route("/", index_page, methods=["GET"]))

    middleware = [
        Middleware(
            CORSMiddleware,
            allow_origins=[
                "http://127.0.0.1:4173",
                "http://localhost:4173",
                "http://127.0.0.1:8787",
                "http://localhost:8787",
                "http://localhost:5173",
                "http://127.0.0.1:5173",
            ],
            allow_methods=["GET", "POST", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type", "X-Office-Token"],
        )
    ]

    app = Starlette(routes=routes, middleware=middleware)
    app.state.office_token = office_token
    app.state.store = store
    app.state.cfg = cfg
    app.state.orchestrator = orchestrator
    return app


def run_office_server(
    cfg: dict[str, Any],
    store: CouncilStore | None = None,
    *,
    host: str = "127.0.0.1",
    port: int = 4173,
    open_browser: bool = False,
) -> int:
    """Start the local Uvicorn HTTP + WebSocket server for the Pixel Office."""
    import sys
    import webbrowser

    import uvicorn

    store = store or CouncilStore()
    token = load_or_create_office_token(store.state_root)
    app = create_office_app(cfg, store, token=token)
    if host not in ("127.0.0.1", "localhost", "::1"):
        sys.stderr.write(
            f"WARNING: binding the office to {host} exposes an API that can start council runs and approve\n"
            "plan execution to every machine that can reach this port (bearer token required). Prefer 127.0.0.1\n"
            "and an SSH tunnel for remote access.\n"
        )
    url_host = f"[{host}]" if ":" in host else host  # IPv6 literals need brackets in URLs
    url = f"http://{url_host}:{port}/?token={token}"
    sys.stderr.write(f"Pixel-Art AI Council Office running at: {url}\n")
    sys.stderr.flush()
    if open_browser:
        webbrowser.open(url)
    uvicorn.run(app, host=host, port=port, log_level="warning")
    return 0
