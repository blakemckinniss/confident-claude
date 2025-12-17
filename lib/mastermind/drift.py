"""Drift detection and escalation triggers for mastermind.

Monitors:
- Files modified vs touch_set
- Test failures
- Approach changes

Triggers escalation when thresholds exceeded.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .config import get_config
from .state import MastermindState, Blueprint
from .telemetry import log_threshold_check


@dataclass
class DriftSignal:
    """Signal indicating potential drift from blueprint."""

    trigger: str  # file_count, test_failures, approach_change
    severity: str  # low, medium, high
    evidence: dict[str, Any]
    should_escalate: bool


def check_file_drift(
    state: MastermindState,
    blueprint: Blueprint | None,
) -> DriftSignal | None:
    """Check if file modifications exceed blueprint touch_set."""
    config = get_config()

    if not config.drift.enabled:
        return None

    if blueprint is None:
        return None

    touch_set = set(blueprint.touch_set)
    modified = set(state.files_modified)

    # Files outside touch_set
    outside = modified - touch_set
    threshold = config.drift.file_count_trigger
    triggered = len(outside) >= threshold

    # Log threshold check for effectiveness analysis
    log_threshold_check(
        session_id=state.session_id,
        turn=state.turn_count,
        threshold_type="file_count",
        current_value=len(outside),
        threshold_value=threshold,
        triggered=triggered,
        epoch_id=state.epoch_id,
    )

    if triggered:
        return DriftSignal(
            trigger="file_count",
            severity="high" if len(outside) >= threshold * 2 else "medium",
            evidence={
                "outside_touch_set": list(outside),
                "total_modified": len(modified),
                "threshold": threshold,
            },
            should_escalate=True,
        )

    return None


def check_test_drift(state: MastermindState) -> DriftSignal | None:
    """Check if test failures exceed threshold."""
    config = get_config()

    if not config.drift.enabled:
        return None

    threshold = config.drift.test_failure_trigger
    triggered = state.test_failures >= threshold

    # Log threshold check for effectiveness analysis
    log_threshold_check(
        session_id=state.session_id,
        turn=state.turn_count,
        threshold_type="test_failures",
        current_value=state.test_failures,
        threshold_value=threshold,
        triggered=triggered,
        epoch_id=state.epoch_id,
    )

    if triggered:
        return DriftSignal(
            trigger="test_failures",
            severity="high" if state.test_failures >= threshold * 2 else "medium",
            evidence={
                "failure_count": state.test_failures,
                "threshold": threshold,
            },
            should_escalate=True,
        )

    return None


def check_approach_drift(
    current_approach: str,
    original_approach: str,
) -> DriftSignal | None:
    """Check if approach has fundamentally changed.

    This is a heuristic check - looks for significant keyword differences.
    """
    config = get_config()

    if not config.drift.enabled:
        return None

    if not config.drift.approach_change_detection:
        return None

    # Simple heuristic: check keyword overlap
    original_words = set(original_approach.lower().split())
    current_words = set(current_approach.lower().split())

    if not original_words:
        return None

    overlap = len(original_words & current_words) / len(original_words)

    if overlap < 0.3:  # Less than 30% overlap suggests significant change
        return DriftSignal(
            trigger="approach_change",
            severity="medium",
            evidence={
                "original": original_approach[:100],
                "current": current_approach[:100],
                "overlap_ratio": overlap,
            },
            should_escalate=True,
        )

    return None


def evaluate_drift(
    state: MastermindState,
    blueprint: Blueprint | None = None,
    current_approach: str | None = None,
    original_approach: str | None = None,
) -> list[DriftSignal]:
    """Evaluate all drift signals.

    Returns list of active drift signals that may require escalation.
    """
    signals: list[DriftSignal] = []

    # Check file drift
    file_signal = check_file_drift(state, blueprint or state.blueprint)
    if file_signal:
        signals.append(file_signal)

    # Check test drift
    test_signal = check_test_drift(state)
    if test_signal:
        signals.append(test_signal)

    # Check approach drift
    if current_approach and original_approach:
        approach_signal = check_approach_drift(current_approach, original_approach)
        if approach_signal:
            signals.append(approach_signal)

    return signals


def should_escalate(
    signals: list[DriftSignal],
    state: MastermindState,
) -> bool:
    """Determine if escalation should occur based on signals and state.

    Respects cooldown and max escalation limits.
    """
    config = get_config()

    if not signals:
        return False

    # Check if any signal requires escalation
    escalation_needed = any(s.should_escalate for s in signals)
    if not escalation_needed:
        return False

    # Check cooldown and limits
    return state.can_escalate(
        config.drift.cooldown_turns,
        config.drift.max_escalations_per_session,
    )
