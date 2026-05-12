# Getting started

## 1. Verify prerequisites

```bash
cc-duet doctor .
```

Review the JSON output before setup. A healthy machine should show `prerequisites` and `integration` as `ok`; after setup, `scaffold` and `runtime` should also be `ok`.
Use `cc-duet doctor --strict .` in automation when warnings should fail the run.

## 2. Scaffold the current Git repo

```bash
cc-duet setup .
```

## 3. Open Claude Code in that target repo

Use:

```text
/cc-duet <task brief>
```

## 4. Successful setup checklist

You should now have:

- `.cc-duet/`
- `.claude/commands/cc-duet.md`
- a `.gitignore` entry for `.cc-duet/`
- a `UserPromptSubmit` hook in `~/.claude/settings.json`

If the target repo did **not** already have `.claude/`, setup will also add `.claude/` to the managed `.gitignore` block. If `.claude/` already existed, setup leaves that repo policy alone.

## 5. Upgrade later

When you install a newer `cc-duet` package, refresh the generated runtime:

```bash
cc-duet doctor .
cc-duet upgrade .
cc-duet doctor --strict .
```

## 6. Walk through one end-to-end task

See `docs/tutorial.md` for a complete setup -> `/cc-duet` -> review example.
