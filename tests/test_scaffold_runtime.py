from __future__ import annotations

import argparse
import importlib.util
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cc_duet import cli as duet_cli


def load_module(module_name: str, path: Path):
    # Evict cached runtime modules so each scaffold gets a fresh load
    # pointing to its own temp directory.
    for key in list(sys.modules):
        if key in ("queue_manager", "mcp_server") or key.startswith("runtime_"):
            del sys.modules[key]
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


class McpServerTestCase(unittest.TestCase):
    """Tests for the MCP stdio server (mcp_server.py)."""

    def _scaffold(self) -> tuple[Path, object]:
        """Create a scaffolded project and return (project_root, mcp_server module)."""
        tmp_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp_dir, ignore_errors=True)
        project_root = Path(tmp_dir)
        subprocess.run(["git", "init"], cwd=project_root, check=True, capture_output=True, text=True)
        subprocess.run(["git", "config", "user.name", "Test User"], cwd=project_root, check=True, capture_output=True, text=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=project_root, check=True, capture_output=True, text=True)
        (project_root / "src").mkdir()
        subprocess.run(["git", "add", "."], cwd=project_root, check=True, capture_output=True, text=True)
        subprocess.run(["git", "commit", "-m", "initial", "--allow-empty"], cwd=project_root, check=True, capture_output=True, text=True)
        settings_path = project_root / "settings.json"
        with mock.patch.object(duet_cli, "validate_project_requirements", lambda _: None):
            duet_cli.setup_project(project_root, settings_path=settings_path)
        mcp = load_module("runtime_mcp_server", project_root / ".cc-duet" / "scripts" / "mcp_server.py")
        return project_root, mcp

    def test_initialize_returns_capabilities(self) -> None:
        _, mcp = self._scaffold()
        response = mcp.handle_request({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        self.assertEqual(response["id"], 1)
        result = response["result"]
        self.assertEqual(result["protocolVersion"], "2024-11-05")
        self.assertIn("tools", result["capabilities"])
        self.assertEqual(result["serverInfo"]["name"], "cc-duet")

    def test_tools_list_returns_all_tools(self) -> None:
        _, mcp = self._scaffold()
        response = mcp.handle_request({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        tools = response["result"]["tools"]
        tool_names = {tool["name"] for tool in tools}
        self.assertIn("cc_duet_create_task", tool_names)
        self.assertIn("cc_duet_list_tasks", tool_names)
        self.assertIn("cc_duet_review_task", tool_names)
        self.assertEqual(len(tools), 7)

    def test_notification_returns_none(self) -> None:
        _, mcp = self._scaffold()
        response = mcp.handle_request({"jsonrpc": "2.0", "method": "notifications/initialized"})
        self.assertIsNone(response)

    def test_unknown_method_returns_error(self) -> None:
        _, mcp = self._scaffold()
        response = mcp.handle_request({"jsonrpc": "2.0", "id": 3, "method": "nonexistent", "params": {}})
        self.assertIn("error", response)
        self.assertEqual(response["error"]["code"], -32601)

    def test_create_and_list_tasks_via_tools_call(self) -> None:
        project_root, mcp = self._scaffold()
        # Create a task via MCP
        create_response = mcp.handle_request({
            "jsonrpc": "2.0", "id": 10, "method": "tools/call",
            "params": {"name": "cc_duet_create_task", "arguments": {"title": "MCP test", "spec": "Validate MCP", "project_paths": ["src/**"]}},
        })
        create_result = json.loads(create_response["result"]["content"][0]["text"])
        self.assertIn("task_id", create_result)
        self.assertIn("path", create_result)
        task_id = create_result["task_id"]

        # List tasks and find our task
        list_response = mcp.handle_request({
            "jsonrpc": "2.0", "id": 11, "method": "tools/call",
            "params": {"name": "cc_duet_list_tasks", "arguments": {"status": "pending"}},
        })
        tasks = json.loads(list_response["result"]["content"][0]["text"])
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["id"], task_id)

        # Get the specific task
        get_response = mcp.handle_request({
            "jsonrpc": "2.0", "id": 12, "method": "tools/call",
            "params": {"name": "cc_duet_get_task", "arguments": {"task_id": task_id}},
        })
        task = json.loads(get_response["result"]["content"][0]["text"])
        self.assertEqual(task["title"], "MCP test")
        self.assertEqual(task["project_paths"], ["src/**"])

    def test_tool_error_returns_is_error(self) -> None:
        _, mcp = self._scaffold()
        response = mcp.handle_request({
            "jsonrpc": "2.0", "id": 20, "method": "tools/call",
            "params": {"name": "cc_duet_get_task", "arguments": {"task_id": "nonexistent"}},
        })
        result = response["result"]
        self.assertTrue(result["isError"])
        self.assertIn("not found", result["content"][0]["text"])

    def test_unknown_tool_returns_is_error(self) -> None:
        _, mcp = self._scaffold()
        response = mcp.handle_request({
            "jsonrpc": "2.0", "id": 21, "method": "tools/call",
            "params": {"name": "nonexistent_tool", "arguments": {}},
        })
        result = response["result"]
        self.assertTrue(result["isError"])
        self.assertIn("Unknown tool", result["content"][0]["text"])

    def test_non_dict_message_returns_invalid_request(self) -> None:
        _, mcp = self._scaffold()
        response = mcp.handle_request([1, 2, 3])
        self.assertIn("error", response)
        self.assertEqual(response["error"]["code"], -32600)

    def test_non_string_method_returns_invalid_request(self) -> None:
        _, mcp = self._scaffold()
        response = mcp.handle_request({"jsonrpc": "2.0", "id": 99, "method": 42})
        self.assertIn("error", response)
        self.assertEqual(response["error"]["code"], -32600)
        self.assertEqual(response["id"], 99)

    def test_unexpected_exception_in_tool_returns_is_error(self) -> None:
        _, mcp = self._scaffold()
        with mock.patch.object(mcp.qm, "list_tasks", side_effect=PermissionError("access denied")):
            response = mcp.handle_request({
                "jsonrpc": "2.0", "id": 30, "method": "tools/call",
                "params": {"name": "cc_duet_list_tasks", "arguments": {}},
            })
        result = response["result"]
        self.assertTrue(result["isError"])
        self.assertIn("PermissionError", result["content"][0]["text"])

    def test_non_object_params_returns_invalid_params(self) -> None:
        _, mcp = self._scaffold()
        for bad_params in [[], "x", 42, None]:
            response = mcp.handle_request({"jsonrpc": "2.0", "id": 40, "method": "tools/call", "params": bad_params})
            self.assertIn("error", response, f"Expected error for params={bad_params!r}")
            self.assertEqual(response["error"]["code"], -32602)
