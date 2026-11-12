import _thread
import json
import os
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from peer_consult import procutil  # noqa: E402

FAKE = Path(__file__).with_name("fake_cli.py")
CLI = [sys.executable, "-m", "peer_consult"]

WEIRD_Q = 'Why does "it" fail?\nLine 2: $(rm -rf /) `x` & | > < ; %PATH% !x! ünïcödé ✓ 日本 \'q\''


@pytest.fixture
def env(tmp_path):
    home = tmp_path / "pc-home"
    home.mkdir()
    rec = tmp_path / "rec"
    cfg = home / "config.toml"

    def write_cfg(**limits):
        lim = {"timeout_seconds": 60, "max_request_chars": 200000, "transient_retries": 1,
               "retry_backoff_seconds": 0, "heartbeat_seconds": 1}
        lim.update(limits)
        py, fk = Path(sys.executable).as_posix(), FAKE.as_posix()
        cfg.write_text(
            f'[codex]\ncommand = ["{py}", "{fk}", "codex"]\nmodel = "gpt-6-astra"\neffort = "max"\n'
            f'[claude]\ncommand = ["{py}", "{fk}", "claude"]\nmodel = "claude-fable-5-1"\neffort = "max"\n'
            f'[agy]\ncommand = ["{py}", "{fk}", "agy"]\nmodel = "gemini-4-argon"\neffort = "high"\n'
            f'[limits]\n' + "".join(f"{k} = {v}\n" for k, v in lim.items()) +
            '[budget]\nmax_consultations_per_task = 2\n', encoding="utf-8")

    write_cfg()
    e = {k: v for k, v in os.environ.items() if k not in ("PEER_CONSULT_DEPTH", "FAKE_MODE")}
    e["PYTHONPATH"] = os.pathsep.join(filter(None, [str(ROOT), e.get("PYTHONPATH")]))
    e.update(PEER_CONSULT_HOME=str(home), PEER_CONSULT_CONFIG=str(cfg), FAKE_RECORD_DIR=str(rec),
             FAKE_PIDS=str(tmp_path / "pids.json"), FAKE_STATE=str(tmp_path / "state.txt"))

    class E:
        pass
    o = E()
    o.env, o.home, o.rec, o.tmp, o.write_cfg = e, home, rec, tmp_path, write_cfg

    def ask(target, req, mode="ok", extra=(), env_over=None, timeout=120, caller=None):
        caller = caller or ("codex" if target == "claude" else "claude")
        rf = tmp_path / f"req {time.time_ns()} ü.json"
        rf.write_text(json.dumps(req, ensure_ascii=False), encoding="utf-8")
        ev = dict(e, FAKE_MODE=mode, **(env_over or {}))
        p = subprocess.run([*CLI, "ask", "--caller", caller, "--target", target,
                            "--request-file", str(rf), *extra], capture_output=True, env=ev,
                           cwd=str(tmp_path), timeout=timeout)
        out = json.loads(p.stdout.decode("ascii"))
        return p.returncode, out, p.stderr.decode("utf-8", "replace")

    def records(kind=""):
        if not rec.exists():
            return []
        return [json.loads(f.read_text(encoding="utf-8")) for f in rec.glob(f"{kind}*.json")]
    o.ask, o.records = ask, records
    return o


def req(**kw):
    r = {"task_id": f"t{time.time_ns()}", "question": "What next?", "help_type": "diagnosis"}
    r.update(kw)
    return r


# 1. invocation both directions -------------------------------------------------

