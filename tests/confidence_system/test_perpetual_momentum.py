"""Tests for perpetual momentum enforcement (v4.24).

Tests for DeadendResponseReducer and MomentumForwardIncreaser.
"""

import sys
from pathlib import Path

# Add paths for imports
_lib = str(Path(__file__).parent.parent.parent / "lib")
_hooks = str(Path(__file__).parent.parent.parent / "hooks")
if _lib not in sys.path:
    sys.path.insert(0, _lib)
if _hooks not in sys.path:
    sys.path.insert(0, _hooks)

from _fixtures import MockSessionState
from reducers._language import DeadendResponseReducer
from _confidence_increasers import MomentumForwardIncreaser


# =============================================================================
# DEADEND RESPONSE REDUCER TESTS
# Note: Reducer has 100 char minimum to avoid false positives on short responses
# =============================================================================


class TestDeadendResponseReducer:
    """Tests for DeadendResponseReducer - enforces perpetual momentum."""

    def test_triggers_on_deadend_pattern(self):
        reducer = DeadendResponseReducer()
        state = MockSessionState()
        state.turn_count = 10
        # Classic deadend - "hope this helps" (>100 chars)
        context = {
            "assistant_output": (
                "I've made the changes to the authentication module and updated "
                "the login flow to handle edge cases better. Hope this helps!"
            )
        }
        assert reducer.should_trigger(context, state, 0) is True

    def test_triggers_on_thats_all_pattern(self):
        reducer = DeadendResponseReducer()
        state = MockSessionState()
        state.turn_count = 10
        # Note: "Let me know" matches momentum pattern, so use different deadend
        context = {
            "assistant_output": (
                "I've reviewed the codebase and made the necessary updates to the "
                "database queries. That's all I have for now. Feel free to reach out!"
            )
        }
        assert reducer.should_trigger(context, state, 0) is True

    def test_triggers_on_passive_suggestion(self):
        reducer = DeadendResponseReducer()
        state = MockSessionState()
        state.turn_count = 10
        # Passive "you could consider" without momentum (>100 chars)
        # Pattern: \byou\s+(?:could|might|may)\s+(?:want\s+to|consider|try)\b
        context = {
            "assistant_output": (
                "The implementation is complete and working correctly now with all features. "
                "You could consider adding more comprehensive test coverage for the new code paths."
            )
        }
        assert reducer.should_trigger(context, state, 0) is True

    def test_does_not_trigger_with_momentum_pattern(self):
        reducer = DeadendResponseReducer()
        state = MockSessionState()
        state.turn_count = 10
        # Has momentum - "I can now..."
        context = {
            "assistant_output": (
                "The implementation is complete and the feature is working. "
                "I can now run the full test suite to verify everything passes correctly."
            )
        }
        assert reducer.should_trigger(context, state, 0) is False

    def test_does_not_trigger_with_next_steps_section(self):
        reducer = DeadendResponseReducer()
        state = MockSessionState()
        state.turn_count = 10
        # Has Next Steps section (>100 chars)
        context = {
            "assistant_output": """Done with the refactor of the authentication system.

## Next Steps
- Run the full test suite to verify changes
- Deploy to staging environment for QA"""
        }
        assert reducer.should_trigger(context, state, 0) is False

    def test_does_not_trigger_with_shall_i_question(self):
        reducer = DeadendResponseReducer()
        state = MockSessionState()
        state.turn_count = 10
        # Has forward-driving question (>100 chars)
        context = {
            "assistant_output": (
                "Changes to the API endpoint have been applied successfully. "
                "The authentication flow should now work correctly. Shall I run the test suite?"
            )
        }
        assert reducer.should_trigger(context, state, 0) is False

    def test_does_not_trigger_on_short_response(self):
        reducer = DeadendResponseReducer()
        state = MockSessionState()
        state.turn_count = 10
        # Too short to evaluate (<100 chars)
        context = {"assistant_output": "Done. Hope this helps!"}
        assert reducer.should_trigger(context, state, 0) is False

    def test_respects_cooldown(self):
        reducer = DeadendResponseReducer()
        state = MockSessionState()
        state.turn_count = 5
        state.confidence = 75  # CERTAINTY zone = 1.0x cooldown
        context = {
            "assistant_output": (
                "I've finished implementing the feature and everything looks good. "
                "That's all for now. Hope this helps with your project!"
            )
        }
        # Cooldown is 2, triggered at turn 4
        assert reducer.should_trigger(context, state, 4) is False

    def test_does_not_trigger_with_let_me_pattern(self):
        reducer = DeadendResponseReducer()
        state = MockSessionState()
        state.turn_count = 10
        context = {
            "assistant_output": (
                "The database migration has been applied successfully to all tables. "
                "Let me also check the build to make sure everything compiles correctly."
            )
        }
        assert reducer.should_trigger(context, state, 0) is False

    def test_does_not_trigger_with_want_me_to(self):
        reducer = DeadendResponseReducer()
        state = MockSessionState()
        state.turn_count = 10
        context = {
            "assistant_output": (
                "Changes to the configuration have been applied and saved correctly. "
                "Want me to run the validation tests to confirm everything works?"
            )
        }
        assert reducer.should_trigger(context, state, 0) is False


