#!/usr/bin/env python3
from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import signal
import subprocess
import sys
import textwrap
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

ROOT = Path(os.environ.get("DUET_ROOT", os.environ.get("ORCHESTRATOR_ROOT", Path(__file__).parent.parent))).resolve()
PROJECT_ROOT = ROOT.parent
QUEUE_DIR = ROOT / "queue"
WORKTREES_DIR = ROOT / "worktrees"
ARTIFACTS_DIR = ROOT / "artifacts"
AGENT_CONTEXT_DIR = ROOT / "agent-context"
SCRIPTS_DIR = ROOT / "scripts"
LOCK_DIR = ROOT / ".locks"

CODEX_BIN = os.environ.get("CODEX_BIN", "codex")
CODEX_DEFAULT_MODEL = os.environ.get("CODEX_DEFAULT_MODEL")
DEFAULT_ALLOWED_ENV_VARS = tuple(value.strip() for value in os.environ.get("CODEX_ALLOWED_ENV_VARS", "").split(",") if value.strip())
ALWAYS_PASS_ENV_VARS = frozenset({"ALL_PROXY", "CODEX_HOME", "COLORTERM", "HOME", "HTTP_PROXY", "HTTPS_PROXY", "LANG", "LC_ALL", "LC_CTYPE", "LOGNAME", "NO_COLOR", "NO_PROXY", "OPENAI_API_BASE", "OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_ORG_ID", "OPENAI_ORGANIZATION", "PATH", "REQUESTS_CA_BUNDLE", "SHELL", "SSL_CERT_DIR", "SSL_CERT_FILE", "TEMP", "TERM", "TMP", "TMPDIR", "USER", "XDG_CACHE_HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME"})
SECRET_PATTERNS = (re.compile(r"\bsk-[A-Za-z0-9_\-]{20,}\b"), re.compile(r"\bghp_[A-Za-z0-9]{20,}\b"), re.compile(r"\bntn_[A-Za-z0-9]{20,}\b"), re.compile(r"\bAKIA[0-9A-Z]{16}\b"), re.compile(r"\bAIza[0-9A-Za-z\-_]{20,}\b"))


def log(message: str) -> None:
    timestamp = datetime.now(timezone.utc).strftime("%H:%M:%S")
    print(f"[{timestamp}] {message}", flush=True)


def find_task(task_id: str) -> Optional[Path]:
    for status in ("pending", "claimed"):
        path = QUEUE_DIR / status / f"{task_id}.json"
        if path.exists():
            return path
    return None


def assemble_prompt(task: dict, worktree: Path, artifacts_dir: Path) -> str:
    template = (AGENT_CONTEXT_DIR / "TASK_PROMPT_TEMPLATE.md").read_text(encoding="utf-8")
    constraints = (AGENT_CONTEXT_DIR / "CONSTRAINTS.md").read_text(encoding="utf-8")
    criteria_lines = "\n".join(f"- [ ] {item}" for item in task.get("acceptance_criteria", []))
    path_lines = "\n".join(f"- `{item}`" for item in task.get("project_paths", []))
    return template.format(constraints_content=constraints, task_id=task["id"], task_title=task["title"], task_priority=task["priority"], base_ref=task.get("base_ref", "HEAD"), worktree_root=str(worktree), artifacts_dir=str(artifacts_dir), result_path=str(artifacts_dir / "RESULT.md"), project_paths=path_lines or "- `(missing)`", task_spec=task["spec"], acceptance_criteria=criteria_lines or "- [ ] (none specified)")


def parse_result_md(artifacts_dir: Path) -> dict:
    result_path = artifacts_dir / "RESULT.md"
    if not result_path.exists():
        return {"summary": "No RESULT.md found - Codex may have timed out or crashed.", "self_pass": False, "artifacts": [], "blocker": "RESULT.md not written", "confidence": "low"}
    text = result_path.read_text(encoding="utf-8")

    def _extract(heading: str) -> str:
        match = re.search(rf"## {heading}\s*\n(.*?)(?=\n## |\Z)", text, re.DOTALL | re.IGNORECASE)
        return match.group(1).strip() if match else ""

    summary = _extract("Summary")
    self_pass = "true" in _extract("Self-pass").lower()
    artifacts = [line.lstrip("- ").strip() for line in _extract("Artifacts").splitlines() if line.strip()]
    blocker_raw = _extract("BLOCKER")
    blocker = None if blocker_raw.lower() in {"", "none"} else blocker_raw
    confidence_raw = _extract("Confidence")
    confidence = confidence_raw.split()[0].lower() if confidence_raw else "medium"
    return {"summary": summary, "self_pass": self_pass, "artifacts": artifacts, "blocker": blocker, "confidence": confidence}


