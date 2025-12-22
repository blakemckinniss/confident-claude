#!/usr/bin/env python3
"""
Integration tests for delegation circuit breakers.

Tests that hard blocks fire correctly and agent spawning resets counters.
"""

import pytest
import sys
from pathlib import Path

# Add hooks to path
sys.path.insert(0, str(Path(__file__).parent.parent / "hooks"))

from gates._delegation import (
    check_exploration_circuit_breaker,
    check_debug_circuit_breaker,
    check_research_circuit_breaker,
    check_review_circuit_breaker,
    check_docs_skill_circuit_breaker,
    check_commit_skill_circuit_breaker,
    check_think_skill_circuit_breaker,
)


class MockSessionState:
    """Mock SessionState for testing."""

    def __init__(self):
        self.turn_count = 10
        self.consecutive_exploration_calls = 0
        self.consecutive_research_calls = 0
        self.recent_explore_agent_turn = -100
        self.recent_debugger_agent_turn = -100
        self.recent_researcher_agent_turn = -100
        self.recent_reviewer_agent_turn = -100
        self.consecutive_tool_failures = 0
        self.edit_counts = {}
        self.files_edited = []
        self.debug_mode_active = False


class TestExplorationCircuitBreaker:
    """Tests for exploration circuit breaker."""

    def test_allows_first_few_calls(self):
        """First 3 exploration calls should be allowed."""
        state = MockSessionState()
        state.consecutive_exploration_calls = 2

        result = check_exploration_circuit_breaker(
            {"tool_name": "Grep", "tool_input": {}}, state
        )

        assert result.decision != "deny"

    def test_warns_at_threshold(self):
        """Should warn at 3 consecutive calls."""
        state = MockSessionState()
        state.consecutive_exploration_calls = 3

        result = check_exploration_circuit_breaker(
            {"tool_name": "Grep", "tool_input": {}}, state
        )

        assert result.decision == "approve"
        assert result.context and "exploration calls" in result.context.lower()

    def test_blocks_at_hard_limit(self):
        """Should BLOCK at 4+ consecutive calls."""
        state = MockSessionState()
        state.consecutive_exploration_calls = 4

        result = check_exploration_circuit_breaker(
            {"tool_name": "Glob", "tool_input": {}}, state
        )

        assert result.decision == "deny"
        assert "BLOCKED" in result.reason

    def test_allows_after_recent_agent(self):
        """Should allow if Explore agent was used recently."""
        state = MockSessionState()
        state.consecutive_exploration_calls = 10
        state.recent_explore_agent_turn = 5  # 5 turns ago (within 8)

        result = check_exploration_circuit_breaker(
            {"tool_name": "Read", "tool_input": {}}, state
        )

        assert result.decision != "deny"

    def test_sudo_bypass(self):
        """SUDO EXPLORE should bypass the block."""
        state = MockSessionState()
        state.consecutive_exploration_calls = 10
        state.sudo_explore = True

        result = check_exploration_circuit_breaker(
            {"tool_name": "Grep", "tool_input": {}}, state
        )

        assert result.decision != "deny"

    def test_whitelisted_read_paths(self):
        """Reading config/memory/rules files should be allowed."""
        state = MockSessionState()
        state.consecutive_exploration_calls = 10

        for path in [
            "/home/user/.claude/CLAUDE.md",
            "/home/user/.claude/rules/confidence.md",
            "/home/user/.claude/memory/test.md",
            "/home/user/project/config.json",
        ]:
            result = check_exploration_circuit_breaker(
                {"tool_name": "Read", "tool_input": {"file_path": path}}, state
            )
            assert result.decision != "deny", f"Should allow reading {path}"


