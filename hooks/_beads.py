"""
Bead (task tracking) helpers for hook runners.

Provides caching and utility functions for interacting with the `bd` CLI.
Extracted from pre_tool_use_runner.py to reduce file size and improve reusability.
"""

import json
import os
import tempfile
from datetime import datetime
from typing import TYPE_CHECKING
from _logging import log_debug

if TYPE_CHECKING:
    from session_state import SessionState

# Simple per-process cache (hooks run as subprocesses, so this resets each call)
_BD_CACHE: list | None = None


def get_open_beads(state: "SessionState") -> list:
    """Get open beads. Caches within single hook invocation.

    Note: Uses temp file + os.system instead of subprocess.run due to bd pipe issues.
    """
    global _BD_CACHE

    # Use cached result if already queried this invocation
    if _BD_CACHE is not None:
        return _BD_CACHE

    # Query bd for both open and in_progress beads
    # Using temp file approach because bd has issues with subprocess pipes
    all_beads = []
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            tmp_path = f.name

        for status in ["open", "in_progress"]:
            exit_code = os.system(
                f'bd list --status={status} --json > "{tmp_path}" 2>/dev/null'
            )
            if exit_code == 0:
                try:
                    with open(tmp_path) as f:
                        content = f.read().strip()
                    if content:
                        all_beads.extend(json.loads(content))
                except (json.JSONDecodeError, OSError):
                    pass

        _BD_CACHE = all_beads
    except Exception as e:
        log_debug("_beads", f"bd list parsing failed: {e}")
    finally:
        # Clean up temp file
        try:
            os.unlink(tmp_path)
        except Exception as e:
            log_debug("_beads", f"temp file cleanup failed: {e}")

    return all_beads


def get_in_progress_beads(state: "SessionState") -> list:
    """Get beads currently being worked on."""
    beads = get_open_beads(state)
    return [b for b in beads if b.get("status") == "in_progress"]


def get_independent_beads(state: "SessionState") -> list:
    """
    Get beads that can be worked in parallel (no blockers).

    FILTERS:
    - Status: open or in_progress only
    - Dependencies: No unresolved blockers
    - Recency: Updated in last 24 hours preferred
    - Limit: Max 4 for parallel work
    """
    beads = get_open_beads(state)
    if not beads:
        return []

    # Get blocked beads to exclude (using temp file due to bd pipe issues)
    blocked_ids = set()
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            tmp_path = f.name
        exit_code = os.system(f'bd blocked --json > "{tmp_path}" 2>/dev/null')
        if exit_code == 0:
            with open(tmp_path) as f:
                content = f.read().strip()
            if content:
                blocked = json.loads(content)
                blocked_ids = {b.get("id") for b in blocked}
        os.unlink(tmp_path)
    except Exception as e:
        log_debug("_beads", f"bd blocked parsing failed: {e}")

    # Filter to independent beads
    independent = [b for b in beads if b.get("id") not in blocked_ids]

    # Sort by recency (updated_at or created_at)
    def get_timestamp(b):
        ts = b.get("updated_at") or b.get("created_at") or ""
        try:
            return datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except Exception:
            return datetime.min

    independent.sort(key=get_timestamp, reverse=True)

    # Cap at 4 for parallel work
    return independent[:4]


def generate_parallel_task_calls(beads: list) -> str:
    """Generate copy-pasteable parallel Task invocation structure."""
    if not beads:
        return ""

    lines = ["**Suggested parallel Task calls** (spawn ALL in one message):"]
    lines.append("```")

    for i, b in enumerate(beads, 1):
        bead_id = b.get("id", "???")[:16]
        title = b.get("title", "untitled")[:50]
        bead_type = b.get("type", "task")

        lines.append(f"# Task {i}: {title}")
        lines.append("Task(")
        lines.append('    subagent_type="general-purpose",')
        lines.append(f'    description="Work on {bead_type}: {title[:30]}",')
        lines.append(f'    prompt="Work on bead `{bead_id}`: {title}. ')
        lines.append(
            f"            First run `bd update {bead_id} --status=in_progress`, "
        )
        lines.append(
            f'            then complete the work, then `bd close {bead_id}`.",'
        )
        lines.append(")")
        if i < len(beads):
            lines.append("")

    lines.append("```")
    return "\n".join(lines)
