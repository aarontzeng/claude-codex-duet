from __future__ import annotations

import argparse
import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cc_duet import cli as duet_cli


def load_module(module_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ScaffoldRuntimeTestCase(unittest.TestCase):
    def test_scaffolded_project_can_create_task_and_dry_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            project_root = Path(tmp_dir)
            subprocess.run(["git", "init"], cwd=project_root, check=True, capture_output=True, text=True)
            (project_root / "src").mkdir()

            settings_path = project_root / "settings.json"
            with mock.patch.object(duet_cli, "validate_project_requirements", lambda _: None):
                duet_cli.setup_project(project_root, settings_path=settings_path)

            create = subprocess.run(
                [
                    sys.executable,
                    str(project_root / ".cc-duet" / "scripts" / "create_task.py"),
                    "--title",
                    "Hello world",
                    "--spec",
                    "Create a bounded change.",
                    "--paths",
                    "src/**",
                    "--acceptance",
                    "Task file exists",
                ],
                cwd=project_root,
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertIn("Created task:", create.stdout)

            pending = list((project_root / ".cc-duet" / "queue" / "pending").glob("*.json"))
            self.assertEqual(len(pending), 1)
            payload = json.loads(pending[0].read_text(encoding="utf-8"))
            self.assertEqual(payload["project_paths"], ["src/**"])

            dry_run = subprocess.run(
                [
                    sys.executable,
                    str(project_root / ".cc-duet" / "scripts" / "codex_runner.py"),
                    "--next",
                    "--dry-run",
                ],
                cwd=project_root,
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertIn("DRY RUN - would prepare:", dry_run.stdout)
            self.assertTrue((project_root / ".claude" / "commands" / "cc-duet.md").exists())

    def test_runtime_detects_committed_changes_relative_to_task_start(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            project_root = Path(tmp_dir)
            subprocess.run(["git", "init"], cwd=project_root, check=True, capture_output=True, text=True)
            subprocess.run(["git", "config", "user.name", "Test User"], cwd=project_root, check=True, capture_output=True, text=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=project_root, check=True, capture_output=True, text=True)
            (project_root / "src").mkdir()
            (project_root / "src" / "tracked.txt").write_text("base\n", encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=project_root, check=True, capture_output=True, text=True)
            subprocess.run(["git", "commit", "-m", "initial"], cwd=project_root, check=True, capture_output=True, text=True)

            settings_path = project_root / "settings.json"
            with mock.patch.object(duet_cli, "validate_project_requirements", lambda _: None):
                duet_cli.setup_project(project_root, settings_path=settings_path)

            runner = load_module("runtime_codex_runner", project_root / ".cc-duet" / "scripts" / "codex_runner.py")
            worktree = runner.ensure_worktree({"id": "t-committed-change", "base_ref": "HEAD"})
            comparison_ref = runner._git_stdout(worktree, "rev-parse", "HEAD")
            (worktree / "src" / "tracked.txt").write_text("changed\n", encoding="utf-8")
            subprocess.run(["git", "add", "src/tracked.txt"], cwd=worktree, check=True, capture_output=True, text=True)
            subprocess.run(["git", "commit", "-m", "change"], cwd=worktree, check=True, capture_output=True, text=True)

            changed_paths = runner.get_changed_paths(worktree, comparison_ref)
            self.assertEqual(changed_paths, ["src/tracked.txt"])

    def test_queue_manager_avoids_same_second_task_id_collisions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            project_root = Path(tmp_dir)
            subprocess.run(["git", "init"], cwd=project_root, check=True, capture_output=True, text=True)
            subprocess.run(["git", "config", "user.name", "Test User"], cwd=project_root, check=True, capture_output=True, text=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=project_root, check=True, capture_output=True, text=True)
            (project_root / "src").mkdir()
            (project_root / "src" / "tracked.txt").write_text("base\n", encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=project_root, check=True, capture_output=True, text=True)
            subprocess.run(["git", "commit", "-m", "initial"], cwd=project_root, check=True, capture_output=True, text=True)

            settings_path = project_root / "settings.json"
            with mock.patch.object(duet_cli, "validate_project_requirements", lambda _: None):
                duet_cli.setup_project(project_root, settings_path=settings_path)

            queue_manager = load_module("runtime_queue_manager", project_root / ".cc-duet" / "scripts" / "queue_manager.py")
            args = argparse.Namespace(
                title="Same title",
                spec="Create a bounded change.",
                priority=2,
                acceptance=None,
                tags=None,
                model=None,
                max_runtime=None,
                env_vars=None,
                created_by="human",
                project_paths=["src/**"],
                base_ref="HEAD",
                max_rejections=3,
            )
            stdout = io.StringIO()
            with (
                mock.patch.object(queue_manager, "_task_id", return_value="t-20260512T000000"),
                mock.patch("sys.stdout", stdout),
            ):
                queue_manager.cmd_create(args)
                queue_manager.cmd_create(args)

            pending_paths = list((project_root / ".cc-duet" / "queue" / "pending").glob("*.json"))
            self.assertEqual({path.stem for path in pending_paths}, {"t-20260512T000000-same-title", "t-20260512T000000-same-title-2"})
