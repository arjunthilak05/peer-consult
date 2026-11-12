# Architecture & design notes

> Design record written while extending peer-consult from a two-agent helper into the three-agent council.
> Line counts, CLI versions and test counts are as of that audit (October 2026); the README is the current reference.

## 1. Executive Summary

This document records the Phase 1 architectural audit of [`peer-consult`](../README.md) and the Phase 7 evaluation of open-source pixel-art virtual office engines. It defines the design decisions for extending `peer-consult` from a two-agent consultation helper into a production-grade **Three-Agent Council** (`claude`, `codex`, `agy`) with durable SQLite state, anonymized cross-critique, chair synthesis, approval-gated single-writer Git worktree execution, independent peer review, and a real-time Pixel-Art Virtual Office.

---

## 2. Phase 1 Audit of Existing `peer-consult` Architecture

### 2.1 Existing Module Inventory & Reusability

| File | Lines | Responsibility | Audit Finding & Reuse Strategy |
|---|---:|---|---|
| [`peer_consult/cli.py`](../peer_consult/cli.py) | 110 | `argparse` entrypoint for `doctor` and `ask`; emits single ASCII JSON to stdout and progress summary to stderr. | **Reuse & Extend**: Preserve `ask` and `doctor` CLI flag parsing, stdout/stderr formatting, and exit codes (`0, 2, 3, 4, 5, 130`) verbatim. Add Typer-powered `council` subcommands (`discuss`, `plan`, `execute`, `status`, `resume`, `cancel`, `report`, `doctor`, `office`) and top-level command aliases. |
| [`peer_consult/config.py`](../peer_consult/config.py) | 128 | Loads `~/.peer-consult/config.toml` via `tomllib`, merges `DEFAULTS`, validates models (`_MODEL_RE`), efforts (`ALLOWED_EFFORTS`), and limits. Rejects Codex `ultra` effort. | **Reuse & Extend**: Keep all existing sections (`[codex]`, `[claude]`, `[agy]`, `[limits]`, `[budget]`) and validation rules intact. Add `[council]`, `[execute]`, and `[office]` configuration blocks. |
| [`peer_consult/core.py`](../peer_consult/core.py) | 290 | Implements `current_depth()` (`PEER_CONSULT_DEPTH`), file-locked `Budget`, `_child_env()`, `_skill_paths_to_disable()`, temp dir creation, and single-adviser `ask()`. | **Reuse**: Import `DEPTH_VAR`, `current_depth()`, `_child_env()`, `_skill_paths_to_disable()`, and exit code constants directly into the council orchestrator so single-adviser and council invocations share identical security invariants. |
| [`peer_consult/procutil.py`](../peer_consult/procutil.py) | 289 | `resolve_command()` (refuses `.cmd`/`.bat` shims, resolves `codex.cmd` to `[node.exe, codex.js]`), Windows Job Object `_Tree` (`JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` + `taskkill /T /F`), bounded stream readers, and `run()`. | **Reuse & Extend**: Keep `run()`, `resolve_command()`, `pid_alive()`, and `_Tree` intact. Add `async_run()` using `asyncio.create_subprocess_exec` (`shell=False`) with `_Tree` job containment, streaming line callbacks (`on_stdout_line`), and `cancel_event` polling. |
| [`peer_consult/providers.py`](../peer_consult/providers.py) | 393 | `CodexAdapter`, `ClaudeAdapter`, `AgyAdapter`, `prepare_agy_workspace()`, error `_CLASSIFIERS`, and `ADVICE_SCHEMA`. | **Reuse & Extend**: Keep `ADVICE_SCHEMA` and existing `build()`/`parse()` signatures backward-compatible. Parameterize `parse(..., validator=...)` to support Pydantic v2 stage schemas and add bounded single-writer builders (`build_writer()`). |
| [`peer_consult/request.py`](../peer_consult/request.py) | 265 | `load_request()`, `is_sensitive_path()`, 10-pattern secret `redact()`, `read_selected_files()`, `build_packet()`, `check_size()`. | **Reuse**: Use `load_request()`, `build_packet()`, `check_size()`, `redact()`, and `is_sensitive_path()` across all council stages, SQLite persistence, JSONL event streams, and WebSocket broadcasts. |
| [`peer_consult/doctor.py`](../peer_consult/doctor.py) | 160 | Verifies CLI executables, auth status, model catalogs, feature flags, and skill files; supports `--live`. | **Reuse & Extend**: Add council readiness checks (SQLite WAL store, Git worktree support, council skills) while preserving all existing `checks` entries. |
| [`peer_consult/installer.py`](../peer_consult/installer.py) | 250 | Manifest-tracked idempotent installer (originally `install.py`, which copied a runtime to `~/.peer-consult/runtime`; now `peer-consult setup` inside the pip package). | **Reuse & Extend**: Render `council` skills for all 3 CLIs; the compiled office UI ships inside the package as `peer_consult/office_dist`. |

