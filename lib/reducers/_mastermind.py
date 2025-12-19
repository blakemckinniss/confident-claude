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
# COVERAGE GAP REDUCERS (v4.18) - Anti-patterns that were detectable but missed
# =============================================================================


__all__ = [
    "MastermindFileDriftReducer",
    "MastermindTestDriftReducer",
    "MastermindApproachDriftReducer",
]
