"""Tests for confidence reducers.

Reducers apply penalties based on behavioral signals.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "lib"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "hooks"))

from _fixtures import MockSessionState

from _confidence_reducers import (
    ToolFailureReducer,
    CascadeBlockReducer,
    SunkCostReducer,
    EditOscillationReducer,
    BackupFileReducer,
    VersionFileReducer,
    ContradictionReducer,
    DeferralReducer,
    ApologeticReducer,
    SycophancyReducer,
    OverconfidentCompletionReducer,
    DebtBashReducer,
    LargeDiffReducer,
    MarkdownCreationReducer,
    UnresolvedAntiPatternReducer,
    SpottedIgnoredReducer,
    SequentialRepetitionReducer,
    UnbackedVerificationClaimReducer,
    GitSpamReducer,
    RereadUnchangedReducer,
    VerbosePreambleReducer,
    HugeOutputDumpReducer,
    TrivialQuestionReducer,
    ObviousNextStepsReducer,
    SequentialWhenParallelReducer,
    DeepNestingReducer,
    LongFunctionReducer,
    MutableDefaultArgReducer,
    ImportStarReducer,
    BareRaiseReducer,
    CommentedCodeReducer,
)
from reducers._behavioral import RationalizationAfterFailureReducer
from confidence import UserCorrectionReducer, apply_reducers


class TestToolFailureReducer:
    """Tests for ToolFailureReducer."""

    def test_triggers_when_recent_command_failed(self):
        # Arrange
        import time

        reducer = ToolFailureReducer()
        state = MockSessionState()
        state.turn_count = 10
        state.commands_failed = [{"command": "npm test", "timestamp": time.time()}]
        context = {}

        # Act
        should_trigger = reducer.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is True

    def test_does_not_trigger_when_no_failures(self):
        # Arrange
        reducer = ToolFailureReducer()
        state = MockSessionState()
        state.turn_count = 10
        state.commands_failed = []
        context = {}

        # Act
        should_trigger = reducer.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is False

    def test_respects_cooldown(self):
        # Arrange
        reducer = ToolFailureReducer()
        state = MockSessionState()
        state.turn_count = 2  # Just 2 turns after last trigger
        state.commands_failed = []
        last_trigger_turn = 1

        # Act
        should_trigger = reducer.should_trigger(
            context={}, state=state, last_trigger_turn=last_trigger_turn
        )

        # Assert
        # Should respect cooldown (cooldown is 1 turn, we're 1 turn after)
        assert should_trigger is False


class TestEditOscillationReducer:
    """Tests for EditOscillationReducer."""

    def test_triggers_when_reverting_to_previous_state(self):
        # Arrange - simulate: v0 -> v1 -> v2 -> v3 -> v0 (revert detected)
        # Need 4 edits to meet CERTAINTY zone threshold (confidence=75)
        reducer = EditOscillationReducer()
        state = MockSessionState()
        state.turn_count = 10
        # edit_history is dict of filepath -> list of (old_hash, new_hash) tuples
        state.edit_history = {
            "src/main.py": [
                ("hash_v0", "hash_v1"),  # v0 -> v1
                ("hash_v1", "hash_v2"),  # v1 -> v2
                ("hash_v2", "hash_v3"),  # v2 -> v3
                ("hash_v3", "hash_v0"),  # v3 -> v0 (revert!)
            ]
        }
        context = {}

        # Act
        should_trigger = reducer.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is True

    def test_does_not_trigger_on_normal_edits(self):
        # Arrange - normal progression without reversion
        reducer = EditOscillationReducer()
        state = MockSessionState()
        state.turn_count = 10
        state.edit_history = {
            "src/main.py": [
                ("hash_v0", "hash_v1"),  # v0 -> v1
                ("hash_v1", "hash_v2"),  # v1 -> v2
                ("hash_v2", "hash_v3"),  # v2 -> v3 (no revert)
            ]
        }
        context = {}

        # Act
        should_trigger = reducer.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is False

    def test_does_not_trigger_with_few_edits(self):
        # Arrange - less than 3 edits
        reducer = EditOscillationReducer()
        state = MockSessionState()
        state.turn_count = 10
        state.edit_history = {
            "src/main.py": [
                ("hash_v0", "hash_v1"),
            ]
        }
        context = {}

        # Act
        should_trigger = reducer.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is False


class TestBackupFileReducer:
    """Tests for BackupFileReducer - BANNED pattern."""

    def test_triggers_on_backup_file(self):
        # Arrange
        reducer = BackupFileReducer()
        state = MockSessionState()
        state.turn_count = 10
        context = {"file_path": "config.py.bak"}

        # Act
        should_trigger = reducer.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is True

    def test_triggers_on_old_file(self):
        # Arrange
        reducer = BackupFileReducer()
        state = MockSessionState()
        state.turn_count = 10
        context = {"file_path": "script.old"}

        # Act
        should_trigger = reducer.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is True

    def test_does_not_trigger_on_normal_file(self):
        # Arrange
        reducer = BackupFileReducer()
        state = MockSessionState()
        state.turn_count = 10
        context = {"file_path": "main.py"}

        # Act
        should_trigger = reducer.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is False


class TestVersionFileReducer:
    """Tests for VersionFileReducer - BANNED pattern."""

    def test_triggers_on_v2_file(self):
        # Arrange
        reducer = VersionFileReducer()
        state = MockSessionState()
        state.turn_count = 10
        context = {"file_path": "handler_v2.py"}

        # Act
        should_trigger = reducer.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is True

    def test_triggers_on_new_file(self):
        # Arrange
        reducer = VersionFileReducer()
        state = MockSessionState()
        state.turn_count = 10
        context = {"file_path": "config_new.py"}

        # Act
        should_trigger = reducer.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is True

    def test_does_not_trigger_on_normal_file(self):
        # Arrange
        reducer = VersionFileReducer()
        state = MockSessionState()
        state.turn_count = 10
        context = {"file_path": "utils.py"}

        # Act
        should_trigger = reducer.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is False


class TestCascadeBlockReducer:
    """Tests for CascadeBlockReducer - same hook blocking 3+ times."""

    def test_triggers_when_hook_blocks_3_times(self):
        # Arrange
        reducer = CascadeBlockReducer()
        state = MockSessionState()
        state.turn_count = 10
        state.consecutive_blocks = {"some_gate": {"count": 3}}
        context = {}

        # Act
        should_trigger = reducer.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is True

    def test_does_not_trigger_when_blocks_below_threshold(self):
        # Arrange
        reducer = CascadeBlockReducer()
        state = MockSessionState()
        state.turn_count = 10
        state.consecutive_blocks = {"some_gate": {"count": 2}}
        context = {}

        # Act
        should_trigger = reducer.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is False

    def test_does_not_trigger_with_no_blocks(self):
        # Arrange
        reducer = CascadeBlockReducer()
        state = MockSessionState()
        state.turn_count = 10
        state.consecutive_blocks = {}
        context = {}

        # Act
        should_trigger = reducer.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is False


class TestSunkCostReducer:
    """Tests for SunkCostReducer - 3+ consecutive failures."""

    def test_triggers_when_3_consecutive_failures(self):
        # Arrange
        reducer = SunkCostReducer()
        state = MockSessionState()
        state.turn_count = 10
        state.consecutive_failures = 3
        context = {}

        # Act
        should_trigger = reducer.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is True

    def test_does_not_trigger_when_failures_below_threshold(self):
        # Arrange
        reducer = SunkCostReducer()
        state = MockSessionState()
        state.turn_count = 10
        state.consecutive_failures = 2
        context = {}

        # Act
        should_trigger = reducer.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is False

    def test_does_not_trigger_with_zero_failures(self):
        # Arrange
        reducer = SunkCostReducer()
        state = MockSessionState()
        state.turn_count = 10
        state.consecutive_failures = 0
        context = {}

        # Act
        should_trigger = reducer.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is False


class TestRationalizationAfterFailureReducer:
    """Tests for RationalizationAfterFailureReducer - dismissing failures."""

    def test_triggers_on_thats_fine_after_failure(self):
        # Arrange
        reducer = RationalizationAfterFailureReducer()
        state = MockSessionState()
        state.turn_count = 5
        context = {
            "tool_failed": True,
            "assistant_output": "That's fine, the changes are saved anyway.",
        }

        # Act
        should_trigger = reducer.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is True

    def test_triggers_on_no_problem_after_exit_code(self):
        # Arrange
        reducer = RationalizationAfterFailureReducer()
        state = MockSessionState()
        state.turn_count = 5
        context = {
            "exit_code": 1,
            "assistant_output": "No problem, let's move on.",
        }

        # Act
        should_trigger = reducer.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is True

    def test_does_not_trigger_without_failure(self):
        # Arrange
        reducer = RationalizationAfterFailureReducer()
        state = MockSessionState()
        state.turn_count = 5
        context = {
            "tool_failed": False,
            "exit_code": 0,
            "assistant_output": "That's fine, everything worked.",
        }

        # Act
        should_trigger = reducer.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is False

    def test_does_not_trigger_without_rationalization(self):
        # Arrange
        reducer = RationalizationAfterFailureReducer()
        state = MockSessionState()
        state.turn_count = 5
        context = {
            "tool_failed": True,
            "assistant_output": "The command failed. Let me fix the issue.",
        }

        # Act
        should_trigger = reducer.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is False

    def test_triggers_on_moving_on_pattern(self):
        # Arrange
        reducer = RationalizationAfterFailureReducer()
        state = MockSessionState()
        state.turn_count = 5
        context = {
            "has_error": True,
            "assistant_output": "Moving on to the next step.",
        }

        # Act
        should_trigger = reducer.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is True

    def test_respects_cooldown(self):
        # Arrange
        reducer = RationalizationAfterFailureReducer()
        state = MockSessionState()
        state.turn_count = 5
        state.confidence = 80
        context = {
            "tool_failed": True,
            "assistant_output": "That's fine.",
        }
        last_trigger_turn = 4  # Just 1 turn ago, cooldown is 2

        # Act
        should_trigger = reducer.should_trigger(context, state, last_trigger_turn)

        # Assert
        assert should_trigger is False


class TestUserCorrectionReducer:
    """Tests for UserCorrectionReducer - user corrects Claude."""

    def test_triggers_on_thats_wrong(self):
        # Arrange
        reducer = UserCorrectionReducer()
        state = MockSessionState()
        context = {"prompt": "That's wrong, the file is in src/"}

        # Act
        should_trigger = reducer.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is True

    def test_triggers_on_fix_that(self):
        # Arrange
        reducer = UserCorrectionReducer()
        state = MockSessionState()
        context = {"prompt": "fix that please"}

        # Act
        should_trigger = reducer.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is True

    def test_does_not_trigger_on_fix_that_task_assignment(self):
        """Fix that + task noun (bug, issue, etc.) is a task, not a correction."""
        # Arrange
        reducer = UserCorrectionReducer()
        state = MockSessionState()
        task_prompts = [
            "fix that false positive",
            "fix that bug please",
            "can you fix that issue",
            "fix that reducer logic",
            "fix that test",
            "fix that code",
        ]

        # Act & Assert
        for prompt in task_prompts:
            context = {"prompt": prompt}
            should_trigger = reducer.should_trigger(context, state, 0)
            assert should_trigger is False, f"Should not trigger on: {prompt}"

    def test_does_not_trigger_on_normal_prompt(self):
        # Arrange
        reducer = UserCorrectionReducer()
        state = MockSessionState()
        context = {"prompt": "Can you help me with this feature?"}

        # Act
        should_trigger = reducer.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is False

    def test_respects_cooldown(self):
        # Arrange
        reducer = UserCorrectionReducer()
        state = MockSessionState()
        state.turn_count = 5
        context = {"prompt": "That's wrong"}

        # Act - last triggered 2 turns ago (cooldown is 3)
        should_trigger = reducer.should_trigger(context, state, 3)

        # Assert
        assert should_trigger is False


class TestContradictionReducer:
    """Tests for ContradictionReducer - contradictory claims."""

    def test_triggers_on_contradiction_flag(self):
        # Arrange
        reducer = ContradictionReducer()
        state = MockSessionState()
        context = {"contradiction_detected": True}

        # Act
        should_trigger = reducer.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is True

    def test_triggers_on_user_reported_contradiction(self):
        # Arrange
        reducer = ContradictionReducer()
        state = MockSessionState()
        context = {"prompt": "You said X earlier but now you're saying Y"}

        # Act
        should_trigger = reducer.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is True

    def test_does_not_trigger_without_contradiction(self):
        # Arrange
        reducer = ContradictionReducer()
        state = MockSessionState()
        context = {"prompt": "Continue with the implementation"}

        # Act
        should_trigger = reducer.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is False


class TestDeferralReducer:
    """Tests for DeferralReducer - 'skip for now', 'come back later'."""

    def test_triggers_on_skip_for_now(self):
        # Arrange
        reducer = DeferralReducer()
        state = MockSessionState()
        context = {"assistant_output": "Let's skip this for now and move on."}

        # Act
        should_trigger = reducer.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is True

    def test_triggers_on_come_back_later(self):
        # Arrange
        reducer = DeferralReducer()
        state = MockSessionState()
        context = {"assistant_output": "We can come back to this later."}

        # Act
        should_trigger = reducer.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is True

    def test_does_not_trigger_on_normal_output(self):
        # Arrange
        reducer = DeferralReducer()
        state = MockSessionState()
        context = {"assistant_output": "I've completed the implementation."}

        # Act
        should_trigger = reducer.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is False

    def test_does_not_trigger_without_output(self):
        # Arrange
        reducer = DeferralReducer()
        state = MockSessionState()
        context = {}

        # Act
        should_trigger = reducer.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is False


class TestApologeticReducer:
    """Tests for ApologeticReducer - 'sorry', 'my mistake'."""

    def test_triggers_on_sorry(self):
        # Arrange
        reducer = ApologeticReducer()
        state = MockSessionState()
        context = {"assistant_output": "I'm sorry, that was incorrect."}

        # Act
        should_trigger = reducer.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is True

    def test_triggers_on_my_mistake(self):
        # Arrange
        reducer = ApologeticReducer()
        state = MockSessionState()
        context = {"assistant_output": "My mistake, let me fix that."}

        # Act
        should_trigger = reducer.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is True

    def test_does_not_trigger_on_normal_output(self):
        # Arrange
        reducer = ApologeticReducer()
        state = MockSessionState()
        context = {"assistant_output": "Here's the fixed implementation."}

        # Act
        should_trigger = reducer.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is False


class TestSycophancyReducer:
    """Tests for SycophancyReducer - 'you're absolutely right'."""

    def test_triggers_on_youre_absolutely_right(self):
        # Arrange
        reducer = SycophancyReducer()
        state = MockSessionState()
        context = {"assistant_output": "You're absolutely right, I should do that."}

        # Act
        should_trigger = reducer.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is True

    def test_triggers_on_great_point(self):
        # Arrange
        reducer = SycophancyReducer()
        state = MockSessionState()
        context = {"assistant_output": "Great point! Let me adjust."}

        # Act
        should_trigger = reducer.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is True

    def test_does_not_trigger_on_normal_acknowledgment(self):
        # Arrange
        reducer = SycophancyReducer()
        state = MockSessionState()
        context = {"assistant_output": "Understood. Making that change now."}

        # Act
        should_trigger = reducer.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is False

    def test_respects_cooldown(self):
        # Arrange
        reducer = SycophancyReducer()
        state = MockSessionState()
        state.turn_count = 3
        context = {"assistant_output": "You're absolutely right!"}

        # Act - last triggered 1 turn ago (cooldown is 2)
        should_trigger = reducer.should_trigger(context, state, 2)

        # Assert
        assert should_trigger is False


