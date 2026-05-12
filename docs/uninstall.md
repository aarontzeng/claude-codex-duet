# Uninstall

## Remove global integration

Delete:

- `~/.claude/commands/cc-duet/setup.md`

Then remove the `UserPromptSubmit` group that runs the cc-duet hook from:

- `~/.claude/settings.json`

## Remove from a target repo

Delete local generated files:

- `.cc-duet/`
- `.claude/commands/cc-duet.md`

Optionally remove the `cc-duet managed block` from the target repo `.gitignore` if you no longer want its `.cc-duet/` (and, in some repos, `.claude/`) ignore rules.
