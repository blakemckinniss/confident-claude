#!/usr/bin/env python3
"""Tests for agent delegation reducers (v4.26)."""

import sys
from pathlib import Path

# Add lib to path
sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

import pytest


class MockSessionState:
    """Mock session state for testing reducers."""

    def __init__(self, **kwargs):
        self.turn_count = kwargs.get("turn_count", 10)
        self.confidence = kwargs.get("confidence", 80)
        # Agent delegation tracking fields
        self.consecutive_exploration_calls = kwargs.get("consecutive_exploration_calls", 0)
        self.consecutive_research_calls = kwargs.get("consecutive_research_calls", 0)
        self.debug_mode_active = kwargs.get("debug_mode_active", False)
        self.file_edit_counts = kwargs.get("file_edit_counts", {})
        self.consecutive_tool_failures = kwargs.get("consecutive_tool_failures", 0)
        self.files_edited = kwargs.get("files_edited", [])
        self.mastermind_classification = kwargs.get("mastermind_classification", "")
        # Recent agent turns
        self.recent_explore_agent_turn = kwargs.get("recent_explore_agent_turn", -100)
        self.recent_debugger_agent_turn = kwargs.get("recent_debugger_agent_turn", -100)
        self.recent_researcher_agent_turn = kwargs.get("recent_researcher_agent_turn", -100)
        self.recent_reviewer_agent_turn = kwargs.get("recent_reviewer_agent_turn", -100)
        self.recent_plan_agent_turn = kwargs.get("recent_plan_agent_turn", -100)
        self.recent_refactorer_agent_turn = kwargs.get("recent_refactorer_agent_turn", -100)


class TestExplorationWithoutAgentReducer:
    """Test ExplorationWithoutAgentReducer."""

    def test_triggers_after_3_exploration_calls(self):
        from reducers._delegation import ExplorationWithoutAgentReducer

        reducer = ExplorationWithoutAgentReducer()
        state = MockSessionState(
            turn_count=20,
            consecutive_exploration_calls=3,  # Threshold is 3
            recent_explore_agent_turn=-100,
        )

        result = reducer.should_trigger({}, state, 0)
        assert result is True

    def test_no_trigger_when_explore_agent_used_recently(self):
        from reducers._delegation import ExplorationWithoutAgentReducer

        reducer = ExplorationWithoutAgentReducer()
        state = MockSessionState(
            turn_count=20,
            consecutive_exploration_calls=10,
            recent_explore_agent_turn=17,  # Within 5 turns
        )

        result = reducer.should_trigger({}, state, 0)
        assert result is False

    def test_no_trigger_under_threshold(self):
        from reducers._delegation import ExplorationWithoutAgentReducer

        reducer = ExplorationWithoutAgentReducer()
        state = MockSessionState(
            turn_count=20,
            consecutive_exploration_calls=2,  # Under 3 threshold
            recent_explore_agent_turn=-100,
        )

        result = reducer.should_trigger({}, state, 0)
        assert result is False


class TestDebuggingWithoutAgentReducer:
    """Test DebuggingWithoutAgentReducer."""

    def test_triggers_when_file_edited_multiple_times(self):
        from reducers._delegation import DebuggingWithoutAgentReducer

        reducer = DebuggingWithoutAgentReducer()
        state = MockSessionState(
            turn_count=20,
            file_edit_counts={"test.py": 2},  # 2+ edits to same file
            recent_debugger_agent_turn=-100,
        )

        result = reducer.should_trigger({}, state, 0)
        assert result is True

    def test_triggers_on_debug_mode_with_failure(self):
        from reducers._delegation import DebuggingWithoutAgentReducer

        reducer = DebuggingWithoutAgentReducer()
        state = MockSessionState(
            turn_count=20,
            debug_mode_active=True,
            consecutive_tool_failures=1,
            file_edit_counts={},
            recent_debugger_agent_turn=-100,
        )

        result = reducer.should_trigger({}, state, 0)
        assert result is True

    def test_no_trigger_when_debugger_agent_used_recently(self):
        from reducers._delegation import DebuggingWithoutAgentReducer

        reducer = DebuggingWithoutAgentReducer()
        state = MockSessionState(
            turn_count=20,
            file_edit_counts={"test.py": 5},
            recent_debugger_agent_turn=15,  # Within 10 turns
        )

        result = reducer.should_trigger({}, state, 0)
        assert result is False


class TestResearchWithoutAgentReducer:
    """Test ResearchWithoutAgentReducer."""

    def test_triggers_after_2_research_calls(self):
        from reducers._delegation import ResearchWithoutAgentReducer

        reducer = ResearchWithoutAgentReducer()
        state = MockSessionState(
            turn_count=20,
            consecutive_research_calls=2,  # Threshold is 2
            recent_researcher_agent_turn=-100,
        )

        result = reducer.should_trigger({}, state, 0)
        assert result is True

    def test_no_trigger_when_researcher_agent_used_recently(self):
        from reducers._delegation import ResearchWithoutAgentReducer

        reducer = ResearchWithoutAgentReducer()
        state = MockSessionState(
            turn_count=20,
            consecutive_research_calls=5,
            recent_researcher_agent_turn=17,  # Within 5 turns
        )

        result = reducer.should_trigger({}, state, 0)
        assert result is False


class TestPlanningWithoutAgentReducer:
    """Test PlanningWithoutAgentReducer."""

    def test_triggers_on_complex_task_with_edits(self):
        from reducers._delegation import PlanningWithoutAgentReducer

        reducer = PlanningWithoutAgentReducer()
        state = MockSessionState(
            turn_count=20,
            mastermind_classification="complex",
            files_edited=["a.py", "b.py"],  # 2+ files
            recent_plan_agent_turn=-100,
        )

        result = reducer.should_trigger({}, state, 0)
        assert result is True

    def test_no_trigger_when_plan_agent_used_recently(self):
        from reducers._delegation import PlanningWithoutAgentReducer

        reducer = PlanningWithoutAgentReducer()
        state = MockSessionState(
            turn_count=50,
            mastermind_classification="complex",
            files_edited=["a.py", "b.py"],
            recent_plan_agent_turn=25,  # Within 30 turns
        )

        result = reducer.should_trigger({}, state, 0)
        assert result is False

    def test_no_trigger_on_non_complex_task(self):
        from reducers._delegation import PlanningWithoutAgentReducer

        reducer = PlanningWithoutAgentReducer()
        state = MockSessionState(
            turn_count=20,
            mastermind_classification="trivial",
            files_edited=["a.py", "b.py", "c.py"],
            recent_plan_agent_turn=-100,
        )

        result = reducer.should_trigger({}, state, 0)
        assert result is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
