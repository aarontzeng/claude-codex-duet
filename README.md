# claude-codex-duet

[![CI](https://github.com/aarontzeng/claude-codex-duet/actions/workflows/ci.yml/badge.svg)](https://github.com/aarontzeng/claude-codex-duet/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)

`claude-codex-duet` turns Claude Code into an orchestrator/reviewer and Codex into a bounded executor that can be scaffolded into any Git project.

This repo is the **installer + scaffold source**.  
It is **not** the runtime location where day-to-day duet tasks should execute.

## What problem it solves

Use `cc-duet` when you want this workflow inside another codebase:

1. Claude receives a natural-language task
2. Claude creates a bounded task with explicit scope
3. Codex executes inside an isolated git worktree
4. Claude reviews the result before approval

The installed runtime lives inside the target project as a local `.cc-duet/` sidecar.

## Status

**Beta.** The installer and scaffold flow are stable enough for everyday experimentation.  
The runtime task format and CLI flags may still see breaking changes before v1.0.

## Prerequisites

- Python **3.10+**
- Git with `git worktree`
- Claude Code CLI available as `claude`
- Codex CLI available as `codex`
- macOS or Linux

## Install

### End-user install from a release artifact

Download a wheel from the [GitHub Releases page](https://github.com/aarontzeng/claude-codex-duet/releases), then install it with `pipx`:

```bash
python3 -m pip install --user pipx
pipx install ./claude_codex_duet-<version>-py3-none-any.whl
```

### Local release-candidate install

If you are validating a checkout before publishing a release:

```bash
python3 -m venv .venv-release
. .venv-release/bin/activate
python -m pip install --upgrade build
python -m build
pipx install dist/claude_codex_duet-<version>-py3-none-any.whl
```

### Maintainer development install

If you are iterating locally as a maintainer:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
```

## Global Claude integration

Install the global `/cc-duet:setup` command and ensure the Claude hook is merged into `~/.claude/settings.json`:

```bash
cc-duet install-global
```

This command:

1. installs `~/.claude/commands/cc-duet/setup.md`
2. idempotently merges the `UserPromptSubmit` hook into `~/.claude/settings.json`

## First-time setup in a target project

From inside the target Git repository:

```bash
cc-duet doctor .
cc-duet setup .
```

`cc-duet doctor .` now reports four diagnostic layers before setup:

1. **prerequisites** — `git`, `claude`, `codex`, plus detected version text
2. **integration** — global `/cc-duet:setup` install state and Claude hook wiring
3. **scaffold** — Git repo resolution, `git worktree`, managed `.gitignore`, project command
4. **runtime** — `.cc-duet/` presence and required runtime file/layout completeness

When you run `doctor` inside the `claude-codex-duet` source repo itself, it switches to a **package-only** view and does not treat the absence of a target-project `.cc-duet/` runtime as a problem.

`cc-duet setup .` will:

1. verify the target is a Git repo with `git worktree`
2. scaffold `.cc-duet/`
3. scaffold `.claude/commands/cc-duet.md`
4. update the target repo `.gitignore`
5. ensure the Claude hook exists in `~/.claude/settings.json`

When you upgrade the installed `cc-duet` package later, refresh an existing target repo with:

```bash
cc-duet upgrade .
```

### Important default

The generated `.cc-duet/` runtime is **local-only by default**.  
`cc-duet setup` always adds `.cc-duet/` to the target repo `.gitignore`.

For `.claude/`, setup is conservative:

- if the target repo does **not** already have a `.claude/` directory, setup also ignores `.claude/`
- if the target repo **already** has `.claude/`, setup preserves that existing policy and only adds `.claude/commands/cc-duet.md`

## Daily usage in a target project

After setup, open Claude Code in the target repo and use:

```text
/cc-duet <task brief>
```

Claude should then:

1. infer a bounded task title and `project_paths`
2. create a task in `.cc-duet/queue/pending/`
3. run Codex in an isolated `.cc-duet/worktrees/<task-id>/`
4. inspect the result and diff
5. record `approved`, `rejected`, or `failed`

Approved task worktrees are kept for inspection and manual merge. After you no
longer need completed task worktrees or artifacts, clean them explicitly with
`cc-duet gc .`.

### Optional: MCP integration

Instead of the `/cc-duet` slash command, you can expose the queue operations
as MCP tools so Claude Code discovers them automatically.

Generate the config:

```bash
cc-duet mcp-config .
```

Save the output as `.mcp.json` in your project root. Claude Code will pick up
the `cc-duet` MCP server on next launch. The server exposes 7 tools
(`cc_duet_create_task`, `cc_duet_list_tasks`, `cc_duet_get_task`,
`cc_duet_next_task`, `cc_duet_move_task`, `cc_duet_submit_result`,
`cc_duet_review_task`) — all thin wrappers over the same queue_manager API.

**The CLI and `/cc-duet` command remain the default.** MCP is an optional,
opt-in mode for users who prefer tool-based discovery over slash commands.

To verify MCP integration health:

```bash
cc-duet doctor .
# Check the "mcp" entry under "integration"
```

## Expected target-project files

After setup, the target repo will have:

```text
.cc-duet/                # local generated runtime
.claude/commands/cc-duet.md   # local Claude slash command
```

These are generated assets, not source-of-truth project code.

## Commands

### Global CLI

```bash
cc-duet --version
cc-duet install-global
cc-duet doctor .
cc-duet setup .
cc-duet upgrade .
cc-duet mcp-config .    # print MCP server config (opt-in)
cc-duet status .        # concise queue summary
cc-duet gc .            # prune done/failed task worktrees and artifacts
```

### Target-project sidecar

```bash
python3 .cc-duet/scripts/create_task.py --title "..." --spec "..." --paths "src/**"
python3 .cc-duet/scripts/codex_runner.py --next
python3 .cc-duet/scripts/codex_runner.py --next --clean
python3 .cc-duet/scripts/queue_manager.py list --status review
python3 .cc-duet/scripts/queue_manager.py status
python3 .cc-duet/scripts/queue_manager.py review <task-id> --decision approved --score 9
python3 .cc-duet/scripts/queue_manager.py gc --keep-last 3
```

## Security model

- Codex runs in `workspace-write` sandbox mode
- task env vars are allowlisted explicitly
- target project changes are bounded by declared `project_paths`
- Claude reviews before approval
- secret scanning runs on changed paths and task artifacts

Known limitations:

- network egress is not separately firewalled by this project
- secret scanning is regex-based
- Windows is not supported

## Documentation

- `docs/install.md`
- `docs/getting-started.md`
- `docs/command-reference.md`
- `docs/troubleshooting.md`
- `docs/compatibility.md`
- `docs/architecture.md`
- `docs/tutorial.md`
- `CHANGELOG.md`

## Development

For maintainers working on this source repo:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
python -m unittest discover -s tests -v
cc-duet doctor .
```

The source repo ships the **package and scaffold assets**. The actual duet runtime is the installed `.cc-duet/` sidecar inside target projects.

## License

MIT.
