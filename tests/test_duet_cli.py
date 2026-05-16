from __future__ import annotations

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


class DuetCliTestCase(unittest.TestCase):
    def test_setup_project_scaffolds_expected_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            project_root = Path(tmp_dir)
            subprocess.run(["git", "init"], cwd=project_root, check=True, capture_output=True, text=True)
            (project_root / ".gitignore").write_text(".venv/\n", encoding="utf-8")
            with mock.patch.object(duet_cli, "validate_project_requirements", lambda _: None):
                resolved_root, created = duet_cli.setup_project(project_root, settings_path=project_root / "settings.json")

            self.assertEqual(resolved_root, project_root.resolve())
            self.assertTrue((project_root / ".cc-duet" / "scripts" / "queue_manager.py").exists())
            self.assertTrue((project_root / ".claude" / "commands" / "cc-duet.md").exists())
            gitignore = (project_root / ".gitignore").read_text(encoding="utf-8")
            self.assertIn(".cc-duet/", gitignore)
            self.assertIn(".claude/", gitignore)
            self.assertTrue(any(path.name == ".gitignore" for path in created))

    def test_setup_project_preserves_existing_claude_policy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            project_root = Path(tmp_dir)
            subprocess.run(["git", "init"], cwd=project_root, check=True, capture_output=True, text=True)
            (project_root / ".claude").mkdir()
            (project_root / ".claude" / "settings.local.json").write_text("{}\n", encoding="utf-8")

            with mock.patch.object(duet_cli, "validate_project_requirements", lambda _: None):
                duet_cli.setup_project(project_root, settings_path=project_root / "settings.json")

            gitignore = (project_root / ".gitignore").read_text(encoding="utf-8")
            self.assertIn(".cc-duet/", gitignore)
            self.assertNotIn(".claude/\n", gitignore)

    def test_gitignore_block_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            project_root = Path(tmp_dir)
            gitignore_path = project_root / ".gitignore"
            gitignore_path.write_text("", encoding="utf-8")
            duet_cli.ensure_gitignore_block(project_root, ignore_claude=True)
            first = gitignore_path.read_text(encoding="utf-8")
            duet_cli.ensure_gitignore_block(project_root, ignore_claude=True)
            second = gitignore_path.read_text(encoding="utf-8")
            self.assertEqual(first, second)

    def test_gitignore_block_updates_managed_policy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            project_root = Path(tmp_dir)
            gitignore_path = project_root / ".gitignore"
            duet_cli.ensure_gitignore_block(project_root, ignore_claude=True)
            duet_cli.ensure_gitignore_block(project_root, ignore_claude=False)
            updated = gitignore_path.read_text(encoding="utf-8")
            self.assertIn(".cc-duet/", updated)
            self.assertNotIn(".claude/\n", updated)

    def test_render_gitignore_contents_recovers_partial_managed_block(self) -> None:
        existing = "\n".join(
            [
                "*.log",
                duet_cli.MANAGED_BLOCK_BEGIN,
                ".cc-duet/",
                ".claude/",
                "",
                "node_modules/",
            ]
        )
        updated = duet_cli.render_gitignore_contents(existing, ignore_claude=True)
        self.assertEqual(updated.count(duet_cli.MANAGED_BLOCK_BEGIN), 1)
        self.assertEqual(updated.count(duet_cli.MANAGED_BLOCK_END), 1)
        self.assertIn("*.log", updated)
        self.assertIn("node_modules/", updated)

    def test_render_global_setup_command_mentions_cc_duet_setup(self) -> None:
        command = duet_cli.render_global_setup_command()
        self.assertIn("cc-duet setup", command)

    def test_settings_hook_merge_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings_path = Path(tmp_dir) / "settings.json"
            duet_cli.ensure_claude_settings_hook(settings_path)
            first = settings_path.read_text(encoding="utf-8")
            duet_cli.ensure_claude_settings_hook(settings_path)
            second = settings_path.read_text(encoding="utf-8")
            self.assertEqual(first, second)
            payload = json.loads(second)
            self.assertIn("hooks", payload)
            self.assertIn("UserPromptSubmit", payload["hooks"])
            self.assertEqual(payload["hooks"]["UserPromptSubmit"][0]["matcher"], "")

    def test_settings_hook_rewrites_legacy_flat_entry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings_path = Path(tmp_dir) / "settings.json"
            settings_path.write_text(
                json.dumps(
                    {
                        "hooks": {
                            "UserPromptSubmit": [
                                {
                                    "type": "command",
                                    "command": "bash -lc 'repo_root=$(git rev-parse --show-toplevel 2>/dev/null || pwd); DUET_ROOT=\"$repo_root/.cc-duet\" bash \"$repo_root/.cc-duet/hooks/user-prompt-submit.sh\"'",
                                }
                            ]
                        }
                    }
                ),
                encoding="utf-8",
            )
            duet_cli.ensure_claude_settings_hook(settings_path)
            payload = json.loads(settings_path.read_text(encoding="utf-8"))
            group = payload["hooks"]["UserPromptSubmit"][0]
            self.assertEqual(group["matcher"], "")
            self.assertEqual(group["hooks"][0]["type"], "command")
            self.assertIn("cc-duet hook-dispatch", group["hooks"][0]["command"])

    def test_resolve_project_root_requires_git_repo(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            with self.assertRaises(RuntimeError):
                duet_cli.resolve_project_root(Path(tmp_dir))

    def test_doctor_reports_missing_tools(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            project_root = Path(tmp_dir)
            subprocess.run(["git", "init"], cwd=project_root, check=True, capture_output=True, text=True)
            with mock.patch.object(duet_cli, "_which", side_effect=lambda name: "/usr/bin/git" if name == "git" else None):
                report = duet_cli.doctor(project_root, settings_path=project_root / "settings.json")
            self.assertEqual(report["prerequisites"]["git"]["status"], "ok")
            self.assertEqual(report["prerequisites"]["claude"]["status"], "missing")
            self.assertEqual(report["prerequisites"]["codex"]["status"], "missing")
            self.assertEqual(report["integration"]["claude_settings"]["status"], "warning")
            self.assertEqual(report["summary"]["status"], "error")

    def test_doctor_reports_scaffolded_runtime_health(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            project_root = Path(tmp_dir)
            subprocess.run(["git", "init"], cwd=project_root, check=True, capture_output=True, text=True)
            settings_path = project_root / "settings.json"
            with mock.patch.object(duet_cli, "validate_project_requirements", lambda _: None):
                duet_cli.setup_project(project_root, settings_path=settings_path)

            with mock.patch.object(
                duet_cli,
                "_which",
                side_effect=lambda name: "/usr/bin/git" if name == "git" else sys.executable,
            ):
                report = duet_cli.doctor(project_root, settings_path=settings_path)

            self.assertEqual(report["integration"]["claude_settings"]["status"], "ok")
            self.assertEqual(report["scaffold"]["project_command"]["status"], "ok")
            self.assertEqual(report["runtime"]["runtime_root"]["status"], "ok")
            self.assertEqual(report["runtime"]["required_files"]["status"], "ok")
            self.assertEqual(report["runtime"]["queue_layout"]["status"], "ok")
            self.assertEqual(report["runtime"]["manifest"]["status"], "ok")
            self.assertEqual(report["runtime"]["runtime_drift"]["status"], "ok")

    def test_doctor_treats_source_repo_as_package_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            project_root = Path(tmp_dir)
            subprocess.run(["git", "init"], cwd=project_root, check=True, capture_output=True, text=True)
            settings_path = project_root / "settings.json"
            duet_cli.ensure_claude_settings_hook(settings_path)

            with (
                mock.patch.object(duet_cli, "_is_source_repo", return_value=True),
                mock.patch.object(
                    duet_cli,
                    "_which",
                    side_effect=lambda name: "/usr/bin/git" if name == "git" else sys.executable,
                ),
            ):
                report = duet_cli.doctor(project_root, settings_path=settings_path)

            self.assertEqual(report["scaffold"]["gitignore"]["status"], "ok")
            self.assertEqual(report["runtime"]["runtime_root"]["status"], "ok")
            self.assertEqual(report["summary"]["status"], "ok")

    def test_doctor_detects_runtime_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            project_root = Path(tmp_dir)
            subprocess.run(["git", "init"], cwd=project_root, check=True, capture_output=True, text=True)
            settings_path = project_root / "settings.json"
            with mock.patch.object(duet_cli, "validate_project_requirements", lambda _: None):
                duet_cli.setup_project(project_root, settings_path=settings_path)
            target = project_root / ".cc-duet" / "scripts" / "create_task.py"
            target.write_text(target.read_text(encoding="utf-8") + "\n# local drift\n", encoding="utf-8")

            with mock.patch.object(
                duet_cli,
                "_which",
                side_effect=lambda name: "/usr/bin/git" if name == "git" else sys.executable,
            ):
                report = duet_cli.doctor(project_root, settings_path=settings_path)

            self.assertEqual(report["runtime"]["runtime_drift"]["status"], "warning")

    def test_setup_rolls_back_when_settings_are_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            project_root = Path(tmp_dir)
            subprocess.run(["git", "init"], cwd=project_root, check=True, capture_output=True, text=True)
            settings_path = project_root / "settings.json"
            settings_path.write_text("{not-json}\n", encoding="utf-8")

            with (
                self.assertRaises(json.JSONDecodeError),
                mock.patch.object(duet_cli, "validate_project_requirements", lambda _: None),
            ):
                duet_cli.setup_project(project_root, settings_path=settings_path)

            self.assertFalse((project_root / ".cc-duet").exists())
            self.assertFalse((project_root / ".claude" / "commands" / "cc-duet.md").exists())

    def test_doctor_exit_code_respects_strict_mode(self) -> None:
        warning_report = {
            "summary": {"status": "warning", "detail": "warnings"},
        }
        error_report = {
            "summary": {"status": "error", "detail": "errors"},
        }
        ok_report = {
            "summary": {"status": "ok", "detail": "ok"},
        }
        self.assertEqual(duet_cli.doctor_exit_code(ok_report), 0)
        self.assertEqual(duet_cli.doctor_exit_code(warning_report), 0)
        self.assertEqual(duet_cli.doctor_exit_code(warning_report, strict=True), 1)
        self.assertEqual(duet_cli.doctor_exit_code(error_report), 1)

    def test_hook_dispatch_emits_review_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            project_root = Path(tmp_dir)
            subprocess.run(["git", "init"], cwd=project_root, check=True, capture_output=True, text=True)
            review_dir = project_root / ".cc-duet" / "queue" / "review"
            review_dir.mkdir(parents=True)
            payload = {
                "id": "t-1",
                "title": "Review me",
                "result": {"summary": "Looks good"},
            }
            (review_dir / "t-1.json").write_text(json.dumps(payload), encoding="utf-8")
            stdout = io.StringIO()
            with mock.patch("sys.stdout", stdout):
                code = duet_cli.emit_hook_context(project_root)
            emitted = json.loads(stdout.getvalue())
            self.assertEqual(code, 0)
            self.assertEqual(emitted["hookSpecificOutput"]["hookEventName"], "UserPromptSubmit")
            self.assertIn("t-1", emitted["hookSpecificOutput"]["additionalContext"])

    def test_runtime_runner_does_not_use_removed_approval_flag(self) -> None:
        runner = (duet_cli.RUNTIME_SOURCE / "scripts" / "codex_runner.py").read_text(encoding="utf-8")
        self.assertNotIn('"exec", "-a", "never"', runner)

    def test_runtime_runner_does_not_force_hardcoded_default_model(self) -> None:
        runner = (duet_cli.RUNTIME_SOURCE / "scripts" / "codex_runner.py").read_text(encoding="utf-8")
        self.assertNotIn('"o4-mini"', runner)

    def test_mcp_config_returns_valid_server_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            project_root = Path(tmp_dir)
            subprocess.run(["git", "init"], cwd=project_root, check=True, capture_output=True, text=True)
            with mock.patch.object(duet_cli, "validate_project_requirements", lambda _: None):
                duet_cli.setup_project(project_root, settings_path=project_root / "settings.json")
            config = duet_cli.mcp_config(project_root)
            self.assertIn("mcpServers", config)
            self.assertIn("cc-duet", config["mcpServers"])
            server = config["mcpServers"]["cc-duet"]
            self.assertEqual(server["command"], "python3")
            self.assertTrue(server["args"][0].endswith("mcp_server.py"))

    def test_mcp_config_fails_without_setup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            project_root = Path(tmp_dir)
            subprocess.run(["git", "init"], cwd=project_root, check=True, capture_output=True, text=True)
            with self.assertRaises(RuntimeError):
                duet_cli.mcp_config(project_root)

    def test_global_status_reads_scaffold_queue(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            project_root = Path(tmp_dir)
            subprocess.run(["git", "init"], cwd=project_root, check=True, capture_output=True, text=True)
            with mock.patch.object(duet_cli, "validate_project_requirements", lambda _: None):
                duet_cli.setup_project(project_root, settings_path=project_root / "settings.json")
            task_path = project_root / ".cc-duet" / "queue" / "pending" / "t-status.json"
            task_path.write_text(
                json.dumps({"id": "t-status", "status": "pending", "priority": 2, "title": "Status", "created_at": "2026-05-16T00:00:00+00:00"}),
                encoding="utf-8",
            )

            stdout = io.StringIO()
            with mock.patch("sys.argv", ["cc-duet", "status", str(project_root)]), mock.patch("sys.stdout", stdout):
                duet_cli.main()

            self.assertEqual(stdout.getvalue().strip(), "1 pending")

    def test_global_gc_removes_done_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            project_root = Path(tmp_dir)
            subprocess.run(["git", "init"], cwd=project_root, check=True, capture_output=True, text=True)
            with mock.patch.object(duet_cli, "validate_project_requirements", lambda _: None):
                duet_cli.setup_project(project_root, settings_path=project_root / "settings.json")
            (project_root / ".cc-duet" / "queue" / "done" / "t-done.json").write_text(
                json.dumps({"id": "t-done", "status": "done", "priority": 2, "title": "Done", "created_at": "2026-05-16T00:00:00+00:00"}),
                encoding="utf-8",
            )
            (project_root / ".cc-duet" / "artifacts" / "t-done").mkdir(parents=True)

            stdout = io.StringIO()
            with mock.patch("sys.argv", ["cc-duet", "gc", str(project_root)]), mock.patch("sys.stdout", stdout):
                duet_cli.main()

            self.assertIn("Removed 1 artifact dir(s): t-done", stdout.getvalue())
            self.assertFalse((project_root / ".cc-duet" / "artifacts" / "t-done").exists())

    def test_doctor_reports_mcp_not_configured(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            project_root = Path(tmp_dir)
            subprocess.run(["git", "init"], cwd=project_root, check=True, capture_output=True, text=True)
            with mock.patch.object(duet_cli, "validate_project_requirements", lambda _: None):
                duet_cli.setup_project(project_root, settings_path=project_root / "settings.json")
            report = duet_cli.doctor(project_root, settings_path=project_root / "settings.json")
            mcp_status = report["integration"]["mcp"]
            self.assertEqual(mcp_status["status"], "ok")
            self.assertIn("opt-in", mcp_status["note"])

    def test_doctor_detects_configured_mcp_server(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            project_root = Path(tmp_dir)
            subprocess.run(["git", "init"], cwd=project_root, check=True, capture_output=True, text=True)
            with mock.patch.object(duet_cli, "validate_project_requirements", lambda _: None):
                duet_cli.setup_project(project_root, settings_path=project_root / "settings.json")
            mcp_json = {"mcpServers": {"cc-duet": {"command": "python3", "args": [".cc-duet/scripts/mcp_server.py"]}}}
            (project_root / ".mcp.json").write_text(json.dumps(mcp_json), encoding="utf-8")
            report = duet_cli.doctor(project_root, settings_path=project_root / "settings.json")
            mcp_status = report["integration"]["mcp"]
            self.assertEqual(mcp_status["status"], "ok")
            self.assertIn("configured", mcp_status["note"])

    def test_doctor_no_false_warning_for_unrelated_mcp_json(self) -> None:
        """A .mcp.json with only other servers should not warn about missing mcp_server.py."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            project_root = Path(tmp_dir)
            subprocess.run(["git", "init"], cwd=project_root, check=True, capture_output=True, text=True)
            # No cc-duet setup, but has a .mcp.json for another server
            (project_root / ".mcp.json").write_text(json.dumps({"mcpServers": {"other-tool": {"command": "node", "args": ["server.js"]}}}), encoding="utf-8")
            report = duet_cli.doctor(project_root, settings_path=project_root / "settings.json")
            mcp_status = report["integration"]["mcp"]
            self.assertEqual(mcp_status["status"], "ok")
            self.assertNotIn("missing", mcp_status.get("note", ""))

    def test_doctor_handles_non_object_mcp_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            project_root = Path(tmp_dir)
            subprocess.run(["git", "init"], cwd=project_root, check=True, capture_output=True, text=True)
            (project_root / ".mcp.json").write_text("[]", encoding="utf-8")
            report = duet_cli.doctor(project_root, settings_path=project_root / "settings.json")
            mcp_status = report["integration"]["mcp"]
            self.assertEqual(mcp_status["status"], "warning")
            self.assertIn("not an object", mcp_status["note"])
