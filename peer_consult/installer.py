"""`peer-consult setup` / `peer-consult uninstall`: render the agent skills and the default config.

What `setup` writes (idempotent; safe to re-run after every upgrade):

    Claude Code: <claude config dir>/skills/ask-codex, ask-agy, council   (~/.claude unless CLAUDE_CONFIG_DIR)
    Codex:       <codex home>/skills/ask-claude, ask-agy, council (+ agents/openai.yaml)   (~/.codex unless CODEX_HOME)
    agy:         ~/.gemini/config/skills/ask-claude, ask-codex, council
    config:      <PEER_CONSULT_HOME>/config.toml   (~/.peer-consult; created once, never overwritten)

Every skill invokes ``"<python>" -I -m peer_consult ...`` with the absolute path of the interpreter
peer-consult is installed in, so skills keep working regardless of PATH or the agent's cwd.

Files we previously wrote and the user has not changed are updated in place. A file the user
modified, or a same-named skill we did not create, is left untouched and the new version is written
beside it as ``*.peer-consult-new`` (``--force`` backs it up and replaces it instead). Every file we
write is tracked by SHA-256 in ``<PEER_CONSULT_HOME>/install-manifest.json``; ``uninstall`` removes
exactly the tracked files that are still unmodified.

Older releases copied the runtime to ``~/.peer-consult/runtime`` and wrote launchers to
``~/.peer-consult/bin`` and ``~/.local/bin``. ``setup`` removes those copies when they are unmodified,
because the installed package (``pipx``/``uv tool``/``pip``) now provides the ``peer-consult`` command.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from importlib import resources
from pathlib import Path

from . import __version__

TARGETS = {
    "claude": {
        "TARGET_LONG": "Anthropic Claude", "TARGET_STRENGTH": "strongest configured Claude model, max effort",
        "TARGET_TRIGGERS": "Claude", "TARGET_LABEL": "Claude Code", "TARGET_SHORT": "Claude",
        "ADVISER_DESC": "Claude runs as a bounded adviser: `claude -p` with no built-in tools, no MCP servers, "
                        "safe mode (no CLAUDE.md/skills/plugins/hooks), no session persistence, fresh stateless session.",
        "MODEL_NOTE": "`model.requested` vs `model.reported` (from Claude's usage metadata). If\n"
                      "  `model.fallback_detected` is true, say so to the user. `effort.observed` is\n"
                      "  unknown unless reported. Treat `cost_usd_estimate` as an estimate.",
    },
    "codex": {
        "TARGET_LONG": "OpenAI Codex", "TARGET_STRENGTH": "strongest configured GPT model, max reasoning",
        "TARGET_TRIGGERS": "Codex or GPT", "TARGET_LABEL": "Codex", "TARGET_SHORT": "Codex",
        "ADVISER_DESC": "Codex runs as a bounded adviser: read-only sandbox, no shell, no subagents, "
                        "no MCP/plugins, fresh stateless session.",
        "MODEL_NOTE": "`model.requested` vs `model.reported` (Codex does not report the serving model, so this\n"
                      "  shows null/unknown). `effort.observed` is unknown unless reported. Treat\n"
                      "  `cost_usd_estimate` as an estimate.",
    },
    "agy": {
        "TARGET_LONG": "Google Gemini via the Antigravity CLI (agy)",
        "TARGET_STRENGTH": "strongest configured Gemini model at its highest effort",
        "TARGET_TRIGGERS": "Gemini, Antigravity or agy", "TARGET_LABEL": "Gemini through the Antigravity CLI (`agy`)",
        "TARGET_SHORT": "Gemini",
        "ADVISER_DESC": "agy runs as a bounded adviser: headless mode in an empty temp workspace whose hook denies "
                        "every tool except returning the answer, terminal sandbox on, slash commands off, fresh conversation.",
        "MODEL_NOTE": "`model.requested` is what was sent. agy does not report the serving model or\n"
                      "  effort, so `model.reported` and `effort.observed` are null. `cost_usd_estimate` is null.",
    },
}

CALLERS = {
    "claude": {"TEMP_WHERE": "your scratchpad or temp dir", "shells": ("bash", "powershell"), "SANDBOX_NOTE": ""},
    "codex": {"TEMP_WHERE": "the system temp dir", "shells": ("powershell", "posix"),
              "SANDBOX_NOTE": "The helper launches `{cli}`, which needs network access and writes its own state under\n"
                              "the user profile. If your sandbox blocks that, request escalation through your normal\n"
                              "approval flow. Never bypass the sandbox.\n"},
    "agy": {"TEMP_WHERE": "the system temp dir", "shells": ("powershell", "posix"),
            "SANDBOX_NOTE": "The helper launches `{cli}`, which needs network access and writes its own state under\n"
                            "the user profile. Run it as an ordinary command and let the user approve it (it may need\n"
                            "to run outside the terminal sandbox). Never use `--dangerously-skip-permissions` or\n"
                            "otherwise bypass approval.\n"},
}
SHELL_LABEL = {"bash": "Bash", "powershell": "PowerShell", "posix": "POSIX shell"}

COUNCIL_OPENAI_YAML = """\
# peer-consult:managed
interface:
  display_name: "Three-Agent Council"
  short_description: "Convene Claude, Codex, and Antigravity for independent proposals, critique, synthesis, and execution"
