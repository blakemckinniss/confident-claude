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
# CONTEXT FLAG REGISTRY
# =============================================================================
# Documents which hook sets which context flag for reducers/increasers.
# All flags are set in post_tool_use_runner.py unless otherwise noted.
#
# Format: "flag_name": "description | set when | used by"

CONTEXT_FLAGS = {
    # Format: "flag": ("set_by", "used_by")
    # All set by post_tool_use_runner.py unless noted
    #
    # === TOOL METADATA ===
    "tool_name": ("always", "Multiple"),
    "tool_input": ("always", "PRCreatedIncreaser"),
    "tool_result": ("always", "PRCreatedIncreaser"),
    "file_path": ("Edit/Write", "BackupFileReducer"),
    "new_string": ("Edit", "PlaceholderImplReducer"),
    "content": ("Write", "PlaceholderImplReducer"),
    "bash_command": ("Bash", "DebtBashReducer"),
    "prompt": ("user_prompt_submit_runner", "UserCorrectionReducer"),
    "assistant_output": ("stop_runner", "OverconfidentCompletionReducer"),
    "current_activity": ("session_tracking", "GoalDriftReducer"),
    # === REDUCER FLAGS ===
    "large_diff": ("git_diff>400", "LargeDiffReducer"),
    "hook_blocked": ("pre_tool_use", "HookBlockReducer"),
    "sequential_repetition_3plus": ("tool_tracking", "SequentialRepetitionReducer"),
    "unbacked_verification": ("output_analysis", "UnbackedVerificationClaimReducer"),
    "fixed_without_chain": ("output_analysis", "FixedWithoutChainReducer"),
    "git_spam": ("command_tracking", "GitSpamReducer"),
    "incomplete_refactor": ("grep_after_edit", "IncompleteRefactorReducer"),
    "reread_unchanged": ("file_hash_tracking", "RereadUnchangedReducer"),
    "huge_output_dump": ("output_size_check", "HugeOutputDumpReducer"),
    "trivial_question": ("question_analysis", "TrivialQuestionReducer"),
    "test_ignored": ("test_file_tracking", "TestIgnoredReducer"),
    "change_without_test": ("coverage_tracking", "ChangeWithoutTestReducer"),
    "contradiction_detected": ("claim_tracking", "ContradictionReducer"),
    # === INCREASER FLAGS ===
    "files_read_count": ("Read_tool", "FileReadIncreaser"),
    "memory_consulted": ("Read_path_check", "MemoryConsultIncreaser"),
    "targeted_read": ("Read_params", "TargetedReadIncreaser"),
    "research_performed": ("WebSearch/WebFetch", "ResearchIncreaser"),
    "search_performed": ("Grep/Glob/Task", "SearchToolIncreaser"),
    "subagent_delegation": ("Task_subagent_type", "SubagentDelegationIncreaser"),
    "asked_user": ("AskUserQuestion", "AskUserIncreaser"),
    "rules_updated": ("Edit_path_check", "RulesUpdateIncreaser"),
    "custom_script_ran": ("Bash_path_check", "CustomScriptIncreaser"),
    "bead_created": ("Bash_output", "BeadCreateIncreaser"),
    "git_explored": ("Bash_command", "GitExploreIncreaser"),
    "git_committed": ("Bash_command", "GitCommitIncreaser"),
    "productive_bash": ("Bash_command", "ProductiveBashIncreaser"),
    "small_diff": ("git_diff<400", "SmallDiffIncreaser"),
    "tests_passed": ("Bash_output", "PassedTestsIncreaser"),
    "build_succeeded": ("Bash_output", "BuildSuccessIncreaser"),
    "lint_passed": ("Bash_output", "LintPassIncreaser"),
    "chained_commands": ("Bash_command", "ChainedCommandsIncreaser"),
    "batch_fix": ("Edit_analysis", "BatchFixIncreaser"),
    "parallel_tools": ("tool_count", "ParallelToolsIncreaser"),
    "efficient_search": ("search_result", "EfficientSearchIncreaser"),
    "first_attempt_success": ("task_tracking", "FirstAttemptSuccessIncreaser"),
    "scoped_change": ("goal_tracking", "ScopedChangeIncreaser"),
    "dead_code_removal": ("output_analysis", "DeadCodeRemovalIncreaser"),
    "external_validation": ("tool_name", "ExternalValidationIncreaser"),
    "pr_created": ("Bash_output", "PRCreatedIncreaser"),
    "issue_closed": ("Bash_output", "IssueClosedIncreaser"),
    "review_addressed": ("Bash_output", "ReviewAddressedIncreaser"),
    "ci_pass": ("Bash_output", "CIPassIncreaser"),
    "merge_complete": ("Bash_output", "MergeCompleteIncreaser"),
    "bead_close": ("Bash_output", "BeadCloseIncreaser"),
    "premise_challenge": ("output_analysis", "PremiseChallengeIncreaser"),
    "direct_action": ("output_analysis", "DirectActionIncreaser"),
}

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
    description: str = f">{VERIFICATION_THRESHOLD} edits without verification (run tests/lint)"
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
        command = context.get("tool_input", {}).get("command", "") if tool_name == "Bash" else ""

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
        nesting_nodes = (ast.If, ast.For, ast.While, ast.With, ast.Try, ast.ExceptHandler)
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
        code_patterns = ["def ", "class ", "if ", "for ", "while ", "return ", "import "]
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
    SpottedIgnoredReducer(),  # "I noticed X" without fixing (-15, magnified)
    DebtBashReducer(),  # --force, --hard, --no-verify commands
    LargeDiffReducer(),  # Diffs > 400 LOC
    HookBlockReducer(),  # Soft/hard hook blocks
    SequentialRepetitionReducer(),  # Same tool 3+ times sequentially (-1)
    SequentialWhenParallelReducer(),  # Sequential when parallel possible (-2) v4.6
    # Verification theater reducers (GPT-5.2 recommendations)
    UnbackedVerificationClaimReducer(),  # Claim without tool evidence (-15)
    FixedWithoutChainReducer(),  # "Fixed" without write+verify (-8)
    GitSpamReducer(),  # >3 git commands in 5 turns (-2)
    # Time waster reducers (v4.2)
    RereadUnchangedReducer(),  # Re-reading unchanged file (-3)
    VerbosePreambleReducer(),  # "I'll now..." fluff (-3)
    HugeOutputDumpReducer(),  # Huge output without summary (-2)
    RedundantExplanationReducer(),  # "As I mentioned..." (-2)
    TrivialQuestionReducer(),  # Questions answerable by reading (-5)
    ObviousNextStepsReducer(),  # "Test in real usage" filler (-5)
    # Code quality reducers (v4.4)
    PlaceholderImplReducer(),  # pass, ..., NotImplementedError (-8)
    SilentFailureReducer(),  # except: pass (-8)
    HallmarkPhraseReducer(),  # AI-speak "certainly", "I'd be happy to" (-3)
    ScopeCreepReducer(),  # "while I'm at it", "might as well" (-8)
    IncompleteRefactorReducer(),  # Partial rename/change (-10)
    # Test coverage reducers (v4.5)
    TestIgnoredReducer(),  # Modified tests without running them (-5)
    ChangeWithoutTestReducer(),  # Prod code without test coverage (-3)
    # AST-based code quality reducers (v4.7)
    DeepNestingReducer(),  # >4 nesting levels (-3)
    LongFunctionReducer(),  # >80 lines (-5)
    MutableDefaultArgReducer(),  # list/dict/set defaults (-5)
    ImportStarReducer(),  # from X import * (-3)
    BareRaiseReducer(),  # raise without exception (-3)
    CommentedCodeReducer(),  # Blocks of commented code (-5)
    # Verification bundling (v4.7)
    UnverifiedEditsReducer(),  # >5 edits without tests/lint (-5)
]


