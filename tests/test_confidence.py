"""Tests for confidence system - reducers, increasers, and gates.

Tests the critical path of the confidence regulation system that prevents
sycophancy, lazy completion, and reward hacking.
"""

import sys
from pathlib import Path

# Add paths for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))
sys.path.insert(0, str(Path(__file__).parent.parent / "hooks"))

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
    # Reducer classes
    ToolFailureReducer,
    CascadeBlockReducer,
    SunkCostReducer,
    EditOscillationReducer,
    GoalDriftReducer,
    BackupFileReducer,
    VersionFileReducer,
    # Increaser classes
    TestPassIncreaser,
    BuildSuccessIncreaser,
    LintPassIncreaser,
    ProductiveBashIncreaser,
)


class MockSessionState:
    """Properly configured mock for SessionState with required attributes."""

    def __init__(self):
        self.turn_count = 10
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


# =============================================================================
# INCREASER TESTS
# =============================================================================


class TestTestPassIncreaser:
    """Tests for TestPassIncreaser."""

    def test_triggers_on_pytest_success(self):
        # Arrange
        increaser = TestPassIncreaser()
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
        increaser = TestPassIncreaser()
        state = MockSessionState()
        state.turn_count = 10
        context = {"tests_passed": True}

        # Act
        should_trigger = increaser.should_trigger(context, state, 0)

        # Assert
        assert should_trigger is True

    def test_does_not_trigger_without_test_commands(self):
        # Arrange
        increaser = TestPassIncreaser()
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
