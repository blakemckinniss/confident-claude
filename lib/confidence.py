#!/usr/bin/env python3
"""
Dynamic Confidence Regulation System

Core engine for mechanical confidence tracking with deterministic reducers
that bypass self-assessment bias.

Design Principles:
1. Reducers fire WITHOUT judgment - mechanical signals only
2. Escalation is MANDATORY at low confidence
3. Trust regain requires explicit user approval for large boosts
4. Visibility: user always sees confidence state and zone changes
"""

import re
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

# Import tier system from epistemology (avoid duplication)
from epistemology import (
    TIER_CERTAINTY,
    TIER_HYPOTHESIS,
    TIER_IGNORANCE,
    TIER_PRIVILEGES,
    TIER_TRUSTED,
    TIER_WORKING,
)

if TYPE_CHECKING:
    from session_state import SessionState

# =============================================================================
# CONSTANTS
# =============================================================================

# Confidence thresholds
THRESHOLD_ROCK_BOTTOM = 10  # At or below: FORCED realignment with user
THRESHOLD_MANDATORY_EXTERNAL = 30  # Below this: external LLM MANDATORY
THRESHOLD_REQUIRE_RESEARCH = 50  # Below this: research REQUIRED
THRESHOLD_PRODUCTION_ACCESS = 51  # Below this: no production writes

# Rock bottom recovery target (nerfed from 85 to prevent gaming)
ROCK_BOTTOM_RECOVERY_TARGET = (
    65  # Boost to this after realignment (not 85 - exploitable)
)

# Tier emoji mapping
TIER_EMOJI = {
    "IGNORANCE": "\U0001f534",  # Red circle
    "HYPOTHESIS": "\U0001f7e0",  # Orange circle
    "WORKING": "\U0001f7e1",  # Yellow circle
    "CERTAINTY": "\U0001f7e2",  # Green circle
    "TRUSTED": "\U0001f49a",  # Green heart
    "EXPERT": "\U0001f48e",  # Gem
}

# Default starting confidence for new sessions
DEFAULT_CONFIDENCE = 70  # Start at WORKING level - must prove up or down

# =============================================================================
# REDUCER REGISTRY (MECHANICAL - NO JUDGMENT)
# =============================================================================


@dataclass
class ConfidenceReducer:
    """A deterministic confidence reducer that fires on specific signals."""

    name: str
    delta: int  # Negative value
    description: str
    cooldown_turns: int = 3  # Minimum turns between triggers

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        """Check if this reducer should fire. Override in subclasses."""
        # Cooldown check
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        return False


@dataclass
class ToolFailureReducer(ConfidenceReducer):
    """Triggers on Bash/command failures."""

    name: str = "tool_failure"
    delta: int = -5
    description: str = "Tool execution failed (exit code != 0)"
    cooldown_turns: int = 1

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
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
    cooldown_turns: int = 5

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
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
    cooldown_turns: int = 5

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        return state.consecutive_failures >= 3


@dataclass
class UserCorrectionReducer(ConfidenceReducer):
    """Triggers when user corrects Claude."""

    name: str = "user_correction"
    delta: int = -10
    description: str = "User corrected or contradicted response"
    cooldown_turns: int = 3
    patterns: list = field(
        default_factory=lambda: [
            r"\bthat'?s?\s+(?:not\s+)?(?:wrong|incorrect)\b",
            r"\bno,?\s+(?:that|it)\b",
            r"\bactually\s+(?:it|that|you)\b",
            r"\bfix\s+that\b",
            r"\byou\s+(?:made|have)\s+(?:a\s+)?(?:mistake|error)\b",
            r"\bwrong\s+(?:file|path|function|approach)\b",
        ]
    )

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        prompt = context.get("prompt", "").lower()
        for pattern in self.patterns:
            if re.search(pattern, prompt, re.IGNORECASE):
                return True
        return False


def _extract_semantic_keywords(activity: str) -> set[str]:
    """Extract semantic keywords from file paths and commands.

    Converts '/home/user/.claude/lib/confidence.py' → {'confidence', 'lib', 'claude'}
    Converts 'git commit -m "fix bug"' → {'git', 'commit', 'fix', 'bug'}
    """
    # Common stop words to filter out
    stop_words = {
        "the",
        "a",
        "an",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
        "will",
        "would",
        "could",
        "should",
        "may",
        "might",
        "must",
        "shall",
        "can",
        "need",
        "dare",
        # Path components that are semantically meaningful - keep for matching
        # Removed: "src", "lib", "test", "tests" - these indicate code structure
        "home",
        "user",
        "users",
        "tmp",
        "var",
        "etc",
        "usr",
        "bin",
        # File extensions - not semantically meaningful
        "py",
        "js",
        "ts",
        "tsx",
        "jsx",
        "md",
        "json",
        "yaml",
        "yml",
        "txt",
        "css",
        "html",
        "xml",
    }

    # Extract words from the activity string
    # Split on path separators, spaces, underscores, hyphens, dots
    words = re.findall(r"[a-zA-Z]{3,}", activity.lower())

    # Filter out stop words and very short words
    keywords = {w for w in words if w not in stop_words and len(w) >= 3}

    return keywords


@dataclass
class GoalDriftReducer(ConfidenceReducer):
    """Triggers when activity diverges from original goal."""

    name: str = "goal_drift"
    delta: int = -8
    description: str = "Activity diverged from original goal"
    cooldown_turns: int = 8

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        # Use existing goal drift detection from session_state
        if not state.original_goal or not state.goal_keywords:
            return False
        if state.turn_count - state.goal_set_turn < 5:
            return False

        # Get current activity and extract semantic keywords
        current = context.get("current_activity", "")
        if not current:
            return False

        # Extract keywords from file paths/commands (semantic matching)
        activity_keywords = _extract_semantic_keywords(current)
        if not activity_keywords:
            return False

        # Check overlap between goal keywords and activity keywords
        goal_set = set(state.goal_keywords)
        matches = len(goal_set & activity_keywords)
        overlap = matches / len(goal_set) if goal_set else 0

        # Only trigger if very low overlap (< 10% instead of 20%)
        # This is more lenient since semantic extraction is imperfect
        return overlap < 0.1


