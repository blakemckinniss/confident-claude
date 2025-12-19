"""
Shared bd CLI client for hooks and MCP server.

Provides a clean interface to the bd CLI tool without temp file dance.
"""

import json
import shutil
import subprocess
from typing import Any

# Find bd binary
BD_PATH = shutil.which("bd") or "/home/jinx/.claude/.venv/bin/bd"


def run_bd(*args: str, json_output: bool = True, timeout: int = 30) -> dict | list | str:
    """
    Run bd command and return parsed output.

    Args:
        *args: CLI arguments (e.g., "list", "--status", "open")
        json_output: Whether to request and parse JSON output
        timeout: Command timeout in seconds

    Returns:
        Parsed JSON (dict/list) or raw string output

    Raises:
        RuntimeError: If bd command fails
    """
    cmd = [BD_PATH] + list(args)
    if json_output and "--json" not in args:
        cmd.append("--json")

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )

    if result.returncode != 0:
        error_msg = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(f"bd failed: {error_msg}")

    output = result.stdout.strip()
    if not output:
        return {} if json_output else ""

    if json_output:
        return json.loads(output)
    return output


def list_beads(status: str | None = None, limit: int = 20) -> list[dict]:
    """List beads with optional filters."""
    args = ["list"]
    if status:
        args.extend(["--status", status])
    if limit:
        args.extend(["--limit", str(limit)])
    result = run_bd(*args)
    return result if isinstance(result, list) else []


def get_open_beads() -> list[dict]:
    """Get all open and in_progress beads."""
    open_beads = list_beads(status="open")
    in_progress = list_beads(status="in_progress")
    return open_beads + in_progress


def get_in_progress_beads() -> list[dict]:
    """Get beads currently being worked on."""
    return list_beads(status="in_progress")


def get_ready_beads(limit: int = 10) -> list[dict]:
    """Get actionable beads (no blockers)."""
    result = run_bd("ready", "--limit", str(limit))
    return result if isinstance(result, list) else []


def get_blocked_beads() -> list[dict]:
    """Get beads that are blocked by dependencies."""
    result = run_bd("blocked")
    return result if isinstance(result, list) else []


def show_bead(bead_id: str) -> dict | None:
    """Get detailed info for a specific bead."""
    result = run_bd("show", bead_id)
    if isinstance(result, list) and result:
        return result[0]
    return result if isinstance(result, dict) else None


def create_bead(title: str, bead_type: str = "task", priority: str = "2") -> dict:
    """Create a new bead."""
    result = run_bd("create", title, "--type", bead_type, "--priority", priority)
    return result if isinstance(result, dict) else {}


def update_bead(bead_id: str, status: str | None = None) -> bool:
    """Update a bead's status."""
    args = ["update", bead_id]
    if status:
        args.extend(["--status", status])
    try:
        run_bd(*args)
        return True
    except RuntimeError:
        return False


def close_bead(bead_id: str) -> bool:
    """Close a bead."""
    try:
        run_bd("close", bead_id)
        return True
    except RuntimeError:
        return False