def test_claude_to_codex_invocation(env):
    code, out, err = env.ask("codex", req(hypothesis="H1"))
    assert code == 0, out
    assert out["status"] == "ok" and out["advice"]["recommendation"] == "Do Z."
    (r,) = env.records("codex")
    a = r["argv"]
    assert a[0] == "exec" and "--json" in a and a[-1] == "-"
    assert a[a.index("--sandbox") + 1] == "read-only"
    assert a[a.index("--model") + 1] == "gpt-6-astra"
    assert 'model_reasoning_effort="max"' in a and 'approval_policy="never"' in a
    assert 'web_search="disabled"' in a and "agents.enabled=false" in a
    for f in ("shell_tool", "multi_agent", "code_mode_host", "hooks", "plugins", "apps"):
        assert a[a.index(f) - 1] == "--disable"
    assert "--ignore-user-config" in a and "--ephemeral" in a
    assert r["env"]["PEER_CONSULT_DEPTH"] == "1"
    assert "UNVERIFIED HYPOTHESIS" in r["stdin"] and "H1" in r["stdin"]
    assert out["model"] == {"requested": "gpt-6-astra", "reported": None, "reported_all": [],
                            "reported_source": "not exposed by codex exec", "fallback_detected": None}
    assert out["effort"] == {"requested": "max", "observed": None}
    assert out["usage"] == {"input_tokens": 10, "output_tokens": 5}


def test_codex_to_claude_invocation(env):
    code, out, err = env.ask("claude", req())
    assert code == 0, out
    (r,) = env.records("claude")
    a = r["argv"]
    assert a[0] == "-p" and a[a.index("--output-format") + 1] == "json"
    assert a[a.index("--tools") + 1] == ""
    for f in ("--strict-mcp-config", "--safe-mode", "--disable-slash-commands", "--no-session-persistence"):
        assert f in a
    assert "--mcp-config" not in a and "--fallback-model" not in a
    assert "--dangerously-skip-permissions" not in a and "bypassPermissions" not in a
    assert a[a.index("--model") + 1] == "claude-fable-5-1" and a[a.index("--effort") + 1] == "max"
    assert json.loads(a[a.index("--json-schema") + 1])["required"]
    assert r["env"]["PEER_CONSULT_DEPTH"] == "1" and r["env"]["CLAUDE_CODE_EFFORT_LEVEL"] == "max"
    assert out["model"]["reported"] == "claude-fable-5-1" and out["model"]["fallback_detected"] is False
    assert out["cost_usd_estimate"] == 0.12


def test_claude_to_agy_invocation(env):
    code, out, err = env.ask("agy", req(question=WEIRD_Q))
    assert code == 0, out
    assert out["status"] == "ok" and out["advice"]["recommendation"] == "Do Z."
    (r,) = env.records("agy")
    a = r["argv"]
    assert a[a.index("--input-format") + 1] == "stream-json" and a[a.index("--output-format") + 1] == "stream-json"
    assert a[a.index("--model") + 1] == "gemini-4-argon" and a[a.index("--effort") + 1] == "high"
    assert "--sandbox" in a and "--disable-slash-commands" in a and Path(a[a.index("--json-schema") + 1]).name == "schema.json"
    assert "--dangerously-skip-permissions" not in a and "-p" not in a and "--print" not in a
    assert WEIRD_Q not in " ".join(a)
    msg = json.loads(r["stdin"])
    assert msg["event"] == "user"
    body = msg["message"]["content"].split("=== CONSULTATION PACKET (JSON) ===\n", 1)[1]
    assert json.loads(body.split("\n=== END PACKET ===")[0])["question"] == WEIRD_Q
    assert {"hooks.json", "peer_consult_gate.py"} <= set(r["dot_agents"])
    assert r["env"]["PEER_CONSULT_DEPTH"] == "1"
    assert out["model"]["requested"] == "gemini-4-argon" and out["model"]["reported"] is None
    assert "init.model only echoes" in out["model"]["reported_source"]
    assert out["usage"]["total_tokens"] == 18


@pytest.mark.parametrize("caller,target", [("agy", "claude"), ("agy", "codex"), ("codex", "agy")])
def test_other_directions(env, caller, target):
    code, out, _ = env.ask(target, req(), caller=caller)
    assert code == 0 and out["caller"] == caller and out["target"] == target, out
    (r,) = env.records(target)
    assert f'the "parent", {caller})' in (json.loads(r["stdin"])["message"]["content"] if target == "agy" else r["stdin"])


