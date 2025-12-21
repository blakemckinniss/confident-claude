#!/usr/bin/env python3
"""Confidence reducers: core category."""

import re
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ._base import ConfidenceReducer

if TYPE_CHECKING:
    from session_state import SessionState


@dataclass
class ToolFailureReducer(ConfidenceReducer):
    """Triggers on Bash/command failures."""

    name: str = "tool_failure"
    delta: int = -5
    description: str = "Tool execution failed (exit code != 0)"
    remedy: str = "check command syntax, verify paths exist"
    cooldown_turns: int = 1

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.get_effective_cooldown(state):
            return False
        # Check for NEW failures since last trigger (prevents double-fire)
        last_processed_ts = state.nudge_history.get(f"reducer_{self.name}_last_ts", 0)
        cutoff = max(time.time() - 60, last_processed_ts)
        new_failures = [
            cmd
            for cmd in state.commands_failed[-5:]
            if cmd.get("timestamp", 0) > cutoff
        ]
        if new_failures:
            # Update last processed timestamp
            state.nudge_history[f"reducer_{self.name}_last_ts"] = max(
                cmd.get("timestamp", 0) for cmd in new_failures
            )
            return True
        return False


@dataclass
class CascadeBlockReducer(ConfidenceReducer):
    """Triggers when same hook blocks 3+ times in 5 turns."""

    name: str = "cascade_block"
    delta: int = -15
    description: str = "Same hook blocked 3+ times recently"
    remedy: str = "fix the root cause the hook is flagging"
    cooldown_turns: int = 5

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.get_effective_cooldown(state):
            return False
        # Check consecutive_blocks from session_state
        for hook_name, entry in state.consecutive_blocks.items():
            if entry.get("count", 0) >= 3:
                return True
        return False


@dataclass
class SunkCostReducer(ConfidenceReducer):
    """Triggers on 3+ consecutive failures."""

    name: str = "sunk_cost"
    delta: int = -20
    description: str = "3+ consecutive failures on same approach"
    remedy: str = "run /think, try different approach"
    cooldown_turns: int = 5

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.get_effective_cooldown(state):
            return False
        return state.consecutive_failures >= 3


@dataclass
class UserCorrectionReducer(ConfidenceReducer):
    """Triggers when user corrects Claude."""

    name: str = "user_correction"
    delta: int = -10
    description: str = "User corrected or contradicted response"
    remedy: str = "acknowledge and fix the specific issue"
    cooldown_turns: int = 3
    patterns: list = field(
        default_factory=lambda: [
            r"\bthat'?s?\s+(?:not\s+)?(?:wrong|incorrect)\b",
            r"\bno,?\s+(?:that|it)\b",
            r"\bactually\s+(?:it|that|you)\b",
            # "fix that" but NOT when followed by task nouns (bug, issue, etc.)
            # This prevents "fix that false positive" from triggering
            r"\bfix\s+that\b(?!\s+(?:bug|issue|error|problem|false\s+positive|fp|reducer|hook|file|function|code|feature|test|logic))",
            r"\byou\s+(?:made|have)\s+(?:a\s+)?(?:mistake|error)\b",
            r"\bwrong\s+(?:file|path|function|approach)\b",
        ]
    )

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.get_effective_cooldown(state):
            return False
        prompt = context.get("prompt", "").lower()
        for pattern in self.patterns:
            if re.search(pattern, prompt):
                return True
        return False


