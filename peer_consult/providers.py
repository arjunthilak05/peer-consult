"""Provider adapters: build the restricted adviser invocation and parse each CLI's output.

Success requires more than exit code 0 or non-empty stdout: each adapter checks the
provider's own terminal/error signals and that a schema-valid answer is present.
"""
from __future__ import annotations

import json
import os
import re
import shlex
from collections.abc import Callable
from pathlib import Path
from typing import Any

ADVICE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "assessment": {"type": "string"},
        "recommendation": {"type": "string"},
        "alternatives": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {"option": {"type": "string"}, "tradeoffs": {"type": "string"}},
                "required": ["option", "tradeoffs"],
            },
        },
        "risks": {"type": "array", "items": {"type": "string"}},
        "verification_steps": {"type": "array", "items": {"type": "string"}},
        "missing_context": {"type": "array", "items": {"type": "string"}},
        "proposed_code": {"type": "string"},
        "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
    },
    "required": ["assessment", "recommendation", "alternatives", "risks",
                 "verification_steps", "missing_context", "proposed_code", "confidence"],
}

# Features switched off for the Codex adviser. Shell/exec, subagents, code-mode
# host (which nests apply_patch/MCP tools), hooks, plugins, apps, memories,
# browser/computer use, goals, image generation. Verified empirically against
# codex-cli 0.164.0; `doctor` checks each name still exists in `codex features list`.
CODEX_DISABLED_FEATURES = (
    "shell_tool", "unified_exec", "multi_agent", "multi_agent_v2", "code_mode_host",
    "goals", "sleep_tool", "hooks", "plugins", "apps", "memories", "browser_use",
    "computer_use", "image_generation", "tool_suggest", "skill_mcp_dependency_install",
)

CLAUDE_SYSTEM_PROMPT = (
    "You are a read-only technical adviser answering a single consultation from another AI "
    "coding agent. You have no tools. Follow the instructions in the user message exactly and "
    "return only the requested structured output."
)

CLAUDE_WRITER_SYSTEM_PROMPT = (
    "You are the single authorized writer agent executing an approved council implementation plan "
    "inside an isolated Git worktree. Modify only files within the authorized scope, never touch "
    "credentials or git/hook metadata, and return the requested structured summary."
)


class ProviderError(Exception):
    def __init__(self, kind: str, message: str, retryable: bool = False, details: dict | None = None):
        super().__init__(message)
        self.kind = kind
        self.retryable = retryable
        self.details = details or {}


_CLASSIFIERS = [
    ("billing_error", False, re.compile(r"credit balance|insufficient[_ ]quota|billing", re.I)),
    ("model_unavailable", False, re.compile(
        r"model[^\n]{0,80}(not found|not supported|does not exist|unavailable|not available|invalid|no access|"
        r"isn't supported|is not supported)|unknown model|invalid model|model_not_found", re.I)),
    ("auth_error", False, re.compile(
        r"not logged in|please (log ?in|run .*login)|unauthori[sz]ed|\b401\b|invalid api key|"
        r"authentication|oauth token|login required|invalid x-api-key", re.I)),
    ("permission_denied", False, re.compile(r"\b403\b|forbidden|permission denied|not permitted by", re.I)),
    ("unsupported_flag", False, re.compile(
        r"unexpected argument|unknown option|unrecognized (option|argument)|invalid value .* for '--|"
        r"error: unknown|found argument .* which wasn't expected", re.I)),
    ("rate_limited", False, re.compile(r"usage limit|rate[ _-]?limit|\b429\b|too many requests|quota", re.I)),
    ("transient", True, re.compile(
        r"overloaded|\b5\d\d\b|service unavailable|internal server error|bad gateway|gateway timeout|"
        r"connection (reset|refused|closed)|econnreset|timed out|stream disconnected|temporarily", re.I)),
]


def classify(text: str, default: str = "provider_error") -> tuple[str, bool]:
    for kind, retryable, rx in _CLASSIFIERS:
        if rx.search(text or ""):
            return kind, retryable
    return default, False


def _tail(s: str, n: int = 1500) -> str:
    s = (s or "").strip()
    return s if len(s) <= n else "..." + s[-n:]