def test_same_agent_direction_refused(env):
    code, out, _ = env.ask("agy", req(), caller="agy")
    assert code == 2 and out["error"]["kind"] == "invalid_direction" and env.records() == []


@pytest.mark.parametrize("mode", ["tool_ran", "tool_left_running"])
def test_agy_tool_execution_discards_advice(env, mode):
    code, out, _ = env.ask("agy", req(), mode=mode)
    assert code == 4 and out["error"]["kind"] == "isolation_breach" and out["advice"] is None


def test_agy_denied_tool_attempt_is_reported(env):
    code, out, _ = env.ask("agy", req(), mode="tool_denied")
    assert code == 0 and any("blocked by the peer-consult gate" in w for w in out["warnings"])


@pytest.mark.parametrize("payload,decision", [
    ({"toolCall": {"name": "finish", "args": {}}}, "allow"),
    ({"toolCall": {"name": "run_command", "args": {"CommandLine": "whoami"}}}, "deny"),
    ({"toolCall": {"name": "read_file"}}, "deny"),
    ("not json", "deny"),
])
def test_agy_gate_script(tmp_path, payload, decision):
    from peer_consult.providers import prepare_agy_workspace
    prepare_agy_workspace(tmp_path, sys.executable)
    hook = json.loads((tmp_path / ".agents" / "hooks.json").read_text())
    (h,) = hook["peer-consult-adviser-lockdown"]["PreToolUse"]
    assert h["matcher"] == "*"
    data = payload if isinstance(payload, str) else json.dumps(payload)
    # run exactly what agy runs: `cmd /c <command>` (or `sh -c`) with cwd = .agents
    shell = ["cmd", "/c", h["hooks"][0]["command"]] if os.name == "nt" else ["sh", "-c", h["hooks"][0]["command"]]
    p = subprocess.run(shell, input=data.encode(), capture_output=True, cwd=str(tmp_path / ".agents"))
    assert p.returncode == 0, p.stderr
    assert json.loads(p.stdout)["decision"] == decision


@pytest.mark.skipif(os.name != "nt", reason="Windows cmd trampoline")
def test_agy_gate_trampoline_quotes_spaced_interpreter(tmp_path):
    from peer_consult.providers import prepare_agy_workspace
    prepare_agy_workspace(tmp_path, r"C:\Program Files\Py 3\python.exe")
    assert json.loads((tmp_path / ".agents" / "hooks.json").read_text())[
        "peer-consult-adviser-lockdown"]["PreToolUse"][0]["hooks"][0]["command"] == r".\peer_consult_gate.cmd"
    assert (tmp_path / ".agents" / "peer_consult_gate.cmd").read_text().startswith(
        r'@"C:\Program Files\Py 3\python.exe" -I "%~dp0peer_consult_gate.py"')


# 2/3. parsing & provider errors ------------------------------------------------

@pytest.mark.parametrize("target,mode,kind", [
    ("codex", "turn_failed", "model_unavailable"),
    ("codex", "no_message", "missing_answer"),
    ("codex", "no_completion", "malformed_output"),
    ("codex", "bad_json", "malformed_output"),
    ("codex", "auth", "auth_error"),
    ("codex", "badflag", "unsupported_flag"),
    ("claude", "credit", "billing_error"),
    ("claude", "not_json", "malformed_output"),
    ("agy", "bad_model", "model_unavailable"),
    ("agy", "prose", "missing_answer"),
])
def test_provider_errors(env, target, mode, kind):
    code, out, _ = env.ask(target, req(), mode=mode)
    assert code == 4 and out["status"] == "error" and out["error"]["kind"] == kind, out
    assert out["advice"] is None


def test_claude_result_fallback_parse_rejects_prose(env):
    code, out, _ = env.ask("claude", req(), mode="no_structured")
    assert out["error"]["kind"] == "missing_answer"


