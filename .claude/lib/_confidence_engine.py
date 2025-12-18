#!/usr/bin/env python3
"""
Confidence Engine - Core application of reducers and increasers.

Handles rate limiting, mean reversion, and applying confidence changes.
"""

from typing import TYPE_CHECKING

from _confidence_reducers import REDUCERS
from _confidence_streaks import (
    update_streak,
    get_streak_multiplier,
    get_diminishing_multiplier,
    get_current_streak,
)
from _confidence_constants import STASIS_FLOOR
from _confidence_increasers import INCREASERS
from _confidence_tool_debt import (
    TOOL_DEBT_REDUCER,
    TOOL_DEBT_RECOVERY_INCREASER,
    get_debt_summary,
)

if TYPE_CHECKING:
    from session_state import SessionState

# Import remaining constants
from _confidence_constants import (
    MAX_CONFIDENCE_DELTA_PER_TURN,
    MAX_CONFIDENCE_RECOVERY_DELTA,
    MEAN_REVERSION_TARGET,
    MEAN_REVERSION_RATE,
)

# =============================================================================
# PROJECT WEIGHTS
# =============================================================================

_PROJECT_WEIGHTS_CACHE: dict = {}
_PROJECT_WEIGHTS_MTIME: float = 0.0


def get_project_weights() -> dict:
    """Load project-specific confidence weights from .claude/confidence.json."""
    import json
    from pathlib import Path

    global _PROJECT_WEIGHTS_CACHE, _PROJECT_WEIGHTS_MTIME

    config_path = Path.cwd() / ".claude" / "confidence.json"
    if not config_path.exists():
        config_path = Path.home() / ".claude" / "confidence.json"
        if not config_path.exists():
            return {"reducer_weights": {}, "increaser_weights": {}}

    try:
        current_mtime = config_path.stat().st_mtime
        if current_mtime == _PROJECT_WEIGHTS_MTIME and _PROJECT_WEIGHTS_CACHE:
            return _PROJECT_WEIGHTS_CACHE

        with open(config_path) as f:
            data = json.load(f)

        _PROJECT_WEIGHTS_CACHE = {
            "reducer_weights": data.get("reducer_weights", {}),
            "increaser_weights": data.get("increaser_weights", {}),
        }
        _PROJECT_WEIGHTS_MTIME = current_mtime
        return _PROJECT_WEIGHTS_CACHE
    except (json.JSONDecodeError, OSError):
        return {"reducer_weights": {}, "increaser_weights": {}}


def get_adjusted_delta(base_delta: int, name: str, is_reducer: bool) -> int:
    """Apply project-specific weight to a reducer/increaser delta."""
    weights = get_project_weights()
    weight_key = "reducer_weights" if is_reducer else "increaser_weights"
    multiplier = weights.get(weight_key, {}).get(name, 1.0)
    return int(base_delta * multiplier)


# =============================================================================
# RATE LIMITING
# =============================================================================


def apply_rate_limit(delta: int, state: "SessionState") -> int:
    """Apply rate limiting to prevent death spirals.

    Caps the maximum confidence change per turn and tracks cumulative
    changes to prevent compound penalties from destroying confidence.

    When below STASIS_FLOOR (80%), allows higher positive gains to enable
    faster legitimate recovery. Penalties always use standard cap.

    Returns the clamped delta.
    """
    # Track cumulative delta this turn
    turn_key = f"_confidence_delta_turn_{state.turn_count}"
    cumulative = state.nudge_history.get(turn_key, 0)

    # Determine cap based on current confidence
    # Allow faster recovery when below stasis floor
    if delta > 0 and state.confidence < STASIS_FLOOR:
        max_positive = MAX_CONFIDENCE_RECOVERY_DELTA
    else:
        max_positive = MAX_CONFIDENCE_DELTA_PER_TURN

    # Calculate remaining budget
    if delta < 0:
        # For penalties, always use standard cap
        remaining = -MAX_CONFIDENCE_DELTA_PER_TURN - cumulative
        clamped = max(delta, remaining)
    else:
        # For boosts, use appropriate cap based on recovery mode
        remaining = max_positive - cumulative
        clamped = min(delta, remaining)

    # Update cumulative tracking
    state.nudge_history[turn_key] = cumulative + clamped

    # Cleanup stale turn keys (keep only last 10 turns to prevent unbounded growth)
    stale_keys = []
    for k in state.nudge_history:
        if k.startswith("_confidence_delta_turn_") and k != turn_key:
            try:
                turn_num = int(k.split("_")[-1])
                if turn_num < state.turn_count - 10:
                    stale_keys.append(k)
            except ValueError:
                stale_keys.append(k)  # Remove malformed keys
    for k in stale_keys:
        del state.nudge_history[k]

    return clamped


