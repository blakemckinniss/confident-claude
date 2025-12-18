"""Capability router for intelligent tool selection.

Builds routing prompts with capability inventory and parses toolchain responses.
The actual PAL MCP call is made by the hook layer (Claude runtime context).

Model selection: PAL auto-selects by default based on intelligence scores.
Claude can override with specific model when task warrants it.

Usage in hook_integration.py:
    from mastermind.router_gpt import build_routing_prompt, parse_toolchain

    prompt = build_routing_prompt(task)
    # Hook calls: mcp__pal__chat(prompt=prompt)  # PAL auto-selects model
    toolchain = parse_toolchain(response_text)
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Paths
CAPABILITIES_DIR = Path.home() / ".claude" / "capabilities"
INDEX_PATH = CAPABILITIES_DIR / "capabilities_index.json"

# GPT routing system prompt
ROUTING_SYSTEM_PROMPT = """You are a capability router for a Claude Code framework.

Given a task and a list of available capabilities (agents, MCP tools, ops scripts, slash commands),
recommend a staged toolchain to accomplish the task.

Output ONLY valid JSON matching this schema:
{
  "schema_version": "1.0",
  "toolchain": [
    {
      "stage": "triage|locate|analyze|modify|validate|report",
      "primary": {
        "capability_id": "exact_id_from_index",
        "params_hint": {}
      },
      "alternatives": [],
      "rationale": "Why this tool for this stage",
      "constraints": {
        "requires": ["network", "repo_indexed", "local_exec", "browser"],
        "risk_ack": {"writes_repo": false, "executes_code": false, "network": false}
      }
    }
  ],
  "notes": {
    "why_this_chain": "Overall reasoning",
    "assumptions": ["assumption1"],
    "fallback_strategy": "If primary fails, do X"
  },
  "confidence": {"overall": 0.85}
}

Rules:
- Use ONLY capability IDs from the provided index
- Max 5 toolchain steps
- Order stages logically (triage→locate→analyze→modify→validate→report)
- Prefer primitives over orchestrators for precision
- Match capability tags to task intent
- Acknowledge risks in constraints.risk_ack"""


@dataclass
class ToolchainStep:
    """A single step in the recommended toolchain."""

    stage: str
    capability_id: str
    rationale: str
    alternatives: list[str] = field(default_factory=list)
    params_hint: dict[str, Any] = field(default_factory=dict)
    requires: list[str] = field(default_factory=list)
    risk_ack: dict[str, bool] = field(default_factory=dict)


@dataclass
class ToolchainRecommendation:
    """Parsed toolchain recommendation from GPT-5.2."""

    steps: list[ToolchainStep]
    why_this_chain: str
    assumptions: list[str]
    fallback_strategy: str
    confidence: float
    raw_response: str = ""
    error: str | None = None

    @property
    def primary_ids(self) -> list[str]:
        """Get list of primary capability IDs in order."""
        return [step.capability_id for step in self.steps]

    @property
    def is_valid(self) -> bool:
        """Check if recommendation is usable."""
        return len(self.steps) > 0 and self.error is None


def load_capabilities_index() -> dict[str, Any]:
    """Load the capabilities index JSON."""
    if not INDEX_PATH.exists():
        return {"capabilities": [], "inventory_version": "missing"}

    with open(INDEX_PATH) as f:
        return json.load(f)


def build_compact_index(index: dict[str, Any], max_capabilities: int = 100) -> str:
    """Build a compact version of the index for the prompt.

    Only includes essential fields to save tokens.
    """
    capabilities = index.get("capabilities", [])[:max_capabilities]

    compact = []
    for cap in capabilities:
        compact.append(
            {
                "id": cap.get("id"),
                "type": cap.get("type"),
                "name": cap.get("name"),
                "summary": cap.get("summary", "")[:100],
                "stages": cap.get("stages", []),
                "tags": cap.get("tags", [])[:5],
                "risk": {
                    "writes_repo": cap.get("risk", {}).get("writes_repo", False),
                    "network": cap.get("risk", {}).get("network", False),
                },
            }
        )

    return json.dumps(compact, separators=(",", ":"))


def build_routing_prompt(task: str, task_type: str = "general") -> str:
    """Build the full routing prompt for GPT-5.2.

    Args:
        task: The user's task/request
        task_type: Hint from Groq classification (debugging, planning, etc.)

    Returns:
        Complete prompt string to send to PAL MCP chat
    """
    index = load_capabilities_index()
    compact_index = build_compact_index(index)

    prompt = f"""{ROUTING_SYSTEM_PROMPT}

## Available Capabilities (version: {index.get("inventory_version", "unknown")})
{compact_index}

## Task Classification
Type: {task_type}

