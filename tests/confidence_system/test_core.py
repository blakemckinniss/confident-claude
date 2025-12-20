"""Tests for core confidence functions.

Tests tier info, permissions, rate limiting, and core apply functions.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "lib"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "hooks"))

from _fixtures import MockSessionState

from confidence import (
    THRESHOLD_ROCK_BOTTOM,
    THRESHOLD_MANDATORY_EXTERNAL,
    THRESHOLD_REQUIRE_RESEARCH,
    THRESHOLD_PRODUCTION_ACCESS,
    DEFAULT_CONFIDENCE,
    MAX_CONFIDENCE_DELTA_PER_TURN,
    DIMINISHING_CAP,
    get_tier_info,
    check_tool_permission,
    apply_rate_limit,
    format_confidence_change,
    is_rock_bottom,
    get_streak_multiplier,
    get_diminishing_multiplier,
    predict_trajectory,
    format_trajectory_warning,
    log_confidence_change,
    get_project_weights,
    get_adjusted_delta,
    UserCorrectionReducer,
)
from _confidence_reducers import SycophancyReducer
from _confidence_increasers import (
    GitExploreIncreaser,
    AskUserIncreaser,
    TrustRegainedIncreaser,
    FileReadIncreaser,
    SearchToolIncreaser,
)


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

        result = predict_trajectory(
            state, planned_edits=0, planned_bash=0, turns_ahead=3
        )

        assert result["current"] == 85
        assert result["projected"] == 82  # 85 - 3 decay
        assert result["delta"] == -3
        assert result["turns_ahead"] == 3

    def test_includes_edit_penalty(self):
        state = MockSessionState()
        state.confidence = 85

        result = predict_trajectory(
            state, planned_edits=2, planned_bash=0, turns_ahead=3
        )

        # 85 - 3 (decay) - 2 (edits) = 80
        assert result["projected"] == 80

    def test_includes_bash_penalty(self):
        state = MockSessionState()
        state.confidence = 85

        result = predict_trajectory(
            state, planned_edits=0, planned_bash=2, turns_ahead=3
        )

        # 85 - 3 (decay) - 2 (bash) = 80
        assert result["projected"] == 80

    def test_warns_when_crossing_stasis_floor(self):
        state = MockSessionState()
        state.confidence = 82  # Just above STASIS_FLOOR (80)

        result = predict_trajectory(
            state, planned_edits=0, planned_bash=0, turns_ahead=3
        )

        # 82 - 3 = 79, crosses STASIS_FLOOR
        assert result["will_gate"] is True
        assert any("stasis floor" in w.lower() for w in result["warnings"])

    def test_no_warning_when_staying_above_stasis(self):
        state = MockSessionState()
        state.confidence = 95

        result = predict_trajectory(
            state, planned_edits=0, planned_bash=0, turns_ahead=3
        )

        # 95 - 3 = 92, still above STASIS_FLOOR
        assert result["will_gate"] is False
        assert not any("stasis floor" in w.lower() for w in result["warnings"])

    def test_recovery_suggestions_when_below_stasis(self):
        state = MockSessionState()
        state.confidence = 78  # Already below stasis

        result = predict_trajectory(
            state, planned_edits=0, planned_bash=0, turns_ahead=3
        )

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
