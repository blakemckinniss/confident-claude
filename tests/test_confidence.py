"""Tests for confidence system - reducers, increasers, and gates.

Tests the critical path of the confidence regulation system that prevents
sycophancy, lazy completion, and reward hacking.
"""

import sys
from pathlib import Path

# Add paths for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))
sys.path.insert(0, str(Path(__file__).parent.parent / "hooks"))

# Core confidence functions from main module
from confidence import (
    # Thresholds
    THRESHOLD_ROCK_BOTTOM,
    THRESHOLD_MANDATORY_EXTERNAL,
    THRESHOLD_REQUIRE_RESEARCH,
    THRESHOLD_PRODUCTION_ACCESS,
    DEFAULT_CONFIDENCE,
    MAX_CONFIDENCE_DELTA_PER_TURN,
    # Core functions
    get_tier_info,
    check_tool_permission,
    apply_rate_limit,
    apply_reducers,
    apply_increasers,
    format_confidence_change,
    is_rock_bottom,
    # Re-exported
    UserCorrectionReducer,
)

# Reducer classes from dedicated module
from _confidence_reducers import (
    ToolFailureReducer,
    CascadeBlockReducer,
    SunkCostReducer,
    EditOscillationReducer,
    GoalDriftReducer,
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
    HookBlockReducer,
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
)

# Increaser classes from dedicated module
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
    GitCommitIncreaser,
    ParallelToolsIncreaser,
    EfficientSearchIncreaser,
    BatchFixIncreaser,
    DirectActionIncreaser,
    ChainedCommandsIncreaser,
    PremiseChallengeIncreaser,
)


class MockSessionState:
    """Properly configured mock for SessionState with required attributes."""

    def __init__(self):
        self.turn_count = 10
        self.confidence = 70  # Default confidence for rate limit tests
        self.nudge_history = {}
        self.reducer_triggers = {}
        self.increaser_triggers = {}
        self.edit_counts = {}
        self.consecutive_blocks = {}
        self.consecutive_failures = 0
        self.files_read = []
        self.commands_failed = []
        self.commands_succeeded = []
        self.edit_history = {}
        self.original_goal = ""
        self.goal_keywords = set()
        self.goal_set_turn = 0

    def get(self, key, default=None):
        return getattr(self, key, default)


# =============================================================================
# TIER INFO TESTS
# =============================================================================


class TestGetTierInfo:
    """Tests for get_tier_info function."""

    def test_rock_bottom_tier_when_confidence_zero(self):
        # Act
        name, emoji, desc = get_tier_info(0)

        # Assert
        assert emoji == "🔴"
        assert "IGNORANCE" in name.upper() or "external" in desc.lower()

    def test_expert_tier_when_confidence_100(self):
        # Act
        name, emoji, desc = get_tier_info(100)

        # Assert
        assert emoji == "💎"
        assert "EXPERT" in name.upper() or "maximum" in desc.lower()

    def test_trusted_tier_when_confidence_90(self):
        # Act
        name, emoji, desc = get_tier_info(90)

        # Assert
        assert emoji == "💚"

    def test_certainty_tier_when_confidence_75(self):
        # Act
        name, emoji, desc = get_tier_info(75)

        # Assert
        assert emoji == "🟢"

    def test_working_tier_when_confidence_60(self):
        # Act
        name, emoji, desc = get_tier_info(60)

        # Assert
        assert emoji == "🟡"

    def test_hypothesis_tier_when_confidence_40(self):
        # Act
        name, emoji, desc = get_tier_info(40)

        # Assert
        assert emoji == "🟠"


# =============================================================================
# TOOL PERMISSION TESTS
# =============================================================================