## User Task
{task}

## Instructions
Recommend a toolchain (1-5 steps) to accomplish this task.
Consider the task type hint but make your own assessment.
Output ONLY the JSON toolchain recommendation."""

    return prompt


def _parse_json_response(text: str) -> dict[str, Any]:
    """Parse JSON from GPT response, handling markdown code blocks."""
    text = text.strip()

    # Handle markdown code blocks
    if text.startswith("```"):
        lines = text.split("\n")
        # Find end of code block
        end_idx = len(lines)
        for i, line in enumerate(lines[1:], 1):
            if line.strip() == "```":
                end_idx = i
                break
        text = "\n".join(lines[1:end_idx])

    # Try direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try to extract JSON object
    start = text.find("{")
    end = text.rfind("}") + 1
    if start >= 0 and end > start:
        return json.loads(text[start:end])

    raise json.JSONDecodeError("No valid JSON found", text, 0)


def parse_toolchain(response_text: str) -> ToolchainRecommendation:
    """Parse GPT-5.2 response into structured ToolchainRecommendation.

    Args:
        response_text: Raw text response from PAL MCP chat

    Returns:
        ToolchainRecommendation with parsed steps or error
    """
    try:
        data = _parse_json_response(response_text)
    except json.JSONDecodeError as e:
        return ToolchainRecommendation(
            steps=[],
            why_this_chain="",
            assumptions=[],
            fallback_strategy="",
            confidence=0.0,
            raw_response=response_text,
            error=f"JSON parse error: {e}",
        )

    # Extract toolchain steps
    steps = []
    for step_data in data.get("toolchain", []):
        primary = step_data.get("primary", {})
        constraints = step_data.get("constraints", {})

        steps.append(
            ToolchainStep(
                stage=step_data.get("stage", "analyze"),
                capability_id=primary.get("capability_id", ""),
                rationale=step_data.get("rationale", ""),
                alternatives=[
                    alt.get("capability_id", "")
                    for alt in step_data.get("alternatives", [])
                ],
                params_hint=primary.get("params_hint", {}),
                requires=constraints.get("requires", []),
                risk_ack=constraints.get("risk_ack", {}),
            )
        )

    # Extract notes
    notes = data.get("notes", {})
    confidence_data = data.get("confidence", {})

    return ToolchainRecommendation(
        steps=steps,
        why_this_chain=notes.get("why_this_chain", ""),
        assumptions=notes.get("assumptions", []),
        fallback_strategy=notes.get("fallback_strategy", ""),
        confidence=confidence_data.get("overall", 0.5),
        raw_response=response_text,
    )


def format_toolchain_injection(recommendation: ToolchainRecommendation) -> str:
    """Format toolchain recommendation for hook injection.

    Returns markdown-formatted suggestion to inject into user prompt context.
    """
    if not recommendation.is_valid:
        return ""

    lines = [
        "# Intelligent Routing Recommendation",
        "",
        f"**Confidence:** {recommendation.confidence:.0%}",
        "",
        "## Suggested Toolchain",
        "",
    ]

    for i, step in enumerate(recommendation.steps, 1):
        lines.append(f"### Step {i}: {step.stage.title()}")
        lines.append(f"**Tool:** `{step.capability_id}`")
        lines.append(f"**Why:** {step.rationale}")
        if step.alternatives:
            lines.append(
                f"**Alternatives:** {', '.join(f'`{a}`' for a in step.alternatives)}"
            )
        if step.requires:
            lines.append(f"**Requires:** {', '.join(step.requires)}")
        lines.append("")

    if recommendation.why_this_chain:
        lines.append("## Reasoning")
        lines.append(recommendation.why_this_chain)
        lines.append("")

    if recommendation.fallback_strategy:
        lines.append("## Fallback")
        lines.append(recommendation.fallback_strategy)

    return "\n".join(lines)


def get_capability_by_id(capability_id: str) -> dict[str, Any] | None:
    """Look up a capability by ID from the index."""
    index = load_capabilities_index()
    for cap in index.get("capabilities", []):
        if cap.get("id") == capability_id:
            return cap
    return None


def validate_toolchain(recommendation: ToolchainRecommendation) -> list[str]:
    """Validate that toolchain IDs exist in the index.

    Returns list of validation errors (empty if valid).
    """
    errors = []
    index = load_capabilities_index()
    valid_ids = {cap.get("id") for cap in index.get("capabilities", [])}

    for step in recommendation.steps:
        if step.capability_id not in valid_ids:
            errors.append(f"Unknown capability ID: {step.capability_id}")
        for alt in step.alternatives:
            if alt and alt not in valid_ids:
                errors.append(f"Unknown alternative ID: {alt}")

    return errors