@dataclass
class EditOscillationReducer(ConfidenceReducer):
    """Triggers when edits revert previous changes (actual oscillation).

    Zone-scaled thresholds (v4.12):
    - EXPERT/TRUSTED (86+): 6 edits before trigger - more freedom to iterate
    - CERTAINTY (71-85): 4 edits - moderate tolerance
    - WORKING (51-70): 3 edits - standard sensitivity
    - HYPOTHESIS/IGNORANCE (<51): 2 edits - force research earlier
    """

    name: str = "edit_oscillation"
    delta: int = -12
    description: str = "Edits reverting previous changes (back-forth pattern)"
    remedy: str = "step back, research the right solution first"
    cooldown_turns: int = 5

    def _get_zone_threshold(self, confidence: int) -> int:
        """Get oscillation detection threshold based on confidence zone."""
        if confidence >= 86:  # EXPERT/TRUSTED
            return 6
        elif confidence >= 71:  # CERTAINTY
            return 4
        elif confidence >= 51:  # WORKING
            return 3
        else:  # HYPOTHESIS/IGNORANCE
            return 2

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.get_effective_cooldown(state):
            return False

        # Get zone-scaled threshold
        confidence = getattr(state, "confidence", 75)
        min_edits = self._get_zone_threshold(confidence)

        # Check for actual oscillation pattern in edit_history
        # Oscillation = latest edit's NEW content matches a PREVIOUS state
        # (i.e., reverting back to something we had before)
        edit_history = getattr(state, "edit_history", {})
        for filepath, history in edit_history.items():
            if len(history) < min_edits:  # Zone-scaled threshold
                continue
            # Collect ALL states from edits before the previous one
            # (skip immediately previous edit - that's normal iteration)
            # Track both old and new hashes to catch: v0→v1→v0→v1 patterns
            previous_states: set[str] = set()
            for h in history[:-2]:
                if h[0]:
                    previous_states.add(h[0])
                if h[1]:
                    previous_states.add(h[1])
            # Check if latest edit's new_hash matches any older state
            latest = history[-1]
            latest_new_hash = latest[1]
            if latest_new_hash and latest_new_hash in previous_states:
                return True  # Detected revert to previous state

        return False


@dataclass
class ContradictionReducer(ConfidenceReducer):
    """Triggers on contradictory claims within session.

    Detection via:
    1. User explicitly points out contradiction (pattern matching)
    2. External LLM verification when patterns match (via Groq)
    """

    name: str = "contradiction"
    delta: int = -10
    description: str = "Made contradictory claims"
    remedy: str = "review previous statements, clarify position"
    cooldown_turns: int = 5

    # Patterns that suggest user noticed a contradiction
    contradiction_patterns: list = field(
        default_factory=lambda: [
            r"\byou (said|told me|mentioned|stated|claimed)\b.*\b(but|now|however)\b",
            r"\bthat('s| is) (contradicting|contradictory|inconsistent)",
            r"\bthat contradicts\b",
            r"\byou('re| are) contradicting\b",
            r"\bearlier you said\b",
            r"\bbefore you (said|mentioned)\b.*\b(now|but)\b",
            r"\bthat('s| is) the opposite of\b",
            r"\byou just said the opposite\b",
            r"\bwhich (is it|one is it)\b",
            r"\bmake up your mind\b",
        ]
    )

    def check_user_reported_contradiction(self, prompt: str) -> bool:
        """Check if user is reporting a contradiction via patterns."""
        prompt_lower = prompt.lower()
        for pattern in self.contradiction_patterns:
            if re.search(pattern, prompt_lower):
                return True
        return False

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.get_effective_cooldown(state):
            return False

        # Check for explicit contradiction flag (set by hooks)
        if context.get("contradiction_detected", False):
            return True

        # Check if user reported contradiction in recent prompt
        prompt = context.get("prompt", "")
        if prompt and self.check_user_reported_contradiction(prompt):
            return True

        return False


