#!/usr/bin/env python3
"""
PAL Mandate Gates - Multi-model orchestration enforcement.

These gates enforce the mastermind PAL consultation mandate:
- Priority 0 hard block when ^ override triggers planning requirement
- Track PAL tool usage for completion gate enforcement

Extracted from pre_tool_use_runner.py for modularity.
"""

import json
import time
from pathlib import Path

from session_state import SessionState
from ._common import register_hook, HookResult

# =============================================================================
# PAL MANDATE CONFIG (Import from centralized config or fallback)
# =============================================================================

try:
    from mastermind.config import PAL_MANDATE_LOCK_PATH, PAL_MANDATE_TTL_MINUTES
except ImportError:
    # Fallback if mastermind not available
    PAL_MANDATE_LOCK_PATH = Path.home() / ".claude" / "tmp" / "pal_mandate.lock"
    PAL_MANDATE_TTL_MINUTES = 30


# =============================================================================
# PAL MANDATE LOCK HELPERS
# =============================================================================


def check_pal_mandate_lock() -> dict | None:
    """Check if PAL mandate lock exists, is valid, and not expired.

    Returns lock contents if valid, None if missing/expired/invalid.
    Auto-clears expired locks based on PAL_MANDATE_TTL_MINUTES.
    """
    if not PAL_MANDATE_LOCK_PATH.exists():
        return None

    try:
        lock_data = json.loads(PAL_MANDATE_LOCK_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return None

    # Check TTL
    created_at = lock_data.get("created_at", 0)
    if created_at and (time.time() - created_at) > (PAL_MANDATE_TTL_MINUTES * 60):
        # Lock expired - auto-clear
        try:
            PAL_MANDATE_LOCK_PATH.unlink()
        except OSError:
            pass
        return None

    return lock_data


def clear_pal_mandate_lock() -> None:
    """Clear the PAL mandate lock file."""
    if PAL_MANDATE_LOCK_PATH.exists():
        PAL_MANDATE_LOCK_PATH.unlink()


# =============================================================================
# PAL MANDATE ENFORCER (Priority 0) - Highest priority, runs first
# =============================================================================


@register_hook("pal_mandate_enforcer", None, priority=0)
def check_pal_mandate_enforcer(data: dict, state: SessionState) -> HookResult:
    """
    🚨 PRIORITY 0 HARD BLOCK: Enforce PAL MCP planner usage.

    When user triggers ^ override, a lock file is created. This hook BLOCKS
    ALL tools except mcp__pal__planner until Claude obeys.

    ONLY WAY TO CLEAR:
    1. Call mcp__pal__planner with model containing "gpt-5" or "gpt5"
    2. User says SUDO (bypass)
    3. Lock file manually deleted

    This implements the mastermind multi-model orchestration mandate.
    """
    from _log import log_debug

    lock = check_pal_mandate_lock()
    if not lock:
        return HookResult.approve()

    # SUDO bypass
    if data.get("_sudo_bypass"):
        clear_pal_mandate_lock()
        return HookResult.approve("⚠️ PAL mandate bypassed via SUDO")

    tool_name = data.get("tool_name", "")

    # Check if this IS a PAL MCP tool call (any PAL tool satisfies the mandate)
    if isinstance(tool_name, str) and tool_name.startswith("mcp__pal__"):
        clear_pal_mandate_lock()
        # Mark session as bootstrapped so Groq routing stops
        try:
            from mastermind.state import load_state, save_state
            from mastermind.hook_integration import get_session_id

            session_id = get_session_id()
            mm_state = load_state(session_id)
            mm_state.mark_bootstrapped()
            mm_state.pal_consulted = True
            save_state(mm_state)
        except (ImportError, FileNotFoundError, AttributeError) as e:
            log_debug(
                "pre_tool_use_runner",
                f"[mastermind] Failed to mark session bootstrapped: {e}",
            )
        return HookResult.approve(
            f"✅ **PAL MANDATE SATISFIED** - `{tool_name}` invoked. Session bootstrapped."
        )

    # Allow read-only investigation tools (can't cause harm)
    if tool_name in (
        "Read",
        "Grep",
        "Glob",
        "LS",
        "WebSearch",
        "WebFetch",
        "AskUserQuestion",
        "TaskOutput",
        "TodoRead",
        "NotebookRead",
    ):
        return HookResult.approve()

    # Allow read-only Bash commands (inspection, no state changes)
    if tool_name == "Bash":
        command = data.get("tool_input", {}).get("command", "")
        READ_ONLY_BASH_PREFIXES = (
            # File/directory inspection
            "ls",
            "cat",
            "head",
            "tail",
            "pwd",
            "which",
            "tree",
            "stat",
            "file",
            "wc",
            "du",
            "df",
            "realpath",
            "dirname",
            "basename",
            # Text processing (read-only)
            "grep",
            "awk",
            "sed",
            "sort",
            "uniq",
            "cut",
            "tr",
            # System info
            "env",
            "printenv",
            "whoami",
            "hostname",
            "uname",
            "date",
            "id",
            "groups",
            "type",
            "man",
            "help",
            "ps",
            "top",
            "lsof",
            # Pagers
            "less",
            "more",
            # Git read-only operations
            "git status",
            "git log",
            "git diff",
            "git show",
            "git branch",
            "git remote",
            "git tag",
            "git blame",
            "git rev-parse",
            "git ls-files",
            "git ls-tree",
            "git cat-file",
            # Hash/verification
            "md5sum",
            "sha256sum",
            "sha1sum",
            "strings",
        )
        # Check if command starts with a read-only prefix
        cmd_stripped = command.strip()
        if any(cmd_stripped.startswith(prefix) for prefix in READ_ONLY_BASH_PREFIXES):
            return HookResult.approve()

    # Allow read-only Task agent types (exploration, research, documentation)
    if tool_name == "Task":
        tool_input = data.get("tool_input", {})
        subagent_type = tool_input.get("subagent_type", "")
        READ_ONLY_AGENTS = (
            "Explore",  # Codebase exploration
            "claude-code-guide",  # Documentation lookup
            "Plan",  # Planning/analysis only
            "planner",  # Planning/analysis only
            "Scout",  # Codebase exploration
            "researcher",  # Research specialist
        )
        if subagent_type in READ_ONLY_AGENTS:
            return HookResult.approve()

    # Allow SAFE MCP tools (read-only / memory / research)
    # NOT blanket mcp__* - that defeats the lock (filesystem writes, playwright actions)
    SAFE_MCP_PREFIXES = (
        "mcp__plugin_claude-mem_",  # Memory tools
        "mcp__serena__",  # Semantic code analysis
        "mcp__crawl4ai__",  # Web research
        "mcp__plugin_repomix-mcp_repomix__",  # Code packing (read-only)
        "mcp__beads__",  # Beads task tracking
    )
    if isinstance(tool_name, str) and tool_name.startswith(SAFE_MCP_PREFIXES):
        return HookResult.approve()

    # BLOCK EVERYTHING ELSE (Edit, Write, Bash, Task, filesystem, playwright, beads, etc.)
    session_id = lock.get("session_id", "unknown")
    project = lock.get("project", "unknown")
    prompt_preview = lock.get("prompt", "")[:100]

    return HookResult.deny(
        f"🚨 **PAL MANDATE ENFORCED** (Priority 0 Hard Block)\n\n"
        f"**This task requires external consultation before proceeding.**\n"
        f"You MUST call a PAL MCP tool (`mcp__pal__*`) FIRST.\n\n"
        f"**Blocked tool:** `{tool_name}`\n"
        f"**Session:** `{session_id}`\n"
        f"**Project:** `{project}`\n"
        f"**Original request:** `{prompt_preview}...`\n\n"
        f"**ALLOWED PAL TOOLS:**\n"
        f"- `mcp__pal__planner` - Strategic planning\n"
        f"- `mcp__pal__debug` - Debugging analysis\n"
        f"- `mcp__pal__codereview` - Code review\n"
        f"- `mcp__pal__consensus` - Architecture decisions\n"
        f"- `mcp__pal__chat` - General discussion\n"
        f"- `mcp__pal__thinkdeep` - Problem decomposition\n\n"
        f"**ALSO ALLOWED:** Read/Grep/Glob/LS/WebSearch/WebFetch, AskUserQuestion,\n"
        f"read-only Bash (ls, cat, git status, etc.), read-only Task agents (Explore, claude-code-guide, Plan),\n"
        f"serena/claude-mem/crawl4ai/repomix/beads MCP tools, SUDO to bypass\n\n"
        f"**Choose the PAL tool that best fits this task.**"
    )


# =============================================================================
# PAL TOOL TRACKER (Priority 1) - Track when any PAL MCP tool is used
# =============================================================================


@register_hook("pal_tool_tracker", "mcp__pal__.*", priority=1)
def track_pal_tool_usage(data: dict, state: SessionState) -> HookResult:
    """
    Track when any PAL MCP tool is called.

    Sets pal_consulted=True in mastermind state for completion gate enforcement.
    This supports the hybrid routing approach where Claude can choose any PAL tool.
    """
    tool_name = data.get("tool_name", "")

    # Only track actual PAL tool calls
    if not tool_name.startswith("mcp__pal__"):
        return HookResult.approve()

    # Set pal_consulted flag in mastermind state
    try:
        from mastermind.state import load_state, save_state

        # Get session_id from hook input data (not env var)
        session_id = data.get("session_id", "")[:16]
        if session_id:
            mm_state = load_state(session_id)
            if not getattr(mm_state, "pal_consulted", False):
                mm_state.pal_consulted = True
                save_state(mm_state)
    except (ImportError, FileNotFoundError, AttributeError):
        # Mastermind state unavailable - non-critical, continue
        pass

    return HookResult.approve()
