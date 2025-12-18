"""
Mastermind-related PostToolUse hooks.

Handles PAL MCP integration, continuation tracking, and routing state.
Priority range: 86-89
"""

import _lib_path  # noqa: F401
import sys
from pathlib import Path

from _hook_registry import register_hook
from _hook_result import HookResult
from session_state import SessionState

# Mastermind state management
try:
    sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))
    from mastermind.state import (
        load_state as load_mastermind_state,
        save_state as save_mastermind_state,
    )

    MASTERMIND_AVAILABLE = True
except ImportError:
    MASTERMIND_AVAILABLE = False
    load_mastermind_state = None
    save_mastermind_state = None


# =============================================================================
# PAL CONTINUATION CAPTURE (priority 86)
# =============================================================================

PAL_TOOL_PREFIX = "mcp__pal__"
PAL_TOOL_TYPES = [
    "debug",
    "planner",
    "codereview",
    "consensus",
    "precommit",
    "chat",
    "thinkdeep",
    "challenge",
    "apilookup",
]


def _extract_continuation_id(tool_result: dict | str | None) -> str | None:
    """Extract continuation_id from PAL tool response.

    PAL responses have structure:
    {
        "continuation_offer": {
            "continuation_id": "abc123",
            "remaining_turns": 39
        }
    }
    """
    if not isinstance(tool_result, dict):
        return None

    # Check direct continuation_offer
    offer = tool_result.get("continuation_offer", {})
    if isinstance(offer, dict):
        cont_id = offer.get("continuation_id")
        if cont_id:
            return cont_id

    # Check nested in content (some PAL tools wrap response)
    content = tool_result.get("content")
    if isinstance(content, dict):
        offer = content.get("continuation_offer", {})
        if isinstance(offer, dict):
            cont_id = offer.get("continuation_id")
            if cont_id:
                return cont_id

    return None


@register_hook("pal_continuation_capture", PAL_TOOL_PREFIX, priority=86)
def capture_pal_continuation(
    data: dict, state: SessionState, runner_state: dict
) -> HookResult:
    """Capture continuation_id from PAL MCP tool responses.

    Stores per-tool continuation_ids in mastermind state for reuse
    in subsequent PAL calls to the same tool type.
    """
    if not MASTERMIND_AVAILABLE:
        return HookResult.none()

    tool_name = data.get("tool_name", "")
    if not tool_name.startswith(PAL_TOOL_PREFIX):
        return HookResult.none()

    # Extract tool type from name (e.g., "mcp__pal__debug" -> "debug")
    tool_type = tool_name.replace(PAL_TOOL_PREFIX, "")
    if tool_type not in PAL_TOOL_TYPES:
        return HookResult.none()

    # Get tool result
    tool_result = data.get("tool_result")
    continuation_id = _extract_continuation_id(tool_result)

    if not continuation_id:
        return HookResult.none()

    # Load mastermind state and capture continuation
    try:
        session_id = state.session_id or "default"
        mm_state = load_mastermind_state(session_id)

        # Check if this is a new continuation (worth noting)
        old_cont = mm_state.get_pal_continuation(tool_type)
        is_new = old_cont != continuation_id

        mm_state.capture_pal_continuation(tool_type, continuation_id)
        save_mastermind_state(mm_state)

        if is_new:
            # Provide context about captured continuation
            return HookResult.with_context(
                f"📎 PAL {tool_type} continuation captured: {continuation_id[:12]}..."
            )
    except Exception as e:
        print(f"[mastermind-hook] Continuation capture error: {e}", file=sys.stderr)

    return HookResult.none()
