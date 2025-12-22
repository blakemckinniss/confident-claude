#!/usr/bin/env python3
"""
Delegation Circuit Breakers - HARD BLOCKS forcing agent usage.

Problem: Claude ignores -8/-12 penalties and keeps wasting master thread context.
Solution: After threshold, BLOCK the direct tool and REQUIRE agent delegation.

Priority 3: Runs early, before most other gates.

SUDO EXPLORE / SUDO DEBUG / SUDO RESEARCH to bypass.
"""

from session_state import SessionState
from _hook_result import HookResult
from ._common import register_hook


# =============================================================================
# EXPLORATION CIRCUIT BREAKER (Priority 3)
# =============================================================================


@register_hook("exploration_circuit_breaker", "Grep|Glob|Read", priority=3)
def check_exploration_circuit_breaker(data: dict, state: SessionState) -> HookResult:
    """
    HARD BLOCK exploration tools after 3+ calls without Task(Explore).

    Token Economy:
    - 5 Grep calls in master thread = 5k+ tokens wasted
    - 1 Task(Explore) = 0 tokens in master, agent gets 200k

    SUDO EXPLORE to bypass.
    """
    # Check for SUDO bypass
    if data.get("_sudo_bypass") or getattr(state, "sudo_explore", False):
        return HookResult.approve()

    tool_name = data.get("tool_name", "")

    # Whitelist: Reading specific known files is fine
    if tool_name == "Read":
        tool_input = data.get("tool_input", {})
        file_path = tool_input.get("file_path", "")
        # Allow reading CLAUDE.md, rules, memory, config - these are targeted
        if any(
            p in file_path
            for p in [
                "CLAUDE.md",
                "/rules/",
                "/memory/",
                "/config/",
                "session_state",
                ".json",
                ".yaml",
                ".yml",
            ]
        ):
            return HookResult.approve()

    # Check consecutive exploration calls
    consecutive = getattr(state, "consecutive_exploration_calls", 0)

    # Check if Explore agent was used recently (within 8 turns)
    recent_explore = getattr(state, "recent_explore_agent_turn", -100)
    if state.turn_count - recent_explore < 8:
        return HookResult.approve()  # Recently used agent, allow direct calls

    # THRESHOLD: 4+ exploration calls without agent
    if consecutive >= 4:
        return HookResult.deny(
            f"🚫 **EXPLORATION BLOCKED** ({consecutive} calls without agent)\n\n"
            f"You've made {consecutive} exploration calls. MUST delegate:\n"
            f"```\n"
            f'Task(subagent_type="Explore", prompt="Find/understand X in codebase")\n'
            f"```\n"
            f"**Why:** Each call burns YOUR 200k context. Agent gets separate 200k FREE.\n\n"
            f"Say `SUDO EXPLORE` to bypass (logged)."
        )

    # Warning at 3
    if consecutive >= 3:
        return HookResult.approve(
            f"⚠️ **{consecutive} exploration calls** - next one BLOCKED without Task(Explore)"
        )

    return HookResult.approve()


# =============================================================================
# DEBUG CIRCUIT BREAKER (Priority 3)
# =============================================================================