def test_claude_stream_requires_terminal_validated_result():
    from peer_consult.providers import ClaudeAdapter, ProviderError
    adapter = ClaudeAdapter()
    progress = json.dumps({"type": "system", "subtype": "init"}) + "\n"
    result = {"type": "result", "subtype": "success", "is_error": False,
              "structured_output": {"status": "OK"}, "modelUsage": {"claude-opus-5-5": {"outputTokens": 5}}}
    def validate(obj):
        if obj != {"status": "OK"}:
            raise ValueError("bad answer")
        return obj
    parsed = adapter.parse(progress + json.dumps(result), "", 0, "claude-opus-5-5", validator=validate)
    assert parsed["advice"] == {"status": "OK"}
    assert parsed["reported_model"] == "claude-opus-5-5"
    with pytest.raises(ProviderError, match="no terminal"):
        adapter.parse(progress, "", 0, "claude-opus-5-5", validator=validate)
    result.update(is_error=True, subtype="error_during_execution", result="OAuth token expired")
    with pytest.raises(ProviderError) as exc:
        adapter.parse(progress + json.dumps(result), "", 1, "claude-opus-5-5", validator=validate)
    assert exc.value.kind == "auth_error"


def test_transient_retry_is_bounded(env):
    code, out, _ = env.ask("codex", req(), mode="transient_once")
    assert code == 0 and out["attempts"] == 2


# 4. hostile strings and filenames ---------------------------------------------

def test_weird_question_and_filename(env):
    d = env.tmp / "dir with spaces & $(x) ü"
    d.mkdir()
    f = d / ("file 'q' ;%PATH%!x! ✓.py" if os.name == "nt" else "file 'q' \"dq\" ✓.py")
    f.write_text("line1\nsecret_line = 2\nline3 ✓\n", encoding="utf-8")
    code, out, _ = env.ask("codex", req(question=WEIRD_Q, files=[{"path": str(f), "start_line": 2, "end_line": 3}]))
    assert code == 0, out
    (r,) = env.records("codex")
    stdin = r["stdin"]
    packet = json.loads(stdin.split("=== CONSULTATION PACKET (JSON) ===\n", 1)[1].split("\n=== END PACKET ===")[0])
    assert packet["question"] == WEIRD_Q
    assert packet["files"][0]["path"] == str(f.resolve())
    assert "1: line1" not in packet["files"][0]["content"] and "3: line3 ✓" in packet["files"][0]["content"]
    assert WEIRD_Q not in " ".join(r["argv"])  # never on the command line


# 5. recursion -------------------------------------------------------------------

@pytest.mark.parametrize("target", ["codex", "claude", "agy"])
def test_recursion_refused(env, target):
    code, out, _ = env.ask(target, req(), env_over={"PEER_CONSULT_DEPTH": "1"})
    assert code == 3 and out["error"]["kind"] == "recursion_refused"
    assert env.records() == []


# 6. timeout & cancellation clean up the whole tree -------------------------------

def _wait_dead(pids, secs=15):
    end = time.time() + secs
    while time.time() < end and any(procutil.pid_alive(p) for p in pids):
        time.sleep(0.2)
    return [p for p in pids if procutil.pid_alive(p)]


def test_timeout_kills_process_tree(env):
    code, out, _ = env.ask("codex", req(), mode="hang", extra=["--timeout", "4"])
    assert code == 5 and out["error"]["kind"] == "timeout"
    pids = json.loads((env.tmp / "pids.json").read_text())
    assert len(pids) == 2 and _wait_dead(pids) == []


def test_normal_exit_reaps_stragglers(env):
    code, out, _ = env.ask("codex", req(), mode="orphan")
    assert code == 0, out
    assert _wait_dead(json.loads((env.tmp / "pids.json").read_text())) == []


