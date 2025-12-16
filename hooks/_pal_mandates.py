#!/usr/bin/env python3
"""
PAL Mandate Formula Book

Defines conditions that trigger MANDATORY PAL tool usage.
VERY AGGRESSIVE by design - prefer external consultation over solo work.

v2.0: Significantly lowered thresholds to encourage proactive PAL usage.
      Added keyword triggers for common scenarios.
      Made mandates fire during normal operation, not just problems.

Usage:
    from _pal_mandates import get_mandate
    mandate = get_mandate(confidence, intent, state_flags)
    if mandate:
        inject mandate.directive into context
"""

from __future__ import annotations

import re
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
P_PROACTIVE = 50  # Proactive consultation (new tier)


def _critical_mandates(
    confidence: int, cascade_failure: bool, sunk_cost: bool
) -> list[Mandate]:
    """Tier 1: Critical mandates (confidence < 50 OR cascade conditions)."""
    mandates = []
    # RAISED from <30 to <50 for more aggressive consultation
    if confidence < 50:
        mandates.append(
            Mandate(
                tool="mcp__pal__thinkdeep",
                directive=f"🚨 **MANDATORY**: Confidence below 50% ({confidence}%). "
                "You MUST use `mcp__pal__thinkdeep` to analyze the situation "
                "before ANY action. Do NOT proceed without external consultation.",
                priority=P_CRITICAL,
                reason=f"Low confidence: {confidence}%",
            )
        )
    if cascade_failure:
        mandates.append(
            Mandate(
                tool="mcp__pal__thinkdeep",
                directive="🚨 **MANDATORY**: Cascade failure detected - same block 3+ times. "
                "You MUST use `mcp__pal__thinkdeep` to break the deadlock. "
                "Current approach is failing repeatedly.",
                priority=P_CRITICAL,
                reason="Cascade failure deadlock",
            )
        )
    if sunk_cost:
        mandates.append(
            Mandate(
                tool="mcp__pal__thinkdeep",
                directive="🚨 **MANDATORY**: Sunk cost detected - 3+ failures on same approach. "
                "You MUST use `mcp__pal__thinkdeep` to reconsider strategy. "
                "Stop trying the same thing.",
                priority=P_CRITICAL,
                reason="Sunk cost fallacy",
            )
        )
    return mandates


def _high_mandates(
    confidence: int, edit_oscillation: bool, goal_drift: bool, consecutive_failures: int
) -> list[Mandate]:
    """Tier 2: High priority mandates (confidence 50-70 OR problematic patterns)."""
    mandates = []
    # RAISED from 30-50 to 50-70 range
    if 50 <= confidence < 70:
        mandates.append(
            Mandate(
                tool="mcp__pal__thinkdeep",
                directive=f"⚠️ **REQUIRED**: Confidence is moderate ({confidence}%). "
                "Use `mcp__pal__thinkdeep` before making significant changes. "
                "External validation improves outcomes.",
                priority=P_HIGH,
                reason=f"Moderate confidence: {confidence}%",
            )
        )
    if edit_oscillation:
        mandates.append(
            Mandate(
                tool="mcp__pal__codereview",
                directive="⚠️ **REQUIRED**: Edit oscillation detected - thrashing on same file. "
                "Use `mcp__pal__codereview` to get fresh perspective. "
                "Stop editing until you understand the problem.",
                priority=P_HIGH,
                reason="Edit oscillation",
            )
        )
    if goal_drift:
        mandates.append(
            Mandate(
                tool="mcp__pal__planner",
                directive="⚠️ **REQUIRED**: Goal drift detected - straying from original task. "
                "Use `mcp__pal__planner` to realign with the goal. "
                "Refocus before continuing.",
                priority=P_HIGH,
                reason="Goal drift",
            )
        )
    # LOWERED from 3 to 2 consecutive failures
    if consecutive_failures >= 2:
        mandates.append(
            Mandate(
                tool="mcp__pal__debug",
                directive=f"⚠️ **REQUIRED**: {consecutive_failures} consecutive failures detected. "
                "Use `mcp__pal__debug` to analyze what's going wrong. "
                "Stop and diagnose before retrying.",
                priority=P_HIGH,
                reason=f"{consecutive_failures} consecutive failures",
            )
        )
    return mandates


