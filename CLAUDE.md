# CLAUDE.md — Claude Code context for claude-codex-duet

## What this repo is

This is the **installer + scaffold source** for `cc-duet`, a tool that turns Claude Code into an orchestrator/reviewer and Codex into a bounded executor. It is **not** the runtime location where duet tasks execute — that lives inside target projects as a `.cc-duet/` sidecar.

## Architecture

```
src/cc_duet/
├── __init__.py          # version (single source of truth alongside pyproject.toml)
├── cli.py               # all CLI commands: setup, upgrade, doctor, install-global, hook-dispatch
└── assets/
    ├── runtime/         # canonical scaffold → copied into target projects as .cc-duet/
    │   ├── scripts/     # create_task.py, codex_runner.py, queue_manager.py
    │   ├── agent-context/  # CONSTRAINTS.md, TASK_PROMPT_TEMPLATE.md, REVIEW_CRITERIA.md
    │   ├── hooks/       # settings-snippet.json (Claude hook payload)
    │   ├── templates/   # task.json template
    │   └── queue/       # pending/, claimed/, review/, done/, failed/ (with .gitkeep)
    └── project-command/ # cc-duet.md → installed as .claude/commands/cc-duet.md
```

## Key commands

```bash
# Development
python3 -m venv .venv && . .venv/bin/activate
python -m pip install -e .
python -m unittest discover -s tests -v

# Validate package health
cc-duet doctor --strict .

# Build
python -m pip install --upgrade build
python -m build
```

## Critical rules

1. **Product boundary**: this repo ships the package and scaffold assets. Do not create a second runtime surface in the source repo.
2. **Canonical assets**: always edit scaffold files under `src/cc_duet/assets/runtime/`, never create parallel copies elsewhere.
3. **Local-only default**: `.cc-duet/` is always gitignored in target projects. Do not change this default.
4. **Zero runtime dependencies**: the package uses only Python stdlib. Do not add third-party dependencies without explicit justification.
5. **Sandbox-first security**: Codex runs in `workspace-write` sandbox mode. Never reintroduce `--dangerously-bypass-approvals-and-sandbox`.
6. **Test the installed flow**: tests should validate the full scaffold path (setup → create task → dry-run), not just unit-test internal helpers in isolation.

## Version management

Version is defined in two places that **must stay in sync**:
- `pyproject.toml` → `project.version`
- `src/cc_duet/__init__.py` → `__version__`

## Test patterns

- Tests use `unittest` (stdlib only, no pytest dependency).
- External tool requirements (`claude`, `codex`) are mocked via `mock.patch.object(duet_cli, "validate_project_requirements", ...)`.
- Each test creates a temporary Git repo with `tempfile.TemporaryDirectory()` + `git init`.
- Settings writes are isolated via `settings_path=` parameter (never touch real `~/.claude/settings.json`).

## File naming conventions

- CLI entry point: `cc-duet` (hyphenated, defined in `[project.scripts]`)
- Python package: `cc_duet` (underscored, under `src/`)
- Runtime sidecar: `.cc-duet/` (dotfile with hyphen, in target projects)
- Queue task IDs: `t-YYYYMMDDTHHmmss-slug` (time-sortable)

## Things to watch out for

- `REVIEW_CRITERIA.md` was previously untracked due to gitignore patterns — it is now force-added. If adding new asset files, verify they are tracked with `git ls-files`.
- The `doctor` command behaves differently in this source repo vs. target repos — it uses `_is_source_repo()` to skip runtime checks when running here.
- Hook dispatch (`cc-duet hook-dispatch`) emits JSON to stdout consumed by Claude's hook system. Do not print anything else to stdout in that code path.
- `setup_project()` is transactional with rollback on failure — maintain this pattern when adding new setup steps.