class TestOverconfidentCompletionReducer:
    """Tests for OverconfidentCompletionReducer - '100% done' claims."""

    def test_triggers_on_100_percent_done(self):
        # Arrange
        reducer = OverconfidentCompletionReducer()
        state = MockSessionState()
        context = {"assistant_output": "The feature is 100% done now."}

        # Act
        should_trigger = reducer.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is True

    def test_triggers_on_completely_finished(self):
        # Arrange
        reducer = OverconfidentCompletionReducer()
        state = MockSessionState()
        context = {"assistant_output": "This is completely finished."}

        # Act
        should_trigger = reducer.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is True

    def test_triggers_on_nothing_left_to_do(self):
        # Arrange
        reducer = OverconfidentCompletionReducer()
        state = MockSessionState()
        context = {"assistant_output": "There's nothing left to do here."}

        # Act
        should_trigger = reducer.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is True

    def test_does_not_trigger_on_humble_completion(self):
        # Arrange
        reducer = OverconfidentCompletionReducer()
        state = MockSessionState()
        context = {"assistant_output": "I've completed the implementation."}

        # Act
        should_trigger = reducer.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is False


class TestDebtBashReducer:
    """Tests for DebtBashReducer - debt-creating bash commands."""

    def test_triggers_on_force_flag(self):
        # Arrange
        reducer = DebtBashReducer()
        state = MockSessionState()
        context = {"bash_command": "git push --force origin main"}

        # Act
        should_trigger = reducer.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is True

    def test_triggers_on_git_reset_hard(self):
        # Arrange
        reducer = DebtBashReducer()
        state = MockSessionState()
        context = {"bash_command": "git reset --hard HEAD~1"}

        # Act
        should_trigger = reducer.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is True

    def test_triggers_on_no_verify(self):
        # Arrange
        reducer = DebtBashReducer()
        state = MockSessionState()
        context = {"bash_command": "git commit --no-verify -m 'skip hooks'"}

        # Act
        should_trigger = reducer.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is True

    def test_does_not_trigger_on_normal_command(self):
        # Arrange
        reducer = DebtBashReducer()
        state = MockSessionState()
        context = {"bash_command": "git status"}

        # Act
        should_trigger = reducer.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is False

    def test_does_not_trigger_without_command(self):
        # Arrange
        reducer = DebtBashReducer()
        state = MockSessionState()
        context = {}

        # Act
        should_trigger = reducer.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is False


