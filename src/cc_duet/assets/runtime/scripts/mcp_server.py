#!/usr/bin/env python3
"""Minimal MCP stdio server for cc-duet queue operations.

Exposes queue_manager API functions as MCP tools over JSON-RPC 2.0 stdio.
This is a thin adapter — all logic lives in queue_manager.py.

Usage (from a target project root):
    python3 .cc-duet/scripts/mcp_server.py

Claude Code MCP configuration (.mcp.json in project root):
    {
      "mcpServers": {
        "cc-duet": {
          "command": "python3",
          "args": [".cc-duet/scripts/mcp_server.py"]
        }
      }
    }

Transport: JSON-RPC 2.0 over stdio (newline-delimited, no embedded newlines).
Protocol version: MCP 2024-11-05.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(os.environ.get("DUET_ROOT", os.environ.get("ORCHESTRATOR_ROOT", Path(__file__).parent.parent))).resolve()
SCRIPTS_DIR = ROOT / "scripts"

if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import queue_manager as qm  # noqa: E402

SERVER_NAME = "cc-duet"
SERVER_VERSION = "0.1.0"
PROTOCOL_VERSION = "2024-11-05"

# ---------------------------------------------------------------------------
# Tool definitions (JSON Schema for MCP tools/list)
# ---------------------------------------------------------------------------

TOOLS: list[dict] = [
    {
        "name": "cc_duet_create_task",
        "description": "Create a bounded task in the pending queue.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Short task title"},
                "spec": {"type": "string", "description": "Detailed task specification (markdown)"},
                "project_paths": {"type": "array", "items": {"type": "string"}, "description": "Allowed file paths/globs for this task"},
                "priority": {"type": "integer", "description": "Priority (1=highest, 5=lowest)", "default": 2},
                "base_ref": {"type": "string", "description": "Git ref to branch from", "default": "HEAD"},
                "max_rejections": {"type": "integer", "description": "Max review rejections before failure", "default": 3},
                "acceptance": {"type": "array", "items": {"type": "string"}, "description": "Acceptance criteria"},
                "model": {"type": "string", "description": "Codex model override"},
                "max_runtime": {"type": "integer", "description": "Max Codex runtime in seconds"},
                "env_vars": {"type": "array", "items": {"type": "string"}, "description": "Extra env vars to pass to Codex"},
            },
            "required": ["title", "project_paths"],
        },
    },
    {
        "name": "cc_duet_list_tasks",
        "description": "List task summaries, optionally filtered by queue status.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["pending", "claimed", "review", "done", "failed"], "description": "Filter by status (omit for all)"},
            },
        },
    },
    {
        "name": "cc_duet_get_task",
        "description": "Get the full JSON payload of a specific task by ID.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "Task ID (e.g. t-20260512T120000-my-task)"},
            },
            "required": ["task_id"],
        },
    },
    {
        "name": "cc_duet_next_task",
        "description": "Get the highest-priority pending task without claiming it.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "cc_duet_move_task",
        "description": "Move a task to a new queue status.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "Task ID"},
                "new_status": {"type": "string", "enum": ["pending", "claimed", "review", "done", "failed"], "description": "Target status"},
                "note": {"type": "string", "description": "Optional note for the history log", "default": ""},
            },
            "required": ["task_id", "new_status"],
        },
    },
    {
        "name": "cc_duet_submit_result",
        "description": "Submit a Codex execution result for a task.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "Task ID"},
                "result_json": {"type": "string", "description": "Path to the result JSON file"},
                "target_status": {"type": "string", "enum": ["review", "failed"], "default": "review"},
            },
            "required": ["task_id", "result_json"],
        },
    },
    {
        "name": "cc_duet_review_task",
        "description": "Review a completed task and decide its fate (approve, reject, or fail).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "Task ID"},
                "decision": {"type": "string", "enum": ["approved", "approved_with_concerns", "rejected", "failed"], "description": "Review decision"},
                "score": {"type": "integer", "description": "Quality score (0-10)", "minimum": 0, "maximum": 10},
                "concerns": {"type": "array", "items": {"type": "string"}, "description": "List of specific concerns"},
                "feedback": {"type": "string", "description": "Feedback for Codex on retry"},
            },
            "required": ["task_id", "decision", "score"],
        },
    },
]


# ---------------------------------------------------------------------------
# Tool dispatch — maps tool names to queue_manager API calls
# ---------------------------------------------------------------------------

def call_tool(name: str, arguments: dict) -> dict:
    """Dispatch a tool call to the queue_manager API.

    Returns:
        MCP tool result: {"content": [...], "isError": bool}
    """
    try:
        if name == "cc_duet_create_task":
            result = qm.create_task(
                title=arguments["title"],
                spec=arguments.get("spec", ""),
                project_paths=arguments["project_paths"],
                priority=arguments.get("priority", 2),
                base_ref=arguments.get("base_ref", "HEAD"),
                max_rejections=arguments.get("max_rejections", 3),
                acceptance=arguments.get("acceptance"),
                model=arguments.get("model"),
                max_runtime=arguments.get("max_runtime"),
                env_vars=arguments.get("env_vars"),
            )
        elif name == "cc_duet_list_tasks":
            result = qm.list_tasks(arguments.get("status"))
        elif name == "cc_duet_get_task":
            result = qm.get_task(arguments["task_id"])
        elif name == "cc_duet_next_task":
            result = qm.next_task()
        elif name == "cc_duet_move_task":
            result = qm.move_task(arguments["task_id"], arguments["new_status"], arguments.get("note", ""))
        elif name == "cc_duet_submit_result":
            result = qm.submit_result(arguments["task_id"], arguments["result_json"], arguments.get("target_status", "review"))
        elif name == "cc_duet_review_task":
            result = qm.review_task(arguments["task_id"], arguments["decision"], arguments["score"], arguments.get("concerns"), arguments.get("feedback"))
        else:
            return {"content": [{"type": "text", "text": f"Unknown tool: {name}"}], "isError": True}
        return {"content": [{"type": "text", "text": json.dumps(result, indent=2, ensure_ascii=False)}]}
    except Exception as exc:
        return {"content": [{"type": "text", "text": f"Error: {type(exc).__name__}: {exc}"}], "isError": True}


# ---------------------------------------------------------------------------
# JSON-RPC 2.0 request handling
# ---------------------------------------------------------------------------

def handle_request(message: object) -> dict | None:
    """Handle a single JSON-RPC 2.0 message.

    Returns a response dict, or None for notifications (no 'id' field).
    Returns a -32600 Invalid Request error for malformed messages.
    """
    # Validate basic structure: must be a dict with a string method
    if not isinstance(message, dict):
        return _error(None, -32600, "Invalid Request: message must be a JSON object")
    method = message.get("method")
    if not isinstance(method, str):
        request_id = message.get("id")
        return _error(request_id, -32600, "Invalid Request: 'method' must be a string")
    request_id = message.get("id")
    raw_params = message.get("params")
    if raw_params is not None and not isinstance(raw_params, dict):
        return _error(request_id, -32602, "Invalid params: 'params' must be a JSON object")
    params = raw_params if isinstance(raw_params, dict) else {}

    # Notifications have no id — acknowledge silently
    if request_id is None:
        return None

    if method == "initialize":
        return _response(request_id, {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        })
    elif method == "tools/list":
        return _response(request_id, {"tools": TOOLS})
    elif method == "tools/call":
        result = call_tool(params.get("name", ""), params.get("arguments", {}))
        return _response(request_id, result)
    elif method == "ping":
        return _response(request_id, {})
    else:
        return _error(request_id, -32601, f"Method not found: {method}")


def _response(request_id: int | str, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error(request_id: int | str | None, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def _log(message: str) -> None:
    """Log to stderr (MCP convention — stdout is reserved for protocol messages)."""
    print(f"[cc-duet-mcp] {message}", file=sys.stderr, flush=True)


# ---------------------------------------------------------------------------
# Stdio event loop
# ---------------------------------------------------------------------------

def main() -> None:
    _log(f"Starting (root={ROOT})")
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError as exc:
            # JSON-RPC 2.0 §5.1: Parse error (-32700)
            error_response = _error(None, -32700, f"Parse error: {exc}")
            sys.stdout.write(json.dumps(error_response, ensure_ascii=False) + "\n")
            sys.stdout.flush()
            continue
        response = handle_request(message)
        if response is not None:
            sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