policy:
  allow_implicit_invocation: true
"""

DEFAULT_CLAUDE_MODEL = "claude-fable-5-1"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def template(name: str) -> str:
    return resources.files("peer_consult").joinpath("templates", name).read_text(encoding="utf-8")


def peer_consult_home(home: Path) -> Path:
    env = os.environ.get("PEER_CONSULT_HOME")
    return Path(env) if env else home / ".peer-consult"


def skill_roots(home: Path) -> dict[str, Path]:
    claude_dir = Path(os.environ["CLAUDE_CONFIG_DIR"]) if os.environ.get("CLAUDE_CONFIG_DIR") else home / ".claude"
    codex_dir = Path(os.environ["CODEX_HOME"]) if os.environ.get("CODEX_HOME") else home / ".codex"
    return {"claude": claude_dir / "skills", "codex": codex_dir / "skills",
            "agy": home / ".gemini" / "config" / "skills"}


def probe_interpreter_flags(python: str) -> list[str]:
    """Return the safest interpreter flags under which ``python -m peer_consult`` imports.

    ``-I`` (isolated: ignore PYTHON* variables and user site-packages, no cwd on sys.path) is preferred.
    A ``pip install --user`` lives in user site-packages, which ``-I`` hides, so ``-E`` is the fallback.
    """
    for flags in (["-I"], ["-E"]):
        try:
            p = subprocess.run([python, *flags, "-m", "peer_consult", "--version"], capture_output=True,
                               text=True, timeout=60, cwd=str(Path.home()))
        except (OSError, subprocess.TimeoutExpired):
            continue
        if p.returncode == 0 and __version__ in p.stdout:
            return flags
    raise SystemExit(
        f"error: '{python} -m peer_consult' does not import peer-consult {__version__}.\n"
        "Run setup with the interpreter peer-consult is installed in (the `peer-consult` command does this),\n"
        "or pass --python <that interpreter>."
    )


class Installer:
    def __init__(self, home: Path, python: str, force: bool, dry: bool, quiet: bool = False):
        self.home = home
        self.root = peer_consult_home(home)
        self.python = python
        self.force = force
        self.dry = dry
        self.quiet = quiet
        self.manifest_path = self.root / "install-manifest.json"
        try:
            self.manifest: dict[str, str] = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            self.manifest = {}
        self.report: list[str] = []

    # -- helpers ---------------------------------------------------------------------------------
    def log(self, msg: str) -> None:
        self.report.append(msg)
        if not self.quiet:
            print(msg)

    def ours_unmodified(self, path: Path) -> bool:
        try:
            return self.manifest.get(str(path)) == sha(path.read_bytes())
        except OSError:
            return False

    def put(self, dest: Path, data: bytes) -> None:
        key = str(dest)
        new_hash = sha(data)
        if dest.exists():
            cur = dest.read_bytes()
            if cur == data:
                self.manifest[key] = new_hash
                self.log(f"unchanged  {dest}")
                return
            ours_unmodified = self.manifest.get(key) == sha(cur)
            if not ours_unmodified and not self.force:
                side = dest.with_name(dest.name + ".peer-consult-new")
                if not self.dry:
                    side.write_bytes(data)
                self.log(f"PRESERVED  {dest} (modified by user or not ours); new version at {side}")
                return
            if not ours_unmodified and self.force:
                bak = dest.with_name(f"{dest.name}.bak-{time.strftime('%Y%m%d-%H%M%S')}")
                if not self.dry:
                    shutil.copy2(dest, bak)
                self.log(f"backed up  {dest} -> {bak}")
        if not self.dry:
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_name(dest.name + ".tmp-install")
            tmp.write_bytes(data)
            os.replace(tmp, dest)
        self.manifest[key] = new_hash
        self.log(f"wrote      {dest}")

    def remove_if_ours(self, path: Path, reason: str) -> None:
        if not path.exists():
            self.manifest.pop(str(path), None)
            return
        if self.ours_unmodified(path):
            if not self.dry:
                path.unlink()
            self.manifest.pop(str(path), None)
            self.log(f"removed    {path} ({reason})")
        elif str(path) in self.manifest:
            self.log(f"LEFT       {path} (modified since peer-consult wrote it)")

    def prune_empty(self, *dirs: Path) -> None:
        for d in dirs:
            if d.is_dir() and not any(d.iterdir()) and not self.dry:
                d.rmdir()

    def save_manifest(self) -> None:
        if self.dry:
            return
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = self.manifest_path.with_name(self.manifest_path.name + ".tmp")
        tmp.write_text(json.dumps(self.manifest, indent=1, sort_keys=True), encoding="utf-8")
        os.replace(tmp, self.manifest_path)

    # -- setup -----------------------------------------------------------------------------------
    def run(self, claude_model: str | None, claude_auth: str | None, flags: list[str]) -> int:
        cfg = self.write_config(claude_model, claude_auth)
        self.write_skills(flags)
        self.migrate_legacy()
        self.save_manifest()
        if not self.quiet:
            cmd = " ".join([f'"{self.python}"', *flags, "-m", "peer_consult"])
            print(f"\npeer-consult {__version__}\npython  : {self.python} {' '.join(flags)}\nconfig  : {cfg}\n"
                  f"next    : {cmd} doctor")
        return 0

    def write_config(self, claude_model: str | None, claude_auth: str | None) -> Path:
        cfg = Path(os.environ["PEER_CONSULT_CONFIG"]) if os.environ.get("PEER_CONSULT_CONFIG") else self.root / "config.toml"
        if cfg.exists():
            self.log(f"kept       {cfg} (an existing config is never overwritten)")
            if claude_model or claude_auth:
                self.log("           note: --claude-model/--claude-auth only apply when creating the config; edit it directly")
            return cfg
        text = template("config.default.toml")
        text = text.replace("@@CLAUDE_MODEL@@", claude_model or DEFAULT_CLAUDE_MODEL)
        text = text.replace("@@CLAUDE_AUTH@@", claude_auth or "inherit")
        if not self.dry:
            cfg.parent.mkdir(parents=True, exist_ok=True)
            cfg.write_text(text, encoding="utf-8")
        self.log(f"wrote      {cfg}")
        return cfg

    def write_skills(self, flags: list[str]) -> None:
        roots = skill_roots(self.home)
        ask_tmpl = template("ask_skill.md.tmpl")
        yaml_tmpl = template("openai.yaml.tmpl")
        council_tmpl = template("council_skill.md.tmpl")

        def render(t: str, values: dict[str, str]) -> bytes:
            for k, v in {"VERSION": __version__, **values}.items():
                t = t.replace("{{" + k + "}}", v)
            if "{{" in t:
                raise SystemExit(f"unrendered placeholder: {t[t.index('{{'):][:40]}")
            return t.encode("utf-8")

        base_cmd = " ".join([f'"{Path(self.python).as_posix()}"', *flags, "-m", "peer_consult"])
        for caller, c in CALLERS.items():
            for target, t in TARGETS.items():
                if target == caller:
                    continue
                argv = f'{base_cmd} ask --caller {caller} --target {target} --request-file "<path>" --delete-request-file'
                blocks = []
                for sh_name in c["shells"]:
                    lang = "powershell" if sh_name == "powershell" else "bash"
                    amp = "& " if lang == "powershell" else ""
                    blocks.append(f"{SHELL_LABEL[sh_name]}:\n```{lang}\n{amp}{argv}\n```")
                values = {**t, "TARGET": target, "TEMP_WHERE": c["TEMP_WHERE"], "INVOKE_BLOCKS": "\n".join(blocks),
                          "SANDBOX_NOTE": c["SANDBOX_NOTE"].format(cli=target)}
                d = roots[caller] / f"ask-{target}"
                self.put(d / "SKILL.md", render(ask_tmpl, values))
                if caller == "codex":
                    self.put(d / "agents" / "openai.yaml", render(yaml_tmpl, values))

            c_blocks = []
            for sh_name in c["shells"]:
                lang = "powershell" if sh_name == "powershell" else "bash"
                amp = "& " if lang == "powershell" else ""
                lines = [
                    f'{amp}{base_cmd} council discuss --caller {caller} --request-file "<path>" --delete-request-file',
                    f'{amp}{base_cmd} council plan --caller {caller} --request-file "<path>" --delete-request-file',
                    f'{amp}{base_cmd} council execute --run-id "<run_id>" --approve',
                    f'{amp}{base_cmd} council status --run-id "<run_id>"',
                    f'{amp}{base_cmd} council resume --run-id "<run_id>"',
                    f'{amp}{base_cmd} council cancel --run-id "<run_id>"',
                    f'{amp}{base_cmd} council report --run-id "<run_id>"',
                    f'{amp}{base_cmd} council doctor',
                ]
                c_blocks.append(f"{SHELL_LABEL[sh_name]}:\n```{lang}\n" + "\n".join(lines) + "\n```")
            c_values = {
                "TEMP_WHERE": c["TEMP_WHERE"],
                "COUNCIL_INVOKE_BLOCKS": "\n".join(c_blocks),
                "SANDBOX_NOTE": c["SANDBOX_NOTE"].format(cli="claude, codex, and agy"),
            }
            cd = roots[caller] / "council"
            self.put(cd / "SKILL.md", render(council_tmpl, c_values))
            if caller == "codex":
                self.put(cd / "agents" / "openai.yaml", COUNCIL_OPENAI_YAML.encode("utf-8"))

    def migrate_legacy(self) -> None:
        # 1. Codex skill that older releases wrote to ~/.agents/skills (agy reads that folder too).
        legacy = self.home / ".agents" / "skills" / "ask-claude"
        for f in (legacy / "agents" / "openai.yaml", legacy / "SKILL.md"):
            if not f.exists():
                continue
            if self.ours_unmodified(f):
                if not self.dry:
                    f.unlink()
                self.manifest.pop(str(f), None)
                self.log(f"removed    {f} (Codex skills now live in {skill_roots(self.home)['codex']})")
            else:
                self.log(f"LEFT       {f} (modified or not ours); agy started under the home dir will also see it")
        self.prune_empty(legacy / "agents", legacy)

        # 2. Runtime copy + launchers from releases before the pip package.
        runtime = self.root / "runtime"
        legacy_files = [Path(k) for k in list(self.manifest) if Path(k).is_relative_to(runtime)]
        legacy_files += [self.root / "bin" / n for n in ("peer-consult", "peer-consult.cmd")]
        legacy_files += [self.home / ".local" / "bin" / n for n in ("peer-consult", "peer-consult.cmd")]
        for f in legacy_files:
            if str(f) in self.manifest:
                self.remove_if_ours(f, "superseded by the installed package")
        dist = runtime / "office_dist"
        if dist.is_dir():  # copied wholesale by the old installer, never user-edited
            if not self.dry:
                shutil.rmtree(dist, ignore_errors=True)
            self.log(f"removed    {dist} (now shipped inside the package)")
        if runtime.is_dir() and not self.dry:
            for d in sorted((p for p in runtime.rglob("*") if p.is_dir()), key=lambda p: len(p.parts), reverse=True):
                if d.name == "__pycache__":
                    shutil.rmtree(d, ignore_errors=True)
                else:
                    self.prune_empty(d)
            self.prune_empty(runtime)
        self.prune_empty(self.root / "bin")

    # -- uninstall -------------------------------------------------------------------------------
    def uninstall(self) -> int:
        for key in sorted(self.manifest):
            self.remove_if_ours(Path(key), "managed by peer-consult")
        for root in skill_roots(self.home).values():
            for name in ("ask-claude", "ask-codex", "ask-agy", "council"):
                self.prune_empty(root / name / "agents", root / name)
        self.save_manifest()
        if not self.quiet:
            print(f"\nKept {self.root} (config, run history, budget state). Delete it yourself if you no longer need it.\n"
                  "Then remove the package: `pipx uninstall peer-consult`, `uv tool uninstall peer-consult` or "
                  "`pip uninstall peer-consult`.")
        return 0


def build_parser(prog: str = "peer-consult setup") -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog=prog, description="Install the ask-* and council skills for Claude Code, Codex and agy.")
    ap.add_argument("--home", help="install under this home directory instead of ~ (testing)")
    ap.add_argument("--python", default=sys.executable, help="interpreter the skills will invoke (default: this one)")
    ap.add_argument("--claude-model", help=f"initial [claude].model when creating the config (default {DEFAULT_CLAUDE_MODEL})")
    ap.add_argument("--claude-auth", choices=["inherit", "subscription"], help="initial [claude].auth when creating the config")
    ap.add_argument("--force", action="store_true", help="back up and replace user-modified managed files")
    ap.add_argument("--dry-run", action="store_true", help="show what would change without writing anything")
    return ap


def setup_main(argv: list[str] | None = None) -> int:
    a = build_parser().parse_args(argv)
    home = Path(a.home) if a.home else Path.home()
    # abspath, not resolve(): resolving a venv's python symlink would escape the venv.
    python = os.path.abspath(a.python) if os.path.exists(a.python) else a.python
    flags = probe_interpreter_flags(python)
    return Installer(home, python, a.force, a.dry_run).run(a.claude_model, a.claude_auth, flags)


def uninstall_main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="peer-consult uninstall",
                                 description="Remove the skills and files peer-consult setup wrote (unmodified ones only).")
    ap.add_argument("--home", help="uninstall from this home directory instead of ~ (testing)")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    home = Path(a.home) if a.home else Path.home()
    return Installer(home, sys.executable, force=False, dry=a.dry_run).uninstall()
