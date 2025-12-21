#!/usr/bin/env python3
"""Confidence reducers: language category."""

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ._base import ConfidenceReducer

if TYPE_CHECKING:
    from session_state import SessionState


@dataclass
class HedgingLanguageReducer(ConfidenceReducer):
    """Triggers on hedging language without follow-up action.

    "This might work" or "could possibly help" indicates uncertainty
    that should be resolved via research or questions, not ignored.
    """

    name: str = "hedging_language"
    delta: int = -3
    description: str = "Hedging language without investigation"
    remedy: str = "research to confirm, or ask user"
    cooldown_turns: int = 3
    patterns: list = field(
        default_factory=lambda: [
            r"\b(?:this\s+)?(?:might|could|may)\s+(?:work|help|fix|solve)\b",
            r"\bperhaps\s+(?:we|you|i)\s+(?:should|could|can)\b",
            r"\bpossibly\s+(?:the|a|this)\b",
            r"\bi'?m\s+not\s+(?:sure|certain)\s+(?:if|whether|that)\b",
            r"\bmaybe\s+(?:we|you|i|this|it)\b",
            r"\bnot\s+(?:entirely\s+)?sure\s+(?:if|whether|about)\b",
        ]
    )

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.get_effective_cooldown(state):
            return False

        output = context.get("assistant_output", "")
        if not output:
            return False

        # Check for hedging patterns
        has_hedging = False
        for pattern in self.patterns:
            if re.search(pattern, output, re.IGNORECASE):
                has_hedging = True
                break

        if not has_hedging:
            return False

        # Check if hedging is followed by action (research, question, tool use)
        # If there's a tool call in the same turn, don't penalize
        if context.get("research_performed", False):
            return False
        if context.get("asked_user", False):
            return False

        return True


@dataclass
class PhantomProgressReducer(ConfidenceReducer):
    """Triggers on progress claims without corresponding tool use.

    "Making progress" or "Getting closer" without actual changes is theater.
    """

    name: str = "phantom_progress"
    delta: int = -5
    description: str = "Progress claim without tool use"
    remedy: str = "do actual work before claiming progress"
    cooldown_turns: int = 3
    patterns: list = field(
        default_factory=lambda: [
            r"\bmaking\s+(?:good\s+)?progress\b",
            r"\bgetting\s+(?:closer|there)\b",
            r"\balmost\s+(?:done|there|finished)\b",
            r"\bnearly\s+(?:done|there|finished|complete)\b",
            r"\bwe'?re\s+(?:on\s+track|close)\b",
            r"\bthings\s+are\s+(?:coming\s+together|working)\b",
        ]
    )

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.get_effective_cooldown(state):
            return False

        output = context.get("assistant_output", "")
        if not output:
            return False

        # Check for progress claims
        has_claim = False
        for pattern in self.patterns:
            if re.search(pattern, output, re.IGNORECASE):
                has_claim = True
                break

        if not has_claim:
            return False

        # Check if there was actual work this turn
        tool_name = context.get("tool_name", "")
        if tool_name in ("Edit", "Write", "Bash"):
            return False  # Actual work was done

        return True


@dataclass
class QuestionAvoidanceReducer(ConfidenceReducer):
    """Triggers when working on ambiguous task without asking questions.

    Extended autonomous work on vague prompts without clarification
    often leads to wasted effort on wrong interpretation.
    """

    name: str = "question_avoidance"
    delta: int = -8
    description: str = "Extended work without clarifying questions"
    remedy: str = "use AskUserQuestion to clarify ambiguity"
    cooldown_turns: int = 15  # Only trigger once per extended period

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.get_effective_cooldown(state):
            return False

        # Need 15+ turns to trigger
        if state.turn_count < 15:
            return False

        # Check if ANY questions were asked in the session
        questions_asked = state.nudge_history.get("ask_user_count", 0)
        if questions_asked > 0:
            return False

        # Check if goal seems ambiguous (short, vague keywords)
        original_goal = getattr(state, "original_goal", "")
        if not original_goal:
            return False

        # Vague goal indicators
        vague_patterns = [
            r"^(?:fix|improve|update|change|make)\s+(?:it|this|that)\b",
            r"^(?:something|anything)\s+(?:like|similar)\b",
            r"\b(?:better|nicer|cleaner)\b",
            r"^(?:help|can you)\b",
        ]

        is_vague = any(
            re.search(p, original_goal, re.IGNORECASE) for p in vague_patterns
        )

        return is_vague


# =============================================================================
# PERPETUAL MOMENTUM REDUCERS (v4.24) - Enforce forward motion philosophy
# =============================================================================
# Core principle: "What can we do to make this even better?"
# Things are never "done" - always enhancement, testing, meta-cognition available.
# Deadend responses without actionable next steps are penalized.
# =============================================================================


