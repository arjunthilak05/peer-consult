"""Model selection for the local office. Never starts provider inference."""
from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from .config import PROVIDERS, ConfigError, config_path, load_config, validate_model

MODEL_OPTIONS = {
    "claude": [
        ("claude-opus-5-5", "Claude Opus 5.5"),
        ("claude-sonnet-5-5", "Claude Sonnet 5.5"),
        ("claude-fable-5-1", "Claude Fable 5.1"),
    ],
    "codex": [],  # populated from the local Codex catalogue when available
    "agy": [
        ("gemini-3.8-flash", "Gemini 3.8 Flash"),
        ("gemini-4-argon", "Gemini 4 Argon"),
    ],
}


def model_settings(cfg: dict[str, Any], *, busy: bool = False) -> dict[str, Any]:
    choices = {provider: list(values) for provider, values in MODEL_OPTIONS.items()}
    cache = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex") / "models_cache.json"
    try:
        catalogue = json.loads(cache.read_text(encoding="utf-8"))
        for model in catalogue.get("models", []):
            slug = model.get("slug")
            if isinstance(slug, str):
                validate_model(slug)
                choices["codex"].append((slug, model.get("display_name") or slug))
    except (OSError, ValueError, TypeError, ConfigError):
        pass
    providers = []
    for provider in PROVIDERS:
        current = cfg[provider]["model"]
        if current not in {model for model, _ in choices[provider]}:
            choices[provider].insert(0, (current, current))
        providers.append({
            "id": provider,
            "name": {"claude": "Claude", "codex": "Codex", "agy": "Antigravity"}[provider],
            "model": current,
            "effort": cfg[provider]["effort"],
            "options": [{"id": model, "label": label} for model, label in dict(choices[provider]).items()],
        })
    return {"providers": providers, "busy": busy}


def save_models(cfg: dict[str, Any], models: Any) -> dict[str, Any]:
    if not isinstance(models, dict) or not models or set(models) - set(PROVIDERS):
        raise ConfigError("models must contain only claude, codex, and/or agy")
    for model in models.values():
        validate_model(model)
    path = Path(cfg.get("_path") or config_path())
    content = path.read_text(encoding="utf-8-sig") if path.exists() else ""
    for provider, model in models.items():
        section = re.compile(rf"(^\[{provider}\][^\n]*\n)(.*?)(?=^\[|\Z)", re.M | re.S)
        entry = f"model = {json.dumps(model)}"
        match = section.search(content)
        if match:
            body = match.group(2)
            if re.search(r"^[ \t]*model[ \t]*=", body, re.M):
                body = re.sub(r"^[ \t]*model[ \t]*=[^\n]*", lambda _, e=entry: e, body, count=1, flags=re.M)
            else:
                body = entry + "\n" + body
            content = content[:match.start()] + match.group(1) + body + content[match.end():]
        else:
            content = content.rstrip() + f"\n\n[{provider}]\n{entry}\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, prefix=".office-models-", suffix=".toml", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(content)
        load_config(temporary)  # validate the complete TOML before atomically replacing it
        os.replace(temporary, path)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)
    return load_config(path)
