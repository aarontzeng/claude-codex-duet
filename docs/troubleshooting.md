# Troubleshooting

## `cc-duet setup` says the project is not a Git repo

Run setup from inside a Git working tree:

```bash
git rev-parse --show-toplevel
```

## `cc-duet setup` says `claude` or `codex` is missing

Install the required CLI and ensure it is on `PATH`.

## Claude hook is not firing

Check:

```bash
cat ~/.claude/settings.json
cc-duet doctor .
```

Restart Claude Code after changing settings.

If you want CI or a bootstrap script to fail on warnings, use:

```bash
cc-duet doctor --strict .
```

## Codex task fails immediately

Check:

- `codex` is installed
- the target repo supports `git worktree`
- task `project_paths` are not empty

## The installed runtime is out of date

If `cc-duet doctor .` warns about runtime drift or manifest version mismatch:

```bash
cc-duet upgrade .
cc-duet doctor --strict .
```
