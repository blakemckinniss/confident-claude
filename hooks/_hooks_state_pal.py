"""
PAL Mandate PostToolUse hook.

Captures blueprints from mcp__pal__planner for mastermind drift detection.
Priority 5 - runs early to capture planning context.
"""

import _lib_path  # noqa: F401
import json
import re
from pathlib import Path

from _hook_registry import register_hook
from _hook_result import HookResult
from session_state import SessionState

# Lock path defined in mastermind/config.py (single source of truth)
try:
    from mastermind.config import PAL_MANDATE_LOCK_PATH
except ImportError:
    PAL_MANDATE_LOCK_PATH = Path.home() / ".claude" / "tmp" / "pal_mandate.lock"


@register_hook("pal_mandate_clear", "mcp__pal__planner", priority=5)
def clear_pal_mandate_on_success(
    data: dict, state: SessionState, runner_state: dict
) -> HookResult:
    """Capture blueprint when mcp__pal__planner succeeds.

    NOTE: Lock clearing is now handled by pre_tool_use_runner.py (priority 0)
    when ANY PAL tool is called. This hook focuses on blueprint capture only.
    """
    tool_input = data.get("tool_input", {})
    tool_result = data.get("tool_result", {})

    context_parts = []

    # Capture blueprint from planner result for mastermind state
    try:
        from mastermind.state import load_state, save_state
        from mastermind.hook_integration import get_session_id

        # Extract result content
        result_str = ""
        if isinstance(tool_result, dict):
            result_str = (
                tool_result.get("content", "")
                or tool_result.get("output", "")
                or str(tool_result)
            )
        elif isinstance(tool_result, str):
            result_str = tool_result
        else:
            result_str = str(tool_result) if tool_result else ""

        # Parse blueprint from planner output
        blueprint = _parse_blueprint_from_planner(result_str, tool_input)

        if blueprint:
            # Load current session state and save blueprint
            session_id = get_session_id()
            mm_state = load_state(session_id)
            mm_state.blueprint = blueprint
            mm_state.routing_decision = None  # Clear old routing decision
            save_state(mm_state)

            context_parts.append(
                f"📋 **Blueprint Captured** - Goal: {blueprint.goal[:100]}..."
                if len(blueprint.goal) > 100
                else f"📋 **Blueprint Captured** - Goal: {blueprint.goal}"
            )

            # Add invariants preview
            if blueprint.invariants:
                inv_preview = ", ".join(blueprint.invariants[:3])
                if len(blueprint.invariants) > 3:
                    inv_preview += f" (+{len(blueprint.invariants) - 3} more)"
                context_parts.append(f"   ⚠️ Invariants: {inv_preview}")

            # Add touch set preview
            if blueprint.touch_set:
                touch_preview = ", ".join(blueprint.touch_set[:5])
                if len(blueprint.touch_set) > 5:
                    touch_preview += f" (+{len(blueprint.touch_set) - 5} more)"
                context_parts.append(f"   📁 Touch set: {touch_preview}")

    except ImportError:
        # Mastermind not available, skip blueprint capture
        pass
    except Exception as e:
        import sys

        print(f"[pal_mandate_clear] Blueprint capture failed: {e}", file=sys.stderr)

    if context_parts:
        return HookResult.approve("\n".join(context_parts))
    return HookResult.approve()


def _parse_blueprint_from_planner(result_str: str, tool_input: dict):
    """Parse blueprint from PAL planner output.

    Extracts structured planning information from the planner response.
    Falls back to extracting from step content if JSON not found.
    """
    try:
        from mastermind.state import Blueprint
    except ImportError:
        return None

    # Try to find JSON blueprint in result
    json_match = re.search(r'\{[^{}]*"goal"[^{}]*\}', result_str, re.DOTALL)
    if json_match:
        try:
            data = json.loads(json_match.group())
            return Blueprint(
                goal=data.get("goal", ""),
                invariants=data.get("invariants", []),
                touch_set=data.get("touch_set", data.get("files", [])),
                budget=data.get("budget", {}),
                decision_points=data.get("decision_points", []),
                acceptance_criteria=data.get("acceptance_criteria", []),
            )
        except json.JSONDecodeError:
            pass

    # Extract from structured sections in result
    goal = ""
    invariants = []
    touch_set = []
    acceptance_criteria = []

    # Look for goal/objective
    goal_patterns = [
        r"(?:Goal|Objective|Purpose)[:\s]+([^\n]+)",
        r"(?:We need to|Task is to|Will)[:\s]*([^\n]+)",
    ]
    for pattern in goal_patterns:
        match = re.search(pattern, result_str, re.IGNORECASE)
        if match:
            goal = match.group(1).strip()
            break

    # If no goal found, use step content from input
    if not goal:
        goal = tool_input.get("step", "")[:200]

    # Look for invariants/constraints
    inv_section = re.search(
        r"(?:Invariants?|Constraints?|Must not)[:\s]*\n((?:[-*]\s*[^\n]+\n?)+)",
        result_str,
        re.IGNORECASE,
    )
    if inv_section:
        invariants = [
            line.strip().lstrip("-* ")
            for line in inv_section.group(1).split("\n")
            if line.strip()
        ]

    # Look for files/touch set
    files_section = re.search(
        r"(?:Files?|Touch set|Will modify)[:\s]*\n((?:[-*]\s*[^\n]+\n?)+)",
        result_str,
        re.IGNORECASE,
    )
    if files_section:
        touch_set = [
            line.strip().lstrip("-* ")
            for line in files_section.group(1).split("\n")
            if line.strip()
        ]

    # Look for acceptance criteria
    accept_section = re.search(
        r"(?:Acceptance|Done when|Success criteria)[:\s]*\n((?:[-*]\s*[^\n]+\n?)+)",
        result_str,
        re.IGNORECASE,
    )
    if accept_section:
        acceptance_criteria = [
            line.strip().lstrip("-* ")
            for line in accept_section.group(1).split("\n")
            if line.strip()
        ]

    if goal:
        return Blueprint(
            goal=goal,
            invariants=invariants[:10],
            touch_set=touch_set[:20],
            budget={},
            decision_points=[],
            acceptance_criteria=acceptance_criteria[:10],
        )

    return None
