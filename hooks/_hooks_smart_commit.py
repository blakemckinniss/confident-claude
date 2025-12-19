"""Smart auto-commit hooks.

Triggers auto-commit at natural completion points:
- bd close: Commits with bead title as message
- Session end: Suggests commit (via stop_runner)
- Periodic: Suggests after significant work

Priority 95 = runs late, after state tracking is done.
"""

from __future__ import annotations

import os
import re
import sys
from typing import TYPE_CHECKING

# Add lib to path for imports
sys.path.insert(0, str(__file__).replace("/hooks/_hooks_smart_commit.py", "/lib"))

from _hook_registry import register_hook
from _hook_result import HookResult

if TYPE_CHECKING:
    from lib._session_state_class import SessionState

# =============================================================================
# Configuration
# =============================================================================

# Environment variable to disable smart commit entirely
DISABLE_ENV = "CLAUDE_SMART_COMMIT_DISABLE"

# Minimum turns between auto-commits
AUTO_COMMIT_COOLDOWN = 3


def _is_enabled() -> bool:
    """Check if smart commit is enabled."""
    return os.environ.get(DISABLE_ENV, "0") != "1"


def _get_cwd() -> str:
    """Get current working directory."""
    return os.getcwd()


# =============================================================================
# Lazy import to avoid circular deps
# =============================================================================

_smart_commit = None


def _get_smart_commit():
    """Lazy import of smart commit module."""
    global _smart_commit
    if _smart_commit is None:
        try:
            from lib import _smart_commit as sc

            _smart_commit = sc
        except ImportError:
            # Fallback: try direct import
            import importlib.util

            spec = importlib.util.spec_from_file_location(
                "_smart_commit",
                os.path.expanduser("~/.claude/lib/_smart_commit.py"),
            )
            if spec and spec.loader:
                _smart_commit = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(_smart_commit)
    return _smart_commit


# =============================================================================
# bd close detection and auto-commit
# =============================================================================


def _extract_bead_title_from_output(output: str) -> str:
    """Extract bead title from bd close output."""
    # bd close output format: Closed bead: <id> - <title>
    # or just: Closed: <title>
    match = re.search(r"[Cc]losed[^:]*:\s*(?:\S+\s*-\s*)?(.+?)(?:\n|$)", output)
    if match:
        return match.group(1).strip()
    return ""


@register_hook("smart_commit_bead_close", "Bash", priority=95)
def check_smart_commit_on_bead_close(
    data: dict, state: SessionState, runner_state: dict
) -> HookResult:
    """Auto-commit when a bead is closed.

    Triggers on successful `bd close` command.
    Uses bead title as commit message.
    """
    if not _is_enabled():
        return HookResult.ok()

    tool_input = data.get("tool_input", {})
    command = tool_input.get("command", "")

    # Check if this is a bd close command
    if not re.search(r"\bbd\s+close\b", command, re.IGNORECASE):
        return HookResult.ok()

    # Check if command succeeded
    tool_response = data.get("tool_response", {})
    if isinstance(tool_response, dict):
        if tool_response.get("interrupted"):
            return HookResult.ok()
        stdout = tool_response.get("stdout", "")
        stderr = tool_response.get("stderr", "")
        # If there's an error, don't commit
        if stderr and "error" in stderr.lower():
            return HookResult.ok()
    else:
        stdout = str(tool_response) if tool_response else ""

    # Extract bead title from output
    bead_title = _extract_bead_title_from_output(stdout)
    if not bead_title:
        # Fallback: try to extract from command args
        title_match = re.search(r"bd\s+close\s+(\S+)", command)
        if title_match:
            bead_title = f"Complete: {title_match.group(1)}"
        else:
            bead_title = "Complete bead"

    # Check cooldown
    last_commit_turn = runner_state.get("last_auto_commit_turn", 0)
    if state.turn_count - last_commit_turn < AUTO_COMMIT_COOLDOWN:
        return HookResult.ok()

    # Try to get smart commit module
    sc = _get_smart_commit()
    if not sc:
        return HookResult.ok()

    cwd = _get_cwd()

    # Track the bead close
    sc.track_bead_close(bead_title)

    # Check if we should commit
    decision = sc.should_commit(state, cwd, trigger="bead_close")

    if not decision.should_commit:
        return HookResult.ok()

    if decision.auto:
        # Auto-commit
        success, result_msg = sc.do_commit(cwd, decision.message, state)
        runner_state["last_auto_commit_turn"] = state.turn_count

        if success:
            # Extract short hash from result
            hash_match = re.search(r"Committed:\s*([a-f0-9]+)", result_msg)
            short_hash = hash_match.group(1) if hash_match else ""
            return HookResult.ok(
                f"📦 **Auto-committed:** `{short_hash}` {bead_title[:50]}"
            )
        else:
            return HookResult.ok(f"⚠️ Auto-commit failed: {result_msg[:100]}")

    # Suggest commit (not auto)
    return HookResult.ok(
        f"💡 **Commit suggested:** {decision.reason}\n"
        f"   Run `/commit` or `git add -A && git commit -m \"{decision.message[:50]}...\"`"
    )


