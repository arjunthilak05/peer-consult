# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [1.0.0] - 2026-11-12

First public release.

### Added
- `ask`: bounded, read-only consultation between any two of Claude Code, Codex CLI and Antigravity
  CLI (`agy`), with structured JSON advice, per-task budgets, size limits, credential-file refusal,
  secret redaction, model-fallback detection and process-tree cleanup on timeout/cancel.
- `council`: three-agent `discuss` / `plan` / `execute` / `status` / `resume` / `cancel` /
  `report` / `doctor`. Covers independent proposals, anonymized cross-critique, chair synthesis
  with evidence and assumption ledgers, a human approval gate (flag or HMAC token), single-writer
  execution in a Git worktree with scope enforcement, deterministic tests, dual peer review and at
  most two repair rounds. State is kept in SQLite WAL with resumable stages.
- `council office`: local Pixel-Art Office web UI (token-protected) with live events, agent
  inspector, approval dialog, diff/test viewer and event replay.
- Installable Python package (`pipx install peer-consult`) with `peer-consult setup` to render the
  `ask-*` and `council` skills for all three agents, `peer-consult uninstall`, and
  `peer-consult --version`.

### Changed
- Skills now invoke `"<python>" -I -m peer_consult`, using the interpreter the package is installed
  in, instead of a copied runtime under `~/.peer-consult/runtime`. `setup` removes the old runtime
  copy and launchers when they are unmodified.
- The generated `council` skill states that only the human user may approve plan execution.
- The Codex adviser also hides the `council` skill, not only the `ask-*` skills.

### Fixed
- The synthesis schema-repair path in the test fake CLI was unreachable; it is now covered by tests
  for both one repair (accepted) and persistent schema failure (run fails).

[1.0.0]: https://github.com/arjunthilakeros/peer-consult/releases/tag/v1.0.0
