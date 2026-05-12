# Executor Task Brief

{constraints_content}

## Task metadata

- **Task ID**: {task_id}
- **Title**: {task_title}
- **Priority**: {task_priority}
- **Base ref**: {base_ref}
- **Worktree root**: `{worktree_root}`
- **Artifacts dir**: `{artifacts_dir}`

## Allowed project paths

{project_paths}

## Spec

{task_spec}

## Acceptance criteria

{acceptance_criteria}

## Execution contract

- Modify repo files only inside the allowed project paths.
- You may also write helper output inside the artifacts directory.
- Do not modify `.cc-duet/`.

When done, write `RESULT.md` to:

`{result_path}`

Use this exact format:

```markdown
# RESULT — {task_id}

## Summary
<Three concise sentences.>

## Self-pass
<true / false>

## Artifacts
<List changed repo files and written artifacts, one per line.>

## Confidence
<high / medium / low — with one short reason>

## BLOCKER
<If self_pass=false, explain the blocker. If self_pass=true, write "none".>
```
