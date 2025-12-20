#!/usr/bin/env python3
"""Confidence reducers: behavioral category."""

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ._base import ConfidenceReducer, IMPACT_BEHAVIORAL

if TYPE_CHECKING:
    from session_state import SessionState


@dataclass
class BackupFileReducer(ConfidenceReducer):
    """Triggers when creating backup files (technical debt)."""

    name: str = "backup_file"
    delta: int = -10
    description: str = "Created backup file (technical debt)"
    remedy: str = "use git for versioning, or edit in place"
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
        if state.turn_count - last_trigger_turn < self.get_effective_cooldown(state):
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
    remedy: str = "use git branches, or edit original file"
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
    # Paths where version-like patterns are expected (not tech debt)
    exempt_paths: list = field(
        default_factory=lambda: [
            r"/plugins/cache/",  # Plugin cache uses semver directories like /7.3.2/
            r"/node_modules/",  # npm packages have version directories
            r"\.venv/",  # Python venvs may have versioned paths
        ]
    )

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.get_effective_cooldown(state):
            return False
        file_path = context.get("file_path", "")
        if not file_path:
            return False
        # Check exempt paths first
        for exempt in self.exempt_paths:
            if re.search(exempt, file_path, re.IGNORECASE):
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
    remedy: str = "use inline comments, or add to existing docs"
    cooldown_turns: int = 1
    # Exempt paths where markdown is acceptable
    exempt_paths: list = field(
        default_factory=lambda: [
            r"\.claude/memory/",  # Memory files OK
            r"\.claude/skills/",  # Skills OK
            r"\.claude/agents/",  # Agent definitions OK
            r"\.claude/commands/",  # Slash commands OK
            r"\.claude/rules/",  # Rules files OK (framework DNA)
            r"\.claude/tmp/",  # Scratch files OK (symlink)
            r"/tmp/\.claude-scratch/",  # Scratch files OK (actual)
            r"\.serena/memories/",  # Serena memories OK
            r"/docs?/",  # Explicit docs folders OK
            r"README\.md$",  # README OK if explicitly requested
        ]
    )

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.get_effective_cooldown(state):
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
    remedy: str = "say 'changes complete, verified with [test]'"
    cooldown_turns: int = 3
    penalty_class: str = "INTEGRITY"
    max_recovery_fraction: float = 0.0
    impact_category: str = IMPACT_BEHAVIORAL
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
        if state.turn_count - last_trigger_turn < self.get_effective_cooldown(state):
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
    remedy: str = "do it now, or delete the thought entirely"
    cooldown_turns: int = 3
    impact_category: str = IMPACT_BEHAVIORAL
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
        if state.turn_count - last_trigger_turn < self.get_effective_cooldown(state):
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
    remedy: str = "say 'Fix:' followed by the action"
    cooldown_turns: int = 2
    penalty_class: str = "INTEGRITY"
    max_recovery_fraction: float = 0.0
    impact_category: str = IMPACT_BEHAVIORAL
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
        if state.turn_count - last_trigger_turn < self.get_effective_cooldown(state):
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
    remedy: str = "just proceed with the work"
    cooldown_turns: int = 2
    penalty_class: str = "INTEGRITY"
    max_recovery_fraction: float = 0.0
    impact_category: str = IMPACT_BEHAVIORAL
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
        if state.turn_count - last_trigger_turn < self.get_effective_cooldown(state):
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
    remedy: str = "fix the issue, or create a bead to track it"
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
        if state.turn_count - last_trigger_turn < self.get_effective_cooldown(state):
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
    remedy: str = "fix it now, or create bead to track"
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
        if state.turn_count - last_trigger_turn < self.get_effective_cooldown(state):
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
    remedy: str = "solve the underlying issue instead of forcing"
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
        if state.turn_count - last_trigger_turn < self.get_effective_cooldown(state):
            return False
        command = context.get("bash_command", "")
        if not command:
            return False
        for pattern in self.debt_patterns:
            if re.search(pattern, command, re.IGNORECASE):
                return True
        return False


# NOTE: ManualCommitReducer REMOVED (v4.17)
# Git commits are now explicit - no auto-commit means no penalty for manual commits.
# All commits require AI or user directive.


@dataclass
class LargeDiffReducer(ConfidenceReducer):
    """Triggers when diffs exceed 400 LOC - risky large changes."""

    name: str = "large_diff"
    delta: int = -8
    description: str = "Large diff (>400 LOC) - risky change"
    remedy: str = "break into smaller, focused changes"
    cooldown_turns: int = 1

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.get_effective_cooldown(state):
            return False
        return context.get("large_diff", False)


@dataclass
class HookBlockReducer(ConfidenceReducer):
    """DISABLED: Double-jeopardy - being blocked IS the corrective signal.

    The hook block itself provides feedback. Adding a confidence penalty
    on top punishes twice for the same thing = net negative.
    """

    name: str = "hook_block"
    delta: int = -5
    description: str = "Hook blocked action (soft/hard)"
    remedy: str = "fix what the hook flagged"
    cooldown_turns: int = 1

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        # DISABLED: Being blocked is already the signal. No double-jeopardy.
        return False


__all__ = [
    "BackupFileReducer",
    "VersionFileReducer",
    "MarkdownCreationReducer",
    "OverconfidentCompletionReducer",
    "DeferralReducer",
    "ApologeticReducer",
    "SycophancyReducer",
    "UnresolvedAntiPatternReducer",
    "SpottedIgnoredReducer",
    "DebtBashReducer",
    "LargeDiffReducer",
    "HookBlockReducer",
]