def test_cancellation_kills_process_tree(tmp_path):
    pidfile = tmp_path / "pids.json"
    ev = dict(os.environ, FAKE_MODE="hang", FAKE_PIDS=str(pidfile))
    ev.pop("FAKE_RECORD_DIR", None)

    def interrupt():
        end = time.time() + 20
        while not pidfile.exists() and time.time() < end:
            time.sleep(0.1)
        _thread.interrupt_main()
    threading.Thread(target=interrupt, daemon=True).start()
    with pytest.raises(KeyboardInterrupt):
        procutil.run([sys.executable, str(FAKE), "codex"], stdin_text="", env=ev, cwd=str(tmp_path),
                     timeout=60, max_stdout=1000, max_stderr=1000, heartbeat=100, label="t")
    assert _wait_dead(json.loads(pidfile.read_text())) == []


# 7. oversized context ------------------------------------------------------------

def test_oversized_context_refused_not_truncated(env):
    env.write_cfg(max_request_chars=500)
    code, out, _ = env.ask("codex", req(observations=["x" * 2000]))
    assert code == 3 and out["error"]["kind"] == "context_too_large"
    assert out["error"]["details"]["by_field_chars"]["observations"] > 2000
    assert env.records() == []
    assert out["budget"] is None


def test_sensitive_file_refused(env):
    secret = env.tmp / ".env"
    secret.write_text("API_KEY=abc", encoding="utf-8")
    code, out, _ = env.ask("codex", req(files=[{"path": str(secret)}]))
    assert code == 3 and out["error"]["kind"] == "file_refused" and env.records() == []


def test_inline_secrets_redacted(env):
    code, out, _ = env.ask("codex", req(observations=["token=ghp_" + "a" * 30, "-----BEGIN RSA PRIVATE KEY-----\nabc\n-----END RSA PRIVATE KEY-----"]))
    (r,) = env.records("codex")
    assert "ghp_aaaa" not in r["stdin"] and "BEGIN RSA" not in r["stdin"]
    assert out["context"]["redactions"]


# 8. no silent model substitution -------------------------------------------------

def test_provider_fallback_is_reported(env):
    code, out, _ = env.ask("claude", req(), mode="fallback")
    assert out["model"]["requested"] == "claude-fable-5-1"
    assert out["model"]["reported"] == "claude-other-1" and out["model"]["fallback_detected"] is True
    assert any("PROVIDER FALLBACK" in w for w in out["warnings"])


def test_ultra_and_bad_models_rejected(env):
    code, out, _ = env.ask("codex", req(), extra=["--effort", "ultra"])
    assert code == 2 and "ultra" in out["error"]["message"]
    code, out, _ = env.ask("codex", req(), extra=["--model", "gpt; rm -rf /"])
    assert code == 2
    assert env.records() == []


def test_model_override_used_exactly(env):
    code, out, _ = env.ask("codex", req(), extra=["--model", "gpt-6.1-sol", "--effort", "xhigh"])
    (r,) = env.records("codex")
    assert r["argv"][r["argv"].index("--model") + 1] == "gpt-6.1-sol"
    assert 'model_reasoning_effort="xhigh"' in r["argv"]


# budget -------------------------------------------------------------------------

def test_budget_per_task(env):
    r = req(task_id="budget-task")
    assert env.ask("codex", r)[0] == 0
    assert env.ask("codex", dict(r, follow_up=True, previous_advice="Do Z."))[0] == 0
    code, out, _ = env.ask("codex", r)
    assert code == 3 and out["error"]["kind"] == "budget_exhausted"
    assert len(env.records("codex")) == 2


# 9. concurrency -----------------------------------------------------------------

def test_concurrent_requests_isolated(env):
    with ThreadPoolExecutor(6) as ex:
        results = list(ex.map(lambda i: env.ask("codex" if i % 2 else "claude", req(task_id=f"c{i}")), range(6)))
    assert all(c == 0 for c, _, _ in results), [o for _, o, _ in results]
    recs = env.records()
    assert len(recs) == 6
    cwds = {r["cwd"] for r in recs}
    assert len(cwds) == 6
    assert not any(Path(c).exists() for c in cwds)  # temp workspaces cleaned up


# npm shim resolution ---------------------------------------------------------------

