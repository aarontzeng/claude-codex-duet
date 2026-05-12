#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from cc_duet import __version__

PACKAGE_ROOT = Path(__file__).resolve().parent
ASSETS_ROOT = PACKAGE_ROOT / "assets"
RUNTIME_SOURCE = ASSETS_ROOT / "runtime"
PROJECT_COMMAND_SOURCE = ASSETS_ROOT / "project-command" / "cc-duet.md"
GLOBAL_COMMAND_DIR = Path.home() / ".claude" / "commands" / "cc-duet"
GLOBAL_SETUP_COMMAND = GLOBAL_COMMAND_DIR / "setup.md"
RUNTIME_DIRNAME = ".cc-duet"
MANAGED_BLOCK_BEGIN = "# BEGIN cc-duet managed block"
MANAGED_BLOCK_END = "# END cc-duet managed block"
REQUIRED_RUNTIME_FILES = (
    "README.md",
    "scripts/create_task.py",
    "scripts/codex_runner.py",
    "scripts/queue_manager.py",
    "scripts/mcp_server.py",
    "hooks/settings-snippet.json",
    "agent-context/CONSTRAINTS.md",
    "agent-context/TASK_PROMPT_TEMPLATE.md",
    "agent-context/REVIEW_CRITERIA.md",
    "templates/task.json",
)
REQUIRED_QUEUE_DIRS = (
    "queue/pending",
    "queue/claimed",
    "queue/review",
    "queue/done",
    "queue/failed",
    "artifacts",
    "worktrees",
)


def _which(name: str) -> str | None:
    return shutil.which(name)


def _run(command: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, capture_output=True, text=True)


def _detail_line(stdout: str, stderr: str) -> str:
    text = stdout.strip() or stderr.strip()
    return text.splitlines()[0] if text else ""


def _status_entry(status: str, detail: str, **extra: str) -> dict[str, str]:
    payload = {"status": status, "detail": detail}
    payload.update({key: value for key, value in extra.items() if value})
    return payload


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_text_if_exists(path: Path) -> str | None:
    if path.exists():
        return path.read_text(encoding="utf-8")
    return None


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(text)
        temp_path = Path(handle.name)
    temp_path.replace(path)


def copy_tree(src: Path, dst: Path) -> None:
    for path in src.rglob("*"):
        relative = path.relative_to(src)
        target = dst / relative
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)


def render_gitignore_block(ignore_claude: bool) -> str:
    lines = [MANAGED_BLOCK_BEGIN, f"{RUNTIME_DIRNAME}/"]
    if ignore_claude:
        lines.append(".claude/")
    lines.append(MANAGED_BLOCK_END)
    return "\n".join(lines) + "\n"


def _repair_partial_gitignore_block(existing: str) -> str:
    lines = existing.splitlines()
    begin_index = next((index for index, line in enumerate(lines) if line == MANAGED_BLOCK_BEGIN), None)
    end_index = next((index for index, line in enumerate(lines) if line == MANAGED_BLOCK_END), None)
    managed_lines = {f"{RUNTIME_DIRNAME}/", ".claude/", ""}
    if begin_index is not None and end_index is None:
        stop = begin_index + 1
        while stop < len(lines) and lines[stop] in managed_lines:
            stop += 1
        lines = lines[:begin_index] + lines[stop:]
    elif end_index is not None and begin_index is None:
        start = end_index
        while start > 0 and lines[start - 1] in managed_lines:
            start -= 1
        lines = lines[:start] + lines[end_index + 1 :]
    elif begin_index is not None and end_index is not None and begin_index > end_index:
        lines = [line for line in lines if line not in {MANAGED_BLOCK_BEGIN, MANAGED_BLOCK_END}]
    repaired = "\n".join(lines)
    if existing.endswith("\n") and repaired:
        return repaired + "\n"
    return repaired