def apply_mean_reversion(confidence: int, idle_turns: int = 0) -> int:
    """Gently pull confidence toward baseline when no strong signals.

    Prevents getting stuck at extremes. Only applies after idle periods.
    """
    if idle_turns < 3:  # Need at least 3 idle turns
        return confidence

    # Calculate reversion amount
    distance = MEAN_REVERSION_TARGET - confidence
    reversion = int(distance * MEAN_REVERSION_RATE * idle_turns)

    # Cap at 5 per application
    reversion = max(-5, min(5, reversion))

    return confidence + reversion


# =============================================================================
# REDUCER/INCREASER APPLICATION
# =============================================================================


def apply_reducers(state: "SessionState", context: dict) -> list[tuple[str, int, str]]:
    """
    Apply all applicable reducers and return list of triggered ones.

    Resets streak counter on any reducer firing (v4.6).
    Also applies tool debt penalties (v4.14).
    Tracks repair_debt for PROCESS-class reducers (v4.16).

    Returns:
        List of (reducer_name, delta, description) tuples
    """
    triggered = []

    # Get last trigger turns from state (stored in nudge_history)
    for reducer in REDUCERS:
        key = f"confidence_reducer_{reducer.name}"
        last_trigger = state.nudge_history.get(key, {}).get("last_turn", -999)

        if reducer.should_trigger(context, state, last_trigger):
            # Apply project-specific weights (v4.7)
            adjusted_delta = get_adjusted_delta(
                reducer.delta, reducer.name, is_reducer=True
            )
            triggered.append((reducer.name, adjusted_delta, reducer.description))
            # Record trigger
            if key not in state.nudge_history:
                state.nudge_history[key] = {}
            state.nudge_history[key]["last_turn"] = state.turn_count

            # Reset streak on failure (v4.6)
            update_streak(state, is_success=False)

            # Track repair debt for PROCESS-class reducers (v4.16)
            penalty_class = getattr(reducer, "penalty_class", "PROCESS")
            max_recovery = getattr(reducer, "max_recovery_fraction", 0.5)
            if penalty_class == "PROCESS" and max_recovery > 0:
                if not hasattr(state, "repair_debt") or state.repair_debt is None:
                    state.repair_debt = {}
                state.repair_debt[reducer.name] = {
                    "amount": abs(adjusted_delta),
                    "turn": state.turn_count,
                    "evidence_tier": 0,
                    "recovered": 0,
                    "max_recovery_fraction": max_recovery,
                }

    # Tool debt penalties (v4.14) - special handling for variable delta
    should_trigger, penalty, reason = TOOL_DEBT_REDUCER.should_trigger(
        context, state, -999  # No cooldown for debt
    )
    if should_trigger and penalty > 0:
        triggered.append(("tool_debt", -penalty, reason))
        # Don't reset streak for debt - it's passive accumulation, not active failure

    return triggered