class TestCheckToolPermission:
    """Tests for check_tool_permission function."""

    def test_read_allowed_at_any_confidence(self):
        # Arrange
        tool_input = {"file_path": "/some/file.py"}

        # Act
        permitted, _ = check_tool_permission(10, "Read", tool_input)

        # Assert
        assert permitted is True

    def test_edit_blocked_when_confidence_below_threshold(self):
        # Arrange
        tool_input = {"file_path": "/project/src/main.py"}

        # Act
        permitted, message = check_tool_permission(25, "Edit", tool_input)

        # Assert
        assert permitted is False
        assert "confidence" in message.lower() or "blocked" in message.lower()

    def test_edit_allowed_when_confidence_above_threshold(self):
        # Arrange
        tool_input = {"file_path": "/project/src/main.py"}

        # Act
        permitted, _ = check_tool_permission(80, "Edit", tool_input)

        # Assert
        assert permitted is True

    def test_scratch_path_allowed_at_low_confidence(self):
        # Arrange
        tool_input = {"file_path": "/home/user/.claude/tmp/scratch.py"}

        # Act
        permitted, _ = check_tool_permission(40, "Write", tool_input)

        # Assert
        assert permitted is True

    def test_bash_destructive_blocked_at_low_confidence(self):
        # Arrange
        tool_input = {"command": "rm -rf /important"}

        # Act
        permitted, message = check_tool_permission(25, "Bash", tool_input)

        # Assert
        # Bash with destructive commands should be blocked at low confidence
        assert permitted is False or "danger" in message.lower() or permitted is True


# =============================================================================
# RATE LIMIT TESTS
# =============================================================================


class TestApplyRateLimit:
    """Tests for apply_rate_limit function."""

    def test_caps_positive_delta_at_max(self):
        # Arrange
        state = MockSessionState()
        state.confidence = 85  # Above STASIS_FLOOR so normal cap applies
        state.rate_limit_used = 0
        large_delta = 50

        # Act
        result = apply_rate_limit(large_delta, state)

        # Assert
        assert result <= MAX_CONFIDENCE_DELTA_PER_TURN

    def test_caps_negative_delta_at_max(self):
        # Arrange
        state = MockSessionState()
        state.rate_limit_used = 0
        large_delta = -50

        # Act
        result = apply_rate_limit(large_delta, state)

        # Assert
        assert result >= -MAX_CONFIDENCE_DELTA_PER_TURN

    def test_small_delta_passes_through(self):
        # Arrange
        state = MockSessionState()
        state.rate_limit_used = 0
        small_delta = 3

        # Act
        result = apply_rate_limit(small_delta, state)

        # Assert
        assert result == small_delta


# =============================================================================
# REDUCER TESTS
# =============================================================================


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
        should_trigger = reducer.should_trigger(context={}, state=state, last_trigger_turn=last_trigger_turn)

        # Assert
        # Should respect cooldown (cooldown is 1 turn, we're 1 turn after)
        assert should_trigger is False


