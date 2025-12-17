#!/usr/bin/env python3
"""
Confidence Reducers - Mechanical penalty signals.

Reducers fire WITHOUT judgment based on specific signals.
Each reducer has a cooldown to prevent spam.
"""

import re
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from session_state import SessionState


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
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        prompt = context.get("prompt", "").lower()
        for pattern in self.patterns:
            if re.search(pattern, prompt):
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
            if re.search(pattern, prompt_lower):
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
    """Triggers when creating NEW markdown files (documentation theater).

    Does NOT trigger when editing existing markdown files (Write to file
    that was previously read is an edit, not creation).
    """

    name: str = "markdown_creation"
    delta: int = -8
    description: str = "Created markdown file (documentation theater)"
    cooldown_turns: int = 1
    # Exempt paths where markdown is acceptable
    exempt_paths: list = field(
        default_factory=lambda: [
            r"\.claude/memory/",  # Memory files OK
            r"\.claude/skills/",  # Skills OK
            r"\.claude/commands/",  # Slash commands OK
            r"\.serena/memories/",  # Serena memories OK
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
        if tool_name != "Write":
            return False
        # If file was read first, this is an edit not creation
        files_read = getattr(state, "files_read", [])
        if file_path in files_read:
            return False  # Editing existing file, not creating new
        return True


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
class SpottedIgnoredReducer(ConfidenceReducer):
    """Triggers when explicitly spotting issues but not fixing them.

    More severe than unresolved_antipattern because it demonstrates
    explicit awareness of the problem.
    """

    name: str = "spotted_ignored"
    delta: int = -15
    description: str = "Explicitly spotted issue but didn't fix it"
    cooldown_turns: int = 3
    # Explicit "I spotted this" patterns
    spotted_signals: list = field(
        default_factory=lambda: [
            r"\bi\s+(noticed|spotted|found|see|saw)\s+(a|an|the|that|this)\s+(bug|issue|problem|error)",
            r"\bthere'?s\s+(a|an)\s+(bug|issue|problem|error)\b",
            r"\bthis\s+(could|might|will)\s+cause\b",
            r"\bthis\s+(is|looks)\s+(broken|wrong|incorrect)\b",
            r"\bi\s+should\s+(note|mention|point\s+out)\b",
            r"\bworth\s+(noting|mentioning)\s+(that|:)",
            r"\bone\s+(issue|problem|concern)\s+(is|here|I\s+see)\b",
            r"\bpotential\s+(issue|problem|bug)\b.*\bbut\b",
            r"\brisk\s+(here|is)\b.*\bbut\b",
        ]
    )
    # Resolution signals - if present, don't trigger
    resolution_signals: list = field(
        default_factory=lambda: [
            r"\bfixing\s+(it|this|that)\b",
            r"\blet\s+me\s+fix\b",
            r"\bi'?ll\s+fix\b",
            r"\bhere'?s\s+(the|a)\s+fix\b",
            r"\bfixed\b",
            r"\bresolving\b",
            r"\baddressing\s+(it|this|that)\b",
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
        # Check if explicitly spotted
        has_spotted = any(
            re.search(p, output, re.IGNORECASE) for p in self.spotted_signals
        )
        if not has_spotted:
            return False
        # Check if resolution also mentioned
        has_resolution = any(
            re.search(p, output, re.IGNORECASE) for p in self.resolution_signals
        )
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
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        # Now requires 3+ consecutive (set by detection logic)
        return context.get("sequential_repetition_3plus", False)


@dataclass
class UnbackedVerificationClaimReducer(ConfidenceReducer):
    """Triggers when claiming verification without matching tool log.

    Detects "verification theater" - claims like "tests passed" or "lint clean"
    without corresponding tool execution in recent turns.
    """

    name: str = "unbacked_verification"
    delta: int = -15
    description: str = "Claimed verification without tool evidence"
    cooldown_turns: int = 3

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        return context.get("unbacked_verification", False)


@dataclass
class FixedWithoutChainReducer(ConfidenceReducer):
    """Triggers when claiming 'fixed' without causal chain.

    Requires: file write + verification step after the claim.
    Catches "Fixed it" claims when nothing changed or no verification attempted.
    """

    name: str = "fixed_without_chain"
    delta: int = -8
    description: str = "Claimed 'fixed' without write or verification"
    cooldown_turns: int = 3

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        return context.get("fixed_without_chain", False)


@dataclass
class GitSpamReducer(ConfidenceReducer):
    """Triggers when git commands are spammed without intervening writes.

    >3 git_explore commands within 5 turns with no file write = farming.
    """

    name: str = "git_spam"
    delta: int = -2
    description: str = "Git command spam (>3 in 5 turns without writes)"
    cooldown_turns: int = 5

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        return context.get("git_spam", False)


# =============================================================================
# CODE QUALITY REDUCERS (Catch incomplete/sloppy work)
# =============================================================================


@dataclass
class PlaceholderImplReducer(ConfidenceReducer):
    """Triggers when writing placeholder implementations.

    Catches incomplete work: pass, ..., NotImplementedError in new code.
    """

    name: str = "placeholder_impl"
    delta: int = -8
    description: str = "Placeholder implementation (incomplete work)"
    cooldown_turns: int = 1

    def _get_patterns(self) -> list:
        """Build patterns at runtime to avoid hook detection."""
        return [
            r"^\s*pass\s*$",  # bare pass
            r"^\s*\.\.\.\s*$",  # ellipsis
            r"raise\s+NotImplemented" + r"Error",  # split to avoid hook
            r"raise\s+NotImplemented\b",  # common typo
            r"#\s*TODO[:\s].*implement",
            r"#\s*FIXME[:\s].*implement",
        ]

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        # Check content being written/edited
        new_content = context.get("new_string", "") or context.get("content", "")
        if not new_content:
            return False
        # Only trigger on Write/Edit tools
        tool_name = context.get("tool_name", "")
        if tool_name not in ("Write", "Edit"):
            return False
        for pattern in self._get_patterns():
            if re.search(pattern, new_content, re.MULTILINE | re.IGNORECASE):
                return True
        return False


@dataclass
class SilentFailureReducer(ConfidenceReducer):
    """Triggers on silent exception swallowing.

    Catches: except: pass, except Exception: pass without logging/handling.
    """

    name: str = "silent_failure"
    delta: int = -8
    description: str = "Silent exception swallowing (error suppression)"
    cooldown_turns: int = 1
    patterns: list = field(
        default_factory=lambda: [
            r"except\s*:\s*pass",
            r"except\s+\w+\s*:\s*pass",
            r"except\s+Exception\s*:\s*pass",
            r"except\s+BaseException\s*:\s*pass",
            r"except\s*:\s*\.\.\.",
            r"except\s+\w+\s*:\s*\.\.\.",
        ]
    )

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        new_content = context.get("new_string", "") or context.get("content", "")
        if not new_content:
            return False
        tool_name = context.get("tool_name", "")
        if tool_name not in ("Write", "Edit"):
            return False
        for pattern in self.patterns:
            if re.search(pattern, new_content, re.IGNORECASE):
                return True
        return False


@dataclass
class HallmarkPhraseReducer(ConfidenceReducer):
    """Triggers on AI-speak hallmark phrases.

    Reduces LLM-typical filler: "certainly", "I'd be happy to", "absolutely".
    """

    name: str = "hallmark_phrase"
    delta: int = -3
    description: str = "AI-speak hallmark phrase"
    cooldown_turns: int = 2
    patterns: list = field(
        default_factory=lambda: [
            r"^certainly[,!]?\s",
            r"^absolutely[,!]?\s",
            r"^i'?d be happy to\b",
            r"^i'?d be glad to\b",
            r"^of course[,!]?\s+i",
            r"^great question[,!]",
            r"^excellent question[,!]",
            r"^that'?s a great\b",
            r"^i understand (?:your|that|the)\b",
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
        first_part = output[:150].lower().strip()
        for pattern in self.patterns:
            if re.search(pattern, first_part):
                return True
        return False


@dataclass
class ScopeCreepReducer(ConfidenceReducer):
    """Triggers when adding functionality beyond original request.

    Detects gold-plating and feature creep via context signals.
    """

    name: str = "scope_creep"
    delta: int = -8
    description: str = "Scope creep (adding unrequested functionality)"
    cooldown_turns: int = 3
    indicators: list = field(
        default_factory=lambda: [
            r"\bwhile\s+(?:i'?m|we'?re)\s+(?:at\s+it|here)\b",
            r"\bmight\s+as\s+well\b",
            r"\blet'?s\s+also\b",
            r"\bi'?ll\s+also\s+add\b",
            r"\bbonus[:\s]",
            r"\bextra\s+feature\b",
            r"\bwhile\s+i'?m\s+at\s+it\b",
            r"\badditionally,?\s+i'?(?:ll|ve)\b",
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
        output_lower = output.lower()
        for pattern in self.indicators:
            if re.search(pattern, output_lower):
                return True
        return False


@dataclass
class IncompleteRefactorReducer(ConfidenceReducer):
    """Triggers when refactoring is incomplete (partial rename/change).

    Detects when changes are made in some places but not all.
    Context-based: set by hooks when grep finds remaining instances.
    """

    name: str = "incomplete_refactor"
    delta: int = -10
    description: str = "Incomplete refactor (changes in some places but not all)"
    cooldown_turns: int = 3

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        # Set by hooks when detecting partial refactors
        return context.get("incomplete_refactor", False)


# =============================================================================
# TIME WASTER REDUCERS (Punish inefficient patterns)
# =============================================================================


@dataclass
class RereadUnchangedReducer(ConfidenceReducer):
    """Triggers when re-reading a file that hasn't changed since last read.

    Wastes time and tokens re-reading content already in context.
    """

    name: str = "reread_unchanged"
    delta: int = -3
    description: str = "Re-read unchanged file (already in context)"
    cooldown_turns: int = 1

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
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
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
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
    cooldown_turns: int = 2

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
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
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
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
    cooldown_turns: int = 3

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
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
class SequentialWhenParallelReducer(ConfidenceReducer):
    """Triggers on 3+ sequential single-tool messages when parallel was possible.

    Wastes tokens and time doing one thing at a time when multiple
    independent operations could run in parallel.
    """

    name: str = "sequential_when_parallel"
    delta: int = -2
    description: str = "Sequential single-tool calls (could parallelize)"
    cooldown_turns: int = 3

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        # Track consecutive single reads/searches (guard for mock states)
        return getattr(state, "consecutive_single_reads", 0) >= 3


@dataclass
class TestIgnoredReducer(ConfidenceReducer):
    """Triggers when test files are modified but tests aren't run.

    If you edit test_*.py or *.test.ts but don't run pytest/jest afterward,
    you're probably not verifying your changes.
    """

    name: str = "test_ignored"
    delta: int = -5
    description: str = "Modified test files without running tests"
    cooldown_turns: int = 5

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        # Context-based: hook sets this when test file edited without test run
        return context.get("test_ignored", False)


@dataclass
class ChangeWithoutTestReducer(ConfidenceReducer):
    """Triggers when production code changes without test coverage.

    Editing src/*.py without corresponding test_*.py existing or tests running
    indicates untested changes being made.
    """

    name: str = "change_without_test"
    delta: int = -3
    description: str = "Production code changed without test coverage"
    cooldown_turns: int = 5

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        # Context-based: hook sets this when prod code edited without tests
        return context.get("change_without_test", False)


# =============================================================================
# VERIFICATION BUNDLING REDUCER (v4.7)
# =============================================================================


VERIFICATION_THRESHOLD = 5  # Edits before verification required


@dataclass
class UnverifiedEditsReducer(ConfidenceReducer):
    """Triggers when too many consecutive edits without verification.

    Prevents edit spam without running tests/lint to validate changes.
    """

    name: str = "unverified_edits"
    delta: int = -5
    description: str = (
        f">{VERIFICATION_THRESHOLD} edits without verification (run tests/lint)"
    )
    cooldown_turns: int = 3

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False

        # Track consecutive edits without verification
        edits_key = "_consecutive_edits_without_verify"
        verify_tools = {"pytest", "jest", "cargo test", "ruff check", "eslint", "tsc"}

        tool_name = context.get("tool_name", "")
        command = (
            context.get("tool_input", {}).get("command", "")
            if tool_name == "Bash"
            else ""
        )

        # Check if this is a verification action
        is_verify = any(v in command.lower() for v in verify_tools)

        if is_verify:
            # Reset counter on verification
            state.nudge_history[edits_key] = 0
            return False

        if tool_name in ("Edit", "Write"):
            # Increment edit counter
            count = state.nudge_history.get(edits_key, 0) + 1
            state.nudge_history[edits_key] = count
            if count > VERIFICATION_THRESHOLD:
                return True

        return False


# =============================================================================
# AST-BASED CODE QUALITY REDUCERS (v4.7)
# =============================================================================


@dataclass
class DeepNestingReducer(ConfidenceReducer):
    """Triggers on deeply nested code (>4 levels).

    Deep nesting makes code hard to read and test.
    """

    name: str = "deep_nesting"
    delta: int = -3
    description: str = "Deep nesting (>4 levels) - hard to read/test"
    cooldown_turns: int = 2
    max_depth: int = 4

    def _get_max_depth(self, node, current: int = 0) -> int:
        """Recursively find maximum nesting depth."""
        import ast

        max_d = current
        nesting_nodes = (
            ast.If,
            ast.For,
            ast.While,
            ast.With,
            ast.Try,
            ast.ExceptHandler,
        )
        for child in ast.iter_child_nodes(node):
            if isinstance(child, nesting_nodes):
                max_d = max(max_d, self._get_max_depth(child, current + 1))
            else:
                max_d = max(max_d, self._get_max_depth(child, current))
        return max_d

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        import ast

        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        content = context.get("new_string", "") or context.get("content", "")
        file_path = context.get("file_path", "")
        if not content or not file_path.endswith(".py"):
            return False
        if context.get("tool_name", "") not in ("Write", "Edit"):
            return False
        try:
            tree = ast.parse(content)
            return self._get_max_depth(tree) > self.max_depth
        except SyntaxError:
            return False


@dataclass
class LongFunctionReducer(ConfidenceReducer):
    """Triggers on functions exceeding 80 lines.

    Long functions are hard to understand and test.
    """

    name: str = "long_function"
    delta: int = -5
    description: str = "Long function (>80 lines) - split into smaller units"
    cooldown_turns: int = 2
    max_lines: int = 80

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        import ast

        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        content = context.get("new_string", "") or context.get("content", "")
        file_path = context.get("file_path", "")
        if not content or not file_path.endswith(".py"):
            return False
        if context.get("tool_name", "") not in ("Write", "Edit"):
            return False
        try:
            tree = ast.parse(content)
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if hasattr(node, "end_lineno") and node.end_lineno:
                        func_lines = node.end_lineno - node.lineno + 1
                        if func_lines > self.max_lines:
                            return True
            return False
        except SyntaxError:
            return False


@dataclass
class MutableDefaultArgReducer(ConfidenceReducer):
    """Triggers on mutable default arguments (list/dict/set).

    Mutable defaults are shared across calls - a common Python gotcha.
    """

    name: str = "mutable_default_arg"
    delta: int = -5
    description: str = "Mutable default argument (list/dict/set) - Python gotcha"
    cooldown_turns: int = 1

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        import ast

        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        content = context.get("new_string", "") or context.get("content", "")
        file_path = context.get("file_path", "")
        if not content or not file_path.endswith(".py"):
            return False
        if context.get("tool_name", "") not in ("Write", "Edit"):
            return False
        try:
            tree = ast.parse(content)
            mutable_types = (ast.List, ast.Dict, ast.Set)
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    for default in node.args.defaults + node.args.kw_defaults:
                        if isinstance(default, mutable_types):
                            return True
            return False
        except SyntaxError:
            return False


@dataclass
class ImportStarReducer(ConfidenceReducer):
    """Triggers on 'from X import *' statements.

    Star imports pollute namespace and make dependencies unclear.
    """

    name: str = "import_star"
    delta: int = -3
    description: str = "Star import (from X import *) - pollutes namespace"
    cooldown_turns: int = 1

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        import ast

        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        content = context.get("new_string", "") or context.get("content", "")
        file_path = context.get("file_path", "")
        if not content or not file_path.endswith(".py"):
            return False
        if context.get("tool_name", "") not in ("Write", "Edit"):
            return False
        try:
            tree = ast.parse(content)
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    if node.names and node.names[0].name == "*":
                        return True
            return False
        except SyntaxError:
            return False


@dataclass
class BareRaiseReducer(ConfidenceReducer):
    """Triggers on 'raise' without exception outside except block.

    Bare raise outside except is a RuntimeError waiting to happen.
    """

    name: str = "bare_raise"
    delta: int = -3
    description: str = "Bare raise outside except block - will fail at runtime"
    cooldown_turns: int = 1

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        import ast

        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        content = context.get("new_string", "") or context.get("content", "")
        file_path = context.get("file_path", "")
        if not content or not file_path.endswith(".py"):
            return False
        if context.get("tool_name", "") not in ("Write", "Edit"):
            return False
        try:
            tree = ast.parse(content)
            # Find bare raises not inside except handlers
            for node in ast.walk(tree):
                if isinstance(node, ast.Raise) and node.exc is None:
                    # Check if inside an except handler by walking parents
                    # Simple heuristic: check if any ExceptHandler contains this raise
                    # This is imperfect but catches most cases
                    return True  # Conservative: flag for review
            return False
        except SyntaxError:
            return False


@dataclass
class CommentedCodeReducer(ConfidenceReducer):
    """Triggers on large blocks of commented-out code.

    Commented code is dead weight - delete it, git remembers.
    """

    name: str = "commented_code"
    delta: int = -5
    description: str = "Commented-out code block - delete it, git remembers"
    cooldown_turns: int = 2
    min_consecutive_lines: int = 5

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        content = context.get("new_string", "") or context.get("content", "")
        file_path = context.get("file_path", "")
        if not content or not file_path.endswith(".py"):
            return False
        if context.get("tool_name", "") not in ("Write", "Edit"):
            return False
        # Count consecutive comment lines that look like code
        lines = content.split("\n")
        consecutive = 0
        code_patterns = [
            "def ",
            "class ",
            "if ",
            "for ",
            "while ",
            "return ",
            "import ",
        ]
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("#"):
                comment_content = stripped[1:].strip()
                # Check if comment looks like code
                if any(comment_content.startswith(p) for p in code_patterns):
                    consecutive += 1
                    if consecutive >= self.min_consecutive_lines:
                        return True
                elif comment_content and not comment_content.startswith(("#", "!")):
                    # Non-empty comment, might be code
                    consecutive += 1
                else:
                    consecutive = 0
            else:
                consecutive = 0
        return False


# =============================================================================
# FRAMEWORK ALIGNMENT REDUCERS (v4.8) - Micro-signals for framework drift
# =============================================================================


@dataclass
class WebFetchOverCrawlReducer(ConfidenceReducer):
    """Triggers when using WebFetch instead of crawl4ai.

    crawl4ai bypasses bot detection and renders JavaScript.
    WebFetch is inferior for web scraping.
    """

    name: str = "webfetch_over_crawl"
    delta: int = -1
    description: str = "WebFetch used (prefer crawl4ai)"
    cooldown_turns: int = 0  # No cooldown - frequency is the point

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        tool_name = context.get("tool_name", "")
        return tool_name == "WebFetch"


@dataclass
class WebSearchBasicReducer(ConfidenceReducer):
    """Triggers when using basic WebSearch.

    crawl4ai.ddg_search is generally better for comprehensive results.
    """

    name: str = "websearch_basic"
    delta: int = -1
    description: str = "WebSearch used (prefer crawl4ai.ddg_search)"
    cooldown_turns: int = 0  # No cooldown - frequency is the point

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        tool_name = context.get("tool_name", "")
        return tool_name == "WebSearch"


@dataclass
class TodoWriteBypassReducer(ConfidenceReducer):
    """Triggers when using TodoWrite instead of beads.

    Beads persists across sessions and enables context recovery.
    TodoWrite is ephemeral and violates the beads rule.
    """

    name: str = "todowrite_bypass"
    delta: int = -2
    description: str = "TodoWrite used (beads required)"
    cooldown_turns: int = 0  # No cooldown - every use is a violation

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        tool_name = context.get("tool_name", "")
        return tool_name == "TodoWrite"


@dataclass
class RawSymbolHuntReducer(ConfidenceReducer):
    """Triggers when reading code files without serena activation.

    When .serena/ exists, symbolic tools should be used for code navigation.
    Reading entire files to find symbols is inefficient.
    """

    name: str = "raw_symbol_hunt"
    delta: int = -1
    description: str = "Reading code file without serena (use symbolic tools)"
    cooldown_turns: int = 0  # No cooldown - frequency is the point

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        # Check if serena is available but not activated
        if not context.get("serena_available", False):
            return False
        if context.get("serena_activated", False):
            return False

        tool_name = context.get("tool_name", "")
        file_path = context.get("file_path", "")

        if tool_name != "Read":
            return False

        # Only for code files
        code_extensions = (".py", ".ts", ".tsx", ".js", ".jsx", ".rs", ".go", ".java")
        return file_path.endswith(code_extensions)


@dataclass
class GrepOverSerenaReducer(ConfidenceReducer):
    """Triggers when using Grep on code when serena is active.

    Serena's search_for_pattern and find_symbol are more semantic.
    """

    name: str = "grep_over_serena"
    delta: int = -1
    description: str = "Grep on code (serena has semantic search)"
    cooldown_turns: int = 0  # No cooldown - frequency is the point

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        # Only if serena is activated
        if not context.get("serena_activated", False):
            return False

        tool_name = context.get("tool_name", "")
        if tool_name != "Grep":
            return False

        # Check if searching in code-heavy areas
        path = context.get("grep_path", "")
        code_indicators = ("/src/", "/lib/", ".py", ".ts", ".js", "/hooks/", "/ops/")
        return any(ind in path for ind in code_indicators)


@dataclass
class FileReeditReducer(ConfidenceReducer):
    """Triggers when re-editing a file already edited this session.

    Creates immediate friction on any re-edit. Stacks with edit_oscillation
    for repeated patterns. Signal: couldn't get it right the first time.

    EXEMPT: Framework DNA files (CLAUDE.md, /rules/) - iterative refinement expected.
    These files get +15 boost via rules_update, so net effect is still positive.
    """

    name: str = "file_reedit"
    delta: int = -2
    description: str = "Re-editing file (get it right first time)"
    cooldown_turns: int = 0  # No cooldown - every re-edit counts

    # Files exempt from re-edit penalty (iterative refinement expected)
    exempt_patterns: tuple = (
        "CLAUDE.md",
        "/rules/",
        "/.claude/rules/",
        "/plans/",  # Plan mode explicitly requires iterative plan file edits
        "/.claude/plans/",
    )

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        tool_name = context.get("tool_name", "")
        if tool_name not in ("Edit", "Write"):
            return False

        file_path = context.get("file_path", "")
        if not file_path:
            return False

        # Exempt framework DNA files - iterative refinement is expected
        if any(pattern in file_path for pattern in self.exempt_patterns):
            return False

        # Check if file was edited before this turn
        # NOTE: state_updater (priority 10) runs BEFORE this reducer (priority 12),
        # so the current edit is ALREADY in files_edited. We need count >= 2 to
        # detect a RE-edit (current + at least one previous).
        files_edited = getattr(state, "files_edited", [])
        edit_count = 0
        for entry in files_edited:
            if isinstance(entry, dict):
                if entry.get("path") == file_path:
                    edit_count += 1
            elif isinstance(entry, str) and entry == file_path:
                edit_count += 1

        # Trigger if this is 2nd+ edit (count >= 2 because current edit already added)
        return edit_count >= 2


@dataclass
class SequentialFileOpsReducer(ConfidenceReducer):
    """Triggers when doing 3+ file operations that could be parallelized.

    Sequential Read/Edit/Write calls waste round trips.
    Should batch or parallelize file operations.
    """

    name: str = "sequential_file_ops"
    delta: int = -1
    description: str = "Sequential file ops (batch or parallelize)"
    cooldown_turns: int = 3

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        # Context-based: hook sets this when detecting sequential pattern
        return context.get("sequential_file_ops", False)


# =============================================================================
# STUCK LOOP REDUCERS (v4.9) - Detect debugging without progress
# =============================================================================


@dataclass
class StuckLoopReducer(ConfidenceReducer):
    """Triggers when editing same file repeatedly without research.

    Detects debugging loops where Claude keeps trying same approach
    without success. Forces research/external consultation.
    """

    name: str = "stuck_loop"
    delta: int = -15
    description: str = "Stuck in debug loop - research required"
    cooldown_turns: int = 5

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
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
    cooldown_turns: int = 8

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        # Context-based: hook sets when no research done in debug session
        return context.get("no_research_in_debug", False)


# Registry of all reducers
# All reducers now ENABLED with proper detection mechanisms

REDUCERS: list[ConfidenceReducer] = [
    # Core reducers
    ToolFailureReducer(),
    CascadeBlockReducer(),
    SunkCostReducer(),
    UserCorrectionReducer(),
    GoalDriftReducer(),
    EditOscillationReducer(),
    ContradictionReducer(),
    FollowUpQuestionReducer(),
    # Bad behavior reducers
    BackupFileReducer(),
    VersionFileReducer(),
    MarkdownCreationReducer(),
    OverconfidentCompletionReducer(),
    DeferralReducer(),
    ApologeticReducer(),
    SycophancyReducer(),
    UnresolvedAntiPatternReducer(),
    SpottedIgnoredReducer(),
    DebtBashReducer(),
    LargeDiffReducer(),
    HookBlockReducer(),
    SequentialRepetitionReducer(),
    SequentialWhenParallelReducer(),
    # Verification theater reducers
    UnbackedVerificationClaimReducer(),
    FixedWithoutChainReducer(),
    GitSpamReducer(),
    # Time waster reducers
    RereadUnchangedReducer(),
    VerbosePreambleReducer(),
    HugeOutputDumpReducer(),
    RedundantExplanationReducer(),
    TrivialQuestionReducer(),
    ObviousNextStepsReducer(),
    # Code quality reducers
    PlaceholderImplReducer(),
    SilentFailureReducer(),
    HallmarkPhraseReducer(),
    ScopeCreepReducer(),
    IncompleteRefactorReducer(),
    # Test coverage reducers
    TestIgnoredReducer(),
    ChangeWithoutTestReducer(),
    # AST-based code quality reducers
    DeepNestingReducer(),
    LongFunctionReducer(),
    MutableDefaultArgReducer(),
    ImportStarReducer(),
    BareRaiseReducer(),
    CommentedCodeReducer(),
    # Verification bundling
    UnverifiedEditsReducer(),
    # Framework alignment reducers (v4.8)
    WebFetchOverCrawlReducer(),
    WebSearchBasicReducer(),
    TodoWriteBypassReducer(),
    RawSymbolHuntReducer(),
    GrepOverSerenaReducer(),
    FileReeditReducer(),
    SequentialFileOpsReducer(),
    # Stuck loop reducers (v4.9)
    StuckLoopReducer(),
    NoResearchDebugReducer(),
]
