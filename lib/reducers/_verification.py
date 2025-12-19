#!/usr/bin/env python3
"""Confidence reducers: verification category."""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ._base import ConfidenceReducer

if TYPE_CHECKING:
    from session_state import SessionState


# Threshold for unverified edits
VERIFICATION_THRESHOLD = 5  # Edits before verification required


@dataclass
class UnbackedVerificationClaimReducer(ConfidenceReducer):
    """Triggers when claiming verification without matching tool log.

    Detects "verification theater" - claims like "tests passed" or "lint clean"
    without corresponding tool execution in recent turns.
    """

    name: str = "unbacked_verification"
    delta: int = -15
    description: str = "Claimed verification without tool evidence"
    remedy: str = "run the actual test/lint command"
    cooldown_turns: int = 3

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.get_effective_cooldown(state):
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
    remedy: str = "verify with test after claiming fixed"
    cooldown_turns: int = 3

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.get_effective_cooldown(state):
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
    remedy: str = "do actual work between git commands"
    cooldown_turns: int = 5

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.get_effective_cooldown(state):
            return False
        return context.get("git_spam", False)


# =============================================================================
# CODE QUALITY REDUCERS (Catch incomplete/sloppy work)
# =============================================================================


@dataclass
class UnverifiedEditsReducer(ConfidenceReducer):
    """Triggers when too many consecutive edits without verification.

    Prevents edit spam without running tests/lint to validate changes.
    """

    name: str = "unverified_edits"
    delta: int = -5
    description: str = f">{VERIFICATION_THRESHOLD} edits without verification"
    remedy: str = "run pytest, ruff check, or tsc"
    cooldown_turns: int = 3

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.get_effective_cooldown(state):
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
class TestIgnoredReducer(ConfidenceReducer):
    """Triggers when test files are modified but tests aren't run.

    If you edit test_*.py or *.test.ts but don't run pytest/jest afterward,
    you're probably not verifying your changes.
    """

    name: str = "test_ignored"
    delta: int = -5
    description: str = "Modified test files without running tests"
    remedy: str = "run pytest/jest after editing tests"
    cooldown_turns: int = 5

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.get_effective_cooldown(state):
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
    remedy: str = "add or run tests for changed code"
    cooldown_turns: int = 5

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.get_effective_cooldown(state):
            return False
        # Context-based: hook sets this when prod code edited without tests
        return context.get("change_without_test", False)


# =============================================================================
# VERIFICATION BUNDLING REDUCER (v4.7)
# =============================================================================


VERIFICATION_THRESHOLD = 5  # Edits before verification required


@dataclass
class TestsExistNotRunReducer(ConfidenceReducer):
    """Triggers when tests exist in project but weren't run after code changes.

    After modifying 3+ files in a project that has tests, if no test framework
    has been executed this session, this reducer fires. Encourages running
    tests early and often.
    """

    name: str = "tests_exist_not_run"
    delta: int = -8
    description: str = "Tests exist but weren't run after code changes"
    remedy: str = "run pytest/jest/vitest to verify changes don't break existing tests"
    cooldown_turns: int = 10

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.get_effective_cooldown(state):
            return False

        # Check if tests were run this session
        test_frameworks_run = getattr(state, "test_frameworks_run", set())
        if test_frameworks_run:
            return False  # Tests were run at some point

        # Check if we've modified enough files to warrant test run
        files_modified = getattr(state, "files_modified_since_test", set())
        if len(files_modified) < 3:
            return False  # Not enough changes yet

        # Check if project has tests (from context or cached)
        has_tests = context.get("project_has_tests", False)
        if not has_tests:
            # Try cached value from state
            project_test_files = getattr(state, "project_test_files", None)
            if project_test_files is None or not any(project_test_files.values()):
                return False

        return True


@dataclass
class OrphanedTestCreationReducer(ConfidenceReducer):
    """Triggers when a test file is created but not executed.

    Creating tests without running them is technical debt waiting to happen.
    Tests that are never run may be broken from the start.
    """

    name: str = "orphaned_test_creation"
    delta: int = -8
    description: str = "Test file created but not executed"
    remedy: str = "run the test file you just created to verify it works"
    cooldown_turns: int = 3

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.get_effective_cooldown(state):
            return False

        # Check for test files created but not run
        test_files_created = getattr(state, "test_files_created", {})
        for path, info in test_files_created.items():
            if not info.get("executed", False):
                # Test was created but not executed
                created_turn = info.get("created_turn", 0)
                # Give some grace period (3 turns) before penalizing
                if state.turn_count - created_turn >= 3:
                    return True

        return False


@dataclass
class PreCommitNoTestsReducer(ConfidenceReducer):
    """Triggers when attempting to commit without running tests.

    If the project has tests and code was modified, tests should be run
    before committing. This is a pre-commit quality gate.
    """

    name: str = "pre_commit_no_tests"
    delta: int = -10
    description: str = "Committing without running tests"
    remedy: str = "run tests before committing to catch regressions"
    cooldown_turns: int = 1

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.get_effective_cooldown(state):
            return False

        # Only trigger on git commit commands
        tool_name = context.get("tool_name", "")
        if tool_name != "Bash":
            return False

        command = context.get("bash_command", "")
        if "git commit" not in command:
            return False

        # Check if tests were run this session
        test_frameworks_run = getattr(state, "test_frameworks_run", set())
        if test_frameworks_run:
            return False  # Tests were run

        # Check if project has tests
        has_tests = context.get("project_has_tests", False)
        if not has_tests:
            project_test_files = getattr(state, "project_test_files", None)
            if project_test_files is None or not any(project_test_files.values()):
                return False  # No tests to run

        # Check if any code files were modified
        files_modified = getattr(state, "files_modified_since_test", set())
        if not files_modified:
            return False  # No code changes

        return True


# Registry of all reducers
# All reducers now ENABLED with proper detection mechanisms


__all__ = [
    "UnbackedVerificationClaimReducer",
    "FixedWithoutChainReducer",
    "GitSpamReducer",
    "UnverifiedEditsReducer",
    "TestIgnoredReducer",
    "ChangeWithoutTestReducer",
    "TestsExistNotRunReducer",
    "OrphanedTestCreationReducer",
    "PreCommitNoTestsReducer",
]