@dataclass
class EditOscillationReducer(ConfidenceReducer):
    """Triggers when edits revert previous changes (actual oscillation)."""

    name: str = "edit_oscillation"
    delta: int = -12
    description: str = "Edits reverting previous changes (back-forth pattern)"
    cooldown_turns: int = 5

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False

        # Check for actual oscillation pattern in edit_history
        # Oscillation = latest edit's NEW content matches a PREVIOUS state
        # (i.e., reverting back to something we had before)
        edit_history = getattr(state, "edit_history", {})
        for filepath, history in edit_history.items():
            if len(history) < 3:  # Need at least 3 edits to detect oscillation
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
            if re.search(pattern, prompt_lower, re.IGNORECASE):
                return True
        return False

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
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
    cooldown_turns: int = 2
    # More specific patterns to reduce false positives
    # Removed: r"\?$" (too broad - catches all questions)
    # Removed: r"^(why|how|what|where|when|which|who)\b" (too broad - catches new questions)
    patterns: list = field(
        default_factory=lambda: [
            # Follow-up starters (continuing previous topic)
            r"^(but |and |also |what about|how about|can you also)",
            r"^(so |then |ok so |okay so )",
            r"^(wait|hold on|actually)",
            # Clarification requests
            r"\bwhat do you mean\b",
            r"\bcan you (explain|clarify|elaborate)",
            r"\bwhat('s| is) (that|this)\b",
            r"\bi (don't understand|still don't|am confused)",
            # Dissatisfaction signals
            r"\bthat doesn't (work|help|answer|make sense)",
            r"\bthat's (not|wrong|incorrect)",
            r"^(no|nope),? (that|it|this)",
            # Incompleteness signals
            r"\byou (didn't|forgot|missed|skipped)",
            r"\bwhat about the\b",
        ]
    )

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        prompt = context.get("prompt", "").lower().strip()
        # Only trigger on short-to-medium prompts (follow-ups are usually brief)
        if len(prompt) > 200 or len(prompt) < 5:
            return False
        for pattern in self.patterns:
            if re.search(pattern, prompt, re.IGNORECASE):
                return True
        return False


# =============================================================================
# BAD BEHAVIOR REDUCERS (Anti-patterns we never want to see)
# =============================================================================


@dataclass
class BackupFileReducer(ConfidenceReducer):
    """Triggers when creating backup files (technical debt)."""

    name: str = "backup_file"
    delta: int = -10
    description: str = "Created backup file (technical debt)"
    cooldown_turns: int = 1
    patterns: list = field(
        default_factory=lambda: [
            r"\.bak$",
            r"\.backup$",
            r"_backup\.",
            r"\.old$",
            r"_old\.",
            r"\.orig$",
        ]
    )

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        file_path = context.get("file_path", "")
        if not file_path:
            return False
        for pattern in self.patterns:
            if re.search(pattern, file_path, re.IGNORECASE):
                return True
        return False


@dataclass
class VersionFileReducer(ConfidenceReducer):
    """Triggers when creating versioned files instead of editing in place."""

    name: str = "version_file"
    delta: int = -10
    description: str = "Created versioned file (technical debt)"
    cooldown_turns: int = 1
    patterns: list = field(
        default_factory=lambda: [
            r"_v\d+\.",  # file_v2.py
            r"_new\.",  # file_new.py
            r"_copy\.",  # file_copy.py
            r"_updated\.",  # file_updated.py
            r"_fixed\.",  # file_fixed.py
            r"\.\d+\.",  # file.2.py
        ]
    )

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        file_path = context.get("file_path", "")
        if not file_path:
            return False
        for pattern in self.patterns:
            if re.search(pattern, file_path, re.IGNORECASE):
                return True
        return False


@dataclass
class MarkdownCreationReducer(ConfidenceReducer):
    """Triggers when creating markdown files (documentation theater)."""

    name: str = "markdown_creation"
    delta: int = -8
    description: str = "Created markdown file (documentation theater)"
    cooldown_turns: int = 1
    # Exempt paths where markdown is acceptable
    exempt_paths: list = field(
        default_factory=lambda: [
            r"\.claude/memory/",  # Memory files OK
            r"\.claude/skills/",  # Skills OK
            r"/docs?/",  # Explicit docs folders OK
            r"README\.md$",  # README OK if explicitly requested
        ]
    )

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        file_path = context.get("file_path", "")
        if not file_path or not file_path.endswith(".md"):
            return False
        # Check if exempt
        for exempt in self.exempt_paths:
            if re.search(exempt, file_path, re.IGNORECASE):
                return False
        # Only trigger on Write (creation), not Edit
        tool_name = context.get("tool_name", "")
        return tool_name == "Write"


@dataclass
class OverconfidentCompletionReducer(ConfidenceReducer):
    """Triggers on '100% done' or similar overconfident claims."""

    name: str = "overconfident_completion"
    delta: int = -15
    description: str = "Claimed '100% done' or similar overconfidence"
    cooldown_turns: int = 3
    patterns: list = field(
        default_factory=lambda: [
            r"\b100%\s*(done|complete|finished|ready)\b",
            r"\bcompletely\s+(done|finished|ready)\b",
            r"\bperfectly\s+(done|finished|working)\b",
            r"\bfully\s+complete[d]?\b",
            r"\bnothing\s+(left|more|else)\s+to\s+(do|fix|change)\b",
        ]
    )

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        output = context.get("assistant_output", "")
        if not output:
            return False
        for pattern in self.patterns:
            if re.search(pattern, output, re.IGNORECASE):
                return True
        return False


@dataclass
class DeferralReducer(ConfidenceReducer):
    """Triggers on 'skip for now', 'come back later' deferral patterns."""

    name: str = "deferral"
    delta: int = -12
    description: str = "Deferred work ('skip for now', 'come back later')"
    cooldown_turns: int = 3
    patterns: list = field(
        default_factory=lambda: [
            r"\bskip\s+(this\s+)?(for\s+)?now\b",
            r"\bcome\s+back\s+(to\s+(this|it)\s+)?later\b",
            r"\bdo\s+(this|it)\s+later\b",
            r"\bleave\s+(this|it)\s+for\s+(now|later)\b",
            r"\bwe\s+can\s+(do|address|handle)\s+(this|it)\s+later\b",
            r"\bpostpone\b",
            r"\bdefer\s+(this|it)\b",
            r"\bput\s+(this|it)\s+off\b",
            r"\btable\s+(this|it)\s+for\s+now\b",
        ]
    )

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        output = context.get("assistant_output", "")
        if not output:
            return False
        for pattern in self.patterns:
            if re.search(pattern, output, re.IGNORECASE):
                return True
        return False


@dataclass
class ApologeticReducer(ConfidenceReducer):
    """Triggers on apologetic language ('sorry', 'my mistake')."""

    name: str = "apologetic"
    delta: int = -5
    description: str = "Used apologetic language (banned)"
    cooldown_turns: int = 2
    patterns: list = field(
        default_factory=lambda: [
            r"\b(i'?m\s+)?sorry\b",
            r"\bmy\s+(mistake|bad|apologies|fault)\b",
            r"\bi\s+apologize\b",
            r"\bapologies\s+for\b",
            r"\bpardon\s+(me|my)\b",
        ]
    )

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        output = context.get("assistant_output", "")
        if not output:
            return False
        for pattern in self.patterns:
            if re.search(pattern, output, re.IGNORECASE):
                return True
        return False


@dataclass
class SycophancyReducer(ConfidenceReducer):
    """Triggers on sycophantic agreement patterns."""

    name: str = "sycophancy"
    delta: int = -8
    description: str = "Sycophantic agreement ('you're absolutely right')"
    cooldown_turns: int = 2
    patterns: list = field(
        default_factory=lambda: [
            r"\byou'?re\s+(absolutely|totally|completely|entirely)\s+right\b",
            r"\babsolutely\s+right\b",
            r"\byou'?re\s+right,?\s+(i|my)\b",  # "you're right, I should..."
            r"\bthat'?s\s+(absolutely|totally|completely)\s+(correct|true|right)\b",
            r"\bgreat\s+(point|observation|catch)\b",
            r"\bexcellent\s+(point|observation|catch)\b",
        ]
    )

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        output = context.get("assistant_output", "")
        if not output:
            return False
        for pattern in self.patterns:
            if re.search(pattern, output, re.IGNORECASE):
                return True
        return False


