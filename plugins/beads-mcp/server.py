#!/usr/bin/env python3
"""
Thin MCP wrapper around the bd CLI for task tracking.

Provides 8 core tools:
- list_beads: List beads with optional status filter
- create_bead: Create a new bead
- update_bead: Update bead status
- close_bead: Close a bead
- get_ready: Get actionable beads (no blockers)
- show_bead: Get detailed bead information
- dep_add: Add a dependency between beads
- dep_remove: Remove a dependency between beads
"""

import json
import subprocess
import shutil
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

# Find bd binary
BD_PATH = shutil.which("bd") or "/home/jinx/.claude/.venv/bin/bd"

server = Server("beads")


def run_bd(*args: str, json_output: bool = True) -> dict | list | str:
    """Run bd command and return parsed output."""
    cmd = [BD_PATH] + list(args)
    if json_output and "--json" not in args:
        cmd.append("--json")

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=30,
    )

    if result.returncode != 0:
        raise RuntimeError(f"bd failed: {result.stderr.strip() or result.stdout.strip()}")

    output = result.stdout.strip()
    if not output:
        return {} if json_output else ""

    if json_output:
        return json.loads(output)
    return output


@server.list_tools()
async def list_tools() -> list[Tool]:
    """List available beads tools."""
    return [
        Tool(
            name="list_beads",
            description="List beads/issues. Returns JSON array of beads.",
            inputSchema={
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "description": "Filter by status: open, in_progress, blocked, closed",
                        "enum": ["open", "in_progress", "blocked", "closed"],
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum results to return",
                        "default": 20,
                    },
                    "assignee": {
                        "type": "string",
                        "description": "Filter by assignee",
                    },
                },
            },
        ),
        Tool(
            name="create_bead",
            description="Create a new bead/issue. Returns the created bead with ID.",
            inputSchema={
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Bead title (required)",
                    },
                    "type": {
                        "type": "string",
                        "description": "Bead type",
                        "enum": ["bug", "feature", "task", "epic", "chore"],
                        "default": "task",
                    },
                    "description": {
                        "type": "string",
                        "description": "Bead description",
                    },
                    "priority": {
                        "type": "string",
                        "description": "Priority 0-4 (0=highest)",
                        "default": "2",
                    },
                },
                "required": ["title"],
            },
        ),
        Tool(
            name="update_bead",
            description="Update a bead's status or other fields.",
            inputSchema={
                "type": "object",
                "properties": {
                    "id": {
                        "type": "string",
                        "description": "Bead ID (required)",
                    },
                    "status": {
                        "type": "string",
                        "description": "New status",
                        "enum": ["open", "in_progress", "blocked", "closed"],
                    },
                    "title": {
                        "type": "string",
                        "description": "New title",
                    },
                    "priority": {
                        "type": "string",
                        "description": "New priority 0-4",
                    },
                },
                "required": ["id"],
            },
        ),
        Tool(
            name="close_bead",
            description="Close a bead/issue.",
            inputSchema={
                "type": "object",
                "properties": {
                    "id": {
                        "type": "string",
                        "description": "Bead ID to close (required)",
                    },
                },
                "required": ["id"],
            },
        ),
        Tool(
            name="get_ready",
            description="Get actionable beads (open/in_progress with no blockers).",
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Maximum results",
                        "default": 10,
                    },
                    "assignee": {
                        "type": "string",
                        "description": "Filter by assignee",
                    },
                },
            },
        ),
        Tool(
            name="show_bead",
            description="Get detailed information about a specific bead.",
            inputSchema={
                "type": "object",
                "properties": {
                    "id": {
                        "type": "string",
                        "description": "Bead ID to show (required)",
                    },
                },
                "required": ["id"],
            },
        ),
        Tool(
            name="dep_add",
            description="Add a dependency between beads (issue depends on depends_on).",
            inputSchema={
                "type": "object",
                "properties": {
                    "issue_id": {
                        "type": "string",
                        "description": "Bead that has the dependency (required)",
                    },
                    "depends_on_id": {
                        "type": "string",
                        "description": "Bead that issue_id depends on (required)",
                    },
                    "type": {
                        "type": "string",
                        "description": "Dependency type",
                        "enum": ["blocks", "related", "parent-child", "discovered-from"],
                        "default": "blocks",
                    },
                },
                "required": ["issue_id", "depends_on_id"],
            },
        ),
        Tool(
            name="dep_remove",
            description="Remove a dependency between beads.",
            inputSchema={
                "type": "object",
                "properties": {
                    "issue_id": {
                        "type": "string",
                        "description": "Bead that has the dependency (required)",
                    },
                    "depends_on_id": {
                        "type": "string",
                        "description": "Bead to remove as dependency (required)",
                    },
                },
                "required": ["issue_id", "depends_on_id"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Handle tool calls."""
    try:
        if name == "list_beads":
            args = ["list"]
            if status := arguments.get("status"):
                args.extend(["--status", status])
            if limit := arguments.get("limit"):
                args.extend(["--limit", str(limit)])
            if assignee := arguments.get("assignee"):
                args.extend(["--assignee", assignee])
            result = run_bd(*args)

        elif name == "create_bead":
            args = ["create", arguments["title"]]
            if bead_type := arguments.get("type"):
                args.extend(["--type", bead_type])
            if desc := arguments.get("description"):
                args.extend(["--description", desc])
            if priority := arguments.get("priority"):
                args.extend(["--priority", priority])
            result = run_bd(*args)

        elif name == "update_bead":
            args = ["update", arguments["id"]]
            if status := arguments.get("status"):
                args.extend(["--status", status])
            if title := arguments.get("title"):
                args.extend(["--title", title])
            if priority := arguments.get("priority"):
                args.extend(["--priority", priority])
            result = run_bd(*args)

        elif name == "close_bead":
            result = run_bd("close", arguments["id"])

        elif name == "get_ready":
            args = ["ready"]
            if limit := arguments.get("limit"):
                args.extend(["--limit", str(limit)])
            if assignee := arguments.get("assignee"):
                args.extend(["--assignee", assignee])
            result = run_bd(*args)

        elif name == "show_bead":
            result = run_bd("show", arguments["id"])

        elif name == "dep_add":
            args = ["dep", "add", arguments["issue_id"], arguments["depends_on_id"]]
            if dep_type := arguments.get("type"):
                args.extend(["--type", dep_type])
            result = run_bd(*args)

        elif name == "dep_remove":
            result = run_bd("dep", "remove", arguments["issue_id"], arguments["depends_on_id"])

        else:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]

        return [TextContent(
            type="text",
            text=json.dumps(result, indent=2) if isinstance(result, (dict, list)) else str(result)
        )]

    except Exception as e:
        return [TextContent(type="text", text=f"Error: {e}")]


async def main():
    """Run the MCP server."""
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
