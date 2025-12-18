"""
Agent Registry: Track agent ↔ bead assignments for lifecycle management.

Prevents orphaned beads by tracking which agent claimed which bead,
enabling automatic cleanup when agents crash or timeout.

Storage: <project>/.beads/agent_assignments.jsonl (per-project)

Project detection uses project_context module - walks up from $PWD
looking for .beads/ or CLAUDE.md markers.
"""

from __future__ import annotations

import fcntl
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from project_context import (
    find_project_root,
    get_assignments_file,
)

# Default timeout in minutes
DEFAULT_TIMEOUT_MINUTES = 30

# Timeout by issue type (more complex = longer timeout)
TIMEOUT_BY_TYPE = {
    "epic": 120,
    "feature": 60,
    "bug": 30,
    "task": 30,
    "chore": 15,
}


def _get_storage_path(project_root: Path | None = None) -> Path:
    """Get assignments file path for project."""
    return get_assignments_file(project_root)


def _ensure_storage(project_root: Path | None = None) -> Path:
    """Ensure storage directory and file exist. Returns assignments file path."""
    assignments_file = _get_storage_path(project_root)
    assignments_file.parent.mkdir(parents=True, exist_ok=True)
    if not assignments_file.exists():
        assignments_file.touch()
    return assignments_file


def _read_assignments(project_root: Path | None = None) -> list[dict[str, Any]]:
    """Read all assignments from storage."""
    assignments_file = _ensure_storage(project_root)
    assignments = []
    try:
        with open(assignments_file) as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        assignments.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
    except OSError:
        pass
    return assignments


def _write_assignments(
    assignments: list[dict[str, Any]], project_root: Path | None = None
) -> None:
    """Write all assignments to storage (atomic with file lock)."""
    assignments_file = _ensure_storage(project_root)
    try:
        with open(assignments_file, "w") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            for assignment in assignments:
                f.write(json.dumps(assignment) + "\n")
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass


def _append_assignment(
    assignment: dict[str, Any], project_root: Path | None = None
) -> None:
    """Append a single assignment (with file lock)."""
    assignments_file = _ensure_storage(project_root)
    try:
        with open(assignments_file, "a") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            f.write(json.dumps(assignment) + "\n")
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass


def claim_bead(
    bead_id: str,
    agent_session_id: str | None = None,
    parent_session_id: str | None = None,
    prompt_snippet: str = "",
    expected_duration_minutes: int | None = None,
    project_root: Path | None = None,
) -> dict[str, Any]:
    """
    Record that an agent has claimed a bead.

    Args:
        bead_id: The bead being claimed
        agent_session_id: Unique ID for the agent (auto-generated if None)
        parent_session_id: Session that spawned this agent
        prompt_snippet: First 100 chars of the agent's prompt
        expected_duration_minutes: How long this task is expected to take
        project_root: Project root (auto-detected if None)

    Returns:
        The assignment record
    """
    if agent_session_id is None:
        agent_session_id = str(uuid.uuid4())[:8]

    # Detect project if not provided
    if project_root is None:
        project_root = find_project_root()

    now = datetime.now(timezone.utc).isoformat()

    assignment = {
        "assignment_id": str(uuid.uuid4())[:12],
        "agent_session_id": agent_session_id,
        "bead_id": bead_id,
        "claimed_at": now,
        "last_heartbeat": now,
        "status": "active",
        "parent_session_id": parent_session_id or "",
        "prompt_snippet": prompt_snippet[:100] if prompt_snippet else "",
        "expected_duration_minutes": expected_duration_minutes
        or DEFAULT_TIMEOUT_MINUTES,
        "project_root": str(project_root),
    }

    _append_assignment(assignment, project_root)
    return assignment


def release_bead(
    bead_id: str,
    agent_session_id: str | None = None,
    status: str = "completed",
    project_root: Path | None = None,
) -> bool:
    """
    Record that an agent has released a bead.

    Args:
        bead_id: The bead being released
        agent_session_id: The agent releasing (optional, matches any if None)
        status: Final status (completed, abandoned, timed_out)
        project_root: Project root (auto-detected if None)

    Returns:
        True if assignment was found and updated
    """
    assignments = _read_assignments(project_root)
    found = False

    for assignment in assignments:
        if assignment.get("bead_id") == bead_id:
            if (
                agent_session_id is None
                or assignment.get("agent_session_id") == agent_session_id
            ):
                if assignment.get("status") == "active":
                    assignment["status"] = status
                    assignment["released_at"] = datetime.now(timezone.utc).isoformat()
                    found = True

    if found:
        _write_assignments(assignments, project_root)

    return found


