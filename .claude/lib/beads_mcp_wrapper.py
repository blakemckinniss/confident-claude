"""
Beads MCP Wrapper - Drop-in replacement for bd CLI calls.

Provides sync functions that wrap beads-mcp async functions,
enabling existing hook code to work without the bd CLI binary.

Usage:
    from beads_mcp_wrapper import (
        list_issues,
        create_issue,
        close_issue,
        update_issue,
        show_issue,
        ready_work,
        blocked,
    )

    # Get all open issues
    issues = list_issues(status="open")

    # Create a new issue
    result = create_issue(title="Fix bug", issue_type="bug")

    # Close an issue
    close_issue("claude-abc123")
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

# Try to import beads_mcp - fall back to JSONL direct access if not available
_BEADS_MCP_AVAILABLE = False
_beads_tools = None

try:
    # Suppress beads-mcp startup logs during import
    import logging
    logging.getLogger("beads_mcp").setLevel(logging.WARNING)

    from beads_mcp.tools import (
        beads_list_issues,
        beads_create_issue,
        beads_close_issue,
        beads_update_issue,
        beads_show_issue,
        beads_ready_work,
        beads_blocked,
        current_workspace,
    )
    _BEADS_MCP_AVAILABLE = True
    _beads_tools = {
        "list": beads_list_issues,
        "create": beads_create_issue,
        "close": beads_close_issue,
        "update": beads_update_issue,
        "show": beads_show_issue,
        "ready": beads_ready_work,
        "blocked": beads_blocked,
    }
except ImportError:
    pass


def _find_beads_dir() -> Path | None:
    """Find .beads directory starting from cwd and going up."""
    current = Path.cwd()
    for _ in range(10):  # Max 10 levels up
        beads_dir = current / ".beads"
        if beads_dir.is_dir():
            return beads_dir
        if current.parent == current:
            break
        current = current.parent
    return None


def _run_async(coro):
    """Run async coroutine synchronously."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        # We're in an async context, create new loop in thread
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            future = pool.submit(asyncio.run, coro)
            return future.result()
    else:
        return asyncio.run(coro)


# =============================================================================
# JSONL FALLBACK - Direct file access when beads-mcp not available
# =============================================================================

def _load_issues_jsonl() -> list[dict]:
    """Load all issues from .beads/issues.jsonl."""
    beads_dir = _find_beads_dir()
    if not beads_dir:
        return []

    issues_file = beads_dir / "issues.jsonl"
    if not issues_file.exists():
        return []

    issues = []
    with open(issues_file, "r") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    issues.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return issues


def _save_issues_jsonl(issues: list[dict]) -> bool:
    """Save all issues to .beads/issues.jsonl."""
    beads_dir = _find_beads_dir()
    if not beads_dir:
        return False

    issues_file = beads_dir / "issues.jsonl"
    try:
        with open(issues_file, "w") as f:
            for issue in issues:
                f.write(json.dumps(issue) + "\n")
        return True
    except OSError:
        return False


def _generate_id() -> str:
    """Generate a new issue ID."""
    import random
    import string
    suffix = ''.join(random.choices(string.ascii_lowercase + string.digits, k=4))
    return f"claude-{suffix}"


# =============================================================================
# PUBLIC API - Drop-in replacements for bd CLI
# =============================================================================

def list_issues(
    status: str | None = None,
    issue_type: str | None = None,
    limit: int | None = None,
) -> list[dict]:
    """
    List issues, optionally filtered by status or type.

    Replaces: bd list [--status=STATUS] [--type=TYPE]

    Args:
        status: Filter by status (open, in_progress, closed)
        issue_type: Filter by type (task, bug, feature)
        limit: Max issues to return

    Returns:
        List of issue dicts
    """
    if _BEADS_MCP_AVAILABLE:
        try:
            result = _run_async(beads_list_issues(
                status=status,
                issue_type=issue_type,
                limit=limit,
            ))
            # Handle CompactedResult or list
            if hasattr(result, 'issues'):
                return [i.model_dump() if hasattr(i, 'model_dump') else dict(i) for i in result.issues]
            elif isinstance(result, list):
                return [i.model_dump() if hasattr(i, 'model_dump') else dict(i) for i in result]
            return []
        except Exception:
            pass

    # Fallback to JSONL
    issues = _load_issues_jsonl()

    if status:
        issues = [i for i in issues if i.get("status") == status]
    if issue_type:
        issues = [i for i in issues if i.get("issue_type") == issue_type]
    if limit:
        issues = issues[:limit]

    return issues


def show_issue(issue_id: str) -> dict | None:
    """
    Get details for a specific issue.

    Replaces: bd show <id>

    Args:
        issue_id: The issue ID

    Returns:
        Issue dict or None if not found
    """
    if _BEADS_MCP_AVAILABLE:
        try:
            result = _run_async(beads_show_issue(issue_id=issue_id))
            if result and hasattr(result, 'model_dump'):
                return result.model_dump()
            elif isinstance(result, dict):
                return result
        except Exception:
            pass

    # Fallback to JSONL
    issues = _load_issues_jsonl()
    for issue in issues:
        if issue.get("id") == issue_id:
            return issue
    return None


