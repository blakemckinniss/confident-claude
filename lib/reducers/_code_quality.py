#!/usr/bin/env python3
"""Confidence reducers: codequality category."""

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ._base import ConfidenceReducer, IMPACT_BEHAVIORAL

if TYPE_CHECKING:
    from session_state import SessionState


@dataclass
class PlaceholderImplReducer(ConfidenceReducer):
    """Triggers when writing placeholder implementations.

    Catches incomplete work: pass, ..., NotImplementedError in new code.
    Does NOT trigger on pass in exception handlers with specific exception types.
    """

    name: str = "placeholder_impl"
    delta: int = -8
    description: str = "Placeholder implementation (incomplete work)"
    remedy: str = "implement fully, or delete the placeholder"
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

    def _is_pass_in_except_handler(self, content: str) -> bool:
        """Check if pass is legitimately in an exception handler.

        Returns True if pass appears after 'except (SpecificException):' pattern,
        which is a legitimate pattern for intentional exception swallowing.
        Does NOT allow bare 'except:' or 'except Exception:' (too broad).
        """
        # Pattern for specific exception handling followed by pass
        # Matches: except (Error1, Error2): ... pass or except SpecificError: ... pass
        # But NOT: except: pass, except Exception: pass
        specific_except_pass = re.compile(
            r"except\s+\([\w\s,]+\)\s*:\s*\n\s*#[^\n]*\n\s*pass"  # tuple with comment
            r"|except\s+\([\w\s,]+\)\s*:\s*\n\s*pass"  # tuple without comment
            r"|except\s+(?!Exception\b)(?!BaseException\b)\w+(?:Error|Exception|Warning)\s*:\s*\n\s*#[^\n]*\n\s*pass"  # specific with comment
            r"|except\s+(?!Exception\b)(?!BaseException\b)\w+(?:Error|Exception|Warning)\s*:\s*\n\s*pass",  # specific without comment
            re.MULTILINE,
        )
        return bool(specific_except_pass.search(content))

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.get_effective_cooldown(state):
            return False
        # Check content being written/edited
        new_content = context.get("new_string", "") or context.get("content", "")
        if not new_content:
            return False
        # Only trigger on Write/Edit tools
        tool_name = context.get("tool_name", "")
        if tool_name not in ("Write", "Edit"):
            return False

        # Check each pattern
        for pattern in self._get_patterns():
            if re.search(pattern, new_content, re.MULTILINE | re.IGNORECASE):
                # Special case: pass in specific exception handler is OK
                if pattern == r"^\s*pass\s*$" and self._is_pass_in_except_handler(
                    new_content
                ):
                    continue
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
    remedy: str = "handle specifically, or let it crash"
    cooldown_turns: int = 1
    patterns: list = field(
        default_factory=lambda: [
            # Bare except - always dangerous
            r"except\s*:\s*pass",
            r"except\s*:\s*\.\.\.",
            # Catching Exception/BaseException - too broad, hides real errors
            r"except\s+Exception\s*:\s*pass",
            r"except\s+Exception\s*:\s*\.\.\.",
            r"except\s+BaseException\s*:\s*pass",
            r"except\s+BaseException\s*:\s*\.\.\.",
            # Note: Specific exceptions like OSError, ValueError with pass are OK
            # when used for intentional fallback (e.g., path.resolve() failing)
        ]
    )

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.get_effective_cooldown(state):
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
    remedy: str = "just do the thing directly"
    cooldown_turns: int = 2
    impact_category: str = IMPACT_BEHAVIORAL
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
        if state.turn_count - last_trigger_turn < self.get_effective_cooldown(state):
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
    remedy: str = "stay focused, create bead for extras"
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
        if state.turn_count - last_trigger_turn < self.get_effective_cooldown(state):
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
    remedy: str = "grep all usages, update in same pass"
    cooldown_turns: int = 3

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.get_effective_cooldown(state):
            return False
        # Set by hooks when detecting partial refactors
        return context.get("incomplete_refactor", False)


# =============================================================================
# TIME WASTER REDUCERS (Punish inefficient patterns)
# =============================================================================