def render_gitignore_contents(existing: str, ignore_claude: bool) -> str:
    block = render_gitignore_block(ignore_claude)
    if MANAGED_BLOCK_BEGIN in existing and MANAGED_BLOCK_END in existing:
        start = existing.index(MANAGED_BLOCK_BEGIN)
        finish = existing.index(MANAGED_BLOCK_END, start) + len(MANAGED_BLOCK_END)
        if finish < len(existing) and existing[finish : finish + 1] == "\n":
            finish += 1
        return existing[:start] + block + existing[finish:]
    existing = _repair_partial_gitignore_block(existing)
    prefix = "" if not existing or existing.endswith("\n") else "\n"
    return existing + prefix + block


def ensure_gitignore_block(project_root: Path, ignore_claude: bool) -> Path:
    gitignore_path = project_root / ".gitignore"
    existing = _read_text_if_exists(gitignore_path) or ""
    updated = render_gitignore_contents(existing, ignore_claude)
    if updated != existing:
        _atomic_write_text(gitignore_path, updated)
    return gitignore_path


def hook_group() -> dict:
    snippet = json.loads((RUNTIME_SOURCE / "hooks" / "settings-snippet.json").read_text(encoding="utf-8"))
    return snippet["hooks"]["UserPromptSubmit"][0]


def _load_settings_payload(target: Path) -> dict:
    if target.exists():
        payload = json.loads(target.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"{target} must contain a top-level JSON object")
        return payload
    return {}


def _merge_hook_group(payload: dict, target: Path) -> dict:
    hooks = payload.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise ValueError(f"{target} hooks value must be a JSON object")

    user_prompt = hooks.setdefault("UserPromptSubmit", [])
    if not isinstance(user_prompt, list):
        raise ValueError(f"{target} hooks.UserPromptSubmit must be a JSON array")

    group = hook_group()
    normalized: list[dict] = []
    for item in user_prompt:
        if not isinstance(item, dict):
            raise ValueError(f"{target} hooks.UserPromptSubmit entries must be JSON objects")
        if item.get("type") == "command":
            command = item.get("command", "")
            if "user-prompt-submit.sh" in command or "cc-duet hook-dispatch" in command:
                continue
        normalized.append(item)

    if not any(item == group for item in normalized):
        normalized.append(group)

    hooks["UserPromptSubmit"] = normalized
    return payload


def render_claude_settings_text(settings_path: Path | None = None) -> str:
    target = settings_path or (Path.home() / ".claude" / "settings.json")
    payload = _merge_hook_group(_load_settings_payload(target), target)
    return json.dumps(payload, indent=2) + "\n"


def ensure_claude_settings_hook(settings_path: Path | None = None) -> Path:
    target = settings_path or (Path.home() / ".claude" / "settings.json")
    _atomic_write_text(target, render_claude_settings_text(target))
    return target


def resolve_project_root(target: Path) -> Path:
    if not _which("git"):
        raise RuntimeError("git is required but was not found in PATH")

    resolved = target.resolve()
    result = _run(["git", "rev-parse", "--show-toplevel"], cwd=resolved)
    if result.returncode != 0:
        raise RuntimeError(f"{resolved} is not inside a Git repository")
    return Path(result.stdout.strip()).resolve()


def validate_project_requirements(project_root: Path) -> None:
    if not _which("claude"):
        raise RuntimeError("Claude Code CLI ('claude') was not found in PATH")
    if not _which("codex"):
        raise RuntimeError("Codex CLI ('codex') was not found in PATH")

    worktree_check = _run(["git", "worktree", "list"], cwd=project_root)
    if worktree_check.returncode != 0:
        raise RuntimeError("git worktree is required but unavailable in this repository")


def render_runtime_manifest() -> dict:
    files: dict[str, str] = {}
    for path in sorted(RUNTIME_SOURCE.rglob("*")):
        if path.is_file():
            files[path.relative_to(RUNTIME_SOURCE).as_posix()] = _sha256_file(path)
    return {
        "schema_version": 1,
        "cc_duet_version": __version__,
        "runtime_dir": RUNTIME_DIRNAME,
        "files": files,
        "project_command_sha256": _sha256_file(PROJECT_COMMAND_SOURCE),
    }