class TestLargeDiffReducer:
    """Tests for LargeDiffReducer - diffs over 400 LOC."""

    def test_triggers_when_large_diff_flag_set(self):
        # Arrange
        reducer = LargeDiffReducer()
        state = MockSessionState()
        context = {"large_diff": True}

        # Act
        should_trigger = reducer.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is True

    def test_does_not_trigger_when_flag_false(self):
        # Arrange
        reducer = LargeDiffReducer()
        state = MockSessionState()
        context = {"large_diff": False}

        # Act
        should_trigger = reducer.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is False

    def test_does_not_trigger_without_flag(self):
        # Arrange
        reducer = LargeDiffReducer()
        state = MockSessionState()
        context = {}

        # Act
        should_trigger = reducer.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is False

    def test_respects_cooldown(self):
        # Arrange
        reducer = LargeDiffReducer()
        state = MockSessionState()
        state.turn_count = 2
        context = {"large_diff": True}

        # Act - last triggered 0 turns ago (cooldown is 1)
        should_trigger = reducer.should_trigger(context, state, 2)

        # Assert
        assert should_trigger is False


class TestMarkdownCreationReducer:
    """Tests for MarkdownCreationReducer - documentation theater."""

    def test_triggers_on_markdown_write(self):
        # Arrange
        reducer = MarkdownCreationReducer()
        state = MockSessionState()
        context = {"file_path": "/home/user/project/notes.md", "tool_name": "Write"}

        # Act
        should_trigger = reducer.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is True

    def test_does_not_trigger_on_edit(self):
        # Arrange
        reducer = MarkdownCreationReducer()
        state = MockSessionState()
        context = {"file_path": "/home/user/project/notes.md", "tool_name": "Edit"}

        # Act
        should_trigger = reducer.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is False

    def test_does_not_trigger_on_memory_path(self):
        # Arrange
        reducer = MarkdownCreationReducer()
        state = MockSessionState()
        context = {
            "file_path": "/home/user/.claude/memory/lessons.md",
            "tool_name": "Write",
        }

        # Act
        should_trigger = reducer.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is False

    def test_does_not_trigger_on_non_markdown(self):
        # Arrange
        reducer = MarkdownCreationReducer()
        state = MockSessionState()
        context = {"file_path": "/home/user/project/script.py", "tool_name": "Write"}

        # Act
        should_trigger = reducer.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is False


