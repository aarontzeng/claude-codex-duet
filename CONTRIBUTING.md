# Contributing

Thanks for considering a contribution.

## Development workflow

1. Create a branch for your change.
2. Keep changes scoped and explain user-facing behavior in the PR description.
3. Prefer standard-library Python only unless a dependency is clearly justified.

## Local checks

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade build
python -m pip install -e .
python -m build
python -m unittest discover -s tests -v
cc-duet doctor --strict .
```

## Design constraints

- Keep Codex sandboxing enabled; do not introduce `--dangerously-bypass-approvals-and-sandbox`.
- Treat this repo as the **installer/scaffold source**, not the runtime location.
- Do not store secret values in queue files, examples, docs, or tests.
- Favor explicit task state transitions over hidden background behavior.

## Pull requests

- Include the problem, the change, and any user-visible impact.
- Update docs when behavior, setup, or packaging changes.
- Add or update tests for the installed scaffold path when touching setup/runtime assets.
- Update `CHANGELOG.md` for user-visible changes.