def apply_increasers(
    state: "SessionState", context: dict
) -> list[tuple[str, int, str, bool]]:
    """
    Apply all applicable increasers and return list of triggered ones.

    Also handles Trust Debt decay: test_pass and build_success clear debt.
    Applies streak multiplier for consecutive successes (v4.6).
    Applies repair debt recovery for PROCESS-class penalties (v4.16).

    Returns:
        List of (increaser_name, delta, description, requires_approval) tuples
    """
    triggered = []

    for increaser in INCREASERS:
        key = f"confidence_increaser_{increaser.name}"
        last_trigger = state.nudge_history.get(key, {}).get("last_turn", -999)

        if increaser.should_trigger(context, state, last_trigger):
            # Apply streak multiplier (v4.6)
            streak = get_current_streak(state)
            streak_mult = get_streak_multiplier(streak)

            # Apply diminishing returns for farmable increasers (v4.7)
            diminish_mult = get_diminishing_multiplier(state, increaser.name)

            # Apply project-specific weights (v4.7)
            base_delta = get_adjusted_delta(
                increaser.delta, increaser.name, is_reducer=False
            )

            # Combined multiplier with streak and diminishing returns
            adjusted_delta = int(base_delta * streak_mult * diminish_mult)

            # Skip if diminished to zero
            if adjusted_delta <= 0:
                continue

            triggered.append(
                (
                    increaser.name,
                    adjusted_delta,
                    increaser.description,
                    increaser.requires_approval,
                )
            )
            # Record trigger (only for non-approval-required)
            if not increaser.requires_approval:
                if key not in state.nudge_history:
                    state.nudge_history[key] = {}
                state.nudge_history[key]["last_turn"] = state.turn_count

                # Update streak counter (success)
                update_streak(state, is_success=True)

                # Trust Debt decay: objective signals (test/build) clear debt
                if increaser.name in ("test_pass", "build_success"):
                    current_debt = getattr(state, "reputation_debt", 0)
                    if current_debt > 0:
                        state.reputation_debt = current_debt - 1

                # Repair debt recovery (v4.16) - evidence-based recovery
                repair_recovery = calculate_repair_recovery(state, increaser.name)
                if repair_recovery > 0:
                    triggered.append(
                        (
                            "repair_recovery",
                            repair_recovery,
                            f"Repair debt recovered ({increaser.name})",
                            False,
                        )
                    )

    # Tool debt recovery (v4.14) - special handling for variable delta
    should_recover, recovery = TOOL_DEBT_RECOVERY_INCREASER.should_trigger(
        context, state, -999  # No cooldown
    )
    if should_recover and recovery > 0:
        triggered.append(
            ("tool_debt_recovery", recovery, "Framework tool used (debt recovered)", False)
        )
        # Add to debt summary for visibility
        debt_info = get_debt_summary(state)
        if debt_info:
            context["_tool_debt_info"] = debt_info

    return triggered


# Evidence tier multipliers for repair debt recovery (v4.16)
EVIDENCE_TIER_MULTIPLIERS = {
    0: 0.0,   # claim only - no recovery
    1: 0.05,  # user stops objecting
    2: 0.15,  # lint/build passes
    3: 0.35,  # tests pass
    4: 0.50,  # user confirms + tests
}

# Map increaser names to evidence tiers
INCREASER_EVIDENCE_TIERS = {
    "user_ok": 1,
    "lint_pass": 2,
    "build_success": 2,
    "test_pass": 3,
    "first_attempt_success": 3,
    "trust_regained": 4,  # User explicitly says CONFIDENCE_BOOST_APPROVED
}


def calculate_repair_recovery(state: "SessionState", increaser_name: str) -> int:
    """
    Calculate repair debt recovery based on evidence tier.

    Returns confidence points to recover (already factored against max_recovery_fraction).
    """
    if not hasattr(state, "repair_debt") or not state.repair_debt:
        return 0

    tier = INCREASER_EVIDENCE_TIERS.get(increaser_name, 0)
    if tier == 0:
        return 0

    multiplier = EVIDENCE_TIER_MULTIPLIERS.get(tier, 0)
    if multiplier == 0:
        return 0

    total_recovery = 0

    for reducer_name, debt_info in list(state.repair_debt.items()):
        amount = debt_info.get("amount", 0)
        max_frac = debt_info.get("max_recovery_fraction", 0.5)
        recovered = debt_info.get("recovered", 0)

        # Calculate maximum recoverable for this reducer
        max_recoverable = int(amount * max_frac)
        remaining = max_recoverable - recovered

        if remaining <= 0:
            continue

        # Apply tier multiplier to remaining recoverable
        recovery = int(remaining * multiplier)
        if recovery > 0:
            # Update debt tracking
            state.repair_debt[reducer_name]["recovered"] = recovered + recovery
            state.repair_debt[reducer_name]["evidence_tier"] = max(
                debt_info.get("evidence_tier", 0), tier
            )
            total_recovery += recovery

    return total_recovery


# =============================================================================
# FALSE POSITIVE DISPUTE SYSTEM
