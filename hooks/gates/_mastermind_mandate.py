#!/usr/bin/env python3
"""
Mastermind Mandate Gates - HARD enforcement of Groq routing decisions.

When Groq router issues mandates, Claude MUST satisfy them before anything else.
This is not optional - Groq's judgment is authoritative.

v4.33: Enhanced to support all mandate types (pal, research, agent, bead, ask_user, etc.)

Priority 1: Runs after PAL mandate (priority 0), before other gates.
"""

import json

from session_state import SessionState
from ._common import register_hook, HookResult


def _persist_mandate_satisfaction(
    state: SessionState, mandates: list[dict], policy: str
) -> None:
    """Persist mandate state to MastermindState for cross-turn/compaction survival.

    v4.33.1: Ensures mandates survive session compaction and handoff.
    Uses session_id from state for proper isolation.
    """
    try:
        session_id = state.get("session_id")
        if not session_id:
            return  # No session tracking, skip persistence

        from lib.mastermind.state import load_state, save_state

        # Load current state (with file locking)
        mm_state = load_state(session_id)

        # Update mandates
        mm_state.pending_mandates = mandates
        mm_state.mandate_policy = policy

        # Persist (atomic write with lock)
        save_state(mm_state)
    except (OSError, ImportError, json.JSONDecodeError) as e:
        # Fail-safe: persistence errors should not block tool execution
        # This is intentional - mandate enforcement continues even if persistence fails
        import sys

        print(f"[mandate-persist] Warning: {e}", file=sys.stderr)


def _is_pal_tool(tool_name: str) -> bool:
    """Check if tool is a PAL MCP tool."""
    return tool_name.startswith("mcp__pal__")