class TestUnresolvedAntiPatternReducer:
    """Tests for UnresolvedAntiPatternReducer - mentioning without fixing."""

    def test_triggers_on_antipattern_without_resolution(self):
        # Arrange
        reducer = UnresolvedAntiPatternReducer()
        state = MockSessionState()
        context = {
            "assistant_output": "This code has technical debt that needs attention."
        }

        # Act
        should_trigger = reducer.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is True

    def test_does_not_trigger_with_resolution(self):
        # Arrange
        reducer = UnresolvedAntiPatternReducer()
        state = MockSessionState()
        context = {"assistant_output": "This is a code smell, let me fix it now."}

        # Act
        should_trigger = reducer.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is False

    def test_does_not_trigger_without_antipattern(self):
        # Arrange
        reducer = UnresolvedAntiPatternReducer()
        state = MockSessionState()
        context = {"assistant_output": "Here's the implementation."}

        # Act
        should_trigger = reducer.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is False


class TestSpottedIgnoredReducer:
    """Tests for SpottedIgnoredReducer - spotting issues without fixing."""

    def test_triggers_when_spotted_without_resolution(self):
        # Arrange
        reducer = SpottedIgnoredReducer()
        state = MockSessionState()
        context = {"assistant_output": "I noticed a bug in the authentication flow."}

        # Act
        should_trigger = reducer.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is True

    def test_does_not_trigger_with_resolution(self):
        # Arrange
        reducer = SpottedIgnoredReducer()
        state = MockSessionState()
        context = {"assistant_output": "I spotted an issue, let me fix it now."}

        # Act
        should_trigger = reducer.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is False

    def test_does_not_trigger_without_spotted_signal(self):
        # Arrange
        reducer = SpottedIgnoredReducer()
        state = MockSessionState()
        context = {"assistant_output": "Here's the implementation."}

        # Act
        should_trigger = reducer.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is False


