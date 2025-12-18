#!/usr/bin/env python3
"""
Beads-Claude-Mem Integration Bridge

Wraps bd CLI commands to fire observations to claude-mem's HTTP API.
Captures task lifecycle events (create, close, update) as memory.

Usage:
    bd_bridge.py create "Task title" [--type TYPE]
    bd_bridge.py close <bead_id> [<bead_id2> ...]
    bd_bridge.py update <bead_id> --status=<status>
    bd_bridge.py <any_other_command>  # Passthrough

The bridge fires observations on create/close/update, then passes through to bd.
All other commands are pure passthrough.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

# Claude-mem API endpoint
CLAUDE_MEM_API = os.environ.get("CLAUDE_MEM_API", "http://127.0.0.1:37777")
OBSERVATION_ENDPOINT = f"{CLAUDE_MEM_API}/api/sessions/observations"

# Timeout for API calls (don't block bd on slow/unavailable API)
API_TIMEOUT = 5


def get_session_id() -> str | None:
    """Get Claude session ID from environment or session state file."""
    # Try environment first
    session_id = os.environ.get("CLAUDE_SESSION_ID")
    if session_id:
        return session_id

    # Fallback: read from session state file
    state_file = Path.home() / ".claude" / "tmp" / "session_state_v3.json"
    if state_file.exists():
        try:
            with open(state_file) as f:
                state = json.load(f)
                return state.get("session_id")
        except (json.JSONDecodeError, OSError):
            pass

    return None


def fire_observation(
    tool_name: str, tool_input: dict[str, Any], tool_response: dict[str, Any]
) -> bool:
    """Send observation to claude-mem API. Returns True on success."""
    session_id = get_session_id()
    if not session_id:
        # No session = probably not in Claude context, skip silently
        return False

    try:
        import urllib.request
        import urllib.error

        payload = json.dumps({
            "claudeSessionId": session_id,
            "tool_name": tool_name,
            "tool_input": tool_input,
            "tool_response": tool_response,
            "cwd": os.getcwd(),
        }).encode("utf-8")

        req = urllib.request.Request(
            OBSERVATION_ENDPOINT,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=API_TIMEOUT) as resp:
            return resp.status == 200

    except (urllib.error.URLError, TimeoutError, OSError):
        # Silent fail - don't break bd workflow
        return False


def run_bd(*args: str) -> subprocess.CompletedProcess:
    """Run bd command and return result."""
    return subprocess.run(["bd", *args], capture_output=True, text=True)


def get_bead_details(bead_id: str) -> dict[str, Any] | None:
    """Fetch bead details from bd show."""
    result = run_bd("show", bead_id, "--json")
    if result.returncode == 0 and result.stdout.strip():
        try:
            data = json.loads(result.stdout)
            # bd show --json returns a list with single element
            if isinstance(data, list) and len(data) > 0:
                return data[0]
            elif isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass
    return None


def handle_create(args: list[str]) -> int:
    """Handle bd create with observation."""
    result = run_bd("create", *args)
    print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)

    if result.returncode == 0:
        # Parse created issue ID from output
        # Format: "✓ Created issue: claude-xyz"
        output = result.stdout.strip()
        for line in output.split("\n"):
            if "Created issue:" in line:
                # Extract ID after "Created issue: "
                parts = line.split("Created issue:")
                if len(parts) > 1:
                    bead_id = parts[1].strip().split()[0]

                    # Extract title from args
                    title = ""
                    for i, arg in enumerate(args):
                        if arg == "--title" and i + 1 < len(args):
                            title = args[i + 1]
                            break
                        elif arg.startswith("--title="):
                            title = arg.split("=", 1)[1]
                            break
                        elif not arg.startswith("-") and not title:
                            title = arg

                    fire_observation(
                        tool_name="BeadsCreate",
                        tool_input={"title": title, "args": args},
                        tool_response={
                            "status": "created",
                            "id": bead_id,
                            "title": title,
                        },
                    )
                break

    return result.returncode


def handle_close(args: list[str]) -> int:
    """Handle bd close with observation."""
    # Get bead IDs (non-flag arguments)
    bead_ids = [a for a in args if not a.startswith("-")]

    # Fetch details BEFORE closing (so we have the info)
    details: dict[str, dict] = {}
    for bead_id in bead_ids:
        detail = get_bead_details(bead_id)
        if detail:
            details[bead_id] = detail

    # Execute the close
    result = run_bd("close", *args)
    print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)

    # Fire observations for each closed bead
    if result.returncode == 0:
        for bead_id in bead_ids:
            detail = details.get(bead_id, {})
            fire_observation(
                tool_name="BeadsClose",
                tool_input={"id": bead_id},
                tool_response={
                    "status": "completed",
                    "id": bead_id,
                    "title": detail.get("title", ""),
                    "issue_type": detail.get("type", "task"),
                    "description": detail.get("description", ""),
                },
            )

    return result.returncode


def handle_update(args: list[str]) -> int:
    """Handle bd update with observation for status changes."""
    result = run_bd("update", *args)
    print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)

    # Only fire observation for status changes
    if result.returncode == 0:
        # Check if --status was provided
        new_status = None
        for i, arg in enumerate(args):
            if arg == "--status" and i + 1 < len(args):
                new_status = args[i + 1]
                break
            elif arg.startswith("--status="):
                new_status = arg.split("=", 1)[1]
                break

        if new_status:
            # Get bead IDs
            bead_ids = [a for a in args if not a.startswith("-")]
            for bead_id in bead_ids:
                detail = get_bead_details(bead_id)
                if detail:
                    fire_observation(
                        tool_name="BeadsUpdate",
                        tool_input={"id": bead_id, "status": new_status},
                        tool_response={
                            "status": "updated",
                            "id": bead_id,
                            "title": detail.get("title", ""),
                            "new_status": new_status,
                        },
                    )

    return result.returncode


def main() -> int:
    """Main entry point."""
    if len(sys.argv) < 2:
        # No args, pass through to bd
        result = run_bd()
        print(result.stdout, end="")
        if result.stderr:
            print(result.stderr, end="", file=sys.stderr)
        return result.returncode

    command = sys.argv[1]
    args = sys.argv[2:]

    # Route to handlers or passthrough
    handlers = {
        "create": handle_create,
        "close": handle_close,
        "update": handle_update,
    }

    if command in handlers:
        return handlers[command](args)
    else:
        # Passthrough for all other commands
        result = run_bd(command, *args)
        print(result.stdout, end="")
        if result.stderr:
            print(result.stderr, end="", file=sys.stderr)
        return result.returncode


if __name__ == "__main__":
    sys.exit(main())
