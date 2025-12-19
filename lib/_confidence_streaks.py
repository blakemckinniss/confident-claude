#!/usr/bin/env python3
"""
Confidence Streaks - Momentum system and trajectory prediction.

Tracks consecutive successes for multiplied rewards, applies diminishing
returns to prevent farming, and predicts confidence trajectory.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from session_state import SessionState

from _confidence_constants import (
    STASIS_FLOOR,
    THRESHOLD_PRODUCTION_ACCESS,
    THRESHOLD_REQUIRE_RESEARCH,
)

# Streak multipliers for consecutive successes
STREAK_MULTIPLIERS = {2: 1.25, 3: 1.5, 5: 2.0}
STREAK_DECAY_ON_FAILURE = 0  # Reset to 0 on any reducer

# Diminishing returns for farmable increasers
FARMABLE_INCREASERS = {"file_read", "productive_bash", "search_tool"}
DIMINISHING_MULTIPLIERS = {1: 1.0, 2: 0.75, 3: 0.5, 4: 0.25}
DIMINISHING_CAP = 5  # After this many, no reward

# =============================================================================


def calculate_idle_reversion(
    confidence: int, last_activity_time: float, current_time: float
) -> tuple[int, str]:
    """Calculate mean reversion based on idle time.

    Returns:
        Tuple of (new_confidence, reason_message)
    """
    if last_activity_time <= 0:
        return confidence, ""

    idle_seconds = current_time - last_activity_time
    idle_minutes = idle_seconds / 60

    # Only apply after 5 minutes of idle time
    if idle_minutes < 5:
        return confidence, ""

    # Calculate idle periods (each 5-minute block counts as 1 idle turn)
    idle_turns = int(idle_minutes / 5)

    # Apply mean reversion (lazy import to avoid circular dependency)
    from _confidence_engine import apply_mean_reversion

    new_confidence = apply_mean_reversion(confidence, idle_turns)

    if new_confidence != confidence:
        delta = new_confidence - confidence
        direction = "+" if delta > 0 else ""
        reason = (
            f"Mean reversion after {int(idle_minutes)}min idle ({direction}{delta})"
        )
        return new_confidence, reason

    return confidence, ""


# =============================================================================
# STREAK/MOMENTUM TRACKING (v4.6)
# =============================================================================


def get_streak_multiplier(streak_count: int) -> float:
    """Get the multiplier for the current streak count.

    Returns highest applicable multiplier based on streak thresholds.
    """
    multiplier = 1.0
    for threshold, mult in sorted(STREAK_MULTIPLIERS.items()):
        if streak_count >= threshold:
            multiplier = mult
    return multiplier


def get_diminishing_multiplier(state: "SessionState", increaser_name: str) -> float:
    """Get diminishing returns multiplier for farmable increasers.

    Tracks how many times this increaser fired this turn and returns
    decreasing multiplier. Resets each turn.

    Returns:
        Multiplier (1.0 for first, 0.5 for second, 0.25 for third, 0 after)
    """
    if increaser_name not in FARMABLE_INCREASERS:
        return 1.0  # Non-farmable increasers always get full value

    # Track per-turn triggers
    turn_key = f"_diminish_{increaser_name}_turn_{state.turn_count}"
    trigger_count = state.nudge_history.get(turn_key, 0) + 1

    # Update count
    state.nudge_history[turn_key] = trigger_count

    # Cleanup old turn keys (keep only current turn)
    stale_keys = [
        k
        for k in state.nudge_history
        if k.startswith(f"_diminish_{increaser_name}_turn_") and k != turn_key
    ]
    for k in stale_keys:
        del state.nudge_history[k]

    # Return multiplier based on trigger count
    if trigger_count > DIMINISHING_CAP:
        return 0.0
    return DIMINISHING_MULTIPLIERS.get(trigger_count, 0.0)


def update_streak(state: "SessionState", is_success: bool) -> int:
    """Update streak counter and return new streak count.

    Args:
        state: Session state to update
        is_success: True if increaser fired, False if reducer fired

    Returns:
        New streak count
    """
    key = "_confidence_streak"
    current = state.nudge_history.get(key, 0)

    if is_success:
        new_streak = current + 1
    else:
        new_streak = STREAK_DECAY_ON_FAILURE

    state.nudge_history[key] = new_streak
    return new_streak


def get_current_streak(state: "SessionState") -> int:
    """Get current streak count."""
    return state.nudge_history.get("_confidence_streak", 0)


# =============================================================================
# TRAJECTORY PREDICTION (v4.6)
# =============================================================================


def predict_trajectory(
    state: "SessionState",
    planned_edits: int = 0,
    planned_bash: int = 0,
    turns_ahead: int = 3,
) -> dict:
    """Predict confidence trajectory based on planned actions.

    Args:
        state: Current session state
        planned_edits: Number of file edits planned
        planned_bash: Number of bash commands planned
        turns_ahead: How many turns to project

    Returns:
        Dict with projected confidence, warnings, and recovery suggestions
    """
    from _fatigue import get_fatigue_multiplier, get_fatigue_tier

    current = state.confidence
    projected = current

    # Apply expected decay with fatigue multiplier (v4.9)
    # Entity gets tired - decay accelerates with session length
    fatigue_mult = get_fatigue_multiplier(state.turn_count)
    projected -= int(turns_ahead * fatigue_mult)  # Fatigued decay

    # Apply risk penalties for planned actions (also fatigued)
    projected -= int(planned_edits * fatigue_mult)  # -1 per edit (fatigued)
    projected -= int(planned_bash * fatigue_mult)  # -1 per bash (fatigued)

    # Get fatigue tier for warning
    fatigue_tier, fatigue_emoji, _ = get_fatigue_tier(state.turn_count)

    # Determine if we'll hit any gates
    warnings = []
    if projected < STASIS_FLOOR and current >= STASIS_FLOOR:
        warnings.append(f"Will drop below stasis floor ({STASIS_FLOOR}%)")
    if (
        projected < THRESHOLD_PRODUCTION_ACCESS
        and current >= THRESHOLD_PRODUCTION_ACCESS
    ):
        warnings.append(
            f"Will lose production write access ({THRESHOLD_PRODUCTION_ACCESS}%)"
        )
    if projected < THRESHOLD_REQUIRE_RESEARCH and current >= THRESHOLD_REQUIRE_RESEARCH:
        warnings.append(f"Will require research ({THRESHOLD_REQUIRE_RESEARCH}%)")

    # Suggest recovery actions if trajectory is concerning
    recovery = []
    if projected < STASIS_FLOOR:
        deficit = STASIS_FLOOR - projected
        recovery.append(f"Run tests (+5 each) - need ~{(deficit // 5) + 1} passes")
        recovery.append("git status/diff (+10)")
        recovery.append("Read relevant files (+1 each)")
        if fatigue_mult >= 1.5:
            recovery.append(
                f"Consider `/compact` or fresh session ({fatigue_emoji} {fatigue_tier})"
            )

    return {
        "current": current,
        "projected": projected,
        "turns_ahead": turns_ahead,
        "delta": projected - current,
        "warnings": warnings,
        "recovery_suggestions": recovery,
        "will_gate": projected < STASIS_FLOOR,
        "fatigue_multiplier": fatigue_mult,
        "fatigue_tier": fatigue_tier,
    }


def format_trajectory_warning(trajectory: dict) -> str:
    """Format trajectory prediction as a warning string."""
    if not trajectory["warnings"]:
        return ""

    lines = [
        f"⚠️ Trajectory: {trajectory['current']}% → {trajectory['projected']}% "
        f"in {trajectory['turns_ahead']} turns"
    ]
    for warning in trajectory["warnings"]:
        lines.append(f"  • {warning}")
    if trajectory["recovery_suggestions"]:
        lines.append("  Recovery options:")
        for suggestion in trajectory["recovery_suggestions"][:3]:
            lines.append(f"    - {suggestion}")

    return "\n".join(lines)


# =============================================================================
# CONFIDENCE JOURNAL (v4.6)


# =============================================================================
# CATEGORY-LEVEL PATTERN DETECTION (v4.21)
# =============================================================================

# Reducer category groupings for meta-pattern detection
REDUCER_CATEGORIES = {
    "code_quality": [
        "placeholder_impl",
        "silent_failure",
        "incomplete_refactor",
        "deep_nesting",
        "long_function",
        "mutable_default_arg",
        "import_star",
        "bare_raise",
        "commented_code",
        "magic_numbers",
        "empty_test",
        "orphaned_imports",
    ],
    "process": [
        "tool_failure",
        "sunk_cost",
        "cascade_block",
        "edit_oscillation",
        "stuck_loop",
        "no_research_debug",
    ],
    "behavioral": [
        "sycophancy",
        "apologetic",
        "deferral",
        "hallmark_phrase",
        "overconfident_completion",
        "hedging_language",
        "phantom_progress",
    ],
    "verification": [
        "unbacked_verification_claim",
        "fixed_without_chain",
        "git_spam",
        "unverified_edits",
    ],
    "scope": [
        "scope_creep",
        "goal_drift",
        "large_diff",
    ],
}

# Invert for lookup
_REDUCER_TO_CATEGORY = {}
for cat, reducers in REDUCER_CATEGORIES.items():
    for r in reducers:
        _REDUCER_TO_CATEGORY[r] = cat


def track_reducer_category(state: "SessionState", reducer_name: str) -> None:
    """Track reducer firing for category-level pattern detection."""
    category = _REDUCER_TO_CATEGORY.get(reducer_name, "other")

    # Append to history (keep last 20)
    if not hasattr(state, "reducer_category_history"):
        state.reducer_category_history = []

    state.reducer_category_history.append((category, reducer_name, state.turn_count))
    state.reducer_category_history = state.reducer_category_history[-20:]


def detect_category_pattern(
    state: "SessionState", window_turns: int = 10
) -> dict | None:
    """Detect if multiple reducers in same category fired recently.

    Returns dict with category and count if pattern detected, None otherwise.
    """
    if not hasattr(state, "reducer_category_history"):
        return None

    # Filter to recent turns
    cutoff = state.turn_count - window_turns
    recent = [
        (cat, name, turn)
        for cat, name, turn in state.reducer_category_history
        if turn >= cutoff
    ]

    if len(recent) < 3:
        return None

    # Count by category
    from collections import Counter

    cat_counts = Counter(cat for cat, _, _ in recent)

    # Check for category with 3+ distinct reducers
    for cat, count in cat_counts.most_common(1):
        if count >= 3 and cat != "other":
            # Get the distinct reducer names
            reducers_in_cat = [name for c, name, _ in recent if c == cat]
            return {
                "category": cat,
                "count": count,
                "reducers": list(set(reducers_in_cat)),
                "message": f"⚠️ {count} {cat} issues in {window_turns} turns: {', '.join(set(reducers_in_cat)[:3])}",
            }

    return None


# =============================================================================
# VOLATILITY DAMPENING (v4.21)
# =============================================================================


def track_confidence_value(state: "SessionState", confidence: int) -> None:
    """Track confidence value for volatility detection."""
    if not hasattr(state, "confidence_history"):
        state.confidence_history = []

    state.confidence_history.append(confidence)
    # Keep last 10 values
    state.confidence_history = state.confidence_history[-10:]


def detect_volatility(state: "SessionState", threshold: int = 15) -> dict | None:
    """Detect if confidence is oscillating wildly.

    Returns warning dict if volatility detected (Δ > threshold in 3+ consecutive turns).
    """
    if not hasattr(state, "confidence_history") or len(state.confidence_history) < 4:
        return None

    history = state.confidence_history

    # Calculate deltas between consecutive values
    deltas = [abs(history[i] - history[i - 1]) for i in range(1, len(history))]

    # Check for 3+ consecutive large swings
    consecutive_large = 0
    for delta in deltas[-5:]:  # Check last 5 deltas
        if delta >= threshold:
            consecutive_large += 1
        else:
            consecutive_large = 0

    if consecutive_large >= 3:
        return {
            "volatility": True,
            "recent_deltas": deltas[-5:],
            "message": f"⚠️ Confidence volatility: swings of {deltas[-3:]} detected. Consider stabilizing.",
        }

    return None


# =============================================================================
# RECOVERY INTENT BOOST (v4.21)
# =============================================================================


def track_recovery_intent(
    state: "SessionState", reducer_name: str, amount: int
) -> None:
    """Track big penalty for recovery intent boost.

    When a penalty >= 10 fires, the first recovery action gets +50% boost.
    """
    if amount < 10:
        return  # Only track big penalties

    if not hasattr(state, "recovery_intent_debt"):
        state.recovery_intent_debt = {}

    state.recovery_intent_debt[reducer_name] = {
        "amount": amount,
        "turn": state.turn_count,
        "recovered": False,
    }


def apply_recovery_intent_boost(state: "SessionState", base_delta: int) -> int:
    """Apply recovery intent boost if applicable.

    Returns boosted delta if this is the first recovery action after a big penalty.
    """
    if not hasattr(state, "recovery_intent_debt") or not state.recovery_intent_debt:
        return base_delta

    # Find any unrecover ed debt from recent turns (within 5 turns)
    cutoff = state.turn_count - 5
    for reducer_name, debt in list(state.recovery_intent_debt.items()):
        if debt["turn"] >= cutoff and not debt["recovered"]:
            # Apply 50% boost
            boosted = int(base_delta * 1.5)
            # Mark as recovered
            state.recovery_intent_debt[reducer_name]["recovered"] = True
            return boosted

    return base_delta


# =============================================================================
# CONFIDENCE JOURNAL (v4.6)


def log_confidence_change(
    state: "SessionState",
    old_confidence: int,
    new_confidence: int,
    reason: str,
    journal_path: str = "",
) -> None:
    """Log significant confidence changes to journal file.

    Only logs changes >= 3 points to avoid noise.
    """
    import time
    from pathlib import Path

    delta = new_confidence - old_confidence
    if abs(delta) < 3:
        return  # Skip tiny changes

    if not journal_path:
        journal_path = Path.home() / ".claude" / "tmp" / "confidence_journal.log"
    else:
        journal_path = Path(journal_path)

    # Ensure directory exists
    journal_path.parent.mkdir(parents=True, exist_ok=True)

    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    direction = "+" if delta > 0 else ""
    entry = f"[{timestamp}] {old_confidence}→{new_confidence} ({direction}{delta}): {reason}\n"

    # Append to journal (keep last 1000 lines max)
    try:
        existing = []
        if journal_path.exists():
            existing = journal_path.read_text().splitlines()[-999:]
        existing.append(entry.strip())
        journal_path.write_text("\n".join(existing) + "\n")
    except OSError:
        return  # Journal write failed, non-critical