def validate_advice(obj) -> dict:
    if not isinstance(obj, dict):
        raise ProviderError("malformed_output", "adviser answer is not a JSON object")
    missing = [k for k in ADVICE_SCHEMA["required"] if k not in obj]
    if missing:
        raise ProviderError("malformed_output", f"adviser answer missing fields: {missing}")
    for k in ("assessment", "recommendation", "proposed_code"):
        if not isinstance(obj[k], str):
            raise ProviderError("malformed_output", f"field '{k}' is not a string")
    for k in ("risks", "verification_steps", "missing_context"):
        if not isinstance(obj[k], list) or not all(isinstance(x, str) for x in obj[k]):
            raise ProviderError("malformed_output", f"field '{k}' is not a list of strings")
    if not isinstance(obj["alternatives"], list) or not all(
            isinstance(a, dict) and isinstance(a.get("option"), str) for a in obj["alternatives"]):
        raise ProviderError("malformed_output", "field 'alternatives' is malformed")
    if obj["confidence"] not in ("low", "medium", "high"):
        raise ProviderError("malformed_output", "field 'confidence' is invalid")
    if not obj["assessment"].strip() and not obj["recommendation"].strip():
        raise ProviderError("malformed_output", "adviser returned an empty answer")
    return {k: obj[k] for k in ADVICE_SCHEMA["required"]}


# ---------------------------------------------------------------- Codex

class CodexAdapter:
    name = "codex"

    def build(self, cmd: list[str], *, model: str, effort: str, workdir: Path, schema_path: Path,
              last_msg_path: Path, disable_skill_paths: list[Path]) -> list[str]:
        argv = [*cmd, "exec", "--json",
                "--ignore-user-config",      # no user MCP servers, plugins, notify hooks, profiles
                "--ignore-rules", "--ephemeral", "--skip-git-repo-check",
                "--sandbox", "read-only",
                "--cd", str(workdir),
                "--model", model,
                "-c", f'model_reasoning_effort="{effort}"',
                "-c", 'approval_policy="never"',   # unavailable actions fail instead of waiting
                "-c", 'web_search="disabled"',
                "-c", "agents.enabled=false",
                "-c", 'shell_environment_policy.inherit="core"']
        if disable_skill_paths:
            entries = ", ".join(f"{{path = '{p}', enabled = false}}" for p in disable_skill_paths)
            argv += ["-c", f"skills.config=[{entries}]"]
        for feat in CODEX_DISABLED_FEATURES:
            argv += ["--disable", feat]
        argv += ["--output-schema", str(schema_path), "--output-last-message", str(last_msg_path), "-"]
        return argv

    def build_writer(self, cmd: list[str], *, model: str, effort: str, workdir: Path, schema_path: Path,
                     last_msg_path: Path, disable_skill_paths: list[Path],
                     read_only_patch_mode: bool = True) -> list[str]:
        """Build Codex single-writer invocation scoped to the dedicated Git worktree.

        On Windows where Codex's ``workspace-write`` sandbox SID setup can fail,
        ``read_only_patch_mode=True`` runs with ``--sandbox read-only`` and the writer
        emits structured ``file_patches`` applied by ``WorktreeSandbox``.
        """
        sandbox_mode = "read-only" if read_only_patch_mode else "workspace-write"
        argv = [*cmd, "exec", "--json",
                "--ignore-user-config",
                "--ignore-rules", "--ephemeral",
                "--sandbox", sandbox_mode,
                "--cd", str(workdir),
                "--model", model,
                "-c", f'model_reasoning_effort="{effort}"',
                "-c", 'approval_policy="never"',
                "-c", 'web_search="disabled"',
                "-c", "agents.enabled=false",
                "-c", 'shell_environment_policy.inherit="core"']
        if disable_skill_paths:
            entries = ", ".join(f"{{path = '{p}', enabled = false}}" for p in disable_skill_paths)
            argv += ["-c", f"skills.config=[{entries}]"]
        for feat in CODEX_DISABLED_FEATURES:
            argv += ["--disable", feat]
        argv += ["--output-schema", str(schema_path), "--output-last-message", str(last_msg_path), "-"]
        return argv

    def parse(self, stdout: str, stderr: str, returncode: int | None, last_msg: str | None,
              *, validator: Callable[[Any], dict] = validate_advice) -> dict:
        events, bad_lines = [], 0
        for line in stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                bad_lines += 1
        warnings: list[str] = []
        if bad_lines:
            warnings.append(f"{bad_lines} non-JSON stdout line(s) ignored")
        thread_id = usage = None
        final_text = None
        failed_msg = None
        error_events: list[str] = []
        tool_events: list[str] = []
        completed = False
        for ev in events:
            t = ev.get("type")
            if t == "thread.started":
                thread_id = ev.get("thread_id")
            elif t == "turn.completed":
                completed = True
                usage = ev.get("usage")
            elif t == "turn.failed":
                err = ev.get("error") or {}
                failed_msg = err.get("message") if isinstance(err, dict) else str(err)
            elif t == "error":
                error_events.append(str(ev.get("message")))
            elif t == "item.completed":
                item = ev.get("item") or {}
                itype = item.get("type")
                if itype == "agent_message":
                    final_text = item.get("text")
                elif itype == "error":
                    warnings.append(f"codex notice: {item.get('message')}")
                elif itype not in (None, "reasoning"):
                    tool_events.append(str(itype))
        meta = {"thread_id": thread_id, "usage": usage, "warnings": warnings, "tool_events": tool_events}
        if failed_msg or (not completed and error_events):
            msg = failed_msg or error_events[-1]
            kind, retry = classify(msg)
            raise ProviderError(kind, f"codex turn failed: {msg}", retry, meta)
        if returncode != 0:
            text = "\n".join(error_events) + "\n" + stderr
            kind, retry = classify(text)
            raise ProviderError(kind, f"codex exited with code {returncode}: {_tail(text)}", retry, meta)
        if not completed:
            raise ProviderError("malformed_output", "codex produced no turn.completed event", False, meta)
        if error_events:
            warnings.extend(f"codex error event (turn still completed): {m}" for m in error_events)
        text = last_msg if (last_msg and last_msg.strip()) else final_text
        if not text or not text.strip():
            raise ProviderError("missing_answer", "codex completed without a final agent message", False, meta)
        try:
            obj = json.loads(text)
        except json.JSONDecodeError:
            raise ProviderError("malformed_output", f"final message is not JSON: {_tail(text, 500)}", False, meta)
        meta["advice"] = validator(obj)
        meta["reported_model"] = None   # codex exec does not expose the serving model
        meta["observed_effort"] = None  # nor the applied reasoning effort
        meta["cost_usd_estimate"] = None
        return meta


