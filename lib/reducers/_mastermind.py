#!/usr/bin/env python3
"""Confidence reducers: mastermind category."""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ._base import ConfidenceReducer

if TYPE_CHECKING:
    from session_state import SessionState


@dataclass
class MastermindFileDriftReducer(ConfidenceReducer):
    """Triggers when file modifications exceed blueprint touch_set.

    Fires when mastermind detects 5+ files modified outside the expected
    touch_set from the blueprint.
    """

    name: str = "mm_drift_files"
    delta: int = -8
    description: str = "5+ files modified outside blueprint touch_set"
    remedy: str = "stay within blueprint touch_set"
    cooldown_turns: int = 8

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.get_effective_cooldown(state):
            return False
        # Check for drift signal in context
        drift_signals = context.get("mastermind_drift", {})
        return drift_signals.get("file_count", False)


@dataclass
class MastermindTestDriftReducer(ConfidenceReducer):
    """Triggers on consecutive test failures detected by mastermind.

    Fires when mastermind detects 3+ consecutive test failures.
    """

    name: str = "mm_drift_tests"
    delta: int = -10
    description: str = "3+ consecutive test failures"
    remedy: str = "fix failing tests before continuing"
    cooldown_turns: int = 5

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.get_effective_cooldown(state):
            return False
        drift_signals = context.get("mastermind_drift", {})
        return drift_signals.get("test_failures", False)


@dataclass
class MastermindApproachDriftReducer(ConfidenceReducer):
    """Triggers when approach diverges from original blueprint.

    Fires when mastermind detects <30% keyword overlap between
    current approach and original blueprint approach.
    """

    name: str = "mm_drift_pivot"
    delta: int = -12
    description: str = "Approach diverged from blueprint"
    remedy: str = "return to original blueprint approach"
    cooldown_turns: int = 10

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.get_effective_cooldown(state):
            return False
        drift_signals = context.get("mastermind_drift", {})
        return drift_signals.get("approach_change", False)


# =============================================================================
# PHASE 1 METADATA REDUCERS (v4.34) - Groq success_criteria integration
# =============================================================================


@dataclass
class FailureSignalDetectedReducer(ConfidenceReducer):
    """Triggers when Groq-predicted failure patterns are detected in output.

    v4.34: Uses success_criteria.failure_signals from mastermind metadata.
    When tool output contains patterns Groq predicted would indicate failure
    (e.g., "TypeError", "Import error"), this reducer fires.
    """

    name: str = "mm_failure_signal"
    delta: int = -8
    description: str = "Groq-predicted failure pattern detected"
    remedy: str = "address the failure pattern before continuing"
    cooldown_turns: int = 3

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.get_effective_cooldown(state):
            return False

        # Get failure signals from mastermind success_criteria
        success_criteria = getattr(state, "mastermind_success_criteria", None)
        if not success_criteria:
            return False

        failure_signals = success_criteria.get("failure_signals", [])
        if not failure_signals:
            return False

        # Check recent tool output for failure patterns
        recent_output = context.get("tool_output", "") or ""
        recent_output_lower = recent_output.lower()

        for signal in failure_signals:
            signal_lower = signal.lower()
            if signal_lower in recent_output_lower:
                # Store which signal triggered for messaging
                setattr(state, "last_failure_signal", signal)
                return True

        return False


__all__ = [
    "MastermindFileDriftReducer",
    "MastermindTestDriftReducer",
    "MastermindApproachDriftReducer",
    "FailureSignalDetectedReducer",
]