def stage_runtime_assets(staging_root: Path) -> None:
    copy_tree(RUNTIME_SOURCE, staging_root)
    _atomic_write_text(staging_root / "manifest.json", json.dumps(render_runtime_manifest(), indent=2) + "\n")


def _restore_text_file(path: Path, original: str | None) -> None:
    if original is None:
        if path.exists():
            path.unlink()
        return
    _atomic_write_text(path, original)


def setup_project(project_target: Path, force: bool = False, settings_path: Path | None = None) -> tuple[Path, list[Path]]:
    settings_target = settings_path or (Path.home() / ".claude" / "settings.json")
    project_root = resolve_project_root(project_target)
    validate_project_requirements(project_root)

    runtime_target = project_root / RUNTIME_DIRNAME
    command_target = project_root / ".claude" / "commands" / "cc-duet.md"
    gitignore_path = project_root / ".gitignore"
    claude_dir_preexisting = (project_root / ".claude").exists()

    staged_settings = render_claude_settings_text(settings_target)
    gitignore_original = _read_text_if_exists(gitignore_path)
    existing_gitignore = gitignore_original or ""
    updated_gitignore = render_gitignore_contents(existing_gitignore, ignore_claude=not claude_dir_preexisting)
    project_command_text = PROJECT_COMMAND_SOURCE.read_text(encoding="utf-8")

    stage_dir = Path(tempfile.mkdtemp(prefix="cc-duet-stage-", dir=project_root))
    stage_runtime = stage_dir / RUNTIME_DIRNAME
    stage_runtime_assets(stage_runtime)

    runtime_backup_root: Path | None = None
    runtime_backup: Path | None = None
    runtime_written = False
    command_written = False
    gitignore_written = False
    settings_written = False

    command_original = _read_text_if_exists(command_target)
    settings_original = _read_text_if_exists(settings_target)

    try:
        if runtime_target.exists():
            if force:
                runtime_backup_root = Path(tempfile.mkdtemp(prefix="cc-duet-backup-", dir=project_root))
                runtime_backup = runtime_backup_root / runtime_target.name
                runtime_target.rename(runtime_backup)
                stage_runtime.rename(runtime_target)
                runtime_written = True
            else:
                shutil.rmtree(stage_runtime)
        else:
            stage_runtime.rename(runtime_target)
            runtime_written = True

        if force or not command_target.exists():
            _atomic_write_text(command_target, project_command_text)
            command_written = True

        if updated_gitignore != existing_gitignore:
            _atomic_write_text(gitignore_path, updated_gitignore)
            gitignore_written = True

        if settings_original != staged_settings:
            _atomic_write_text(settings_target, staged_settings)
            settings_written = True
    except Exception:
        if runtime_written and runtime_target.exists():
            shutil.rmtree(runtime_target, ignore_errors=True)
        if runtime_backup and runtime_backup.exists():
            runtime_backup.rename(runtime_target)
        if command_written:
            _restore_text_file(command_target, command_original)
        if gitignore_written:
            _restore_text_file(gitignore_path, gitignore_original)
        if settings_written:
            _restore_text_file(settings_target, settings_original)
        raise
    finally:
        shutil.rmtree(stage_dir, ignore_errors=True)
        if runtime_backup_root and runtime_backup_root.exists():
            shutil.rmtree(runtime_backup_root, ignore_errors=True)

    created = [runtime_target, command_target, gitignore_path, settings_target]
    return project_root, created


def upgrade_project(project_target: Path, settings_path: Path | None = None) -> tuple[Path, list[Path]]:
    return setup_project(project_target, force=True, settings_path=settings_path)


def render_global_setup_command() -> str:
    return """# /cc-duet:setup

Install the cc-duet project-local workflow into the current Git repository.

When the user runs this command:

1. Determine the project root with `git rev-parse --show-toplevel 2>/dev/null || pwd`
2. Run `cc-duet setup "<project-root>"`
3. Summarize what was added:
   - `.cc-duet/`
   - `.claude/commands/cc-duet.md`
   - `.gitignore` updates
4. Mention that `cc-duet setup` already merged the `UserPromptSubmit` hook into `~/.claude/settings.json`

Do not stop at planning. Execute the setup command directly.
"""


