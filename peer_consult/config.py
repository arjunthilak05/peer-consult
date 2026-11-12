"""Configuration loading for peer-consult.

Settings come from a small TOML file (default ``~/.peer-consult/config.toml``),
overridable per-call from the command line. Nothing here falls back to a
different model or a lower effort: an invalid value is an error.
"""
from __future__ import annotations

import copy
import os
import re
import tomllib
from pathlib import Path

PROVIDERS = ("claude", "codex", "agy")

# "ultra" exists for some Codex models but delegates work to subagents, which an
# adviser must not do, so it is deliberately excluded.
ALLOWED_EFFORTS = {
    "codex": ("low", "medium", "high", "xhigh", "max"),
    "claude": ("low", "medium", "high", "xhigh", "max"),
    # agy validates per model ("gemini-4-argon has no 'max' effort (available: low, medium,
    # high)") and fails loudly, so the CLI's own check is authoritative.
    "agy": ("low", "medium", "high", "xhigh", "max"),
}

CLAUDE_AUTH_MODES = ("inherit", "subscription")

DEFAULTS: dict = {
    "limits": {
        "timeout_seconds": 1200,
        "max_request_chars": 200_000,
        "max_stdout_bytes": 16_000_000,
        "max_stderr_bytes": 1_000_000,
        "transient_retries": 1,
        "retry_backoff_seconds": 20,
        "heartbeat_seconds": 30,
    },
    "budget": {"max_consultations_per_task": 2},
    "codex": {"command": [], "model": "gpt-6-astra", "effort": "max"},
    "claude": {
        "command": [],
        "model": "claude-fable-5-1",
        "effort": "max",
        # "inherit": child uses whatever auth the CLI would normally pick
        #   (an ANTHROPIC_API_KEY in the environment wins over a subscription login).
        # "subscription": remove ANTHROPIC_API_KEY from the child environment only,
        #   so the CLI's existing subscription login is used. Set explicitly by the user.
        "auth": "inherit",
    },
    # Google Antigravity CLI. Effort is a separate flag; `agy models` lists the
    # combinations as "<model>-<effort>" (gemini-4-argon-low/medium/high).
    "agy": {"command": [], "model": "gemini-4-argon", "effort": "high"},
    "council": {
        "chair": "claude",
        "quorum": 3,
        "max_concurrency": 3,
        "stage_timeout_seconds": 900,
        "anonymize_proposals": True,
        "schema_repair_attempts": 1,
    },
    "execute": {
        "default_writer": "claude",
        "max_repairs": 2,
        "require_approval": True,
        "worktree_base_dir": "",
    },
    "office": {
        "host": "127.0.0.1",
        "port": 4173,
    },
}

_MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:\-\[\]]{0,127}$")


class ConfigError(Exception):
    pass


def home_dir() -> Path:
    return Path(os.environ.get("PEER_CONSULT_HOME") or Path.home() / ".peer-consult")


def config_path() -> Path:
    env = os.environ.get("PEER_CONSULT_CONFIG")
    return Path(env) if env else home_dir() / "config.toml"


def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config(path: Path | None = None) -> dict:
    path = path or config_path()
    data: dict = {}
    if path.exists():
        try:
            data = tomllib.loads(path.read_text(encoding="utf-8-sig"))
        except tomllib.TOMLDecodeError as e:
            raise ConfigError(f"invalid TOML in {path}: {e}") from e
    cfg = _merge(DEFAULTS, data)
    cfg["_path"] = str(path)
    cfg["_exists"] = path.exists()
    validate(cfg)
    return cfg


def validate_model(model: str) -> None:
    if not isinstance(model, str) or not _MODEL_RE.match(model):
        raise ConfigError(f"invalid model identifier: {model!r}")


def validate_effort(provider: str, effort: str) -> None:
    if effort not in ALLOWED_EFFORTS[provider]:
        extra = " ('ultra' delegates to subagents and is not allowed for advisers)" if effort == "ultra" else ""
        raise ConfigError(
            f"effort {effort!r} not allowed for {provider}; choose one of {ALLOWED_EFFORTS[provider]}{extra}"
        )


def validate(cfg: dict) -> None:
    for p in PROVIDERS:
        sect = cfg[p]
        validate_model(sect["model"])
        validate_effort(p, sect["effort"])
        cmd = sect.get("command", [])
        if not isinstance(cmd, list) or not all(isinstance(c, str) and c for c in cmd):
            raise ConfigError(f"[{p}].command must be a list of non-empty strings")
    if cfg["claude"]["auth"] not in CLAUDE_AUTH_MODES:
        raise ConfigError(f"[claude].auth must be one of {CLAUDE_AUTH_MODES}")
    lim = cfg["limits"]
    for k in ("timeout_seconds", "max_request_chars", "max_stdout_bytes", "max_stderr_bytes", "heartbeat_seconds"):
        if not isinstance(lim[k], (int, float)) or lim[k] <= 0:
            raise ConfigError(f"[limits].{k} must be positive")
    if not isinstance(lim["transient_retries"], int) or not 0 <= lim["transient_retries"] <= 2:
        raise ConfigError("[limits].transient_retries must be 0, 1 or 2")
    b = cfg["budget"]["max_consultations_per_task"]
    if not isinstance(b, int) or b < 1:
        raise ConfigError("[budget].max_consultations_per_task must be >= 1")
    cn = cfg["council"]
    if cn["chair"] not in PROVIDERS:
        raise ConfigError(f"[council].chair must be one of {PROVIDERS}")
    if not isinstance(cn["quorum"], int) or not 1 <= cn["quorum"] <= 3:
        raise ConfigError("[council].quorum must be 1, 2 or 3")
    if not isinstance(cn["max_concurrency"], int) or not 1 <= cn["max_concurrency"] <= 3:
        raise ConfigError("[council].max_concurrency must be 1, 2 or 3")
    if not isinstance(cn["stage_timeout_seconds"], (int, float)) or cn["stage_timeout_seconds"] <= 0:
        raise ConfigError("[council].stage_timeout_seconds must be positive")
    if not isinstance(cn["anonymize_proposals"], bool):
        raise ConfigError("[council].anonymize_proposals must be a boolean")
    if not isinstance(cn["schema_repair_attempts"], int) or not 0 <= cn["schema_repair_attempts"] <= 2:
        raise ConfigError("[council].schema_repair_attempts must be 0, 1 or 2")
    ex = cfg["execute"]
    if ex["default_writer"] not in PROVIDERS:
        raise ConfigError(f"[execute].default_writer must be one of {PROVIDERS}")
    if not isinstance(ex["max_repairs"], int) or not 0 <= ex["max_repairs"] <= 2:
        raise ConfigError("[execute].max_repairs must be 0, 1 or 2")
    if not isinstance(ex["require_approval"], bool):
        raise ConfigError("[execute].require_approval must be a boolean")
    if not isinstance(ex["worktree_base_dir"], str):
        raise ConfigError("[execute].worktree_base_dir must be a string")
    of = cfg["office"]
    if not isinstance(of["host"], str) or not of["host"].strip():
        raise ConfigError("[office].host must be a non-empty string")
    if not isinstance(of["port"], int) or not 1 <= of["port"] <= 65535:
        raise ConfigError("[office].port must be between 1 and 65535")