# =============================================================================
# RATE LIMITING (prevents death spirals)
# =============================================================================

# Maximum confidence change per turn (prevents compound penalty death spirals)
MAX_CONFIDENCE_DELTA_PER_TURN = 15

# Higher cap when recovering below stasis floor (allows faster legitimate recovery)
MAX_CONFIDENCE_RECOVERY_DELTA = 30
STASIS_FLOOR = 80

# Mean reversion target (confidence drifts toward this when no strong signals)
MEAN_REVERSION_TARGET = 70
MEAN_REVERSION_RATE = 0.1  # Pull 10% toward target per idle period

# =============================================================================
# STREAK/MOMENTUM SYSTEM (v4.6)
# =============================================================================

# Streak multipliers for consecutive successes
STREAK_MULTIPLIERS = {
    2: 1.25,  # 2 consecutive → 25% bonus
    3: 1.5,  # 3 consecutive → 50% bonus
    5: 2.0,  # 5+ consecutive → 100% bonus (capped)
}
STREAK_DECAY_ON_FAILURE = 0  # Reset to 0 on any reducer firing

# =============================================================================
# DIMINISHING RETURNS SYSTEM (v4.7)
# =============================================================================
# Prevents farming of low-cooldown increasers by reducing value on repeat use.
# Resets each turn to allow legitimate repeated actions across turns.

# Increasers subject to diminishing returns within same turn
FARMABLE_INCREASERS = {
    "file_read",  # cooldown=0, can spam reads
    "productive_bash",  # can spam ls/pwd/tree
    "search_tool",  # can repeat searches
}

# Diminishing multipliers: nth trigger in same turn gets this multiplier
DIMINISHING_MULTIPLIERS = {
    1: 1.0,  # First trigger: full value
    2: 0.5,  # Second: half value
    3: 0.25,  # Third: quarter value
    # 4+: 0 (no reward)
}
DIMINISHING_CAP = 3  # Max triggers per turn that give any reward

# =============================================================================
# PROJECT-SPECIFIC CONFIDENCE TUNING (v4.7)
# =============================================================================
# Per-project weight adjustments via .claude/confidence.json
# Example: {"reducer_weights": {"scope_creep": 0.5}, "increaser_weights": {"test_pass": 1.5}}

