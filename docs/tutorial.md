# Tutorial

## Goal

This walkthrough shows one complete happy path:

1. scaffold a repo with `cc-duet setup`
2. ask Claude to run `/cc-duet <task>`
3. inspect the generated queue entry
4. review and close the task

## 1. Create a toy Git repo

```bash
mkdir hello-duet
cd hello-duet
git init
mkdir src
```

## 2. Install the runtime

```bash
cc-duet doctor .
cc-duet setup .
```

Expected result:

- `.cc-duet/`
- `.claude/commands/cc-duet.md`
- a managed `.gitignore` block

## 3. Give Claude a bounded task

Inside Claude Code, run:

```text
/cc-duet Implement examples/hello-world-spec.md as src/hello.py
```

Claude should create a bounded task, run Codex, and leave a queue item for review.

## 4. Inspect the pending review item

```bash
python3 .cc-duet/scripts/queue_manager.py list --status review
python3 .cc-duet/scripts/queue_manager.py get <task-id>
```

You should see the task metadata, Codex summary, changed paths, and workspace/artifact locations.

## 5. Review and decide

If the task is acceptable:

```bash
python3 .cc-duet/scripts/queue_manager.py review <task-id> --decision approved --score 9
```

If it needs another retry:

```bash
python3 .cc-duet/scripts/queue_manager.py review <task-id> --decision rejected --score 4 --feedback "Tighten the CLI output and add output.txt handling."
```

## 6. Upgrade later

When the installed package version changes:

```bash
cc-duet doctor .
cc-duet upgrade .
cc-duet doctor --strict .
```