# ---------------------------------------------------------------- Claude

class ClaudeAdapter:
    name = "claude"

    def build(self, cmd: list[str], *, model: str, effort: str, schema_json: str,
              system_prompt: str = CLAUDE_SYSTEM_PROMPT, stream: bool = False) -> list[str]:
        argv = [*cmd, "-p",
                "--output-format", "json",
                "--model", model,
                "--effort", effort,
                "--tools", "",                 # no built-in tools at all
                "--strict-mcp-config",         # and no MCP servers (none passed via --mcp-config)
                "--safe-mode",                 # no CLAUDE.md, skills, plugins, hooks, custom agents
                "--disable-slash-commands",
                "--no-session-persistence",
                "--permission-mode", "dontAsk",
                "--permission-prompts", "none",
                "--max-turns", "4",
                "--system-prompt", system_prompt,
                "--json-schema", schema_json]
        if stream:
            argv[argv.index("--output-format") + 1] = "stream-json"
            argv.extend(["--verbose", "--include-partial-messages"])
        return argv

    def build_writer(self, cmd: list[str], *, model: str, effort: str, schema_json: str,
                     system_prompt: str = CLAUDE_WRITER_SYSTEM_PROMPT) -> list[str]:
        """Build bounded Claude single-writer invocation with only file tools enabled (no shell/MCP)."""
        return [*cmd, "-p",
                "--output-format", "json",
                "--model", model,
                "--effort", effort,
                "--tools", "Read,Edit,Write,Grep,Glob",
                "--strict-mcp-config",
                "--safe-mode",
                "--disable-slash-commands",
                "--no-session-persistence",
                "--permission-mode", "acceptEdits",
                "--permission-prompts", "none",
                "--max-turns", "12",
                "--system-prompt", system_prompt,
                "--json-schema", schema_json]

    def parse(self, stdout: str, stderr: str, returncode: int | None, requested_model: str,
              *, validator: Callable[[Any], dict] = validate_advice) -> dict:
        try:
            d = json.loads(stdout)
        except json.JSONDecodeError:
            # Council calls stream progress as NDJSON; only the terminal result
            # establishes success. Keep single-result JSON support for ask/writer.
            d = None
            errors = []
            for line in stdout.splitlines():
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(event, dict):
                    continue
                if event.get("type") == "result":
                    d = event
                elif event.get("type") == "error":
                    errors.append(str(event.get("error") or event.get("message") or ""))
            if d is None:
                text = "\n".join(errors) + "\n" + stderr
                kind, retry = classify(text, "malformed_output")
                raise ProviderError(kind, f"claude returned no terminal JSON result (exit {returncode}): {_tail(text)}", retry)
        if not isinstance(d, dict) or d.get("type") != "result":
            raise ProviderError("malformed_output", "claude returned no terminal JSON result object")
        model_usage = d.get("modelUsage") or {}
        reported = sorted(model_usage, key=lambda m: -(model_usage[m] or {}).get("outputTokens", 0))
        warnings: list[str] = []
        meta = {
            "session_id": d.get("session_id"),
            "usage": d.get("usage"),
            "num_turns": d.get("num_turns"),
            "reported_models": reported,
            "reported_model": reported[0] if reported else None,
            "observed_effort": None,  # not present in the json result
            "cost_usd_estimate": d.get("total_cost_usd") if model_usage else None,
            "warnings": warnings,
        }
        if d.get("is_error") or d.get("subtype") != "success" or returncode != 0:
            msg = str(d.get("result") or d.get("subtype") or "")
            status = d.get("api_error_status")
            kind, retry = classify(f"{msg} {status or ''} {stderr}")
            if d.get("subtype") == "error_max_turns":
                kind, retry = "max_turns", False
            raise ProviderError(kind, f"claude reported an error (subtype={d.get('subtype')}, "
                                      f"api_error_status={status}, exit={returncode}): {_tail(msg, 800)}", retry, meta)
        obj = d.get("structured_output")
        if obj is None:
            res = d.get("result")
            if isinstance(res, str):
                try:
                    obj = json.loads(res)
                    warnings.append("structured_output missing; parsed JSON from 'result' instead")
                except json.JSONDecodeError:
                    obj = None
        if obj is None:
            raise ProviderError("missing_answer", "claude returned no structured_output", False, meta)
        meta["advice"] = validator(obj)
        return meta