class LockFile:
    def __init__(self, task_id: str):
        LOCK_DIR.mkdir(parents=True, exist_ok=True)
        self.path = LOCK_DIR / f"{task_id}.lock"
        self.acquired = False

    def acquire(self) -> bool:
        while True:
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError:
                try:
                    pid = int(self.path.read_text(encoding="utf-8").strip())
                    os.kill(pid, 0)
                    return False
                except (FileNotFoundError, ProcessLookupError, ValueError):
                    try:
                        self.path.unlink()
                    except FileNotFoundError:
                        pass
                    continue
            else:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    handle.write(str(os.getpid()))
                self.acquired = True
                return True

    def release(self) -> None:
        if self.acquired:
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass
            self.acquired = False


def build_codex_env(task_allowed_env_vars: list[str] | None = None) -> dict[str, str]:
    allowed = set(ALWAYS_PASS_ENV_VARS)
    allowed.update(DEFAULT_ALLOWED_ENV_VARS)
    allowed.update(item.strip() for item in (task_allowed_env_vars or []) if item and item.strip())
    return {key: value for key, value in os.environ.items() if key in allowed}


def ensure_worktree(task: dict) -> Path:
    WORKTREES_DIR.mkdir(parents=True, exist_ok=True)
    worktree = WORKTREES_DIR / task["id"]
    if (worktree / ".git").exists():
        return worktree
    if worktree.exists() and any(worktree.iterdir()):
        raise RuntimeError(f"worktree path already exists and is not empty: {worktree}")
    subprocess.run(["git", "worktree", "add", "--detach", str(worktree), task.get("base_ref", "HEAD")], cwd=PROJECT_ROOT, check=True, capture_output=True, text=True)
    return worktree


def _git_stdout(cwd: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)
    return result.stdout.strip()


def get_changed_paths(worktree: Path, comparison_ref: str) -> list[str]:
    result = subprocess.run(["git", "diff", "--name-only", "--relative", comparison_ref], cwd=worktree, check=True, capture_output=True, text=True)
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _matches_allowed_path(path: str, pattern: str) -> bool:
    normalized_pattern = pattern.strip("/")
    if any(char in normalized_pattern for char in "*?[]"):
        return fnmatch.fnmatch(path, normalized_pattern)
    return path == normalized_pattern or path.startswith(normalized_pattern + "/")


def validate_changed_paths(changed_paths: list[str], allowed_patterns: list[str]) -> list[str]:
    if not allowed_patterns:
        return changed_paths[:]
    violations = []
    for path in changed_paths:
        if path.startswith(".cc-duet/"):
            violations.append(path)
            continue
        if not any(_matches_allowed_path(path, pattern) for pattern in allowed_patterns):
            violations.append(path)
    return violations


def _looks_binary(data: bytes) -> bool:
    return b"\x00" in data


def _scan_file_for_secrets(path: Path, label: str) -> Optional[str]:
    if not path.is_file() or path.stat().st_size > 1024 * 1024:
        return None
    raw = path.read_bytes()
    if _looks_binary(raw):
        return None
    text = raw.decode("utf-8", errors="ignore")
    if any(pattern.search(text) for pattern in SECRET_PATTERNS):
        return label
    return None


def scan_paths_for_secrets(worktree: Path, artifacts_dir: Path, changed_paths: list[str]) -> list[str]:
    findings: list[str] = []
    seen: set[str] = set()
    for changed_path in changed_paths:
        finding = _scan_file_for_secrets(worktree / changed_path, changed_path)
        if finding and finding not in seen:
            findings.append(finding)
            seen.add(finding)
    for artifact in artifacts_dir.rglob("*"):
        finding = _scan_file_for_secrets(artifact, f"artifacts/{artifacts_dir.name}/{artifact.relative_to(artifacts_dir)}")
        if finding and finding not in seen:
            findings.append(finding)
            seen.add(finding)
    return findings


def run_task(task_id: str, dry_run: bool = False) -> int:
    task_path = find_task(task_id)
    if not task_path:
        log(f"ERROR: task {task_id} not found")
        return 1
    task = json.loads(task_path.read_text(encoding="utf-8"))
    lock = LockFile(task_id)
    if not lock.acquire():
        log(f"SKIP: task {task_id} already being processed")
        return 0
    try:
        return _run_task_locked(task, task_path, dry_run)
    finally:
        lock.release()


