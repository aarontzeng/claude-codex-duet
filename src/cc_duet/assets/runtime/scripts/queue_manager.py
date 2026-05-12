#!/usr/bin/env python3
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


def _slug(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower())
    return slug.strip("-")[:40]


def _task_id() -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    return f"t-{ts}"


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


def cmd_create(args: argparse.Namespace) -> None:
    template = json.loads((TEMPLATES_DIR / "task.json").read_text(encoding="utf-8"))
    task_id = f"{_task_id()}-{_slug(args.title)}"
    task = {**template}
    task["id"] = task_id
    task["title"] = args.title
    task["spec"] = args.spec or ""
    task["priority"] = args.priority
    task["created_by"] = getattr(args, "created_by", "human")
    task["created_at"] = datetime.now(timezone.utc).isoformat()
    task["status"] = "pending"
    task["base_ref"] = args.base_ref or "HEAD"
    task["max_rejections"] = args.max_rejections
    task["project_paths"] = [item.strip() for item in args.project_paths if item.strip()]
    if args.acceptance:
        task["acceptance_criteria"] = [item.strip() for item in args.acceptance]
    if args.tags:
        task["tags"] = [item.strip() for item in args.tags]
    if args.model:
        task["codex"]["model"] = args.model
    if args.max_runtime:
        task["codex"]["max_runtime_s"] = args.max_runtime
    if args.env_vars:
        task["codex"]["allowed_env_vars"] = [item.strip() for item in args.env_vars]
    _history_append(task, "created")
    destination = QUEUE_DIR / "pending" / f"{task_id}.json"
    _write(destination, task)
    _git_commit(f"chore(cc-duet): queue {task_id}")
    print(json.dumps({"task_id": task_id, "path": str(destination)}, indent=2))


def cmd_list(args: argparse.Namespace) -> None:
    statuses = [args.status] if args.status else STATUSES
    items = []
    for status in statuses:
        for path in sorted((QUEUE_DIR / status).glob("*.json")):
            payload = _read(path)
            items.append({"id": payload["id"], "status": payload["status"], "priority": payload["priority"], "title": payload["title"], "path": str(path)})
    print(json.dumps(items, indent=2))


def cmd_get(args: argparse.Namespace) -> None:
    path = _find_task(args.task_id)
    if not path:
        print(json.dumps({"error": f"task {args.task_id} not found"}), file=sys.stderr)
        sys.exit(1)
    print(path.read_text(encoding="utf-8"))


def cmd_next(_: argparse.Namespace) -> None:
    tasks: list[tuple[int, str, dict, Path]] = []
    for path in (QUEUE_DIR / "pending").glob("*.json"):
        payload = _read(path)
        tasks.append((payload["priority"], payload["created_at"], payload, path))
    if not tasks:
        print(json.dumps({"task": None}))
        return
    tasks.sort(key=lambda item: (item[0], item[1]))
    _, _, task, path = tasks[0]
    print(json.dumps({"task": task, "path": str(path)}, indent=2))


def cmd_move(args: argparse.Namespace) -> None:
    source = _find_task(args.task_id)
    if not source:
        print(json.dumps({"error": f"task {args.task_id} not found"}), file=sys.stderr)
        sys.exit(1)
    payload = _read(source)
    old_status = payload["status"]
    payload["status"] = args.new_status
    _history_append(payload, f"moved:{old_status}->{args.new_status}", args.note or "")
    destination = QUEUE_DIR / args.new_status / f"{args.task_id}.json"
    _write(destination, payload)
    if source != destination:
        source.unlink()
    _git_commit(f"chore(cc-duet): {args.task_id} {old_status}->{args.new_status}")
    print(json.dumps({"task_id": args.task_id, "status": args.new_status}))


def cmd_submit_result(args: argparse.Namespace) -> None:
    path = _find_task(args.task_id)
    if not path:
        print(json.dumps({"error": f"task {args.task_id} not found"}), file=sys.stderr)
        sys.exit(1)
    payload = _read(path)
    result = json.loads(Path(args.result_json).read_text(encoding="utf-8"))
    payload["result"] = {
        "summary": result.get("summary", ""),
        "self_pass": result.get("self_pass", False),
        "artifacts": result.get("artifacts", []),
        "blocker": result.get("blocker"),
        "confidence": result.get("confidence", "low"),
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "workspace": result.get("workspace", str(WORKTREES_DIR / args.task_id)),
        "artifacts_dir": result.get("artifacts_dir", str(ARTIFACTS_DIR / args.task_id)),
        "changed_paths": result.get("changed_paths", []),
        "base_ref": result.get("base_ref", payload.get("base_ref", "HEAD"))
    }
    payload["status"] = args.target_status
    _history_append(payload, "result_submitted", f"status={args.target_status}, self_pass={result.get('self_pass')}")
    destination = QUEUE_DIR / args.target_status / f"{args.task_id}.json"
    _write(destination, payload)
    if path != destination:
        path.unlink()
    _git_commit(f"chore(cc-duet): result {args.task_id}->{args.target_status}")
    print(json.dumps({"task_id": args.task_id, "status": args.target_status}))


def cmd_review(args: argparse.Namespace) -> None:
    path = _find_task(args.task_id)
    if not path:
        print(json.dumps({"error": f"task {args.task_id} not found"}), file=sys.stderr)
        sys.exit(1)
    if not 0 <= args.score <= 10:
        print(json.dumps({"error": "score must be between 0 and 10"}), file=sys.stderr)
        sys.exit(1)
    payload = _read(path)
    approved = args.decision in {"approved", "approved_with_concerns"}
    payload["review"] = {"reviewer": "claude", "reviewed_at": datetime.now(timezone.utc).isoformat(), "decision": args.decision, "score": args.score, "concerns": [item.strip() for item in (args.concerns or []) if item.strip()], "feedback_for_codex": args.feedback, "approved": approved}
    if approved:
        new_status = "done"
        payload["status"] = "done"
        _history_append(payload, "approved", f"score={args.score}")
    elif args.decision == "failed":
        new_status = "failed"
        payload["status"] = "failed"
        _history_append(payload, "failed", f"score={args.score}")
    else:
        retries = _retry_count(payload)
        max_rejections = int(payload.get("max_rejections", 3) or 3)
        if args.feedback:
            payload["spec"] = payload["spec"] + f"\n\n---\n## Review feedback (retry #{retries})\n{args.feedback}"
        if retries >= max_rejections:
            new_status = "failed"
            payload["status"] = "failed"
            _history_append(payload, "failed:max_rejections", f"score={args.score}, retries={retries}")
        else:
            new_status = "pending"
            payload["status"] = "pending"
            _history_append(payload, "rejected", f"score={args.score}, retry={retries}")
    destination = QUEUE_DIR / new_status / f"{args.task_id}.json"
    _write(destination, payload)
    if path != destination:
        path.unlink()
    _git_commit(f"chore(cc-duet): review {args.task_id} {args.decision} score={args.score}")
    print(json.dumps({"task_id": args.task_id, "decision": args.decision, "new_status": new_status}))


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
    args = parser.parse_args()
    dispatch = {"create": cmd_create, "list": cmd_list, "get": cmd_get, "next": cmd_next, "move": cmd_move, "submit-result": cmd_submit_result, "review": cmd_review}
    dispatch[args.command](args)


if __name__ == "__main__":
    main()
