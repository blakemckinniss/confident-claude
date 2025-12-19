#!/usr/bin/env python3
"""Confidence reducers: stuck category."""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ._base import ConfidenceReducer

if TYPE_CHECKING:
    from session_state import SessionState


@dataclass
class StuckLoopReducer(ConfidenceReducer):
    """Triggers when editing same file repeatedly without research.

    Detects debugging loops where Claude keeps trying same approach
    without success. Forces research/external consultation.
    """

    name: str = "stuck_loop"
    delta: int = -15
    description: str = "Stuck in debug loop - research required"
    remedy: str = "use WebSearch, PAL debug, or mcp__pal__apilookup"
    cooldown_turns: int = 5

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.get_effective_cooldown(state):
            return False
        # Context-based: hook sets this when stuck loop detected
        return context.get("stuck_loop_detected", False)


@dataclass
class NoResearchDebugReducer(ConfidenceReducer):
    """Triggers when debugging for extended period without research.

    After 3+ fix attempts on same symptom, should research online
    or consult external LLM for fresh perspective.
    """

    name: str = "no_research_debug"
    delta: int = -10
    description: str = "Extended debugging without research"
    remedy: str = "consult external LLM or search for solutions"
    cooldown_turns: int = 8

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.get_effective_cooldown(state):
            return False
        # Context-based: hook sets when no research done in debug session
        return context.get("no_research_in_debug", False)


# =============================================================================
# MASTERMIND DRIFT REDUCERS (v4.10)
# =============================================================================
# These reducers fire when mastermind drift detection signals are active.
# Signals are passed in context["mastermind_drift"] dict from check_mastermind_drift().
# =============================================================================


__all__ = [
    "StuckLoopReducer",
    "NoResearchDebugReducer",
]