---

### 2.2 Verified CLI Versions, Auth & Protection Mechanisms

All three CLIs were verified locally on `Windows-11-10.0.26100-SP0` with Python `3.13.5`:

1. **Claude Code (`claude.exe` v2.1.312)**
   - **Auth**: Verified via `claude auth status` (`loggedIn: true`, `claude.ai` team subscription; when `[claude].auth = "subscription"`, `ANTHROPIC_API_KEY` is stripped from child environment so `-p` mode uses subscription login).
   - **Read-Only Adviser Enforcement**:
     - `--tools ""` disables all built-in tools.
     - `--strict-mcp-config` (with no `--mcp-config`) disables all MCP servers.
     - `--safe-mode` disables `CLAUDE.md`, skills, plugins, hooks, custom agents, and workflows.
     - `--disable-slash-commands`, `--no-session-persistence`, `--permission-mode dontAsk`, `--permission-prompts none`.
     - Runs in an empty temporary working directory.
   - **Model Identity Verification**: `ClaudeAdapter.parse()` inspects `modelUsage` keys from the JSON result object and flags `fallback_detected = True` if the serving model does not match the requested model prefix.

2. **OpenAI Codex CLI (`codex-cli` v0.164.0 via `node.exe` v22.18.0)**
   - **Auth & Catalog**: Verified via `codex login status` (`Logged in using ChatGPT`) and `codex debug models` (`gpt-6-astra` present with `max` effort).
   - **Read-Only Adviser Enforcement**:
     - `codex exec --json --ignore-user-config --ignore-rules --ephemeral --skip-git-repo-check --sandbox read-only`.
     - `-c approval_policy="never"`, `-c web_search="disabled"`, `-c agents.enabled=false`, `-c shell_environment_policy.inherit="core"`.
     - Explicit `--disable` for all 16 features in `CODEX_DISABLED_FEATURES` (`shell_tool`, `unified_exec`, `multi_agent`, `multi_agent_v2`, `code_mode_host`, `goals`, `sleep_tool`, `hooks`, `plugins`, `apps`, `memories`, `browser_use`, `computer_use`, `image_generation`, `tool_suggest`, `skill_mcp_dependency_install`) — all 16 verified present in `codex features list`.
     - Disables `ask-*` and `council` skills via `-c skills.config=[...]`.
     - Runs in an empty temporary working directory.

3. **Google Antigravity CLI (`agy.EXE` v1.4.9)**
   - **Auth & Catalog**: Verified via `agy models` (`gemini-4-argon-low/medium/high` listed; `high` is maximum supported effort for `gemini-4-argon`).
   - **Read-Only Adviser Enforcement**:
     - Two-layer defense:
       1. **Preventive**: `prepare_agy_workspace()` writes `.agents/hooks.json` (`PreToolUse`, matcher `*`) invoking `peer_consult_gate.py` via `.\peer_consult_gate.cmd` trampoline, which denies every tool except `finish` (and fails closed on malformed JSON or hook execution error).
       2. **Detective (Fail-Closed)**: `AgyAdapter.parse()` inspects every `step_update` event in the NDJSON output stream. Any non-`finish` tool step whose terminal state is not `ERROR` raises `ProviderError("isolation_breach")` and discards the output.
     - Also passes `--sandbox` and `--disable-slash-commands`.

4. **Baseline Test Results**
   - Command: `python -m pytest -v tests`
   - Result: **47 passed in 13.23s** (covering invocation in all 6 directions, `agy` gate script & trampoline, provider error classification, hostile filenames/unicode, `PEER_CONSULT_DEPTH` recursion refusal, timeout/orphan/cancellation process-tree cleanup, oversized context refusal, secret redaction, fallback detection, per-task budget, concurrency isolation, npm shim resolution, and installer idempotency).

---

### 2.3 Identified Gaps, Risks & Engineering Mitigations