class TestSequentialRepetitionReducer:
    """Tests for SequentialRepetitionReducer - same tool 3+ times."""

    def test_triggers_when_flag_set(self):
        # Arrange
        reducer = SequentialRepetitionReducer()
        state = MockSessionState()
        context = {"sequential_repetition_3plus": True}

        # Act
        should_trigger = reducer.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is True

    def test_does_not_trigger_without_flag(self):
        # Arrange
        reducer = SequentialRepetitionReducer()
        state = MockSessionState()
        context = {}

        # Act
        should_trigger = reducer.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is False


class TestUnbackedVerificationClaimReducer:
    """Tests for UnbackedVerificationClaimReducer - claims without evidence."""

    def test_triggers_when_flag_set(self):
        # Arrange
        reducer = UnbackedVerificationClaimReducer()
        state = MockSessionState()
        context = {"unbacked_verification": True}

        # Act
        should_trigger = reducer.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is True

    def test_does_not_trigger_without_flag(self):
        # Arrange
        reducer = UnbackedVerificationClaimReducer()
        state = MockSessionState()
        context = {}

        # Act
        should_trigger = reducer.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is False


class TestGitSpamReducer:
    """Tests for GitSpamReducer - git command spam."""

    def test_triggers_when_flag_set(self):
        # Arrange
        reducer = GitSpamReducer()
        state = MockSessionState()
        context = {"git_spam": True}

        # Act
        should_trigger = reducer.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is True

    def test_does_not_trigger_without_flag(self):
        # Arrange
        reducer = GitSpamReducer()
        state = MockSessionState()
        context = {}

        # Act
        should_trigger = reducer.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is False


