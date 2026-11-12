"""`peer-consult doctor`: environment, executables, auth, model catalog, restrictions, skills, council store."""
from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
from pathlib import Path

from . import procutil
from .config import config_path
from .core import DEPTH_VAR, codex_home, current_depth
from .providers import CODEX_DISABLED_FEATURES
from .state import CouncilStore


def _run(argv, timeout=60, env=None):
    try:
        p = subprocess.run(argv, capture_output=True, timeout=timeout, shell=False, env=env)
        return p.returncode, p.stdout.decode("utf-8", "replace"), p.stderr.decode("utf-8", "replace")
    except (OSError, subprocess.TimeoutExpired) as e:
        return None, "", str(e)


def doctor(cfg: dict, live: bool = False) -> tuple[int, dict]:
    rep: dict = {
        "platform": {"os": platform.platform(), "python": sys.executable, "python_version": platform.python_version(),
                     "wsl": bool(os.environ.get("WSL_DISTRO_NAME")), "shell": os.environ.get("SHELL") or os.environ.get("ComSpec")},
        "config": {"path": str(config_path()), "exists": cfg["_exists"],
                   "codex": {k: cfg["codex"][k] for k in ("model", "effort", "command")},
                   "claude": {k: cfg["claude"][k] for k in ("model", "effort", "auth", "command")},
                   "agy": {k: cfg["agy"][k] for k in ("model", "effort", "command")},
                   "limits": cfg["limits"], "budget": cfg["budget"],
                   "council": cfg.get("council"), "execute": cfg.get("execute"), "office": cfg.get("office")},
        "recursion": {"env_var": DEPTH_VAR, "current_depth": current_depth(),
                      "would_refuse_ask": current_depth() >= 1},
        "checks": [],
    }
    problems = 0

    def check(name, ok, detail):
        nonlocal problems
        rep["checks"].append({"name": name, "ok": ok, "detail": detail})
        if ok is False:
            problems += 1

    cmds = {}
    for name in ("codex", "claude", "agy"):
        try:
            cmds[name] = procutil.resolve_command(name, cfg[name].get("command") or [])
            rc, so, se = _run([*cmds[name], "--version"])
            check(f"{name}: executable", rc == 0, {"argv_prefix": cmds[name], "version": (so or se).strip()})
        except procutil.ExecutableError as e:
            check(f"{name}: executable", False, str(e))

    if "codex" in cmds:
        rc, so, se = _run([*cmds["codex"], "login", "status"])
        text = (so + se).strip()
        check("codex: auth (codex login status)", rc == 0 and "logged in" in text.lower(), text.splitlines()[-1:] if text else text)
        rc, so, se = _run([*cmds["codex"], "debug", "models"], timeout=90)
        model, effort = cfg["codex"]["model"], cfg["codex"]["effort"]
        try:
            models = json.loads(so).get("models", [])
            entry = next((m for m in models if m.get("slug") == model), None)
            efforts = [e.get("effort") for e in (entry or {}).get("supported_reasoning_levels", [])]
            listed = sorted((m.get("priority", 999), m["slug"]) for m in models if m.get("visibility") == "list")
            check("codex: model in catalog (catalog is NOT proof of account access)", entry is not None,
                  {"model": model, "catalog_efforts": efforts, "listed_models_by_priority": [s for _, s in listed][:8]})
            check("codex: effort supported by catalog entry", effort in efforts, {"effort": effort})
        except (json.JSONDecodeError, AttributeError) as e:
            check("codex: model catalog", None, f"could not read `codex debug models`: {e}")
        rc, so, se = _run([*cmds["codex"], "features", "list"])
        known = {ln.split()[0] for ln in so.splitlines() if ln.strip()}
        missing = [f for f in CODEX_DISABLED_FEATURES if f not in known]
        check("codex: restriction feature flags exist in this version", rc == 0 and not missing,
              {"missing": missing} if missing else "all present")

    if "claude" in cmds:
        rc, so, se = _run([*cmds["claude"], "auth", "status"])
        try:
            st = json.loads(so)
            safe = {k: st.get(k) for k in ("loggedIn", "authMethod", "apiProvider", "subscriptionType")}
        except json.JSONDecodeError:
            safe = {"raw": (so + se).strip()[:200]}
        check("claude: auth (claude auth status, as inherited)", bool(safe.get("loggedIn")), safe)
        if os.environ.get("ANTHROPIC_API_KEY"):
            env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
            rc, so, se = _run([*cmds["claude"], "auth", "status"], env=env)
            try:
                st2 = json.loads(so)
                sub = {k: st2.get(k) for k in ("loggedIn", "authMethod", "subscriptionType")}
            except json.JSONDecodeError:
                sub = None
            check("claude: ANTHROPIC_API_KEY present in environment", None, {
                "note": "In -p mode the API key always wins over a subscription login.",
                "configured_auth_mode": cfg["claude"]["auth"],
                "subscription_login_without_key": sub})
        rc, so, se = _run([*cmds["claude"], "--help"])
        needed = ["--tools", "--strict-mcp-config", "--safe-mode", "--disable-slash-commands",
                  "--no-session-persistence", "--json-schema", "--effort", "--permission-prompts"]
        miss = [f for f in needed if f not in so]
        check("claude: restriction flags in --help", not miss, {"missing": miss} if miss else "all present")

    if "agy" in cmds:
        # `agy models` needs a signed-in account, so success doubles as the auth check.
        rc, so, se = _run([*cmds["agy"], "models"], timeout=90)
        ids = [ln.split("	")[0].strip() for ln in so.splitlines() if "	" in ln]
        model, effort = cfg["agy"]["model"], cfg["agy"]["effort"]
        efforts = [i[len(model) + 1:] for i in ids if i.startswith(model + "-")]
        check("agy: auth + model list (agy models; a listing is NOT proof the request will be served)",
              rc == 0 and bool(ids), {"models": ids[:20]} if ids else (so + se).strip()[-300:])
        check("agy: configured model/effort listed", model in ids or effort in efforts,
              {"model": model, "effort": effort, "listed_efforts_for_model": efforts})
        rc, so, se = _run([*cmds["agy"], "--help"])
        text = so + se
        needed = ["--input-format", "--output-format", "--json-schema", "--effort", "--sandbox",
                  "--disable-slash-commands", "--print-timeout"]
        miss = [f for f in needed if f not in text]
        check("agy: adviser flags in --help", not miss, {"missing": miss} if miss else "all present")

    # Council infrastructure checks
    rc_git, so_git, se_git = _run(["git", "--version"])
    check("council: git worktree support", rc_git == 0, (so_git or se_git).strip())
    try:
        store = CouncilStore()
        check("council: SQLite WAL state store", store.db_path.exists(), str(store.db_path))
    except Exception as e:
        check("council: SQLite WAL state store", False, str(e))

    claude_dir = Path(os.environ["CLAUDE_CONFIG_DIR"]) if os.environ.get("CLAUDE_CONFIG_DIR") else Path.home() / ".claude"
    agy_dir = Path.home() / ".gemini" / "config"
    skills = {
        "claude ask-codex": claude_dir / "skills" / "ask-codex" / "SKILL.md",
        "claude ask-agy": claude_dir / "skills" / "ask-agy" / "SKILL.md",
        "codex ask-claude": codex_home() / "skills" / "ask-claude" / "SKILL.md",
        "codex ask-agy": codex_home() / "skills" / "ask-agy" / "SKILL.md",
        "agy ask-claude": agy_dir / "skills" / "ask-claude" / "SKILL.md",
        "agy ask-codex": agy_dir / "skills" / "ask-codex" / "SKILL.md",
    }
    for label, p in skills.items():
        ok = p.exists() and "peer-consult:managed" in p.read_text(encoding="utf-8", errors="replace")
        check(f"skill installed: {label}", ok, str(p))

    council_skills = {
        "claude council": claude_dir / "skills" / "council" / "SKILL.md",
        "codex council": codex_home() / "skills" / "council" / "SKILL.md",
        "agy council": agy_dir / "skills" / "council" / "SKILL.md",
    }
    for label, p in council_skills.items():
        if p.exists():
            ok = "peer-consult:managed" in p.read_text(encoding="utf-8", errors="replace")
            check(f"skill installed: {label}", ok, str(p))

    old = Path.home() / ".agents" / "skills" / "ask-claude" / "SKILL.md"
    if old.exists():
        check("no ask-claude in ~/.agents/skills (agy also reads it there, as a workspace skill, under the home dir)",
              False, f"{old} exists; Codex skills now live in {codex_home() / 'skills'}. Remove it if it is ours.")
    if os.environ.get("CLAUDE_CONFIG_DIR"):
        check("claude: CLAUDE_CONFIG_DIR override", None, f"set to {os.environ['CLAUDE_CONFIG_DIR']}; skills may need to live there")
    if os.environ.get("CODEX_HOME"):
        check("codex: CODEX_HOME override", None, os.environ["CODEX_HOME"])

    if live:
        from .core import ask
        for caller, target in (("codex", "claude"), ("claude", "codex"), ("claude", "agy")):
            if target not in cmds:
                continue
            req = {"task_id": "doctor-live", "question": "Connectivity check. Set assessment to 'ok', recommendation "
                   "to 'none', confidence 'high', and leave the lists and proposed_code empty.",
                   "help_type": "other", "help_type_detail": "connectivity check only"}
            import uuid
            req["request_id"] = f"doctor-{uuid.uuid4()}"
            from .request import load_request
            code, out = ask(lambda r=req: load_request(json.dumps(r)), caller=caller, target=target,
                            cfg={**cfg, "budget": {"max_consultations_per_task": 10**6}}, base_dir=Path.cwd())
            check(f"live: {caller} -> {target}", out["status"] == "ok", {
                "model": out["model"], "effort": out["effort"], "elapsed_seconds": out["elapsed_seconds"],
                "error": out["error"], "warnings": out["warnings"]})

    rep["ok"] = problems == 0
    return (0 if problems == 0 else 1), rep