@dataclass
class UnresolvedAntiPatternReducer(ConfidenceReducer):
    """Triggers when mentioning anti-patterns without resolving them."""

    name: str = "unresolved_antipattern"
    delta: int = -10
    description: str = "Identified anti-pattern without resolution"
    cooldown_turns: int = 3
    # Anti-pattern mentions
    antipattern_signals: list = field(
        default_factory=lambda: [
            r"\banti-?pattern\b",
            r"\bcode\s+smell\b",
            r"\btechnical\s+debt\b",
            r"\bbad\s+practice\b",
            r"\bshould\s+(be\s+)?(refactor|fix|change|update)ed\b",
            r"\bneeds\s+(to\s+be\s+)?(refactor|fix|clean)ed\b",
        ]
    )
    # Resolution signals (if present, don't trigger)
    resolution_signals: list = field(
        default_factory=lambda: [
            r"\bfixed\b",
            r"\bresolved\b",
            r"\brefactored\b",
            r"\bupdated\b",
            r"\bchanged\b",
            r"\bhere'?s\s+(the|a)\s+fix\b",
            r"\blet\s+me\s+fix\b",
            r"\bi'?ll\s+fix\b",
        ]
    )

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        output = context.get("assistant_output", "")
        if not output:
            return False
        # Check if anti-pattern mentioned
        has_antipattern = any(
            re.search(p, output, re.IGNORECASE) for p in self.antipattern_signals
        )
        if not has_antipattern:
            return False
        # Check if resolution also mentioned (within same output)
        has_resolution = any(
            re.search(p, output, re.IGNORECASE) for p in self.resolution_signals
        )
        # Only trigger if anti-pattern mentioned WITHOUT resolution
        return not has_resolution


@dataclass
class DebtBashReducer(ConfidenceReducer):
    """Triggers on bash commands that create technical debt."""

    name: str = "debt_bash"
    delta: int = -10
    description: str = "Ran debt-creating bash command"
    cooldown_turns: int = 1
    # Commands that create debt or are dangerous
    debt_patterns: list = field(
        default_factory=lambda: [
            r"--force\b",
            r"-f\b.*(?:rm|git|npm)",  # Force flags
            r"git\s+reset\s+--hard",
            r"git\s+push\s+--force",
            r"git\s+push\s+-f\b",
            r"npm\s+audit\s+fix\s+--force",
            r"rm\s+-rf\s+/",  # Dangerous rm
            r"chmod\s+777",
            r">\s*/dev/null\s+2>&1",  # Suppressing errors
            r"\|\|\s*true\b",  # Ignoring failures
            r"--no-verify",
            r"--skip-",
            r"DISABLE_",
        ]
    )

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        command = context.get("bash_command", "")
        if not command:
            return False
        for pattern in self.debt_patterns:
            if re.search(pattern, command, re.IGNORECASE):
                return True
        return False


@dataclass
class LargeDiffReducer(ConfidenceReducer):
    """Triggers when diffs exceed 400 LOC - risky large changes."""

    name: str = "large_diff"
    delta: int = -8
    description: str = "Large diff (>400 LOC) - risky change"
    cooldown_turns: int = 1

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        return context.get("large_diff", False)


@dataclass
class HookBlockReducer(ConfidenceReducer):
    """Triggers when a hook blocks (soft or hard)."""

    name: str = "hook_block"
    delta: int = -5
    description: str = "Hook blocked action (soft/hard)"
    cooldown_turns: int = 1

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        return context.get("hook_blocked", False)


# Registry of all reducers
# All reducers now ENABLED with proper detection mechanisms
REDUCERS: list[ConfidenceReducer] = [
    # Core reducers (existing)
    ToolFailureReducer(),
    CascadeBlockReducer(),
    SunkCostReducer(),
    UserCorrectionReducer(),
    GoalDriftReducer(),  # Uses semantic keyword extraction from file paths
    EditOscillationReducer(),
    ContradictionReducer(),  # Uses pattern matching for user-reported contradictions
    FollowUpQuestionReducer(),
    # Bad behavior reducers (new)
    BackupFileReducer(),  # Technical debt: .bak, .backup, .old files
    VersionFileReducer(),  # Technical debt: _v2, _new, _copy files
    MarkdownCreationReducer(),  # Documentation theater (except memory/skills/docs)
    OverconfidentCompletionReducer(),  # "100% done" claims
    DeferralReducer(),  # "skip for now", "come back later"
    ApologeticReducer(),  # "sorry", "my mistake"
    SycophancyReducer(),  # "you're absolutely right"
    UnresolvedAntiPatternReducer(),  # Mentioning issues without fixing
    DebtBashReducer(),  # --force, --hard, --no-verify commands
    LargeDiffReducer(),  # Diffs > 400 LOC
    HookBlockReducer(),  # Soft/hard hook blocks
]


# =============================================================================
# RATE LIMITING (prevents death spirals)
# =============================================================================

# Maximum confidence change per turn (prevents compound penalty death spirals)
MAX_CONFIDENCE_DELTA_PER_TURN = 15

# Mean reversion target (confidence drifts toward this when no strong signals)
MEAN_REVERSION_TARGET = 70
MEAN_REVERSION_RATE = 0.1  # Pull 10% toward target per idle period


# =============================================================================
# INCREASER REGISTRY
# =============================================================================


@dataclass
class ConfidenceIncreaser:
    """A confidence increaser that fires on success signals."""

    name: str
    delta: int  # Positive value
    description: str
    requires_approval: bool = False
    cooldown_turns: int = 1

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        """Check if this increaser should fire. Override in subclasses."""
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        return False


@dataclass
class TestPassIncreaser(ConfidenceIncreaser):
    """Triggers when tests pass."""

    name: str = "test_pass"
    delta: int = 5
    description: str = "Tests passed successfully"
    requires_approval: bool = False
    cooldown_turns: int = 1

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        # Check context from post_tool_use_runner (output-based detection)
        if context.get("tests_passed"):
            return True
        # Check recent commands for test passes
        for cmd in state.commands_succeeded[-5:]:
            cmd_str = cmd.get("command", "").lower()
            output = cmd.get("output", "").lower()
            # Command-based: actual test runners
            if any(t in cmd_str for t in ["pytest", "jest", "cargo test", "npm test"]):
                return True
            # Output-based: success patterns in output
            if any(p in output for p in ["passed", "tests passed", "success", "✓"]):
                return True
        return False