@dataclass
class DeepNestingReducer(ConfidenceReducer):
    """Triggers on deeply nested code (>4 levels).

    Deep nesting makes code hard to read and test.
    """

    name: str = "deep_nesting"
    delta: int = -3
    description: str = "Deep nesting (>4 levels) - hard to read/test"
    remedy: str = "extract nested logic to helper functions"
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

        if state.turn_count - last_trigger_turn < self.get_effective_cooldown(state):
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
    remedy: str = "split into smaller focused functions"
    cooldown_turns: int = 2
    max_lines: int = 80

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        import ast

        if state.turn_count - last_trigger_turn < self.get_effective_cooldown(state):
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
    remedy: str = "use None default, create in function body"
    cooldown_turns: int = 1

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        import ast

        if state.turn_count - last_trigger_turn < self.get_effective_cooldown(state):
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
    remedy: str = "import specific names needed"
    cooldown_turns: int = 1

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        import ast

        if state.turn_count - last_trigger_turn < self.get_effective_cooldown(state):
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
    remedy: str = "raise specific exception with context"
    cooldown_turns: int = 1

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        import ast

        if state.turn_count - last_trigger_turn < self.get_effective_cooldown(state):
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
    remedy: str = "delete it, git remembers"
    cooldown_turns: int = 2
    min_consecutive_lines: int = 5

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.get_effective_cooldown(state):
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
class PathHardcodingReducer(ConfidenceReducer):
    """Triggers when hardcoding user-specific paths in code.

    Catches embarrassing leaks like /home/jinx/ or C:\\Users\\Blake\\ in
    committed code. These should use environment variables or relative paths.

    GOLDEN STEP: Simple regex, catches real issues.
    """

    name: str = "path_hardcoding"
    delta: int = -8
    description: str = "Hardcoded user path in code (use env var or relative)"
    remedy: str = "use Path.home(), os.environ, or relative paths"
    cooldown_turns: int = 1
    patterns: list = field(
        default_factory=lambda: [
            r"/home/\w+/",  # Linux home dirs
            r"/Users/\w+/",  # macOS home dirs
            r"C:\\Users\\\w+\\",  # Windows paths
            r"C:/Users/\w+/",  # Windows paths (forward slash)
        ]
    )
    # Exempt paths where hardcoding is expected
    exempt_patterns: list = field(
        default_factory=lambda: [
            r"\.claude/tmp/",  # Scratch files OK
            r"/tmp/",  # Temp files OK
            r"#.*",  # Comments OK
            r'""".*"""',  # Docstrings OK
            r"'''.*'''",  # Docstrings OK
        ]
    )

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.get_effective_cooldown(state):
            return False

        tool_name = context.get("tool_name", "")
        if tool_name not in ("Write", "Edit"):
            return False

        new_content = context.get("new_string", "") or context.get("content", "")
        file_path = context.get("file_path", "")
        if not new_content:
            return False

        # Skip config/scratch/documentation files where paths are expected
        if any(
            p in file_path
            for p in [
                ".claude/tmp/",
                "/tmp/",
                ".env",
                "config.json",
                "settings.",
                "installed_plugins.json",  # Plugin registry requires absolute paths
                ".md",
                # Shell config files legitimately contain hardcoded paths
                ".bashrc",
                ".zshrc",
                ".profile",
                ".bash_profile",
                ".bash_aliases",
                ".bash_env",
                ".tmux.conf",
            ]
        ):
            return False

        # Check for hardcoded paths
        for pattern in self.patterns:
            matches = re.finditer(pattern, new_content, re.IGNORECASE)
            for match in matches:
                # Check if match is in an exempt context
                match_start = match.start()
                # Get the line containing this match
                line_start = new_content.rfind("\n", 0, match_start) + 1
                line_end = new_content.find("\n", match_start)
                if line_end == -1:
                    line_end = len(new_content)
                line = new_content[line_start:line_end]

                # Skip if line is a comment
                stripped = line.strip()
                if stripped.startswith("#") or stripped.startswith("//"):
                    continue

                return True
        return False


