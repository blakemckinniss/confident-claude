"""
Bead (task tracking) helpers for hook runners.

Provides caching and utility functions for interacting with the `bd` CLI.
Extracted from pre_tool_use_runner.py to reduce file size and improve reusability.
"""

import json
import subprocess
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from session_state import SessionState

# Cache for bd queries (avoid repeated subprocess calls)
_BD_CACHE: dict = {}
_BD_CACHE_TURN: int = 0


def get_open_beads(state: "SessionState") -> list:
    """Get open beads, cached per turn."""
    global _BD_CACHE, _BD_CACHE_TURN

    current_turn = state.turn_count
    if _BD_CACHE_TURN == current_turn and "open_beads" in _BD_CACHE:
        return _BD_CACHE.get("open_beads", [])

    # Cache miss - query bd (separate queries since bd doesn't support comma-separated status)
    try:
        all_beads = []
        for status in ["open", "in_progress"]:
            result = subprocess.run(
                ["bd", "list", f"--status={status}", "--json"],
                capture_output=True,
                text=True,
                timeout=2,
            )
            if result.returncode == 0 and result.stdout.strip():
                all_beads.extend(json.loads(result.stdout))

        _BD_CACHE = {"open_beads": all_beads}
        _BD_CACHE_TURN = current_turn
        return all_beads
    except Exception:
        pass

    return []


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

    # Get blocked beads to exclude
    blocked_ids = set()
    try:
        result = subprocess.run(
            ["bd", "blocked", "--json"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        if result.returncode == 0 and result.stdout.strip():
            blocked = json.loads(result.stdout)
            blocked_ids = {b.get("id") for b in blocked}
    except Exception:
        pass

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
