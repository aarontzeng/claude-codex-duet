from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cc_duet import cli as duet_cli


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