@dataclass
class FollowUpQuestionReducer(ConfidenceReducer):
    """Triggers when user asks follow-up questions (indicating incomplete answer)."""

    name: str = "follow_up_question"
    delta: int = -5
    description: str = "User asked follow-up question (answer was incomplete)"
    remedy: str = "provide complete answers upfront"
    cooldown_turns: int = 2
    # More specific patterns to reduce false positives
    # Removed: r"\?$" (too broad - catches all questions)
    # Removed: r"^(why|how|what|where|when|which|who)\b" (too broad - catches new questions)
    patterns: list = field(
        default_factory=lambda: [
            # Clarification requests (answer was unclear)
            r"\bwhat do you mean\b",
            r"\bcan you (explain|clarify|elaborate)\b.*\?",
            r"\bi (don't understand|still don't get|am confused about)\b",
            # Dissatisfaction signals (answer was wrong/unhelpful)
            r"\bthat doesn't (work|help|answer|make sense)\b",
            r"\bthat's (not right|wrong|incorrect|not what i)\b",
            r"^(no|nope),?\s+(that's not|it's not|this isn't)",
            # Explicit incompleteness (I missed something)
            r"\byou (didn't|forgot to|missed|skipped|left out)\b",
            r"\bwhat about the\s+\w+\s+(you|i|we)\s+(mentioned|discussed|said)\b",
            r"\byou said you would\b",
            r"\bwasn't that supposed to\b",
        ]
    )

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.get_effective_cooldown(state):
            return False
        prompt = context.get("prompt", "").lower().strip()
        # Only trigger on short-to-medium prompts (follow-ups are usually brief)
        if len(prompt) > 200 or len(prompt) < 5:
            return False
        for pattern in self.patterns:
            if re.search(pattern, prompt, re.IGNORECASE):
                return True
        return False


@dataclass
class GoalDriftReducer(ConfidenceReducer):
    """Triggers when current activity diverges from original goal.

    Detection: Compare keywords from original goal (first substantive prompt)
    with recent activity. If overlap drops below threshold, goal drift detected.
    """

    name: str = "goal_drift"
    delta: int = -8
    description: str = "Activity diverging from original goal"
    remedy: str = "refocus on original task or explicitly pivot with user approval"
    cooldown_turns: int = 8
    overlap_threshold: float = 0.20  # < 20% keyword overlap = drift

    def _extract_keywords(self, text: str) -> set:
        """Extract meaningful keywords from text."""
        if not text:
            return set()
        # Simple keyword extraction: lowercase words 4+ chars, no common words
        stopwords = {
            "that", "this", "with", "from", "have", "been", "were", "will",
            "would", "could", "should", "their", "there", "what", "when",
            "where", "which", "while", "about", "after", "before", "being",
            "between", "both", "each", "into", "just", "like", "make", "more",
            "most", "only", "other", "over", "some", "such", "than", "them",
            "then", "these", "they", "through", "under", "very", "want",
            "your", "also", "back", "because", "come", "does", "even", "first",
            "give", "going", "good", "here", "know", "look", "made", "many",
            "much", "need", "never", "work", "year", "take", "thing", "think",
            "time", "well", "file", "code", "function", "class", "method",
        }
        words = re.findall(r"\b[a-z]{4,}\b", text.lower())
        return {w for w in words if w not in stopwords}

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.get_effective_cooldown(state):
            return False

        # Get original goal from session state
        original_goal = getattr(state, "original_goal", "") or ""
        if not original_goal:
            return False

        # Get current activity description (recent context)
        current_activity = context.get("current_activity", "")
        if not current_activity:
            # Fall back to recent files/tools as proxy for activity
            recent_files = getattr(state, "files_edited", [])[-5:]
            recent_tools = getattr(state, "tools_used", [])[-10:]
            current_activity = " ".join(recent_files + recent_tools)

        if not current_activity:
            return False

        # Compare keyword overlap
        goal_keywords = self._extract_keywords(original_goal)
        activity_keywords = self._extract_keywords(current_activity)

        if not goal_keywords:
            return False

        overlap = len(goal_keywords & activity_keywords)
        overlap_ratio = overlap / len(goal_keywords)

        return overlap_ratio < self.overlap_threshold


__all__ = [
    "ToolFailureReducer",
    "CascadeBlockReducer",
    "SunkCostReducer",
    "UserCorrectionReducer",
    "EditOscillationReducer",
    "ContradictionReducer",
    "FollowUpQuestionReducer",
    "GoalDriftReducer",
]
