# cc-duet Review Criteria

Claude should review each completed Codex task against this rubric before approving it.

## Must-pass checks

1. The changes stay within the task's declared `project_paths`.
2. The implementation satisfies the stated acceptance criteria.
3. The result does not weaken sandboxing, secret handling, or review boundaries.
4. The change is coherent with the surrounding code and does not introduce obvious regressions.

## Approval guidance

- **approved**: requirements are met and no substantive concerns remain.
- **approved_with_concerns**: acceptable to land, but note follow-up concerns clearly.
- **rejected**: the task can likely succeed after one more bounded retry with explicit feedback.
- **failed**: the task is unsafe, out-of-scope, or should not be retried automatically.

## When to reject

- The implementation edits files outside the declared scope.
- Acceptance criteria are only partially met.
- The diff is confusing, over-broad, or ignores repo conventions.
- The task needs architectural decisions the brief did not authorize.

## When to fail immediately

- Potential secrets appear in changed files or artifacts.
- The change attempts to weaken approvals, sandboxing, or runtime constraints.
- The task brief is too ambiguous to review safely.