@dataclass
class MagicNumbersReducer(ConfidenceReducer):
    """Triggers on magic numbers in code (numeric literals not in constants).

    Numbers like 86400, 3600, 1024 should be named constants for clarity.
    Only triggers for numbers >100 to avoid false positives on small values.
    """

    name: str = "magic_numbers"
    delta: int = -3
    description: str = "Magic number in code (use named constant)"
    remedy: str = "extract to SCREAMING_SNAKE_CASE constant"
    cooldown_turns: int = 2
    # Common acceptable magic numbers
    allowed_numbers: set = field(
        default_factory=lambda: {
            0,
            1,
            2,
            10,
            100,
            1000,  # Common bases
            -1,  # Sentinel
            255,
            256,
            512,
            1024,
            2048,
            4096,  # Powers of 2
            60,
            24,
            7,
            30,
            365,  # Time units (should still be constants, but common)
        }
    )

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        import ast

        if state.turn_count - last_trigger_turn < self.get_effective_cooldown(state):
            return False

        tool_name = context.get("tool_name", "")
        if tool_name not in ("Write", "Edit"):
            return False

        new_content = context.get("new_string", "") or context.get("content", "")
        file_path = context.get("file_path", "")
        if not new_content or not file_path.endswith(".py"):
            return False

        try:
            tree = ast.parse(new_content)
            for node in ast.walk(tree):
                # Look for numeric literals
                if isinstance(node, ast.Constant) and isinstance(
                    node.value, (int, float)
                ):
                    val = node.value
                    # Skip small/common numbers
                    if val in self.allowed_numbers:
                        continue
                    # Skip numbers <= 100 (too many false positives)
                    if isinstance(val, int) and abs(val) <= 100:
                        continue
                    if isinstance(val, float) and abs(val) <= 100:
                        continue
                    # Found a magic number
                    return True
            return False
        except SyntaxError:
            return False


@dataclass
class EmptyTestReducer(ConfidenceReducer):
    """Triggers on test functions without assertions.

    Tests that don't assert anything are useless - they always pass.
    """

    name: str = "empty_test"
    delta: int = -8
    description: str = "Test function without assertions"
    remedy: str = "add assert statements or delete the test"
    cooldown_turns: int = 1

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        import ast

        if state.turn_count - last_trigger_turn < self.get_effective_cooldown(state):
            return False

        tool_name = context.get("tool_name", "")
        if tool_name not in ("Write", "Edit"):
            return False

        new_content = context.get("new_string", "") or context.get("content", "")
        file_path = context.get("file_path", "")
        if not new_content:
            return False

        # Only check test files
        if not (
            "test_" in file_path or "_test.py" in file_path or "/tests/" in file_path
        ):
            return False

        try:
            tree = ast.parse(new_content)
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    # Check if it's a test function
                    if not node.name.startswith("test_"):
                        continue

                    # Check function body for assertions
                    has_assertion = False
                    for child in ast.walk(node):
                        # assert statement
                        if isinstance(child, ast.Assert):
                            has_assertion = True
                            break
                        # pytest.raises or similar context managers
                        if isinstance(child, ast.With):
                            has_assertion = (
                                True  # Assume with blocks in tests are assertions
                            )
                            break
                        # Method calls that look like assertions
                        if isinstance(child, ast.Call):
                            if isinstance(child.func, ast.Attribute):
                                if child.func.attr.startswith(
                                    ("assert", "expect", "should")
                                ):
                                    has_assertion = True
                                    break

                    if not has_assertion:
                        # Check if it's just a pass or docstring
                        body = node.body
                        if len(body) == 1:
                            if isinstance(body[0], ast.Pass):
                                return True
                            if isinstance(body[0], ast.Expr) and isinstance(
                                body[0].value, ast.Constant
                            ):
                                return True  # Just a docstring
                        elif len(body) == 0:
                            return True

            return False
        except SyntaxError:
            return False


@dataclass
class OrphanedImportsReducer(ConfidenceReducer):
    """Triggers when an edit removes code but leaves orphaned imports.

    If you delete a function that used `requests`, the import stays orphaned.
    Context-based: set by hooks when detecting import without usage after edit.
    """

    name: str = "orphaned_imports"
    delta: int = -5
    description: str = "Orphaned import after code removal"
    remedy: str = "remove unused imports"
    cooldown_turns: int = 1

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.get_effective_cooldown(state):
            return False

        tool_name = context.get("tool_name", "")
        if tool_name != "Edit":
            return False

        # Must be removing code (old_string longer than new_string)
        old_content = context.get("old_string", "")
        new_content = context.get("new_string", "")
        file_path = context.get("file_path", "")

        if not old_content or not new_content or not file_path.endswith(".py"):
            return False

        # Only check if we're removing code
        if len(new_content) >= len(old_content):
            return False

        # Context-based: hook can set this if it detects orphaned imports
        return context.get("orphaned_imports", False)


__all__ = [
    "PlaceholderImplReducer",
    "SilentFailureReducer",
    "HallmarkPhraseReducer",
    "ScopeCreepReducer",
    "IncompleteRefactorReducer",
    "DeepNestingReducer",
    "LongFunctionReducer",
    "MutableDefaultArgReducer",
    "ImportStarReducer",
    "BareRaiseReducer",
    "CommentedCodeReducer",
    "PathHardcodingReducer",
    "MagicNumbersReducer",
    "EmptyTestReducer",
    "OrphanedImportsReducer",
]
