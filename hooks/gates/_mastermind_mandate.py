#!/usr/bin/env python3
"""
Mastermind Mandate Gates - HARD enforcement of Groq routing decisions.

When Groq router suggests a tool, Claude MUST use it before anything else.
This is not optional - Groq's judgment is authoritative.

Priority 1: Runs after PAL mandate (priority 0), before other gates.
"""

from session_state import SessionState
from ._common import register_hook, HookResult


def _is_pal_tool(tool_name: str) -> bool:
    """Check if tool is a PAL MCP tool."""
    return tool_name.startswith("mcp__pal__")


def _suggested_tool_matches(suggested: str, tool_name: str) -> bool:
    """Check if the tool being called matches the suggested tool.

    Handles both exact matches and PAL tool family matches:
    - "debug" matches "mcp__pal__debug"
    - "thinkdeep" matches "mcp__pal__thinkdeep"
    - Full tool names match exactly
    """
    if not suggested:
        return True  # No suggestion = no restriction

    # Exact match
    if tool_name == suggested:
        return True

    # PAL shorthand match (e.g., "debug" -> "mcp__pal__debug")
    if tool_name == f"mcp__pal__{suggested}":
        return True

    # Any PAL tool satisfies a PAL suggestion
    if suggested in ("pal", "external", "consult") and _is_pal_tool(tool_name):
        return True

    return False


# Tools always allowed regardless of mandate (investigation/research)
_ALWAYS_ALLOWED = frozenset(
    {
        "Read",
        "Grep",
        "Glob",
        "WebSearch",
        "WebFetch",
        "TodoRead",
        "AskUserQuestion",
    }
)

# Read-only bash prefixes
_READONLY_BASH = (
    "ls",
    "cat",
    "head",
    "tail",
    "pwd",
    "which",
    "tree",
    "stat",
    "git status",
    "git log",
    "git diff",
    "git show",
    "git branch",
)


@register_hook("mastermind_mandate_enforcer", None, priority=1)
def check_mastermind_mandate(data: dict, state: SessionState) -> HookResult:
    """
    HARD BLOCK: Enforce Groq's suggested tool before anything else.

    When mastermind routes a task to a specific tool, Claude MUST use that
    tool first. This is not advisory - it's mandatory.

    SUDO to bypass.
    """
    # SUDO bypass
    if data.get("_sudo_bypass"):
        return HookResult.approve("⚠️ Mastermind mandate bypassed via SUDO")

    # Check if we have a pending mandate
    suggested = state.get("mastermind_pal_suggested")
    if not suggested:
        return HookResult.approve()

    # Check if mandate was already satisfied
    if state.get("mastermind_mandate_satisfied"):
        return HookResult.approve()

    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})

    # Check if this tool satisfies the mandate
    if _suggested_tool_matches(suggested, tool_name):
        # Mark mandate as satisfied
        state.set("mastermind_mandate_satisfied", True)
        return HookResult.approve(f"✅ Mastermind mandate satisfied: `{tool_name}`")

    # Always allow investigation tools (needed to gather context)
    if tool_name in _ALWAYS_ALLOWED:
        return HookResult.approve()

    # Allow read-only bash
    if tool_name == "Bash":
        command = tool_input.get("command", "").strip()
        if any(command.startswith(prefix) for prefix in _READONLY_BASH):
            return HookResult.approve()

    # Allow read-only Task agents
    if tool_name == "Task":
        subagent = tool_input.get("subagent_type", "").lower()
        if subagent in ("explore", "plan", "scout", "researcher", "claude-code-guide"):
            return HookResult.approve()

    # Allow Serena read tools
    if tool_name.startswith("mcp__serena__") and any(
        x in tool_name for x in ("find", "get", "list", "search", "check")
    ):
        return HookResult.approve()

    # BLOCK - mandate not satisfied
    suggested_display = (
        f"mcp__pal__{suggested}" if not suggested.startswith("mcp__") else suggested
    )

    return HookResult.deny(
        f"🚨 **MASTERMIND MANDATE** - Groq routing is authoritative\n\n"
        f"**Required tool:** `{suggested_display}`\n"
        f"**Attempted tool:** `{tool_name}`\n\n"
        f"Groq analyzed this task and determined the best approach.\n"
        f"**You MUST call `{suggested_display}` first.**\n\n"
        f"**Allowed while pending:**\n"
        f"- Read/Grep/Glob/WebSearch (investigation)\n"
        f"- Read-only Bash (ls, git status, etc.)\n"
        f"- Exploration agents (Explore, Plan, Scout)\n\n"
        f"**Bypass:** Say `SUDO` (logged)"
    )


__all__ = ["check_mastermind_mandate"]