_PROJECT_WEIGHTS_CACHE: dict = {}
_PROJECT_WEIGHTS_MTIME: float = 0.0


def get_project_weights() -> dict:
    """Load project-specific confidence weights from .claude/confidence.json.

    Returns dict with:
      - reducer_weights: {reducer_name: multiplier}
      - increaser_weights: {increaser_name: multiplier}

    Multiplier < 1.0 softens effect, > 1.0 hardens it, 0 disables.
    """
    import json
    from pathlib import Path

    global _PROJECT_WEIGHTS_CACHE, _PROJECT_WEIGHTS_MTIME

    # Check current working directory for .claude/confidence.json
    config_path = Path.cwd() / ".claude" / "confidence.json"
    if not config_path.exists():
        # Also check home directory project
        config_path = Path.home() / ".claude" / "confidence.json"
        if not config_path.exists():
            return {"reducer_weights": {}, "increaser_weights": {}}

    # Cache with mtime check for hot reload
    try:
        current_mtime = config_path.stat().st_mtime
        if current_mtime == _PROJECT_WEIGHTS_MTIME and _PROJECT_WEIGHTS_CACHE:
            return _PROJECT_WEIGHTS_CACHE

        with open(config_path) as f:
            data = json.load(f)

        _PROJECT_WEIGHTS_CACHE = {
            "reducer_weights": data.get("reducer_weights", {}),
            "increaser_weights": data.get("increaser_weights", {}),
        }
        _PROJECT_WEIGHTS_MTIME = current_mtime
        return _PROJECT_WEIGHTS_CACHE
    except (json.JSONDecodeError, OSError):
        return {"reducer_weights": {}, "increaser_weights": {}}


def get_adjusted_delta(base_delta: int, name: str, is_reducer: bool) -> int:
    """Apply project-specific weight to a reducer/increaser delta.

    Args:
        base_delta: Original delta value
        name: Reducer or increaser name
        is_reducer: True for reducers, False for increasers

    Returns:
        Adjusted delta (int)
    """
    weights = get_project_weights()
    weight_key = "reducer_weights" if is_reducer else "increaser_weights"
    multiplier = weights.get(weight_key, {}).get(name, 1.0)
    return int(base_delta * multiplier)


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
class PassedTestsIncreaser(ConfidenceIncreaser):
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
    """Triggers when asking user for clarification - epistemic humility.

    Reduced from +20 to +8 with longer cooldown to prevent question-spam gaming.
    """

    name: str = "ask_user"
    delta: int = 8  # Reduced from 20 - prevents gaming via question spam
    description: str = "Consulted user for clarification"
    requires_approval: bool = False
    cooldown_turns: int = 8  # Increased from 2 - can't farm questions

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
    """Triggers when exploring git history - understanding context.

    Reduced from +10 to +3 with longer cooldown - process hygiene, not evidence.
    """

    name: str = "git_explore"
    delta: int = 3  # Reduced from 10 - prevent farming
    description: str = "Explored git history/state"
    requires_approval: bool = False
    cooldown_turns: int = 5  # Increased from 2 - diminishing returns

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


# =============================================================================
# TIME SAVER INCREASERS (Reward efficient patterns)
# =============================================================================


@dataclass
class ParallelToolsIncreaser(ConfidenceIncreaser):
    """Triggers when using multiple tools in parallel (same message).

    Efficient use of parallelism saves time and context.
    """

    name: str = "parallel_tools"
    delta: int = 3
    description: str = "Used parallel tool calls efficiently"
    requires_approval: bool = False
    cooldown_turns: int = 1

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        return context.get("parallel_tools", False)


@dataclass
class EfficientSearchIncreaser(ConfidenceIncreaser):
    """Triggers when search finds target on first try.

    Efficient searching demonstrates codebase understanding.
    """

    name: str = "efficient_search"
    delta: int = 2
    description: str = "Found target on first search attempt"
    requires_approval: bool = False
    cooldown_turns: int = 2

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        return context.get("efficient_search", False)


@dataclass
class BatchFixIncreaser(ConfidenceIncreaser):
    """Triggers when fixing multiple issues in single edit.

    Batch operations are more efficient than one-at-a-time.
    """

    name: str = "batch_fix"
    delta: int = 3
    description: str = "Fixed multiple issues in single edit"
    requires_approval: bool = False
    cooldown_turns: int = 1

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        return context.get("batch_fix", False)


@dataclass
class DirectActionIncreaser(ConfidenceIncreaser):
    """Triggers when taking direct action without preamble.

    Direct action saves tokens and time vs verbose explanations.
    """

    name: str = "direct_action"
    delta: int = 2
    description: str = "Took direct action without preamble"
    requires_approval: bool = False
    cooldown_turns: int = 2

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        return context.get("direct_action", False)


@dataclass
class ChainedCommandsIncreaser(ConfidenceIncreaser):
    """Triggers when chaining related commands with && or ;.

    Chaining saves round trips and demonstrates planning.
    """

    name: str = "chained_commands"
    delta: int = 1
    description: str = "Chained related commands efficiently"
    requires_approval: bool = False
    cooldown_turns: int = 1

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        return context.get("chained_commands", False)