def install_global(force: bool = False, settings_path: Path | None = None) -> list[Path]:
    installed: list[Path] = []
    GLOBAL_COMMAND_DIR.mkdir(parents=True, exist_ok=True)
    if force or not GLOBAL_SETUP_COMMAND.exists():
        _atomic_write_text(GLOBAL_SETUP_COMMAND, render_global_setup_command())
    installed.append(GLOBAL_SETUP_COMMAND)
    installed.append(ensure_claude_settings_hook(settings_path))
    return installed


def _doctor_binary(name: str) -> dict[str, str]:
    path = _which(name)
    if not path:
        return _status_entry("missing", "not found in PATH")

    version_result = _run([path, "--version"])
    version = _detail_line(version_result.stdout, version_result.stderr)
    if version_result.returncode != 0 and not version:
        return _status_entry("warning", path, version_error="version probe failed")
    return _status_entry("ok", path, version=version or "reported no version text")


def _doctor_claude_settings(settings_file: Path) -> dict[str, str]:
    if not settings_file.exists():
        return _status_entry("warning", f"{settings_file} does not exist")

    try:
        payload = _load_settings_payload(settings_file)
        hooks = payload.get("hooks", {})
        ups = hooks.get("UserPromptSubmit", []) if isinstance(hooks, dict) else []
        if any(item == hook_group() for item in ups if isinstance(item, dict)):
            return _status_entry("ok", str(settings_file))
        return _status_entry("warning", str(settings_file), note="cc-duet UserPromptSubmit hook missing")
    except Exception as exc:  # noqa: BLE001
        return _status_entry("error", f"{settings_file}: {exc}")


def _doctor_project_command(project_root: Path) -> dict[str, str]:
    command_path = project_root / ".claude" / "commands" / "cc-duet.md"
    if not command_path.is_file():
        return _status_entry("warning", str(command_path), note="run `cc-duet setup .` to install the project command")

    current_hash = _sha256_file(command_path)
    expected_hash = _sha256_file(PROJECT_COMMAND_SOURCE)
    if current_hash != expected_hash:
        return _status_entry("warning", str(command_path), note="project command differs from packaged asset; run `cc-duet upgrade .`")
    return _status_entry("ok", str(command_path))


def _doctor_gitignore(project_root: Path) -> dict[str, str]:
    gitignore_path = project_root / ".gitignore"
    if not gitignore_path.exists():
        return _status_entry("warning", str(gitignore_path), note="managed block not installed")

    contents = gitignore_path.read_text(encoding="utf-8")
    if MANAGED_BLOCK_BEGIN not in contents or MANAGED_BLOCK_END not in contents:
        return _status_entry("warning", str(gitignore_path), note="cc-duet managed block missing")
    if f"{RUNTIME_DIRNAME}/" not in contents:
        return _status_entry("warning", str(gitignore_path), note=f"{RUNTIME_DIRNAME}/ ignore rule missing")
    return _status_entry("ok", str(gitignore_path))


