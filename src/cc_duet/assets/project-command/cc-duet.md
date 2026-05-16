# /cc-duet

Use the repo-local `.cc-duet/` sidecar to turn the user's natural-language request into a bounded Codex task, run it, then review it yourself.

The remainder of the user's message after `/cc-duet` is the task brief.

## Required workflow

1. Infer a short task title.
2. Infer **conservative** `project_paths` (prefer 1-3 globs, not repo-wide scope).
3. Infer 2-4 objective acceptance criteria.
4. Create and run the task with:

```bash
python3 .cc-duet/scripts/create_task.py \
  --title "<title>" \
  --spec "<full task brief>" \
  --paths "<path-glob-1>" "<path-glob-2>" \
  --acceptance "<criterion-1>" "<criterion-2>" \
  --run
```

5. When Codex finishes, inspect:
   - `python3 .cc-duet/scripts/queue_manager.py get <task-id>`
   - `git -C <worktree> status --short`
   - `git -C <worktree> diff --stat`
6. Apply `.cc-duet/agent-context/REVIEW_CRITERIA.md`
7. Record the decision with `queue_manager.py review`
8. If the task is approved, keep the worktree available until the implementation has been inspected or merged; use `queue_manager.py gc` only after it is no longer needed.

## Rules

- Do not require the human to run `create_task.py` manually.
- If the request is ambiguous, choose the narrowest reasonable scope and state the assumption.
- If Codex edits files outside the intended scope, reject or fail the task.
- If the task needs broader architectural changes than the brief supports, fail safely instead of guessing.
- Treat `.cc-duet/` and `.claude/` as **local generated runtime files** in this project unless the user explicitly asks to version them.
