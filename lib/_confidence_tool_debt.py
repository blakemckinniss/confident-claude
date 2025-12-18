#!/usr/bin/env python3
"""
Tool Debt System v1.0 - Pressure-to-remember mechanism.

The LLM doesn't actively avoid tools - it just forgets they exist.
This system creates mounting pressure to use PAL, Serena, and Beads
by applying small per-turn penalties that accumulate until tools are used.

Design:
- Each tool family accumulates -1/turn debt when not used
- Using the tool recovers 50% of accumulated debt
- Debt is capped to prevent runaway penalties

This creates:
1. Mounting pressure to remember tools exist
2. Relief/reward when finally using them
3. Net benefit for early usage vs late usage (50% recovery < 100%)
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from _session_state_class import SessionState


# =============================================================================
# CONFIGURATION
# =============================================================================

TOOL_DEBT_CONFIG = {
    "pal": {
        "rate": 1,       # -1 per turn without PAL
        "recovery": 0.5,  # Get back 50% when used
        "cap": 15,       # Max debt accumulation
        "grace_turns": 3, # Don't penalize first N turns
    },
    "serena": {
        "rate": 1,
        "recovery": 0.5,
        "cap": 15,
        "grace_turns": 5,  # Serena needs activation first
    },
    "beads": {
        "rate": 1,
        "recovery": 0.5,
        "cap": 10,
        "grace_turns": 3,
    },
}


# =============================================================================
# STATE HELPERS
# =============================================================================

def get_tool_debt(state: "SessionState") -> dict:
    """Get current tool debt from state, initializing if needed."""
    if not hasattr(state, "tool_debt") or state.tool_debt is None:
        state.tool_debt = {
            "pal": {"turns_without": 0, "last_used_turn": 0},
            "serena": {"turns_without": 0, "last_used_turn": 0},
            "beads": {"turns_without": 0, "last_used_turn": 0},
        }
    return state.tool_debt


def mark_tool_used(state: "SessionState", family: str) -> int:
    """
    Mark a tool family as used this turn.

    Returns the confidence recovery amount (50% of accumulated debt).
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


def tick_tool_debt(state: "SessionState", tools_used_this_turn: set) -> int:
    """
    Called at end of turn to increment debt for unused tools.

    Args:
        state: Session state
        tools_used_this_turn: Set of tool families used this turn
                             ("pal", "serena", "beads")

    Returns:
        Total penalty to apply this turn.
    """
    debt = get_tool_debt(state)
    total_penalty = 0

    for family, config in TOOL_DEBT_CONFIG.items():
        grace = config.get("grace_turns", 3)
        rate = config.get("rate", 1)
        cap = config.get("cap", 15)

        # Skip penalty during grace period
        if state.turn_count <= grace:
            continue

        # Skip if serena isn't activated (can't use what isn't available)
        if family == "serena" and not getattr(state, "serena_activated", False):
            continue

        # If tool wasn't used this turn, increment debt
        if family not in tools_used_this_turn:
            debt[family]["turns_without"] += 1
            # Apply penalty (capped)
            current_debt = min(debt[family]["turns_without"], cap)
            if current_debt > 0:
                total_penalty += rate

    return total_penalty


def get_debt_summary(state: "SessionState") -> str:
    """Get a formatted summary of current tool debt for display."""
    debt = get_tool_debt(state)
    parts = []

    for family, config in TOOL_DEBT_CONFIG.items():
        cap = config.get("cap", 15)
        turns = min(debt[family]["turns_without"], cap)
        if turns > 0:
            potential_recovery = int(turns * config.get("recovery", 0.5))
            parts.append(f"{family}: -{turns} (use for +{potential_recovery})")

    if not parts:
        return ""

    return "🔋 Tool debt: " + " | ".join(parts)


# =============================================================================
# TOOL DETECTION HELPERS
# =============================================================================

def detect_tool_family(tool_name: str, bash_command: str = "") -> str | None:
    """
    Detect which tool family a tool belongs to.

    Returns: "pal", "serena", "beads", or None
    """
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

    return None


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

        family = detect_tool_family(tool_name, bash_cmd)
        if family:
            tools_used.add(family)

        # Also check context for tools used earlier in the turn
        turn_tools = context.get("turn_tool_families", set())
        tools_used.update(turn_tools)

        # Calculate penalty
        penalty = tick_tool_debt(state, tools_used)

        if penalty > 0:
            debt = get_tool_debt(state)
            reasons = []
            for family in ["pal", "serena", "beads"]:
                turns = debt[family]["turns_without"]
                if turns > 0:
                    reasons.append(f"{family}:{turns}t")
            reason = f"tool_debt ({', '.join(reasons)})"
            return True, penalty, reason

        return False, 0, ""


# =============================================================================
# INCREASERS
# =============================================================================

@dataclass
class ToolDebtRecoveryIncreaser:
    """
    Recovers 50% of accumulated debt when a tool family is used.

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

        family = detect_tool_family(tool_name, bash_cmd)
        if not family:
            return False, 0

        # Calculate and apply recovery
        recovery = mark_tool_used(state, family)

        if recovery > 0:
            return True, recovery

        return False, 0


# =============================================================================
# EXPORTS
# =============================================================================

# Singleton instances for registration
TOOL_DEBT_REDUCER = ToolDebtReducer()
TOOL_DEBT_RECOVERY_INCREASER = ToolDebtRecoveryIncreaser()

__all__ = [
    "TOOL_DEBT_CONFIG",
    "get_tool_debt",
    "mark_tool_used",
    "tick_tool_debt",
    "get_debt_summary",
    "detect_tool_family",
    "ToolDebtReducer",
    "ToolDebtRecoveryIncreaser",
    "TOOL_DEBT_REDUCER",
    "TOOL_DEBT_RECOVERY_INCREASER",
]
