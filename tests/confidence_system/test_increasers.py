"""Tests for confidence increasers.

Increasers apply rewards for evidence-based work.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "lib"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "hooks"))

from _fixtures import MockSessionState

from _confidence_increasers import (
    PassedTestsIncreaser,
    BuildSuccessIncreaser,
    LintPassIncreaser,
    ProductiveBashIncreaser,
    MemoryConsultIncreaser,
    FileReadIncreaser,
    GitExploreIncreaser,
    AskUserIncreaser,
    BeadCreateIncreaser,
    RulesUpdateIncreaser,
    UserOkIncreaser,
    TrustRegainedIncreaser,
    ResearchIncreaser,
    CustomScriptIncreaser,
    SearchToolIncreaser,
    SmallDiffIncreaser,
    ParallelToolsIncreaser,
    EfficientSearchIncreaser,
    BatchFixIncreaser,
    DirectActionIncreaser,
    ChainedCommandsIncreaser,
    PremiseChallengeIncreaser,
    TargetedReadIncreaser,
    SubagentDelegationIncreaser,
)
from _confidence_constants import FARMABLE_INCREASERS
from confidence import apply_increasers


class TestPassedTestsIncreaser:
    """Tests for PassedTestsIncreaser."""

    def test_triggers_on_pytest_success(self):
        # Arrange
        increaser = PassedTestsIncreaser()
        state = MockSessionState()
        state.turn_count = 10
        state.commands_succeeded = [
            {"command": "pytest tests/", "output": "5 passed in 0.5s"}
        ]
        context = {}

        # Act
        should_trigger = increaser.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is True

    def test_triggers_via_context_flag(self):
        # Arrange
        increaser = PassedTestsIncreaser()
        state = MockSessionState()
        state.turn_count = 10
        context = {"tests_passed": True}

        # Act
        should_trigger = increaser.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is True

    def test_does_not_trigger_without_test_commands(self):
        # Arrange
        increaser = PassedTestsIncreaser()
        state = MockSessionState()
        state.turn_count = 10
        state.commands_succeeded = [{"command": "ls -la", "output": "file1.txt"}]
        context = {}

        # Act
        should_trigger = increaser.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is False


class TestBuildSuccessIncreaser:
    """Tests for BuildSuccessIncreaser."""

    def test_triggers_on_npm_build_success(self):
        # Arrange
        increaser = BuildSuccessIncreaser()
        state = MockSessionState()
        state.turn_count = 10
        state.commands_succeeded = [
            {"command": "npm run build", "output": "Build completed successfully"}
        ]
        context = {}

        # Act
        should_trigger = increaser.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is True

    def test_triggers_via_context_flag(self):
        # Arrange
        increaser = BuildSuccessIncreaser()
        state = MockSessionState()
        state.turn_count = 10
        context = {"build_succeeded": True}

        # Act
        should_trigger = increaser.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is True


class TestLintPassIncreaser:
    """Tests for LintPassIncreaser."""

    def test_triggers_on_ruff_clean(self):
        # Arrange
        increaser = LintPassIncreaser()
        state = MockSessionState()
        state.turn_count = 10
        state.commands_succeeded = [{"command": "ruff check src/", "output": ""}]
        context = {}

        # Act
        should_trigger = increaser.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is True

    def test_triggers_via_context_flag(self):
        # Arrange
        increaser = LintPassIncreaser()
        state = MockSessionState()
        state.turn_count = 10
        context = {"lint_passed": True}

        # Act
        should_trigger = increaser.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is True


class TestProductiveBashIncreaser:
    """Tests for ProductiveBashIncreaser - uses context flag only."""

    def test_triggers_when_productive_bash_flag_set(self):
        # Arrange
        increaser = ProductiveBashIncreaser()
        state = MockSessionState()
        state.turn_count = 10
        context = {"productive_bash": True}

        # Act
        should_trigger = increaser.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is True

    def test_does_not_trigger_without_flag(self):
        # Arrange
        increaser = ProductiveBashIncreaser()
        state = MockSessionState()
        state.turn_count = 10
        context = {}

        # Act
        should_trigger = increaser.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is False

    def test_does_not_trigger_when_flag_false(self):
        # Arrange
        increaser = ProductiveBashIncreaser()
        state = MockSessionState()
        state.turn_count = 10
        context = {"productive_bash": False}

        # Act
        should_trigger = increaser.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is False


class TestMemoryConsultIncreaser:
    """Tests for MemoryConsultIncreaser - consulting persistent memory."""

    def test_triggers_when_memory_consulted_flag_set(self):
        # Arrange
        increaser = MemoryConsultIncreaser()
        state = MockSessionState()
        state.turn_count = 10
        context = {"memory_consulted": True}

        # Act
        should_trigger = increaser.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is True

    def test_does_not_trigger_without_flag(self):
        # Arrange
        increaser = MemoryConsultIncreaser()
        state = MockSessionState()
        state.turn_count = 10
        context = {}

        # Act
        should_trigger = increaser.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is False

    def test_respects_cooldown(self):
        # Arrange
        increaser = MemoryConsultIncreaser()
        state = MockSessionState()
        state.turn_count = 3
        context = {"memory_consulted": True}

        # Act - last trigger was turn 2, cooldown is 2 turns
        should_trigger = increaser.should_trigger(context, state, 2)

        # Assert
        assert should_trigger is False


class TestFileReadIncreaser:
    """Tests for FileReadIncreaser - reading files for evidence."""

    def test_triggers_when_files_read(self):
        # Arrange
        increaser = FileReadIncreaser()
        state = MockSessionState()
        state.turn_count = 10
        context = {"files_read_count": 3}

        # Act
        should_trigger = increaser.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is True

    def test_does_not_trigger_when_no_files_read(self):
        # Arrange
        increaser = FileReadIncreaser()
        state = MockSessionState()
        state.turn_count = 10
        context = {"files_read_count": 0}

        # Act
        should_trigger = increaser.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is False

    def test_does_not_trigger_without_count(self):
        # Arrange
        increaser = FileReadIncreaser()
        state = MockSessionState()
        state.turn_count = 10
        context = {}

        # Act
        should_trigger = increaser.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is False


class TestGitExploreIncreaser:
    """Tests for GitExploreIncreaser - exploring git history."""

    def test_triggers_when_git_explored_flag_set(self):
        # Arrange
        increaser = GitExploreIncreaser()
        state = MockSessionState()
        state.turn_count = 10
        context = {"git_explored": True}

        # Act
        should_trigger = increaser.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is True

    def test_does_not_trigger_without_flag(self):
        # Arrange
        increaser = GitExploreIncreaser()
        state = MockSessionState()
        state.turn_count = 10
        context = {}

        # Act
        should_trigger = increaser.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is False

    def test_respects_cooldown(self):
        # Arrange
        increaser = GitExploreIncreaser()
        state = MockSessionState()
        state.turn_count = 5
        context = {"git_explored": True}

        # Act - last trigger was recent
        should_trigger = increaser.should_trigger(context, state, 4)

        # Assert
        assert should_trigger is False


class TestAskUserIncreaser:
    """Tests for AskUserIncreaser - epistemic humility."""

    def test_triggers_when_asked_user_flag_set(self):
        # Arrange
        increaser = AskUserIncreaser()
        state = MockSessionState()
        state.turn_count = 10
        context = {"asked_user": True}

        # Act
        should_trigger = increaser.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is True

    def test_does_not_trigger_without_flag(self):
        # Arrange
        increaser = AskUserIncreaser()
        state = MockSessionState()
        state.turn_count = 10
        context = {}

        # Act
        should_trigger = increaser.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is False

    def test_respects_cooldown(self):
        # Arrange
        increaser = AskUserIncreaser()
        state = MockSessionState()
        state.turn_count = 10
        context = {"asked_user": True}

        # Act - cooldown is 8, last triggered 5 turns ago
        should_trigger = increaser.should_trigger(context, state, 5)

        # Assert
        assert should_trigger is False


class TestBeadCreateIncreaser:
    """Tests for BeadCreateIncreaser - task tracking."""

    def test_triggers_when_bead_created_flag_set(self):
        # Arrange
        increaser = BeadCreateIncreaser()
        state = MockSessionState()
        state.turn_count = 10
        context = {"bead_created": True}

        # Act
        should_trigger = increaser.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is True

    def test_does_not_trigger_without_flag(self):
        # Arrange
        increaser = BeadCreateIncreaser()
        state = MockSessionState()
        state.turn_count = 10
        context = {}

        # Act
        should_trigger = increaser.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is False

    def test_does_not_trigger_when_flag_false(self):
        # Arrange
        increaser = BeadCreateIncreaser()
        state = MockSessionState()
        state.turn_count = 10
        context = {"bead_created": False}

        # Act
        should_trigger = increaser.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is False


class TestRulesUpdateIncreaser:
    """Tests for RulesUpdateIncreaser - system improvement."""

    def test_triggers_when_rules_updated_flag_set(self):
        # Arrange
        increaser = RulesUpdateIncreaser()
        state = MockSessionState()
        state.turn_count = 10
        context = {"rules_updated": True}

        # Act
        should_trigger = increaser.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is True

    def test_does_not_trigger_without_flag(self):
        # Arrange
        increaser = RulesUpdateIncreaser()
        state = MockSessionState()
        state.turn_count = 10
        context = {}

        # Act
        should_trigger = increaser.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is False

    def test_respects_cooldown(self):
        # Arrange
        increaser = RulesUpdateIncreaser()
        state = MockSessionState()
        state.turn_count = 3
        context = {"rules_updated": True}

        # Act - cooldown is 1, last triggered same turn (turn 3)
        # turn_count - last_trigger_turn = 3 - 3 = 0 < 1, so should not trigger
        should_trigger = increaser.should_trigger(context, state, 3)

        # Assert
        assert should_trigger is False


class TestUserOkIncreaser:
    """Tests for UserOkIncreaser - positive user feedback on short prompts."""

    def test_triggers_on_ok_response(self):
        # Arrange
        increaser = UserOkIncreaser()
        state = MockSessionState()
        state.turn_count = 10
        context = {"prompt": "ok"}

        # Act
        should_trigger = increaser.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is True

    def test_triggers_on_thanks(self):
        # Arrange
        increaser = UserOkIncreaser()
        state = MockSessionState()
        state.turn_count = 10
        context = {"prompt": "thanks!"}

        # Act
        should_trigger = increaser.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is True

    def test_triggers_on_looks_good(self):
        # Arrange
        increaser = UserOkIncreaser()
        state = MockSessionState()
        state.turn_count = 10
        context = {"prompt": "looks good"}

        # Act
        should_trigger = increaser.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is True

    def test_does_not_trigger_on_long_prompt(self):
        # Arrange
        increaser = UserOkIncreaser()
        state = MockSessionState()
        state.turn_count = 10
        # Long prompt > 100 chars containing "ok"
        context = {"prompt": "ok " + "x" * 100}

        # Act
        should_trigger = increaser.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is False

    def test_does_not_trigger_without_pattern(self):
        # Arrange
        increaser = UserOkIncreaser()
        state = MockSessionState()
        state.turn_count = 10
        context = {"prompt": "do something"}

        # Act
        should_trigger = increaser.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is False

    def test_respects_cooldown(self):
        # Arrange
        increaser = UserOkIncreaser()
        state = MockSessionState()
        state.turn_count = 3
        context = {"prompt": "ok"}

        # Act - cooldown is 2, last triggered 1 turn ago
        should_trigger = increaser.should_trigger(context, state, 2)

        # Assert
        assert should_trigger is False


class TestTrustRegainedIncreaser:
    """Tests for TrustRegainedIncreaser - explicit trust restoration."""

    def test_triggers_on_confidence_boost_approved(self):
        # Arrange
        increaser = TrustRegainedIncreaser()
        state = MockSessionState()
        state.turn_count = 10
        context = {"prompt": "CONFIDENCE_BOOST_APPROVED"}

        # Act
        should_trigger = increaser.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is True

    def test_triggers_on_trust_regained(self):
        # Arrange
        increaser = TrustRegainedIncreaser()
        state = MockSessionState()
        state.turn_count = 10
        context = {"prompt": "trust regained, you can proceed"}

        # Act
        should_trigger = increaser.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is True

    def test_triggers_on_confidence_restored(self):
        # Arrange
        increaser = TrustRegainedIncreaser()
        state = MockSessionState()
        state.turn_count = 10
        context = {"prompt": "confidence restored"}

        # Act
        should_trigger = increaser.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is True

    def test_does_not_trigger_without_pattern(self):
        # Arrange
        increaser = TrustRegainedIncreaser()
        state = MockSessionState()
        state.turn_count = 10
        context = {"prompt": "ok go ahead"}

        # Act
        should_trigger = increaser.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is False

    def test_respects_cooldown(self):
        # Arrange
        increaser = TrustRegainedIncreaser()
        state = MockSessionState()
        state.turn_count = 6
        context = {"prompt": "CONFIDENCE_BOOST_APPROVED"}

        # Act - cooldown is 5, last triggered 3 turns ago
        should_trigger = increaser.should_trigger(context, state, 3)

        # Assert
        assert should_trigger is False


class TestResearchIncreaser:
    """Tests for ResearchIncreaser - web research performed."""

    def test_triggers_when_research_performed_flag_set(self):
        # Arrange
        increaser = ResearchIncreaser()
        state = MockSessionState()
        state.turn_count = 10
        context = {"research_performed": True}

        # Act
        should_trigger = increaser.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is True

    def test_does_not_trigger_without_flag(self):
        # Arrange
        increaser = ResearchIncreaser()
        state = MockSessionState()
        state.turn_count = 10
        context = {}

        # Act
        should_trigger = increaser.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is False

    def test_respects_cooldown(self):
        # Arrange
        increaser = ResearchIncreaser()
        state = MockSessionState()
        state.turn_count = 2
        context = {"research_performed": True}

        # Act - cooldown is 1, last triggered 0 turns ago
        should_trigger = increaser.should_trigger(context, state, 2)

        # Assert
        assert should_trigger is False


class TestCustomScriptIncreaser:
    """Tests for CustomScriptIncreaser - running ops scripts."""

    def test_triggers_when_custom_script_ran_flag_set(self):
        # Arrange
        increaser = CustomScriptIncreaser()
        state = MockSessionState()
        state.turn_count = 10
        context = {"custom_script_ran": True}

        # Act
        should_trigger = increaser.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is True

    def test_does_not_trigger_without_flag(self):
        # Arrange
        increaser = CustomScriptIncreaser()
        state = MockSessionState()
        state.turn_count = 10
        context = {}

        # Act
        should_trigger = increaser.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is False


class TestSearchToolIncreaser:
    """Tests for SearchToolIncreaser - Grep/Glob/Task usage."""

    def test_triggers_when_search_performed_flag_set(self):
        # Arrange
        increaser = SearchToolIncreaser()
        state = MockSessionState()
        state.turn_count = 10
        context = {"search_performed": True}

        # Act
        should_trigger = increaser.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is True

    def test_does_not_trigger_without_flag(self):
        # Arrange
        increaser = SearchToolIncreaser()
        state = MockSessionState()
        state.turn_count = 10
        context = {}

        # Act
        should_trigger = increaser.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is False

    def test_respects_cooldown(self):
        # Arrange
        increaser = SearchToolIncreaser()
        state = MockSessionState()
        state.turn_count = 2
        context = {"search_performed": True}

        # Act - cooldown is 1, last triggered 1 turn ago
        should_trigger = increaser.should_trigger(context, state, 2)

        # Assert
        assert should_trigger is False


class TestSmallDiffIncreaser:
    """Tests for SmallDiffIncreaser - focused changes under 400 LOC."""

    def test_triggers_when_small_diff_flag_set(self):
        # Arrange
        increaser = SmallDiffIncreaser()
        state = MockSessionState()
        state.turn_count = 10
        context = {"small_diff": True}

        # Act
        should_trigger = increaser.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is True

    def test_does_not_trigger_without_flag(self):
        # Arrange
        increaser = SmallDiffIncreaser()
        state = MockSessionState()
        state.turn_count = 10
        context = {}

        # Act
        should_trigger = increaser.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is False


class TestParallelToolsIncreaser:
    """Tests for ParallelToolsIncreaser - efficient parallel tool usage."""

    def test_triggers_when_parallel_tools_flag_set(self):
        # Arrange
        increaser = ParallelToolsIncreaser()
        state = MockSessionState()
        state.turn_count = 10
        context = {"parallel_tools": True}

        # Act
        should_trigger = increaser.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is True

    def test_does_not_trigger_without_flag(self):
        # Arrange
        increaser = ParallelToolsIncreaser()
        state = MockSessionState()
        state.turn_count = 10
        context = {}

        # Act
        should_trigger = increaser.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is False


class TestEfficientSearchIncreaser:
    """Tests for EfficientSearchIncreaser - first-try search success."""

    def test_triggers_when_efficient_search_flag_set(self):
        # Arrange
        increaser = EfficientSearchIncreaser()
        state = MockSessionState()
        state.turn_count = 10
        context = {"efficient_search": True}

        # Act
        should_trigger = increaser.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is True

    def test_does_not_trigger_without_flag(self):
        # Arrange
        increaser = EfficientSearchIncreaser()
        state = MockSessionState()
        state.turn_count = 10
        context = {}

        # Act
        should_trigger = increaser.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is False

    def test_respects_cooldown(self):
        # Arrange
        increaser = EfficientSearchIncreaser()
        state = MockSessionState()
        state.turn_count = 3
        context = {"efficient_search": True}

        # Act - cooldown is 2, last triggered 1 turn ago
        should_trigger = increaser.should_trigger(context, state, 2)

        # Assert
        assert should_trigger is False


class TestBatchFixIncreaser:
    """Tests for BatchFixIncreaser - fixing multiple issues in one edit."""

    def test_triggers_when_batch_fix_flag_set(self):
        # Arrange
        increaser = BatchFixIncreaser()
        state = MockSessionState()
        state.turn_count = 10
        context = {"batch_fix": True}

        # Act
        should_trigger = increaser.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is True

    def test_does_not_trigger_without_flag(self):
        # Arrange
        increaser = BatchFixIncreaser()
        state = MockSessionState()
        state.turn_count = 10
        context = {}

        # Act
        should_trigger = increaser.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is False


class TestDirectActionIncreaser:
    """Tests for DirectActionIncreaser - action without preamble."""

    def test_triggers_when_direct_action_flag_set(self):
        # Arrange
        increaser = DirectActionIncreaser()
        state = MockSessionState()
        state.turn_count = 10
        context = {"direct_action": True}

        # Act
        should_trigger = increaser.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is True

    def test_does_not_trigger_without_flag(self):
        # Arrange
        increaser = DirectActionIncreaser()
        state = MockSessionState()
        state.turn_count = 10
        context = {}

        # Act
        should_trigger = increaser.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is False

    def test_respects_cooldown(self):
        # Arrange
        increaser = DirectActionIncreaser()
        state = MockSessionState()
        state.turn_count = 3
        context = {"direct_action": True}

        # Act - cooldown is 2, last triggered 1 turn ago
        should_trigger = increaser.should_trigger(context, state, 2)

        # Assert
        assert should_trigger is False


class TestChainedCommandsIncreaser:
    """Tests for ChainedCommandsIncreaser - efficient command chaining."""

    def test_triggers_when_chained_commands_flag_set(self):
        # Arrange
        increaser = ChainedCommandsIncreaser()
        state = MockSessionState()
        state.turn_count = 10
        context = {"chained_commands": True}

        # Act
        should_trigger = increaser.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is True

    def test_does_not_trigger_without_flag(self):
        # Arrange
        increaser = ChainedCommandsIncreaser()
        state = MockSessionState()
        state.turn_count = 10
        context = {}

        # Act
        should_trigger = increaser.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is False


class TestPremiseChallengeIncreaser:
    """Tests for PremiseChallengeIncreaser - suggesting alternatives to building."""

    def test_triggers_when_premise_challenge_flag_set(self):
        # Arrange
        increaser = PremiseChallengeIncreaser()
        state = MockSessionState()
        state.turn_count = 10
        context = {"premise_challenge": True}

        # Act
        should_trigger = increaser.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is True

    def test_does_not_trigger_without_flag(self):
        # Arrange
        increaser = PremiseChallengeIncreaser()
        state = MockSessionState()
        state.turn_count = 10
        context = {}

        # Act
        should_trigger = increaser.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is False

    def test_respects_cooldown(self):
        # Arrange
        increaser = PremiseChallengeIncreaser()
        state = MockSessionState()
        state.turn_count = 4
        context = {"premise_challenge": True}

        # Act - cooldown is 3, last triggered 2 turns ago
        should_trigger = increaser.should_trigger(context, state, 2)

        # Assert
        assert should_trigger is False


# =============================================================================
# COOLDOWN BOUNDARY EDGE CASE TESTS
# =============================================================================


class TestApplyIncreasers:
    """Integration tests for apply_increasers function."""

    def test_returns_empty_list_when_no_increasers_trigger(self):
        # Arrange
        state = MockSessionState()
        state.turn_count = 10
        state.files_read = []
        state.increaser_triggers = {}
        context = {"tool_name": "SomeUnknownTool"}

        # Act
        triggered = apply_increasers(state, context)

        # Assert
        assert isinstance(triggered, list)


# =============================================================================
# HELPER FUNCTION TESTS
# =============================================================================


class TestTargetedReadIncreaser:
    """Tests for TargetedReadIncreaser."""

    def test_triggers_when_targeted_read_flag_set(self):
        increaser = TargetedReadIncreaser()
        state = MockSessionState()
        state.turn_count = 10

        result = increaser.should_trigger({"targeted_read": True}, state, 0)

        assert result is True

    def test_does_not_trigger_without_flag(self):
        increaser = TargetedReadIncreaser()
        state = MockSessionState()
        state.turn_count = 10

        result = increaser.should_trigger({}, state, 0)

        assert result is False

    def test_respects_cooldown(self):
        increaser = TargetedReadIncreaser()
        state = MockSessionState()
        state.turn_count = 10

        # Triggered same turn, cooldown is 1 (10 - 10 = 0 < 1)
        result = increaser.should_trigger({"targeted_read": True}, state, 10)

        assert result is False


class TestSubagentDelegationIncreaser:
    """Tests for SubagentDelegationIncreaser."""

    def test_triggers_when_delegation_flag_set(self):
        increaser = SubagentDelegationIncreaser()
        state = MockSessionState()
        state.turn_count = 10

        result = increaser.should_trigger({"subagent_delegation": True}, state, 0)

        assert result is True

    def test_does_not_trigger_without_flag(self):
        increaser = SubagentDelegationIncreaser()
        state = MockSessionState()
        state.turn_count = 10

        result = increaser.should_trigger({}, state, 0)

        assert result is False

    def test_respects_cooldown(self):
        increaser = SubagentDelegationIncreaser()
        state = MockSessionState()
        state.turn_count = 10

        # Triggered 1 turn ago, cooldown is 2
        result = increaser.should_trigger({"subagent_delegation": True}, state, 9)

        assert result is False


# =============================================================================
# FARMABLE INCREASERS CONSTANT TESTS
# =============================================================================


class TestFarmableIncreasersConstant:
    """Tests to verify FARMABLE_INCREASERS is configured correctly."""

    def test_file_read_is_farmable(self):
        assert "file_read" in FARMABLE_INCREASERS

    def test_productive_bash_is_farmable(self):
        assert "productive_bash" in FARMABLE_INCREASERS

    def test_search_tool_is_farmable(self):
        assert "search_tool" in FARMABLE_INCREASERS

    def test_test_pass_is_not_farmable(self):
        # High-value signals should not be farmable
        assert "test_pass" not in FARMABLE_INCREASERS

    def test_build_success_is_not_farmable(self):
        assert "build_success" not in FARMABLE_INCREASERS