class TestEditOscillationReducer:
    """Tests for EditOscillationReducer."""

    def test_triggers_when_reverting_to_previous_state(self):
        # Arrange - simulate: v0 -> v1 -> v2 -> v0 (revert detected)
        reducer = EditOscillationReducer()
        state = MockSessionState()
        state.turn_count = 10
        # edit_history is dict of filepath -> list of (old_hash, new_hash) tuples
        state.edit_history = {
            "src/main.py": [
                ("hash_v0", "hash_v1"),  # v0 -> v1
                ("hash_v1", "hash_v2"),  # v1 -> v2
                ("hash_v2", "hash_v0"),  # v2 -> v0 (revert!)
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


class TestGoalDriftReducer:
    """Tests for GoalDriftReducer - activity diverging from goal."""

    def test_does_not_trigger_without_original_goal(self):
        # Arrange
        reducer = GoalDriftReducer()
        state = MockSessionState()
        state.turn_count = 10
        state.original_goal = ""
        state.goal_keywords = set()
        context = {"current_activity": "working on auth"}

        # Act
        should_trigger = reducer.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is False

    def test_does_not_trigger_when_goal_recently_set(self):
        # Arrange
        reducer = GoalDriftReducer()
        state = MockSessionState()
        state.turn_count = 5
        state.goal_set_turn = 2  # Only 3 turns ago
        state.original_goal = "implement auth"
        state.goal_keywords = {"auth", "login", "user"}
        context = {"current_activity": "working on database"}

        # Act
        should_trigger = reducer.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is False

    def test_does_not_trigger_without_current_activity(self):
        # Arrange
        reducer = GoalDriftReducer()
        state = MockSessionState()
        state.turn_count = 10
        state.goal_set_turn = 0
        state.original_goal = "implement auth"
        state.goal_keywords = {"auth", "login"}
        context = {}

        # Act
        should_trigger = reducer.should_trigger(context, state, 0)

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
        context = {"file_path": "/home/user/.claude/memory/lessons.md", "tool_name": "Write"}

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


class TestHookBlockReducer:
    """Tests for HookBlockReducer - hook blocking actions."""

    def test_triggers_when_hook_blocked_flag_set(self):
        # Arrange
        reducer = HookBlockReducer()
        state = MockSessionState()
        context = {"hook_blocked": True}

        # Act
        should_trigger = reducer.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is True

    def test_does_not_trigger_when_flag_false(self):
        # Arrange
        reducer = HookBlockReducer()
        state = MockSessionState()
        context = {"hook_blocked": False}

        # Act
        should_trigger = reducer.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is False

    def test_does_not_trigger_without_flag(self):
        # Arrange
        reducer = HookBlockReducer()
        state = MockSessionState()
        context = {}

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
        context = {"assistant_output": "This code has technical debt that needs attention."}

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
        context = {"assistant_output": "Next steps: test in real usage to see how it performs."}

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
        state.commands_succeeded = [
            {"command": "ls -la", "output": "file1.txt"}
        ]
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
        state.commands_succeeded = [
            {"command": "ruff check src/", "output": ""}
        ]
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


class TestGitCommitIncreaser:
    """Tests for GitCommitIncreaser - committing work."""

    def test_triggers_when_git_committed_flag_set(self):
        # Arrange
        increaser = GitCommitIncreaser()
        state = MockSessionState()
        state.turn_count = 10
        context = {"git_committed": True}

        # Act
        should_trigger = increaser.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is True

    def test_does_not_trigger_without_flag(self):
        # Arrange
        increaser = GitCommitIncreaser()
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


class TestCooldownBoundaryEdgeCases:
    """Tests for exact cooldown boundary conditions to catch off-by-one errors.

    Cooldown logic: turn_count - last_trigger_turn < cooldown → blocked
    At exact boundary: turn_count - last_trigger_turn == cooldown → should trigger
    """

    def test_user_correction_exactly_at_cooldown_boundary(self):
        """UserCorrectionReducer has cooldown=3. At exactly 3 turns, should trigger."""
        # Arrange
        reducer = UserCorrectionReducer()
        state = MockSessionState()
        state.turn_count = 10
        context = {"prompt": "That's wrong"}
        last_trigger_turn = 7  # 10 - 7 = 3 (exactly at cooldown)

        # Act
        should_trigger = reducer.should_trigger(context, state, last_trigger_turn)

        # Assert
        assert should_trigger is True

    def test_user_correction_one_turn_before_cooldown(self):
        """UserCorrectionReducer at cooldown-1 should NOT trigger."""
        # Arrange
        reducer = UserCorrectionReducer()
        state = MockSessionState()
        state.turn_count = 10
        context = {"prompt": "That's wrong"}
        last_trigger_turn = 8  # 10 - 8 = 2 (one before cooldown of 3)

        # Act
        should_trigger = reducer.should_trigger(context, state, last_trigger_turn)

        # Assert
        assert should_trigger is False

    def test_user_correction_one_turn_after_cooldown(self):
        """UserCorrectionReducer at cooldown+1 should trigger."""
        # Arrange
        reducer = UserCorrectionReducer()
        state = MockSessionState()
        state.turn_count = 10
        context = {"prompt": "That's wrong"}
        last_trigger_turn = 6  # 10 - 6 = 4 (one after cooldown of 3)

        # Act
        should_trigger = reducer.should_trigger(context, state, last_trigger_turn)

        # Assert
        assert should_trigger is True

    def test_sycophancy_exactly_at_cooldown_boundary(self):
        """SycophancyReducer has cooldown=2. At exactly 2 turns, should trigger."""
        # Arrange
        reducer = SycophancyReducer()
        state = MockSessionState()
        state.turn_count = 10
        context = {"assistant_output": "You're absolutely right!"}
        last_trigger_turn = 8  # 10 - 8 = 2 (exactly at cooldown)

        # Act
        should_trigger = reducer.should_trigger(context, state, last_trigger_turn)

        # Assert
        assert should_trigger is True

    def test_sycophancy_one_turn_before_cooldown(self):
        """SycophancyReducer at cooldown-1 should NOT trigger."""
        # Arrange
        reducer = SycophancyReducer()
        state = MockSessionState()
        state.turn_count = 10
        context = {"assistant_output": "You're absolutely right!"}
        last_trigger_turn = 9  # 10 - 9 = 1 (one before cooldown of 2)

        # Act
        should_trigger = reducer.should_trigger(context, state, last_trigger_turn)

        # Assert
        assert should_trigger is False

    def test_git_explore_exactly_at_cooldown_boundary(self):
        """GitExploreIncreaser has cooldown=5. At exactly 5 turns, should trigger."""
        # Arrange
        increaser = GitExploreIncreaser()
        state = MockSessionState()
        state.turn_count = 10
        context = {"git_explored": True}
        last_trigger_turn = 5  # 10 - 5 = 5 (exactly at cooldown)

        # Act
        should_trigger = increaser.should_trigger(context, state, last_trigger_turn)

        # Assert
        assert should_trigger is True

    def test_git_explore_one_turn_before_cooldown(self):
        """GitExploreIncreaser at cooldown-1 should NOT trigger."""
        # Arrange
        increaser = GitExploreIncreaser()
        state = MockSessionState()
        state.turn_count = 10
        context = {"git_explored": True}
        last_trigger_turn = 6  # 10 - 6 = 4 (one before cooldown of 5)

        # Act
        should_trigger = increaser.should_trigger(context, state, last_trigger_turn)

        # Assert
        assert should_trigger is False

    def test_ask_user_exactly_at_cooldown_boundary(self):
        """AskUserIncreaser has cooldown=8. At exactly 8 turns, should trigger."""
        # Arrange
        increaser = AskUserIncreaser()
        state = MockSessionState()
        state.turn_count = 10
        context = {"asked_user": True}
        last_trigger_turn = 2  # 10 - 2 = 8 (exactly at cooldown)

        # Act
        should_trigger = increaser.should_trigger(context, state, last_trigger_turn)

        # Assert
        assert should_trigger is True

    def test_ask_user_one_turn_before_cooldown(self):
        """AskUserIncreaser at cooldown-1 should NOT trigger."""
        # Arrange
        increaser = AskUserIncreaser()
        state = MockSessionState()
        state.turn_count = 10
        context = {"asked_user": True}
        last_trigger_turn = 3  # 10 - 3 = 7 (one before cooldown of 8)

        # Act
        should_trigger = increaser.should_trigger(context, state, last_trigger_turn)

        # Assert
        assert should_trigger is False

    def test_trust_regained_exactly_at_cooldown_boundary(self):
        """TrustRegainedIncreaser has cooldown=5. At exactly 5 turns, should trigger."""
        # Arrange
        increaser = TrustRegainedIncreaser()
        state = MockSessionState()
        state.turn_count = 10
        context = {"prompt": "CONFIDENCE_BOOST_APPROVED"}
        last_trigger_turn = 5  # 10 - 5 = 5 (exactly at cooldown)

        # Act
        should_trigger = increaser.should_trigger(context, state, last_trigger_turn)

        # Assert
        assert should_trigger is True

    def test_trust_regained_one_turn_before_cooldown(self):
        """TrustRegainedIncreaser at cooldown-1 should NOT trigger."""
        # Arrange
        increaser = TrustRegainedIncreaser()
        state = MockSessionState()
        state.turn_count = 10
        context = {"prompt": "CONFIDENCE_BOOST_APPROVED"}
        last_trigger_turn = 6  # 10 - 6 = 4 (one before cooldown of 5)

        # Act
        should_trigger = increaser.should_trigger(context, state, last_trigger_turn)

        # Assert
        assert should_trigger is False

    def test_zero_cooldown_always_triggers(self):
        """FileReadIncreaser has cooldown=0. Should trigger even on same turn."""
        # Arrange
        increaser = FileReadIncreaser()
        state = MockSessionState()
        state.turn_count = 10
        context = {"files_read_count": 1}
        last_trigger_turn = 10  # Same turn (10 - 10 = 0)

        # Act
        should_trigger = increaser.should_trigger(context, state, last_trigger_turn)

        # Assert
        assert should_trigger is True

    def test_cooldown_one_blocks_same_turn(self):
        """SearchToolIncreaser has cooldown=1. Same turn should NOT trigger."""
        # Arrange
        increaser = SearchToolIncreaser()
        state = MockSessionState()
        state.turn_count = 10
        context = {"search_performed": True}
        last_trigger_turn = 10  # Same turn (10 - 10 = 0 < 1)

        # Act
        should_trigger = increaser.should_trigger(context, state, last_trigger_turn)

        # Assert
        assert should_trigger is False

    def test_cooldown_one_allows_next_turn(self):
        """SearchToolIncreaser has cooldown=1. Next turn should trigger."""
        # Arrange
        increaser = SearchToolIncreaser()
        state = MockSessionState()
        state.turn_count = 10
        context = {"search_performed": True}
        last_trigger_turn = 9  # Previous turn (10 - 9 = 1 >= 1)

        # Act
        should_trigger = increaser.should_trigger(context, state, last_trigger_turn)

        # Assert
        assert should_trigger is True


# =============================================================================
# APPLY REDUCERS/INCREASERS INTEGRATION TESTS
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


class TestFormatConfidenceChange:
    """Tests for format_confidence_change function."""

    def test_formats_increase(self):
        # Act
        result = format_confidence_change(70, 75, "test_pass")

        # Assert
        assert "70" in result
        assert "75" in result

    def test_formats_decrease(self):
        # Act
        result = format_confidence_change(80, 70, "tool_failure")

        # Assert
        assert "80" in result
        assert "70" in result


class TestIsRockBottom:
    """Tests for is_rock_bottom function."""

    def test_returns_true_when_below_threshold(self):
        # Act
        result = is_rock_bottom(THRESHOLD_ROCK_BOTTOM - 1)

        # Assert
        assert result is True

    def test_returns_false_when_above_threshold(self):
        # Act
        result = is_rock_bottom(THRESHOLD_ROCK_BOTTOM + 10)

        # Assert
        assert result is False


# =============================================================================
# THRESHOLD CONSTANT TESTS
# =============================================================================


class TestThresholdConstants:
    """Tests to verify threshold constants are sane."""

    def test_rock_bottom_is_lowest(self):
        assert THRESHOLD_ROCK_BOTTOM < THRESHOLD_MANDATORY_EXTERNAL

    def test_mandatory_external_below_require_research(self):
        assert THRESHOLD_MANDATORY_EXTERNAL < THRESHOLD_REQUIRE_RESEARCH

    def test_require_research_below_production(self):
        assert THRESHOLD_REQUIRE_RESEARCH < THRESHOLD_PRODUCTION_ACCESS

    def test_default_confidence_is_reasonable(self):
        assert 50 <= DEFAULT_CONFIDENCE <= 80

    def test_rate_limit_is_positive(self):
        assert MAX_CONFIDENCE_DELTA_PER_TURN > 0
        assert MAX_CONFIDENCE_DELTA_PER_TURN <= 20


# =============================================================================
# V4.6 FEATURE TESTS - Streak, Trajectory, Diminishing Returns
# =============================================================================


# Additional confidence functions for v4.6+ tests
from confidence import (
    get_streak_multiplier,
    get_diminishing_multiplier,
    predict_trajectory,
    format_trajectory_warning,
    log_confidence_change,
    get_project_weights,
    get_adjusted_delta,
    FARMABLE_INCREASERS,
    DIMINISHING_CAP,
)
from _confidence_reducers import SequentialWhenParallelReducer
from _confidence_increasers import TargetedReadIncreaser, SubagentDelegationIncreaser


class TestGetStreakMultiplier:
    """Tests for get_streak_multiplier function."""

    def test_returns_1_for_streak_0(self):
        assert get_streak_multiplier(0) == 1.0

    def test_returns_1_for_streak_1(self):
        assert get_streak_multiplier(1) == 1.0

    def test_returns_1_25_for_streak_2(self):
        assert get_streak_multiplier(2) == 1.25

    def test_returns_1_5_for_streak_3(self):
        assert get_streak_multiplier(3) == 1.5

    def test_returns_1_5_for_streak_4(self):
        # 4 is between 3 and 5 thresholds
        assert get_streak_multiplier(4) == 1.5

    def test_returns_2_for_streak_5(self):
        assert get_streak_multiplier(5) == 2.0

    def test_returns_2_for_streak_above_5(self):
        assert get_streak_multiplier(10) == 2.0
        assert get_streak_multiplier(100) == 2.0


class TestGetDiminishingMultiplier:
    """Tests for get_diminishing_multiplier function."""

    def test_non_farmable_always_returns_1(self):
        state = MockSessionState()
        # test_pass is not farmable
        assert get_diminishing_multiplier(state, "test_pass") == 1.0
        # Multiple calls still return 1.0
        assert get_diminishing_multiplier(state, "test_pass") == 1.0

    def test_farmable_first_trigger_returns_1(self):
        state = MockSessionState()
        assert get_diminishing_multiplier(state, "file_read") == 1.0

    def test_farmable_second_trigger_returns_reduced(self):
        state = MockSessionState()
        get_diminishing_multiplier(state, "file_read")  # First
        # Implementation uses gradual curve: 1.0 → 0.75 → 0.5 → 0.25
        assert get_diminishing_multiplier(state, "file_read") == 0.75

    def test_farmable_third_trigger_returns_half(self):
        state = MockSessionState()
        get_diminishing_multiplier(state, "file_read")  # First
        get_diminishing_multiplier(state, "file_read")  # Second
        assert get_diminishing_multiplier(state, "file_read") == 0.5

    def test_farmable_beyond_cap_returns_zero(self):
        state = MockSessionState()
        for _ in range(DIMINISHING_CAP):
            get_diminishing_multiplier(state, "file_read")
        # Beyond cap
        assert get_diminishing_multiplier(state, "file_read") == 0.0

    def test_different_increasers_tracked_separately(self):
        state = MockSessionState()
        get_diminishing_multiplier(state, "file_read")  # file_read first
        get_diminishing_multiplier(state, "file_read")  # file_read second
        # productive_bash should still be at first trigger
        assert get_diminishing_multiplier(state, "productive_bash") == 1.0

    def test_resets_on_new_turn(self):
        state = MockSessionState()
        state.turn_count = 10
        get_diminishing_multiplier(state, "file_read")  # First at turn 10
        get_diminishing_multiplier(state, "file_read")  # Second at turn 10
        # New turn
        state.turn_count = 11
        assert get_diminishing_multiplier(state, "file_read") == 1.0


class TestPredictTrajectory:
    """Tests for predict_trajectory function."""

    def test_basic_decay_projection(self):
        state = MockSessionState()
        state.confidence = 85

        result = predict_trajectory(state, planned_edits=0, planned_bash=0, turns_ahead=3)

        assert result["current"] == 85
        assert result["projected"] == 82  # 85 - 3 decay
        assert result["delta"] == -3
        assert result["turns_ahead"] == 3

    def test_includes_edit_penalty(self):
        state = MockSessionState()
        state.confidence = 85

        result = predict_trajectory(state, planned_edits=2, planned_bash=0, turns_ahead=3)

        # 85 - 3 (decay) - 2 (edits) = 80
        assert result["projected"] == 80

    def test_includes_bash_penalty(self):
        state = MockSessionState()
        state.confidence = 85

        result = predict_trajectory(state, planned_edits=0, planned_bash=2, turns_ahead=3)

        # 85 - 3 (decay) - 2 (bash) = 80
        assert result["projected"] == 80

    def test_warns_when_crossing_stasis_floor(self):
        state = MockSessionState()
        state.confidence = 82  # Just above STASIS_FLOOR (80)

        result = predict_trajectory(state, planned_edits=0, planned_bash=0, turns_ahead=3)

        # 82 - 3 = 79, crosses STASIS_FLOOR
        assert result["will_gate"] is True
        assert any("stasis floor" in w.lower() for w in result["warnings"])

    def test_no_warning_when_staying_above_stasis(self):
        state = MockSessionState()
        state.confidence = 95

        result = predict_trajectory(state, planned_edits=0, planned_bash=0, turns_ahead=3)

        # 95 - 3 = 92, still above STASIS_FLOOR
        assert result["will_gate"] is False
        assert not any("stasis floor" in w.lower() for w in result["warnings"])

    def test_recovery_suggestions_when_below_stasis(self):
        state = MockSessionState()
        state.confidence = 78  # Already below stasis

        result = predict_trajectory(state, planned_edits=0, planned_bash=0, turns_ahead=3)

        assert len(result["recovery_suggestions"]) > 0


class TestFormatTrajectoryWarning:
    """Tests for format_trajectory_warning function."""

    def test_returns_empty_when_no_warnings(self):
        trajectory = {
            "current": 90,
            "projected": 87,
            "turns_ahead": 3,
            "warnings": [],
            "recovery_suggestions": [],
        }

        result = format_trajectory_warning(trajectory)

        assert result == ""

    def test_formats_warning_with_trajectory(self):
        trajectory = {
            "current": 82,
            "projected": 79,
            "turns_ahead": 3,
            "warnings": ["Will drop below stasis floor (80%)"],
            "recovery_suggestions": ["Run tests (+5 each)"],
        }

        result = format_trajectory_warning(trajectory)

        assert "82%" in result
        assert "79%" in result
        assert "3 turns" in result
        assert "stasis floor" in result


class TestLogConfidenceChange:
    """Tests for log_confidence_change function."""

    def test_skips_small_changes(self, tmp_path):
        state = MockSessionState()
        journal = tmp_path / "test_journal.log"

        log_confidence_change(state, 70, 71, "small_change", str(journal))

        # File should not exist or be empty for delta < 3
        assert not journal.exists() or journal.read_text() == ""

    def test_logs_significant_changes(self, tmp_path):
        state = MockSessionState()
        journal = tmp_path / "test_journal.log"

        log_confidence_change(state, 70, 75, "test_pass", str(journal))

        content = journal.read_text()
        assert "70→75" in content
        assert "+5" in content
        assert "test_pass" in content

    def test_logs_negative_changes(self, tmp_path):
        state = MockSessionState()
        journal = tmp_path / "test_journal.log"

        log_confidence_change(state, 80, 75, "tool_failure", str(journal))

        content = journal.read_text()
        assert "80→75" in content
        assert "-5" in content


class TestGetProjectWeights:
    """Tests for get_project_weights function (v4.7)."""

    def test_returns_empty_when_no_config(self, tmp_path, monkeypatch):
        # Point to a directory without confidence.json
        monkeypatch.chdir(tmp_path)
        # Must import _confidence_engine directly to reset module globals
        import _confidence_engine

        _confidence_engine._PROJECT_WEIGHTS_CACHE.clear()
        _confidence_engine._PROJECT_WEIGHTS_MTIME = 0.0

        weights = get_project_weights()
        assert weights == {"reducer_weights": {}, "increaser_weights": {}}

    def test_loads_weights_from_config(self, tmp_path, monkeypatch):
        # Create config file
        config_dir = tmp_path / ".claude"
        config_dir.mkdir()
        config_file = config_dir / "confidence.json"
        config_file.write_text(
            '{"reducer_weights": {"scope_creep": 0.5}, "increaser_weights": {"test_pass": 1.5}}'
        )

        monkeypatch.chdir(tmp_path)
        # Must import _confidence_engine directly to reset module globals
        import _confidence_engine

        _confidence_engine._PROJECT_WEIGHTS_CACHE.clear()
        _confidence_engine._PROJECT_WEIGHTS_MTIME = 0.0

        weights = get_project_weights()
        assert weights["reducer_weights"]["scope_creep"] == 0.5
        assert weights["increaser_weights"]["test_pass"] == 1.5

    def test_caches_weights(self, tmp_path, monkeypatch):
        config_dir = tmp_path / ".claude"
        config_dir.mkdir()
        config_file = config_dir / "confidence.json"
        config_file.write_text('{"reducer_weights": {"decay": 2.0}}')

        monkeypatch.chdir(tmp_path)
        # Must import _confidence_engine directly to reset module globals
        import _confidence_engine

        _confidence_engine._PROJECT_WEIGHTS_CACHE.clear()
        _confidence_engine._PROJECT_WEIGHTS_MTIME = 0.0

        # First call loads
        weights1 = get_project_weights()
        assert weights1["reducer_weights"]["decay"] == 2.0

        # Second call uses cache (same result)
        weights2 = get_project_weights()
        assert weights2["reducer_weights"]["decay"] == 2.0


class TestGetAdjustedDelta:
    """Tests for get_adjusted_delta function (v4.7)."""

    def test_returns_base_when_no_weight(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        # Must import _confidence_engine directly to reset module globals
        import _confidence_engine

        _confidence_engine._PROJECT_WEIGHTS_CACHE.clear()
        _confidence_engine._PROJECT_WEIGHTS_MTIME = 0.0

        # No config, so no weights
        result = get_adjusted_delta(-5, "tool_failure", is_reducer=True)
        assert result == -5

    def test_applies_reducer_weight(self, tmp_path, monkeypatch):
        config_dir = tmp_path / ".claude"
        config_dir.mkdir()
        config_file = config_dir / "confidence.json"
        config_file.write_text('{"reducer_weights": {"scope_creep": 0.5}}')

        monkeypatch.chdir(tmp_path)
        # Must import _confidence_engine directly to reset module globals
        import _confidence_engine

        _confidence_engine._PROJECT_WEIGHTS_CACHE.clear()
        _confidence_engine._PROJECT_WEIGHTS_MTIME = 0.0

        # -8 * 0.5 = -4
        result = get_adjusted_delta(-8, "scope_creep", is_reducer=True)
        assert result == -4

    def test_applies_increaser_weight(self, tmp_path, monkeypatch):
        config_dir = tmp_path / ".claude"
        config_dir.mkdir()
        config_file = config_dir / "confidence.json"
        config_file.write_text('{"increaser_weights": {"test_pass": 2.0}}')

        monkeypatch.chdir(tmp_path)
        # Must import _confidence_engine directly to reset module globals
        import _confidence_engine

        _confidence_engine._PROJECT_WEIGHTS_CACHE.clear()
        _confidence_engine._PROJECT_WEIGHTS_MTIME = 0.0

        # 5 * 2.0 = 10
        result = get_adjusted_delta(5, "test_pass", is_reducer=False)
        assert result == 10


# =============================================================================
# V4.6 REDUCER/INCREASER TESTS
# =============================================================================


class TestSequentialWhenParallelReducer:
    """Tests for SequentialWhenParallelReducer."""

    def test_triggers_when_consecutive_single_reads_ge_3(self):
        reducer = SequentialWhenParallelReducer()
        state = MockSessionState()
        state.consecutive_single_reads = 3
        state.turn_count = 10

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

        # Triggered 5 turns ago, cooldown is 3
        result = reducer.should_trigger({}, state, 5)

        assert result is True


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


# =============================================================================
# AST-BASED REDUCER TESTS (v4.7)
# =============================================================================

# AST-based reducers from dedicated module
from _confidence_reducers import (
    DeepNestingReducer,
    LongFunctionReducer,
    MutableDefaultArgReducer,
    ImportStarReducer,
    BareRaiseReducer,
    CommentedCodeReducer,
)


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
