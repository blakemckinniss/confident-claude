#!/usr/bin/env python3
"""
Workflow Prerequisite Tracking (v4.32) - PostToolUse hooks to set prerequisite flags.

These hooks run AFTER tool execution and update workflow_prerequisites flags
based on which tools were used successfully.

Priority: 8 (early, before other state updates)

Tracks:
- PAL tool usage → pal_initialized
- Memory tool usage → memory_searched
- Research tool usage → research_done
- Bead tool usage → bead_claimed
"""

import re

from _hook_registry import register_hook


# =============================================================================
# Tool patterns for prerequisite detection
# =============================================================================

# PAL MCP tools that satisfy pal_initialized
PAL_TOOLS = {
    "mcp__pal__chat",
    "mcp__pal__debug",
    "mcp__pal__thinkdeep",
    "mcp__pal__planner",
    "mcp__pal__consensus",
    "mcp__pal__codereview",
    "mcp__pal__precommit",
    "mcp__pal__analyze",
    "mcp__pal__apilookup",
    "mcp__pal__challenge",
    "mcp__pal__clink",
}

# Memory tools that satisfy memory_searched
MEMORY_TOOLS = {
    "mcp__plugin_claude-mem_mem-search__search",
    "mcp__plugin_claude-mem_mem-search__timeline",
    "mcp__plugin_claude-mem_mem-search__get_recent_context",
    "mcp__mem-search__search",
    "mcp__mem-search__timeline",
    "mcp__mem-search__get_recent_context",
    "mcp__serena__read_memory",
}

# Research tools that satisfy research_done
RESEARCH_TOOLS = {
    "WebSearch",
    "mcp__crawl4ai__crawl",
    "mcp__crawl4ai__ddg_search",
    "mcp__serena__search_for_pattern",
    "mcp__serena__find_symbol",
    "mcp__serena__get_symbols_overview",
    "mcp__serena__find_referencing_symbols",
}

# Bead tools that satisfy bead_claimed
BEAD_TOOLS = {
    "mcp__beads__create_bead",
    "mcp__beads__update_bead",
}


def _get_prerequisites(state) -> dict:
    """Get workflow prerequisites dict, ensuring it exists."""
    if (
        not hasattr(state, "workflow_prerequisites")
        or state.workflow_prerequisites is None
    ):
        state.workflow_prerequisites = {
            "groq_routed": False,
            "pal_initialized": False,
            "memory_searched": False,
            "research_done": False,
            "bead_claimed": False,
            "active_beads_checked": False,
        }
    return state.workflow_prerequisites


@register_hook("workflow_pal_tracker", None, priority=8)
def track_workflow_pal(data: dict, state, runner_state: dict) -> str | None:
    """Track PAL tool usage to set pal_initialized flag."""
    tool_name = data.get("tool_name", "")

    # Check if it's a PAL tool
    if tool_name in PAL_TOOLS or tool_name.startswith("mcp__pal__"):
        prereqs = _get_prerequisites(state)
        if not prereqs.get("pal_initialized"):
            prereqs["pal_initialized"] = True
            state.workflow_prerequisites = prereqs

    return None


@register_hook("workflow_memory_tracker", None, priority=8)
def track_workflow_memory(data: dict, state, runner_state: dict) -> str | None:
    """Track memory tool usage to set memory_searched flag."""
    tool_name = data.get("tool_name", "")

    # Check if it's a memory tool
    if tool_name in MEMORY_TOOLS:
        prereqs = _get_prerequisites(state)
        if not prereqs.get("memory_searched"):
            prereqs["memory_searched"] = True
            state.workflow_prerequisites = prereqs

    # Also check for /sm skill execution
    if tool_name == "Skill":
        skill_name = data.get("tool_input", {}).get("skill", "")
        if skill_name in ("sm", "serena-mem"):
            prereqs = _get_prerequisites(state)
            if not prereqs.get("memory_searched"):
                prereqs["memory_searched"] = True
                state.workflow_prerequisites = prereqs

    return None


@register_hook("workflow_research_tracker", None, priority=8)
def track_workflow_research(data: dict, state, runner_state: dict) -> str | None:
    """Track research tool usage to set research_done flag."""
    tool_name = data.get("tool_name", "")

    # Check if it's a research tool
    if tool_name in RESEARCH_TOOLS:
        prereqs = _get_prerequisites(state)
        if not prereqs.get("research_done"):
            prereqs["research_done"] = True
            state.workflow_prerequisites = prereqs

    # Check for Explore/researcher Task agents
    if tool_name == "Task":
        tool_input = data.get("tool_input", {})
        subagent = tool_input.get("subagent_type", "").lower()
        if subagent in ("explore", "researcher", "scout", "general-purpose"):
            prereqs = _get_prerequisites(state)
            if not prereqs.get("research_done"):
                prereqs["research_done"] = True
                state.workflow_prerequisites = prereqs

    # Track exploration patterns (3+ Grep/Glob/Read = exploration)
    if tool_name in ("Grep", "Glob", "Read"):
        exploration_count = getattr(state, "consecutive_exploration_calls", 0) + 1
        state.consecutive_exploration_calls = exploration_count
        if exploration_count >= 3:
            prereqs = _get_prerequisites(state)
            if not prereqs.get("research_done"):
                prereqs["research_done"] = True
                state.workflow_prerequisites = prereqs

    return None


@register_hook("workflow_bead_tracker", None, priority=8)
def track_workflow_bead(data: dict, state, runner_state: dict) -> str | None:
    """Track bead tool usage to set bead_claimed flag."""
    tool_name = data.get("tool_name", "")

    # Check if it's a bead creation/update tool
    if tool_name in BEAD_TOOLS:
        prereqs = _get_prerequisites(state)
        if not prereqs.get("bead_claimed"):
            prereqs["bead_claimed"] = True
            state.workflow_prerequisites = prereqs

    # Also track bd CLI commands via Bash
    if tool_name == "Bash":
        command = data.get("tool_input", {}).get("command", "")
        # Check for bd create or bd update --status=in_progress
        if re.search(r"\bbd\s+(create|update\s+.*--status[=\s]+in_progress)", command):
            prereqs = _get_prerequisites(state)
            if not prereqs.get("bead_claimed"):
                prereqs["bead_claimed"] = True
                state.workflow_prerequisites = prereqs

    return None
