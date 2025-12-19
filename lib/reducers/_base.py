#!/usr/bin/env python3
"""
Base class and constants for confidence reducers.

This module provides the foundation for all reducer implementations.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from session_state import SessionState


# Impact categories for streak protection (v4.21)
# FAILURE: Active failures that indicate things went wrong - resets streak
# BEHAVIORAL: Bad language/process patterns - resets streak
# AMBIENT: Background costs of taking action - does NOT reset streak
IMPACT_FAILURE = "FAILURE"
IMPACT_BEHAVIORAL = "BEHAVIORAL"
IMPACT_AMBIENT = "AMBIENT"


@dataclass
class ConfidenceReducer:
    """A deterministic confidence reducer that fires on specific signals.

    Zone-Scaled Cooldowns (v4.13):
    Cooldowns scale by confidence zone - creating more friction at low confidence:
    - EXPERT/TRUSTED (86+): 1.5x cooldown (more lenient, earned freedom)
    - CERTAINTY (71-85): 1.0x cooldown (baseline)
    - WORKING (51-70): 0.75x cooldown (more friction)
    - HYPOTHESIS/IGNORANCE (<51): 0.5x cooldown (maximum friction)

    Use get_effective_cooldown(state) instead of raw cooldown_turns for zone-scaling.

    Impact Categories (v4.21):
    - FAILURE: Active failures (tool_failure, sunk_cost) - resets streak
    - BEHAVIORAL: Bad patterns (sycophancy, deferral) - resets streak
    - AMBIENT: Background costs (decay, bash-risk, edit-risk) - does NOT reset streak
    """

    name: str
    delta: int  # Negative value
    description: str
    remedy: str = ""  # What to do instead (actionable guidance)
    cooldown_turns: int = 3  # Minimum turns between triggers (baseline)
    penalty_class: str = (
        "PROCESS"  # "PROCESS" (recoverable) or "INTEGRITY" (not recoverable)
    )
    max_recovery_fraction: float = (
        0.5  # Max % of penalty that can be recovered (0.0 for INTEGRITY)
    )
    impact_category: str = IMPACT_FAILURE  # Default to FAILURE (streak-breaking)

    def get_effective_cooldown(self, state: "SessionState") -> int:
        """Get zone-scaled cooldown based on current confidence.

        Lower confidence = shorter cooldown = more friction = more signals.
        This implements the crescendo theory: declining confidence intensifies guardrails.
        """
        confidence = getattr(state, "confidence", 75)

        if confidence >= 86:  # EXPERT/TRUSTED - earned freedom
            multiplier = 1.5
        elif confidence >= 71:  # CERTAINTY - baseline
            multiplier = 1.0
        elif confidence >= 51:  # WORKING - increased friction
            multiplier = 0.75
        else:  # HYPOTHESIS/IGNORANCE - maximum friction
            multiplier = 0.5

        return max(1, int(self.cooldown_turns * multiplier))

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        """Check if this reducer should fire. Override in subclasses."""
        # Cooldown check (zone-scaled)
        effective_cooldown = self.get_effective_cooldown(state)
        if state.turn_count - last_trigger_turn < effective_cooldown:
            return False
        return False


__all__ = [
    "ConfidenceReducer",
    "IMPACT_FAILURE",
    "IMPACT_BEHAVIORAL",
    "IMPACT_AMBIENT",
]