def create_issue(
    title: str,
    issue_type: str = "task",
    description: str = "",
    priority: int = 2,
) -> dict | None:
    """
    Create a new issue.

    Replaces: bd create --title="..." --type=task

    Args:
        title: Issue title
        issue_type: task, bug, or feature
        description: Optional description
        priority: 0-4 (0=highest)

    Returns:
        Created issue dict or None on failure
    """
    if _BEADS_MCP_AVAILABLE:
        try:
            result = _run_async(beads_create_issue(
                title=title,
                issue_type=issue_type,
                description=description,
                priority=priority,
            ))
            if result and hasattr(result, 'model_dump'):
                return result.model_dump()
            elif isinstance(result, dict):
                return result
        except Exception:
            pass

    # Fallback to JSONL
    from datetime import datetime

    new_issue = {
        "id": _generate_id(),
        "title": title,
        "description": description,
        "status": "open",
        "priority": priority,
        "issue_type": issue_type,
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
    }

    issues = _load_issues_jsonl()
    issues.append(new_issue)

    if _save_issues_jsonl(issues):
        return new_issue
    return None


def close_issue(issue_id: str) -> bool:
    """
    Close an issue.

    Replaces: bd close <id>

    Args:
        issue_id: The issue ID to close

    Returns:
        True on success
    """
    if _BEADS_MCP_AVAILABLE:
        try:
            _run_async(beads_close_issue(issue_id=issue_id))
            return True
        except Exception:
            pass

    # Fallback to JSONL
    from datetime import datetime

    issues = _load_issues_jsonl()
    for issue in issues:
        if issue.get("id") == issue_id:
            issue["status"] = "closed"
            issue["closed_at"] = datetime.now().isoformat()
            issue["updated_at"] = datetime.now().isoformat()
            return _save_issues_jsonl(issues)
    return False


def update_issue(
    issue_id: str,
    status: str | None = None,
    title: str | None = None,
    description: str | None = None,
    priority: int | None = None,
) -> bool:
    """
    Update an issue.

    Replaces: bd update <id> --status=in_progress

    Args:
        issue_id: The issue ID
        status: New status
        title: New title
        description: New description
        priority: New priority

    Returns:
        True on success
    """
    if _BEADS_MCP_AVAILABLE:
        try:
            _run_async(beads_update_issue(
                issue_id=issue_id,
                status=status,
                title=title,
                description=description,
                priority=priority,
            ))
            return True
        except Exception:
            pass

    # Fallback to JSONL
    from datetime import datetime

    issues = _load_issues_jsonl()
    for issue in issues:
        if issue.get("id") == issue_id:
            if status:
                issue["status"] = status
            if title:
                issue["title"] = title
            if description is not None:
                issue["description"] = description
            if priority is not None:
                issue["priority"] = priority
            issue["updated_at"] = datetime.now().isoformat()
            return _save_issues_jsonl(issues)
    return False


def ready_work() -> list[dict]:
    """
    Get issues ready to work on (no blockers).

    Replaces: bd ready

    Returns:
        List of ready issue dicts
    """
    if _BEADS_MCP_AVAILABLE:
        try:
            result = _run_async(beads_ready_work())
            if hasattr(result, 'issues'):
                return [i.model_dump() if hasattr(i, 'model_dump') else dict(i) for i in result.issues]
            elif isinstance(result, list):
                return [i.model_dump() if hasattr(i, 'model_dump') else dict(i) for i in result]
            return []
        except Exception:
            pass

    # Fallback: return open issues (simplified - no blocker checking)
    return list_issues(status="open")


def blocked() -> list[dict]:
    """
    Get blocked issues.

    Replaces: bd blocked

    Returns:
        List of blocked issue dicts
    """
    if _BEADS_MCP_AVAILABLE:
        try:
            result = _run_async(beads_blocked())
            if isinstance(result, list):
                return [i.model_dump() if hasattr(i, 'model_dump') else dict(i) for i in result]
            return []
        except Exception:
            pass

    # Fallback: return empty (can't determine blockers from JSONL alone)
    return []


def get_open_beads() -> list[dict]:
    """
    Get all open and in_progress beads.

    Convenience function for hooks.
    """
    open_issues = list_issues(status="open")
    in_progress = list_issues(status="in_progress")
    return open_issues + in_progress


def get_in_progress_beads() -> list[dict]:
    """Get beads currently being worked on."""
    return list_issues(status="in_progress")


# =============================================================================
# STATUS CHECK
# =============================================================================

def is_mcp_available() -> bool:
    """Check if beads-mcp is available."""
    return _BEADS_MCP_AVAILABLE


def get_backend() -> str:
    """Get current backend being used."""
    return "beads-mcp" if _BEADS_MCP_AVAILABLE else "jsonl-fallback"