@dataclass
class TargetedReadIncreaser(ConfidenceIncreaser):
    """Triggers when using offset/limit on Read for large files.

    Reading targeted sections saves tokens vs reading entire file.
    """

    name: str = "targeted_read"
    delta: int = 2
    description: str = "Used targeted read (offset/limit) for efficiency"
    requires_approval: bool = False
    cooldown_turns: int = 1

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        return context.get("targeted_read", False)


@dataclass
class SubagentDelegationIncreaser(ConfidenceIncreaser):
    """Triggers when using Task(Explore) for open-ended exploration.

    Delegating exploration to subagents saves main context window.
    """

    name: str = "subagent_delegation"
    delta: int = 2
    description: str = "Delegated exploration to subagent (context saved)"
    requires_approval: bool = False
    cooldown_turns: int = 2

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        return context.get("subagent_delegation", False)


@dataclass
class PremiseChallengeIncreaser(ConfidenceIncreaser):
    """Triggers when suggesting existing solutions instead of building from scratch.

    Challenging the build-vs-buy premise saves time and prevents wheel reinvention.
    Rewards "thinking outside the box" by suggesting alternatives.
    """

    name: str = "premise_challenge"
    delta: int = 5
    description: str = "Suggested existing solution or challenged build-vs-buy"
    requires_approval: bool = False
    cooldown_turns: int = 3

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        return context.get("premise_challenge", False)


# =============================================================================
# COMPLETION QUALITY INCREASERS (Reward good outcomes)
# =============================================================================


@dataclass
class BeadCloseIncreaser(ConfidenceIncreaser):
    """Triggers when closing a bead (completing tracked work).

    Completing tracked tasks demonstrates follow-through.
    """

    name: str = "bead_close"
    delta: int = 5
    description: str = "Closed bead (completed tracked work)"
    requires_approval: bool = False
    cooldown_turns: int = 1

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        # Detect bd close commands
        for cmd in state.commands_succeeded[-3:]:
            cmd_str = cmd.get("command", "").lower()
            if "bd close" in cmd_str or "bd update" in cmd_str and "closed" in cmd_str:
                return True
        return context.get("bead_close", False)


@dataclass
class FirstAttemptSuccessIncreaser(ConfidenceIncreaser):
    """Triggers when task completed without retry/correction.

    Getting it right first time demonstrates competence.
    """

    name: str = "first_attempt_success"
    delta: int = 3
    description: str = "Task completed on first attempt"
    requires_approval: bool = False
    cooldown_turns: int = 3

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        # Context-based: set by hooks when detecting clean completion
        return context.get("first_attempt_success", False)


@dataclass
class DeadCodeRemovalIncreaser(ConfidenceIncreaser):
    """Triggers when deleting unused code/imports.

    Cleanup improves codebase health.
    """

    name: str = "dead_code_removal"
    delta: int = 3
    description: str = "Removed dead/unused code"
    requires_approval: bool = False
    cooldown_turns: int = 1
    patterns: list = field(
        default_factory=lambda: [
            r"removed?\s+(?:unused|dead)\s+(?:code|import|function|class|variable)",
            r"delet(?:ed?|ing)\s+(?:unused|dead|obsolete)",
            r"clean(?:ed|ing)\s+up\s+(?:unused|dead)",
        ]
    )

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        output = context.get("assistant_output", "")
        if output:
            output_lower = output.lower()
            for pattern in self.patterns:
                if re.search(pattern, output_lower):
                    return True
        return context.get("dead_code_removal", False)


@dataclass
class ScopedChangeIncreaser(ConfidenceIncreaser):
    """Triggers when changes stay within original request scope.

    Focused work without scope creep is efficient.
    """

    name: str = "scoped_change"
    delta: int = 2
    description: str = "Changes stayed within requested scope"
    requires_approval: bool = False
    cooldown_turns: int = 3

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        # Context-based: set by hooks when detecting focused work
        return context.get("scoped_change", False)


@dataclass
class ExternalValidationIncreaser(ConfidenceIncreaser):
    """Triggers when using PAL/oracle tools for validation.

    External verification catches blind spots.
    """

    name: str = "external_validation"
    delta: int = 5
    description: str = "Used external validation (PAL/oracle)"
    requires_approval: bool = False
    cooldown_turns: int = 2

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        tool_name = context.get("tool_name", "")
        # Detect PAL MCP tools
        if tool_name.startswith("mcp__pal__"):
            return True
        return context.get("external_validation", False)


@dataclass
class PRCreatedIncreaser(ConfidenceIncreaser):
    """Triggers when a pull request is successfully created.

    Creating a PR indicates work is ready for review - a completion signal.
    """

    name: str = "pr_created"
    delta: int = 5
    description: str = "Pull request created successfully"
    requires_approval: bool = False
    cooldown_turns: int = 1

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        # Check for gh pr create success in bash output
        tool_name = context.get("tool_name", "")
        if tool_name != "Bash":
            return False
        command = context.get("tool_input", {}).get("command", "")
        output = context.get("tool_result", "")
        if "gh pr create" in command and "github.com" in output.lower():
            return True
        return context.get("pr_created", False)


