#!/usr/bin/env python3
"""
Tool Debt System v2.0 - Pressure-to-remember mechanism.

The LLM doesn't actively avoid tools - it just forgets they exist.
This system creates mounting pressure to use framework capabilities
by applying small per-turn penalties that accumulate until tools are used.

Debt Families (v2.0):
1. PAL MCP tools - external LLM consultation
2. Serena - semantic code analysis
3. Beads - task tracking
4. Agent Delegation - spawning Task agents for complex work
5. Skills - invoking available skills
6. Clarification - asking user questions when uncertain
7. Tech Debt Cleanup - addressing surfaced issues

Design:
- Each family accumulates debt when not used (configurable rate)
- Using the tool recovers a percentage of accumulated debt
- Debt is capped to prevent runaway penalties
- Grace periods allow startup without immediate penalties

This creates:
1. Mounting pressure to remember tools exist
2. Relief/reward when finally using them
3. Net benefit for early usage vs late usage
"""

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from _session_state_class import SessionState


# =============================================================================
# CONFIGURATION
# =============================================================================

TOOL_DEBT_CONFIG = {
    # === Original Tool Families ===
    "pal": {
        "rate": 1,  # -1 per turn without PAL
        "recovery": 0.5,  # Get back 50% when used
        "cap": 15,  # Max debt accumulation
        "grace_turns": 3,  # Don't penalize first N turns
        "description": "PAL MCP consultation",
    },
    "serena": {
        "rate": 1,
        "recovery": 0.5,
        "cap": 15,
        "grace_turns": 5,  # Serena needs activation first
        "requires": "serena_activated",  # Only penalize if serena is available
        "description": "Serena semantic analysis",
    },
    "beads": {
        "rate": 1,
        "recovery": 0.5,
        "cap": 10,
        "grace_turns": 3,
        "description": "Beads task tracking",
    },
    # === New Families (v2.0) ===
    "agent_delegation": {
        "rate": 1,
        "recovery": 0.5,
        "cap": 12,
        "grace_turns": 5,  # Simple tasks don't need agents
        "requires": "complex_task",  # Only penalize for complex tasks
        "description": "Task agent delegation",
    },
    "skills": {
        "rate": 1,
        "recovery": 0.5,
        "cap": 8,
        "grace_turns": 2,
        "requires": "skill_match",  # Only penalize when skill matches task
        "description": "Skill invocation",
    },
    "clarification": {
        "rate": 2,  # Higher rate - assumptions are costly
        "recovery": 0.5,
        "cap": 10,
        "grace_turns": 2,  # Should clarify early
        "requires": "vague_prompt",  # Only penalize for vague prompts
        "description": "User clarification",
    },
    "tech_debt_cleanup": {
        "rate": 1,
        "recovery": 1.0,  # Full recovery - actually fixing is good
        "cap": 15,
        "grace_turns": 3,  # Time to finish primary task first
        "requires": "debt_surfaced",  # Only penalize when debt is known
        "description": "Tech debt cleanup",
    },
}

# Keywords that indicate vague/ambiguous prompts needing clarification
VAGUE_PROMPT_INDICATORS = [
    r"\bmake\s+it\s+better\b",
    r"\bfix\s+this\b",
    r"\bsomething\s+like\b",
    r"\bimprove\b",
    r"\bupdate\b",
    r"\bchange\b",
    r"\btweak\b",
    r"\bmodify\b",
    r"\benhance\b",
    r"\boptimize\b",
    r"\bclean\s*up\b",
    r"\brefactor\b",
]

# Skill keywords for matching
SKILL_KEYWORDS = {
    "frontend-design": ["frontend", "ui", "component", "page", "interface", "design"],
    "debugging": ["debug", "bug", "error", "fix", "issue", "broken"],
    "testing": ["test", "spec", "coverage", "unit test", "integration"],
    "code-quality": ["lint", "quality", "clean", "style"],
    "database": ["database", "db", "sql", "query", "migration"],
    "api-development": ["api", "endpoint", "rest", "graphql"],
    "security-audit": ["security", "auth", "vulnerability", "safe"],
    "performance": ["performance", "slow", "optimize", "speed", "memory"],
    "refactoring": ["refactor", "restructure", "reorganize"],
}

