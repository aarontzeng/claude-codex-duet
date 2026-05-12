# ADR-002: Codex Native Sandbox (replacing --dangerously-bypass)

## Status
Accepted

## Context
The prior system invoked Codex with `--dangerously-bypass-approvals-and-sandbox` because:
- `launchd` runs the loop unattended; no human to press "Y" on approval prompts
- The prior system relied entirely on prompt-level constraints (ANTI-PATTERNS.md) for safety

This is a valid trade-off **in an already-sandboxed environment** (e.g., a container, a restricted CI runner). On a developer's primary machine — where the filesystem contains credentials, private keys, production configs, and personal data — it is not acceptable, because:

1. A sufficiently confused or manipulated Codex run could write to `~/.ssh/`, `~/.aws/`, `~/Documents/`, etc.
2. Prompt-level constraints work well for well-specified tasks but have no defense-in-depth
3. One misspecified `spec` field + one hallucination = potential irreversible damage

## Decision

Use Codex's native **`-s workspace-write` sandbox** for all automated runs:

```bash
codex exec \
  -s workspace-write \                  # ← OS-level: writes confined to -C dir
  -C .cc-duet/worktrees/<task-id>/ \     # ← Codex working root = isolated task worktree
  --skip-git-repo-check \       # ← workspace is not a git repo
  --ephemeral \                 # ← no session state persisted
  --add-dir .cc-duet/artifacts/<task-id>/ \
  -o .cc-duet/artifacts/<task-id>/.codex-last-message.txt \
  -m <model> \
  < task-prompt.md
```

The `workspace-write` sandbox is an **OS-level filesystem sandbox** (Linux namespaces / macOS sandbox-exec):
- Codex can **read** anywhere it could normally read
- Codex can **write** only within the directory passed to `-C`
- Any write attempt outside that directory fails at the syscall level — not the prompt level

This means:
- No modification to `~/.ssh/`, `~/.aws/`, `~/.config/`, or any file outside the isolated task worktree/artifacts dirs
- CONSTRAINTS.md red lines are still loaded (defense-in-depth, not the only layer)
- Human review is still required before outputs are accepted (Claude review gate)

## Approval policy

`workspace-write` sandbox still requires approval prompts **for shell commands** unless the task is pre-configured with a profile. For unattended runs we use:

```toml
# ~/.codex/profiles/orchestrator.toml  (not tracked in this repo)
[approval]
shell = "auto"             # auto-approve shell commands within workspace
```

Current tested `codex-cli` releases no longer accept `-a never` on `codex exec`, so this repo does **not** try to force approval policy through that older flag. If a local Codex profile is needed, it must be provided through the user's Codex configuration rather than a deprecated CLI switch.

## Consequences

**Easier:**
- Primary machine is safe from runaway writes: OS enforces, not prompt
- Logging is cleaner: the task worktree and artifacts directory contain everything Codex touched
- Simpler debugging: inspect `.cc-duet/worktrees/<task-id>/` and `.cc-duet/artifacts/<task-id>/`

**Harder:**
- Tasks that legitimately need to write to multiple locations (e.g., write output to a target project dir) must declare `--add-dir <path>` explicitly
- `workspace-write` sandbox may not be available on all platforms; fallback to `read-only` with explicit `--add-dir` for target dirs
- More configuration per task (explicit `extra_writable_dirs` in task JSON)

**Non-change:**
- CONSTRAINTS.md red lines are still loaded on every run (prompt-level safety remains; OS sandbox adds a second layer)
- Claude review gate unchanged — Codex output still goes through human-in-the-loop review before being acted on