@pytest.mark.skipif(os.name != "nt", reason="Windows batch-shim handling")
def test_cmd_shim_resolution(tmp_path, monkeypatch):
    shim = tmp_path / "codex.cmd"
    shim.write_text("@echo off\r\n")
    monkeypatch.setattr(procutil.shutil, "which", lambda n: str(shim) if n == "codex" else
                        (r"C:\node.exe" if n == "node" else None))
    with pytest.raises(procutil.ExecutableError):
        procutil.resolve_command("codex", [])
    js = tmp_path / "node_modules" / "@openai" / "codex" / "bin" / "codex.js"
    js.parent.mkdir(parents=True)
    js.write_text("")
    assert procutil.resolve_command("codex", []) == [r"C:\node.exe", str(js)]


# 10. installer (`peer-consult setup` / `uninstall`) -------------------------------------
# These run the installed package (`pip install -e .[dev]`): setup probes `python -I -m peer_consult`.

def _clean_env():
    return {k: v for k, v in os.environ.items()
            if k not in ("PEER_CONSULT_HOME", "PEER_CONSULT_CONFIG", "CLAUDE_CONFIG_DIR", "CODEX_HOME", "PEER_CONSULT_DEPTH")}


def _install(home, *extra, cmd="setup"):
    p = subprocess.run([*CLI, cmd, "--home", str(home), *extra], capture_output=True, text=True, env=_clean_env())
    assert p.returncode == 0, p.stdout + p.stderr
    return p.stdout


def test_version_flag():
    from peer_consult import __version__
    for flag in ("--version", "-V"):
        p = subprocess.run([*CLI, flag], capture_output=True, text=True)
        assert p.returncode == 0 and p.stdout.strip() == f"peer-consult {__version__}"


def test_installer_idempotent_and_preserving(tmp_path):
    home = tmp_path / "h"
    (home / ".claude" / "skills" / "other").mkdir(parents=True)
    (home / ".claude" / "skills" / "other" / "SKILL.md").write_text("mine")
    (home / ".agents" / "skills").mkdir(parents=True)
    _install(home)
    ck = home / ".claude" / "skills" / "ask-codex" / "SKILL.md"
    cx = home / ".codex" / "skills" / "ask-claude" / "SKILL.md"
    cfg = home / ".peer-consult" / "config.toml"
    assert ck.exists() and cx.exists() and cfg.exists()
    six = [home / ".claude" / "skills" / "ask-agy", home / ".codex" / "skills" / "ask-agy",
           home / ".gemini" / "config" / "skills" / "ask-claude", home / ".gemini" / "config" / "skills" / "ask-codex"]
    assert all((d / "SKILL.md").exists() for d in six)
    councils = [home / ".claude" / "skills" / "council", home / ".codex" / "skills" / "council",
                home / ".gemini" / "config" / "skills" / "council"]
    assert all((d / "SKILL.md").exists() for d in councils)
    agy_skill = (home / ".gemini" / "config" / "skills" / "ask-codex" / "SKILL.md").read_text(encoding="utf-8")
    assert "--caller agy --target codex" in agy_skill and "name: ask-codex" in agy_skill
    assert f'"{Path(os.path.abspath(sys.executable)).as_posix()}" -I -m peer_consult ask' in agy_skill
    assert "Only the human user can approve" in (councils[0] / "SKILL.md").read_text(encoding="utf-8")
    assert not (home / ".agents" / "skills" / "ask-claude").exists()
    assert "{{" not in ck.read_text(encoding="utf-8") and "peer-consult:managed" in cx.read_text(encoding="utf-8")
    cfg.write_text(cfg.read_text() + "\n# user edit\n")
    out2 = _install(home)
    assert "wrote" not in out2  # nothing rewritten
    assert "# user edit" in cfg.read_text()
    ck.write_text(ck.read_text(encoding="utf-8") + "\nuser note\n", encoding="utf-8")
    out3 = _install(home)
    assert "PRESERVED" in out3 and "user note" in ck.read_text(encoding="utf-8")
    assert ck.with_name("SKILL.md.peer-consult-new").exists()
    assert (home / ".claude" / "skills" / "other" / "SKILL.md").read_text() == "mine"
    out4 = _install(home, "--force")
    assert "backed up" in out4 and "user note" not in ck.read_text(encoding="utf-8")
    assert list(ck.parent.glob("SKILL.md.bak-*"))


