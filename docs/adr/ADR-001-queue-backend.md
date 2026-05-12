# ADR-001: Local Filesystem Queue (replacing Notion)

## Status
Accepted

## Context
The prior system (claude-codex-bridge) used Notion as the task queue. This introduced:
- **Remote dependency**: every enqueue/dequeue required an API call to notion.so (~500ms RTT)
- **Secret management overhead**: Notion integration token in env, shared across machines
- **Fragility**: network unavailability or API rate limits halted the entire pipeline
- **No offline operation**: queue unreadable without internet access
- **Coupling**: task schema was tied to Notion column types (multi-select, rich-text, etc.)

We need a queue that:
1. Works fully offline and locally
2. Requires no external account or token
3. Provides a readable audit trail
4. Supports atomic state transitions without races
5. Is inspectable with standard tools (cat, ls, jq)

## Decision

Use a **git-tracked directory queue** with one JSON file per task, organized into status subdirectories:

```
.cc-duet/queue/
  pending/    ← new tasks, ready to be claimed
  claimed/    ← task assigned to a Codex run (in-flight)
  review/     ← Codex done, awaiting Claude review
  done/       ← approved by Claude, archived
  failed/     ← permanently failed (manual intervention needed)
```

State transitions are atomic POSIX file renames (`tmp.write → dest.rename`). Each transition is followed by `git add -A && git commit`, providing:
- Full audit trail of every state change
- Point-in-time queue inspection (`git log .cc-duet/queue/`)
- Safe rollback via `git revert` or `git checkout <sha> -- .cc-duet/queue/`

Task identity is a time-stamped slug: `t-20260601T100000-refactor-auth.json`. This is:
- Lexicographically sortable
- Human-readable
- Collision-resistant without a central ID service

## Consequences

**Easier:**
- Zero external dependencies — works on plane, in offline lab, anywhere git runs
- `git log .cc-duet/queue/review/` gives complete task history with diffs
- Task JSON is the full source of truth (no "go look in Notion for the real spec")
- Queue readable by any tool that understands JSON and files
- Multi-machine use: just `git pull` to sync queue state

**Harder:**
- No phone/browser UI out of the box (Notion gave a free board view)
- No built-in sorting UI — must use CLI or `jq` filters
- Concurrent writes from multiple machines need care (last-writer-wins on merge conflicts; acceptable for solo/small-team use)
- No rich-text spec formatting — markdown in the JSON `spec` field is sufficient but not as visual

**Mitigations:**
- A simple `python3 .cc-duet/scripts/queue_manager.py list` gives a CLI table
- A future Phase-2 MCP server exposes queue reads as Claude Code tools (rich interactive access)
- For multi-machine: branch-per-machine + merge, or designate one machine as queue master