# ---------------------------------------------------------------- Antigravity (agy)

# agy has no flag that removes tools. Workspace hooks are discovered from `.agents/` in
# the session cwd, so the adviser's empty temp cwd gets a PreToolUse hook that denies
# every tool except `finish` (the tool agy uses to return --json-schema output). The
# gate defaults to deny, and agy fails the tool call if the hook itself errors.
AGY_GATE_SCRIPT = '''\
import json, sys
decision = {"decision": "deny", "reason": "peer-consult adviser: tools are disabled; answer from the packet only"}
try:
    payload = json.loads(sys.stdin.read())
    call = payload.get("toolCall") if isinstance(payload, dict) else None
    if isinstance(call, dict) and call.get("name") == "finish":
        decision = {"decision": "allow"}
except Exception:
    pass
finally:
    sys.stdout.write(json.dumps(decision))
'''

AGY_WRITER_GATE_SCRIPT = '''\
import fnmatch, json, os, sys
from pathlib import Path

decision = {"decision": "deny", "reason": "peer-consult writer gate: tool or path not authorized"}
try:
    cfg = json.loads(Path(__file__).with_name("writer_scope.json").read_text(encoding="utf-8"))
    root = Path(cfg["worktree"]).resolve()
    auth = cfg.get("authorized_files") or []
    forb = cfg.get("forbidden_paths") or []
    payload = json.loads(sys.stdin.read())
    call = payload.get("toolCall") if isinstance(payload, dict) else None
    name = call.get("name") if isinstance(call, dict) else None
    args = (call.get("args") or call.get("parameters") or {}) if isinstance(call, dict) else {}
    if name == "finish":
        decision = {"decision": "allow"}
    elif name in ("read_file", "edit_file", "write_file"):
        raw_p = args.get("Path") or args.get("path") or ""
        if raw_p:
            p = Path(raw_p)
            if not p.is_absolute():
                p = root / p
            p = p.resolve()
            rel = p.relative_to(root).as_posix()
            parts = {pt.lower() for pt in p.parts}
            bad_dirs = {".git", ".agents", ".claude", ".codex", ".gemini", ".ssh", ".aws"}
            is_forb = any(fnmatch.fnmatch(rel, pat) for pat in forb) or bool(parts & bad_dirs) or p.name.lower().startswith(".env")
            if not is_forb:
                if name == "read_file":
                    decision = {"decision": "allow"}
                elif not auth or any(fnmatch.fnmatch(rel, pat) or rel == pat for pat in auth):
                    decision = {"decision": "allow"}
except Exception:
    pass
finally:
    sys.stdout.write(json.dumps(decision))
'''

