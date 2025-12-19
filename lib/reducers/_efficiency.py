#!/usr/bin/env python3
"""Confidence reducers: efficiency category."""

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ._base import ConfidenceReducer

if TYPE_CHECKING:
    from session_state import SessionState


@dataclass
class SequentialRepetitionReducer(ConfidenceReducer):
    """Triggers when same tool is used 3+ times sequentially without state change.

    Softened from -3 to -1 to avoid punishing legitimate iterative debugging.
    Only triggers after 3+ consecutive uses of same tool category.
    """

    name: str = "sequential_repetition"
    delta: int = -1  # Softened from -3
    description: str = "Same tool used 3+ times sequentially"
    cooldown_turns: int = 1

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.get_effective_cooldown(state):
            return False
        # Now requires 3+ consecutive (set by detection logic)
        return context.get("sequential_repetition_3plus", False)


@dataclass
class SequentialWhenParallelReducer(ConfidenceReducer):
    """Triggers on 3+ sequential single-tool messages when parallel was possible.

    Wastes tokens and time doing one thing at a time when multiple
    independent operations could run in parallel.
    """

    name: str = "sequential_when_parallel"
    delta: int = -2
    description: str = "Sequential single-tool calls (could parallelize)"
    remedy: str = "batch independent reads/operations"
    cooldown_turns: int = 3

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.get_effective_cooldown(state):
            return False
        # Track consecutive single reads/searches (guard for mock states)
        return getattr(state, "consecutive_single_reads", 0) >= 3


@dataclass
class RereadUnchangedReducer(ConfidenceReducer):
    """Triggers when re-reading a file that hasn't changed since last read.

    Wastes time and tokens re-reading content already in context.
    """

    name: str = "reread_unchanged"
    delta: int = -3
    description: str = "Re-read unchanged file (already in context)"
    remedy: str = "use info already in context"
    cooldown_turns: int = 1

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.get_effective_cooldown(state):
            return False
        return context.get("reread_unchanged", False)


