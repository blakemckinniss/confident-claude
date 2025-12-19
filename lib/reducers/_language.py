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
# PAL MAXIMIZATION REDUCERS (v4.19) - Penalties for NOT using external LLMs
# =============================================================================
# PAL MCP provides "free" auxiliary context. These reducers create friction
# when Claude does complex reasoning inline instead of delegating to PAL.
# =============================================================================


@dataclass
class InlineComplexReasoningReducer(ConfidenceReducer):
    """Triggers when doing complex reasoning inline without PAL delegation.

    Long reasoning passages (500+ chars) in Claude's output consume precious
    context window. This reasoning could be offloaded to PAL tools instead.

    Exception: If PAL was used this turn, don't penalize - Claude may be
    synthesizing PAL's response.
    """

    name: str = "inline_complex_reasoning"
    delta: int = -3
    description: str = "Complex reasoning without PAL delegation"
    remedy: str = "use mcp__pal__thinkdeep or mcp__pal__chat to offload reasoning"
    cooldown_turns: int = 3

    # Minimum chars to consider "complex reasoning"
    threshold_chars: int = 500

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.get_effective_cooldown(state):
            return False

        # Skip if PAL was used this turn (Claude synthesizing response)
        if context.get("pal_used_this_turn", False):
            return False

        # Check assistant output length
        assistant_output = context.get("assistant_output", "")
        if len(assistant_output) < self.threshold_chars:
            return False

        # Check for reasoning indicators in output
        reasoning_patterns = [
            r"\blet me think\b",
            r"\bconsidering\b",
            r"\banalyzing\b",
            r"\bevaluating\b",
            r"\bweighing\b",
            r"\btrade-?offs?\b",
            r"\bpros? and cons?\b",
            r"\boption[s]?\s*(?:1|2|a|b|:)",
            r"\bapproach\s*(?:1|2|a|b|:)",
        ]

        import re

        output_lower = assistant_output.lower()
        has_reasoning = any(re.search(p, output_lower) for p in reasoning_patterns)

        return has_reasoning


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
    "InlineComplexReasoningReducer",
    "DebugLoopNoPalReducer",
]