AGY_ALLOWED_TOOLS = ("finish",)
AGY_WRITER_ALLOWED_TOOLS = ("finish", "read_file", "edit_file", "write_file")


def prepare_agy_workspace(cwd: Path, python: str) -> None:
    dot = cwd / ".agents"
    dot.mkdir(parents=True, exist_ok=True)
    (dot / "peer_consult_gate.py").write_text(AGY_GATE_SCRIPT, encoding="utf-8")
    if os.name == "nt":
        # The hook runs as `cmd /c <command>` with cwd = .agents, and cmd mangles a quoted
        # interpreter path, so the command is a bare trampoline name that quotes it itself.
        if any(c in python for c in '"%\r\n'):
            raise ProviderError("config_error", f"cannot build an agy hook trampoline for interpreter path {python!r}")
        (dot / "peer_consult_gate.cmd").write_text(f'@"{python}" -I "%~dp0peer_consult_gate.py"\r\n', encoding="utf-8")
        command = r".\peer_consult_gate.cmd"  # explicit: cmd skips cwd under NoDefaultCurrentDirectoryInExePath
    else:
        command = f"{shlex.quote(python)} -I peer_consult_gate.py"
    hook = {"peer-consult-adviser-lockdown": {"PreToolUse": [{"matcher": "*", "hooks": [
        {"type": "command", "command": command, "timeout": 30}]}]}}
    (dot / "hooks.json").write_text(json.dumps(hook), encoding="utf-8")


def prepare_agy_writer_workspace(cwd: Path, python: str, authorized_files: list[str], forbidden_paths: list[str]) -> None:
    dot = cwd / ".agents"
    dot.mkdir(parents=True, exist_ok=True)
    (dot / "peer_consult_gate.py").write_text(AGY_WRITER_GATE_SCRIPT, encoding="utf-8")
    (dot / "writer_scope.json").write_text(
        json.dumps({"worktree": str(cwd.resolve()), "authorized_files": authorized_files, "forbidden_paths": forbidden_paths}),
        encoding="utf-8",
    )
    if os.name == "nt":
        if any(c in python for c in '"%\r\n'):
            raise ProviderError("config_error", f"cannot build an agy hook trampoline for interpreter path {python!r}")
        (dot / "peer_consult_gate.cmd").write_text(f'@"{python}" -I "%~dp0peer_consult_gate.py"\r\n', encoding="utf-8")
        command = r".\peer_consult_gate.cmd"
    else:
        command = f"{shlex.quote(python)} -I peer_consult_gate.py"
    hook = {"peer-consult-writer-lockdown": {"PreToolUse": [{"matcher": "*", "hooks": [
        {"type": "command", "command": command, "timeout": 30}]}]}}
    (dot / "hooks.json").write_text(json.dumps(hook), encoding="utf-8")


