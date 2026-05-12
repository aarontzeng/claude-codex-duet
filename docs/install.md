# Install

## Requirements

- Python 3.10+
- Git with `git worktree`
- Claude Code CLI on `PATH`
- Codex CLI on `PATH`

## Install the package

### From a release artifact

Download a wheel from the project's release artifacts, then install it with `pipx`:

```bash
python3 -m pip install --user pipx
pipx install ./claude_codex_duet-<version>-py3-none-any.whl
```

### From a local release candidate

```bash
python3 -m venv .venv-release
. .venv-release/bin/activate
python -m pip install --upgrade build
python -m build
pipx install dist/claude_codex_duet-<version>-py3-none-any.whl
```

### For development

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
```

## Enable global Claude integration

```bash
cc-duet install-global
```

This installs `/cc-duet:setup` and merges the required `UserPromptSubmit` hook into `~/.claude/settings.json`.

## Upgrade an existing target repo

After updating the installed `cc-duet` package, refresh any repo that already has `.cc-duet/`:

```bash
cc-duet upgrade /path/to/project
```