| Area | Gap in Existing Codebase | Risk | Mitigation in Council Architecture |
|---|---|---|---|
| **Concurrency** | `procutil.run()` is synchronous blocking `Popen.wait()`. | Sequential execution of 3 advisers across 2 rounds would take 2–3× longer and block event streaming. | Add `procutil.async_run()` using `asyncio.create_subprocess_exec` (`shell=False`) with `asyncio.Semaphore` and live NDJSON/chunk callbacks while retaining `_Tree` Windows Job Object cleanup. |
| **State & Recovery** | Only `state/budget/<task_id>.json` exists; no run history or checkpointing. | A crash or timeout in Stage 2 (Critique) or Stage 3 (Synthesis) loses completed Stage 1 proposals. | Implement `CouncilStore` (`state.py`) using SQLite in `WAL` mode (`council.db`) + `runs/<run_id>/events.jsonl`. `resume` loads completed `stage_outputs` and only runs unfinished stages/agents. |
| **Bias in Peer Critique** | Advisers know the caller's name in `ask`. | Models may exhibit self-preference or brand bias when critiquing named peers. | Stage 2 (`CRITIQUING`) permutes proposals into `Proposal A`, `Proposal B`, `Proposal C` via CSPRNG and persists the mapping in SQLite (`anonymization_map_json`), stripping provider/model identifiers from the critique prompt. |
| **Single-Writer Sandboxing** | `peer-consult` only supports read-only advisers; Codex Windows `workspace-write` sandbox has known capability SID issues on some machines. | Unbounded writer could modify files outside the plan scope, touch `.git`/`.env`, or conflict with concurrent runs. | Dedicated Git worktree (`git worktree add`), SQLite + file writer lock (1 writer max), scoped tool allowlists/hooks (`prepare_agy_writer_workspace`, Claude `--tools "Read,Edit,Write,Grep,Glob"`, Codex worktree execution + structured patch fallback), and deterministic post-write `git status`/`git diff` scope verification that reverts and fails closed on any unauthorized or sensitive path touch. |
| **CLI Ergonomics** | `cli.py` uses raw `argparse` with only `doctor` and `ask`. | Requirement specifies Typer CLI and rich `council` commands while preserving existing functionality. | Route `ask` and `doctor` through backward-compatible handlers while mounting a full `typer.Typer` application for `council` (`discuss`, `plan`, `execute`, `status`, `resume`, `cancel`, `report`, `doctor`, `office`) and top-level aliases. |

---

## 3. Phase 7 Open-Source Pixel-Office Repository Evaluation

All four repositories were cloned and inspected for code licenses, third-party sprite/tileset licenses, dependencies, and architecture:

1. **`pixel-agents-hq/pixel-agents` (v1.5.0) — SELECTED**
   - **Code License**: MIT (`Copyright (c) 2026 Pablo De Lucca`).
   - **Asset License**: Bundled `webview-ui/public/assets/` includes complete, redistributable `characters/` (6 palettes based on JIK-A-4's *Metro City Free Topdown Character Pack*), `floors/` (9 patterns), `walls/`, `carpets/`, `pets/`, and `furniture/` (50+ items with `manifest.json` definitions).
   - **Architecture**: React 19, TypeScript 5.9, Vite, Canvas 2D (`webview-ui/src/office/`). Includes a clean, modular engine (`office/engine/{characters.ts, gameLoop.ts, officeState.ts, renderer.ts, seatPlacement.ts, matrixEffect.ts}`, `office/layout/{tileMap.ts, furnitureCatalog.ts, layoutSerializer.ts}`, `office/sprites/{spriteCache.ts, spriteData.ts, carpetTiles.ts}`) with BFS pathfinding, named Areas, furniture z-sorting, and speech bubbles.

2. **`W17ant/Claude-Office` (v1.1.1) — UI PATTERNS REFERENCED; NON-MIT SKIN EXCLUDED**
   - **Code License**: MIT (`Copyright (c) 2026 W17ANT`).
   - **Asset License Warning**: `NOTICE.md` explicitly excludes `public/sprites/office/characters/`, `public/sprites/office/props/`, and quoted lines in `src/theme.ts` (*The Office* / Dunder Mifflin fan art) from the MIT license. We strictly exclude all non-MIT assets.
   - **Architecture**: React 18, TypeScript, Vite, CSS/DOM positioning. Its UI organization for character inspection, task boards, and permission cards informs our React side panels.

3. **`KbWen/agent-virtual-office` (v1.6.13) — NOT SELECTED**
   - **Code & Asset License**: MIT (`Copyright (c) 2026 KbWen`), inline procedural SVG sprites.
   - **Architecture**: React 19 + plain JavaScript (`.jsx`/`.js`, not TypeScript). Does not satisfy the TypeScript + Canvas pixel engine requirement as cleanly as `pixel-agents`.

4. **`fedevgonzalez/pixel-office` (v0.2.0) — NOT SELECTED**
   - **Code License**: MIT (fork of `pixel-agents`).
   - **Asset License Blocker**: Its README (lines 156–161) states that the office furniture/floor/wall tileset is *Office Interior Tileset (16x16)* by Donarg ($2 commercial asset on itch.io), which is **omitted from the repository** (`webview-ui/public/assets/` lacks `furniture/`, `floors/`, and `walls/`). `pixel-agents` v1.5.0 solved this upstream by shipping its own bundled free/MIT furniture, floor, wall, and carpet sprites.
