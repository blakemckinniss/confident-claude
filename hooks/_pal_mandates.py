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


def get_mandate(
    confidence: int,
    intent: Optional[str] = None,
    cascade_failure: bool = False,
    edit_oscillation: bool = False,
    sunk_cost: bool = False,
    goal_drift: bool = False,
    consecutive_failures: int = 0,
) -> Optional[Mandate]:
    """
    Evaluate conditions and return the highest-priority mandate.

    Args:
        confidence: Current confidence percentage (0-100)
        intent: Detected intent (debug, implement, refactor, etc.)
        cascade_failure: Same hook blocked 3+ times
        edit_oscillation: Same file edited 3+ times in 5 turns
        sunk_cost: 3+ consecutive failures on same approach
        goal_drift: Activity diverged from original goal
        consecutive_failures: Number of consecutive tool failures

    Returns:
        Mandate if conditions warrant, None otherwise
    """
    mandates = []

    # =========================================================================
    # TIER 1: CRITICAL (confidence < 30 OR cascade conditions)
    # =========================================================================

    if confidence < 30:
        mandates.append(
            Mandate(
                tool="mcp__pal__thinkdeep",
                directive=(
                    "🚨 **MANDATORY**: Confidence is critically low ({conf}%). "
                    "You MUST use `mcp__pal__thinkdeep` to analyze the situation "
                    "before ANY action. Do NOT proceed without external consultation."
                ).format(conf=confidence),
                priority=P_CRITICAL,
                reason=f"Critical confidence: {confidence}%",
            )
        )

    if cascade_failure:
        mandates.append(
            Mandate(
                tool="mcp__pal__thinkdeep",
                directive=(
                    "🚨 **MANDATORY**: Cascade failure detected - same block 3+ times. "
                    "You MUST use `mcp__pal__thinkdeep` to break the deadlock. "
                    "Current approach is failing repeatedly."
                ),
                priority=P_CRITICAL,
                reason="Cascade failure deadlock",
            )
        )

    if sunk_cost:
        mandates.append(
            Mandate(
                tool="mcp__pal__thinkdeep",
                directive=(
                    "🚨 **MANDATORY**: Sunk cost detected - 3+ failures on same approach. "
                    "You MUST use `mcp__pal__thinkdeep` to reconsider strategy. "
                    "Stop trying the same thing."
                ),
                priority=P_CRITICAL,
                reason="Sunk cost fallacy",
            )
        )

    # =========================================================================
    # TIER 2: HIGH (confidence 30-50 OR problematic patterns)
    # =========================================================================

    if 30 <= confidence < 50:
        mandates.append(
            Mandate(
                tool="mcp__pal__thinkdeep",
                directive=(
                    "⚠️ **REQUIRED**: Confidence is low ({conf}%). "
                    "Use `mcp__pal__thinkdeep` before making changes. "
                    "Research and validate your approach first."
                ).format(conf=confidence),
                priority=P_HIGH,
                reason=f"Low confidence: {confidence}%",
            )
        )

    if edit_oscillation:
        mandates.append(
            Mandate(
                tool="mcp__pal__codereview",
                directive=(
                    "⚠️ **REQUIRED**: Edit oscillation detected - thrashing on same file. "
                    "Use `mcp__pal__codereview` to get fresh perspective. "
                    "Stop editing until you understand the problem."
                ),
                priority=P_HIGH,
                reason="Edit oscillation",
            )
        )

    if goal_drift:
        mandates.append(
            Mandate(
                tool="mcp__pal__planner",
                directive=(
                    "⚠️ **REQUIRED**: Goal drift detected - straying from original task. "
                    "Use `mcp__pal__planner` to realign with the goal. "
                    "Refocus before continuing."
                ),
                priority=P_HIGH,
                reason="Goal drift",
            )
        )

    if consecutive_failures >= 3:
        mandates.append(
            Mandate(
                tool="mcp__pal__debug",
                directive=(
                    "⚠️ **REQUIRED**: {n} consecutive failures detected. "
                    "Use `mcp__pal__debug` to analyze what's going wrong. "
                    "Stop and diagnose before retrying."
                ).format(n=consecutive_failures),
                priority=P_HIGH,
                reason=f"{consecutive_failures} consecutive failures",
            )
        )

    # =========================================================================
    # TIER 3: MEDIUM (intent-based mandates at moderate confidence)
    # =========================================================================

    if intent == "debug" and confidence < 70:
        mandates.append(
            Mandate(
                tool="mcp__pal__debug",
                directive=(
                    "🔧 **RECOMMENDED**: Debug intent detected with confidence {conf}%. "
                    "Use `mcp__pal__debug` for systematic root cause analysis. "
                    "External perspective helps debugging."
                ).format(conf=confidence),
                priority=P_MEDIUM,
                reason=f"Debug intent at {confidence}%",
            )
        )

    if intent == "code_review" and confidence < 80:
        mandates.append(
            Mandate(
                tool="mcp__pal__codereview",
                directive=(
                    "🔍 **RECOMMENDED**: Code review intent detected. "
                    "Use `mcp__pal__codereview` for comprehensive analysis. "
                    "External review catches blind spots."
                ),
                priority=P_MEDIUM,
                reason="Code review intent",
            )
        )

    if intent == "refactor" and confidence < 75:
        mandates.append(
            Mandate(
                tool="mcp__pal__codereview",
                directive=(
                    "♻️ **RECOMMENDED**: Refactor intent at {conf}% confidence. "
                    "Use `mcp__pal__codereview` before restructuring. "
                    "Validate approach before major changes."
                ).format(conf=confidence),
                priority=P_MEDIUM,
                reason=f"Refactor at {confidence}%",
            )
        )

    # =========================================================================
    # TIER 4: CONTEXTUAL (architecture, complex decisions)
    # =========================================================================

    # These are detected by keyword patterns, not intent classifier
    # Handled separately in the hook

    # =========================================================================
    # Return highest priority mandate
    # =========================================================================

    if not mandates:
        return None

    return max(mandates, key=lambda m: m.priority)


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
