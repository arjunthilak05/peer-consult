"""Consultation orchestration: guards, budget, temp workspace, retries, normalization."""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

from . import procutil
from .config import PROVIDERS, home_dir
from .procutil import log
from .providers import ADVICE_SCHEMA, AgyAdapter, ClaudeAdapter, CodexAdapter, ProviderError, prepare_agy_workspace
from .request import RequestError, build_packet, check_size, render_prompt

DEPTH_VAR = "PEER_CONSULT_DEPTH"

EXIT_OK, EXIT_USAGE, EXIT_REFUSED, EXIT_PROVIDER, EXIT_TIMEOUT, EXIT_CANCELLED = 0, 2, 3, 4, 5, 130


def current_depth() -> int:
    try:
        return int(os.environ.get(DEPTH_VAR, "0") or 0)
    except ValueError:
        return 1  # malformed marker: fail safe


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def envelope(req: dict | None, caller: str, target: str, cfg: dict, model: str, effort: str) -> dict:
    return {
        "status": "error",
        "request_id": (req or {}).get("request_id"),
        "task_id": (req or {}).get("task_id"),
        "caller": caller,
        "target": target,
        "started_at": _now(),
        "model": {"requested": model, "reported": None, "reported_all": [], "reported_source": None,
                  "fallback_detected": None},
        "effort": {"requested": effort, "observed": None},
        "elapsed_seconds": None,
        "attempts": 0,
        "usage": None,
        "cost_usd_estimate": None,
        "context": None,
        "budget": None,
        "advice": None,
        "error": None,
        "warnings": [],
    }


# ---------------------------------------------------------------- budget