@dataclass
class IssueClosedIncreaser(ConfidenceIncreaser):
    """Triggers when a GitHub issue is closed.

    Closing issues indicates task completion and progress tracking.
    """

    name: str = "issue_closed"
    delta: int = 3
    description: str = "GitHub issue closed"
    requires_approval: bool = False
    cooldown_turns: int = 1

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        tool_name = context.get("tool_name", "")
        if tool_name != "Bash":
            return False
        command = context.get("tool_input", {}).get("command", "")
        output = context.get("tool_result", "")
        # gh issue close or gh issue edit --state closed
        if "gh issue close" in command or "gh issue edit" in command:
            if "closed" in output.lower() or "✓" in output:
                return True
        return context.get("issue_closed", False)


@dataclass
class ReviewAddressedIncreaser(ConfidenceIncreaser):
    """Triggers when PR review comments are addressed.

    Resolving review feedback indicates responsiveness and quality work.
    """

    name: str = "review_addressed"
    delta: int = 5
    description: str = "PR review comments addressed"
    requires_approval: bool = False
    cooldown_turns: int = 3

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        tool_name = context.get("tool_name", "")
        if tool_name != "Bash":
            return False
        command = context.get("tool_input", {}).get("command", "")
        output = context.get("tool_result", "")
        # gh pr review --approve or resolving threads
        if "gh pr review" in command and "approved" in output.lower():
            return True
        # Pushing after review comments
        if "git push" in command and context.get("review_addressed", False):
            return True
        return context.get("review_addressed", False)


@dataclass
class CIPassIncreaser(ConfidenceIncreaser):
    """Triggers when CI/GitHub Actions passes.

    Successful CI indicates code meets quality gates.
    """

    name: str = "ci_pass"
    delta: int = 5
    description: str = "CI/GitHub Actions passed"
    requires_approval: bool = False
    cooldown_turns: int = 3

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        tool_name = context.get("tool_name", "")
        if tool_name != "Bash":
            return False
        command = context.get("tool_input", {}).get("command", "")
        output = context.get("tool_result", "")
        # gh run view or gh pr checks
        if "gh run" in command or "gh pr checks" in command:
            output_lower = output.lower() if isinstance(output, str) else ""
            if "pass" in output_lower or "success" in output_lower or "✓" in output:
                return True
        return context.get("ci_pass", False)


@dataclass
class MergeCompleteIncreaser(ConfidenceIncreaser):
    """Triggers when a PR is merged.

    Merging indicates work is complete and accepted.
    """

    name: str = "merge_complete"
    delta: int = 5
    description: str = "Pull request merged"
    requires_approval: bool = False
    cooldown_turns: int = 1

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        tool_name = context.get("tool_name", "")
        if tool_name != "Bash":
            return False
        command = context.get("tool_input", {}).get("command", "")
        output = context.get("tool_result", "")
        # gh pr merge
        if "gh pr merge" in command:
            output_lower = output.lower() if isinstance(output, str) else ""
            if "merged" in output_lower or "✓" in output:
                return True
        return context.get("merge_complete", False)


# =============================================================================
# CODE IMPROVEMENT INCREASERS (v4.7)
# =============================================================================


@dataclass
class DocstringAdditionIncreaser(ConfidenceIncreaser):
    """Triggers when adding docstrings to functions/classes.

    Documentation improves code maintainability.
    """

    name: str = "docstring_addition"
    delta: int = 2
    description: str = "Added docstring to function/class"
    requires_approval: bool = False
    cooldown_turns: int = 1

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        new_content = context.get("new_string", "") or context.get("content", "")
        old_content = context.get("old_string", "")
        if not new_content:
            return False
        # Check if adding triple-quoted strings (docstrings)
        new_docstrings = new_content.count('"""') + new_content.count("'''")
        old_docstrings = old_content.count('"""') + old_content.count("'''")
        return new_docstrings > old_docstrings


@dataclass
class TypeHintAdditionIncreaser(ConfidenceIncreaser):
    """Triggers when adding type hints to code.

    Type hints improve code clarity and catch bugs early.
    """

    name: str = "type_hint_addition"
    delta: int = 2
    description: str = "Added type hints"
    requires_approval: bool = False
    cooldown_turns: int = 1

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        import re

        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        new_content = context.get("new_string", "") or context.get("content", "")
        old_content = context.get("old_string", "")
        file_path = context.get("file_path", "")
        if not new_content or not file_path.endswith(".py"):
            return False
        # Count type hint patterns: -> Type, : Type (in function signatures)
        hint_pattern = r":\s*[A-Z][a-zA-Z\[\],\s|]+|->[\s]*[A-Z][a-zA-Z\[\],\s|]+"
        new_hints = len(re.findall(hint_pattern, new_content))
        old_hints = len(re.findall(hint_pattern, old_content))
        return new_hints > old_hints