@register_hook("debug_circuit_breaker", "Edit", priority=3)
def check_debug_circuit_breaker(data: dict, state: SessionState) -> HookResult:
    """
    HARD BLOCK editing same file 3+ times without Task(debugger).

    Pattern: Edit-test-fail-edit-test-fail loop = context waste
    Solution: Fresh debugger agent with 200k context finds it faster

    SUDO DEBUG to bypass.
    """
    # Check for SUDO bypass
    if data.get("_sudo_bypass") or getattr(state, "sudo_debug", False):
        return HookResult.approve()

    tool_input = data.get("tool_input", {})
    file_path = tool_input.get("file_path", "")

    if not file_path:
        return HookResult.approve()

    # Get edit counts per file (tracked as 'edit_counts' in state)
    edit_counts = getattr(state, "edit_counts", {})
    edits_to_this_file = edit_counts.get(file_path, 0)

    # Check if debugger agent was used recently
    recent_debugger = getattr(state, "recent_debugger_agent_turn", -100)
    if state.turn_count - recent_debugger < 10:
        return HookResult.approve()  # Recently used debugger, allow edits

    # Check if in debug mode (tool failures indicate debugging)
    consecutive_failures = getattr(state, "consecutive_tool_failures", 0)
    in_debug_mode = consecutive_failures >= 1 or edits_to_this_file >= 2

    # THRESHOLD: 3+ edits to same file while debugging
    if edits_to_this_file >= 3 and in_debug_mode:
        short_path = file_path.split("/")[-1]
        return HookResult.deny(
            f"🚫 **DEBUG LOOP BLOCKED** ({edits_to_this_file} edits to `{short_path}`)\n\n"
            f"You're stuck. MUST spawn fresh perspective:\n"
            f"```\n"
            f'Task(subagent_type="debugger", prompt="Debug: [describe the issue]")\n'
            f"```\n"
            f"**Why:** Debugger agent gets fresh 200k context + no sunk cost bias.\n\n"
            f"Say `SUDO DEBUG` to bypass (logged)."
        )

    # Warning at 2 edits
    if edits_to_this_file >= 2 and in_debug_mode:
        short_path = file_path.split("/")[-1]
        return HookResult.approve(
            f"⚠️ **{edits_to_this_file} edits to `{short_path}`** - consider Task(debugger)"
        )

    return HookResult.approve()


# =============================================================================
# RESEARCH CIRCUIT BREAKER (Priority 3)
# =============================================================================


@register_hook(
    "research_circuit_breaker",
    "WebSearch|WebFetch|mcp__crawl4ai__crawl|mcp__crawl4ai__ddg_search",
    priority=3,
)
def check_research_circuit_breaker(data: dict, state: SessionState) -> HookResult:
    """
    HARD BLOCK research tools after 3+ calls without Task(researcher).

    Pattern: Multiple web lookups for same topic = context pollution
    Solution: Researcher agent does comprehensive research in separate context

    SUDO RESEARCH to bypass.
    """
    # Check for SUDO bypass
    if data.get("_sudo_bypass") or getattr(state, "sudo_research", False):
        return HookResult.approve()

    # Check consecutive research calls
    consecutive = getattr(state, "consecutive_research_calls", 0)

    # Check if researcher agent was used recently
    recent_researcher = getattr(state, "recent_researcher_agent_turn", -100)
    if state.turn_count - recent_researcher < 8:
        return HookResult.approve()

    # THRESHOLD: 3+ research calls without agent
    if consecutive >= 3:
        return HookResult.deny(
            f"🚫 **RESEARCH BLOCKED** ({consecutive} lookups without agent)\n\n"
            f"You've made {consecutive} research calls. MUST delegate:\n"
            f"```\n"
            f'Task(subagent_type="researcher", prompt="Research: [topic]")\n'
            f"```\n"
            f"**Why:** Researcher agent does comprehensive lookup in separate 200k context.\n\n"
            f"Say `SUDO RESEARCH` to bypass (logged)."
        )

    # Warning at 2
    if consecutive >= 2:
        return HookResult.approve(
            f"⚠️ **{consecutive} research calls** - next one BLOCKED without Task(researcher)"
        )

    return HookResult.approve()


# =============================================================================
# REVIEW CIRCUIT BREAKER (Priority 3)
# =============================================================================


@register_hook("review_circuit_breaker", "Edit|Write", priority=3)
def check_review_circuit_breaker(data: dict, state: SessionState) -> HookResult:
    """
    NUDGE (not block) to spawn code-reviewer after 5+ file edits.

    Pattern: Large implementation without review = bugs slip through
    Solution: Code-reviewer agent catches blind spots

    This is a nudge, not a hard block - implementation shouldn't be interrupted.
    """
    files_edited = getattr(state, "files_edited", [])

    # Check if reviewer was used recently
    recent_reviewer = getattr(state, "recent_reviewer_agent_turn", -100)
    if state.turn_count - recent_reviewer < 20:
        return HookResult.approve()

    # Strong nudge at 5+ files
    if len(files_edited) >= 5:
        return HookResult.approve(
            f"💡 **{len(files_edited)} files edited** - spawn Task(code-reviewer) to catch blind spots"
        )

    return HookResult.approve()


__all__ = [
    "check_exploration_circuit_breaker",
    "check_debug_circuit_breaker",
    "check_research_circuit_breaker",
    "check_review_circuit_breaker",
]