class Budget:
    def __init__(self, task_id: str, limit: int):
        self.dir = home_dir() / "state" / "budget"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.path = self.dir / f"{task_id}.json"
        self.lock = self.dir / f"{task_id}.lock"
        self.limit = limit

    def _locked(self, fn):
        deadline = time.monotonic() + 15
        while True:
            try:
                fd = os.open(self.lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                break
            except FileExistsError:
                if time.monotonic() > deadline:
                    # stale lock from a crashed run
                    try:
                        if time.time() - self.lock.stat().st_mtime > 60:
                            self.lock.unlink()
                            continue
                    except FileNotFoundError:
                        continue
                    raise RuntimeError(f"budget lock busy: {self.lock}")
                time.sleep(0.05)
        try:
            return fn()
        finally:
            os.close(fd)
            self.lock.unlink(missing_ok=True)

    def _read(self) -> dict:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return {"count": 0, "request_ids": []}

    def reserve(self, request_id: str) -> dict:
        def f():
            st = self._read()
            if st["count"] >= self.limit:
                return {"ok": False, "used": st["count"], "max": self.limit}
            st["count"] += 1
            st["request_ids"].append(request_id)
            tmp = self.path.with_suffix(f".{os.getpid()}.tmp")
            tmp.write_text(json.dumps(st), encoding="utf-8")
            os.replace(tmp, self.path)
            return {"ok": True, "used": st["count"], "max": self.limit}
        return self._locked(f)

    def release(self, request_id: str) -> None:
        def f():
            st = self._read()
            if request_id in st["request_ids"]:
                st["request_ids"].remove(request_id)
                st["count"] = max(0, st["count"] - 1)
                self.path.write_text(json.dumps(st), encoding="utf-8")
        self._locked(f)


# ---------------------------------------------------------------- ask

def codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")


def _skill_paths_to_disable() -> list[Path]:
    """Hide our own Codex skills from a Codex adviser (belt-and-braces with no exec tools)."""
    paths = [codex_home() / "skills" / n / "SKILL.md" for n in ("ask-claude", "ask-agy", "council")]
    paths.append(Path.home() / ".agents" / "skills" / "ask-claude" / "SKILL.md")  # pre-agy install location
    return [p for p in paths if p.exists()]


def _child_env(target: str, cfg: dict, effort: str) -> tuple[dict, list[str]]:
    env = dict(os.environ)
    env[DEPTH_VAR] = str(current_depth() + 1)
    notes = []
    if target == "claude":
        # Documented precedence: CLAUDE_CODE_EFFORT_LEVEL overrides --effort. Pin it to the
        # requested effort so an inherited value cannot silently lower it.
        env["CLAUDE_CODE_EFFORT_LEVEL"] = effort
        if cfg["claude"]["auth"] == "subscription" and "ANTHROPIC_API_KEY" in env:
            env.pop("ANTHROPIC_API_KEY")
            notes.append("ANTHROPIC_API_KEY removed from adviser env (config [claude].auth = 'subscription')")
    return env, notes


def ask(req_raw_loader, *, caller: str, target: str, cfg: dict, base_dir: Path,
        model_override: str | None = None, effort_override: str | None = None,
        timeout_override: float | None = None, dry_run: bool = False) -> tuple[int, dict]:
    sect = cfg[target]
    model = model_override or sect["model"]
    effort = effort_override or sect["effort"]
    out = envelope(None, caller, target, cfg, model, effort)

    def fail(code, kind, msg, details=None, retryable=False):
        out["error"] = {"kind": kind, "message": msg, "retryable": retryable, "details": details or {}}
        return code, out

    if caller not in PROVIDERS or target not in PROVIDERS or caller == target:
        return fail(EXIT_USAGE, "invalid_direction",
                    f"caller and target must be two different agents from {PROVIDERS} (got {caller} -> {target})")
    if current_depth() >= 1:
        return fail(EXIT_REFUSED, "recursion_refused",
                    f"{DEPTH_VAR}={os.environ.get(DEPTH_VAR)}: this process is already a consultation adviser; "
                    "advisers may not consult another adviser. Answer from the packet instead.")
    try:
        req = req_raw_loader()
        out["request_id"], out["task_id"] = req["request_id"], req["task_id"]
        packet, ctx = build_packet(req, base_dir)
        out["context"] = ctx
        for kind, n in ctx["redactions"].items():
            out["warnings"].append(f"redacted {n} {kind} match(es) from the packet")
        check_size(packet, ctx, int(cfg["limits"]["max_request_chars"]))
    except RequestError as e:
        return fail(EXIT_REFUSED if e.kind in ("context_too_large", "file_refused") else EXIT_USAGE,
                    e.kind, str(e), e.details)

    prompt = render_prompt(packet, caller)
    if dry_run:
        out["status"] = "dry_run"
        out["prompt_preview"] = prompt
        return EXIT_OK, out

    try:
        cmd = procutil.resolve_command(target, sect.get("command") or [])
    except procutil.ExecutableError as e:
        return fail(EXIT_PROVIDER, "missing_executable", str(e))

    budget = Budget(req["task_id"], int(cfg["budget"]["max_consultations_per_task"]))
    b = budget.reserve(req["request_id"])
    out["budget"] = {"used": b["used"], "max": b["max"]}
    if not b["ok"]:
        return fail(EXIT_REFUSED, "budget_exhausted",
                    f"task '{req['task_id']}' already used {b['used']}/{b['max']} consultations. Decide with "
                    "the evidence you have, or ask the user to raise [budget].max_consultations_per_task.")

    work = Path(tempfile.mkdtemp(prefix=f"peer-consult-{req['request_id'][:8]}-"))
    lim = cfg["limits"]
    timeout = float(timeout_override or lim["timeout_seconds"])
    env, notes = _child_env(target, cfg, effort)
    out["warnings"].extend(notes)
    started = time.monotonic()
    launched = False
    try:
        attempt = 0
        while True:
            attempt += 1
            out["attempts"] = attempt
            adviser_cwd = work / "cwd"
            adviser_cwd.mkdir(exist_ok=True)
            stdin_text = prompt
            if target == "codex":
                schema_path = work / "schema.json"
                schema_path.write_text(json.dumps(ADVICE_SCHEMA), encoding="utf-8")
                last_msg = work / f"last-{attempt}.txt"
                argv = CodexAdapter().build(cmd, model=model, effort=effort, workdir=adviser_cwd,
                                            schema_path=schema_path, last_msg_path=last_msg,
                                            disable_skill_paths=_skill_paths_to_disable())
            elif target == "agy":
                schema_path = work / "schema.json"
                schema_path.write_text(json.dumps(ADVICE_SCHEMA), encoding="utf-8")
                try:
                    prepare_agy_workspace(adviser_cwd, sys.executable)
                except ProviderError as e:
                    return fail(EXIT_USAGE, e.kind, str(e))
                argv = AgyAdapter().build(cmd, model=model, effort=effort, schema_path=schema_path,
                                          timeout=timeout - (time.monotonic() - started))
                stdin_text = AgyAdapter.stdin_message(prompt)
            else:
                argv = ClaudeAdapter().build(cmd, model=model, effort=effort,
                                             schema_json=json.dumps(ADVICE_SCHEMA, separators=(",", ":")))
            log(f"consulting {target} (model={model}, effort={effort}, request={req['request_id']}, "
                f"attempt {attempt}, ~{ctx['approx_tokens_estimate']} tokens est.)")
            launched = True
            res = procutil.run(argv, stdin_text=stdin_text, env=env, cwd=str(adviser_cwd),
                               timeout=max(1.0, timeout - (time.monotonic() - started)),
                               max_stdout=int(lim["max_stdout_bytes"]), max_stderr=int(lim["max_stderr_bytes"]),
                               heartbeat=float(lim["heartbeat_seconds"]), label=target)
            if res.stdout_truncated:
                out["warnings"].append("adviser stdout exceeded max_stdout_bytes and was cut; parse may fail")
            if res.timed_out:
                return fail(EXIT_TIMEOUT, "timeout",
                            f"{target} did not finish within {int(timeout)}s; process tree terminated. "
                            "Narrow the question or raise --timeout.")
            try:
                if target == "codex":
                    lm = last_msg.read_text(encoding="utf-8") if last_msg.exists() else None
                    meta = CodexAdapter().parse(res.stdout, res.stderr, res.returncode, lm)
                    out["model"]["reported_source"] = "not exposed by codex exec"
                elif target == "agy":
                    meta = AgyAdapter().parse(res.stdout, res.stderr, res.returncode)
                    out["model"]["reported_source"] = ("not exposed by agy (stream-json init.model only echoes "
                                                       f"--model: {meta.get('init_model')!r})")
                else:
                    meta = ClaudeAdapter().parse(res.stdout, res.stderr, res.returncode, model)
                    out["model"]["reported_all"] = meta.get("reported_models", [])
                    out["model"]["reported_source"] = "claude json result modelUsage keys"
                    out["model"]["reported"] = meta.get("reported_model")
                    rep = meta.get("reported_model")
                    if rep and model.startswith("claude-"):
                        out["model"]["fallback_detected"] = not rep.startswith(model)
                        if out["model"]["fallback_detected"]:
                            out["warnings"].append(
                                f"PROVIDER FALLBACK: requested {model} but usage reports {meta['reported_models']}")
                    elif rep:
                        out["warnings"].append(f"requested model '{model}' is an alias; provider reported {rep}")
                out["usage"] = meta.get("usage")
                out["cost_usd_estimate"] = meta.get("cost_usd_estimate")
                out["model"]["reported"] = meta.get("reported_model") or out["model"]["reported"]
                out["effort"]["observed"] = meta.get("observed_effort")
                out["warnings"].extend(meta.get("warnings", []))
                out["advice"] = meta["advice"]
                out["status"] = "ok"
                return EXIT_OK, out
            except ProviderError as e:
                if e.details:
                    out["warnings"].extend(e.details.get("warnings", []))
                if e.retryable and attempt <= int(lim["transient_retries"]):
                    wait = float(lim["retry_backoff_seconds"])
                    log(f"{target}: transient failure ({e}); retrying once in {int(wait)}s")
                    time.sleep(wait)
                    continue
                return fail(EXIT_PROVIDER, e.kind, str(e), {"stderr_tail": res.stderr[-1500:]}, e.retryable)
    except KeyboardInterrupt:
        return fail(EXIT_CANCELLED, "cancelled", "consultation cancelled; adviser process tree terminated")
    finally:
        out["elapsed_seconds"] = round(time.monotonic() - started, 2)
        if not launched:
            budget.release(req["request_id"])
        shutil.rmtree(work, ignore_errors=True)