@dataclass
class BuildSuccessIncreaser(ConfidenceIncreaser):
    """Triggers when builds succeed."""

    name: str = "build_success"
    delta: int = 5
    description: str = "Build completed successfully"
    requires_approval: bool = False
    cooldown_turns: int = 1
    # Strict patterns - must be actual build commands, not substrings
    build_commands: list = field(
        default_factory=lambda: [
            "npm run build",
            "npm build",
            "yarn build",
            "pnpm build",
            "cargo build",
            "cargo test",  # Rust tests are builds
            "go build",
            "go test",
            "tsc",
            "webpack",
            "vite build",
            "next build",
            "make all",
            "make build",
            "cmake --build",
            "gradle build",
            "mvn package",
            "dotnet build",
        ]
    )

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        # Check context from post_tool_use_runner (output-based detection)
        if context.get("build_succeeded"):
            return True
        # Check recent commands for builds
        for cmd in state.commands_succeeded[-5:]:
            cmd_str = cmd.get("command", "").lower()
            output = cmd.get("output", "").lower()
            # Command-based: actual build commands
            if any(
                cmd_str.startswith(t) or f" {t}" in cmd_str for t in self.build_commands
            ):
                return True
            # Output-based: build success patterns in output
            if any(p in output for p in ["built", "compiled", "build successful"]):
                return True
        return False


@dataclass
class UserOkIncreaser(ConfidenceIncreaser):
    """Triggers on positive user feedback.

    Reduced from +5 to +2: Generic politeness ("ok", "thanks") shouldn't
    inflate confidence as much as objective signals (tests, builds).
    For specific acceptance ("that fixed it"), user can say CONFIDENCE_BOOST_APPROVED.
    """

    name: str = "user_ok"
    delta: int = 2  # Reduced from 5 - generic politeness < objective signals
    description: str = "User confirmed correctness"
    requires_approval: bool = False
    cooldown_turns: int = 2
    patterns: list = field(
        default_factory=lambda: [
            r"\b(?:looks?\s+)?good\b",
            r"\bok(?:ay)?\b",
            r"\bcorrect\b",
            r"\bperfect\b",
            r"\bnice\b",
            r"\bthanks?\b",
            r"\byes\b",
        ]
    )

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        prompt = context.get("prompt", "").lower().strip()
        # Short positive responses only (avoid false positives in long prompts)
        # Allow up to 100 chars for "thanks, looks good - also check tests" type messages
        if len(prompt) > 100:
            return False
        for pattern in self.patterns:
            if re.search(pattern, prompt, re.IGNORECASE):
                return True
        return False


@dataclass
class TrustRegainedIncreaser(ConfidenceIncreaser):
    """Triggers on explicit trust restoration request (requires approval)."""

    name: str = "trust_regained"
    delta: int = 15
    description: str = "User explicitly restored trust"
    requires_approval: bool = True
    cooldown_turns: int = 5
    trigger_patterns: list = field(
        default_factory=lambda: [
            r"\btrust\s+regained\b",
            r"\bconfidence\s+(?:restored|boost(?:ed)?)\b",
            r"\bCONFIDENCE_BOOST_APPROVED\b",
        ]
    )

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        prompt = context.get("prompt", "")
        for pattern in self.trigger_patterns:
            if re.search(pattern, prompt, re.IGNORECASE):
                return True
        return False


# =============================================================================
# NATURAL INCREASERS (balance the natural decay)
# =============================================================================


@dataclass
class FileReadIncreaser(ConfidenceIncreaser):
    """Triggers on file reads - gathering evidence increases confidence."""

    name: str = "file_read"
    delta: int = 1
    description: str = "Gathered evidence by reading files"
    requires_approval: bool = False
    cooldown_turns: int = 0  # Can fire every turn

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        # Check if files were read this turn
        files_read_count = context.get("files_read_count", 0)
        return files_read_count > 0


@dataclass
class ResearchIncreaser(ConfidenceIncreaser):
    """Triggers on web research - due diligence increases confidence."""

    name: str = "research"
    delta: int = 2
    description: str = "Performed web research"
    requires_approval: bool = False
    cooldown_turns: int = 1

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        # Check for research tools used
        return context.get("research_performed", False)


@dataclass
class AskUserIncreaser(ConfidenceIncreaser):
    """Triggers when asking user for clarification - epistemic humility."""

    name: str = "ask_user"
    delta: int = 20  # Significant boost - consulting user is GOOD
    description: str = "Consulted user for clarification"
    requires_approval: bool = False
    cooldown_turns: int = 2

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        return context.get("asked_user", False)


@dataclass
class RulesUpdateIncreaser(ConfidenceIncreaser):
    """Triggers when updating CLAUDE.md or /rules - improving the system."""

    name: str = "rules_update"
    delta: int = 3
    description: str = "Updated system rules/documentation"
    requires_approval: bool = False
    cooldown_turns: int = 2

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        return context.get("rules_updated", False)


@dataclass
class CustomScriptIncreaser(ConfidenceIncreaser):
    """Triggers when running custom ops scripts - HUGE boost for using tools."""

    name: str = "custom_script"
    delta: int = 5
    description: str = "Ran custom ops script"
    requires_approval: bool = False
    cooldown_turns: int = 1

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        return context.get("custom_script_ran", False)


@dataclass
class LintPassIncreaser(ConfidenceIncreaser):
    """Triggers when linting passes."""

    name: str = "lint_pass"
    delta: int = 3
    description: str = "Lint check passed"
    requires_approval: bool = False
    cooldown_turns: int = 1

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        if context.get("lint_passed"):
            return True
        # Check recent commands
        for cmd in state.commands_succeeded[-3:]:
            cmd_str = cmd.get("command", "").lower()
            if any(t in cmd_str for t in ["ruff check", "eslint", "clippy", "pylint"]):
                return True
        return False


@dataclass
class MemoryConsultIncreaser(ConfidenceIncreaser):
    """Triggers when consulting memory files - leveraging accumulated knowledge."""

    name: str = "memory_consult"
    delta: int = 10
    description: str = "Consulted persistent memory"
    requires_approval: bool = False
    cooldown_turns: int = 2

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        return context.get("memory_consulted", False)


@dataclass
class BeadCreateIncreaser(ConfidenceIncreaser):
    """Triggers when creating beads - planning and tracking work."""

    name: str = "bead_create"
    delta: int = 10
    description: str = "Created task tracking bead"
    requires_approval: bool = False
    cooldown_turns: int = 1

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        return context.get("bead_created", False)


@dataclass
class SearchToolIncreaser(ConfidenceIncreaser):
    """Triggers when using search tools - gathering understanding."""

    name: str = "search_tool"
    delta: int = 2
    description: str = "Used search tool (Grep/Glob/Task)"
    requires_approval: bool = False
    cooldown_turns: int = 1

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        return context.get("search_performed", False)


@dataclass
class ProductiveBashIncreaser(ConfidenceIncreaser):
    """Triggers on productive, non-risky bash commands."""

    name: str = "productive_bash"
    delta: int = 1
    description: str = "Ran productive bash command"
    requires_approval: bool = False
    cooldown_turns: int = 1
    # Non-risky productive commands
    productive_patterns: list = field(
        default_factory=lambda: [
            r"^ls\b",
            r"^pwd$",
            r"^which\b",
            r"^type\b",
            r"^file\b",
            r"^wc\b",
            r"^du\b",
            r"^df\b",
            r"^env\b",
            r"^echo\s+\$",  # Variable inspection
            r"^cat\b.*\|\s*(head|tail|grep)",  # Piped inspection
            r"^tree\b",
            r"^find\b.*-name",  # Finding files
            r"^stat\b",
        ]
    )

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        return context.get("productive_bash", False)