class TestDebugCircuitBreaker:
    """Tests for debug circuit breaker."""

    def test_allows_first_edits(self):
        """First 2 edits to a file should be allowed."""
        state = MockSessionState()
        # v2 format: low edit count, no failures = allowed
        state.edit_counts_v2 = {
            "/path/to/file.py": {"count": 2, "last_turn": 10, "failures": 0}
        }
        state.consecutive_tool_failures = 0

        result = check_debug_circuit_breaker(
            {"tool_name": "Edit", "tool_input": {"file_path": "/path/to/file.py"}},
            state,
        )

        assert result.decision != "deny"

    def test_warns_at_threshold_with_failures(self):
        """Should warn at 4 edits with failures (v2 thresholds)."""
        state = MockSessionState()
        # v2 format: {path: {count, last_turn, failures}}
        state.edit_counts_v2 = {
            "/path/to/file.py": {"count": 4, "last_turn": 10, "failures": 2}
        }
        state.consecutive_tool_failures = 2

        result = check_debug_circuit_breaker(
            {"tool_name": "Edit", "tool_input": {"file_path": "/path/to/file.py"}},
            state,
        )

        assert result.decision == "approve"
        assert result.context and "edits" in result.context.lower()

    def test_blocks_debug_loop(self):
        """Should BLOCK at 5+ edits WITH failures (v2 - smarter detection)."""
        state = MockSessionState()
        # v2 format: requires BOTH high edit count AND failures
        state.edit_counts_v2 = {
            "/path/to/file.py": {"count": 5, "last_turn": 10, "failures": 2}
        }
        state.consecutive_tool_failures = 2

        result = check_debug_circuit_breaker(
            {"tool_name": "Edit", "tool_input": {"file_path": "/path/to/file.py"}},
            state,
        )

        assert result.decision == "deny"
        assert "BLOCKED" in result.reason

    def test_allows_after_debugger_agent(self):
        """Should allow if debugger agent was used recently."""
        state = MockSessionState()
        # v2 format: would normally block (high count + failures)
        state.edit_counts_v2 = {
            "/path/to/file.py": {"count": 10, "last_turn": 10, "failures": 5}
        }
        state.consecutive_tool_failures = 5
        state.recent_debugger_agent_turn = 5  # 5 turns ago (within 10)

        result = check_debug_circuit_breaker(
            {"tool_name": "Edit", "tool_input": {"file_path": "/path/to/file.py"}},
            state,
        )

        assert result.decision != "deny"

    def test_sudo_bypass(self):
        """SUDO DEBUG should bypass the block."""
        state = MockSessionState()
        # v2 format: would normally block (high count + failures)
        state.edit_counts_v2 = {
            "/path/to/file.py": {"count": 10, "last_turn": 10, "failures": 5}
        }
        state.consecutive_tool_failures = 5
        state.sudo_debug = True

        result = check_debug_circuit_breaker(
            {"tool_name": "Edit", "tool_input": {"file_path": "/path/to/file.py"}},
            state,
        )

        assert result.decision != "deny"


class TestResearchCircuitBreaker:
    """Tests for research circuit breaker."""

    def test_allows_first_calls(self):
        """First 2 research calls should be allowed."""
        state = MockSessionState()
        state.consecutive_research_calls = 1

        result = check_research_circuit_breaker(
            {"tool_name": "WebSearch", "tool_input": {}}, state
        )

        assert result.decision != "deny"

    def test_warns_at_threshold(self):
        """Should warn at 2 consecutive calls."""
        state = MockSessionState()
        state.consecutive_research_calls = 2

        result = check_research_circuit_breaker(
            {"tool_name": "WebSearch", "tool_input": {}}, state
        )

        assert result.decision == "approve"
        assert result.context and "research calls" in result.context.lower()

    def test_blocks_at_hard_limit(self):
        """Should BLOCK at 3+ consecutive calls."""
        state = MockSessionState()
        state.consecutive_research_calls = 3

        result = check_research_circuit_breaker(
            {"tool_name": "mcp__crawl4ai__crawl", "tool_input": {}}, state
        )

        assert result.decision == "deny"
        assert "BLOCKED" in result.reason

    def test_allows_after_researcher_agent(self):
        """Should allow if researcher agent was used recently."""
        state = MockSessionState()
        state.consecutive_research_calls = 10
        state.recent_researcher_agent_turn = 5  # 5 turns ago (within 8)

        result = check_research_circuit_breaker(
            {"tool_name": "WebSearch", "tool_input": {}}, state
        )

        assert result.decision != "deny"

    def test_sudo_bypass(self):
        """SUDO RESEARCH should bypass the block."""
        state = MockSessionState()
        state.consecutive_research_calls = 10
        state.sudo_research = True

        result = check_research_circuit_breaker(
            {"tool_name": "WebSearch", "tool_input": {}}, state
        )

        assert result.decision != "deny"


class TestReviewCircuitBreaker:
    """Tests for review circuit breaker (nudge only)."""

    def test_no_nudge_under_threshold(self):
        """Should not nudge under 5 files edited."""
        state = MockSessionState()
        state.files_edited = ["a.py", "b.py", "c.py", "d.py"]

        result = check_review_circuit_breaker(
            {"tool_name": "Edit", "tool_input": {}}, state
        )

        # No message expected
        assert result.context is None or "files edited" not in result.context.lower()

    def test_nudges_at_threshold(self):
        """Should nudge at 5+ files edited."""
        state = MockSessionState()
        state.files_edited = ["a.py", "b.py", "c.py", "d.py", "e.py"]

        result = check_review_circuit_breaker(
            {"tool_name": "Edit", "tool_input": {}}, state
        )

        assert result.decision == "approve"  # Nudge, not block
        assert result.context and "files edited" in result.context.lower()

    def test_no_nudge_after_recent_reviewer(self):
        """Should not nudge if reviewer was used recently."""
        state = MockSessionState()
        state.files_edited = ["a.py", "b.py", "c.py", "d.py", "e.py", "f.py"]
        state.recent_reviewer_agent_turn = 5  # 5 turns ago (within 20)

        result = check_review_circuit_breaker(
            {"tool_name": "Edit", "tool_input": {}}, state
        )

        assert result.context is None or "files edited" not in result.context.lower()