# =============================================================================
# MOMENTUM FORWARD INCREASER TESTS
# Note: Increaser has 50 char minimum to avoid noise on short responses
# =============================================================================


class TestMomentumForwardIncreaser:
    """Tests for MomentumForwardIncreaser - rewards forward motion."""

    def test_triggers_on_i_can_pattern(self):
        increaser = MomentumForwardIncreaser()
        state = MockSessionState()
        state.turn_count = 10
        # >50 chars with "I can now" pattern
        context = {
            "assistant_output": "The changes are complete. I can now run the tests to verify."
        }
        assert increaser.should_trigger(context, state, 0) is True

    def test_triggers_on_let_me_pattern(self):
        increaser = MomentumForwardIncreaser()
        state = MockSessionState()
        state.turn_count = 10
        # >50 chars with "Let me" pattern
        context = {
            "assistant_output": "The file has been updated successfully. Let me verify it compiles."
        }
        assert increaser.should_trigger(context, state, 0) is True

    def test_triggers_on_next_steps_section(self):
        increaser = MomentumForwardIncreaser()
        state = MockSessionState()
        state.turn_count = 10
        context = {
            "assistant_output": """Implementation complete and working now.

## Next Steps
- Run tests
- Deploy to staging"""
        }
        assert increaser.should_trigger(context, state, 0) is True

    def test_triggers_on_shall_i_question(self):
        increaser = MomentumForwardIncreaser()
        state = MockSessionState()
        state.turn_count = 10
        # >50 chars with "Shall I" pattern
        context = {
            "assistant_output": "All changes have been applied correctly. Shall I run the linter now?"
        }
        assert increaser.should_trigger(context, state, 0) is True

    def test_does_not_trigger_without_momentum(self):
        increaser = MomentumForwardIncreaser()
        state = MockSessionState()
        state.turn_count = 10
        # >50 chars but no momentum patterns
        context = {
            "assistant_output": "The implementation is done and working correctly. Hope this helps!"
        }
        assert increaser.should_trigger(context, state, 0) is False

    def test_does_not_trigger_on_passive_suggestion(self):
        increaser = MomentumForwardIncreaser()
        state = MockSessionState()
        state.turn_count = 10
        # Passive "you could" is NOT momentum
        context = {
            "assistant_output": "The feature is finished now. You could also add more tests for coverage."
        }
        assert increaser.should_trigger(context, state, 0) is False

    def test_respects_cooldown(self):
        increaser = MomentumForwardIncreaser()
        state = MockSessionState()
        state.turn_count = 5
        context = {
            "assistant_output": "Changes are done and ready. I can now test this functionality."
        }
        # Cooldown is 1, so turn_count - last_trigger must be < 1 to block
        # 5 - 5 = 0 < 1, so same turn should block
        assert increaser.should_trigger(context, state, 5) is False

    def test_triggers_on_i_will_pattern(self):
        increaser = MomentumForwardIncreaser()
        state = MockSessionState()
        state.turn_count = 10
        # >50 chars with "I will" pattern
        context = {
            "assistant_output": "The bug has been fixed successfully. I will run the tests next."
        }
        assert increaser.should_trigger(context, state, 0) is True

    def test_triggers_on_next_ill_pattern(self):
        increaser = MomentumForwardIncreaser()
        state = MockSessionState()
        state.turn_count = 10
        # >50 chars with "Next I'll" pattern
        context = {
            "assistant_output": "All the changes have been applied. Next I'll check the linting results."
        }
        assert increaser.should_trigger(context, state, 0) is True

    def test_does_not_trigger_on_short_response(self):
        increaser = MomentumForwardIncreaser()
        state = MockSessionState()
        state.turn_count = 10
        # <50 chars - should not trigger even with pattern
        context = {"assistant_output": "Done. I can now test."}
        assert increaser.should_trigger(context, state, 0) is False