def _medium_mandates(intent: Optional[str], confidence: int) -> list[Mandate]:
    """Tier 3: Medium priority mandates (intent-based - fire at ANY confidence)."""
    mandates = []
    # REMOVED confidence gates - always recommend for these intents
    if intent == "debug":
        mandates.append(
            Mandate(
                tool="mcp__pal__debug",
                directive="🔧 **USE PAL**: Debug intent detected. "
                "Use `mcp__pal__debug` for systematic root cause analysis. "
                "External perspective catches blind spots in debugging.",
                priority=P_MEDIUM,
                reason="Debug intent",
            )
        )
    if intent == "code_review":
        mandates.append(
            Mandate(
                tool="mcp__pal__codereview",
                directive="🔍 **USE PAL**: Code review intent detected. "
                "Use `mcp__pal__codereview` for comprehensive analysis. "
                "External review is always more thorough.",
                priority=P_MEDIUM,
                reason="Code review intent",
            )
        )
    if intent == "refactor":
        mandates.append(
            Mandate(
                tool="mcp__pal__codereview",
                directive="♻️ **USE PAL**: Refactor intent detected. "
                "Use `mcp__pal__codereview` before restructuring. "
                "Validate approach with external perspective.",
                priority=P_MEDIUM,
                reason="Refactor intent",
            )
        )
    if intent == "implement":
        mandates.append(
            Mandate(
                tool="mcp__pal__planner",
                directive="🏗️ **USE PAL**: Implementation task detected. "
                "Use `mcp__pal__planner` to structure the approach. "
                "Planning with external input improves quality.",
                priority=P_PROACTIVE,
                reason="Implementation intent",
            )
        )
    if intent == "architecture":
        mandates.append(
            Mandate(
                tool="mcp__pal__consensus",
                directive="🏛️ **USE PAL**: Architecture decision detected. "
                "Use `mcp__pal__consensus` for multi-model perspective. "
                "Architecture decisions benefit from diverse viewpoints.",
                priority=P_HIGH,
                reason="Architecture intent",
            )
        )
    return mandates


def _proactive_mandates(confidence: int) -> list[Mandate]:
    """Tier 4: Proactive mandates - encourage PAL even when things are going well."""
    mandates = []
    # Proactive consultation even at moderate-high confidence
    if 70 <= confidence < 85:
        mandates.append(
            Mandate(
                tool="mcp__pal__chat",
                directive="💡 **CONSIDER PAL**: Confidence is good but not expert-level. "
                "Consider `mcp__pal__chat` for a quick sanity check. "
                "External perspective often reveals blind spots.",
                priority=P_LOW,
                reason=f"Proactive consultation at {confidence}%",
            )
        )
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
    mandates.extend(
        _high_mandates(confidence, edit_oscillation, goal_drift, consecutive_failures)
    )
    mandates.extend(_medium_mandates(intent, confidence))
    mandates.extend(_proactive_mandates(confidence))

    return max(mandates, key=lambda m: m.priority) if mandates else None


# =============================================================================
# KEYWORD TRIGGERS (AGGRESSIVE - fire on common patterns)
# =============================================================================

# Regex patterns for more flexible matching
_RE_ARCHITECTURE = re.compile(
    r"(architect|redesign|migrat|rewrite|restructur|overhaul|"
    r"fundamental\s+change|breaking\s+change|major\s+refactor|"
    r"new\s+approach|different\s+strategy|rethink|reimagine)",
    re.IGNORECASE,
)

