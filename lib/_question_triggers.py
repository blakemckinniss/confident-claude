"""
Question Trigger Detection Library

Detects situations where proactive questioning adds value:
- Assumption surfacing (before proceeding on unstated assumptions)
- Scope/priority clarification (multiple valid paths exist)
- Build vs buy decisions (new file/module creation)
- Implementation detail choices (technical decisions user might care about)

Philosophy: Questions are a feature, not a bug. They demonstrate epistemic humility
and ensure alignment with user's underlying interests.
"""

import re
from dataclasses import dataclass
from typing import Optional


@dataclass
class QuestionOpportunity:
    """Represents a detected opportunity for clarifying questions."""

    category: str  # assumption, scope, build_vs_buy, implementation, priority
    confidence: float  # 0-1, how confident we are this needs a question
    suggested_questions: list[str]
    reason: str


# =============================================================================
# DETECTION PATTERNS
# =============================================================================

# Vague/ambiguous prompt patterns that benefit from clarification
_VAGUE_PATTERNS = [
    (re.compile(r"\b(something|somehow|some\s+way)\b", re.I), "vague_mechanism"),
    (
        re.compile(
            r"\b(better|improve|optimize|enhance)\b(?!\s+\w+\s+(by|with|using))", re.I
        ),
        "undefined_improvement",
    ),
    (
        re.compile(r"\b(fix|handle|deal\s+with)\s+(it|this|that)\b", re.I),
        "ambiguous_target",
    ),
    (
        re.compile(r"\b(make\s+it|should\s+be)\s+(good|nice|clean|proper)\b", re.I),
        "subjective_quality",
    ),
    (re.compile(r"\b(etc|and\s+so\s+on|and\s+stuff)\b", re.I), "incomplete_list"),
]

# Patterns suggesting multiple valid approaches
_MULTI_PATH_PATTERNS = [
    (
        re.compile(r"\b(add|implement|create|build)\s+(a|an|the)\s+\w+", re.I),
        "new_feature",
    ),
    (
        re.compile(r"\b(refactor|restructure|reorganize)\b", re.I),
        "architectural_change",
    ),
    (re.compile(r"\b(migrate|convert|upgrade)\b", re.I), "migration"),
    (re.compile(r"\b(integrate|connect|hook\s+up)\b", re.I), "integration"),
]

# Build vs buy signals
_BUILD_SIGNALS = [
    (
        re.compile(
            r"\b(build|create|implement|write|make)\s+(a|an|my|our|the)\s+\w+\s*(app|tool|system|service|bot|script|cli|api)\b",
            re.I,
        ),
        "app_creation",
    ),
    (re.compile(r"\bfrom\s+scratch\b", re.I), "from_scratch"),
    (re.compile(r"\b(custom|bespoke|homegrown)\b", re.I), "custom_solution"),
]

# Implementation choice signals
_IMPL_CHOICE_PATTERNS = [
    (re.compile(r"\b(database|db|storage|persistence)\b", re.I), "storage_choice"),
    (re.compile(r"\b(auth|authentication|login|oauth)\b", re.I), "auth_choice"),
    (re.compile(r"\b(api|endpoint|rest|graphql)\b", re.I), "api_design"),
    (re.compile(r"\b(ui|frontend|interface|component)\b", re.I), "ui_approach"),
    (re.compile(r"\b(test|testing|coverage)\b", re.I), "testing_strategy"),
]

# Assumption indicators (Claude might assume without asking)
_ASSUMPTION_RISK_PATTERNS = [
    (re.compile(r"^(do|can|will|should)\s+", re.I), "yes_no_assumption"),
    (
        re.compile(r"\b(the|this|that)\s+(file|code|function|class)\b", re.I),
        "specific_target_assumption",
    ),
    (re.compile(r"\b(all|every|each)\s+\w+", re.I), "scope_assumption"),
    (re.compile(r"\b(always|never|must|required)\b", re.I), "constraint_assumption"),
]


# =============================================================================
# QUESTION TEMPLATES
# =============================================================================

QUESTION_TEMPLATES = {
    "scope": [
        "What's the scope here - minimal viable or comprehensive?",
        "Should this cover edge cases now or start simple?",
        "Any specific constraints I should know about?",
    ],
    "priority": [
        "Which aspect is most important to get right first?",
        "If we can only do one thing well, what should it be?",
        "What's the priority order if these conflict?",
    ],
    "build_vs_buy": [
        "Have you looked at existing solutions like {alternatives}?",
        "Is this a learning exercise or production need?",
        "What's missing from existing tools that we need to build?",
    ],
    "implementation": [
        "Any preference on the approach here?",
        "Should I optimize for simplicity or flexibility?",
        "Are there existing patterns in the codebase I should follow?",
    ],
    "assumption": [
        "I'm assuming {assumption} - is that right?",
        "Just to confirm: you want {interpretation}?",
        "Before I proceed: {clarification}?",
    ],
}


# =============================================================================
# CORE DETECTION
# =============================================================================