# Tools always allowed regardless of mandate (investigation/research)
_ALWAYS_ALLOWED = frozenset(
    {
        "Read",
        "Grep",
        "Glob",
        "TodoRead",
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

# Mandate type to tool pattern mapping
_MANDATE_PATTERNS = {
    "pal": ["mcp__pal__"],
    "research": ["mcp__crawl4ai__", "WebSearch", "WebFetch", "mcp__pal__apilookup"],
    "agent": ["Task"],
    "script": ["Write"],
    "bead": ["mcp__beads__create", "mcp__beads__update"],
    "ask_user": ["AskUserQuestion"],
    "plan_mode": ["EnterPlanMode"],
    "project_research": ["mcp__serena__", "Grep", "Glob", "Task"],
}


def _check_mandate_satisfaction(
    mandate: dict, tool_name: str, tool_input: dict
) -> bool:
    """Check if a tool use satisfies a specific mandate."""
    mtype = mandate.get("type", "")
    patterns = _MANDATE_PATTERNS.get(mtype, [])

    for pattern in patterns:
        if pattern in tool_name:
            # Type-specific validation
            if mtype == "pal":
                specified_tool = mandate.get("tool")
                if specified_tool:
                    # Must match specific PAL tool
                    if specified_tool in tool_name:
                        return True
                    # Allow shorthand: "debug" matches "mcp__pal__debug"
                    if f"mcp__pal__{specified_tool}" in tool_name:
                        return True
                    continue  # Wrong PAL tool
                return True  # Any PAL tool satisfies generic pal mandate

            if mtype == "agent":
                specified_subagent = mandate.get("subagent")
                if specified_subagent:
                    subagent_type = tool_input.get("subagent_type", "")
                    if subagent_type.lower() != specified_subagent.lower():
                        continue  # Wrong agent type
                return True

            if mtype == "script":
                path = tool_input.get("file_path", "")
                if "/.claude/tmp/" not in path or not path.endswith(".py"):
                    continue  # Not a tmp script
                return True

            if mtype == "project_research" and tool_name == "Task":
                subagent = tool_input.get("subagent_type", "").lower()
                if subagent not in ("explore", "scout", "researcher"):
                    continue  # Not exploration agent
                return True

            return True

    return False


def _get_unsatisfied_blocking(mandates: list[dict]) -> list[dict]:
    """Get blocking mandates that haven't been satisfied."""
    return [m for m in mandates if m.get("blocking") and not m.get("satisfied")]


def _format_mandate_block_message(mandates: list[dict], tool_name: str) -> str:
    """Format the block message showing required mandates."""
    lines = [
        "🚨 **GROQ MANDATES ACTIVE** - Complete required actions first\n",
        "**Attempted:** `{}`\n".format(tool_name),
        "**Required actions (blocking):**",
    ]

    for i, m in enumerate(mandates[:5], 1):
        mtype = m.get("type", "unknown").upper()
        reason = m.get("reason", "Required by router")
        priority = m.get("priority", "p1")
        icon = {"p0": "🔴", "p1": "🟡", "p2": "🔵"}.get(priority, "🟡")

        # Format tool hint
        tool_hint = _format_tool_hint(m)
        lines.append(f"\n{i}. {icon} **{mtype}**: {reason}")
        lines.append(f"   → `{tool_hint}`")

    lines.append("\n\n**Allowed while pending:**")
    lines.append("- Read/Grep/Glob (investigation)")
    lines.append("- Read-only Bash (ls, git status, etc.)")
    lines.append("- Serena read tools")
    lines.append("\n**Bypass:** Say `SUDO` (logged)")

    return "\n".join(lines)


def _format_tool_hint(m: dict) -> str:
    """Format tool usage hint for a mandate."""
    mtype = m.get("type", "")

    if mtype == "pal":
        tool = m.get("tool", "chat")
        if not tool.startswith("mcp__"):
            tool = f"mcp__pal__{tool}"
        return tool

    if mtype == "research":
        tool = m.get("tool", "mcp__crawl4ai__ddg_search")
        query = m.get("query", "")
        if query:
            return f'{tool}(query="{query[:50]}...")'
        return tool

    if mtype == "agent":
        subagent = m.get("subagent", "Explore")
        return f'Task(subagent_type="{subagent}")'

    if mtype == "bead":
        action = m.get("action", "create")
        if action == "create":
            return 'mcp__beads__create_bead(title="...")'
        return 'mcp__beads__update_bead(status="in_progress")'

    if mtype == "ask_user":
        return "AskUserQuestion"

    if mtype == "plan_mode":
        return "EnterPlanMode"

    if mtype == "project_research":
        return 'Task(subagent_type="Explore") or mcp__serena__*'

    if mtype == "script":
        return 'Write(file_path="~/.claude/tmp/<task>.py")'

    return mtype


@register_hook("mastermind_mandate_enforcer", None, priority=1)
def check_mastermind_mandate(data: dict, state: SessionState) -> HookResult:
    """
    HARD BLOCK: Enforce Groq's mandatory tool directives.

    When mastermind routes a task with mandates, Claude MUST satisfy
    all blocking mandates before using other tools.

    SUDO to bypass.
    """
    # SUDO bypass
    if data.get("_sudo_bypass"):
        return HookResult.approve("⚠️ Mastermind mandates bypassed via SUDO")

    # Get pending mandates from state
    mandates = state.get("pending_mandates", [])
    policy = state.get("mandate_policy", "strict")

    # No mandates = no restriction
    if not mandates:
        # Fallback: check legacy single-tool mandate
        suggested = state.get("mastermind_pal_suggested")
        if not suggested or state.get("mastermind_mandate_satisfied"):
            return HookResult.approve()
        # Convert legacy to new format for consistent handling
        mandates = [
            {
                "type": "pal",
                "tool": suggested,
                "reason": "Groq routing decision",
                "priority": "p0",
                "blocking": True,
                "satisfied": False,
            }
        ]

    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})

    # Check if this tool satisfies any unsatisfied mandate
    for m in mandates:
        if m.get("satisfied"):
            continue
        if _check_mandate_satisfaction(m, tool_name, tool_input):
            # Mark as satisfied
            m["satisfied"] = True
            m["satisfied_by"] = tool_name
            state.set("pending_mandates", mandates)

            # v4.33.1: Persist to MastermindState for cross-turn/compaction survival
            _persist_mandate_satisfaction(state, mandates, policy)

            return HookResult.approve(
                f"✅ Mandate satisfied: {m.get('type', 'unknown').upper()}"
            )

    # Get unsatisfied blocking mandates
    blocking = _get_unsatisfied_blocking(mandates)

    # No blocking mandates remaining = allow
    if not blocking:
        return HookResult.approve()

    # Always allow basic investigation tools
    if tool_name in _ALWAYS_ALLOWED:
        return HookResult.approve()

    # Allow read-only bash
    if tool_name == "Bash":
        command = tool_input.get("command", "").strip()
        if any(command.startswith(prefix) for prefix in _READONLY_BASH):
            return HookResult.approve()

    # Allow read-only Task agents (Explore, scout for investigation)
    if tool_name == "Task":
        subagent = tool_input.get("subagent_type", "").lower()
        if subagent in ("explore", "scout", "claude-code-guide"):
            return HookResult.approve()

    # Allow Serena read tools
    if tool_name.startswith("mcp__serena__"):
        read_patterns = ("find", "get", "list", "search", "check", "read")
        if any(x in tool_name for x in read_patterns):
            return HookResult.approve()

    # Allow mem-search (memory lookups)
    if "mem-search" in tool_name or "mem_search" in tool_name:
        return HookResult.approve()

    # Lenient policy = warn only
    if policy == "lenient":
        count = len(blocking)
        return HookResult.approve(
            f"⚠️ {count} blocking mandate(s) pending - complete soon"
        )

    # BLOCK - mandates not satisfied
    return HookResult.deny(_format_mandate_block_message(blocking, tool_name))


__all__ = ["check_mastermind_mandate"]
