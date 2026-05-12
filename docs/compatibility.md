# Compatibility

## Tested environment

CI currently covers:

- Python 3.10, 3.11, 3.12
- Ubuntu latest
- macOS latest

## Expected runtime environment

- macOS: supported and CI-tested
- Linux: supported and CI-tested
- Windows: not supported

## CLI assumptions

- Claude Code exposes hook support via `~/.claude/settings.json`
- Codex CLI supports `codex exec`, `-s workspace-write`, and `--ephemeral`
- If a task does not declare `--model` and `CODEX_DEFAULT_MODEL` is unset, the runner lets Codex CLI fall back to the user's own global config (for example `~/.codex/config.toml`)