# =============================================================================
# Track file changes for periodic suggestions
# =============================================================================


@register_hook("smart_commit_track_edit", "Edit|Write", priority=96)
def check_smart_commit_track_edit(
    data: dict, state: SessionState, runner_state: dict
) -> HookResult:
    """Track file edits for commit suggestions."""
    if not _is_enabled():
        return HookResult.ok()

    tool_input = data.get("tool_input", {})
    file_path = tool_input.get("file_path", "")

    if file_path:
        sc = _get_smart_commit()
        if sc:
            sc.track_file_change(file_path)

    return HookResult.ok()


# =============================================================================
# Track commits to reset state
# =============================================================================


@register_hook("smart_commit_track_commit", "Bash", priority=96)
def check_smart_commit_track_commit(
    data: dict, state: SessionState, runner_state: dict
) -> HookResult:
    """Track git commits to reset smart commit state."""
    if not _is_enabled():
        return HookResult.ok()

    tool_input = data.get("tool_input", {})
    command = tool_input.get("command", "")

    # Check if this is a git commit
    if not re.search(r"\bgit\s+commit\b", command, re.IGNORECASE):
        return HookResult.ok()

    tool_response = data.get("tool_response", {})
    if isinstance(tool_response, dict):
        stdout = tool_response.get("stdout", "")
        if tool_response.get("interrupted"):
            return HookResult.ok()
    else:
        stdout = str(tool_response) if tool_response else ""

    # Extract commit hash
    hash_match = re.search(r"\[[\w-]+\s+([a-f0-9]{7,})\]", stdout)
    commit_hash = hash_match.group(1) if hash_match else ""

    if commit_hash:
        sc = _get_smart_commit()
        if sc:
            sc.track_commit(state.turn_count, commit_hash)
            runner_state["last_auto_commit_turn"] = state.turn_count

    return HookResult.ok()


# =============================================================================
# Periodic check for commit suggestions
# =============================================================================


@register_hook("smart_commit_periodic", None, priority=97)
def check_smart_commit_periodic(
    data: dict, state: SessionState, runner_state: dict
) -> HookResult:
    """Periodic check for commit suggestions.

    Runs on all tools, but only fires suggestions occasionally.
    """
    if not _is_enabled():
        return HookResult.ok()

    # Only check every 5 turns to avoid noise
    if state.turn_count % 5 != 0:
        return HookResult.ok()

    # Check cooldown
    last_suggestion_turn = runner_state.get("last_commit_suggestion_turn", 0)
    if state.turn_count - last_suggestion_turn < 10:
        return HookResult.ok()

    sc = _get_smart_commit()
    if not sc:
        return HookResult.ok()

    cwd = _get_cwd()
    decision = sc.should_commit(state, cwd, trigger="periodic")

    if decision.should_commit and not decision.auto:
        runner_state["last_commit_suggestion_turn"] = state.turn_count
        return HookResult.ok(
            f"💡 **Commit suggested:** {decision.reason}\n"
            f"   Run `/commit` to save your progress"
        )

    return HookResult.ok()