# Tech debt indicators (when surfaced in output)
TECH_DEBT_INDICATORS = [
    r"\bTODO\b",
    r"\bFIXME\b",
    r"\bHACK\b",
    r"\bXXX\b",
    r"code\s+smell",
    r"tech(?:nical)?\s+debt",
    r"quick\s+win",
    r"should\s+(?:be\s+)?refactor",
    r"needs?\s+cleanup",
    r"deprecated",
]


# =============================================================================
# STATE HELPERS
# =============================================================================


def _init_debt_entry() -> dict:
    """Create a new debt tracking entry."""
    return {"turns_without": 0, "last_used_turn": 0}


def get_tool_debt(state: "SessionState") -> dict:
    """Get current tool debt from state, initializing if needed."""
    if not hasattr(state, "tool_debt") or state.tool_debt is None:
        state.tool_debt = {}

    # Ensure all families exist
    for family in TOOL_DEBT_CONFIG:
        if family not in state.tool_debt:
            state.tool_debt[family] = _init_debt_entry()

    return state.tool_debt


def mark_tool_used(state: "SessionState", family: str) -> int:
    """
    Mark a tool family as used this turn.

    Returns the confidence recovery amount based on configured recovery rate.
    """
    debt = get_tool_debt(state)
    if family not in debt:
        return 0

    config = TOOL_DEBT_CONFIG.get(family, {})
    recovery_rate = config.get("recovery", 0.5)
    cap = config.get("cap", 15)

    # Calculate recovery based on accumulated turns
    accumulated = min(debt[family]["turns_without"], cap)
    recovery = int(accumulated * recovery_rate)

    # Reset the debt counter
    debt[family]["turns_without"] = 0
    debt[family]["last_used_turn"] = state.turn_count

    return recovery


def _check_requirement(state: "SessionState", context: dict, requirement: str) -> bool:
    """Check if a conditional requirement is met for debt accumulation."""
    if requirement == "serena_activated":
        return getattr(state, "serena_activated", False)

    if requirement == "complex_task":
        # Check mastermind classification or file count
        classification = context.get("task_classification", "")
        files_edited = len(getattr(state, "files_edited", []))
        return classification == "complex" or files_edited >= 5

    if requirement == "skill_match":
        # Check if any skill keywords match the current task
        return context.get("_skill_match_detected", False)

    if requirement == "vague_prompt":
        # Check if prompt has vague indicators
        return context.get("_vague_prompt_detected", False)

    if requirement == "debt_surfaced":
        # Check if tech debt was mentioned in recent output
        return context.get("_tech_debt_surfaced", False)

    return True  # No requirement = always active


def detect_vague_prompt(prompt: str) -> bool:
    """Detect if a prompt is vague and would benefit from clarification."""
    prompt_lower = prompt.lower()
    for pattern in VAGUE_PROMPT_INDICATORS:
        if re.search(pattern, prompt_lower):
            return True
    return False


def detect_skill_match(prompt: str, available_skills: list[str]) -> bool:
    """Detect if any available skill matches the prompt."""
    prompt_lower = prompt.lower()
    for skill, keywords in SKILL_KEYWORDS.items():
        if skill in available_skills or any(
            s.endswith(skill) for s in available_skills
        ):
            if any(kw in prompt_lower for kw in keywords):
                return True
    return False


def detect_tech_debt_surfaced(output: str) -> bool:
    """Detect if tech debt indicators were surfaced in output."""
    for pattern in TECH_DEBT_INDICATORS:
        if re.search(pattern, output, re.IGNORECASE):
            return True
    return False


