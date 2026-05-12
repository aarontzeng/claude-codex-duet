# ADR-003: Claude Code as Orchestrator + Reviewer (not just trigger)

## Status
Accepted

## Context
In the prior system, Claude main brain had two thin roles:
1. **Create** a Notion row (via MCP)
2. **Triage** the inbox notification (🟢/🟡/🔴 to user)

The review step was cosmetic — Claude summarized Codex's self-assessment but had no structured rubric, no recorded decision, and no feedback loop back to Codex on retry.

This created:
- **No quality gate**: if Codex claimed self_pass=true, Claude typically agreed without deep inspection
- **Silent retries**: if a task failed, there was no automatic retry with improved context
- **No learning loop**: Codex received no feedback on why a result was rejected

## Decision

Elevate Claude Code to a **first-class orchestrator** with three distinct responsibilities:

### 1. Task authorship
Claude Code (not a human shell script) is the canonical task author. It:
- Uses `queue_manager.py create` (or Phase-2 MCP) to enqueue tasks
- Writes structured `spec`, `acceptance_criteria`, and `codex.allowed_env_vars`
- Sets appropriate `codex.sandbox` and `codex.max_runtime_s` per task type

### 2. Structured review (not just triage)
Claude Code evaluates Codex output against the `REVIEW_CRITERIA.md` rubric:
- Five dimensions, each scored 0–2 (total 0–10)
- Decision thresholds: 9–10 approved, 6–8 approved_with_concerns, 3–5 rejected, 0–2 failed
- Review JSON written to task file (persisted, auditable)
- Concerns and feedback appended to task spec on retry

### 3. Feedback loop on rejection
When Claude rejects a result:
- Structured `feedback_for_codex` appended to task `spec`
- Task moves back to `queue/pending/` (automatic retry available)
- History entry records rejection count
- After `max_rejections` (default 3), task moves to `failed` for human inspection

### Why not auto-approve high-scoring tasks?
Phase 1 keeps **manual review required for everything**, because:
- The review step is where Claude's judgment adds the most value
- False negatives in auto-approval are harder to catch than false positives in manual review
- The overhead is low: reviewing a RESULT.md takes ~30 seconds

Auto-approval can be added later once scoring data exists.

## Consequences

**Easier:**
- Every approved result has a documented score and rationale
- Rejected results carry structured feedback → Codex retry quality improves
- Quality trends visible in `git log queue/done/` (scores over time)
- Clear escalation path: `failed` queue surfaces tasks needing human intervention

**Harder:**
- Claude Code must actively participate in review (not just read notifications)
- Review rubric (REVIEW_CRITERIA.md) needs maintenance as task types evolve
- Auto-approve threshold tuning requires historical score data (not available at launch)

**Non-change:**
- Codex still self-assesses with self_pass/BLOCKER in RESULT.md — this is the Codex layer's output, not Claude's input filter
- Human can always bypass by directly invoking `queue_manager.py review --decision approved`