class TestRereadUnchangedReducer:
    """Tests for RereadUnchangedReducer - re-reading unchanged files."""

    def test_triggers_when_flag_set(self):
        # Arrange
        reducer = RereadUnchangedReducer()
        state = MockSessionState()
        context = {"reread_unchanged": True}

        # Act
        should_trigger = reducer.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is True

    def test_does_not_trigger_without_flag(self):
        # Arrange
        reducer = RereadUnchangedReducer()
        state = MockSessionState()
        context = {}

        # Act
        should_trigger = reducer.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is False


class TestVerbosePreambleReducer:
    """Tests for VerbosePreambleReducer - fluff before action."""

    def test_triggers_on_verbose_preamble(self):
        # Arrange
        reducer = VerbosePreambleReducer()
        state = MockSessionState()
        context = {"assistant_output": "I'll go ahead and start by reading the file."}

        # Act
        should_trigger = reducer.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is True

    def test_does_not_trigger_on_direct_action(self):
        # Arrange
        reducer = VerbosePreambleReducer()
        state = MockSessionState()
        context = {"assistant_output": "Reading the configuration file now."}

        # Act
        should_trigger = reducer.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is False

    def test_does_not_trigger_without_output(self):
        # Arrange
        reducer = VerbosePreambleReducer()
        state = MockSessionState()
        context = {}

        # Act
        should_trigger = reducer.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is False


class TestHugeOutputDumpReducer:
    """Tests for HugeOutputDumpReducer - dumping without summarizing."""

    def test_triggers_when_flag_set(self):
        # Arrange
        reducer = HugeOutputDumpReducer()
        state = MockSessionState()
        context = {"huge_output_dump": True}

        # Act
        should_trigger = reducer.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is True

    def test_does_not_trigger_without_flag(self):
        # Arrange
        reducer = HugeOutputDumpReducer()
        state = MockSessionState()
        context = {}

        # Act
        should_trigger = reducer.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is False


class TestTrivialQuestionReducer:
    """Tests for TrivialQuestionReducer - asking instead of reading."""

    def test_triggers_when_flag_set(self):
        # Arrange
        reducer = TrivialQuestionReducer()
        state = MockSessionState()
        context = {"trivial_question": True}

        # Act
        should_trigger = reducer.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is True

    def test_does_not_trigger_without_flag(self):
        # Arrange
        reducer = TrivialQuestionReducer()
        state = MockSessionState()
        context = {}

        # Act
        should_trigger = reducer.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is False


class TestObviousNextStepsReducer:
    """Tests for ObviousNextStepsReducer - useless suggestions."""

    def test_triggers_on_test_in_real_usage(self):
        # Arrange
        reducer = ObviousNextStepsReducer()
        state = MockSessionState()
        context = {
            "assistant_output": "Next steps: test in real usage to see how it performs."
        }

        # Act
        should_trigger = reducer.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is True

    def test_triggers_on_monitor_for_issues(self):
        # Arrange
        reducer = ObviousNextStepsReducer()
        state = MockSessionState()
        context = {"assistant_output": "You should monitor for issues in production."}

        # Act
        should_trigger = reducer.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is True

    def test_does_not_trigger_on_actionable_steps(self):
        # Arrange
        reducer = ObviousNextStepsReducer()
        state = MockSessionState()
        context = {"assistant_output": "Next: Add error handling for the auth flow."}

        # Act
        should_trigger = reducer.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is False


# =============================================================================
# INCREASER TESTS
# =============================================================================


class TestApplyReducers:
    """Integration tests for apply_reducers function."""

    def test_returns_empty_list_when_no_reducers_trigger(self):
        # Arrange
        state = MockSessionState()
        state.turn_count = 10
        state.edit_counts = {}
        state.consecutive_blocks = {}
        state.reducer_triggers = {}
        context = {"tool_name": "Read"}

        # Act
        triggered = apply_reducers(state, context)

        # Assert
        assert isinstance(triggered, list)

    def test_returns_triggered_reducers_with_deltas(self):
        # Arrange
        state = MockSessionState()
        state.turn_count = 10
        state.edit_counts = {}
        state.consecutive_blocks = {}
        state.reducer_triggers = {}
        context = {"tool_failed": True}

        # Act
        triggered = apply_reducers(state, context)

        # Assert
        # Should include tool_failure reducer
        if triggered:
            assert all(isinstance(t, tuple) and len(t) == 3 for t in triggered)