@dataclass
class SmallDiffIncreaser(ConfidenceIncreaser):
    """Triggers when diffs are under 400 LOC - focused changes."""

    name: str = "small_diff"
    delta: int = 3
    description: str = "Small diff (<400 LOC) - focused change"
    requires_approval: bool = False
    cooldown_turns: int = 1

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        return context.get("small_diff", False)


@dataclass
class GitExploreIncreaser(ConfidenceIncreaser):
    """Triggers when exploring git history - understanding context."""

    name: str = "git_explore"
    delta: int = 10
    description: str = "Explored git history/state"
    requires_approval: bool = False
    cooldown_turns: int = 2

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        return context.get("git_explored", False)


@dataclass
class GitCommitIncreaser(ConfidenceIncreaser):
    """Triggers when committing with a message - saving work."""

    name: str = "git_commit"
    delta: int = 3
    description: str = "Committed work with message"
    requires_approval: bool = False
    cooldown_turns: int = 1

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        return context.get("git_committed", False)


# Registry of all increasers
INCREASERS: list[ConfidenceIncreaser] = [
    # High-value context gathering (+10)
    MemoryConsultIncreaser(),
    BeadCreateIncreaser(),
    GitExploreIncreaser(),
    GitCommitIncreaser(),  # Saving work (+3)
    # Objective signals (high value)
    TestPassIncreaser(),
    BuildSuccessIncreaser(),
    LintPassIncreaser(),
    CustomScriptIncreaser(),
    SmallDiffIncreaser(),  # Small focused changes (+3)
    # Due diligence signals
    FileReadIncreaser(),
    ResearchIncreaser(),
    RulesUpdateIncreaser(),
    SearchToolIncreaser(),  # Grep/Glob/Task (+2)
    ProductiveBashIncreaser(),  # Non-risky bash (+1)
    # User interaction
    AskUserIncreaser(),
    UserOkIncreaser(),
    TrustRegainedIncreaser(),
]


def get_confidence_recovery_options(current_confidence: int, target: int = 70) -> str:
    """Generate full ledger of ways to recover confidence.

    Called by any gate that blocks on confidence to show ALL options,
    not just one tunnel-vision path.

    Args:
        current_confidence: Current confidence level
        target: Target confidence needed (default 70 for production)

    Returns:
        Formatted string showing all confidence recovery options
    """
    deficit = target - current_confidence
    if deficit <= 0:
        return ""

    lines = [
        f"**Current**: {current_confidence}% | **Need**: {target}% | **Gap**: {deficit}",
        "",
        "**Ways to earn confidence:**",
    ]

    # Objective signals (highest value)
    lines.append("```")
    lines.append("📈 +5  test_pass      pytest | jest | cargo test | npm test")
    lines.append("📈 +5  build_success  npm build | cargo build | tsc | make")
    lines.append("📈 +5  custom_script  ~/.claude/ops/* (audit, void, think, etc)")
    lines.append("📈 +3  lint_pass      ruff check | eslint | cargo clippy")
    lines.append("```")

    # Due diligence signals
    lines.append("")
    lines.append("**Due diligence (natural balance to decay):**")
    lines.append("```")
    lines.append("📈 +1  file_read      Read files to gather evidence")
    lines.append("📈 +2  research       WebSearch | WebFetch | crawl4ai")
    lines.append("📈 +3  rules_update   Edit CLAUDE.md or /rules/")
    lines.append("```")

    # Context-building signals (high value)
    lines.append("")
    lines.append("**Context-building (+10 each):**")
    lines.append("```")
    lines.append("📈 +10 memory_consult Read ~/.claude/memory/ files")
    lines.append("📈 +10 bead_create    bd create | bd update (task tracking)")
    lines.append("📈 +10 git_explore    git log | git diff | git status | git show")
    lines.append("```")

    # User interaction (highest)
    lines.append("")
    lines.append("**User interaction:**")
    lines.append("```")
    lines.append("📈 +20 ask_user       AskUserQuestion (epistemic humility)")
    lines.append("📈 +2  user_ok        Short positive feedback (ok, thanks)")
    lines.append("📈 +15 trust_regained CONFIDENCE_BOOST_APPROVED")
    lines.append("```")

    # Bypass
    lines.append("")
    lines.append("**Bypass**: Say `SUDO` (logged) | `FP: <reducer>` to dispute")

    return "\n".join(lines)


# =============================================================================
# CORE FUNCTIONS
# =============================================================================


def get_tier_info(confidence: int) -> tuple[str, str, str]:
    """
    Get confidence tier name, emoji, and description.

    Returns:
        Tuple[str, str, str]: (tier_name, emoji, description)
    """
    if TIER_IGNORANCE[0] <= confidence <= TIER_IGNORANCE[1]:
        return "IGNORANCE", TIER_EMOJI["IGNORANCE"], "Read/Research ONLY"
    elif TIER_HYPOTHESIS[0] <= confidence <= TIER_HYPOTHESIS[1]:
        return "HYPOTHESIS", TIER_EMOJI["HYPOTHESIS"], "Scratch only"
    elif TIER_WORKING[0] <= confidence <= TIER_WORKING[1]:
        return "WORKING", TIER_EMOJI["WORKING"], "Scratch + git read"
    elif TIER_CERTAINTY[0] <= confidence <= TIER_CERTAINTY[1]:
        return "CERTAINTY", TIER_EMOJI["CERTAINTY"], "Production with gates"
    elif TIER_TRUSTED[0] <= confidence <= TIER_TRUSTED[1]:
        return "TRUSTED", TIER_EMOJI["TRUSTED"], "Production with warnings"
    else:
        return "EXPERT", TIER_EMOJI["EXPERT"], "Maximum freedom"


def format_confidence_change(old: int, new: int, reason: str = "") -> str:
    """Format a confidence change for display."""
    delta = new - old
    sign = "+" if delta > 0 else ""
    old_tier, old_emoji, _ = get_tier_info(old)
    new_tier, new_emoji, _ = get_tier_info(new)

    msg = f"Confidence: {old_emoji}{old}% \u2192 {new_emoji}{new}% ({sign}{delta}"
    if reason:
        msg += f" {reason}"
    msg += ")"

    # Zone change alert
    if old_tier != new_tier:
        msg += f"\n\u26a0\ufe0f ZONE CHANGE: {old_tier} \u2192 {new_tier}"

    return msg


def should_require_research(confidence: int, context: dict) -> tuple[bool, str]:
    """
    Check if research should be required based on confidence.

    Returns:
        Tuple[bool, str]: (should_require, message)
    """
    if confidence >= THRESHOLD_REQUIRE_RESEARCH:
        return False, ""

    _, emoji, _ = get_tier_info(confidence)
    return True, (
        f"{emoji} **LOW CONFIDENCE: {confidence}%**\n"
        "Research is RECOMMENDED before proceeding.\n"
        "Use: /research, /docs, WebSearch, or mcp__pal__apilookup"
    )


