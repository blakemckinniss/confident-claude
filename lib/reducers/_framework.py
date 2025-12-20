#!/usr/bin/env python3
"""Confidence reducers: framework category."""

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ._base import ConfidenceReducer

if TYPE_CHECKING:
    from session_state import SessionState


@dataclass
class WebFetchOverCrawlReducer(ConfidenceReducer):
    """Triggers when using WebFetch instead of crawl4ai.

    crawl4ai bypasses bot detection and renders JavaScript.
    WebFetch is inferior for web scraping.
    """

    name: str = "webfetch_over_crawl"
    delta: int = -1
    description: str = "WebFetch used (prefer crawl4ai)"
    remedy: str = "use mcp__crawl4ai__crawl instead"
    cooldown_turns: int = 2  # One signal per behavior is enough

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.get_effective_cooldown(state):
            return False
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
    remedy: str = "use mcp__crawl4ai__ddg_search instead"
    cooldown_turns: int = 2  # One signal per behavior is enough

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.get_effective_cooldown(state):
            return False
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
    remedy: str = "use bd create/update instead"
    cooldown_turns: int = 2  # One signal per behavior is enough

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.get_effective_cooldown(state):
            return False
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
    remedy: str = "activate serena, use find_symbol"
    cooldown_turns: int = 2  # One signal per behavior is enough

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.get_effective_cooldown(state):
            return False
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

    EXEMPT: Single-file searches - Grep on a known specific file is fine.
    Only penalize broad directory searches where Serena would be better.
    """

    name: str = "grep_over_serena"
    delta: int = -1
    description: str = "Grep on code (serena has semantic search)"
    remedy: str = "use serena search_for_pattern instead"
    cooldown_turns: int = 2  # One signal per behavior is enough

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.get_effective_cooldown(state):
            return False
        # Only if serena is activated
        if not context.get("serena_activated", False):
            return False

        tool_name = context.get("tool_name", "")
        if tool_name != "Grep":
            return False

        # Check if searching in code-heavy areas
        path = context.get("grep_path", "")

        # FIX: Exempt single-file searches - Grep on a specific file is fine
        # Only penalize broad directory searches where Serena adds value
        file_extensions = (
            ".py",
            ".ts",
            ".tsx",
            ".js",
            ".jsx",
            ".rs",
            ".go",
            ".java",
            ".md",
        )
        if path.endswith(file_extensions):
            return False  # Searching specific file, Grep is appropriate

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
    remedy: str = "get it right the first time"
    cooldown_turns: int = 2  # One signal per behavior is enough

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
        if state.turn_count - last_trigger_turn < self.get_effective_cooldown(state):
            return False
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
class ComplexBashChainReducer(ConfidenceReducer):
    """Triggers on complex bash chains that should be scripts.

    3+ pipes or semicolons in a command indicates complexity better
    handled by a reusable Python script in ~/.claude/tmp/.
    """

    name: str = "complex_bash_chain"
    delta: int = -2
    description: str = "Complex bash chain (3+ pipes/semicolons)"
    remedy: str = "write to ~/.claude/tmp/<task>.py instead"
    cooldown_turns: int = 2

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.get_effective_cooldown(state):
            return False

        tool_name = context.get("tool_name", "")
        if tool_name != "Bash":
            return False

        command = context.get("bash_command", "")
        if not command:
            return False

        # Exempt: Already running a script (good behavior!)
        if ".claude/tmp/" in command or ".claude/ops/" in command:
            return False

        # Exempt: Simple git commands with heredoc (commit messages)
        if "git commit" in command:
            return False

        # Count structural complexity indicators
        pipe_count = command.count("|")
        semicolon_count = command.count(";")
        and_count = command.count("&&")

        # Trigger on 3+ structural operators
        total_complexity = pipe_count + semicolon_count + and_count
        return total_complexity >= 3


@dataclass
class BashDataTransformReducer(ConfidenceReducer):
    """Triggers on complex data transformation in bash.

    awk/sed/jq with complex expressions should be Python scripts
    for readability, debuggability, and reusability.
    """

    name: str = "bash_data_transform"
    delta: int = -3
    description: str = "Complex bash data transform - use Python script"
    remedy: str = "write Python script to ~/.claude/tmp/"
    cooldown_turns: int = 2
    # Patterns indicating complex transforms (not simple usage)
    complex_patterns: list = field(
        default_factory=lambda: [
            r"awk\s+'[^']{30,}'",  # awk with long script
            r'awk\s+"[^"]{30,}"',  # awk with long script (double quotes)
            r"sed\s+(-e\s+){2,}",  # multiple sed expressions
            r"sed\s+'[^']*;[^']*;",  # sed with multiple commands
            r"jq\s+'[^']{40,}'",  # jq with complex filter
            r"\|\s*awk.*\|\s*awk",  # chained awk
            r"\|\s*sed.*\|\s*sed",  # chained sed
        ]
    )

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.get_effective_cooldown(state):
            return False

        tool_name = context.get("tool_name", "")
        if tool_name != "Bash":
            return False

        command = context.get("bash_command", "")
        if not command:
            return False

        # Exempt: Already running a script
        if ".claude/tmp/" in command or ".claude/ops/" in command:
            return False

        for pattern in self.complex_patterns:
            if re.search(pattern, command):
                return True
        return False


# =============================================================================
# STUCK LOOP REDUCERS (v4.9) - Detect debugging without progress
# =============================================================================


__all__ = [
    "WebFetchOverCrawlReducer",
    "WebSearchBasicReducer",
    "TodoWriteBypassReducer",
    "RawSymbolHuntReducer",
    "GrepOverSerenaReducer",
    "FileReeditReducer",
    "ComplexBashChainReducer",
    "BashDataTransformReducer",
]