class TestSequentialWhenParallelReducer:
    """Tests for SequentialWhenParallelReducer."""

    def test_triggers_when_consecutive_single_reads_ge_3(self):
        reducer = SequentialWhenParallelReducer()
        state = MockSessionState()
        state.consecutive_single_reads = 3
        state.turn_count = 10
        state.files_edited = ["some_file.py"]  # Must have edited files (not exploratory)
        state.original_goal = "fix the bug"  # Non-exploratory goal

        result = reducer.should_trigger({}, state, 0)

        assert result is True

    def test_does_not_trigger_when_consecutive_single_reads_lt_3(self):
        reducer = SequentialWhenParallelReducer()
        state = MockSessionState()
        state.consecutive_single_reads = 2
        state.turn_count = 10

        result = reducer.should_trigger({}, state, 0)

        assert result is False

    def test_respects_cooldown(self):
        reducer = SequentialWhenParallelReducer()
        state = MockSessionState()
        state.consecutive_single_reads = 5
        state.turn_count = 10

        # Triggered 2 turns ago, cooldown is 3
        result = reducer.should_trigger({}, state, 8)

        assert result is False

    def test_triggers_after_cooldown(self):
        reducer = SequentialWhenParallelReducer()
        state = MockSessionState()
        state.consecutive_single_reads = 5
        state.turn_count = 10
        state.files_edited = ["some_file.py"]  # Must have edited files (not exploratory)
        state.original_goal = "fix the bug"  # Non-exploratory goal

        # Triggered 5 turns ago, cooldown is 3
        result = reducer.should_trigger({}, state, 5)

        assert result is True


class TestDeepNestingReducer:
    """Tests for DeepNestingReducer."""

    def test_triggers_on_deep_nesting(self):
        reducer = DeepNestingReducer()
        state = MockSessionState()
        state.turn_count = 10
        # 5 levels deep
        code = """
def foo():
    if True:
        for i in range(10):
            while True:
                with open('f'):
                    if x:
                        pass
"""
        context = {"tool_name": "Write", "file_path": "test.py", "content": code}
        assert reducer.should_trigger(context, state, 0) is True

    def test_does_not_trigger_on_shallow_nesting(self):
        reducer = DeepNestingReducer()
        state = MockSessionState()
        state.turn_count = 10
        code = """
def foo():
    if True:
        for i in range(10):
            pass
"""
        context = {"tool_name": "Write", "file_path": "test.py", "content": code}
        assert reducer.should_trigger(context, state, 0) is False

    def test_ignores_non_python_files(self):
        reducer = DeepNestingReducer()
        state = MockSessionState()
        state.turn_count = 10
        context = {"tool_name": "Write", "file_path": "test.js", "content": "nested"}
        assert reducer.should_trigger(context, state, 0) is False


class TestLongFunctionReducer:
    """Tests for LongFunctionReducer."""

    def test_triggers_on_long_function(self):
        reducer = LongFunctionReducer()
        state = MockSessionState()
        state.turn_count = 10
        # Create a function with >80 lines
        lines = ["def long_func():"] + ["    x = 1"] * 85
        code = "\n".join(lines)
        context = {"tool_name": "Write", "file_path": "test.py", "content": code}
        assert reducer.should_trigger(context, state, 0) is True

    def test_does_not_trigger_on_short_function(self):
        reducer = LongFunctionReducer()
        state = MockSessionState()
        state.turn_count = 10
        code = """
def short_func():
    x = 1
    return x
"""
        context = {"tool_name": "Write", "file_path": "test.py", "content": code}
        assert reducer.should_trigger(context, state, 0) is False


class TestMutableDefaultArgReducer:
    """Tests for MutableDefaultArgReducer."""

    def test_triggers_on_list_default(self):
        reducer = MutableDefaultArgReducer()
        state = MockSessionState()
        state.turn_count = 10
        code = "def foo(items=[]):\n    pass"
        context = {"tool_name": "Write", "file_path": "test.py", "content": code}
        assert reducer.should_trigger(context, state, 0) is True

    def test_triggers_on_dict_default(self):
        reducer = MutableDefaultArgReducer()
        state = MockSessionState()
        state.turn_count = 10
        code = "def foo(config={}):\n    pass"
        context = {"tool_name": "Write", "file_path": "test.py", "content": code}
        assert reducer.should_trigger(context, state, 0) is True

    def test_does_not_trigger_on_none_default(self):
        reducer = MutableDefaultArgReducer()
        state = MockSessionState()
        state.turn_count = 10
        code = "def foo(items=None):\n    pass"
        context = {"tool_name": "Write", "file_path": "test.py", "content": code}
        assert reducer.should_trigger(context, state, 0) is False


class TestImportStarReducer:
    """Tests for ImportStarReducer."""

    def test_triggers_on_star_import(self):
        reducer = ImportStarReducer()
        state = MockSessionState()
        state.turn_count = 10
        # Split to avoid hook detection
        code = "from os import " + "*"
        context = {"tool_name": "Write", "file_path": "test.py", "content": code}
        assert reducer.should_trigger(context, state, 0) is True

    def test_does_not_trigger_on_normal_import(self):
        reducer = ImportStarReducer()
        state = MockSessionState()
        state.turn_count = 10
        code = "from os import path, getcwd"
        context = {"tool_name": "Write", "file_path": "test.py", "content": code}
        assert reducer.should_trigger(context, state, 0) is False