def _doctor_runtime(project_root: Path) -> dict[str, dict[str, str]]:
    runtime_root = project_root / RUNTIME_DIRNAME
    report: dict[str, dict[str, str]] = {
        "runtime_root": _status_entry(
            "ok" if runtime_root.is_dir() else "warning",
            str(runtime_root),
            note="" if runtime_root.is_dir() else "run `cc-duet setup .` to scaffold the runtime",
        )
    }
    if not runtime_root.is_dir():
        report["manifest"] = _status_entry("warning", str(runtime_root / "manifest.json"), note="runtime not installed")
        report["required_files"] = _status_entry("warning", str(runtime_root), note="runtime not installed")
        report["queue_layout"] = _status_entry("warning", str(runtime_root), note="runtime not installed")
        report["runtime_drift"] = _status_entry("warning", str(runtime_root), note="runtime not installed")
        return report

    manifest_path = runtime_root / "manifest.json"
    if not manifest_path.is_file():
        report["manifest"] = _status_entry("warning", str(manifest_path), note="manifest missing; run `cc-duet upgrade .`")
        manifest: dict | None = None
    else:
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            version = str(manifest.get("cc_duet_version", ""))
            if version and version != __version__:
                report["manifest"] = _status_entry("warning", str(manifest_path), note=f"runtime version {version} differs from installed package {__version__}")
            else:
                report["manifest"] = _status_entry("ok", str(manifest_path), version=version or __version__)
        except Exception as exc:  # noqa: BLE001
            manifest = None
            report["manifest"] = _status_entry("error", f"{manifest_path}: {exc}")

    missing_files = [relative for relative in REQUIRED_RUNTIME_FILES if not (runtime_root / relative).is_file()]
    missing_dirs = [relative for relative in REQUIRED_QUEUE_DIRS if not (runtime_root / relative).is_dir()]
    report["required_files"] = _status_entry("ok" if not missing_files else "error", str(runtime_root), missing=", ".join(missing_files))
    report["queue_layout"] = _status_entry("ok" if not missing_dirs else "error", str(runtime_root), missing=", ".join(missing_dirs))

    if not manifest or not isinstance(manifest.get("files"), dict):
        report["runtime_drift"] = _status_entry("warning", str(runtime_root), note="cannot verify runtime asset drift without a valid manifest")
        return report

    changed: list[str] = []
    missing: list[str] = []
    for relative, expected_hash in manifest["files"].items():
        current_path = runtime_root / relative
        if not current_path.is_file():
            missing.append(relative)
            continue
        if _sha256_file(current_path) != expected_hash:
            changed.append(relative)

    if missing or changed:
        report["runtime_drift"] = _status_entry(
            "warning",
            str(runtime_root),
            missing=", ".join(missing),
            changed=", ".join(changed),
            note="runtime assets differ from the packaged scaffold; run `cc-duet upgrade .`",
        )
    else:
        report["runtime_drift"] = _status_entry("ok", str(runtime_root))
    return report


def _is_source_repo(project_root: Path) -> bool:
    return (project_root / "pyproject.toml").is_file() and (project_root / "src" / "cc_duet" / "assets" / "runtime").is_dir()


def _summarize_report(report: dict[str, dict[str, dict[str, str]]]) -> dict[str, str]:
    statuses: list[str] = []
    for section in report.values():
        statuses.extend(item["status"] for item in section.values())
    if any(status in {"error", "missing"} for status in statuses):
        return _status_entry("error", "cc-duet doctor found blocking issues")
    if any(status == "warning" for status in statuses):
        return _status_entry("warning", "cc-duet doctor found warnings")
    return _status_entry("ok", "cc-duet doctor checks passed")