def _run_task_locked(task: dict, task_path: Path, dry_run: bool) -> int:
    task_id = task["id"]
    allowed_paths = task.get("project_paths", [])
    if not allowed_paths:
        if not dry_run:
            _submit_error(task_id, "task is missing project_paths")
        return 1
    artifacts_dir = ARTIFACTS_DIR / task_id
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    worktree = WORKTREES_DIR / task_id
    if dry_run:
        prompt = assemble_prompt(task, worktree, artifacts_dir)
        log("DRY RUN - would prepare:")
        log(f"  worktree: {worktree}")
        log(f"  artifacts: {artifacts_dir}")
        print(textwrap.indent(prompt[:400], "  "))
        return 0
    try:
        worktree = ensure_worktree(task)
    except (RuntimeError, subprocess.CalledProcessError) as exc:
        _submit_error(task_id, f"unable to prepare worktree: {exc}")
        return 1
    try:
        comparison_ref = _git_stdout(worktree, "rev-parse", "HEAD")
    except subprocess.CalledProcessError as exc:
        _submit_error(task_id, f"unable to determine worktree base revision: {exc}")
        return 1
    if task_path.parent.name == "pending":
        subprocess.run([sys.executable, str(SCRIPTS_DIR / "queue_manager.py"), "move", task_id, "claimed"], cwd=PROJECT_ROOT, check=True, capture_output=True, text=True)
    prompt_file = artifacts_dir / ".task-prompt.md"
    prompt_file.write_text(assemble_prompt(task, worktree, artifacts_dir), encoding="utf-8")
    codex_cfg = task.get("codex", {})
    cmd = [CODEX_BIN, "exec", "-s", codex_cfg.get("sandbox", "workspace-write"), "-C", str(worktree), "--skip-git-repo-check", "-o", str(artifacts_dir / ".codex-last-message.txt"), "--ephemeral", "--add-dir", str(artifacts_dir)]
    selected_model = codex_cfg.get("model") or CODEX_DEFAULT_MODEL
    if selected_model:
        cmd += ["-m", selected_model]
    env = build_codex_env(codex_cfg.get("allowed_env_vars", []))
    timeout = codex_cfg.get("max_runtime_s", 600)
    try:
        with prompt_file.open("r", encoding="utf-8") as stdin_handle:
            process = subprocess.Popen(cmd, stdin=stdin_handle, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env, cwd=worktree, start_new_session=True)
        try:
            stdout, _ = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(os.getpgid(process.pid), signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                stdout, _ = process.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                except ProcessLookupError:
                    pass
                stdout, _ = process.communicate()
            stdout = (stdout or b"") + b"\n[RUNNER: process killed due to timeout]"
        if stdout:
            (artifacts_dir / ".codex-output.log").write_bytes(stdout if isinstance(stdout, bytes) else stdout.encode())
    except FileNotFoundError:
        _submit_error(task_id, "codex binary not found")
        return 1
    changed_paths = get_changed_paths(worktree, comparison_ref)
    violations = validate_changed_paths(changed_paths, allowed_paths)
    result = parse_result_md(artifacts_dir)
    result.update({"workspace": str(worktree), "artifacts_dir": str(artifacts_dir), "changed_paths": changed_paths, "base_ref": comparison_ref})
    target_status = "review"
    if violations:
        result.update({"summary": "Runner blocked submission because Codex modified files outside the declared task scope.", "self_pass": False, "blocker": "Out-of-scope files: " + ", ".join(violations), "confidence": "low"})
        target_status = "failed"
    secret_findings = scan_paths_for_secrets(worktree, artifacts_dir, changed_paths)
    if secret_findings:
        result.update({"summary": "Runner blocked submission because potential secrets were found in task output.", "self_pass": False, "blocker": "Potential secrets detected in: " + ", ".join(secret_findings), "confidence": "low"})
        target_status = "failed"
    result_json = artifacts_dir / ".codex-result.json"
    result_json.write_text(json.dumps(result, indent=2), encoding="utf-8")
    subprocess.run([sys.executable, str(SCRIPTS_DIR / "queue_manager.py"), "submit-result", task_id, "--result-json", str(result_json), "--target-status", target_status], cwd=PROJECT_ROOT, check=True)
    return 0


def _submit_error(task_id: str, reason: str) -> None:
    artifacts_dir = ARTIFACTS_DIR / task_id
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    result = {"summary": f"Runner error: {reason}", "self_pass": False, "artifacts": [], "blocker": reason, "confidence": "low", "workspace": str(WORKTREES_DIR / task_id), "artifacts_dir": str(artifacts_dir), "changed_paths": []}
    result_path = artifacts_dir / ".codex-result.json"
    result_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    subprocess.run([sys.executable, str(SCRIPTS_DIR / "queue_manager.py"), "submit-result", task_id, "--result-json", str(result_path), "--target-status", "failed"], cwd=PROJECT_ROOT, capture_output=True, text=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run cc-duet Codex tasks in isolated worktrees")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--task-id")
    group.add_argument("--next", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.next:
        result = subprocess.run([sys.executable, str(SCRIPTS_DIR / "queue_manager.py"), "next"], cwd=PROJECT_ROOT, capture_output=True, text=True, check=True)
        payload = json.loads(result.stdout)
        if not payload.get("task"):
            log("No pending tasks.")
            return
        task_id = payload["task"]["id"]
    else:
        task_id = args.task_id
    sys.exit(run_task(task_id, dry_run=args.dry_run))


if __name__ == "__main__":
    main()
