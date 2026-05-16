# Command reference

## Global commands

### `cc-duet install-global`

Installs the global Claude command `/cc-duet:setup` and merges the required Claude hook into `~/.claude/settings.json`.

**Flags**

- `--force` — overwrite the global setup command and refresh the installed hook group

### `cc-duet doctor [path]`

Checks:

- **prerequisites**: `git`, `claude`, `codex`, and version probe output
- **integration**: global `/cc-duet:setup` install state and Claude hook presence in `~/.claude/settings.json`
- **scaffold**: Git repo detection, `git worktree`, target `.gitignore` managed block, project command
- **runtime**: `.cc-duet/` existence plus required files and queue/artifact/worktree directory layout

The command prints structured JSON with per-check status entries and a top-level `summary`.
When run inside the `claude-codex-duet` source repo, it reports package health without expecting a target-project `.cc-duet/` runtime to already exist.

**Flags**

- `--strict` — return non-zero on warnings as well as errors

### `cc-duet setup [path]`

Scaffolds the duet sidecar into the target Git repo.

**Flags**

- `--force` — overwrite existing generated scaffold files

Behavior:

- always installs `.cc-duet/`
- always installs `.claude/commands/cc-duet.md`
- always adds `.cc-duet/` to the managed `.gitignore` block
- adds `.claude/` to that block only when the target repo did not already have a `.claude/` directory
- preflights Claude settings before mutating project files

### `cc-duet upgrade [path]`

Refreshes an already installed `.cc-duet/` runtime to the currently installed package version. This rewrites generated runtime assets and refreshes `manifest.json`.

### `cc-duet hook-dispatch [path]`

Internal command used by the global Claude hook. It reads `.cc-duet/queue/review/*.json` and emits additional Claude hook context without executing repo-local shell code.

### `cc-duet status [path]`

Prints a concise queue summary for a scaffolded target project, such as `2 pending, 1 review`.

### `cc-duet gc [path]`

Prunes worktrees and artifacts for done/failed tasks in a scaffolded target project.
Approved task worktrees are kept until this command runs so reviewers can inspect
or merge the implementation.

**Flags**

- `--keep-last <n>` — keep the most recent `n` done tasks while still pruning failed tasks

## Installed target-project commands

### `python3 .cc-duet/scripts/create_task.py`

Create a bounded task for the local sidecar runtime.

**Common flags**

- `--title`
- `--spec` or `--spec-file`
- `--from-json`
- `--paths`
- `--acceptance`
- `--priority`
- `--model`
- `--env-vars`
- `--max-runtime`
- `--base-ref`
- `--max-rejections`
- `--run`

### `python3 .cc-duet/scripts/codex_runner.py`

Run one task through Codex in an isolated worktree.

**Flags**

- `--task-id <id>`
- `--next`
- `--dry-run`
- `--clean` — remove failed task worktrees after submission; review worktrees are kept for inspection

### `python3 .cc-duet/scripts/queue_manager.py`

Inspect or mutate queue state.

**Subcommands**

- `create`
- `list`
- `get`
- `next`
- `move`
- `submit-result`
- `review`
- `status`
- `gc`

`review` is the normal Claude-side decision point after Codex finishes. `submit-result` is normally called by `codex_runner.py`.
