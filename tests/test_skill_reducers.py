#!/usr/bin/env python3
"""Tests for skill enforcement reducers (v4.27)."""

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
        # Skill tracking fields
        self.recent_docs_skill_turn = kwargs.get("recent_docs_skill_turn", -100)
        self.recent_think_skill_turn = kwargs.get("recent_think_skill_turn", -100)
        self.recent_commit_skill_turn = kwargs.get("recent_commit_skill_turn", -100)
        self.recent_verify_skill_turn = kwargs.get("recent_verify_skill_turn", -100)
        self.recent_audit_turn = kwargs.get("recent_audit_turn", -100)
        self.recent_void_turn = kwargs.get("recent_void_turn", -100)
        self.research_for_library_docs = kwargs.get("research_for_library_docs", False)
        self.consecutive_debug_attempts = kwargs.get("consecutive_debug_attempts", 0)
        self.consecutive_code_file_reads = kwargs.get("consecutive_code_file_reads", 0)
        self.framework_files_edited = kwargs.get("framework_files_edited", [])
        self.serena_active = kwargs.get("serena_active", False)


class TestResearchWithoutDocsSkillReducer:
    """Test ResearchWithoutDocsSkillReducer."""

    def test_triggers_when_researching_library_docs(self):
        from reducers._skills import ResearchWithoutDocsSkillReducer

        reducer = ResearchWithoutDocsSkillReducer()
        state = MockSessionState(
            turn_count=20,
            research_for_library_docs=True,
            recent_docs_skill_turn=-100,
        )

        result = reducer.should_trigger({}, state, 0)
        assert result is True

    def test_no_trigger_when_docs_skill_used_recently(self):
        from reducers._skills import ResearchWithoutDocsSkillReducer

        reducer = ResearchWithoutDocsSkillReducer()
        state = MockSessionState(
            turn_count=20,
            research_for_library_docs=True,
            recent_docs_skill_turn=15,  # Used 5 turns ago
        )

        result = reducer.should_trigger({}, state, 0)
        assert result is False

    def test_no_trigger_without_library_research(self):
        from reducers._skills import ResearchWithoutDocsSkillReducer

        reducer = ResearchWithoutDocsSkillReducer()
        state = MockSessionState(
            turn_count=20,
            research_for_library_docs=False,
        )

        result = reducer.should_trigger({}, state, 0)
        assert result is False


class TestDebuggingWithoutThinkSkillReducer:
    """Test DebuggingWithoutThinkSkillReducer."""

    def test_triggers_after_3_debug_attempts(self):
        from reducers._skills import DebuggingWithoutThinkSkillReducer

        reducer = DebuggingWithoutThinkSkillReducer()
        state = MockSessionState(
            turn_count=20,
            consecutive_debug_attempts=3,
            recent_think_skill_turn=-100,
        )

        result = reducer.should_trigger({}, state, 0)
        assert result is True

    def test_no_trigger_with_recent_think_skill(self):
        from reducers._skills import DebuggingWithoutThinkSkillReducer

        reducer = DebuggingWithoutThinkSkillReducer()
        state = MockSessionState(
            turn_count=20,
            consecutive_debug_attempts=5,
            recent_think_skill_turn=10,  # Used 10 turns ago
        )

        result = reducer.should_trigger({}, state, 0)
        assert result is False

    def test_no_trigger_under_threshold(self):
        from reducers._skills import DebuggingWithoutThinkSkillReducer

        reducer = DebuggingWithoutThinkSkillReducer()
        state = MockSessionState(
            turn_count=20,
            consecutive_debug_attempts=2,  # Under threshold
        )

        result = reducer.should_trigger({}, state, 0)
        assert result is False


class TestFrameworkEditWithoutAuditReducer:
    """Test FrameworkEditWithoutAuditReducer."""

    def test_triggers_when_framework_edited_without_audit(self):
        from reducers._skills import FrameworkEditWithoutAuditReducer

        reducer = FrameworkEditWithoutAuditReducer()
        state = MockSessionState(
            turn_count=20,
            framework_files_edited=[".claude/hooks/test.py"],
            recent_audit_turn=-100,
            recent_void_turn=-100,
        )

        result = reducer.should_trigger({}, state, 0)
        assert result is True

    def test_no_trigger_when_audit_run_recently(self):
        from reducers._skills import FrameworkEditWithoutAuditReducer

        reducer = FrameworkEditWithoutAuditReducer()
        state = MockSessionState(
            turn_count=20,
            framework_files_edited=[".claude/hooks/test.py"],
            recent_audit_turn=10,  # Run 10 turns ago
            recent_void_turn=-100,
        )

        result = reducer.should_trigger({}, state, 0)
        assert result is False

    def test_no_trigger_when_void_run_recently(self):
        from reducers._skills import FrameworkEditWithoutAuditReducer

        reducer = FrameworkEditWithoutAuditReducer()
        state = MockSessionState(
            turn_count=20,
            framework_files_edited=[".claude/hooks/test.py"],
            recent_audit_turn=-100,
            recent_void_turn=10,  # Run 10 turns ago
        )

        result = reducer.should_trigger({}, state, 0)
        assert result is False


class TestCodeExplorationWithoutSerenaReducer:
    """Test CodeExplorationWithoutSerenaReducer."""

    def test_triggers_after_4_code_reads_without_serena(self):
        from reducers._skills import CodeExplorationWithoutSerenaReducer

        reducer = CodeExplorationWithoutSerenaReducer()
        state = MockSessionState(
            turn_count=20,
            consecutive_code_file_reads=4,
            serena_active=False,
        )

        result = reducer.should_trigger({}, state, 0)
        assert result is True

    def test_no_trigger_when_serena_active(self):
        from reducers._skills import CodeExplorationWithoutSerenaReducer

        reducer = CodeExplorationWithoutSerenaReducer()
        state = MockSessionState(
            turn_count=20,
            consecutive_code_file_reads=10,
            serena_active=True,
        )

        result = reducer.should_trigger({}, state, 0)
        assert result is False

    def test_no_trigger_under_threshold(self):
        from reducers._skills import CodeExplorationWithoutSerenaReducer

        reducer = CodeExplorationWithoutSerenaReducer()
        state = MockSessionState(
            turn_count=20,
            consecutive_code_file_reads=3,  # Under threshold
            serena_active=False,
        )

        result = reducer.should_trigger({}, state, 0)
        assert result is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