def doctor(project_target: Path, settings_path: Path | None = None) -> dict[str, dict[str, dict[str, str]] | dict[str, str]]:
    settings_file = settings_path or (Path.home() / ".claude" / "settings.json")
    report: dict[str, dict[str, dict[str, str]] | dict[str, str]] = {
        "prerequisites": {name: _doctor_binary(name) for name in ("git", "claude", "codex")},
        "integration": {
            "global_setup_command": _status_entry(
                "ok" if GLOBAL_SETUP_COMMAND.is_file() else "warning",
                str(GLOBAL_SETUP_COMMAND),
                note="" if GLOBAL_SETUP_COMMAND.is_file() else "run `cc-duet install-global` to install it",
            ),
            "claude_settings": _doctor_claude_settings(settings_file),
        },
        "scaffold": {},
        "runtime": {},
    }

    # MCP status (informational — MCP is opt-in, not required)
    try:
        mcp_project_root = resolve_project_root(project_target)
        mcp_json_path = mcp_project_root / ".mcp.json"
        mcp_server_script = mcp_project_root / RUNTIME_DIRNAME / "scripts" / "mcp_server.py"
        if not mcp_json_path.is_file():
            report["integration"]["mcp"] = _status_entry("ok", str(mcp_json_path), note="MCP not configured (opt-in; run `cc-duet mcp-config .` for setup instructions)")
        elif not mcp_server_script.is_file():
            report["integration"]["mcp"] = _status_entry("warning", str(mcp_json_path), note=".mcp.json exists but .cc-duet/scripts/mcp_server.py is missing; run `cc-duet upgrade .`")
        else:
            try:
                mcp_cfg = json.loads(mcp_json_path.read_text(encoding="utf-8"))
                servers = mcp_cfg.get("mcpServers", {})
                if "cc-duet" in servers:
                    report["integration"]["mcp"] = _status_entry("ok", str(mcp_json_path), note="MCP configured with cc-duet server")
                else:
                    report["integration"]["mcp"] = _status_entry("ok", str(mcp_json_path), note=".mcp.json exists but no 'cc-duet' server entry; run `cc-duet mcp-config .` for the snippet")
            except (json.JSONDecodeError, OSError):
                report["integration"]["mcp"] = _status_entry("warning", str(mcp_json_path), note=".mcp.json exists but is not valid JSON")
    except RuntimeError:
        report["integration"]["mcp"] = _status_entry("ok", "skipped", note="MCP check skipped (not a git project)")

    try:
        project_root = resolve_project_root(project_target)
        report["scaffold"]["project_root"] = _status_entry("ok", str(project_root))
        worktree_check = _run(["git", "worktree", "list"], cwd=project_root)
        report["scaffold"]["git_worktree"] = _status_entry(
            "ok" if worktree_check.returncode == 0 else "error",
            (worktree_check.stdout or worktree_check.stderr).strip() or "available",
        )
        if _is_source_repo(project_root):
            report["integration"]["global_setup_command"] = _status_entry(
                "ok",
                str(GLOBAL_SETUP_COMMAND),
                note="global install is optional when validating the package source repo",
            )
            report["scaffold"]["gitignore"] = _status_entry("ok", str(project_root / ".gitignore"), note="source repo is package-only")
            report["scaffold"]["project_command"] = _status_entry(
                "ok",
                str(project_root / ".claude" / "commands" / "cc-duet.md"),
                note="project command is only expected in target repos",
            )
            report["runtime"] = {
                "runtime_root": _status_entry("ok", str(project_root / RUNTIME_DIRNAME), note="source repo does not install target runtime"),
                "manifest": _status_entry("ok", str(RUNTIME_SOURCE), note="manifest is generated when scaffolding target repos"),
                "required_files": _status_entry("ok", str(RUNTIME_SOURCE), note="runtime assets are packaged under src/cc_duet/assets"),
                "queue_layout": _status_entry("ok", str(RUNTIME_SOURCE), note="queue layout is validated from packaged scaffold assets"),
                "runtime_drift": _status_entry("ok", str(RUNTIME_SOURCE), note="source repo is canonical scaffold source"),
            }
        else:
            report["scaffold"]["gitignore"] = _doctor_gitignore(project_root)
            report["scaffold"]["project_command"] = _doctor_project_command(project_root)
            report["runtime"] = _doctor_runtime(project_root)
    except RuntimeError as exc:
        report["scaffold"]["project_root"] = _status_entry("error", str(exc))
        report["scaffold"]["git_worktree"] = _status_entry("error", "skipped because project root check failed")
        report["scaffold"]["gitignore"] = _status_entry("warning", "skipped because project root check failed")
        report["scaffold"]["project_command"] = _status_entry("warning", "skipped because project root check failed")
        report["runtime"] = {
            "runtime_root": _status_entry("warning", "skipped because project root check failed"),
            "manifest": _status_entry("warning", "skipped because project root check failed"),
            "required_files": _status_entry("warning", "skipped because project root check failed"),
            "queue_layout": _status_entry("warning", "skipped because project root check failed"),
            "runtime_drift": _status_entry("warning", "skipped because project root check failed"),
        }

    report["summary"] = _summarize_report(
        {
            "prerequisites": report["prerequisites"],
            "integration": report["integration"],
            "scaffold": report["scaffold"],
            "runtime": report["runtime"],
        }
    )
    return report


