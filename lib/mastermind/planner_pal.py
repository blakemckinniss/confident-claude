"""Planner via PAL MCP for blueprint generation.

Model selection: PAL auto-selects by default, can specify model for complex tasks.

Generates execution blueprints with:
- Goal statement
- Invariants (must-not-violate constraints)
- Touch set (files expected to change)
- Budget (token/time estimates)
- Decision points (where Claude can choose)
- Acceptance criteria
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .state import Blueprint


PLANNER_SYSTEM_PROMPT = """You are a strategic planner for an AI coding assistant (Claude).

Generate a blueprint for the given task. The blueprint will guide Claude's execution.

Output JSON with this schema:
{
  "goal": "One-sentence goal statement",
  "invariants": ["Constraint 1", "Constraint 2"],
  "touch_set": ["file1.py", "file2.ts"],
  "budget": {
    "estimated_files": 3,
    "estimated_complexity": "medium",
    "max_turns": 10
  },
  "decision_points": ["Choice 1: X vs Y", "Choice 2: A vs B"],
  "acceptance_criteria": ["Criterion 1", "Criterion 2"]
}

Guidelines:
- Goal: Clear, measurable outcome
- Invariants: Things that MUST NOT break (tests, APIs, security)
- Touch set: Files likely to be modified (be conservative)
- Budget: Reasonable estimates to prevent scope creep
- Decision points: Where Claude has freedom to choose approach
- Acceptance: How to know the task is done"""


@dataclass
class PlannerResponse:
    """Response from GPT-5.2 planner."""

    blueprint: Blueprint | None
    raw_response: str
    latency_ms: int
    continuation_id: str | None = None
    error: str | None = None


def call_pal_planner(
    context: str,
    model: str = "openai/gpt-5.2",
    continuation_id: str | None = None,
    working_dir: Path | None = None,
) -> PlannerResponse:
    """DEPRECATED: Blueprint capture now happens via PostToolUse hook.

    The mastermind architecture changed:
    1. User sends `^ <prompt>` to trigger planning
    2. UserPromptSubmit hook injects PAL mandate instruction
    3. Claude calls mcp__pal__planner directly
    4. PostToolUse hook in _hooks_state.py captures the blueprint
    5. Blueprint stored in MastermindState for drift detection

    This function is retained for reference but should not be called.
    Use mcp__pal__planner MCP tool instead.

    Args:
        context: Packed context for planning
        model: Model to use (default: gpt-5.2)
        continuation_id: Optional continuation for multi-turn
        working_dir: Working directory for context

    Returns:
        PlannerResponse with error indicating deprecation
    """
    return PlannerResponse(
        blueprint=None,
        raw_response="",
        latency_ms=0,
        error="DEPRECATED: Use mcp__pal__planner MCP tool directly. "
        "Blueprint capture happens via PostToolUse hook in _hooks_state.py",
    )


def parse_blueprint_response(text: str) -> Blueprint | None:
    """Parse blueprint JSON from planner response."""
    try:
        # Handle markdown code blocks
        if "```" in text:
            lines = text.split("\n")
            json_lines = []
            in_block = False
            for line in lines:
                if line.strip().startswith("```"):
                    in_block = not in_block
                    continue
                if in_block:
                    json_lines.append(line)
            text = "\n".join(json_lines)

        # Find JSON object
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            data = json.loads(text[start:end])

            return Blueprint(
                goal=data.get("goal", ""),
                invariants=data.get("invariants", []),
                touch_set=data.get("touch_set", []),
                budget=data.get("budget", {}),
                decision_points=data.get("decision_points", []),
                acceptance_criteria=data.get("acceptance_criteria", []),
            )
    except (json.JSONDecodeError, KeyError, TypeError):
        pass

    return None


def format_blueprint_for_injection(blueprint: Blueprint) -> str:
    """Format blueprint for injection into Claude's context.

    Creates a concise summary suitable for system prompt injection.
    """
    lines = [
        "## Execution Blueprint",
        f"**Goal:** {blueprint.goal}",
        "",
        "**Invariants (must preserve):**",
    ]

    for inv in blueprint.invariants[:5]:  # Limit to 5
        lines.append(f"- {inv}")

    if blueprint.touch_set:
        lines.append("")
        lines.append("**Expected files:**")
        for f in blueprint.touch_set[:10]:  # Limit to 10
            lines.append(f"- {f}")

    if blueprint.decision_points:
        lines.append("")
        lines.append("**Decision points (your choice):**")
        for dp in blueprint.decision_points[:5]:
            lines.append(f"- {dp}")

    if blueprint.acceptance_criteria:
        lines.append("")
        lines.append("**Done when:**")
        for ac in blueprint.acceptance_criteria[:5]:
            lines.append(f"- {ac}")

    return "\n".join(lines)