def should_mandate_external(confidence: int) -> tuple[bool, str]:
    """
    Check if external LLM consultation is MANDATORY.

    Returns:
        Tuple[bool, str]: (is_mandatory, message)
    """
    if confidence >= THRESHOLD_MANDATORY_EXTERNAL:
        return False, ""

    _, emoji, _ = get_tier_info(confidence)
    return True, (
        f"{emoji} **CONFIDENCE CRITICALLY LOW: {confidence}% (IGNORANCE)**\n\n"
        "External consultation is **MANDATORY**. Pick one:\n"
        "1. `mcp__pal__thinkdeep` - Deep analysis via PAL MCP\n"
        "2. `/think` - Problem decomposition\n"
        "3. `/oracle` - Expert consultation\n"
        "4. `/research` - Verify with current docs\n\n"
        "Say **SUDO** to bypass (not recommended)."
    )


def check_tool_permission(
    confidence: int, tool_name: str, tool_input: dict
) -> tuple[bool, str]:
    """
    Check if a tool is permitted at current confidence level.

    Returns:
        Tuple[bool, str]: (is_permitted, block_message)
    """
    _, emoji, _ = get_tier_info(confidence)

    # Always-allowed tools (diagnostic, read-only)
    always_allowed = {
        "Read",
        "Grep",
        "Glob",
        "WebSearch",
        "WebFetch",
        "TodoRead",
        "AskUserQuestion",
    }
    if tool_name in always_allowed:
        return True, ""

    # External LLM tools always allowed (they're the escalation path)
    external_llm_tools = {
        "mcp__pal__thinkdeep",
        "mcp__pal__debug",
        "mcp__pal__codereview",
    }
    if tool_name.startswith("mcp__pal__") or tool_name in external_llm_tools:
        return True, ""

    # Task tool - allow read-only agent types
    if tool_name == "Task":
        read_only_agents = {
            "scout",
            "digest",
            "parallel",
            "explore",
            "chore",
            "plan",
            "claude-code-guide",
        }
        subagent_type = tool_input.get("subagent_type", "").lower()
        if subagent_type in read_only_agents:
            return True, ""

    # Check confidence-based restrictions
    file_path = tool_input.get("file_path", "")
    is_scratch = ".claude/tmp" in file_path or "/tmp/" in file_path
    is_production = not is_scratch and ".claude/" not in file_path

    # IGNORANCE (< 30): Only read-only tools - MUST consult external first
    if confidence < 30:
        if tool_name in {"Edit", "Write", "Bash", "NotebookEdit"}:
            recovery = get_confidence_recovery_options(confidence, target=30)
            return False, (
                f"{emoji} **BLOCKED: {tool_name}**\n"
                f"Confidence too low ({confidence}% IGNORANCE).\n\n"
                f"{recovery}"
            )

    # HYPOTHESIS (30-50): Scratch only - SHOULD consult external
    elif confidence < 51:
        if tool_name in {"Edit", "Write"} and not is_scratch:
            recovery = get_confidence_recovery_options(confidence, target=51)
            return False, (
                f"{emoji} **BLOCKED: {tool_name}** to production\n"
                f"Confidence ({confidence}% HYPOTHESIS) only allows scratch writes.\n"
                f"Write to `~/.claude/tmp/` for scratch, or earn confidence:\n\n"
                f"{recovery}"
            )
        if tool_name == "Bash":
            command = tool_input.get("command", "").lower()
            risky_patterns = ["git push", "git commit", "rm -rf", "deploy", "kubectl"]
            if any(p in command for p in risky_patterns):
                recovery = get_confidence_recovery_options(confidence, target=51)
                return False, (
                    f"{emoji} **BLOCKED: Risky Bash command**\n"
                    f"Confidence ({confidence}% HYPOTHESIS) blocks production commands.\n\n"
                    f"{recovery}"
                )

    # WORKING (51-70): Production with quality gates suggested
    elif confidence < 71:
        if tool_name in {"Edit", "Write"} and is_production:
            # Allow but suggest gates - this is advisory not blocking
            pass  # Enforcement via pre_tool_use advisory messages

    # CERTAINTY (71-85): Production allowed, gates enforced by pre_tool_use
    # TRUSTED (86-94): Production allowed, warnings only
    # EXPERT (95-100): Maximum freedom

    return True, ""


def suggest_alternatives(confidence: int, task_description: str = "") -> str:
    """
    Suggest alternative approaches based on confidence level.

    Lower confidence = more alternatives suggested.
    """
    if confidence >= 50:
        return ""

    alternatives = []

    # At IGNORANCE, suggest 2-3 alternatives
    if confidence < 30:
        alternatives = [
            "\U0001f4a1 **Alternative Approaches** (confidence critically low):",
            "1. **Research first**: Use /research, /docs, or WebSearch",
            "2. **External consultation**: mcp__pal__thinkdeep or /oracle",
            "3. **Decompose problem**: /think to break down the task",
        ]
    # At HYPOTHESIS, suggest 1-2 alternatives
    elif confidence < 50:
        alternatives = [
            "\U0001f4a1 **Consider**:",
            "1. **Research**: Verify approach with /research or /docs",
            "2. **Consultation**: Quick check with /oracle if uncertain",
        ]

    return "\n".join(alternatives)


def assess_prompt_complexity(prompt: str) -> tuple[int, list[str]]:
    """
    Assess prompt complexity and return initial confidence adjustment.

    Returns:
        Tuple[int, list[str]]: (confidence_delta, reasons)
    """
    delta = 0
    reasons = []

    prompt_lower = prompt.lower()

    # Complexity indicators (reduce confidence)
    complexity_patterns = [
        (r"\b(complex|complicated|difficult|tricky)\b", -10, "complex task indicated"),
        (r"\b(refactor|rewrite|overhaul|redesign)\b", -8, "major refactoring"),
        (r"\b(async|concurrent|parallel|thread)\b", -5, "concurrency involved"),
        (r"\b(security|auth|crypto|encrypt)\b", -5, "security-sensitive"),
        (r"\b(database|sql|migration)\b", -5, "database operations"),
        (r"\b(deploy|production|live)\b", -8, "production impact"),
    ]

    for pattern, adj, reason in complexity_patterns:
        if re.search(pattern, prompt_lower):
            delta += adj
            reasons.append(reason)

    # Familiarity indicators (increase confidence)
    familiarity_patterns = [
        (r"\b(simple|easy|quick|small)\b", 5, "simple task"),
        (r"\b(fix typo|rename|update comment)\b", 10, "trivial change"),
    ]

    for pattern, adj, reason in familiarity_patterns:
        if re.search(pattern, prompt_lower):
            delta += adj
            reasons.append(reason)

    return delta, reasons


# =============================================================================
# RATE LIMITING HELPERS
# =============================================================================


