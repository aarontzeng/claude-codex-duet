# Architecture

`claude-codex-duet` has two layers:

1. **source repo** — package, installer, scaffold assets, docs, tests
2. **installed target-project sidecar** — the local runtime under `.cc-duet/`

## Source repo

The source repo contains:

- `src/cc_duet/cli.py` — package CLI
- `src/cc_duet/assets/` — canonical scaffold assets copied into target repos
- `tests/` — package and scaffold validation
- `docs/` — user and maintainer documentation

The source repo is **not** where duet tasks should run.

## Installed target-project runtime

After `cc-duet setup .`, the target Git repo gets:

```text
.cc-duet/
  queue/
  worktrees/
  artifacts/
  scripts/
  hooks/
  agent-context/
  templates/
.claude/commands/cc-duet.md
```

By default `.cc-duet/` is added to the target repo `.gitignore`.
If the target repo does not already have `.claude/`, setup also adds `.claude/`.
If `.claude/` already exists, setup preserves the repo's existing `.claude/` tracking policy.

## Runtime flow in a target project

```text
Claude Code
  -> creates bounded task
  -> Codex executes in `.cc-duet/worktrees/<task-id>/`
  -> runner records result in `.cc-duet/queue/review/`
  -> Claude reviews and decides approved/rejected/failed
```

## Why this split exists

This separation keeps the product boundary clean:

- the OSS repo stays a package and scaffold source
- individual projects receive their own local runtime
- target repos are not forced to version-control generated duet machinery
