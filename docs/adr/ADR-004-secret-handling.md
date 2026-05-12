# ADR-004: Secret Handling

## Status
Accepted

## Context
The prior system stored all secrets in a single `.env` file and sourced it globally before running Codex. This means every Codex run had access to all configured secrets regardless of what the task needed. A misconfigured or malicious task spec could cause Codex to exfiltrate credentials it should never have seen.

## Decision

Implement **per-task secret scoping**:

### 1. Secret declaration in task JSON
Each task declares which env vars it needs:
```json
{
  "codex": {
    "allowed_env_vars": ["DATABASE_URL", "AWS_PROFILE"]
  }
}
```

The runner reads these names from the task JSON, looks them up in the **invoking process's environment** (not from any file), and passes only those to the Codex subprocess.

### 2. Secret storage: system keychain or shell environment
Secrets are loaded into the shell that runs the installed sidecar (e.g., `direnv`, `pass`, or shell exports). They are **never written to disk** by the runtime, and the runner never passes the whole shell environment to Codex.

### 3. Codex subprocess env isolation
The runner constructs a clean env for the Codex subprocess:
```python
clean_env = {
    # Always pass: PATH, HOME, TERM, LANG, TMPDIR
    **ALWAYS_PASS_VARS,
    # Task-specific: only declared vars, only if present in parent env
    **{k: os.environ[k] for k in task["codex"]["allowed_env_vars"] if k in os.environ}
}
```
This shipped in Phase 1. Future iterations may tighten the baseline allowlist further.

### 4. No secrets in task files
Task JSON files are committed to git. They must never contain secret values. If a task spec requires a secret, it references the env var name only:
```json
"spec": "Connect to the DB using $DATABASE_URL and run the migration."
```

### 5. Workspace output audit
After every Codex run, the runner scans `.cc-duet/worktrees/<task-id>/` and `.cc-duet/artifacts/<task-id>/` for common secret patterns (API key regexes) before moving to review. If found, the task is immediately flagged as failed with `BLOCKER: potential credential in output`.

## Consequences

**Easier:**
- Least-privilege: Codex sees only what it needs
- Task files are safely committable (no embedded secrets)
- Auditable: `allowed_env_vars` in task JSON documents what access was granted

**Harder:**
- Task authors must explicitly declare env vars (extra step vs. "it just works")
- Env var leakage through child processes (e.g., a shell script that `printenv`) is still possible without Phase-2 isolation
- Secret scanning regex in Phase 1 will have false positives/negatives

**Accepted risk:**
- The baseline allowlist still includes provider/runtime variables such as `OPENAI_API_KEY` so Codex can function. Task-specific secrets remain opt-in via `allowed_env_vars`.
