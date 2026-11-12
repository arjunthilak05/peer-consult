# peer-consult

[![CI](https://github.com/arjunthilakeros/peer-consult/actions/workflows/ci.yml/badge.svg)](https://github.com/arjunthilakeros/peer-consult/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/peer-consult.svg)](https://pypi.org/project/peer-consult/)
[![Python](https://img.shields.io/pypi/pyversions/peer-consult.svg)](https://pypi.org/project/peer-consult/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

**Let your coding agents ask each other for a second opinion, safely.**

peer-consult connects **Claude Code**, **OpenAI Codex CLI** and **Google Antigravity CLI (`agy`)**. From
any one of them you can:

- **`ask-*`**: consult one of the others as a *bounded, read-only adviser*. The adviser sees only the
  packet you send, runs with every tool disabled, and returns structured advice (assessment,
  recommendation, alternatives, risks, verification steps, confidence) as one JSON document.
- **`council`**: convene all three. They write independent proposals, critique each other
  *anonymously* (Proposal A/B/C), and a chair synthesizes a plan with an evidence ledger and the
  disagreements that remain. After **you** approve, one agent implements the plan in an isolated Git
  worktree. Tests then run, and the other two review the diff.
- **Pixel Office**: watch the council work in a local real-time pixel-art office, inspect each agent,
  approve plans, and replay past runs.

![The Pixel Office during a council discussion](https://raw.githubusercontent.com/arjunthilakeros/peer-consult/main/docs/screenshots/02-meeting-awaiting-approval.png)

## Contents

- [Requirements](#requirements)
- [Install](#install)
- [Using it from your agent](#using-it-from-your-agent)
- [Command line](#command-line)
- [Configuration](#configuration)
- [Security model](#security-model)
- [Upgrading and uninstalling](#upgrading-and-uninstalling)
- [Known limitations](#known-limitations)
- [Development](#development)

## Requirements

- Python **3.11+** on Windows, macOS or Linux.
- At least **two** of these CLIs, installed and logged in:

  | Agent | CLI | Check |
  |---|---|---|
  | Claude Code | `claude` | `claude auth status` |
  | OpenAI Codex | `codex` | `codex login status` |
  | Google Antigravity | `agy` | `agy models` |

  The council needs all three.
- `git` for `council execute`, which works in Git worktrees.

## Install

```bash
# recommended: an isolated tool install
pipx install peer-consult            # or: uv tool install peer-consult

# install the skills into Claude Code, Codex and agy, and create a default config
peer-consult setup

# check executables, logins, models, sandbox flags and skills
peer-consult doctor            # add --live for one tiny real consultation against each installed CLI
```

To install the latest code from GitHub, use
`pipx install git+https://github.com/arjunthilakeros/peer-consult`.

`setup` writes these skills (each one calls the exact interpreter peer-consult is installed in, so
they work no matter what is on `PATH`):

| Agent | Skills | Location |
|---|---|---|
| Claude Code | `ask-codex`, `ask-agy`, `council` | `~/.claude/skills/` (or `$CLAUDE_CONFIG_DIR/skills/`) |
| Codex | `ask-claude`, `ask-agy`, `council` | `~/.codex/skills/` (or `$CODEX_HOME/skills/`) |
| agy | `ask-claude`, `ask-codex`, `council` | `~/.gemini/config/skills/` |

It also creates `~/.peer-consult/config.toml` the first time. After that it never overwrites the
config. If you edited a skill, `setup` leaves it alone and writes the new version next to it as
`SKILL.md.peer-consult-new`. Use `--force` to back up and replace, and `--dry-run` to preview.

## Using it from your agent

Ask in plain language. The skill handles the packet and the call:

> *"Ask Codex to review this migration plan before we run it."*
>
> *"Get Gemini's opinion on why this test is flaky; include the failing log."*
>
> *"Convene the council on whether we should split the auth service."*

The skills also tell agents to consult on their own when a second opinion is likely to change the
outcome: repeated failed attempts, consequential design decisions, conflicting evidence, or a
complex change before it is finalized. The calling agent stays responsible. It weighs the advice,
verifies claims, and tells you which recommendations it adopted or rejected and why.

## Command line

### `ask`: one adviser

```bash
peer-consult ask --caller claude --target codex --request-file req.json [--delete-request-file]
peer-consult ask --caller codex  --target agy   < req.json
#   [--model ID] [--effort LEVEL] [--timeout SECONDS] [--output-file out.json] [--dry-run] [--base-dir DIR]
```

A minimal request is `{"question": "..."}`. The full packet also accepts `task_id`, `help_type`
(`diagnosis | design_critique | experiment_review | code_review | other`), `goal`, `constraints`,
`tried`, `observations`, `hypothesis`, `snippets`, `files` (explicit path + line range, read by the
helper), `diff`, `revision`, `experiment_results`, `previous_advice` and `follow_up`.

stdout is a single JSON document. Progress goes to stderr.

```json
{"status": "ok", "request_id": "...", "task_id": "...", "caller": "claude", "target": "codex",
 "model": {"requested": "...", "reported": null, "fallback_detected": null},
 "effort": {"requested": "max", "observed": null},
 "elapsed_seconds": 41.2, "budget": {"used": 1, "max": 2},
 "context": {"chars": 5120, "approx_tokens_estimate": 1280, "packet_sha256": "...", "files": [], "redactions": {}},
 "advice": {"assessment": "...", "recommendation": "...", "alternatives": [{"option": "...", "tradeoffs": "..."}],
            "risks": [], "verification_steps": [], "missing_context": [], "proposed_code": "", "confidence": "medium"},
 "error": null, "warnings": []}
```

| Exit code | Meaning |
|---|---|
| `0` | ok |
| `2` | usage or config error |
| `3` | refused: recursion, budget exhausted, packet too large, credential-like file |
| `4` | provider error: auth, billing, model unavailable, malformed output, isolation breach |
| `5` | timeout |
| `130` | cancelled |

### `council`: three agents

```bash
peer-consult council discuss -q "Should we migrate session caching from Redis to DragonFly?"
peer-consult council plan    -q "Add WebAuthn to the login flow" --file src/auth/login.py --chair claude
peer-consult council execute --run-id <run_id> --approve [--writer codex] [--test-cmd "pytest -q"]
peer-consult council status  [--run-id <run_id>]
peer-consult council resume  --run-id <run_id>      # skips stages that already completed
peer-consult council cancel  --run-id <run_id>
peer-consult council report  --run-id <run_id> [--format markdown|json]
peer-consult council doctor
peer-consult council office  [--host 127.0.0.1] [--port 4173] [--no-browser]
```

```
          ┌──────────── 1. independent proposals (parallel, read-only) ────────────┐
          │        claude                    codex                    agy          │
          └────────────────────────────────────┬───────────────────────────────────┘
                         2. anonymized cross-critique (Proposal A/B/C)
                                               │
                         3. chair synthesis: plan, evidence & assumption ledgers,
                            unresolved disagreements, authorized_files
                                               │
                         4. HUMAN APPROVAL  (plan mode stops here)
                                               │
                         5. single writer in a dedicated git worktree + lock
                            (changes outside authorized_files are reverted)
                                               │
                         6. deterministic tests  →  7. two read-only peer reviews
                                               │
                         at most 2 repair rounds → draft branch + report (never merged)
```

The office (`council office`) serves the same runs in the browser at `http://127.0.0.1:4173/?token=…`.
The bearer token is printed on start.

![Peer reviews and disagreements in the office](https://raw.githubusercontent.com/arjunthilakeros/peer-consult/main/docs/screenshots/03-meeting-disagreements.png)

## Configuration

`~/.peer-consult/config.toml`:

```toml
[codex]
model = "gpt-6-astra"
effort = "max"          # "ultra" is rejected: it delegates to subagents
command = []            # optional explicit argv prefix, e.g. ["/usr/bin/node", "/path/to/codex.js"]

[claude]
model = "claude-fable-5-1"
effort = "max"
auth = "inherit"        # "subscription" removes ANTHROPIC_API_KEY from the adviser env so your claude.ai login is used

[agy]
model = "gemini-4-argon"
effort = "high"         # the agy CLI rejects "max" for this model

[limits]
timeout_seconds = 1200
max_request_chars = 200000   # oversized packets are refused, never truncated

[budget]
max_consultations_per_task = 2   # one consultation + one follow-up per task_id

[council]
chair = "claude"
quorum = 3

[execute]
default_writer = "claude"
max_repairs = 2
require_approval = true

[office]
host = "127.0.0.1"
port = 4173
```

The generated file documents every key. There is **no fallback chain**: if a model or effort is
unavailable, the call fails loudly and never silently downgrades. Per-call overrides:
`--model`, `--effort`, `--timeout`.

| Environment variable | Effect |
|---|---|
| `PEER_CONSULT_HOME` | state and config directory (default `~/.peer-consult`) |
| `PEER_CONSULT_CONFIG` | explicit config file path |
| `CLAUDE_CONFIG_DIR`, `CODEX_HOME` | honoured when installing and disabling skills |
| `PEER_CONSULT_DEPTH` | set inside advisers. When it is present, peer-consult refuses to consult (recursion guard) |

## Security model

Advisers are **read-only by construction**, not just by instruction:

**Claude** (`claude -p`):
- `--tools ""` removes every built-in tool.
- `--strict-mcp-config` without `--mcp-config` removes every MCP server.
- `--safe-mode` loads no CLAUDE.md, skills, plugins or hooks.
- `--disable-slash-commands` and `--no-session-persistence`.
- `--permission-mode dontAsk`, a custom system prompt and `--json-schema`.
- Runs in an empty temporary directory.

**Codex** (`codex exec`):
- `--sandbox read-only`, `approval_policy="never"` and `--ignore-user-config --ignore-rules --ephemeral`.
- Web search and subagents are off.
- Disabled features: shell, unified exec, multi-agent, code-mode host, hooks, plugins, apps,
  memories, browser and computer use, goals, image generation.
- Its own `ask-*` skills are hidden.
- Runs in an empty temporary directory.

**agy**:
- agy has no flag that removes tools. Instead, the empty workspace gets a `PreToolUse` hook that
  denies every tool except `finish` (how agy returns schema output). The hook fails closed.
- After the run, the parser rejects any non-`finish` tool step that did not end in `ERROR`
  (`isolation_breach`) and discards that advice.

**All advisers:**
- `PEER_CONSULT_DEPTH=1` is set, so an adviser cannot consult further.
- Every session is fresh and stateless. Follow-ups resend the earlier advice explicitly.
- Credential-like files (`.env`, keys, `auth.json`, `~/.ssh`, …) are refused.
- Secret-looking strings are redacted as a second line of defence.

**Council execution:**
- Nothing is written without explicit approval: `--approve`, or the HMAC approval token issued by `plan`.
- The generated `council` skill tells agents that only the human user may approve.
- Writes happen only in a dedicated worktree, under a single-writer lock.
- Edits outside `authorized_files` are detected and reverted.
- Nothing is merged, pushed or deployed.

**Pixel Office:**
- Binds to `127.0.0.1` by default and requires a bearer token.
- Binding to another interface prints a warning.

Report vulnerabilities privately; see [SECURITY.md](SECURITY.md).

## Upgrading and uninstalling

```bash
pipx upgrade peer-consult && peer-consult setup     # re-render skills for the new version
peer-consult uninstall                              # removes the skill files setup wrote, if unmodified
pipx uninstall peer-consult                         # then remove the package
```

`uninstall` keeps `~/.peer-consult` (config, run history, budget state). Delete it by hand if you
want a clean slate.

If you used the pre-package `install.py`, its old `peer-consult` launcher may block the new
command. Install with `--force` (`pipx install --force peer-consult` or
`uv tool install --force peer-consult`), then run `peer-consult setup` once. Setup removes the old
`~/.peer-consult/runtime` copy and launchers, but only files it wrote that you have not modified.
It warns if the old launcher is still first on `PATH`.

## Known limitations

- **Model identity is only partly observable.** Codex and agy do not report the serving model or the
  applied effort, so those fields are `null`. Claude's serving model comes from its usage metadata,
  and peer-consult flags any mismatch as `fallback_detected`.
- **Process-tree containment on Windows.** The adviser is assigned to a Job Object just after
  `Popen`. A grandchild spawned in that sub-millisecond window is caught only by `taskkill /T`.
- **Codex or agy as the *calling* agent need approval.** The helper launches other CLIs, which need
  network access and write their own state under your profile. A sandboxed Codex session must
  request escalation. Headless `agy -p` auto-denies the command, so use agy interactively and
  approve it.
- **agy keeps its conversations.** agy has no ephemeral mode, so adviser conversations are stored
  under `~/.gemini/antigravity-cli/` like any other. agy also loads your global skills and rules,
  but it cannot act on them because every tool is denied.

The design record behind the council is in [docs/architecture.md](docs/architecture.md).

## Development

```bash
git clone https://github.com/arjunthilakeros/peer-consult && cd peer-consult
python -m venv .venv && . .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

pytest                    # Python suite; provider CLIs are replaced by tests/fake_cli.py
ruff check .

cd office-ui && npm ci
npm test                  # Vitest
npm run build             # rebuilds peer_consult/office_dist (commit the result)
npx playwright install chromium && npx playwright test   # browser end-to-end (UPDATE_DOCS_SCREENSHOTS=1 refreshes docs/screenshots)
```

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[MIT](LICENSE). The Pixel Office adapts the engine and sprites of
[Pixel Agents](https://github.com/pixel-agents-hq/pixel-agents) (MIT); see
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). peer-consult is an independent project, not
affiliated with Anthropic, OpenAI or Google.