@dataclass
class DeadendResponseReducer(ConfidenceReducer):
    """Triggers when response ends without actionable next steps.

    Deadend patterns indicate satisfaction without forward motion.
    The framework demands perpetual momentum - always suggesting what
    Claude can do next (not passive "you could" suggestions).

    Anti-patterns:
    - "That's all for now"
    - "We're done here"
    - "Let me know if you need anything"
    - Passive suggestions: "You could...", "You might want to..."

    Pro-patterns (NOT penalized):
    - "I can...", "Let me...", "I will..."
    - "Next Steps:" section with actionable items
    - Questions to drive continuation
    """

    name: str = "deadend_response"
    delta: int = -8
    description: str = "Response ended without actionable next steps"
    remedy: str = "add 'I can...' suggestions or Next Steps section"
    cooldown_turns: int = 2
    deadend_patterns: list = field(
        default_factory=lambda: [
            r"\bthat'?s\s+(?:all|it)\s+(?:for now|i have)\b",
            r"\bwe'?re\s+(?:all\s+)?(?:done|finished|complete)\b",
            r"\blet\s+me\s+know\s+if\s+(?:you\s+)?(?:need|want|have)\b",
            r"\bhope\s+(?:this|that)\s+helps?\b",
            r"\banything\s+else\s+(?:you\s+)?(?:need|want)\b",
            r"\bfeel\s+free\s+to\s+(?:ask|reach out)\b",
            r"\bi'?m\s+here\s+if\s+you\s+need\b",
            r"\bdon'?t\s+hesitate\s+to\b",
        ]
    )
    passive_patterns: list = field(
        default_factory=lambda: [
            r"\byou\s+(?:could|might|may)\s+(?:want\s+to|consider|try)\b",
            r"\byou\s+(?:should|can)\s+(?:also\s+)?(?:consider|look at|check)\b",
            r"\bit\s+(?:might|could)\s+be\s+worth\b",
        ]
    )
    momentum_patterns: list = field(
        default_factory=lambda: [
            r"\bi\s+(?:can|will|could)\s+(?:also\s+)?(?:now\s+)?(?:\w+)",
            r"\blet\s+me\s+(?:now\s+)?(?:\w+)",
            r"\bnext\s+(?:i'?ll|step|steps?)[\s:]+",
            r"\b(?:shall|should)\s+i\s+(?:\w+)",
            r"\bwant\s+me\s+to\b",
            r"(?:^|\n)#+\s*(?:next\s+steps?|➡️|🛤️)",
            r"(?:^|\n)\*\*(?:next\s+steps?|➡️)\*\*",
        ]
    )

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.get_effective_cooldown(state):
            return False

        output = context.get("assistant_output", "")
        if not output or len(output) < 100:  # Skip very short responses
            return False

        output_lower = output.lower()

        # Check for momentum patterns - if present, don't penalize
        for pattern in self.momentum_patterns:
            if re.search(pattern, output_lower, re.IGNORECASE | re.MULTILINE):
                return False

        # Check for deadend patterns
        has_deadend = False
        for pattern in self.deadend_patterns:
            if re.search(pattern, output_lower, re.IGNORECASE):
                has_deadend = True
                break

        # Check for passive patterns (weaker signal)
        has_passive = False
        if not has_deadend:
            for pattern in self.passive_patterns:
                if re.search(pattern, output_lower, re.IGNORECASE):
                    has_passive = True
                    break

        # Trigger on deadend, or passive without momentum
        return has_deadend or has_passive


# =============================================================================
# PAL MAXIMIZATION REDUCERS (v4.19) - Penalties for NOT using external LLMs
# =============================================================================
# PAL MCP provides "free" auxiliary context. These reducers create friction
# when Claude does complex reasoning inline instead of delegating to PAL.
# =============================================================================


@dataclass
class DebugLoopNoPalReducer(ConfidenceReducer):
    """Triggers when debugging iteratively without using PAL debug.

    After 2+ debug attempts on same issue, should delegate to
    mcp__pal__debug for external perspective. Iterative debugging
    burns context without fresh insight.
    """

    name: str = "debug_loop_no_pal"
    delta: int = -5
    description: str = "Iterative debugging without PAL consultation"
    remedy: str = "use mcp__pal__debug for external debugging perspective"
    cooldown_turns: int = 5

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.get_effective_cooldown(state):
            return False

        # Check for debug loop indicators
        debug_attempts = context.get("debug_attempts_without_pal", 0)
        if debug_attempts < 2:
            return False

        # Check if mcp__pal__debug was used recently
        recent_pal_debug = context.get("pal_debug_used_recently", False)
        if recent_pal_debug:
            return False

        return True


# =============================================================================
# TEST ENFORCEMENT REDUCERS (v4.20) - Ensure tests are always run
# =============================================================================


__all__ = [
    "HedgingLanguageReducer",
    "PhantomProgressReducer",
    "QuestionAvoidanceReducer",
    "DeadendResponseReducer",
    "DebugLoopNoPalReducer",
]