class AgyAdapter:
    name = "agy"

    def build(self, cmd: list[str], *, model: str, effort: str, schema_path: Path, timeout: float) -> list[str]:
        return [*cmd,
                "--input-format", "stream-json",    # prompt on stdin, never on the command line
                "--output-format", "stream-json",
                "--model", model,
                "--effort", effort,
                "--sandbox",                        # terminal sandbox as a second layer behind the hook
                "--disable-slash-commands",
                "--json-schema", str(schema_path),
                "--print-timeout", f"{max(1, int(timeout))}s"]

    def build_writer(self, cmd: list[str], *, model: str, effort: str, schema_path: Path, timeout: float) -> list[str]:
        return [*cmd,
                "--input-format", "stream-json",
                "--output-format", "stream-json",
                "--mode", "accept-edits",
                "--model", model,
                "--effort", effort,
                "--sandbox",
                "--disable-slash-commands",
                "--json-schema", str(schema_path),
                "--print-timeout", f"{max(1, int(timeout))}s"]

    @staticmethod
    def stdin_message(prompt: str) -> str:
        return json.dumps({"event": "user", "message": {"content": prompt}}, ensure_ascii=False) + "\n"

    def parse(self, stdout: str, stderr: str, returncode: int | None,
              *, validator: Callable[[Any], dict] = validate_advice,
              allowed_tools: tuple[str, ...] = AGY_ALLOWED_TOOLS) -> dict:
        events, bad_lines = [], 0
        for line in stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                bad_lines += 1
        warnings: list[str] = []
        if bad_lines:
            warnings.append(f"{bad_lines} non-JSON stdout line(s) ignored")
        init_model = result = None
        # last observed state of every non-allowed tool step; anything but ERROR (denied)
        # means the step ran or was still running when the turn ended
        tool_steps: dict = {}
        allowed_steps: list[str] = []
        for ev in events:
            kind = ev.get("event")
            if kind == "init":
                init_model = (ev.get("init") or {}).get("model")
            elif kind == "result":
                result = ev.get("result") or {}
            elif kind == "step_update":
                st = ev.get("step_update") or {}
                name = st.get("tool_name")
                if st.get("step_type") == "tool" or name:
                    if name not in allowed_tools:
                        tool_steps[st.get("step_index", len(tool_steps))] = (str(name), st.get("state"))
                    elif name != "finish":
                        allowed_steps.append(str(name))
        ran_tools = [n for n, state in tool_steps.values() if state != "ERROR"]
        denied = [n for n, state in tool_steps.values() if state == "ERROR"]
        meta = {"conversation_id": (result or {}).get("conversation_id"), "usage": (result or {}).get("usage"),
                "num_turns": (result or {}).get("num_turns"), "init_model": init_model,
                "reported_model": None,   # init.model only echoes --model; the serving model is not exposed
                "observed_effort": None, "cost_usd_estimate": None, "warnings": warnings,
                "allowed_tools_used": sorted(set(allowed_steps))}
        if denied:
            warnings.append(f"adviser attempted tool(s) {sorted(set(denied))}; blocked by the peer-consult gate")
        if ran_tools:
            raise ProviderError("isolation_breach", f"agy adviser completed tool call(s) {sorted(set(ran_tools))} "
                                "despite the deny-all gate; advice discarded", False, meta)
        if result is None:
            text = stderr + "\n" + stdout[-1500:]
            kind, retry = classify(text, "malformed_output")
            raise ProviderError(kind, f"agy produced no result event (exit {returncode}): {_tail(text)}", retry, meta)
        status = result.get("status")
        if status != "SUCCESS" or returncode != 0:
            msg = str(result.get("error") or "") + "\n" + stderr
            kind, retry = classify(msg)
            raise ProviderError(kind, f"agy reported status={status} (exit {returncode}): {_tail(msg, 800)}", retry, meta)
        if result.get("denied_actions"):
            warnings.append(f"agy denied actions: {result['denied_actions']}")
        obj = result.get("structured_output")
        if obj is None:
            text = result.get("response")
            if isinstance(text, str) and text.strip():
                try:
                    obj = json.loads(text)
                    warnings.append("structured_output missing; parsed JSON from 'response' instead")
                except json.JSONDecodeError:
                    obj = None
        if obj is None:
            raise ProviderError("missing_answer", "agy returned no structured_output", False, meta)
        meta["advice"] = validator(obj)
        return meta
