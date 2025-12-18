#!/usr/bin/env python3
"""
Session Thresholds - Adaptive thresholds, block tracking, cascade failure detection.
"""

import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from _session_state_class import SessionState

# Default thresholds
DEFAULT_THRESHOLDS = {
    "quality_long_method": 50,
    "quality_high_complexity": 10,
    "quality_deep_nesting": 4,
    "quality_debug_statements": 3,
    "quality_tech_debt_markers": 5,
    "quality_magic_numbers": 5,
    "perf_blocking_io": 1,
    "perf_repeated_calculation": 3,
    "perf_repeated_calculation_ops": 2,
    "batch_sequential_reads": 3,
    "iteration_same_tool": 4,
    "velocity_oscillation": 3,
}

THRESHOLD_COOLDOWNS = {
    "quality_long_method": 3600,
    "quality_high_complexity": 3600,
    "quality_deep_nesting": 3600,
    "quality_debug_statements": 1800,
    "quality_tech_debt_markers": 3600,
    "quality_magic_numbers": 1800,
    "perf_blocking_io": 1800,
    "perf_repeated_calculation": 1800,
    "batch_sequential_reads": 600,
    "iteration_same_tool": 600,
    "velocity_oscillation": 600,
    "default": 1800,
}

CASCADE_THRESHOLD = 3
CASCADE_WINDOW = 5


def get_adaptive_threshold(state: "SessionState", pattern_name: str) -> float:
    """Get adaptive threshold for a pattern."""
    learning = state.nudge_history.get(f"threshold_{pattern_name}", {})
    default = DEFAULT_THRESHOLDS.get(pattern_name, 10)
    current_threshold = learning.get("threshold", default)

    cooldown_until = learning.get("cooldown_until", 0)
    if cooldown_until and time.time() < cooldown_until:
        return float("inf")

    last_trigger = learning.get("last_trigger", 0)
    if last_trigger:
        time_since = time.time() - last_trigger

        if time_since < 300:
            current_threshold = min(current_threshold * 1.5, default * 3.0)
            cooldown_duration = THRESHOLD_COOLDOWNS.get(
                pattern_name, THRESHOLD_COOLDOWNS["default"]
            )
            learning["cooldown_until"] = time.time() + cooldown_duration
            learning["threshold"] = current_threshold
            state.nudge_history[f"threshold_{pattern_name}"] = learning

        elif time_since > 86400:
            current_threshold = max(current_threshold * 0.9, default * 0.5)
            learning["threshold"] = current_threshold
            state.nudge_history[f"threshold_{pattern_name}"] = learning

    return current_threshold


def record_threshold_trigger(state: "SessionState", pattern_name: str, value: int = 1):
    """Record that a pattern was triggered."""
    key = f"threshold_{pattern_name}"
    if key not in state.nudge_history:
        state.nudge_history[key] = {
            "threshold": DEFAULT_THRESHOLDS.get(pattern_name, 10),
            "trigger_count": 0,
            "last_trigger": 0,
            "cooldown_until": 0,
        }

    state.nudge_history[key]["trigger_count"] = (
        state.nudge_history[key].get("trigger_count", 0) + 1
    )
    state.nudge_history[key]["last_trigger"] = time.time()
    state.nudge_history[key]["last_value"] = value


def track_block(state: "SessionState", hook_name: str):
    """Track a block from a hook for cascade detection."""
    if hook_name not in state.consecutive_blocks:
        state.consecutive_blocks[hook_name] = {
            "count": 0,
            "first_turn": state.turn_count,
            "last_turn": 0,
        }

    entry = state.consecutive_blocks[hook_name]

    if state.turn_count - entry.get("last_turn", 0) > CASCADE_WINDOW:
        entry["count"] = 0
        entry["first_turn"] = state.turn_count

    entry["count"] = entry.get("count", 0) + 1
    entry["last_turn"] = state.turn_count
    state.last_block_turn = state.turn_count


def clear_blocks(state: "SessionState", hook_name: str = None):
    """Clear block tracking."""
    if hook_name:
        if hook_name in state.consecutive_blocks:
            del state.consecutive_blocks[hook_name]
    else:
        state.consecutive_blocks = {}


def check_cascade_failure(state: "SessionState", hook_name: str) -> tuple[bool, str]:
    """Check if we're in a cascade failure state for a hook."""
    entry = state.consecutive_blocks.get(hook_name, {})
    count = entry.get("count", 0)

    if count < CASCADE_THRESHOLD:
        return False, ""

    turns_since_first = state.turn_count - entry.get("first_turn", 0)
    if turns_since_first > CASCADE_WINDOW * 2:
        return False, ""

    return True, (
        f"⚠️ **CASCADE FAILURE**: `{hook_name}` blocked {count}x in {turns_since_first} turns.\n"
        f"💡 Try: `/think` to decompose, `/oracle` for advice, or say 'BYPASS {hook_name}' to override once."
    )


def _apply_mean_reversion_on_load(state: "SessionState") -> "SessionState":
    """Apply mean reversion based on idle time when loading state."""
    if state.last_activity_time <= 0:
        return state

    from confidence import calculate_idle_reversion, apply_rate_limit
    from _session_confidence import set_confidence

    current_time = time.time()
    new_confidence, reason = calculate_idle_reversion(
        state.confidence, state.last_activity_time, current_time
    )

    if new_confidence != state.confidence:
        raw_delta = new_confidence - state.confidence
        clamped_delta = apply_rate_limit(raw_delta, state)
        final_confidence = state.confidence + clamped_delta

        state.nudge_history["_mean_reversion_applied"] = {
            "old": state.confidence,
            "new": final_confidence,
            "reason": reason,
            "raw_delta": raw_delta,
            "clamped_delta": clamped_delta,
        }
        set_confidence(state, final_confidence, f"mean_reversion: {reason}")

    return state
