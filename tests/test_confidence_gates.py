#!/usr/bin/env python3
"""
Tests for confidence gate subagent bypasses (v4.32).

Tests that subagents (fresh spawns with low turn count) bypass gates
that would otherwise block them due to inherited parent state.
"""

import sys
from pathlib import Path

# Add hooks to path
sys.path.insert(0, str(Path(__file__).parent.parent / "hooks"))

from gates._confidence import (
    _is_subagent_confidence,
    check_confidence_tool_gate,
    check_integration_gate,
)


class MockSessionState:
    """Mock SessionState for testing."""

    def __init__(self):
        self.turn_count = 10
        self.confidence = 75
        self.pending_integration_greps = []
        self.consecutive_blocks = {}  # Required by track_block
        self.last_block_turn = 0  # Required by track_block

    def set(self, key, value):
        setattr(self, key, value)


class TestIsSubagentConfidence:
    """Tests for _is_subagent_confidence helper."""

    def test_detects_fresh_agent_turn_1(self):
        """Turn 1 should be detected as subagent."""
        state = MockSessionState()
        state.turn_count = 1
        assert _is_subagent_confidence(state) is True

    def test_detects_fresh_agent_turn_2(self):
        """Turn 2 should be detected as subagent."""
        state = MockSessionState()
        state.turn_count = 2
        assert _is_subagent_confidence(state) is True

    def test_detects_fresh_agent_turn_3(self):
        """Turn 3 should be detected as subagent."""
        state = MockSessionState()
        state.turn_count = 3
        assert _is_subagent_confidence(state) is True

    def test_not_subagent_turn_4(self):
        """Turn 4+ should NOT be detected as subagent."""
        state = MockSessionState()
        state.turn_count = 4
        assert _is_subagent_confidence(state) is False

    def test_not_subagent_turn_10(self):
        """Turn 10 should NOT be detected as subagent."""
        state = MockSessionState()
        state.turn_count = 10
        assert _is_subagent_confidence(state) is False


class TestConfidenceToolGateSubagentBypass:
    """Tests for confidence_tool_gate subagent bypass."""

    def test_subagent_bypasses_low_confidence(self):
        """Fresh subagent should bypass even with low confidence."""
        state = MockSessionState()
        state.turn_count = 2
        state.confidence = 20  # Very low - would normally block

        result = check_confidence_tool_gate(
            {"tool_name": "Edit", "tool_input": {"file_path": "/tmp/test.py"}}, state
        )

        # Should approve due to subagent bypass
        assert result.decision == "approve"

    def test_subagent_bypasses_at_turn_1(self):
        """Turn 1 subagent should bypass."""
        state = MockSessionState()
        state.turn_count = 1
        state.confidence = 15

        result = check_confidence_tool_gate(
            {"tool_name": "Write", "tool_input": {"file_path": "/tmp/new.py"}}, state
        )

        assert result.decision == "approve"

    def test_no_bypass_at_turn_4(self):
        """Turn 4+ should NOT get subagent bypass."""
        state = MockSessionState()
        state.turn_count = 4
        state.confidence = 20  # Low enough to potentially block

        # At turn 4, gate evaluates normally - not auto-bypassed
        # Just verify the function runs without subagent bypass
        # (actual block/allow depends on confidence module)
        result = check_confidence_tool_gate(
            {"tool_name": "Edit", "tool_input": {"file_path": "/tmp/test.py"}}, state
        )
        # Result exists (no exception) - gate ran through normal path
        assert result is not None

    def test_sudo_bypass_still_works(self):
        """SUDO bypass should work at any turn count."""
        state = MockSessionState()
        state.turn_count = 50
        state.confidence = 10

        result = check_confidence_tool_gate(
            {
                "tool_name": "Edit",
                "tool_input": {"file_path": "/tmp/test.py"},
                "_sudo_bypass": True,
            },
            state,
        )

        assert result.decision == "approve"


class TestIntegrationGateSubagentBypass:
    """Tests for integration_gate subagent bypass."""

    def test_subagent_bypasses_pending_greps(self):
        """Fresh subagent should bypass even with pending greps from parent."""
        state = MockSessionState()
        state.turn_count = 2
        state.pending_integration_greps = [{"symbol": "test_func", "turn": 1}]

        result = check_integration_gate(
            {"tool_name": "Edit", "tool_input": {"file_path": "/tmp/test.py"}}, state
        )

        # Should approve due to subagent bypass
        assert result.decision == "approve"

    def test_subagent_bypasses_at_turn_3(self):
        """Turn 3 subagent should bypass."""
        state = MockSessionState()
        state.turn_count = 3
        state.pending_integration_greps = [
            {"symbol": "func_a", "turn": 1},
            {"symbol": "func_b", "turn": 2},
        ]

        result = check_integration_gate(
            {"tool_name": "Write", "tool_input": {"file_path": "/tmp/new.py"}}, state
        )

        assert result.decision == "approve"

    def test_no_bypass_at_turn_4(self):
        """Turn 4+ should NOT get subagent bypass."""
        state = MockSessionState()
        state.turn_count = 4
        # Even with empty pending greps, should go through normal path
        state.pending_integration_greps = []

        result = check_integration_gate(
            {"tool_name": "Edit", "tool_input": {"file_path": "/tmp/test.py"}}, state
        )

        # Should still approve (no pending greps) but via normal path
        assert result.decision == "approve"
