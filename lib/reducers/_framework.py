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
    """DISABLED: Grep is often the right tool even when Serena is active.

    Serena is better for symbol-based queries, but Grep excels at:
    - Quick pattern matching across many files
    - Non-code patterns (config, comments, strings)
    - When you know what you're looking for
    Net negative - creates friction on legitimate tool use.
    """

    name: str = "grep_over_serena"
    delta: int = -1
    description: str = "Grep on code (serena has semantic search)"
    remedy: str = "use serena search_for_pattern instead"
    cooldown_turns: int = 2

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        # DISABLED: Grep is often the right choice. See docstring.
        return False


@dataclass
class FileReeditReducer(ConfidenceReducer):
    """DISABLED: "Get it right the first time" is unrealistic and counterproductive.

    Iterative editing is normal, healthy development. This reducer punished
    legitimate refinement. edit_oscillation already catches actual thrashing.
    Net negative - creates anxiety about normal editing.
    """

    name: str = "file_reedit"
    delta: int = -2
    description: str = "Re-editing file (get it right first time)"
    remedy: str = "get it right the first time"
    cooldown_turns: int = 2

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        # DISABLED: Iteration is healthy. See docstring.
        return False


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
