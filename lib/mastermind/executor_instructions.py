"""Executor instruction injection for Claude context.

Injects blueprint constraints and escalation triggers into Claude's context.
Gives Claude permission to challenge the blueprint if evidence warrants.
"""

from __future__ import annotations

from .state import Blueprint, MastermindState
from .config import get_config


def generate_executor_instructions(
    blueprint: Blueprint,
    state: MastermindState,
) -> str:
    """Generate executor instructions for Claude's context.

    Includes:
    - Blueprint summary
    - Escalation triggers
    - Permission to challenge
    - Current state summary
    """
    config = get_config()

    lines = [
        "# Mastermind Executor Contract",
        "",
        f"**Epoch:** {state.epoch_id} | **Turn:** {state.turn_count} | **Escalations:** {state.escalation_count}/{config.drift.max_escalations_per_session}",
        "",
        "## Blueprint",
        f"**Goal:** {blueprint.goal}",
        "",
    ]

    if blueprint.invariants:
        lines.append("**Invariants (MUST preserve):**")
        for inv in blueprint.invariants[:5]:
            lines.append(f"- ⚠️ {inv}")
        lines.append("")

    if blueprint.touch_set:
        lines.append("**Expected files:**")
        for f in blueprint.touch_set[:8]:
            lines.append(f"- {f}")
        lines.append("")

    # Escalation triggers
    lines.extend([
        "## Escalation Triggers",
        f"- Modifying >{config.drift.file_count_trigger} files outside touch_set",
        f"- {config.drift.test_failure_trigger}+ test failures",
        "- Fundamental approach change from blueprint",
        "",
        "**On trigger:** Report variance, request delta consult.",
        "",
    ])

    # Permission to challenge
    lines.extend([
        "## Permission to Challenge",
        "You MAY challenge the blueprint if:",
        "- Evidence shows a constraint is wrong",
        "- A better approach becomes clear",
        "- Requirements were misunderstood",
        "",
        "Challenge format: State evidence, propose alternative, request approval.",
        "",
    ])

    # Current state
    if state.files_modified:
        lines.append("## Files Modified This Session")
        for f in state.files_modified[-10:]:
            lines.append(f"- {f}")
        lines.append("")

    return "\n".join(lines)


def generate_escalation_prompt(
    trigger: str,
    evidence: dict,
    state: MastermindState,
) -> str:
    """Generate prompt for escalation to planner.

    Used when drift detection fires.
    """
    lines = [
        "# Escalation Report",
        "",
        f"**Trigger:** {trigger}",
        f"**Epoch:** {state.epoch_id} → {state.epoch_id + 1}",
        f"**Turn:** {state.turn_count}",
        "",
        "## Evidence",
    ]

    if trigger == "file_count":
        lines.append(f"Files modified: {len(state.files_modified)}")
        lines.append("Files outside touch_set:")
        for f in evidence.get("outside_touch_set", [])[:5]:
            lines.append(f"  - {f}")

    elif trigger == "test_failures":
        lines.append(f"Test failures: {state.test_failures}")
        if evidence.get("failing_tests"):
            lines.append("Failing tests:")
            for t in evidence["failing_tests"][:5]:
                lines.append(f"  - {t}")

    elif trigger == "approach_change":
        lines.append("Approach divergence detected:")
        lines.append(f"  Original: {evidence.get('original', 'unknown')}")
        lines.append(f"  Current: {evidence.get('current', 'unknown')}")

    lines.extend([
        "",
        "## Request",
        "Please provide updated blueprint or guidance.",
        "Options:",
        "1. Approve current approach (expand touch_set)",
        "2. Redirect to original approach",
        "3. Provide new strategy",
    ])

    return "\n".join(lines)


def should_inject_instructions(state: MastermindState) -> bool:
    """Check if executor instructions should be injected.

    Instructions are injected when:
    - A blueprint exists
    - Mastermind is enabled
    - We're past turn 0 (after routing)
    """
    config = get_config()

    if not config.planner.enabled:
        return False

    if state.blueprint is None:
        return False

    if state.turn_count < 1:
        return False

    return True