def test_installer_dry_run_writes_nothing(tmp_path):
    home = tmp_path / "h"
    home.mkdir()
    out = _install(home, "--dry-run")
    assert "wrote" in out
    assert not any(home.rglob("*"))


def test_installer_does_not_clobber_foreign_skill(tmp_path):
    home = tmp_path / "h"
    foreign = home / ".codex" / "skills" / "ask-claude" / "SKILL.md"
    foreign.parent.mkdir(parents=True)
    foreign.write_text("someone else's skill")
    out = _install(home)
    assert "PRESERVED" in out and foreign.read_text() == "someone else's skill"


def test_installer_migrates_legacy_codex_skill(tmp_path):
    home = tmp_path / "h"
    legacy = home / ".agents" / "skills" / "ask-claude" / "SKILL.md"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("old managed copy")
    root = home / ".peer-consult"
    root.mkdir()
    import hashlib
    (root / "install-manifest.json").write_text(json.dumps({str(legacy): hashlib.sha256(b"old managed copy").hexdigest()}))
    out = _install(home)
    assert "removed" in out and not legacy.parent.exists()
    edited = home / ".agents" / "skills" / "ask-claude" / "SKILL.md"
    edited.parent.mkdir(parents=True)
    edited.write_text("user's own")
    out = _install(home)
    assert "LEFT" in out and edited.read_text() == "user's own"


def test_installer_migrates_pre_package_runtime_and_launchers(tmp_path):
    """Releases before the pip package copied the runtime to ~/.peer-consult/runtime and wrote launchers."""
    import hashlib
    home = tmp_path / "h"
    root = home / ".peer-consult"
    files = {
        root / "runtime" / "peer_consult.py": b"launcher",
        root / "runtime" / "peer_consult" / "cli.py": b"old cli",
        root / "bin" / "peer-consult": b"#!/bin/sh\n",
        home / ".local" / "bin" / "peer-consult.cmd": b"@echo off\r\n",
    }
    edited = root / "runtime" / "peer_consult" / "core.py"
    files[edited] = b"original"
    for f, data in files.items():
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(data)
    (root / "runtime" / "office_dist" / "assets").mkdir(parents=True)
    (root / "runtime" / "office_dist" / "index.html").write_text("<html>")
    (root / "install-manifest.json").write_text(json.dumps({str(f): hashlib.sha256(d).hexdigest() for f, d in files.items()}))
    edited.write_bytes(b"user patched this")
    foreign = home / ".local" / "bin" / "peer-consult"  # not in the manifest: e.g. pipx's own launcher
    foreign.write_bytes(b"not ours")

    out = _install(home)
    assert "superseded by the installed package" in out
    for f in files:
        if f != edited:
            assert not f.exists(), f
    assert edited.read_bytes() == b"user patched this" and "LEFT" in out
    assert not (root / "runtime" / "office_dist").exists()
    assert not (root / "bin").exists()
    assert foreign.read_bytes() == b"not ours"
    manifest = json.loads((root / "install-manifest.json").read_text())
    assert not any("runtime" in k or "bin" in Path(k).parts for k in manifest)  # nothing legacy is tracked any more
    out2 = _install(home)
    assert "LEFT" not in out2 and "removed" not in out2  # reported once, not on every run
    assert edited.read_bytes() == b"user patched this"


