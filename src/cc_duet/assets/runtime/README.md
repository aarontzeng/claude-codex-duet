# cc-duet project sidecar

This `.cc-duet/` folder is the **repo-local runtime** installed by `cc-duet setup`.

## Important default

`cc-duet setup` always adds `.cc-duet/` to the target project's `.gitignore`.
If the target repo did not already have `.claude/`, setup also adds `.claude/`.
If `.claude/` already existed, setup preserves that existing repo policy.

That means this sidecar is **local-only by default**:

- generated for the current machine and project checkout
- not intended to be committed unless a team explicitly chooses to change that policy

## What it does

- Claude creates bounded tasks
- Codex executes inside isolated git worktrees
- Claude reviews and records the decision

## Main commands

```bash
python3 .cc-duet/scripts/create_task.py --title "..." --spec "..." --paths "src/**"
python3 .cc-duet/scripts/codex_runner.py --next
python3 .cc-duet/scripts/queue_manager.py list --status review
python3 .cc-duet/scripts/queue_manager.py review <task-id> --decision approved --score 9
```

## Claude command

If this project also has `.claude/commands/cc-duet.md`, Claude can drive the whole flow from:

```text
/cc-duet <task brief>
```

## Hook setup

`cc-duet setup` already merges the required `UserPromptSubmit` hook into `~/.claude/settings.json`.
That hook calls the package-owned `cc-duet hook-dispatch` command, not repo-local shell code.
`.cc-duet/hooks/settings-snippet.json` is kept here as the exact reference payload that was installed.