_RE_DECISION = re.compile(
    r"(should\s+[iwe]|which\s+(approach|way|method|option)|"
    r"better\s+(option|way|approach)|trade.?off|pros?\s+and\s+cons?|"
    r"compare|versus|\bvs\b|alternative|best\s+way|optimal|"
    r"recommend|advice|suggest|opinion)",
    re.IGNORECASE,
)

_RE_DEBUG = re.compile(
    r"(debug|fix|broken|not\s+working|error|bug|issue|problem|"
    r"fail|crash|exception|wrong|unexpected|strange|weird|"
    r"doesn.t\s+work|can.t\s+figure|stuck|confused)",
    re.IGNORECASE,
)

_RE_IMPLEMENTATION = re.compile(
    r"(implement|build|create|add|develop|write|make|"
    r"new\s+feature|add\s+feature|how\s+to\s+|how\s+do\s+i|"
    r"need\s+to\s+(add|create|build|implement))",
    re.IGNORECASE,
)

_RE_REVIEW = re.compile(
    r"(review|check|audit|examine|inspect|look\s+at|"
    r"code\s+quality|clean\s+up|improve|optimize|"
    r"is\s+this\s+(good|right|correct|ok)|feedback)",
    re.IGNORECASE,
)

_RE_COMPLEX = re.compile(
    r"(complex|complicated|tricky|difficult|hard|"
    r"challenging|advanced|sophisticated|intricate|"
    r"multi.?step|multi.?part|several\s+files)",
    re.IGNORECASE,
)

_RE_UNCERTAINTY = re.compile(
    r"(not\s+sure|uncertain|unsure|don.t\s+know|"
    r"maybe|perhaps|possibly|might|could\s+be|"
    r"i\s+think|i\s+guess|wondering|confused)",
    re.IGNORECASE,
)

_RE_API_DOCS = re.compile(
    r"(api|sdk|library|framework|package|module|"
    r"documentation|docs|how\s+does\s+.+\s+work|"
    r"latest|current\s+version|deprecat|breaking)",
    re.IGNORECASE,
)