def doctor_exit_code(report: dict[str, dict[str, dict[str, str]] | dict[str, str]], strict: bool = False) -> int:
    summary = report["summary"]["status"]
    if summary == "error":
        return 1
    if strict and summary == "warning":
        return 1
    return 0


def emit_hook_context(project_target: Path) -> int:
    try:
        project_root = resolve_project_root(project_target)
    except RuntimeError:
        return 0

    review_dir = project_root / RUNTIME_DIRNAME / "queue" / "review"
    if not review_dir.is_dir():
        return 0

    entries = []
    for path in sorted(review_dir.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        entries.append(
            {
                "id": payload.get("id", "unknown"),
                "title": payload.get("title", "?"),
                "summary": ((payload.get("result") or {}).get("summary") or "")[:120],
            }
        )

    if not entries:
        return 0

    context = f"[cc-duet inbox] {len(entries)} Codex task(s) await review:\n\n"
    for entry in entries:
        context += f"- {entry['id']} — {entry['title']}\n"
        context += f"  Summary: {entry['summary']}\n\n"
    context += "Review with: python3 .cc-duet/scripts/queue_manager.py review <task-id> --decision approved --score 9"
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "UserPromptSubmit",
                    "additionalContext": context,
                }
            }
        )
    )
    return 0


def mcp_config(project_target: Path) -> dict:
    """Generate the .mcp.json configuration snippet for a target project.

    Returns the full .mcp.json content as a dict. Does not write any files.
    """
    project_root = resolve_project_root(project_target)
    server_path = str(project_root / RUNTIME_DIRNAME / "scripts" / "mcp_server.py")
    return {
        "mcpServers": {
            "cc-duet": {
                "command": "python3",
                "args": [server_path],
            }
        }
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Install and scaffold the cc-duet workflow into Git projects")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    setup_parser = sub.add_parser("setup", help="Scaffold cc-duet into a Git project")
    setup_parser.add_argument("target", nargs="?", default=".")
    setup_parser.add_argument("--force", action="store_true")

    upgrade_parser = sub.add_parser("upgrade", help="Refresh an installed cc-duet runtime to the current packaged version")
    upgrade_parser.add_argument("target", nargs="?", default=".")

    install_parser = sub.add_parser("install-global", help="Install the global /cc-duet:setup Claude command and hook")
    install_parser.add_argument("--force", action="store_true")

    doctor_parser = sub.add_parser("doctor", help="Check local prerequisites and scaffold health for cc-duet")
    doctor_parser.add_argument("target", nargs="?", default=".")
    doctor_parser.add_argument("--strict", action="store_true", help="Return a non-zero exit code on warnings as well as errors")

    hook_parser = sub.add_parser("hook-dispatch", help="Emit Claude hook context for pending cc-duet review tasks")
    hook_parser.add_argument("target", nargs="?", default=".")

    mcp_parser = sub.add_parser("mcp-config", help="Print the MCP server configuration for a target project")
    mcp_parser.add_argument("target", nargs="?", default=".")

    args = parser.parse_args()

    if args.command == "setup":
        project_root, created = setup_project(Path(args.target), force=args.force)
        print(f"Installed cc-duet into {project_root}:")
        for path in created:
            print(f"- {path}")
        return

    if args.command == "upgrade":
        project_root, created = upgrade_project(Path(args.target))
        print(f"Upgraded cc-duet in {project_root}:")
        for path in created:
            print(f"- {path}")
        return

    if args.command == "install-global":
        installed = install_global(force=args.force)
        print("Installed global cc-duet tooling:")
        for path in installed:
            print(f"- {path}")
        return

    if args.command == "doctor":
        report = doctor(Path(args.target))
        print(json.dumps(report, indent=2))
        raise SystemExit(doctor_exit_code(report, strict=args.strict))

    if args.command == "hook-dispatch":
        raise SystemExit(emit_hook_context(Path(args.target)))

    if args.command == "mcp-config":
        config = mcp_config(Path(args.target))
        print(json.dumps(config, indent=2))
        print("\n# Save the above as .mcp.json in your project root to enable MCP.", file=sys.stderr)
        return


if __name__ == "__main__":
    main()
