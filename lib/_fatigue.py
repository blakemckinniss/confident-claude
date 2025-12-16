"""
Fatigue system for Entity Model v4.9.

The entity "gets tired" as sessions progress - decay accelerates with turn count.
This creates natural pressure toward session boundaries and encourages fresh starts.

Philosophy:
- Short sessions (< 30 turns): Full energy, normal decay
- Medium sessions (30-60 turns): Slight fatigue, 25% faster decay
- Long sessions (60-100 turns): Working hard, 50% faster decay
- Extended sessions (100-150 turns): Tired, 100% faster decay
- Marathon sessions (150+ turns): Exhausted, 150% faster decay

The multiplier affects base_decay in check_confidence_decay, making it harder
to maintain high confidence in long sessions without active recovery actions.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from session_state import SessionState


# Fatigue thresholds and multipliers
FATIGUE_TIERS = [
    (30, 1.0, "fresh", "💚"),  # < 30 turns: full energy
    (60, 1.25, "warming", "🟢"),  # 30-60 turns: slight fatigue
    (100, 1.5, "working", "🟡"),  # 60-100 turns: working hard
    (150, 2.0, "tired", "🟠"),  # 100-150 turns: getting tired
    (999, 2.5, "exhausted", "🔴"),  # 150+ turns: exhausted
]


def get_fatigue_multiplier(turn_count: int) -> float:
    """
    Calculate decay multiplier based on session length.

    Args:
        turn_count: Current turn number in session

    Returns:
        Multiplier for base decay (1.0 = normal, 2.5 = max fatigue)
    """
    for threshold, multiplier, _, _ in FATIGUE_TIERS:
        if turn_count < threshold:
            return multiplier
    return FATIGUE_TIERS[-1][1]  # Max fatigue


def get_fatigue_tier(turn_count: int) -> tuple[str, str, float]:
    """
    Get fatigue tier info for display.

    Args:
        turn_count: Current turn number in session

    Returns:
        Tuple of (tier_name, emoji, multiplier)
    """
    for threshold, multiplier, name, emoji in FATIGUE_TIERS:
        if turn_count < threshold:
            return name, emoji, multiplier
    last = FATIGUE_TIERS[-1]
    return last[2], last[3], last[1]


def get_turns_until_next_tier(turn_count: int) -> int | None:
    """
    Get turns remaining until next fatigue tier.

    Args:
        turn_count: Current turn number in session

    Returns:
        Turns until next tier, or None if at max tier
    """
    for threshold, _, _, _ in FATIGUE_TIERS:
        if turn_count < threshold:
            return threshold - turn_count
    return None  # Already at max tier


def format_fatigue_status(turn_count: int) -> str:
    """
    Format fatigue status for display in health check or statusline.

    Args:
        turn_count: Current turn number in session

    Returns:
        Formatted string like "🟡 working (1.5x decay) - 40 turns to tired"
    """
    name, emoji, multiplier = get_fatigue_tier(turn_count)
    turns_until = get_turns_until_next_tier(turn_count)

    base = f"{emoji} {name} ({multiplier:.1f}x decay)"
    if turns_until is not None:
        next_tier_idx = next(
            (i for i, (t, _, _, _) in enumerate(FATIGUE_TIERS) if turn_count < t),
            len(FATIGUE_TIERS) - 1,
        )
        if next_tier_idx < len(FATIGUE_TIERS) - 1:
            next_name = FATIGUE_TIERS[next_tier_idx + 1][2]
            base += f" - {turns_until} turns to {next_name}"

    return base


def predict_fatigue_trajectory(current_turn: int, planned_turns: int) -> dict:
    """
    Predict fatigue trajectory for upcoming turns.

    Args:
        current_turn: Current turn number
        planned_turns: How many turns ahead to predict

    Returns:
        Dict with current and projected fatigue info
    """
    current_name, current_emoji, current_mult = get_fatigue_tier(current_turn)
    future_turn = current_turn + planned_turns
    future_name, future_emoji, future_mult = get_fatigue_tier(future_turn)

    result = {
        "current_turn": current_turn,
        "current_tier": current_name,
        "current_multiplier": current_mult,
        "projected_turn": future_turn,
        "projected_tier": future_name,
        "projected_multiplier": future_mult,
        "tier_change": current_name != future_name,
    }

    if current_name != future_name:
        result["warning"] = (
            f"⚠️ Fatigue: {current_emoji} {current_name} → {future_emoji} {future_name} "
            f"({current_mult:.1f}x → {future_mult:.1f}x decay)"
        )

    return result


def should_suggest_break(state: "SessionState") -> tuple[bool, str | None]:
    """
    Determine if a break/fresh session should be suggested.

    Args:
        state: Current session state

    Returns:
        Tuple of (should_suggest, reason)
    """
    turn_count = state.turn_count
    confidence = state.confidence

    # Exhausted + low confidence = definitely suggest break
    if turn_count >= 150 and confidence < 70:
        return True, (
            "🔴 SESSION FATIGUE: 150+ turns with declining confidence. "
            "Consider `/compact` or starting fresh session for optimal performance."
        )

    # Tired + struggling = suggest break
    if turn_count >= 100 and confidence < 60:
        return True, (
            "🟠 EXTENDED SESSION: 100+ turns with low confidence. "
            "A fresh session may help reset fatigue."
        )

    # Working hard for a long time
    if turn_count >= 80 and confidence < 75:
        return True, (
            "🟡 LONG SESSION: Consider consolidating progress with `/compact` "
            "or summarizing before continuing."
        )

    return False, None