def apply_rate_limit(delta: int, state: "SessionState") -> int:
    """Apply rate limiting to prevent death spirals.

    Caps the maximum confidence change per turn and tracks cumulative
    changes to prevent compound penalties from destroying confidence.

    Returns the clamped delta.
    """
    # Track cumulative delta this turn
    turn_key = f"_confidence_delta_turn_{state.turn_count}"
    cumulative = state.nudge_history.get(turn_key, 0)

    # Calculate remaining budget
    if delta < 0:
        # For penalties, limit total negative change
        remaining = -MAX_CONFIDENCE_DELTA_PER_TURN - cumulative
        clamped = max(delta, remaining)
    else:
        # For boosts, limit total positive change
        remaining = MAX_CONFIDENCE_DELTA_PER_TURN - cumulative
        clamped = min(delta, remaining)

    # Update cumulative tracking
    state.nudge_history[turn_key] = cumulative + clamped

    # Cleanup stale turn keys (keep only last 10 turns to prevent unbounded growth)
    stale_keys = []
    for k in state.nudge_history:
        if k.startswith("_confidence_delta_turn_") and k != turn_key:
            try:
                turn_num = int(k.split("_")[-1])
                if turn_num < state.turn_count - 10:
                    stale_keys.append(k)
            except ValueError:
                stale_keys.append(k)  # Remove malformed keys
    for k in stale_keys:
        del state.nudge_history[k]

    return clamped


def apply_mean_reversion(confidence: int, idle_turns: int = 0) -> int:
    """Gently pull confidence toward baseline when no strong signals.

    Prevents getting stuck at extremes. Only applies after idle periods.
    """
    if idle_turns < 3:  # Need at least 3 idle turns
        return confidence

    # Calculate reversion amount
    distance = MEAN_REVERSION_TARGET - confidence
    reversion = int(distance * MEAN_REVERSION_RATE * idle_turns)

    # Cap at 5 per application
    reversion = max(-5, min(5, reversion))

    return confidence + reversion


# =============================================================================
# REDUCER/INCREASER APPLICATION
# =============================================================================


def apply_reducers(state: "SessionState", context: dict) -> list[tuple[str, int, str]]:
    """
    Apply all applicable reducers and return list of triggered ones.

    Returns:
        List of (reducer_name, delta, description) tuples
    """
    triggered = []

    # Get last trigger turns from state (stored in nudge_history)
    for reducer in REDUCERS:
        key = f"confidence_reducer_{reducer.name}"
        last_trigger = state.nudge_history.get(key, {}).get("last_turn", -999)

        if reducer.should_trigger(context, state, last_trigger):
            triggered.append((reducer.name, reducer.delta, reducer.description))
            # Record trigger
            if key not in state.nudge_history:
                state.nudge_history[key] = {}
            state.nudge_history[key]["last_turn"] = state.turn_count

    return triggered


def apply_increasers(
    state: "SessionState", context: dict
) -> list[tuple[str, int, str, bool]]:
    """
    Apply all applicable increasers and return list of triggered ones.

    Also handles Trust Debt decay: test_pass and build_success clear debt.

    Returns:
        List of (increaser_name, delta, description, requires_approval) tuples
    """
    triggered = []

    for increaser in INCREASERS:
        key = f"confidence_increaser_{increaser.name}"
        last_trigger = state.nudge_history.get(key, {}).get("last_turn", -999)

        if increaser.should_trigger(context, state, last_trigger):
            triggered.append(
                (
                    increaser.name,
                    increaser.delta,
                    increaser.description,
                    increaser.requires_approval,
                )
            )
            # Record trigger (only for non-approval-required)
            if not increaser.requires_approval:
                if key not in state.nudge_history:
                    state.nudge_history[key] = {}
                state.nudge_history[key]["last_turn"] = state.turn_count

                # Trust Debt decay: objective signals (test/build) clear debt
                if increaser.name in ("test_pass", "build_success"):
                    current_debt = getattr(state, "reputation_debt", 0)
                    if current_debt > 0:
                        state.reputation_debt = current_debt - 1

    return triggered


# =============================================================================
# FALSE POSITIVE DISPUTE SYSTEM
# =============================================================================

# Patterns that indicate user is disputing a confidence reduction
# Note: patterns are matched against lowercased prompt
DISPUTE_PATTERNS = [
    r"\bfalse\s+positive\b",
    r"\bfp\s*:\s*(\w+)\b",  # fp: reducer_name (lowercase)
    r"\bdispute\s+(\w+)\b",
    r"\bthat\s+(?:was|is)\s+wrong\b",
    r"\bshouldn'?t\s+have\s+(?:reduced|dropped)\b",
    r"\bwrongly\s+(?:reduced|penalized)\b",
    r"\blegitimate\s+(?:edit|change|work)\b",
    r"\bnot\s+(?:oscillating|spinning|stuck)\b",
]


def get_adaptive_cooldown(state: "SessionState", reducer_name: str) -> int:
    """Get adaptive cooldown for a reducer based on false positive history.

    High false positive rates increase cooldowns to reduce future triggers.
    """
    base_cooldown = next(
        (r.cooldown_turns for r in REDUCERS if r.name == reducer_name), 3
    )

    # Get FP count from state
    fp_key = f"reducer_fp_{reducer_name}"
    fp_count = state.nudge_history.get(fp_key, {}).get("count", 0)

    # Scale cooldown: each FP adds 50% more cooldown, max 3x
    if fp_count == 0:
        return base_cooldown

    multiplier = min(3.0, 1.0 + (fp_count * 0.5))
    return int(base_cooldown * multiplier)


def record_false_positive(state: "SessionState", reducer_name: str, reason: str = ""):
    """Record a false positive for adaptive learning.

    This increases future cooldowns for this reducer.
    """
    fp_key = f"reducer_fp_{reducer_name}"
    if fp_key not in state.nudge_history:
        state.nudge_history[fp_key] = {"count": 0, "reasons": []}

    state.nudge_history[fp_key]["count"] = (
        state.nudge_history[fp_key].get("count", 0) + 1
    )

    # Keep last 5 reasons for debugging
    if reason:
        reasons = state.nudge_history[fp_key].get("reasons", [])
        reasons.append(reason[:100])
        state.nudge_history[fp_key]["reasons"] = reasons[-5:]

    state.nudge_history[fp_key]["last_turn"] = state.turn_count


def dispute_reducer(
    state: "SessionState", reducer_name: str, reason: str = ""
) -> tuple[int, str]:
    """User disputes a confidence reduction as false positive.

    Returns:
        Tuple of (confidence_restored, message)
    """
    # Find the reducer
    reducer = next((r for r in REDUCERS if r.name == reducer_name), None)
    if not reducer:
        # Try fuzzy match
        for r in REDUCERS:
            if reducer_name.lower() in r.name.lower():
                reducer = r
                break

    if not reducer:
        return (
            0,
            f"Unknown reducer: {reducer_name}. Valid: {[r.name for r in REDUCERS]}",
        )

    # Record the false positive
    record_false_positive(state, reducer.name, reason)

    # Restore confidence
    restore_amount = abs(reducer.delta)
    fp_count = state.nudge_history.get(f"reducer_fp_{reducer.name}", {}).get("count", 1)
    new_cooldown = get_adaptive_cooldown(state, reducer.name)

    return restore_amount, (
        f"✅ **False Positive Recorded**: {reducer.name}\n"
        f"  • Confidence restored: +{restore_amount}\n"
        f"  • Total FPs for this reducer: {fp_count}\n"
        f"  • New adaptive cooldown: {new_cooldown} turns\n"
    )