def tick_tool_debt(
    state: "SessionState", tools_used_this_turn: set, context: dict
) -> int:
    """
    Called at end of turn to increment debt for unused tools.

    Args:
        state: Session state
        tools_used_this_turn: Set of tool families used this turn
        context: Context dict with detection flags

    Returns:
        Total penalty to apply this turn (capped at MAX_TOOL_DEBT_PER_TURN).
    """
    # CRITICAL: Only tick once per turn to prevent accumulating penalties
    # from multiple tool uses in the same turn
    last_ticked = getattr(state, "_tool_debt_last_tick", -1)
    if last_ticked == state.turn_count:
        return 0  # Already ticked this turn
    state._tool_debt_last_tick = state.turn_count

    debt = get_tool_debt(state)
    total_penalty = 0

    # Cap total tool debt penalty per turn to prevent excessive passive drain
    MAX_TOOL_DEBT_PER_TURN = 2

    for family, config in TOOL_DEBT_CONFIG.items():
        grace = config.get("grace_turns", 3)
        rate = config.get("rate", 1)
        cap = config.get("cap", 15)
        requirement = config.get("requires")

        # Skip penalty during grace period
        if state.turn_count <= grace:
            continue

        # Skip if conditional requirement not met
        if requirement and not _check_requirement(state, context, requirement):
            continue

        # If tool wasn't used this turn, increment debt
        if family not in tools_used_this_turn:
            debt[family]["turns_without"] += 1
            # Apply penalty (capped)
            current_debt = min(debt[family]["turns_without"], cap)
            if current_debt > 0:
                total_penalty += rate

    # Cap total penalty to prevent multi-family piling
    return min(total_penalty, MAX_TOOL_DEBT_PER_TURN)


def get_debt_summary(state: "SessionState") -> str:
    """Get a formatted summary of current tool debt for display."""
    debt = get_tool_debt(state)
    parts = []

    for family, config in TOOL_DEBT_CONFIG.items():
        cap = config.get("cap", 15)
        turns = min(debt[family]["turns_without"], cap)
        if turns > 0:
            recovery_rate = config.get("recovery", 0.5)
            potential_recovery = int(turns * recovery_rate)
            parts.append(f"{family}: -{turns} (+{potential_recovery})")

    if not parts:
        return ""

    return "🔋 Debt: " + " | ".join(parts)


def get_debt_for_family(state: "SessionState", family: str) -> int:
    """Get current debt for a specific family."""
    debt = get_tool_debt(state)
    if family not in debt:
        return 0
    config = TOOL_DEBT_CONFIG.get(family, {})
    cap = config.get("cap", 15)
    return min(debt[family]["turns_without"], cap)


# =============================================================================
# TOOL DETECTION HELPERS
# =============================================================================


def detect_tool_family(
    tool_name: str, bash_command: str = "", context: dict = None
) -> str | None:
    """
    Detect which tool family a tool belongs to.

    Returns: family name or None
    """
    context = context or {}

    # PAL MCP tools
    if tool_name.startswith("mcp__pal__"):
        return "pal"

    # Serena MCP tools
    if tool_name.startswith("mcp__serena__"):
        return "serena"

    # Beads via bash
    if tool_name == "Bash" and bash_command.strip().startswith("bd "):
        # Only count substantive bd commands, not just listing
        if not bash_command.strip().startswith("bd list"):
            return "beads"

    # Task tool = agent delegation
    if tool_name == "Task":
        return "agent_delegation"

    # Skill tool
    if tool_name == "Skill":
        return "skills"

    # AskUserQuestion = clarification
    if tool_name == "AskUserQuestion":
        return "clarification"

    # Tech debt cleanup is detected via outcome, not tool
    # (when Edit/Write addresses a surfaced issue)

    return None


def detect_tech_debt_fix(tool_name: str, context: dict) -> bool:
    """
    Detect if a tool use is addressing tech debt.

    Returns True if this looks like a debt cleanup action.
    """
    if tool_name not in ("Edit", "Write"):
        return False

    # Check if we have surfaced debt AND this edit is in a flagged file
    surfaced_files = context.get("_tech_debt_files", set())
    current_file = context.get("file_path", "")

    return current_file in surfaced_files


# =============================================================================
# REDUCERS
# =============================================================================