class TestDocsSkillCircuitBreaker:
    """Tests for /docs skill circuit breaker."""

    def test_allows_non_doc_searches(self):
        """Non-library doc searches should be allowed."""
        state = MockSessionState()
        state.lib_doc_searches = 0

        result = check_docs_skill_circuit_breaker(
            {"tool_name": "WebSearch", "tool_input": {"query": "weather forecast"}},
            state,
        )

        assert result.decision != "deny"

    def test_warns_on_first_lib_doc_search(self):
        """Should warn on first library doc search."""
        state = MockSessionState()
        state.lib_doc_searches = 0

        result = check_docs_skill_circuit_breaker(
            {
                "tool_name": "WebSearch",
                "tool_input": {"query": "react hooks documentation"},
            },
            state,
        )

        assert result.decision == "approve"
        # First search gets a nudge
        assert result.context and "docs" in result.context.lower()

    def test_blocks_at_threshold(self):
        """Should BLOCK at 2+ library doc searches."""
        state = MockSessionState()
        state.lib_doc_searches = 1  # Already had one

        result = check_docs_skill_circuit_breaker(
            {
                "tool_name": "WebSearch",
                "tool_input": {"query": "vue documentation guide"},
            },
            state,
        )

        assert result.decision == "deny"
        assert "BLOCKED" in result.reason

    def test_allows_after_recent_docs_skill(self):
        """Should allow if /docs was used recently."""
        state = MockSessionState()
        state.lib_doc_searches = 5
        state.recent_docs_skill_turn = 5  # 5 turns ago (within 10)

        result = check_docs_skill_circuit_breaker(
            {"tool_name": "WebSearch", "tool_input": {"query": "react docs"}},
            state,
        )

        assert result.decision != "deny"

    def test_sudo_bypass(self):
        """SUDO DOCS should bypass the block."""
        state = MockSessionState()
        state.lib_doc_searches = 5
        state.sudo_docs = True

        result = check_docs_skill_circuit_breaker(
            {"tool_name": "WebSearch", "tool_input": {"query": "react documentation"}},
            state,
        )

        assert result.decision != "deny"


class TestCommitSkillCircuitBreaker:
    """Tests for /commit skill circuit breaker."""

    def test_allows_non_commit_commands(self):
        """Non-commit bash commands should be allowed."""
        state = MockSessionState()

        result = check_commit_skill_circuit_breaker(
            {"tool_name": "Bash", "tool_input": {"command": "git status"}}, state
        )

        assert result.decision != "deny"

    def test_blocks_manual_git_commit(self):
        """Should BLOCK manual git commit -m immediately."""
        state = MockSessionState()
        state.manual_commits = 0

        result = check_commit_skill_circuit_breaker(
            {
                "tool_name": "Bash",
                "tool_input": {"command": 'git commit -m "test message"'},
            },
            state,
        )

        assert result.decision == "deny"
        assert "BLOCKED" in result.reason

    def test_allows_after_recent_commit_skill(self):
        """Should allow if /commit was used recently."""
        state = MockSessionState()
        state.manual_commits = 5
        state.recent_commit_skill_turn = 7  # 3 turns ago (within 5)

        result = check_commit_skill_circuit_breaker(
            {
                "tool_name": "Bash",
                "tool_input": {"command": 'git commit -m "test"'},
            },
            state,
        )

        assert result.decision != "deny"

    def test_sudo_bypass(self):
        """SUDO COMMIT should bypass the block."""
        state = MockSessionState()
        state.manual_commits = 5
        state.sudo_commit = True

        result = check_commit_skill_circuit_breaker(
            {
                "tool_name": "Bash",
                "tool_input": {"command": 'git commit -m "test"'},
            },
            state,
        )

        assert result.decision != "deny"


class TestThinkSkillCircuitBreaker:
    """Tests for /think skill nudge."""

    def test_no_nudge_without_debug_mode(self):
        """Should not nudge if not in debug mode."""
        state = MockSessionState()
        state.debug_mode_active = False
        state.consecutive_debug_attempts = 5

        result = check_think_skill_circuit_breaker(
            {"tool_name": "Edit", "tool_input": {}}, state
        )

        # No nudge expected
        assert result.context is None or "think" not in result.context.lower()

    def test_no_nudge_under_threshold(self):
        """Should not nudge under 3 debug attempts."""
        state = MockSessionState()
        state.debug_mode_active = True
        state.consecutive_debug_attempts = 2

        result = check_think_skill_circuit_breaker(
            {"tool_name": "Edit", "tool_input": {}}, state
        )

        assert result.context is None or "think" not in result.context.lower()

    def test_nudges_at_threshold(self):
        """Should nudge at 3+ debug attempts in debug mode."""
        state = MockSessionState()
        state.debug_mode_active = True
        state.consecutive_debug_attempts = 3

        result = check_think_skill_circuit_breaker(
            {"tool_name": "Edit", "tool_input": {}}, state
        )

        assert result.decision == "approve"  # Nudge, not block
        assert result.context and "think" in result.context.lower()

    def test_no_nudge_after_recent_think(self):
        """Should not nudge if /think was used recently."""
        state = MockSessionState()
        state.debug_mode_active = True
        state.consecutive_debug_attempts = 5
        state.recent_think_skill_turn = 5  # 5 turns ago (within 8)

        result = check_think_skill_circuit_breaker(
            {"tool_name": "Edit", "tool_input": {}}, state
        )

        assert result.context is None or "think" not in result.context.lower()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