@dataclass
class VerbosePreambleReducer(ConfidenceReducer):
    """Triggers on verbose preambles like 'I'll now...' or 'Let me...'.

    Wastes tokens on fluff instead of direct action.
    """

    name: str = "verbose_preamble"
    delta: int = -3
    description: str = "Verbose preamble (fluff before action)"
    remedy: str = "start with the action, skip preamble"
    cooldown_turns: int = 2
    patterns: list = field(
        default_factory=lambda: [
            r"^(?:i'?ll|let me|i'?m going to|i will now|now i'?ll)\s+(?:go ahead and|proceed to|start by)",
            r"^(?:first,?\s+)?(?:i'?ll|let me)\s+(?:begin|start)\s+by\s+(?:reading|checking|looking)",
            r"^(?:okay|alright|sure),?\s+(?:i'?ll|let me|i will)\s+",
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
        # Check first 200 chars for preamble patterns
        first_part = output[:200].lower().strip()
        for pattern in self.patterns:
            if re.search(pattern, first_part):
                return True
        return False


@dataclass
class HugeOutputDumpReducer(ConfidenceReducer):
    """Triggers when dumping huge tool output without summarizing.

    Wastes context window with raw dumps instead of extracting key info.
    """

    name: str = "huge_output_dump"
    delta: int = -2
    description: str = "Huge output dump without summarizing"
    remedy: str = "summarize key findings instead"
    cooldown_turns: int = 2

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.get_effective_cooldown(state):
            return False
        return context.get("huge_output_dump", False)


@dataclass
class RedundantExplanationReducer(ConfidenceReducer):
    """Triggers when re-explaining something already explained.

    Wastes tokens repeating information user already has.
    """

    name: str = "redundant_explanation"
    delta: int = -2
    description: str = "Redundant explanation (already explained)"
    remedy: str = "skip re-explaining, just proceed"
    cooldown_turns: int = 3
    patterns: list = field(
        default_factory=lambda: [
            r"\bas\s+(?:i|we)\s+(?:mentioned|said|explained|noted)\s+(?:earlier|before|previously)\b",
            r"\bto\s+reiterate\b",
            r"\bas\s+(?:i|we)\s+(?:already|just)\s+(?:mentioned|said|explained)\b",
            r"\blike\s+(?:i|we)\s+said\s+(?:earlier|before)\b",
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
        for pattern in self.patterns:
            if re.search(pattern, output.lower()):
                return True
        return False


@dataclass
class TrivialQuestionReducer(ConfidenceReducer):
    """Triggers when asking questions that could be answered by reading code.

    Should read the code first instead of asking obvious questions.
    """

    name: str = "trivial_question"
    delta: int = -5
    description: str = "Trivial question (read code instead)"
    remedy: str = "read the code first"
    cooldown_turns: int = 3

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.get_effective_cooldown(state):
            return False
        return context.get("trivial_question", False)


@dataclass
class ObviousNextStepsReducer(ConfidenceReducer):
    """Triggers on useless obvious 'next steps' suggestions.

    Patterns like "test in real usage", "tune values", "monitor for issues"
    are filler that wastes tokens and provides no actionable guidance.
    """

    name: str = "obvious_next_steps"
    delta: int = -5
    description: str = "Obvious/useless next steps (filler)"
    remedy: str = "only suggest paths needing user input"
    cooldown_turns: int = 1
    patterns: list = field(
        default_factory=lambda: [
            r"test\s+(?:in\s+)?(?:real\s+)?usage",
            r"tune\s+(?:the\s+)?(?:values?|deltas?|parameters?)",
            r"adjust\s+(?:as\s+)?needed",
            r"monitor\s+(?:for\s+)?(?:issues?|problems?)",
            r"verify\s+(?:it\s+)?works",
            r"play\s*test",
            r"try\s+it\s+out",
            r"see\s+how\s+it\s+(?:works|performs)",
            r"test\s+the\s+(?:new\s+)?(?:patterns?|changes?|implementation)",
            # v4.13: Git ops are auto-handled - never suggest as next steps
            r"commit\s+(?:the\s+)?(?:changes?|v\d|now)",
            r"push\s+(?:to\s+)?(?:remote|origin|main|master)",
            r"git\s+(?:add|commit|push)",
            r"ready\s+(?:to\s+)?commit",
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
        # Only check in "Next Steps" section if present
        next_steps_match = re.search(
            r"(?:next\s+steps?|➡️).*$", output, re.IGNORECASE | re.DOTALL
        )
        if next_steps_match:
            section = next_steps_match.group(0)
        else:
            # Check last 500 chars as fallback
            section = output[-500:]
        for pattern in self.patterns:
            if re.search(pattern, section, re.IGNORECASE):
                return True
        return False


@dataclass
class SequentialFileOpsReducer(ConfidenceReducer):
    """Triggers when doing 3+ file operations that could be parallelized.

    Sequential Read/Edit/Write calls waste round trips.
    Should batch or parallelize file operations.
    """

    name: str = "sequential_file_ops"
    delta: int = -1
    description: str = "Sequential file ops (batch or parallelize)"
    remedy: str = "parallelize independent file ops"
    cooldown_turns: int = 3

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.get_effective_cooldown(state):
            return False
        # Context-based: hook sets this when detecting sequential pattern
        return context.get("sequential_file_ops", False)


# =============================================================================
# SCRIPTING ESCAPE HATCH REDUCERS (v4.11) - Encourage tmp scripts over complex bash
# =============================================================================


__all__ = [
    "SequentialRepetitionReducer",
    "SequentialWhenParallelReducer",
    "RereadUnchangedReducer",
    "VerbosePreambleReducer",
    "HugeOutputDumpReducer",
    "RedundantExplanationReducer",
    "TrivialQuestionReducer",
    "ObviousNextStepsReducer",
    "SequentialFileOpsReducer",
]
