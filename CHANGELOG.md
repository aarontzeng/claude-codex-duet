# Changelog

All notable changes to `claude-codex-duet` will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Changed

- Nothing yet.

## [0.6.0] - 2026-05-16

### Added

- `cc-duet status` and runtime `queue_manager.py status` for concise queue summaries
- `cc-duet gc` and runtime `queue_manager.py gc` to explicitly prune done/failed task worktrees and artifacts
- optional `codex_runner.py --clean` cleanup path for failed task submissions

### Changed

- MCP server version now reads the scaffold manifest instead of a hardcoded value
- runtime test loading now evicts cached sidecar modules so independent scaffold tests do not leak state
- MCP scaffold tests now clean up temporary project directories

### Fixed

- approved task worktrees are kept after review so reviewers can inspect or merge the implementation before explicit garbage collection
- rejected and failed task worktrees are cleaned after review so retries start from a fresh worktree

## [0.5.0] - 2026-05-12

### Added

- optional MCP stdio server integration for target-project runtimes
- `cc-duet mcp-config` to print a ready-to-save `.mcp.json` snippet for scaffolded projects

### Changed

- extracted importable runtime queue APIs so `create_task.py`, `codex_runner.py`, and the MCP adapter share the same logic
- expanded `doctor` with opt-in MCP diagnostics for config health and runtime presence
- documented MCP as an optional integration while keeping the CLI and `/cc-duet` command as the default workflow

### Fixed

- queue task creation now rejects whitespace-only `project_paths` after normalization
- MCP request handling now returns structured JSON-RPC errors for malformed requests and invalid params instead of crashing
- MCP tool calls now convert unexpected runtime exceptions into tool errors instead of terminating the stdio session
- `mcp-config` now fails fast when the target project has not been scaffolded yet

## [0.4.0] - 2026-05-12

### Changed

- README status wording now describes beta state more directly and calls out possible pre-v1.0 breaking changes
- package metadata now uses a SPDX license expression, a valid macOS classifier, and advertises Python 3.13 support

### Fixed

- runtime changed-path detection now anchors to the task start commit so committed Codex work cannot bypass scope validation or secret scanning
- runner timeout handling now escalates from `SIGTERM` to `SIGKILL` so stuck tasks do not remain in `claimed`
- `.gitignore` managed block repair now recovers from partial marker corruption instead of duplicating the managed block
- queue task creation now avoids same-second same-title ID collisions by appending a numeric suffix when needed
- added regression coverage for committed change detection, partial `.gitignore` repair, and task ID collision handling

## [0.3.0] - 2026-05-12

### Added

- `cc-duet upgrade` command
- runtime `manifest.json` generation and drift detection
- package-owned `cc-duet hook-dispatch`
- tutorial, feature request template, release workflow, and changelog
- `REVIEW_CRITERIA.md` in the packaged runtime assets

### Changed

- renamed the generated target runtime to `.cc-duet/`
- renamed packaged scaffold assets to `src/cc_duet/assets/runtime/`
- expanded `doctor` into layered installer diagnostics with `--strict`
- updated install docs around release artifacts, upgrade flow, and venv-first maintainer workflows
- CI now runs on Ubuntu + macOS and validates built wheel artifacts

### Fixed

- existing target-project `.claude/` policy is preserved during setup
- setup now preflights settings and rolls back on invalid settings
- global hook no longer executes repo-local shell code

## [0.2.0] - 2026-05-12

### Added

- packaged `cc-duet` installer/scaffold workflow
- global `/cc-duet:setup` command
- initial OSS docs, CI, security policy, and contribution files

## [0.1.0] - 2026-05-12

### Added

- initial local dual-agent scaffold prototype
