"""Smart auto-commit hooks v2.

Fully automatic commits at natural break points. No suggestions, no prompts.
Either it auto-commits or it does nothing.

SINGLE HOOK DESIGN:
- One unified hook handles ALL commit triggers
- Clear feedback after commit (so Claude knows state)
- Checks git status as source of truth (not internal tracking)
- No competing hooks, no confusion

Triggers:
- bd close: Auto-commit with bead title as message
- test pass: Auto-commit after successful pytest/jest/cargo test
- build success: Auto-commit after successful npm build/cargo build

Session end commits are handled by stop_runner.py, not here.

Priority 95 = runs late, after state tracking is done.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import TYPE_CHECKING

# Add lib to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

from _hook_registry import register_hook
from _hook_result import HookResult

if TYPE_CHECKING:
    from lib._session_state_class import SessionState

# =============================================================================
# Configuration
# =============================================================================

# Environment variable to disable smart commit entirely
DISABLE_ENV = "CLAUDE_SMART_COMMIT_DISABLE"

# Test command patterns
TEST_PATTERNS = [
    r"\bpytest\b",
    r"\bnpm\s+test\b",
    r"\bjest\b",
    r"\bcargo\s+test\b",
    r"\bgo\s+test\b",
    r"\brspec\b",
    r"\bphpunit\b",
]

# Build command patterns
BUILD_PATTERNS = [
    r"\bnpm\s+run\s+build\b",
    r"\bnpm\s+build\b",
    r"\bcargo\s+build\b",
    r"\bgo\s+build\b",
    r"\btsc\b",
    r"\bvite\s+build\b",
    r"\bwebpack\b",
]

# Success indicators (command succeeded)
SUCCESS_INDICATORS = [
    r"passed",
    r"succeeded",
    r"success",
    r"\bOK\b",
    r"0 errors?",
    r"✓",
    r"all \d+ tests? passed",
]


def _is_enabled() -> bool:
    """Check if smart commit is enabled."""
    return os.environ.get(DISABLE_ENV, "0") != "1"


# =============================================================================
# Lazy import smart commit module
# =============================================================================

_smart_commit = None


def _get_sc():
    """Lazy import of smart commit module."""
    global _smart_commit
    if _smart_commit is None:
        try:
            from lib import _smart_commit as sc
            _smart_commit = sc
        except ImportError:
            import importlib.util
            spec = importlib.util.spec_from_file_location(
                "_smart_commit",
                Path(__file__).parent.parent / "lib" / "_smart_commit.py",
            )
            if spec and spec.loader:
                _smart_commit = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(_smart_commit)
    return _smart_commit


# =============================================================================
# Trigger Detection
# =============================================================================


def _detect_trigger(command: str, stdout: str, stderr: str, exit_code: int) -> str | None:
    """Detect what trigger (if any) this command represents.

    Returns: "bead_close", "test_pass", "build_success", or None
    """
    cmd_lower = command.lower()

    # bd close detection
    if re.search(r"\bbd\s+close\b", cmd_lower):
        if exit_code == 0:
            return "bead_close"
        return None

    # Test pass detection
    for pattern in TEST_PATTERNS:
        if re.search(pattern, cmd_lower, re.IGNORECASE):
            if exit_code == 0:
                # Extra verification for test success
                output = (stdout + stderr).lower()
                if any(re.search(p, output, re.I) for p in SUCCESS_INDICATORS):
                    return "test_pass"
                # If exit code is 0, assume success even without indicators
                return "test_pass"
            return None

    # Build success detection
    for pattern in BUILD_PATTERNS:
        if re.search(pattern, cmd_lower, re.IGNORECASE):
            if exit_code == 0:
                return "build_success"
            return None

    return None


def _extract_bead_title(command: str, stdout: str) -> str | None:
    """Extract bead title from bd close command/output."""
    # Try to get from output first
    # Format: "Closed bead: <id> - <title>" or "Closed: <title>"
    match = re.search(r"[Cc]losed[^:]*:\s*(?:\S+\s*-\s*)?(.+?)(?:\n|$)", stdout)
    if match:
        return match.group(1).strip()

    # Fallback: try to extract bead ID from command
    id_match = re.search(r"bd\s+close\s+(\S+)", command)
    if id_match:
        return f"Complete: {id_match.group(1)}"

    return "Complete bead"


# =============================================================================
# Unified Commit Hook
# =============================================================================


@register_hook("smart_commit_auto", "Bash", priority=95)
def auto_commit_on_trigger(
    data: dict, state: SessionState, runner_state: dict
) -> HookResult:
    """Unified auto-commit hook for all triggers.

    Handles:
    - bd close: Commit with bead title
    - test pass: Commit after successful test
    - build success: Commit after successful build

    This is the ONLY commit hook. All commit logic goes through here.
    Clear, simple, no confusion.
    """
    if not _is_enabled():
        return HookResult.ok()

    # Get command and response
    tool_input = data.get("tool_input", {})
    command = tool_input.get("command", "")
    if not command:
        return HookResult.ok()

    tool_response = data.get("tool_response", {})
    if isinstance(tool_response, dict):
        if tool_response.get("interrupted"):
            return HookResult.ok()
        stdout = tool_response.get("stdout", "")
        stderr = tool_response.get("stderr", "")
        exit_code = tool_response.get("exit_code", 0)
    else:
        stdout = str(tool_response) if tool_response else ""
        stderr = ""
        exit_code = 0

    # Detect trigger
    trigger = _detect_trigger(command, stdout, stderr, exit_code)
    if not trigger:
        return HookResult.ok()

    # Get smart commit module
    sc = _get_sc()
    if not sc:
        return HookResult.ok()

    # Get all repos to potentially commit
    repos = sc.get_all_active_repos()
    if not repos:
        return HookResult.ok()

    # Get bead title if this is a bead close
    bead_title = None
    if trigger == "bead_close":
        bead_title = _extract_bead_title(command, stdout)
        sc.track_bead_close(bead_title, state.turn_count)

    # Commit each repo that has changes
    results = []
    for repo_root in repos:
        # Check if should commit (handles cooldown, no-changes, etc.)
        should, reason = sc.should_auto_commit(repo_root, trigger, state.turn_count)
        if not should:
            continue

        # Do the commit
        result = sc.do_commit(repo_root, trigger, state.turn_count, bead_title)
        results.append(result)

    # No commits happened
    if not results:
        return HookResult.ok()

    # Format results for Claude to see
    successes = [r for r in results if r.success and "no changes" not in r.message.lower()]
    failures = [r for r in results if not r.success]

    if not successes and not failures:
        return HookResult.ok()

    # Build clear feedback message
    lines = []
    if successes:
        lines.append(f"**Auto-committed ({trigger}):**")
        for r in successes:
            repo_name = Path(r.repo_root).name
            lines.append(f"  `{repo_name}`: {r.message}")

    if failures:
        lines.append("**Commit failed:**")
        for r in failures:
            repo_name = Path(r.repo_root).name
            lines.append(f"  `{repo_name}`: {r.message}")

    return HookResult.ok("\n".join(lines))


# =============================================================================
# Track manual git commits (so we know state)
# =============================================================================


@register_hook("smart_commit_track_manual", "Bash", priority=96)
def track_manual_commits(
    data: dict, state: SessionState, runner_state: dict
) -> HookResult:
    """Track manual git commits so our state stays accurate.

    This doesn't do any committing - just updates our tracking when
    Claude or user runs git commit manually.
    """
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

    # Extract commit hash to verify it actually committed
    hash_match = re.search(r"\[[\w-]+\s+([a-f0-9]{7,})\]", stdout)
    if not hash_match:
        return HookResult.ok()

    # Track the commit
    sc = _get_sc()
    if sc:
        # Find which repo this was in
        cwd = os.getcwd()
        repo_root = sc.get_repo_root(cwd)
        if repo_root:
            sc.track_commit(repo_root, state.turn_count)

    return HookResult.ok()
