#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(os.environ.get("DUET_ROOT", os.environ.get("ORCHESTRATOR_ROOT", Path(__file__).parent.parent))).resolve()
SCRIPTS_DIR = ROOT / "scripts"


def _qm(*args: str) -> dict:
    result = subprocess.run([sys.executable, str(SCRIPTS_DIR / "queue_manager.py"), *args], cwd=ROOT.parent, capture_output=True, text=True)
    if result.returncode != 0:
        print(result.stderr, file=sys.stderr)
        sys.exit(result.returncode)
    return json.loads(result.stdout) if result.stdout.strip() else {}


def interactive_create() -> str:
    title = input("Title: ").strip()
    if not title:
        print("Title required.", file=sys.stderr)
        sys.exit(1)
    print("Spec (finish with a line containing only '---'):")
    lines: list[str] = []
    while True:
        line = input()
        if line == "---":
            break
        lines.append(line)
    spec = "\n".join(lines)
    print("Allowed project paths (blank line to finish):")
    project_paths: list[str] = []
    while True:
        item = input("  - ").strip()
        if not item:
            break
        project_paths.append(item)
    if not project_paths:
        print("At least one project path is required.", file=sys.stderr)
        sys.exit(1)
    qm_args = ["create", "--title", title, "--spec", spec, "--created-by", "human", "--project-paths", *project_paths]
    result = _qm(*qm_args)
    return result["task_id"]


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a cc-duet task in the current project")
    parser.add_argument("--title", default=None)
    parser.add_argument("--spec", default=None)
    parser.add_argument("--spec-file", default=None)
    parser.add_argument("--from-json", default=None)
    parser.add_argument("--priority", type=int, default=2)
    parser.add_argument("--acceptance", nargs="*", default=None)
    parser.add_argument("--paths", nargs="+", default=None)
    parser.add_argument("--model", default=None)
    parser.add_argument("--env-vars", nargs="*", default=None)
    parser.add_argument("--max-runtime", type=int, default=None)
    parser.add_argument("--base-ref", default="HEAD")
    parser.add_argument("--max-rejections", type=int, default=3)
    parser.add_argument("--run", action="store_true")
    args = parser.parse_args()
    if args.from_json:
        payload = json.loads(Path(args.from_json).read_text(encoding="utf-8"))
        project_paths = payload.get("project_paths") or []
        if not project_paths:
            print("Imported task JSON must include project_paths.", file=sys.stderr)
            sys.exit(1)
        qm_args = ["create", "--title", payload["title"], "--spec", payload.get("spec", ""), "--priority", str(payload.get("priority", 2)), "--created-by", "import", "--project-paths", *project_paths, "--base-ref", payload.get("base_ref", "HEAD"), "--max-rejections", str(payload.get("max_rejections", 3))]
        if payload.get("acceptance_criteria"):
            qm_args += ["--acceptance", *payload["acceptance_criteria"]]
        codex_cfg = payload.get("codex", {})
        if codex_cfg.get("model"):
            qm_args += ["--model", codex_cfg["model"]]
        if codex_cfg.get("max_runtime_s"):
            qm_args += ["--max-runtime", str(codex_cfg["max_runtime_s"])]
        if codex_cfg.get("allowed_env_vars"):
            qm_args += ["--env-vars", *codex_cfg["allowed_env_vars"]]
        result = _qm(*qm_args)
        task_id = result["task_id"]
    elif args.title and args.paths and (args.spec or args.spec_file):
        if args.spec and args.spec_file:
            print("Use either --spec or --spec-file, not both.", file=sys.stderr)
            sys.exit(1)
        spec = args.spec or Path(args.spec_file).read_text(encoding="utf-8")
        qm_args = ["create", "--title", args.title, "--spec", spec, "--priority", str(args.priority), "--created-by", "human", "--project-paths", *args.paths, "--base-ref", args.base_ref, "--max-rejections", str(args.max_rejections)]
        if args.acceptance:
            qm_args += ["--acceptance", *args.acceptance]
        if args.model:
            qm_args += ["--model", args.model]
        if args.env_vars:
            qm_args += ["--env-vars", *args.env_vars]
        if args.max_runtime:
            qm_args += ["--max-runtime", str(args.max_runtime)]
        result = _qm(*qm_args)
        task_id = result["task_id"]
    else:
        task_id = interactive_create()
    print(f"Created task: {task_id}")
    print(f"Location: .cc-duet/queue/pending/{task_id}.json")
    if args.run:
        run_result = subprocess.run([sys.executable, str(SCRIPTS_DIR / "codex_runner.py"), "--task-id", task_id], cwd=ROOT.parent)
        sys.exit(run_result.returncode)


if __name__ == "__main__":
    main()
