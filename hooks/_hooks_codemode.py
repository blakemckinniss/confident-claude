#!/usr/bin/env python3
"""
Code-Mode PostToolUse Hooks

Auto-records tool results for pending handoff calls, completing the
Python→Claude→Python execution bridge.

HOOKS INDEX (by priority):
  88 codemode_result_recorder - Auto-record results for pending handoff calls
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

# Add lib to path
SCRIPT_DIR = Path(__file__).parent
LIB_DIR = SCRIPT_DIR.parent / "lib"
if str(LIB_DIR) not in sys.path:
    sys.path.insert(0, str(LIB_DIR))

from _hook_registry import register_hook  # noqa: E402
from _hook_result import HookResult  # noqa: E402
from _session_state_class import SessionState  # noqa: E402

# Try to import handoff functions
try:
    from _codemode_executor import (
        get_pending_calls,
        record_tool_result,
        ToolCallRequest,
    )

    CODEMODE_AVAILABLE = True
except ImportError:
    CODEMODE_AVAILABLE = False
    ToolCallRequest = None


def _find_matching_pending_call(
    tool_name: str, pending_calls: list[ToolCallRequest]
) -> ToolCallRequest | None:
    """Find a pending call that matches the executed tool.

    Matching strategy:
    1. Exact tool name match (most common case)
    2. First match wins (calls are priority-sorted)
    """
    for call in pending_calls:
        if call.tool == tool_name:
            return call
    return None


def _extract_result(data: dict) -> tuple[bool, Any, str | None]:
    """Extract success status and result from tool output.

    Returns:
        (success, result, error)
    """
    tool_output = data.get("tool_output", "")
    tool_error = data.get("tool_error", "")

    # Check for explicit error
    if tool_error:
        return (False, None, tool_error)

    # Check for error patterns in output
    if isinstance(tool_output, str):
        error_indicators = ["Error:", "error:", "Exception:", "Traceback", "failed"]
        for indicator in error_indicators:
            if indicator in tool_output:
                return (False, tool_output, f"Output contains '{indicator}'")

    return (True, tool_output, None)


@register_hook("codemode_result_recorder", "mcp__.*", priority=88)
def record_codemode_result(
    data: dict, state: SessionState, runner_state: dict
) -> HookResult:
    """Auto-record tool results for pending code-mode handoff calls.

    Priority 88 runs after most quality/tracking hooks but before smart-commit.
    Only fires for MCP tools (mcp__*) since those are what code-mode orchestrates.
    """
    if not CODEMODE_AVAILABLE:
        return HookResult.none()

    tool_name = data.get("tool_name", "")

    # Get pending calls
    try:
        pending = get_pending_calls()
    except Exception:
        return HookResult.none()

    if not pending:
        return HookResult.none()

    # Find matching pending call
    matching_call = _find_matching_pending_call(tool_name, pending)
    if not matching_call:
        return HookResult.none()

    # Extract result
    success, result, error = _extract_result(data)

    # Record the result
    try:
        record_tool_result(
            call_id=matching_call.id,
            success=success,
            result=result,
            error=error,
        )
    except Exception as e:
        print(f"[codemode] Failed to record result: {e}", file=sys.stderr)
        return HookResult.none()

    # Provide feedback
    status = "completed" if success else "failed"
    context = f"Code-mode: `{matching_call.id}` {status}"

    # Track in session state for downstream hooks
    if not hasattr(state, "_codemode_completed"):
        state._codemode_completed = []
    state._codemode_completed.append(matching_call.id)

    return HookResult.approve(context)


# For direct testing
if __name__ == "__main__":
    from _codemode_executor import (
        ToolCallRequest,
        submit_tool_call,
        clear_handoff_state,
        get_completed_result,
    )

    # Clean start
    clear_handoff_state()

    # Submit a test call
    submit_tool_call(
        ToolCallRequest(
            id="test-auto-record",
            tool="mcp__serena__find_symbol",
            args={"name_path_pattern": "TestClass"},
            priority=0,
        )
    )

    # Simulate tool completion
    class MockState:
        pass

    mock_data = {
        "tool_name": "mcp__serena__find_symbol",
        "tool_output": '{"symbols": [{"name": "TestClass", "type": "class"}]}',
        "tool_error": "",
    }

    result = record_codemode_result(mock_data, MockState(), {})
    print(f"Hook result: {result}")

    # Check if it was recorded
    completed = get_completed_result("test-auto-record")
    if completed:
        print(f"Recorded: success={completed.success}, result={completed.result}")
    else:
        print("ERROR: Result was not recorded")

    # Cleanup
    clear_handoff_state()