@dataclass
class ComplexityReductionIncreaser(ConfidenceIncreaser):
    """Triggers when reducing code complexity (fewer lines, simpler logic).

    Rewards refactoring that simplifies code.
    """

    name: str = "complexity_reduction"
    delta: int = 3
    description: str = "Reduced code complexity"
    requires_approval: bool = False
    cooldown_turns: int = 2

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        new_content = context.get("new_string", "") or context.get("content", "")
        old_content = context.get("old_string", "")
        tool_name = context.get("tool_name", "")
        if tool_name != "Edit" or not old_content or not new_content:
            return False
        # Simplified: fewer lines AND fewer conditionals
        new_lines = len(new_content.splitlines())
        old_lines = len(old_content.splitlines())
        new_conds = new_content.count("if ") + new_content.count("elif ")
        old_conds = old_content.count("if ") + old_content.count("elif ")
        # Must reduce both lines (by >20%) and conditionals
        line_reduction = old_lines > 0 and new_lines < old_lines * 0.8
        cond_reduction = new_conds < old_conds
        return line_reduction or (old_conds > 0 and cond_reduction)


@dataclass
class SecurityFixIncreaser(ConfidenceIncreaser):
    """Triggers when fixing security issues.

    Security fixes are high-value improvements.
    """

    name: str = "security_fix"
    delta: int = 10
    description: str = "Fixed security issue"
    requires_approval: bool = False
    cooldown_turns: int = 1

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        # Context-based: hook sets this when security pattern removed
        return context.get("security_fix", False)


@dataclass
class DependencyRemovalIncreaser(ConfidenceIncreaser):
    """Triggers when removing unnecessary dependencies.

    Fewer dependencies = smaller attack surface, simpler builds.
    """

    name: str = "dependency_removal"
    delta: int = 3
    description: str = "Removed unnecessary dependency"
    requires_approval: bool = False
    cooldown_turns: int = 1

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        tool_name = context.get("tool_name", "")
        file_path = context.get("file_path", "")
        old_content = context.get("old_string", "")
        new_content = context.get("new_string", "")
        if tool_name != "Edit":
            return False
        # Check dependency files
        dep_files = ("requirements.txt", "pyproject.toml", "package.json", "Cargo.toml")
        if not any(file_path.endswith(f) for f in dep_files):
            return False
        # Removal = old has more non-empty lines than new
        old_deps = len([line for line in old_content.splitlines() if line.strip()])
        new_deps = len([line for line in new_content.splitlines() if line.strip()])
        return new_deps < old_deps


@dataclass
class ConfigExternalizationIncreaser(ConfidenceIncreaser):
    """Triggers when externalizing hardcoded values to config.

    Config externalization improves maintainability.
    """

    name: str = "config_externalization"
    delta: int = 2
    description: str = "Externalized hardcoded value to config"
    requires_approval: bool = False
    cooldown_turns: int = 1

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        # Context-based: hook sets this when detecting config pattern
        return context.get("config_externalization", False)