def detect_question_opportunities(
    prompt: str,
    confidence_level: int = 70,
    turn_count: int = 0,
    files_mentioned: list[str] | None = None,
) -> list[QuestionOpportunity]:
    """
    Analyze prompt for situations that benefit from clarifying questions.

    Args:
        prompt: User's prompt text
        confidence_level: Current confidence (0-100)
        turn_count: Current turn in conversation
        files_mentioned: Files referenced in prompt

    Returns:
        List of QuestionOpportunity objects, sorted by confidence
    """
    opportunities = []
    prompt_lower = prompt.lower()

    # Skip trivial prompts
    if len(prompt) < 20 or re.match(r"^(yes|no|ok|hi|thanks|/\w+)\b", prompt_lower):
        return []

    # 1. Check for vague/ambiguous language
    for pattern, signal_type in _VAGUE_PATTERNS:
        if pattern.search(prompt):
            opportunities.append(
                QuestionOpportunity(
                    category="assumption",
                    confidence=0.7,
                    suggested_questions=QUESTION_TEMPLATES["assumption"],
                    reason=f"Vague language detected: {signal_type}",
                )
            )
            break  # One vagueness signal is enough

    # 2. Check for multi-path situations
    for pattern, signal_type in _MULTI_PATH_PATTERNS:
        if pattern.search(prompt):
            opportunities.append(
                QuestionOpportunity(
                    category="scope",
                    confidence=0.6,
                    suggested_questions=QUESTION_TEMPLATES["scope"]
                    + QUESTION_TEMPLATES["priority"],
                    reason=f"Multiple valid approaches possible: {signal_type}",
                )
            )
            break

    # 3. Check for build vs buy opportunities
    for pattern, signal_type in _BUILD_SIGNALS:
        if pattern.search(prompt):
            opportunities.append(
                QuestionOpportunity(
                    category="build_vs_buy",
                    confidence=0.8,
                    suggested_questions=QUESTION_TEMPLATES["build_vs_buy"],
                    reason=f"Custom build requested: {signal_type}",
                )
            )
            break

    # 4. Check for implementation choices
    impl_signals = []
    for pattern, signal_type in _IMPL_CHOICE_PATTERNS:
        if pattern.search(prompt):
            impl_signals.append(signal_type)

    if len(impl_signals) >= 2:  # Multiple technical domains = choices needed
        opportunities.append(
            QuestionOpportunity(
                category="implementation",
                confidence=0.5,
                suggested_questions=QUESTION_TEMPLATES["implementation"],
                reason=f"Technical choices needed: {', '.join(impl_signals[:3])}",
            )
        )

    # 5. Boost confidence thresholds based on state
    if confidence_level < 70:
        # Low confidence = more questions are valuable
        for opp in opportunities:
            opp.confidence = min(1.0, opp.confidence + 0.2)

    if turn_count <= 2:
        # Early in conversation = questions establish alignment
        for opp in opportunities:
            opp.confidence = min(1.0, opp.confidence + 0.1)

    # Sort by confidence descending
    opportunities.sort(key=lambda x: x.confidence, reverse=True)

    return opportunities


def format_question_suggestion(
    opportunities: list[QuestionOpportunity], max_questions: int = 2
) -> Optional[str]:
    """
    Format question opportunities into a suggestion string for hook injection.

    Args:
        opportunities: List of detected opportunities
        max_questions: Maximum number of questions to suggest

    Returns:
        Formatted suggestion string or None if no suggestions
    """
    if not opportunities:
        return None

    # Take top opportunities
    top = opportunities[:max_questions]

    lines = ["❓ **QUESTION OPPORTUNITY** - Consider clarifying:"]

    for opp in top:
        category_emoji = {
            "assumption": "🤔",
            "scope": "📏",
            "build_vs_buy": "🛒",
            "implementation": "⚙️",
            "priority": "🎯",
        }.get(opp.category, "❓")

        lines.append(
            f"  {category_emoji} **{opp.category.replace('_', ' ').title()}**: {opp.reason}"
        )

        # Show one example question
        if opp.suggested_questions:
            example = opp.suggested_questions[0]
            # Clean up template placeholders
            example = re.sub(r"\{[^}]+\}", "...", example)
            lines.append(f'     → "{example}"')

    lines.append("")
    lines.append(
        "💡 Use `AskUserQuestion` tool for structured multi-choice questions (+20 confidence)"
    )

    return "\n".join(lines)


def should_force_question(
    prompt: str,
    confidence_level: int,
    consecutive_actions: int = 0,
) -> tuple[bool, Optional[str]]:
    """
    Determine if a question should be forced (blocking) vs suggested (advisory).

    Returns:
        (should_force, reason) - True if question is mandatory
    """
    # Force question at very low confidence before major actions
    if confidence_level < 50:
        opportunities = detect_question_opportunities(prompt, confidence_level)
        if any(o.category in ("scope", "build_vs_buy") for o in opportunities):
            return True, "Low confidence + ambiguous scope requires clarification"

    # Force question after many actions without user input
    if consecutive_actions >= 10:
        return True, "Extended autonomous work - check alignment"

    return False, None
