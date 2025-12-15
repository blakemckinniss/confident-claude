#!/usr/bin/env python3
"""
PAL Mandate Formula Book

Defines conditions that trigger MANDATORY PAL tool usage.
Aggressive by design - mandates fire automatically, not suggestions.

Usage:
    from _pal_mandates import get_mandate
    mandate = get_mandate(confidence, intent, state_flags)
    if mandate:
        inject mandate.directive into context
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class Mandate:
    """A mandatory PAL tool invocation."""

    tool: str  # MCP tool name
    directive: str  # Injected text
    priority: int  # Higher = more urgent (1-100)
    reason: str  # Why this mandate fired


# =============================================================================
# FORMULA BOOK: Condition → Mandate mappings
# =============================================================================

# Priority levels
P_CRITICAL = 100  # Must do immediately
P_HIGH = 80  # Should do before proceeding
P_MEDIUM = 60  # Recommended before major actions
P_LOW = 40  # Suggested but optional


def _critical_mandates(confidence: int, cascade_failure: bool, sunk_cost: bool) -> list[Mandate]:
    """Tier 1: Critical mandates (confidence < 30 OR cascade conditions)."""
    mandates = []
    if confidence < 30:
        mandates.append(Mandate(
            tool="mcp__pal__thinkdeep",
            directive=f"🚨 **MANDATORY**: Confidence is critically low ({confidence}%). "
                     "You MUST use `mcp__pal__thinkdeep` to analyze the situation "
                     "before ANY action. Do NOT proceed without external consultation.",
            priority=P_CRITICAL,
            reason=f"Critical confidence: {confidence}%",
        ))
    if cascade_failure:
        mandates.append(Mandate(
            tool="mcp__pal__thinkdeep",
            directive="🚨 **MANDATORY**: Cascade failure detected - same block 3+ times. "
                     "You MUST use `mcp__pal__thinkdeep` to break the deadlock. "
                     "Current approach is failing repeatedly.",
            priority=P_CRITICAL,
            reason="Cascade failure deadlock",
        ))
    if sunk_cost:
        mandates.append(Mandate(
            tool="mcp__pal__thinkdeep",
            directive="🚨 **MANDATORY**: Sunk cost detected - 3+ failures on same approach. "
                     "You MUST use `mcp__pal__thinkdeep` to reconsider strategy. "
                     "Stop trying the same thing.",
            priority=P_CRITICAL,
            reason="Sunk cost fallacy",
        ))
    return mandates


def _high_mandates(
    confidence: int, edit_oscillation: bool, goal_drift: bool, consecutive_failures: int
) -> list[Mandate]:
    """Tier 2: High priority mandates (confidence 30-50 OR problematic patterns)."""
    mandates = []
    if 30 <= confidence < 50:
        mandates.append(Mandate(
            tool="mcp__pal__thinkdeep",
            directive=f"⚠️ **REQUIRED**: Confidence is low ({confidence}%). "
                     "Use `mcp__pal__thinkdeep` before making changes. "
                     "Research and validate your approach first.",
            priority=P_HIGH,
            reason=f"Low confidence: {confidence}%",
        ))
    if edit_oscillation:
        mandates.append(Mandate(
            tool="mcp__pal__codereview",
            directive="⚠️ **REQUIRED**: Edit oscillation detected - thrashing on same file. "
                     "Use `mcp__pal__codereview` to get fresh perspective. "
                     "Stop editing until you understand the problem.",
            priority=P_HIGH,
            reason="Edit oscillation",
        ))
    if goal_drift:
        mandates.append(Mandate(
            tool="mcp__pal__planner",
            directive="⚠️ **REQUIRED**: Goal drift detected - straying from original task. "
                     "Use `mcp__pal__planner` to realign with the goal. "
                     "Refocus before continuing.",
            priority=P_HIGH,
            reason="Goal drift",
        ))
    if consecutive_failures >= 3:
        mandates.append(Mandate(
            tool="mcp__pal__debug",
            directive=f"⚠️ **REQUIRED**: {consecutive_failures} consecutive failures detected. "
                     "Use `mcp__pal__debug` to analyze what's going wrong. "
                     "Stop and diagnose before retrying.",
            priority=P_HIGH,
            reason=f"{consecutive_failures} consecutive failures",
        ))
    return mandates


def _medium_mandates(intent: Optional[str], confidence: int) -> list[Mandate]:
    """Tier 3: Medium priority mandates (intent-based at moderate confidence)."""
    mandates = []
    if intent == "debug" and confidence < 70:
        mandates.append(Mandate(
            tool="mcp__pal__debug",
            directive=f"🔧 **RECOMMENDED**: Debug intent detected with confidence {confidence}%. "
                     "Use `mcp__pal__debug` for systematic root cause analysis. "
                     "External perspective helps debugging.",
            priority=P_MEDIUM,
            reason=f"Debug intent at {confidence}%",
        ))
    if intent == "code_review" and confidence < 80:
        mandates.append(Mandate(
            tool="mcp__pal__codereview",
            directive="🔍 **RECOMMENDED**: Code review intent detected. "
                     "Use `mcp__pal__codereview` for comprehensive analysis. "
                     "External review catches blind spots.",
            priority=P_MEDIUM,
            reason="Code review intent",
        ))
    if intent == "refactor" and confidence < 75:
        mandates.append(Mandate(
            tool="mcp__pal__codereview",
            directive=f"♻️ **RECOMMENDED**: Refactor intent at {confidence}% confidence. "
                     "Use `mcp__pal__codereview` before restructuring. "
                     "Validate approach before major changes.",
            priority=P_MEDIUM,
            reason=f"Refactor at {confidence}%",
        ))
    return mandates


def get_mandate(
    confidence: int,
    intent: Optional[str] = None,
    cascade_failure: bool = False,
    edit_oscillation: bool = False,
    sunk_cost: bool = False,
    goal_drift: bool = False,
    consecutive_failures: int = 0,
) -> Optional[Mandate]:
    """Evaluate conditions and return the highest-priority mandate."""
    mandates = []
    mandates.extend(_critical_mandates(confidence, cascade_failure, sunk_cost))
    mandates.extend(_high_mandates(confidence, edit_oscillation, goal_drift, consecutive_failures))
    mandates.extend(_medium_mandates(intent, confidence))

    return max(mandates, key=lambda m: m.priority) if mandates else None


# =============================================================================
# KEYWORD TRIGGERS (for architectural/complex decisions)
# =============================================================================

ARCHITECTURE_KEYWORDS = {
    "architecture",
    "redesign",
    "migrate",
    "migration",
    "refactor entire",
    "rewrite",
    "new approach",
    "different strategy",
    "fundamental change",
    "breaking change",
}

DECISION_KEYWORDS = {
    "should i",
    "should we",
    "which approach",
    "better option",
    "trade-off",
    "tradeoff",
    "pros and cons",
    "compare",
    "versus",
    " vs ",
    "alternative",
}


def check_keyword_mandate(prompt: str, confidence: int) -> Optional[Mandate]:
    """
    Check for keyword-triggered mandates in user prompt.

    Args:
        prompt: User's prompt text
        confidence: Current confidence

    Returns:
        Mandate if keywords detected, None otherwise
    """
    prompt_lower = prompt.lower()

    # Architecture keywords → planner/consensus
    if any(kw in prompt_lower for kw in ARCHITECTURE_KEYWORDS):
        return Mandate(
            tool="mcp__pal__consensus",
            directive=(
                "🏗️ **RECOMMENDED**: Architecture/migration keywords detected. "
                "Use `mcp__pal__consensus` for multi-perspective analysis. "
                "Major changes need external validation."
            ),
            priority=P_MEDIUM if confidence >= 70 else P_HIGH,
            reason="Architecture keywords",
        )

    # Decision keywords → consensus
    if any(kw in prompt_lower for kw in DECISION_KEYWORDS):
        return Mandate(
            tool="mcp__pal__consensus",
            directive=(
                "⚖️ **RECOMMENDED**: Decision-making keywords detected. "
                "Consider `mcp__pal__consensus` for balanced analysis. "
                "Multiple perspectives improve decisions."
            ),
            priority=P_LOW if confidence >= 80 else P_MEDIUM,
            reason="Decision keywords",
        )

    return None


# =============================================================================
# SUMMARY: Mandate Thresholds
# =============================================================================
#
# | Condition              | Tool           | Priority | Confidence Range |
# |------------------------|----------------|----------|------------------|
# | confidence < 30        | thinkdeep      | CRITICAL | 0-29             |
# | cascade_failure        | thinkdeep      | CRITICAL | any              |
# | sunk_cost              | thinkdeep      | CRITICAL | any              |
# | confidence 30-50       | thinkdeep      | HIGH     | 30-49            |
# | edit_oscillation       | codereview     | HIGH     | any              |
# | goal_drift             | planner        | HIGH     | any              |
# | failures >= 3          | debug          | HIGH     | any              |
# | intent=debug + <70     | debug          | MEDIUM   | <70              |
# | intent=code_review     | codereview     | MEDIUM   | <80              |
# | intent=refactor + <75  | codereview     | MEDIUM   | <75              |
# | architecture keywords  | consensus      | MEDIUM   | <70, else LOW    |
# | decision keywords      | consensus      | LOW-MED  | varies           |
#
