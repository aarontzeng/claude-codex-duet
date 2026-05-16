#!/usr/bin/env python3
"""Queue manager for cc-duet project sidecars.

Provides both an importable Python API and a CLI interface.
Other runtime scripts (create_task.py, codex_runner.py) import the API
functions directly instead of shelling out via subprocess.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

ROOT = Path(os.environ.get("DUET_ROOT", os.environ.get("ORCHESTRATOR_ROOT", Path(__file__).parent.parent))).resolve()
PROJECT_ROOT = ROOT.parent
QUEUE_DIR = ROOT / "queue"
WORKTREES_DIR = ROOT / "worktrees"
ARTIFACTS_DIR = ROOT / "artifacts"
TEMPLATES_DIR = ROOT / "templates"
ENABLE_GIT_COMMITS = os.environ.get("DUET_GIT_COMMITS", os.environ.get("ORCHESTRATOR_GIT_COMMITS", "0")) == "1"

STATUSES = ["pending", "claimed", "review", "done", "failed"]


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _slug(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower())
    return slug.strip("-")[:40]


def _task_id() -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    return f"t-{ts}"


def _next_task_id(title: str) -> str:
    base_task_id = f"{_task_id()}-{_slug(title)}"
    task_id = base_task_id
    suffix = 2
    while _find_task(task_id):
        task_id = f"{base_task_id}-{suffix}"
        suffix += 1
    return task_id


def _find_task(task_id: str) -> Optional[Path]:
    for status in STATUSES:
        path = QUEUE_DIR / status / f"{task_id}.json"
        if path.exists():
            return path
    return None


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def _git_commit(message: str) -> None:
    if not ENABLE_GIT_COMMITS:
        return
    try:
        subprocess.run(["git", "add", ".cc-duet/queue"], cwd=PROJECT_ROOT, check=True, capture_output=True)
        diff = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=PROJECT_ROOT, capture_output=True)
        if diff.returncode != 0:
            subprocess.run(["git", "commit", "-m", message], cwd=PROJECT_ROOT, check=True, capture_output=True)
    except subprocess.CalledProcessError:
        pass


def _history_append(data: dict, event: str, detail: str = "") -> None:
    data.setdefault("history", []).append({"at": datetime.now(timezone.utc).isoformat(), "event": event, "detail": detail})


def _retry_count(data: dict) -> int:
    return sum(1 for item in data.get("history", []) if item.get("event") == "rejected") + 1


# ---------------------------------------------------------------------------
# Public API — importable by other runtime scripts and future MCP layer
# ---------------------------------------------------------------------------

def create_task(
    title: str,
    spec: str = "",
    priority: int = 2,
    created_by: str = "human",
    project_paths: list[str] | None = None,
    base_ref: str = "HEAD",
    max_rejections: int = 3,
    acceptance: list[str] | None = None,
    tags: list[str] | None = None,
    model: str | None = None,
    max_runtime: int | None = None,
    env_vars: list[str] | None = None,
) -> dict:
    """Create a task in the pending queue.

    Returns:
        {"task_id": str, "path": str}

    Raises:
        ValueError: if project_paths is empty.
    """
    if not project_paths:
        raise ValueError("project_paths is required")
    normalized_paths = [item.strip() for item in project_paths if item.strip()]
    if not normalized_paths:
        raise ValueError("project_paths is required (all entries were blank)")
    template = json.loads((TEMPLATES_DIR / "task.json").read_text(encoding="utf-8"))
    task_id = _next_task_id(title)
    task = {**template}
    task["id"] = task_id
    task["title"] = title
    task["spec"] = spec
    task["priority"] = priority
    task["created_by"] = created_by
    task["created_at"] = datetime.now(timezone.utc).isoformat()
    task["status"] = "pending"
    task["base_ref"] = base_ref or "HEAD"
    task["max_rejections"] = max_rejections
    task["project_paths"] = normalized_paths
    if acceptance:
        task["acceptance_criteria"] = [item.strip() for item in acceptance]
    if tags:
        task["tags"] = [item.strip() for item in tags]
    if model:
        task["codex"]["model"] = model
    if max_runtime:
        task["codex"]["max_runtime_s"] = max_runtime
    if env_vars:
        task["codex"]["allowed_env_vars"] = [item.strip() for item in env_vars]
    _history_append(task, "created")
    destination = QUEUE_DIR / "pending" / f"{task_id}.json"
    _write(destination, task)
    _git_commit(f"chore(cc-duet): queue {task_id}")
    return {"task_id": task_id, "path": str(destination)}


def list_tasks(status: str | None = None) -> list[dict]:
    """List task summaries, optionally filtered by status."""
    statuses = [status] if status else STATUSES
    items = []
    for s in statuses:
        for path in sorted((QUEUE_DIR / s).glob("*.json")):
            payload = _read(path)
            items.append({"id": payload["id"], "status": payload["status"], "priority": payload["priority"], "title": payload["title"], "path": str(path)})
    return items


def get_task(task_id: str) -> dict:
    """Get full task payload.

    Raises:
        ValueError: if the task is not found.
    """
    path = _find_task(task_id)
    if not path:
        raise ValueError(f"task {task_id} not found")
    return _read(path)


def next_task() -> dict:
    """Get the highest-priority pending task.

    Returns:
        {"task": dict, "path": str} when a task exists, or {"task": None} when the queue is empty.
    """
    tasks: list[tuple[int, str, dict, Path]] = []
    for path in (QUEUE_DIR / "pending").glob("*.json"):
        payload = _read(path)
        tasks.append((payload["priority"], payload["created_at"], payload, path))
    if not tasks:
        return {"task": None}
    tasks.sort(key=lambda item: (item[0], item[1]))
    _, _, task, path = tasks[0]
    return {"task": task, "path": str(path)}


def move_task(task_id: str, new_status: str, note: str = "") -> dict:
    """Move a task to a new status.

    Returns:
        {"task_id": str, "status": str}

    Raises:
        ValueError: if the task is not found.
    """
    source = _find_task(task_id)
    if not source:
        raise ValueError(f"task {task_id} not found")
    payload = _read(source)
    old_status = payload["status"]
    payload["status"] = new_status
    _history_append(payload, f"moved:{old_status}->{new_status}", note)
    destination = QUEUE_DIR / new_status / f"{task_id}.json"
    _write(destination, payload)
    if source != destination:
        source.unlink()
    _git_commit(f"chore(cc-duet): {task_id} {old_status}->{new_status}")
    return {"task_id": task_id, "status": new_status}


def submit_result(task_id: str, result: dict | str, target_status: str = "review") -> dict:
    """Submit a Codex result for a task.

    Args:
        result: either a dict or a path to a JSON file.

    Returns:
        {"task_id": str, "status": str}

    Raises:
        ValueError: if the task is not found.
    """
    path = _find_task(task_id)
    if not path:
        raise ValueError(f"task {task_id} not found")
    payload = _read(path)
    if isinstance(result, str):
        result = json.loads(Path(result).read_text(encoding="utf-8"))
    payload["result"] = {
        "summary": result.get("summary", ""),
        "self_pass": result.get("self_pass", False),
        "artifacts": result.get("artifacts", []),
        "blocker": result.get("blocker"),
        "confidence": result.get("confidence", "low"),
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "workspace": result.get("workspace", str(WORKTREES_DIR / task_id)),
        "artifacts_dir": result.get("artifacts_dir", str(ARTIFACTS_DIR / task_id)),
        "changed_paths": result.get("changed_paths", []),
        "base_ref": result.get("base_ref", payload.get("base_ref", "HEAD"))
    }
    payload["status"] = target_status
    _history_append(payload, "result_submitted", f"status={target_status}, self_pass={result.get('self_pass')}")
    destination = QUEUE_DIR / target_status / f"{task_id}.json"
    _write(destination, payload)
    if path != destination:
        path.unlink()
    _git_commit(f"chore(cc-duet): result {task_id}->{target_status}")
    return {"task_id": task_id, "status": target_status}


def review_task(
    task_id: str,
    decision: str,
    score: int,
    concerns: list[str] | None = None,
    feedback: str | None = None,
) -> dict:
    """Review a completed task.

    Returns:
        {"task_id": str, "decision": str, "new_status": str}

    Raises:
        ValueError: if the task is not found or score is out of range.
    """
    path = _find_task(task_id)
    if not path:
        raise ValueError(f"task {task_id} not found")
    if not 0 <= score <= 10:
        raise ValueError("score must be between 0 and 10")
    payload = _read(path)
    approved = decision in {"approved", "approved_with_concerns"}
    payload["review"] = {"reviewer": "claude", "reviewed_at": datetime.now(timezone.utc).isoformat(), "decision": decision, "score": score, "concerns": [item.strip() for item in (concerns or []) if item.strip()], "feedback_for_codex": feedback, "approved": approved}
    if approved:
        new_status = "done"
        payload["status"] = "done"
        _history_append(payload, "approved", f"score={score}")
    elif decision == "failed":
        new_status = "failed"
        payload["status"] = "failed"
        _history_append(payload, "failed", f"score={score}")
    else:
        retries = _retry_count(payload)
        max_rejections = int(payload.get("max_rejections", 3) or 3)
        if feedback:
            payload["spec"] = payload["spec"] + f"\n\n---\n## Review feedback (retry #{retries})\n{feedback}"
        if retries >= max_rejections:
            new_status = "failed"
            payload["status"] = "failed"
            _history_append(payload, "failed:max_rejections", f"score={score}, retries={retries}")
        else:
            new_status = "pending"
            payload["status"] = "pending"
            _history_append(payload, "rejected", f"score={score}, retry={retries}")
    destination = QUEUE_DIR / new_status / f"{task_id}.json"
    _write(destination, payload)
    if path != destination:
        path.unlink()
    _git_commit(f"chore(cc-duet): review {task_id} {decision} score={score}")
    return {"task_id": task_id, "decision": decision, "new_status": new_status}


def status_summary() -> dict:
    """Return a concise count of tasks per status.

    Returns:
        {"pending": int, "claimed": int, "review": int, "done": int, "failed": int, "total": int}
    """
    counts: dict[str, int] = {}
    total = 0
    for status in STATUSES:
        count = len(list((QUEUE_DIR / status).glob("*.json")))
        counts[status] = count
        total += count
    counts["total"] = total
    return counts


def gc_tasks(keep_last: int = 0) -> dict:
    """Remove worktrees and artifacts for done/failed tasks.

    Args:
        keep_last: number of most recent done tasks to keep (by created_at).
                   Failed tasks are always eligible for cleanup.

    Returns:
        {"removed_worktrees": list[str], "removed_artifacts": list[str], "errors": list[str]}
    """
    import shutil

    removed_worktrees: list[str] = []
    removed_artifacts: list[str] = []
    errors: list[str] = []

    # Collect done tasks sorted by created_at (newest first) for keep_last
    done_tasks: list[tuple[str, dict]] = []
    for path in sorted((QUEUE_DIR / "done").glob("*.json")):
        try:
            payload = _read(path)
            done_tasks.append((payload.get("id", path.stem), payload))
        except Exception:  # noqa: BLE001
            continue
    done_tasks.sort(key=lambda item: item[1].get("created_at", ""), reverse=True)

    # Tasks eligible for cleanup: all failed + done tasks beyond keep_last
    eligible_ids: list[str] = []
    for path in (QUEUE_DIR / "failed").glob("*.json"):
        try:
            payload = _read(path)
            eligible_ids.append(payload.get("id", path.stem))
        except Exception:  # noqa: BLE001
            continue
    if keep_last >= 0:
        for task_id, _ in done_tasks[keep_last:]:
            eligible_ids.append(task_id)
    else:
        # keep_last < 0 means keep all done tasks
        pass

    for task_id in eligible_ids:
        worktree_path = WORKTREES_DIR / task_id
        if worktree_path.exists():
            try:
                result = subprocess.run(
                    ["git", "worktree", "remove", "--force", str(worktree_path)],
                    cwd=PROJECT_ROOT, capture_output=True, text=True,
                )
                if result.returncode == 0:
                    removed_worktrees.append(task_id)
                else:
                    # Fallback: remove directory directly
                    shutil.rmtree(worktree_path, ignore_errors=True)
                    if not worktree_path.exists():
                        removed_worktrees.append(task_id)
                    else:
                        errors.append(f"worktree {task_id}: {result.stderr.strip()}")
            except Exception as exc:  # noqa: BLE001
                errors.append(f"worktree {task_id}: {exc}")

        artifacts_path = ARTIFACTS_DIR / task_id
        if artifacts_path.exists():
            try:
                shutil.rmtree(artifacts_path)
                removed_artifacts.append(task_id)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"artifacts {task_id}: {exc}")

    return {
        "removed_worktrees": removed_worktrees,
        "removed_artifacts": removed_artifacts,
        "errors": errors,
    }


# ---------------------------------------------------------------------------
# CLI layer — thin wrappers that parse args and delegate to the API
# ---------------------------------------------------------------------------

def cmd_create(args: argparse.Namespace) -> None:
    try:
        result = create_task(
            title=args.title,
            spec=args.spec,
            priority=args.priority,
            created_by=getattr(args, "created_by", "human"),
            project_paths=args.project_paths,
            base_ref=args.base_ref,
            max_rejections=args.max_rejections,
            acceptance=args.acceptance,
            tags=args.tags,
            model=args.model,
            max_runtime=args.max_runtime,
            env_vars=args.env_vars,
        )
        print(json.dumps(result, indent=2))
    except ValueError as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        sys.exit(1)


def cmd_list(args: argparse.Namespace) -> None:
    print(json.dumps(list_tasks(args.status), indent=2))


def cmd_get(args: argparse.Namespace) -> None:
    try:
        payload = get_task(args.task_id)
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    except ValueError as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        sys.exit(1)


def cmd_next(_: argparse.Namespace) -> None:
    print(json.dumps(next_task(), indent=2))


def cmd_move(args: argparse.Namespace) -> None:
    try:
        result = move_task(args.task_id, args.new_status, args.note or "")
        print(json.dumps(result))
    except ValueError as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        sys.exit(1)


def cmd_submit_result(args: argparse.Namespace) -> None:
    try:
        result = submit_result(args.task_id, args.result_json, args.target_status)
        print(json.dumps(result))
    except ValueError as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        sys.exit(1)


def cmd_review(args: argparse.Namespace) -> None:
    try:
        result = review_task(args.task_id, args.decision, args.score, args.concerns, args.feedback)
        print(json.dumps(result))
    except ValueError as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        sys.exit(1)


def cmd_status(_: argparse.Namespace) -> None:
    counts = status_summary()
    parts = [f"{counts[s]} {s}" for s in STATUSES if counts[s] > 0]
    print(", ".join(parts) if parts else "Queue is empty.")


def cmd_gc(args: argparse.Namespace) -> None:
    result = gc_tasks(keep_last=args.keep_last)
    if result["removed_worktrees"]:
        print(f"Removed {len(result['removed_worktrees'])} worktree(s): {', '.join(result['removed_worktrees'])}")
    if result["removed_artifacts"]:
        print(f"Removed {len(result['removed_artifacts'])} artifact dir(s): {', '.join(result['removed_artifacts'])}")
    if result["errors"]:
        for error in result["errors"]:
            print(f"Error: {error}", file=sys.stderr)
    if not result["removed_worktrees"] and not result["removed_artifacts"]:
        print("Nothing to clean up.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Queue manager for cc-duet project sidecars")
    sub = parser.add_subparsers(dest="command", required=True)
    create_parser = sub.add_parser("create")
    create_parser.add_argument("--title", required=True)
    create_parser.add_argument("--spec", default="")
    create_parser.add_argument("--priority", type=int, default=2)
    create_parser.add_argument("--acceptance", nargs="*")
    create_parser.add_argument("--tags", nargs="*")
    create_parser.add_argument("--model", default=None)
    create_parser.add_argument("--max-runtime", type=int, default=None)
    create_parser.add_argument("--env-vars", nargs="*")
    create_parser.add_argument("--created-by", default="human")
    create_parser.add_argument("--project-paths", nargs="+", required=True)
    create_parser.add_argument("--base-ref", default="HEAD")
    create_parser.add_argument("--max-rejections", type=int, default=3)
    list_parser = sub.add_parser("list")
    list_parser.add_argument("--status", choices=STATUSES, default=None)
    get_parser = sub.add_parser("get")
    get_parser.add_argument("task_id")
    sub.add_parser("next")
    move_parser = sub.add_parser("move")
    move_parser.add_argument("task_id")
    move_parser.add_argument("new_status", choices=STATUSES)
    move_parser.add_argument("--note", default="")
    submit_parser = sub.add_parser("submit-result")
    submit_parser.add_argument("task_id")
    submit_parser.add_argument("--result-json", required=True)
    submit_parser.add_argument("--target-status", choices=["review", "failed"], default="review")
    review_parser = sub.add_parser("review")
    review_parser.add_argument("task_id")
    review_parser.add_argument("--decision", required=True, choices=["approved", "approved_with_concerns", "rejected", "failed"])
    review_parser.add_argument("--score", type=int, required=True)
    review_parser.add_argument("--concerns", nargs="*")
    review_parser.add_argument("--feedback", default=None)
    sub.add_parser("status")
    gc_parser = sub.add_parser("gc")
    gc_parser.add_argument("--keep-last", type=int, default=0, help="Number of most recent done tasks to keep")
    args = parser.parse_args()
    dispatch = {"create": cmd_create, "list": cmd_list, "get": cmd_get, "next": cmd_next, "move": cmd_move, "submit-result": cmd_submit_result, "review": cmd_review, "status": cmd_status, "gc": cmd_gc}
    dispatch[args.command](args)


if __name__ == "__main__":
    main()
