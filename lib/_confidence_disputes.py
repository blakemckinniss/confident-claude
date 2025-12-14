#!/usr/bin/env python3
"""
Confidence Disputes - False positive handling and adaptive cooldowns.

Allows disputing incorrect reducer triggers and adjusts cooldowns
based on false positive history.
"""

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from session_state import SessionState

from _confidence_reducers import REDUCERS
from epistemology import TIER_PRIVILEGES
from _confidence_tiers import get_tier_info

# =============================================================================

# Patterns that indicate user is disputing a confidence reduction
# Note: patterns are matched against lowercased prompt
DISPUTE_PATTERNS = [
    r"\bfalse\s+positive\b",
    r"\bfp\s*:\s*(\w+)\b",  # fp: reducer_name (lowercase)
    r"\bdispute\s+(\w+)\b",
    r"\bthat\s+(?:was|is)\s+wrong\b",
    r"\bshouldn'?t\s+have\s+(?:reduced|dropped)\b",
    r"\bwrongly\s+(?:reduced|penalized)\b",
    r"\blegitimate\s+(?:edit|change|work)\b",
    r"\bnot\s+(?:oscillating|spinning|stuck)\b",
]


def get_adaptive_cooldown(state: "SessionState", reducer_name: str) -> int:
    """Get adaptive cooldown for a reducer based on false positive history.

    High false positive rates increase cooldowns to reduce future triggers.
    """
    base_cooldown = next(
        (r.cooldown_turns for r in REDUCERS if r.name == reducer_name), 3
    )

    # Get FP count from state
    fp_key = f"reducer_fp_{reducer_name}"
    fp_count = state.nudge_history.get(fp_key, {}).get("count", 0)

    # Scale cooldown: each FP adds 50% more cooldown, max 3x
    if fp_count == 0:
        return base_cooldown

    multiplier = min(3.0, 1.0 + (fp_count * 0.5))
    return int(base_cooldown * multiplier)


def record_false_positive(state: "SessionState", reducer_name: str, reason: str = ""):
    """Record a false positive for adaptive learning.

    This increases future cooldowns for this reducer.
    """
    fp_key = f"reducer_fp_{reducer_name}"
    if fp_key not in state.nudge_history:
        state.nudge_history[fp_key] = {"count": 0, "reasons": []}

    state.nudge_history[fp_key]["count"] = (
        state.nudge_history[fp_key].get("count", 0) + 1
    )

    # Keep last 5 reasons for debugging
    if reason:
        reasons = state.nudge_history[fp_key].get("reasons", [])
        reasons.append(reason[:100])
        state.nudge_history[fp_key]["reasons"] = reasons[-5:]

    state.nudge_history[fp_key]["last_turn"] = state.turn_count


def dispute_reducer(
    state: "SessionState", reducer_name: str, reason: str = ""
) -> tuple[int, str]:
    """User disputes a confidence reduction as false positive.

    Returns:
        Tuple of (confidence_restored, message)
    """
    # Find the reducer
    reducer = next((r for r in REDUCERS if r.name == reducer_name), None)
    if not reducer:
        # Try fuzzy match
        for r in REDUCERS:
            if reducer_name.lower() in r.name.lower():
                reducer = r
                break

    if not reducer:
        return (
            0,
            f"Unknown reducer: {reducer_name}. Valid: {[r.name for r in REDUCERS]}",
        )

    # Record the false positive
    record_false_positive(state, reducer.name, reason)

    # Restore confidence
    restore_amount = abs(reducer.delta)
    fp_count = state.nudge_history.get(f"reducer_fp_{reducer.name}", {}).get("count", 1)
    new_cooldown = get_adaptive_cooldown(state, reducer.name)

    return restore_amount, (
        f"✅ **False Positive Recorded**: {reducer.name}\n"
        f"  • Confidence restored: +{restore_amount}\n"
        f"  • Total FPs for this reducer: {fp_count}\n"
        f"  • New adaptive cooldown: {new_cooldown} turns\n"
    )


def detect_dispute_in_prompt(prompt: str) -> tuple[bool, str, str]:
    """Detect if user is disputing a confidence reduction.

    Returns:
        Tuple of (is_dispute, reducer_name, reason)
    """
    prompt_lower = prompt.lower()

    for pattern in DISPUTE_PATTERNS:
        match = re.search(pattern, prompt_lower)
        if match:
            # Try to extract reducer name from match groups
            reducer_name = ""
            if match.groups():
                reducer_name = match.group(1)

            # If no reducer name in pattern, try to find it in prompt
            if not reducer_name:
                for reducer in REDUCERS:
                    if reducer.name in prompt_lower:
                        reducer_name = reducer.name
                        break

            # Extract reason (rest of prompt after pattern)
            reason = prompt[match.end() :].strip()[:100]

            return True, reducer_name, reason

    return False, "", ""


def get_recent_reductions(state: "SessionState", turns: int = 3) -> list[str]:
    """Get reducers that fired recently (for dispute context)."""
    recent = []
    current_turn = state.turn_count

    for reducer in REDUCERS:
        key = f"confidence_reducer_{reducer.name}"
        last_turn = state.nudge_history.get(key, {}).get("last_turn", -999)
        if current_turn - last_turn <= turns:
            recent.append(reducer.name)

    return recent


def format_dispute_instructions(reducer_names: list[str]) -> str:
    """Format instructions for disputing a reduction."""
    if not reducer_names:
        return ""

    reducers_str = ", ".join(reducer_names)
    return (
        f"\n💡 **False positive?** Options:\n"
        f"   • Claude: Run `~/.claude/ops/fp.py <reducer> [reason]`\n"
        f"   • User: Say `FP: <reducer>` or `dispute <reducer>`\n"
        f"   Recent reducers: {reducers_str}"
    )


def generate_approval_prompt(
    current_confidence: int, requested_delta: int, reasons: list[str]
) -> str:
    """Generate approval prompt for large confidence boosts."""
    new_confidence = min(100, current_confidence + requested_delta)
    old_tier, old_emoji, _ = get_tier_info(current_confidence)
    new_tier, new_emoji, _ = get_tier_info(new_confidence)

    # List what will be unlocked
    old_privs = TIER_PRIVILEGES.get(old_tier, {})
    new_privs = TIER_PRIVILEGES.get(new_tier, {})
    unlocks = []
    for priv, allowed in new_privs.items():
        if allowed and not old_privs.get(priv, False):
            unlocks.append(f"  \u2705 {priv.replace('_', ' ').title()}")

    unlock_str = "\n".join(unlocks) if unlocks else "  (no new permissions)"

    return (
        f"\U0001f50d **Confidence Boost Request**\n\n"
        f"Current: {old_emoji}{current_confidence}% {old_tier}\n"
        f"Proposed: {new_emoji}{new_confidence}% {new_tier} (+{requested_delta})\n\n"
        f"This will unlock:\n{unlock_str}\n\n"
        f"Reply: **CONFIDENCE_BOOST_APPROVED** to confirm"
    )


# =============================================================================
# ROCK BOTTOM REALIGNMENT