def heartbeat(
    bead_id: str,
    agent_session_id: str | None = None,
    project_root: Path | None = None,
) -> bool:
    """
    Update last_heartbeat for an assignment.

    Returns:
        True if assignment was found and updated
    """
    assignments = _read_assignments(project_root)
    found = False

    for assignment in assignments:
        if assignment.get("bead_id") == bead_id:
            if (
                agent_session_id is None
                or assignment.get("agent_session_id") == agent_session_id
            ):
                if assignment.get("status") == "active":
                    assignment["last_heartbeat"] = datetime.now(
                        timezone.utc
                    ).isoformat()
                    found = True

    if found:
        _write_assignments(assignments, project_root)

    return found


def get_active_assignments(project_root: Path | None = None) -> list[dict[str, Any]]:
    """Get all active (uncompleted) assignments for a project."""
    assignments = _read_assignments(project_root)
    return [a for a in assignments if a.get("status") == "active"]


def get_stale_assignments(
    timeout_minutes: int | None = None,
    project_root: Path | None = None,
) -> list[dict[str, Any]]:
    """
    Get assignments that have exceeded their timeout.

    Args:
        timeout_minutes: Override timeout (uses per-assignment if None)
        project_root: Project root (auto-detected if None)

    Returns:
        List of stale assignments
    """
    now = datetime.now(timezone.utc)
    active = get_active_assignments(project_root)
    stale = []

    for assignment in active:
        # Get timeout for this assignment
        if timeout_minutes is not None:
            timeout = timeout_minutes
        else:
            timeout = assignment.get(
                "expected_duration_minutes", DEFAULT_TIMEOUT_MINUTES
            )

        # Check last heartbeat
        last_hb = assignment.get("last_heartbeat", assignment.get("claimed_at", ""))
        if last_hb:
            try:
                hb_time = datetime.fromisoformat(last_hb.replace("Z", "+00:00"))
                elapsed = (now - hb_time).total_seconds() / 60
                if elapsed > timeout:
                    assignment["elapsed_minutes"] = round(elapsed, 1)
                    stale.append(assignment)
            except (ValueError, TypeError):
                # Can't parse timestamp, consider stale
                stale.append(assignment)

    return stale


def mark_abandoned(
    bead_id: str,
    reason: str = "",
    project_root: Path | None = None,
) -> bool:
    """
    Mark a bead's assignment as abandoned.

    Returns:
        True if assignment was found and marked
    """
    return release_bead(bead_id, status="abandoned", project_root=project_root)


def get_assignment_for_bead(
    bead_id: str,
    project_root: Path | None = None,
) -> dict[str, Any] | None:
    """Get the active assignment for a bead, if any."""
    active = get_active_assignments(project_root)
    for assignment in active:
        if assignment.get("bead_id") == bead_id:
            return assignment
    return None


def cleanup_old_assignments(
    days: int = 7,
    project_root: Path | None = None,
) -> int:
    """
    Remove assignments older than N days.

    Returns:
        Number of assignments removed
    """
    cutoff = datetime.now(timezone.utc).timestamp() - (days * 24 * 60 * 60)
    assignments = _read_assignments(project_root)
    original_count = len(assignments)

    filtered = []
    for assignment in assignments:
        claimed = assignment.get("claimed_at", "")
        if claimed:
            try:
                claimed_time = datetime.fromisoformat(claimed.replace("Z", "+00:00"))
                if claimed_time.timestamp() > cutoff:
                    filtered.append(assignment)
            except (ValueError, TypeError):
                filtered.append(assignment)
        else:
            filtered.append(assignment)

    _write_assignments(filtered, project_root)
    return original_count - len(filtered)


def get_timeout_for_type(issue_type: str) -> int:
    """Get recommended timeout for an issue type."""
    return TIMEOUT_BY_TYPE.get(issue_type, DEFAULT_TIMEOUT_MINUTES)
