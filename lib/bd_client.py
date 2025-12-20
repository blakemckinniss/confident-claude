"""
Shared bd CLI client for hooks and MCP server.

Provides a clean interface to the bd CLI tool without temp file dance.

Project Isolation:
    All queries automatically filter by project label (project:<name>).
    New beads are auto-labeled with the current project.
    This prevents cross-project bead bleed.
"""

import json
import shutil
import subprocess
from pathlib import Path

# Find bd binary - use Path.home() to avoid hardcoding
_DEFAULT_BD = Path.home() / ".claude" / ".venv" / "bin" / "bd"
BD_PATH = shutil.which("bd") or str(_DEFAULT_BD)


def _get_current_project_label() -> str | None:
    """
    Get the project label for the current working directory.

    Returns:
        Label string like "project:claude-framework" or None if detection fails.
    """
    try:
        # Import here to avoid circular imports
        import sys

        lib_dir = Path(__file__).parent
        if str(lib_dir) not in sys.path:
            sys.path.insert(0, str(lib_dir))

        from project_context import get_project_name

        name = get_project_name()
        return f"project:{name}"
    except Exception:
        return None


def run_bd(
    *args: str, json_output: bool = True, timeout: int = 30
) -> dict | list | str:
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


def list_beads(
    status: str | None = None,
    limit: int = 20,
    project_filter: bool = True,
) -> list[dict]:
    """
    List beads with optional filters.

    Args:
        status: Filter by status (open, in_progress, blocked, closed)
        limit: Maximum number of results
        project_filter: If True, filter to current project only (default: True)

    Returns:
        List of bead dictionaries
    """
    args = ["list"]
    if status:
        args.extend(["--status", status])
    if limit:
        args.extend(["--limit", str(limit)])

    # Add project filtering to prevent cross-project bleed
    if project_filter:
        label = _get_current_project_label()
        if label:
            args.extend(["--label", label])

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


def get_ready_beads(limit: int = 10, project_filter: bool = True) -> list[dict]:
    """
    Get actionable beads (no blockers).

    Args:
        limit: Maximum number of results
        project_filter: If True, filter to current project only
    """
    args = ["ready", "--limit", str(limit)]

    if project_filter:
        label = _get_current_project_label()
        if label:
            args.extend(["--label", label])

    result = run_bd(*args)
    return result if isinstance(result, list) else []


def get_blocked_beads(project_filter: bool = True) -> list[dict]:
    """
    Get beads that are blocked by dependencies.

    Args:
        project_filter: If True, filter to current project only
    """
    args = ["blocked"]

    if project_filter:
        label = _get_current_project_label()
        if label:
            args.extend(["--label", label])

    result = run_bd(*args)
    return result if isinstance(result, list) else []


def show_bead(bead_id: str) -> dict | None:
    """Get detailed info for a specific bead."""
    result = run_bd("show", bead_id)
    if isinstance(result, list) and result:
        return result[0]
    return result if isinstance(result, dict) else None


def create_bead(
    title: str,
    bead_type: str = "task",
    priority: str = "2",
    auto_label: bool = True,
) -> dict:
    """
    Create a new bead.

    Args:
        title: Bead title
        bead_type: Type (task, bug, feature, epic, chore)
        priority: Priority 0-4 (0=highest)
        auto_label: If True, auto-add project label for isolation

    Returns:
        Created bead dict with id
    """
    result = run_bd("create", title, "--type", bead_type, "--priority", priority)

    # Auto-label with current project for isolation
    if auto_label and isinstance(result, dict) and result.get("id"):
        label = _get_current_project_label()
        if label:
            try:
                run_bd("label", "add", result["id"], label, json_output=False)
            except RuntimeError:
                # Label add failed but bead was created - still return bead
                # This is non-fatal since the bead exists
                result["_label_failed"] = True

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