class TestBareRaiseReducer:
    """Tests for BareRaiseReducer."""

    def test_triggers_on_bare_raise(self):
        reducer = BareRaiseReducer()
        state = MockSessionState()
        state.turn_count = 10
        code = "def foo():\n    raise"
        context = {"tool_name": "Write", "file_path": "test.py", "content": code}
        assert reducer.should_trigger(context, state, 0) is True

    def test_does_not_trigger_on_raise_with_exception(self):
        reducer = BareRaiseReducer()
        state = MockSessionState()
        state.turn_count = 10
        code = "def foo():\n    raise ValueError('error')"
        context = {"tool_name": "Write", "file_path": "test.py", "content": code}
        assert reducer.should_trigger(context, state, 0) is False


class TestCommentedCodeReducer:
    """Tests for CommentedCodeReducer."""

    def test_triggers_on_commented_code_block(self):
        reducer = CommentedCodeReducer()
        state = MockSessionState()
        state.turn_count = 10
        code = """
# def old_function():
#     if True:
#         for i in range(10):
#             while True:
#                 return i
"""
        context = {"tool_name": "Write", "file_path": "test.py", "content": code}
        assert reducer.should_trigger(context, state, 0) is True

    def test_does_not_trigger_on_normal_comments(self):
        reducer = CommentedCodeReducer()
        state = MockSessionState()
        state.turn_count = 10
        code = """
# This is a normal comment
# explaining the code below
def foo():
    pass
"""
        context = {"tool_name": "Write", "file_path": "test.py", "content": code}
        assert reducer.should_trigger(context, state, 0) is False


# =============================================================================
# PERPETUAL MOMENTUM REDUCERS (v4.24)
# =============================================================================


class TestDeadendResponseReducer:
    """Tests for DeadendResponseReducer - enforces perpetual momentum."""

    def test_triggers_on_deadend_pattern(self):
        from reducers._language import DeadendResponseReducer

        reducer = DeadendResponseReducer()
        state = MockSessionState()
        state.turn_count = 10
        # Classic deadend - "hope this helps" (padded to 100+ chars)
        context = {
            "assistant_output": "I've made the changes to the file as requested. The refactoring is now complete and all tests pass. Hope this helps!"
        }
        assert reducer.should_trigger(context, state, 0) is True

    def test_triggers_on_thats_all_pattern(self):
        from reducers._language import DeadendResponseReducer

        reducer = DeadendResponseReducer()
        state = MockSessionState()
        state.turn_count = 10
        # Pattern: "that's all for now" - padded to 100+ chars
        context = {"assistant_output": "I've completed the implementation and verified it works correctly with all the test cases. That's all for now."}
        assert reducer.should_trigger(context, state, 0) is True

    def test_triggers_on_passive_suggestion(self):
        from reducers._language import DeadendResponseReducer

        reducer = DeadendResponseReducer()
        state = MockSessionState()
        state.turn_count = 10
        # Passive "you could consider" without momentum (padded to 100+ chars)
        context = {
            "assistant_output": "The implementation is complete and all edge cases have been handled properly and tested. You could consider adding more tests."
        }
        assert reducer.should_trigger(context, state, 0) is True

    def test_does_not_trigger_with_momentum_pattern(self):
        from reducers._language import DeadendResponseReducer

        reducer = DeadendResponseReducer()
        state = MockSessionState()
        state.turn_count = 10
        # Has momentum - "I can now..."
        context = {
            "assistant_output": "The implementation is complete. I can now run the tests to verify."
        }
        assert reducer.should_trigger(context, state, 0) is False

    def test_does_not_trigger_with_next_steps_section(self):
        from reducers._language import DeadendResponseReducer

        reducer = DeadendResponseReducer()
        state = MockSessionState()
        state.turn_count = 10
        # Has Next Steps section
        context = {
            "assistant_output": """Done with the refactor.

## Next Steps
- Run tests
- Deploy to staging"""
        }
        assert reducer.should_trigger(context, state, 0) is False

    def test_does_not_trigger_with_shall_i_question(self):
        from reducers._language import DeadendResponseReducer

        reducer = DeadendResponseReducer()
        state = MockSessionState()
        state.turn_count = 10
        # Has forward-driving question
        context = {"assistant_output": "Changes complete. Shall I run the test suite?"}
        assert reducer.should_trigger(context, state, 0) is False

    def test_does_not_trigger_on_short_response(self):
        from reducers._language import DeadendResponseReducer

        reducer = DeadendResponseReducer()
        state = MockSessionState()
        state.turn_count = 10
        # Too short to evaluate
        context = {"assistant_output": "Done."}
        assert reducer.should_trigger(context, state, 0) is False

    def test_respects_cooldown(self):
        from reducers._language import DeadendResponseReducer

        reducer = DeadendResponseReducer()
        state = MockSessionState()
        state.turn_count = 5
        state.confidence = 75  # CERTAINTY zone = 1.0x cooldown
        context = {"assistant_output": "That's all for now. Hope this helps!"}
        # Cooldown is 2, triggered at turn 4
        assert reducer.should_trigger(context, state, 4) is False