def detect_dispute_in_prompt(prompt: str) -> tuple[bool, str, str]:
    """Detect if user is disputing a confidence reduction.

    Returns:
        Tuple of (is_dispute, reducer_name, reason)
    """
    prompt_lower = prompt.lower()

    for pattern in DISPUTE_PATTERNS:
        match = re.search(pattern, prompt_lower)
        if match:
            # Try to extract reducer name from match groups
            reducer_name = ""
            if match.groups():
                reducer_name = match.group(1)

            # If no reducer name in pattern, try to find it in prompt
            if not reducer_name:
                for reducer in REDUCERS:
                    if reducer.name in prompt_lower:
                        reducer_name = reducer.name
                        break

            # Extract reason (rest of prompt after pattern)
            reason = prompt[match.end() :].strip()[:100]

            return True, reducer_name, reason

    return False, "", ""


def get_recent_reductions(state: "SessionState", turns: int = 3) -> list[str]:
    """Get reducers that fired recently (for dispute context)."""
    recent = []
    current_turn = state.turn_count

    for reducer in REDUCERS:
        key = f"confidence_reducer_{reducer.name}"
        last_turn = state.nudge_history.get(key, {}).get("last_turn", -999)
        if current_turn - last_turn <= turns:
            recent.append(reducer.name)

    return recent


def format_dispute_instructions(reducer_names: list[str]) -> str:
    """Format instructions for disputing a reduction."""
    if not reducer_names:
        return ""

    reducers_str = ", ".join(reducer_names)
    return (
        f"\n💡 **False positive?** Options:\n"
        f"   • Claude: Run `~/.claude/ops/fp.py <reducer> [reason]`\n"
        f"   • User: Say `FP: <reducer>` or `dispute <reducer>`\n"
        f"   Recent reducers: {reducers_str}"
    )


def generate_approval_prompt(
    current_confidence: int, requested_delta: int, reasons: list[str]
) -> str:
    """Generate approval prompt for large confidence boosts."""
    new_confidence = min(100, current_confidence + requested_delta)
    old_tier, old_emoji, _ = get_tier_info(current_confidence)
    new_tier, new_emoji, _ = get_tier_info(new_confidence)

    # List what will be unlocked
    old_privs = TIER_PRIVILEGES.get(old_tier, {})
    new_privs = TIER_PRIVILEGES.get(new_tier, {})
    unlocks = []
    for priv, allowed in new_privs.items():
        if allowed and not old_privs.get(priv, False):
            unlocks.append(f"  \u2705 {priv.replace('_', ' ').title()}")

    unlock_str = "\n".join(unlocks) if unlocks else "  (no new permissions)"

    return (
        f"\U0001f50d **Confidence Boost Request**\n\n"
        f"Current: {old_emoji}{current_confidence}% {old_tier}\n"
        f"Proposed: {new_emoji}{new_confidence}% {new_tier} (+{requested_delta})\n\n"
        f"This will unlock:\n{unlock_str}\n\n"
        f"Reply: **CONFIDENCE_BOOST_APPROVED** to confirm"
    )


# =============================================================================
# ROCK BOTTOM REALIGNMENT
# =============================================================================

# Realignment questions to ask when at rock bottom
REALIGNMENT_QUESTIONS = [
    {
        "question": "What is the primary goal you want me to accomplish right now?",
        "header": "Goal",
        "options": [
            {
                "label": "Continue current task",
                "description": "Keep working on what we were doing",
            },
            {
                "label": "New task",
                "description": "Start fresh with a different objective",
            },
            {"label": "Debug/fix issues", "description": "Focus on resolving problems"},
        ],
    },
    {
        "question": "How should I approach this work?",
        "header": "Approach",
        "options": [
            {
                "label": "Careful & thorough",
                "description": "Take time, verify everything",
            },
            {
                "label": "Fast & iterative",
                "description": "Move quickly, fix issues as they come",
            },
            {
                "label": "Ask before acting",
                "description": "Check with you before each step",
            },
        ],
    },
    {
        "question": "What went wrong that led to this confidence drop?",
        "header": "Issue",
        "options": [
            {
                "label": "Misunderstood request",
                "description": "I wasn't clear on what you wanted",
            },
            {
                "label": "Technical errors",
                "description": "Code/commands failed repeatedly",
            },
            {"label": "Wrong approach", "description": "Strategy wasn't working"},
            {"label": "Nothing wrong", "description": "Confidence dropped unfairly"},
        ],
    },
]


def is_rock_bottom(confidence: int) -> bool:
    """Check if confidence is at rock bottom threshold."""
    return confidence <= THRESHOLD_ROCK_BOTTOM


def get_realignment_questions() -> list[dict]:
    """Get the realignment questions for AskUserQuestion tool."""
    return REALIGNMENT_QUESTIONS


def check_realignment_complete(state: "SessionState") -> bool:
    """Check if realignment has been completed this session."""
    return state.nudge_history.get("rock_bottom_realignment", {}).get(
        "completed", False
    )


def mark_realignment_complete(state: "SessionState") -> int:
    """Mark realignment as complete and return new confidence."""
    state.nudge_history["rock_bottom_realignment"] = {
        "completed": True,
        "turn": state.turn_count,
    }
    return ROCK_BOTTOM_RECOVERY_TARGET


def reset_realignment(state: "SessionState"):
    """Reset realignment tracking (called when confidence rises above rock bottom)."""
    if "rock_bottom_realignment" in state.nudge_history:
        state.nudge_history["rock_bottom_realignment"]["completed"] = False


# =============================================================================
# MEAN REVERSION INTEGRATION
# =============================================================================


def calculate_idle_reversion(
    confidence: int, last_activity_time: float, current_time: float
) -> tuple[int, str]:
    """Calculate mean reversion based on idle time.

    Returns:
        Tuple of (new_confidence, reason_message)
    """
    if last_activity_time <= 0:
        return confidence, ""

    idle_seconds = current_time - last_activity_time
    idle_minutes = idle_seconds / 60

    # Only apply after 5 minutes of idle time
    if idle_minutes < 5:
        return confidence, ""

    # Calculate idle periods (each 5-minute block counts as 1 idle turn)
    idle_turns = int(idle_minutes / 5)

    # Apply mean reversion
    new_confidence = apply_mean_reversion(confidence, idle_turns)

    if new_confidence != confidence:
        delta = new_confidence - confidence
        direction = "+" if delta > 0 else ""
        reason = (
            f"Mean reversion after {int(idle_minutes)}min idle ({direction}{delta})"
        )
        return new_confidence, reason

    return confidence, ""
