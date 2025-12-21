#!/usr/bin/env python3
"""Integration tests for PAL continuation_id lifecycle (v4.28.1).

Tests the full flow: capture → storage → reuse detection → waste detection → telemetry.
"""

import sys
from pathlib import Path

# Add both lib and hooks to path
sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))
sys.path.insert(0, str(Path(__file__).parent.parent / "hooks"))

import pytest
from unittest.mock import patch


class MockSessionState:
    """Mock session state for testing."""

    def __init__(self):
        self.session_id = "test-session-123"
        self.turn_count = 10
        self.confidence = 80
        self.pal_continuations = {}
        self.pal_continuation_id = ""
        self.last_pal_tool = ""
        self.pal_tracking = {}


class TestPalContinuationCapture:
    """Test continuation_id capture from PAL responses."""

    def test_captures_continuation_from_response(self):
        from hooks._hooks_state_increasers import (
            _capture_pal_continuation_from_response,
        )

        state = MockSessionState()
        data = {
            "tool_response": {
                "continuation_id": "abc123-continuation",
                "result": "some analysis",
            }
        }

        with patch("hooks._hooks_state_increasers.log_pal_continuation_event"):
            _capture_pal_continuation_from_response("mcp__pal__debug", data, state)

        assert state.pal_continuations.get("debug") == "abc123-continuation"
        assert state.pal_continuation_id == "abc123-continuation"

    def test_ignores_non_pal_tools(self):
        from hooks._hooks_state_increasers import (
            _capture_pal_continuation_from_response,
        )

        state = MockSessionState()
        data = {"tool_response": {"continuation_id": "should-not-capture"}}

        _capture_pal_continuation_from_response("Read", data, state)

        assert state.pal_continuations == {}

    def test_handles_nested_content_structure(self):
        from hooks._hooks_state_increasers import (
            _capture_pal_continuation_from_response,
        )

        state = MockSessionState()
        data = {
            "tool_response": {
                "content": [
                    {"type": "text", "text": "analysis"},
                    {"continuation_id": "nested-id-456"},
                ]
            }
        }

        with patch("hooks._hooks_state_increasers.log_pal_continuation_event"):
            _capture_pal_continuation_from_response("mcp__pal__analyze", data, state)

        assert state.pal_continuations.get("analyze") == "nested-id-456"


class TestPalContinuationReuse:
    """Test continuation_id reuse detection."""

    def test_detects_reuse_when_continuation_provided(self):
        from hooks._hooks_state_increasers import _build_pal_signals

        state = MockSessionState()
        state.pal_continuations = {"debug": "existing-id"}
        context = {}

        with patch("hooks._hooks_state_increasers.log_pal_continuation_event"):
            _build_pal_signals(
                "mcp__pal__debug",
                {"prompt": "test", "continuation_id": "existing-id"},
                state,
                context,
            )

        assert context.get("continuation_reuse") is True
        assert context.get("pal_called_without_continuation") is not True

    def test_detects_waste_when_continuation_available_but_not_used(self):
        from hooks._hooks_state_increasers import _build_pal_signals

        state = MockSessionState()
        state.pal_continuations = {"debug": "available-id-xyz"}
        context = {}

        with patch("hooks._hooks_state_increasers.log_pal_continuation_event"):
            _build_pal_signals(
                "mcp__pal__debug",
                {"prompt": "test"},  # No continuation_id!
                state,
                context,
            )

        assert context.get("pal_called_without_continuation") is True
        assert context.get("wasted_continuation_tool") == "debug"
        assert context.get("wasted_continuation_id") == "available-id-xyz"

    def test_no_waste_for_first_call(self):
        from hooks._hooks_state_increasers import _build_pal_signals

        state = MockSessionState()
        state.pal_continuations = {}  # No existing continuations
        context = {}

        with patch("hooks._hooks_state_increasers.log_pal_continuation_event"):
            _build_pal_signals(
                "mcp__pal__debug",
                {"prompt": "first call"},
                state,
                context,
            )

        assert context.get("pal_called_without_continuation") is not True


class TestContinuationIdWasteReducer:
    """Test the reducer integration."""

    def test_reducer_fires_on_waste_context(self):
        from reducers._skills import ContinuationIdWasteReducer

        reducer = ContinuationIdWasteReducer()
        state = MockSessionState()
        context = {"pal_called_without_continuation": True}

        result = reducer.should_trigger(context, state, 0)
        assert result is True

    def test_reducer_respects_cooldown(self):
        from reducers._skills import ContinuationIdWasteReducer

        reducer = ContinuationIdWasteReducer()
        state = MockSessionState()
        state.turn_count = 5
        context = {"pal_called_without_continuation": True}

        # Just triggered 2 turns ago, cooldown is 3
        result = reducer.should_trigger(context, state, 3)
        assert result is False


class TestTelemetryIntegration:
    """Test telemetry logging for continuation events."""

    def test_telemetry_logs_capture_event(self):
        from mastermind.telemetry import log_pal_continuation_event
        import json
        import tempfile
        from unittest.mock import patch

        session_id = "test-telemetry-session"

        # Mock the telemetry path to use temp directory
        with tempfile.TemporaryDirectory() as tmpdir:
            mock_path = Path(tmpdir) / f"{session_id}.jsonl"

            with patch(
                "mastermind.telemetry.get_telemetry_path", return_value=mock_path
            ):
                with patch("mastermind.telemetry.get_config") as mock_config:
                    mock_config.return_value.telemetry.enabled = True

                    log_pal_continuation_event(
                        session_id, 5, "debug", "captured", continuation_id="test-id"
                    )

                    if mock_path.exists():
                        content = mock_path.read_text()
                        event = json.loads(content.strip())
                        assert event["event_type"] == "pal_continuation"
                        assert event["data"]["event"] == "captured"
                        assert event["data"]["tool_type"] == "debug"


class TestFullLifecycle:
    """End-to-end test of the continuation lifecycle."""

    def test_full_capture_and_reuse_cycle(self):
        from hooks._hooks_state_increasers import (
            _build_pal_signals,
            _capture_pal_continuation_from_response,
        )

        state = MockSessionState()

        # Step 1: First PAL call (no continuation yet)
        context1 = {}
        with patch("hooks._hooks_state_increasers.log_pal_continuation_event"):
            _build_pal_signals("mcp__pal__debug", {"prompt": "help"}, state, context1)

        assert context1.get("pal_called_without_continuation") is not True

        # Step 2: PAL response includes continuation_id
        response_data = {"tool_response": {"continuation_id": "new-cont-id"}}
        with patch("hooks._hooks_state_increasers.log_pal_continuation_event"):
            _capture_pal_continuation_from_response(
                "mcp__pal__debug", response_data, state
            )

        assert state.pal_continuations["debug"] == "new-cont-id"

        # Step 3: Next call REUSES continuation_id (good!)
        context2 = {}
        with patch("hooks._hooks_state_increasers.log_pal_continuation_event"):
            _build_pal_signals(
                "mcp__pal__debug",
                {"prompt": "follow up", "continuation_id": "new-cont-id"},
                state,
                context2,
            )

        assert context2.get("continuation_reuse") is True

        # Step 4: Another call WITHOUT continuation_id (waste!)
        state.turn_count = 20
        context3 = {}
        with patch("hooks._hooks_state_increasers.log_pal_continuation_event"):
            _build_pal_signals(
                "mcp__pal__debug",
                {"prompt": "forgot continuation"},  # Missing!
                state,
                context3,
            )

        assert context3.get("pal_called_without_continuation") is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