def check_keyword_mandate(prompt: str, confidence: int) -> Optional[Mandate]:
    """
    Check for keyword-triggered mandates in user prompt.

    AGGRESSIVE: Triggers on many common patterns to encourage PAL usage.

    Args:
        prompt: User's prompt text
        confidence: Current confidence

    Returns:
        Mandate if keywords detected, None otherwise
    """
    # Skip very short prompts or slash commands
    if len(prompt) < 10 or prompt.startswith("/"):
        return None

    # Architecture keywords → consensus (ALWAYS HIGH PRIORITY)
    if _RE_ARCHITECTURE.search(prompt):
        return Mandate(
            tool="mcp__pal__consensus",
            directive=(
                "🏗️ **USE PAL**: Architecture/migration task detected. "
                "Use `mcp__pal__consensus` for multi-model perspective. "
                "Major changes REQUIRE external validation."
            ),
            priority=P_HIGH,
            reason="Architecture keywords",
        )

    # Decision keywords → consensus
    if _RE_DECISION.search(prompt):
        return Mandate(
            tool="mcp__pal__consensus",
            directive=(
                "⚖️ **USE PAL**: Decision-making detected. "
                "Use `mcp__pal__consensus` for balanced multi-model analysis. "
                "Decisions benefit from diverse perspectives."
            ),
            priority=P_MEDIUM,
            reason="Decision keywords",
        )

    # Debug keywords → debug tool
    if _RE_DEBUG.search(prompt):
        return Mandate(
            tool="mcp__pal__debug",
            directive=(
                "🔧 **USE PAL**: Debug/fix task detected. "
                "Use `mcp__pal__debug` for systematic root cause analysis. "
                "External debugging perspective catches blind spots."
            ),
            priority=P_MEDIUM,
            reason="Debug keywords",
        )

    # Uncertainty keywords → thinkdeep
    if _RE_UNCERTAINTY.search(prompt):
        return Mandate(
            tool="mcp__pal__thinkdeep",
            directive=(
                "🤔 **USE PAL**: Uncertainty detected in request. "
                "Use `mcp__pal__thinkdeep` to clarify the approach. "
                "When uncertain, external analysis helps."
            ),
            priority=P_MEDIUM,
            reason="Uncertainty keywords",
        )

    # Complex task keywords → planner
    if _RE_COMPLEX.search(prompt):
        return Mandate(
            tool="mcp__pal__planner",
            directive=(
                "🧩 **USE PAL**: Complex task detected. "
                "Use `mcp__pal__planner` to structure the approach. "
                "Complex tasks benefit from external planning."
            ),
            priority=P_PROACTIVE,
            reason="Complexity keywords",
        )

    # Review keywords → codereview
    if _RE_REVIEW.search(prompt):
        return Mandate(
            tool="mcp__pal__codereview",
            directive=(
                "🔍 **USE PAL**: Review/quality task detected. "
                "Use `mcp__pal__codereview` for thorough analysis. "
                "External review is always more comprehensive."
            ),
            priority=P_PROACTIVE,
            reason="Review keywords",
        )

    # API/docs keywords → apilookup
    if _RE_API_DOCS.search(prompt):
        return Mandate(
            tool="mcp__pal__apilookup",
            directive=(
                "📚 **USE PAL**: API/library question detected. "
                "Use `mcp__pal__apilookup` for current documentation. "
                "Get authoritative info before implementing."
            ),
            priority=P_LOW,
            reason="API/docs keywords",
        )

    # Implementation keywords → planner (catch-all for substantial work)
    if _RE_IMPLEMENTATION.search(prompt) and len(prompt) > 30:
        return Mandate(
            tool="mcp__pal__planner",
            directive=(
                "🏗️ **CONSIDER PAL**: Implementation task detected. "
                "Consider `mcp__pal__planner` to structure approach. "
                "Planning improves implementation quality."
            ),
            priority=P_LOW,
            reason="Implementation keywords",
        )

    return None


# =============================================================================
# SUMMARY: Mandate Thresholds (v2.0 - AGGRESSIVE)
# =============================================================================
#
# CONFIDENCE-BASED (always fire):
# | Condition              | Tool           | Priority | Confidence Range |
# |------------------------|----------------|----------|------------------|
# | confidence < 50        | thinkdeep      | CRITICAL | 0-49             |
# | cascade_failure        | thinkdeep      | CRITICAL | any              |
# | sunk_cost              | thinkdeep      | CRITICAL | any              |
# | confidence 50-70       | thinkdeep      | HIGH     | 50-69            |
# | edit_oscillation       | codereview     | HIGH     | any              |
# | goal_drift             | planner        | HIGH     | any              |
# | failures >= 2          | debug          | HIGH     | any              |
# | confidence 70-85       | chat           | LOW      | 70-84 (proactive)|
#
# INTENT-BASED (fire at ANY confidence):
# | Intent                 | Tool           | Priority |
# |------------------------|----------------|----------|
# | debug                  | debug          | MEDIUM   |
# | code_review            | codereview     | MEDIUM   |
# | refactor               | codereview     | MEDIUM   |
# | implement              | planner        | PROACTIVE|
# | architecture           | consensus      | HIGH     |
#
# KEYWORD-BASED (fire on pattern match):
# | Keywords               | Tool           | Priority |
# |------------------------|----------------|----------|
# | architect/migrate/etc  | consensus      | HIGH     |
# | should/which/compare   | consensus      | MEDIUM   |
# | debug/fix/broken/etc   | debug          | MEDIUM   |
# | uncertain/unsure/etc   | thinkdeep      | MEDIUM   |
# | complex/difficult/etc  | planner        | PROACTIVE|
# | review/audit/check     | codereview     | PROACTIVE|
# | api/docs/library       | apilookup      | LOW      |
# | implement/build/create | planner        | LOW      |
#