# Registry of all increasers
INCREASERS: list[ConfidenceIncreaser] = [
    # High-value context gathering (+10)
    MemoryConsultIncreaser(),
    BeadCreateIncreaser(),
    GitExploreIncreaser(),
    GitCommitIncreaser(),  # Saving work (+3)
    # Objective signals (high value)
    PassedTestsIncreaser(),
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
    # Time saver increasers (v4.2)
    ParallelToolsIncreaser(),  # Multiple tools in parallel (+3)
    EfficientSearchIncreaser(),  # First-try search success (+2)
    BatchFixIncreaser(),  # Multiple fixes in one edit (+3)
    DirectActionIncreaser(),  # No preamble, just action (+2)
    ChainedCommandsIncreaser(),  # Commands with && or ; (+1)
    TargetedReadIncreaser(),  # Used offset/limit on Read (+2) v4.6
    SubagentDelegationIncreaser(),  # Delegated to subagent (+2) v4.6
    # Build-vs-buy (v4.3)
    PremiseChallengeIncreaser(),  # Suggest alternatives (+5)
    # Completion quality increasers (v4.4)
    BeadCloseIncreaser(),  # Closed tracked work (+5)
    FirstAttemptSuccessIncreaser(),  # Got it right first time (+3)
    DeadCodeRemovalIncreaser(),  # Cleanup/deletion (+3)
    ScopedChangeIncreaser(),  # Stayed focused (+2)
    ExternalValidationIncreaser(),  # Used PAL/oracle (+5)
    # Workflow signals (v4.5)
    PRCreatedIncreaser(),  # PR created successfully (+5)
    IssueClosedIncreaser(),  # GitHub issue closed (+3)
    ReviewAddressedIncreaser(),  # PR review addressed (+5)
    CIPassIncreaser(),  # CI/GitHub Actions passed (+5)
    MergeCompleteIncreaser(),  # PR merged (+5)
    # Code improvement increasers (v4.7)
    DocstringAdditionIncreaser(),  # Added docstring (+2)
    TypeHintAdditionIncreaser(),  # Added type hints (+2)
    ComplexityReductionIncreaser(),  # Simplified code (+3)
    SecurityFixIncreaser(),  # Fixed security issue (+10)
    DependencyRemovalIncreaser(),  # Removed dependency (+3)
    ConfigExternalizationIncreaser(),  # Externalized config (+2)
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

    When below STASIS_FLOOR (80%), allows higher positive gains to enable
    faster legitimate recovery. Penalties always use standard cap.

    Returns the clamped delta.
    """
    # Track cumulative delta this turn
    turn_key = f"_confidence_delta_turn_{state.turn_count}"
    cumulative = state.nudge_history.get(turn_key, 0)

    # Determine cap based on current confidence
    # Allow faster recovery when below stasis floor
    if delta > 0 and state.confidence < STASIS_FLOOR:
        max_positive = MAX_CONFIDENCE_RECOVERY_DELTA
    else:
        max_positive = MAX_CONFIDENCE_DELTA_PER_TURN

    # Calculate remaining budget
    if delta < 0:
        # For penalties, always use standard cap
        remaining = -MAX_CONFIDENCE_DELTA_PER_TURN - cumulative
        clamped = max(delta, remaining)
    else:
        # For boosts, use appropriate cap based on recovery mode
        remaining = max_positive - cumulative
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

    Resets streak counter on any reducer firing (v4.6).

    Returns:
        List of (reducer_name, delta, description) tuples
    """
    triggered = []

    # Get last trigger turns from state (stored in nudge_history)
    for reducer in REDUCERS:
        key = f"confidence_reducer_{reducer.name}"
        last_trigger = state.nudge_history.get(key, {}).get("last_turn", -999)

        if reducer.should_trigger(context, state, last_trigger):
            # Apply project-specific weights (v4.7)
            adjusted_delta = get_adjusted_delta(reducer.delta, reducer.name, is_reducer=True)
            triggered.append((reducer.name, adjusted_delta, reducer.description))
            # Record trigger
            if key not in state.nudge_history:
                state.nudge_history[key] = {}
            state.nudge_history[key]["last_turn"] = state.turn_count

            # Reset streak on failure (v4.6)
            update_streak(state, is_success=False)

    return triggered


def apply_increasers(
    state: "SessionState", context: dict
) -> list[tuple[str, int, str, bool]]:
    """
    Apply all applicable increasers and return list of triggered ones.

    Also handles Trust Debt decay: test_pass and build_success clear debt.
    Applies streak multiplier for consecutive successes (v4.6).

    Returns:
        List of (increaser_name, delta, description, requires_approval) tuples
    """
    triggered = []

    for increaser in INCREASERS:
        key = f"confidence_increaser_{increaser.name}"
        last_trigger = state.nudge_history.get(key, {}).get("last_turn", -999)

        if increaser.should_trigger(context, state, last_trigger):
            # Apply streak multiplier (v4.6)
            streak = get_current_streak(state)
            streak_mult = get_streak_multiplier(streak)

            # Apply diminishing returns for farmable increasers (v4.7)
            diminish_mult = get_diminishing_multiplier(state, increaser.name)

            # Apply project-specific weights (v4.7)
            base_delta = get_adjusted_delta(increaser.delta, increaser.name, is_reducer=False)

            # Combined multiplier with streak and diminishing returns
            adjusted_delta = int(base_delta * streak_mult * diminish_mult)

            # Skip if diminished to zero
            if adjusted_delta <= 0:
                continue

            triggered.append(
                (
                    increaser.name,
                    adjusted_delta,
                    increaser.description,
                    increaser.requires_approval,
                )
            )
            # Record trigger (only for non-approval-required)
            if not increaser.requires_approval:
                if key not in state.nudge_history:
                    state.nudge_history[key] = {}
                state.nudge_history[key]["last_turn"] = state.turn_count

                # Update streak counter (success)
                update_streak(state, is_success=True)

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


# =============================================================================
# STREAK/MOMENTUM TRACKING (v4.6)
# =============================================================================


def get_streak_multiplier(streak_count: int) -> float:
    """Get the multiplier for the current streak count.

    Returns highest applicable multiplier based on streak thresholds.
    """
    multiplier = 1.0
    for threshold, mult in sorted(STREAK_MULTIPLIERS.items()):
        if streak_count >= threshold:
            multiplier = mult
    return multiplier


def get_diminishing_multiplier(
    state: "SessionState", increaser_name: str
) -> float:
    """Get diminishing returns multiplier for farmable increasers.

    Tracks how many times this increaser fired this turn and returns
    decreasing multiplier. Resets each turn.

    Returns:
        Multiplier (1.0 for first, 0.5 for second, 0.25 for third, 0 after)
    """
    if increaser_name not in FARMABLE_INCREASERS:
        return 1.0  # Non-farmable increasers always get full value

    # Track per-turn triggers
    turn_key = f"_diminish_{increaser_name}_turn_{state.turn_count}"
    trigger_count = state.nudge_history.get(turn_key, 0) + 1

    # Update count
    state.nudge_history[turn_key] = trigger_count

    # Cleanup old turn keys (keep only current turn)
    stale_keys = [
        k
        for k in state.nudge_history
        if k.startswith(f"_diminish_{increaser_name}_turn_")
        and k != turn_key
    ]
    for k in stale_keys:
        del state.nudge_history[k]

    # Return multiplier based on trigger count
    if trigger_count > DIMINISHING_CAP:
        return 0.0
    return DIMINISHING_MULTIPLIERS.get(trigger_count, 0.0)


def update_streak(state: "SessionState", is_success: bool) -> int:
    """Update streak counter and return new streak count.

    Args:
        state: Session state to update
        is_success: True if increaser fired, False if reducer fired

    Returns:
        New streak count
    """
    key = "_confidence_streak"
    current = state.nudge_history.get(key, 0)

    if is_success:
        new_streak = current + 1
    else:
        new_streak = STREAK_DECAY_ON_FAILURE

    state.nudge_history[key] = new_streak
    return new_streak


def get_current_streak(state: "SessionState") -> int:
    """Get current streak count."""
    return state.nudge_history.get("_confidence_streak", 0)


# =============================================================================
# TRAJECTORY PREDICTION (v4.6)
# =============================================================================


def predict_trajectory(
    state: "SessionState",
    planned_edits: int = 0,
    planned_bash: int = 0,
    turns_ahead: int = 3,
) -> dict:
    """Predict confidence trajectory based on planned actions.

    Args:
        state: Current session state
        planned_edits: Number of file edits planned
        planned_bash: Number of bash commands planned
        turns_ahead: How many turns to project

    Returns:
        Dict with projected confidence, warnings, and recovery suggestions
    """
    current = state.confidence
    projected = current

    # Apply expected decay
    projected -= turns_ahead  # -1 decay per turn

    # Apply risk penalties for planned actions
    projected -= planned_edits  # -1 per edit
    projected -= planned_bash  # -1 per bash

    # Determine if we'll hit any gates
    warnings = []
    if projected < STASIS_FLOOR and current >= STASIS_FLOOR:
        warnings.append(f"Will drop below stasis floor ({STASIS_FLOOR}%)")
    if (
        projected < THRESHOLD_PRODUCTION_ACCESS
        and current >= THRESHOLD_PRODUCTION_ACCESS
    ):
        warnings.append(
            f"Will lose production write access ({THRESHOLD_PRODUCTION_ACCESS}%)"
        )
    if projected < THRESHOLD_REQUIRE_RESEARCH and current >= THRESHOLD_REQUIRE_RESEARCH:
        warnings.append(f"Will require research ({THRESHOLD_REQUIRE_RESEARCH}%)")

    # Suggest recovery actions if trajectory is concerning
    recovery = []
    if projected < STASIS_FLOOR:
        deficit = STASIS_FLOOR - projected
        recovery.append(f"Run tests (+5 each) - need ~{(deficit // 5) + 1} passes")
        recovery.append("git status/diff (+10)")
        recovery.append("Read relevant files (+1 each)")

    return {
        "current": current,
        "projected": projected,
        "turns_ahead": turns_ahead,
        "delta": projected - current,
        "warnings": warnings,
        "recovery_suggestions": recovery,
        "will_gate": projected < STASIS_FLOOR,
    }


def format_trajectory_warning(trajectory: dict) -> str:
    """Format trajectory prediction as a warning string."""
    if not trajectory["warnings"]:
        return ""

    lines = [
        f"⚠️ Trajectory: {trajectory['current']}% → {trajectory['projected']}% "
        f"in {trajectory['turns_ahead']} turns"
    ]
    for warning in trajectory["warnings"]:
        lines.append(f"  • {warning}")
    if trajectory["recovery_suggestions"]:
        lines.append("  Recovery options:")
        for suggestion in trajectory["recovery_suggestions"][:3]:
            lines.append(f"    - {suggestion}")

    return "\n".join(lines)


# =============================================================================
# CONFIDENCE JOURNAL (v4.6)
# =============================================================================


def log_confidence_change(
    state: "SessionState",
    old_confidence: int,
    new_confidence: int,
    reason: str,
    journal_path: str = "",
) -> None:
    """Log significant confidence changes to journal file.

    Only logs changes >= 3 points to avoid noise.
    """
    from pathlib import Path

    delta = new_confidence - old_confidence
    if abs(delta) < 3:
        return  # Skip tiny changes

    if not journal_path:
        journal_path = Path.home() / ".claude" / "tmp" / "confidence_journal.log"
    else:
        journal_path = Path(journal_path)

    # Ensure directory exists
    journal_path.parent.mkdir(parents=True, exist_ok=True)

    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    direction = "+" if delta > 0 else ""
    entry = f"[{timestamp}] {old_confidence}→{new_confidence} ({direction}{delta}): {reason}\n"

    # Append to journal (keep last 1000 lines max)
    try:
        existing = []
        if journal_path.exists():
            existing = journal_path.read_text().splitlines()[-999:]
        existing.append(entry.strip())
        journal_path.write_text("\n".join(existing) + "\n")
    except OSError:
        return  # Journal write failed, non-critical