@dataclass
class ToolDebtReducer:
    """
    Applies per-turn penalty for not using framework tools.

    This reducer is special - it doesn't check for bad behavior,
    it checks for absence of good behavior (tool usage).
    """

    name: str = "tool_debt"
    delta: int = -1  # Per tool family per turn
    description: str = "Framework tool not used"
    cooldown_turns: int = 0  # No cooldown - applies every turn

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> tuple[bool, int, str]:
        """
        Check tool debt and return (should_trigger, total_penalty, reason).

        Unlike other reducers, this can return variable penalties.
        """
        # Collect tools used this turn
        tools_used = set()

        tool_name = context.get("tool_name", "")
        bash_cmd = context.get("bash_command", "")

        family = detect_tool_family(tool_name, bash_cmd, context)
        if family:
            tools_used.add(family)

        # Also check context for tools used earlier in the turn
        turn_tools = context.get("turn_tool_families", set())
        tools_used.update(turn_tools)

        # Check for tech debt fix
        if detect_tech_debt_fix(tool_name, context):
            tools_used.add("tech_debt_cleanup")

        # Calculate penalty
        penalty = tick_tool_debt(state, tools_used, context)

        if penalty > 0:
            debt = get_tool_debt(state)
            reasons = []
            for family in TOOL_DEBT_CONFIG:
                turns = debt[family]["turns_without"]
                if turns > 0:
                    reasons.append(f"{family}:{turns}t")
            reason = (
                f"tool_debt ({', '.join(reasons[:4])})"  # Limit to 4 for readability
            )
            return True, penalty, reason

        return False, 0, ""


# =============================================================================
# INCREASERS
# =============================================================================


@dataclass
class ToolDebtRecoveryIncreaser:
    """
    Recovers percentage of accumulated debt when a tool family is used.

    This creates the "pressure release" that makes tool usage feel rewarding.
    """

    name: str = "tool_debt_recovery"
    delta: int = 0  # Dynamic based on debt
    description: str = "Framework tool used (debt recovered)"
    requires_approval: bool = False
    cooldown_turns: int = 0  # No cooldown - can recover multiple families

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> tuple[bool, int]:
        """
        Check if tool was used and calculate recovery.

        Returns (should_trigger, recovery_amount).
        """
        tool_name = context.get("tool_name", "")
        bash_cmd = context.get("bash_command", "")

        family = detect_tool_family(tool_name, bash_cmd, context)

        # Also check for tech debt fix
        if not family and detect_tech_debt_fix(tool_name, context):
            family = "tech_debt_cleanup"

        if not family:
            return False, 0

        # Calculate and apply recovery
        recovery = mark_tool_used(state, family)

        if recovery > 0:
            return True, recovery

        return False, 0


# =============================================================================
# CONTEXT ENRICHMENT
# =============================================================================


def enrich_context_for_debt(context: dict, state: "SessionState") -> dict:
    """
    Enrich context with debt-related detection flags.

    Call this early in the hook pipeline to set detection flags.
    """
    # Detect vague prompt
    user_prompt = context.get("user_prompt", "")
    if user_prompt:
        context["_vague_prompt_detected"] = detect_vague_prompt(user_prompt)

    # Detect skill match (need available skills from somewhere)
    available_skills = context.get("available_skills", [])
    if user_prompt and available_skills:
        context["_skill_match_detected"] = detect_skill_match(
            user_prompt, available_skills
        )

    # Detect tech debt surfaced in recent output
    recent_output = context.get("recent_output", "")
    if recent_output:
        context["_tech_debt_surfaced"] = detect_tech_debt_surfaced(recent_output)

    return context


# =============================================================================
# EXPORTS
# =============================================================================

# Singleton instances for registration
TOOL_DEBT_REDUCER = ToolDebtReducer()
TOOL_DEBT_RECOVERY_INCREASER = ToolDebtRecoveryIncreaser()

__all__ = [
    "TOOL_DEBT_CONFIG",
    "VAGUE_PROMPT_INDICATORS",
    "SKILL_KEYWORDS",
    "TECH_DEBT_INDICATORS",
    "get_tool_debt",
    "mark_tool_used",
    "tick_tool_debt",
    "get_debt_summary",
    "get_debt_for_family",
    "detect_tool_family",
    "detect_vague_prompt",
    "detect_skill_match",
    "detect_tech_debt_surfaced",
    "detect_tech_debt_fix",
    "enrich_context_for_debt",
    "ToolDebtReducer",
    "ToolDebtRecoveryIncreaser",
    "TOOL_DEBT_REDUCER",
    "TOOL_DEBT_RECOVERY_INCREASER",
]
