#!/usr/bin/env python3
"""
Code-Mode Handoff Hook (UserPromptSubmit, priority 8)

Checks for pending tool calls from the code-mode handoff queue and injects
context instructing Claude to execute them before processing the user's request.

This bridges Python-generated execution plans with Claude's native tool-calling.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Add lib to path
SCRIPT_DIR = Path(__file__).parent
LIB_DIR = SCRIPT_DIR.parent / "lib"
if str(LIB_DIR) not in sys.path:
    sys.path.insert(0, str(LIB_DIR))

from _prompt_registry import register_hook  # noqa: E402
from _hook_result import HookResult  # noqa: E402
from _session_state_class import SessionState  # noqa: E402

# Try to import handoff functions
try:
    from _codemode_executor import get_pending_calls, ToolCallRequest

    CODEMODE_AVAILABLE = True
except ImportError:
    CODEMODE_AVAILABLE = False
    ToolCallRequest = None


def format_tool_call(call: ToolCallRequest) -> str:
    """Format a tool call for display."""
    args_preview = ", ".join(
        f"{k}={repr(v)[:30]}" for k, v in list(call.args.items())[:3]
    )
    if len(call.args) > 3:
        args_preview += ", ..."
    return f"  - `{call.tool}({args_preview})` [id: {call.id}]"


def format_execution_instructions(calls: list[ToolCallRequest]) -> str:
    """Format pending calls as execution instructions for Claude."""
    if not calls:
        return ""

    # Sort by priority (lower = higher priority)
    sorted_calls = sorted(calls, key=lambda c: c.priority)

    lines = [
        "# 🔧 Code-Mode: Pending Tool Executions",
        "",
        f"**{len(calls)} tool call(s) queued for execution.**",
        "",
        "Execute these MCP tool calls in order before responding to the user:",
        "",
    ]

    for call in sorted_calls:
        lines.append(format_tool_call(call))

    lines.extend(
        [
            "",
            "After executing each call, record the result with:",
            "```python",
            "from lib._codemode_executor import record_tool_result",
            'record_tool_result(call_id="...", success=True/False, result=..., error=...)',
            "```",
            "",
            "Then proceed with the user's request below.",
            "",
        ]
    )

    return "\n".join(lines)


@register_hook("codemode_handoff", priority=8)
def check_codemode_handoff(data: dict, state: SessionState) -> HookResult:
    """
    Inject pending code-mode tool calls into context.

    Priority 8 ensures this runs early, before other context injectors.
    """
    if not CODEMODE_AVAILABLE:
        return HookResult.allow()

    try:
        pending = get_pending_calls()
    except Exception:
        # Silently skip if handoff state is corrupted
        return HookResult.allow()

    if not pending:
        return HookResult.allow()

    # Track in state for downstream hooks
    if not hasattr(state, "_codemode_pending"):
        state._codemode_pending = []
    state._codemode_pending = pending

    # Generate instructions
    instructions = format_execution_instructions(pending)

    return HookResult.allow(instructions)


# For direct testing
if __name__ == "__main__":
    from _codemode_executor import (
        ToolCallRequest,
        submit_tool_call,
        clear_handoff_state,
    )

    # Clean start
    clear_handoff_state()

    # Submit test calls
    submit_tool_call(
        ToolCallRequest(
            id="test1",
            tool="mcp__serena__find_symbol",
            args={"name_path_pattern": "MyClass", "include_body": True},
            priority=0,
        )
    )
    submit_tool_call(
        ToolCallRequest(
            id="test2",
            tool="mcp__pal__chat",
            args={"prompt": "Analyze this code", "model": "kimi-k2"},
            priority=1,
        )
    )

    # Test the hook
    class MockState:
        pass

    result = check_codemode_handoff({"prompt": "Hello"}, MockState())
    print("Hook result:")
    print(result.context if result.context else "(no context)")

    # Cleanup
    clear_handoff_state()
