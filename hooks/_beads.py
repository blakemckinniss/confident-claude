"""
Bead (task tracking) helpers for hook runners.

Provides caching and utility functions for interacting with the `bd` CLI.
Extracted from pre_tool_use_runner.py to reduce file size and improve reusability.

Integration Synergy:
- Uses project_context for project-aware operations
- Supports agent lifecycle tracking via agent_registry
- Can fire observations to claude-mem
"""

import json
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from _logging import log_debug

if TYPE_CHECKING:
    from session_state import SessionState

# Add lib to path for imports
LIB_DIR = Path(__file__).parent.parent / "lib"
if str(LIB_DIR) not in sys.path:
    sys.path.insert(0, str(LIB_DIR))

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


# =============================================================================
# PROJECT-AWARE FUNCTIONS (Integration Synergy)
# =============================================================================


def get_project_root() -> Path | None:
    """Get current project root using project_context detection."""
    try:
        from project_context import find_project_root

        return find_project_root()
    except Exception as e:
        log_debug("_beads", f"Project detection failed: {e}")
        return None


def get_project_beads_dir() -> Path | None:
    """Get .beads/ directory for current project."""
    try:
        from project_context import get_beads_dir

        return get_beads_dir()
    except Exception as e:
        log_debug("_beads", f"Beads dir failed: {e}")
        return None


def claim_bead_for_agent(
    bead_id: str,
    agent_id: str | None = None,
    prompt_snippet: str = "",
) -> dict | None:
    """
    Claim a bead for an agent with lifecycle tracking.

    Uses agent_registry to track the claim in project-local storage.
    """
    try:
        from agent_registry import claim_bead

        return claim_bead(
            bead_id=bead_id,
            agent_session_id=agent_id,
            prompt_snippet=prompt_snippet,
        )
    except Exception as e:
        log_debug("_beads", f"Claim failed: {e}")
        return None


def release_bead_for_agent(
    bead_id: str,
    agent_id: str | None = None,
    status: str = "completed",
) -> bool:
    """
    Release a bead from an agent.

    Updates agent_registry to mark assignment complete.
    """
    try:
        from agent_registry import release_bead

        return release_bead(
            bead_id=bead_id,
            agent_session_id=agent_id,
            status=status,
        )
    except Exception as e:
        log_debug("_beads", f"Release failed: {e}")
        return False


def get_stale_bead_assignments(timeout_minutes: int = 30) -> list:
    """Get stale agent assignments that may be orphaned."""
    try:
        from agent_registry import get_stale_assignments

        return get_stale_assignments(timeout_minutes)
    except Exception as e:
        log_debug("_beads", f"Stale check failed: {e}")
        return []


def fire_bead_observation(
    action: str,
    bead_id: str,
    title: str = "",
    status: str = "",
) -> bool:
    """
    Fire a bead action observation to claude-mem.

    Actions: create, update, close, claim, release
    """
    try:
        from _integration import fire_observation

        return fire_observation(
            tool_name=f"bd_{action}",
            tool_input={"bead_id": bead_id, "title": title, "status": status},
            tool_response=f"Bead {bead_id} {action}: {title or status}",
        )
    except Exception as e:
        log_debug("_beads", f"Observation failed: {e}")
        return False


def format_bead_context(state: "SessionState") -> str:
    """Format bead context with project awareness for injection."""
    parts = []

    # Get in-progress beads
    in_progress = get_in_progress_beads(state)
    if in_progress:
        parts.append(f"📋 **Active beads**: {len(in_progress)} in progress")
        for b in in_progress[:3]:
            bead_id = b.get("id", "?")[:12]
            title = b.get("title", "untitled")[:40]
            parts.append(f"  • `{bead_id}`: {title}")

    # Check for stale assignments (potential orphans)
    stale = get_stale_bead_assignments(timeout_minutes=60)
    if stale:
        parts.append(f"⚠️ **Stale assignments**: {len(stale)} may be orphaned")

    # Project context
    root = get_project_root()
    if root:
        project_name = root.name
        beads_dir = root / ".beads"
        if beads_dir.is_dir():
            parts.append(f"📁 **Project**: `{project_name}` (isolated beads)")

    return "\n".join(parts) if parts else ""