def test_uninstall_removes_only_unmodified_managed_files(tmp_path):
    home = tmp_path / "h"
    _install(home)
    ck = home / ".claude" / "skills" / "ask-codex" / "SKILL.md"
    kept = home / ".claude" / "skills" / "ask-agy" / "SKILL.md"
    kept.write_text(kept.read_text(encoding="utf-8") + "\nmine\n", encoding="utf-8")
    other = home / ".claude" / "skills" / "other" / "SKILL.md"
    other.parent.mkdir(parents=True)
    other.write_text("unrelated")
    out = _install(home, cmd="uninstall")
    assert "removed" in out and not ck.parent.exists()
    assert kept.exists() and "LEFT" in out
    assert other.read_text() == "unrelated"
    assert not (home / ".codex" / "skills" / "council").exists()
    assert (home / ".peer-consult" / "config.toml").exists()  # config and history are kept


def test_skill_command_works_from_unrelated_cwd(tmp_path):
    """The exact interpreter invocation rendered into the skills must work from any cwd."""
    home = tmp_path / "h"
    _install(home)
    elsewhere = tmp_path / "unrelated project"
    elsewhere.mkdir()
    (elsewhere / "peer_consult").mkdir()  # a hostile same-named package in cwd must not shadow ours
    (elsewhere / "peer_consult" / "__init__.py").write_text("raise SystemExit('hijacked')")
    ev = dict(_clean_env(), PEER_CONSULT_HOME=str(home / ".peer-consult"))
    p = subprocess.run([sys.executable, "-I", "-m", "peer_consult", "ask", "--caller", "claude", "--target", "codex",
                        "--dry-run"], input=json.dumps({"question": "q?", "help_type": "diagnosis"}).encode(),
                       capture_output=True, cwd=str(elsewhere), env=ev)
    assert p.returncode == 0, p.stderr
    assert json.loads(p.stdout)["status"] == "dry_run"


def test_fallback_interpreter_flags_never_put_cwd_on_sys_path(tmp_path, monkeypatch):
    """`-E` alone would import a planted typer.py from the agent's cwd; the fallback must include -P."""
    from peer_consult import installer

    calls = []

    def fake_run(argv, **kw):
        calls.append(argv)
        ok = "-I" not in argv  # simulate a `pip install --user` that -I cannot see

        class R:
            returncode = 0 if ok else 1
            stdout = f"peer-consult {installer.__version__}" if ok else ""
        return R()

    monkeypatch.setattr(installer.subprocess, "run", fake_run)
    flags = installer.probe_interpreter_flags(sys.executable)
    assert flags == ["-E", "-P"]
    monkeypatch.undo()

    planted = tmp_path / "repo"
    planted.mkdir()
    (planted / "typer.py").write_text("raise SystemExit('HIJACKED from cwd')")
    p = subprocess.run([sys.executable, *flags, "-m", "peer_consult", "--version"], capture_output=True, text=True,
                       cwd=str(planted), env=_clean_env())
    assert p.returncode == 0 and "HIJACKED" not in p.stdout + p.stderr


def test_installer_relative_home_and_rerun_is_quiet(tmp_path):
    rel_home = "rel home"
    p = subprocess.run([*CLI, "setup", "--home", rel_home], capture_output=True, text=True, env=_clean_env(), cwd=str(tmp_path))
    assert p.returncode == 0, p.stdout + p.stderr
    manifest = json.loads((tmp_path / rel_home / ".peer-consult" / "install-manifest.json").read_text())
    assert manifest and all(os.path.isabs(k) for k in manifest)
    p2 = subprocess.run([*CLI, "setup", "--home", rel_home], capture_output=True, text=True, env=_clean_env(), cwd=str(tmp_path))
    assert p2.returncode == 0 and "wrote" not in p2.stdout and "LEFT" not in p2.stdout


def test_office_token_file_is_private(tmp_path):
    from peer_consult.office_server import load_or_create_office_token

    state = tmp_path / "state"
    t1 = load_or_create_office_token(state)
    t2 = load_or_create_office_token(state)
    assert t1 == t2 and len(t1) >= 16
    if os.name != "nt":
        assert ((state / "office-token").stat().st_mode & 0o777) == 0o600
        assert (state.stat().st_mode & 0o777) == 0o700
