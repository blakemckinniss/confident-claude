#!/usr/bin/env python3
"""
Complexity Detection - BMAD-inspired scale-adaptive intelligence.

Classifies tasks as trivial/standard/complex to tune hook verbosity
and ceremony level. Inspired by BMAD's Quick Flow vs BMad Method vs Enterprise.

Usage:
    complexity = assess_complexity(prompt, context)
    # complexity.level: "trivial" | "standard" | "complex"
    # complexity.score: 0-100
    # complexity.factors: list of contributing factors
    # complexity.recommendations: suggested adjustments

Integration:
    Hooks can check complexity to adjust their behavior:
    - Trivial: Skip verbose suggestions, minimal gates
    - Standard: Normal hook behavior
    - Complex: Enhanced suggestions, require external validation
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

# Complexity thresholds (BMAD-inspired)
TRIVIAL_THRESHOLD = 25  # Quick Flow territory
STANDARD_THRESHOLD = 60  # BMad Method territory
# Above 60 = Complex (Enterprise territory)


@dataclass
class ComplexityResult:
    """Result of complexity assessment."""

    level: str  # "trivial", "standard", "complex"
    score: int  # 0-100
    factors: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)

    @property
    def is_trivial(self) -> bool:
        return self.level == "trivial"

    @property
    def is_standard(self) -> bool:
        return self.level == "standard"

    @property
    def is_complex(self) -> bool:
        return self.level == "complex"


# Complexity signals - patterns that increase complexity score
COMPLEXITY_SIGNALS = {
    # Multi-file operations (+15 each)
    "multi_file": {
        "patterns": [
            r"\b(all|every|each|multiple)\s+(file|component|module|test)s?\b",
            r"\b(across|throughout)\s+(the\s+)?(codebase|project|repo)",
            r"\b(refactor|rename|update)\s+.{5,}\s+(everywhere|throughout)",
        ],
        "score": 15,
        "factor": "Multi-file operation",
    },
    # Architecture decisions (+20)
    "architecture": {
        "patterns": [
            r"\b(architect|design|structure)\s+(decision|choice|pattern)",
            r"\b(should\s+I|which)\s+(framework|library|pattern|approach)",
            r"\b(trade-?off|pros?\s+and\s+cons?)",
            r"\b(best\s+practice|recommend|optimal)",
        ],
        "score": 20,
        "factor": "Architecture decision needed",
    },
    # Migration/breaking changes (+25)
    "migration": {
        "patterns": [
            r"\b(migration|migrate|breaking\s+change)",
            r"\b(deprecat|backward\s+compat|legacy)",
            r"\b(upgrade|downgrade)\s+.{3,}\s+(version|major)",
        ],
        "score": 25,
        "factor": "Migration/breaking change risk",
    },
    # Security-sensitive (+20)
    "security": {
        "patterns": [
            r"\b(auth|security|credential|secret|token|password|api\s*key)",
            r"\b(encrypt|hash|sign|verify|validate)",
            r"\b(permission|access\s+control|rbac|acl)",
        ],
        "score": 20,
        "factor": "Security-sensitive operation",
    },
    # Data operations (+15)
    "data": {
        "patterns": [
            r"\b(database|db|schema|migration|table)",
            r"\b(data\s+loss|irreversible|destructive)",
            r"\b(backup|restore|rollback)",
        ],
        "score": 15,
        "factor": "Data operation risk",
    },
    # Integration complexity (+15)
    "integration": {
        "patterns": [
            r"\b(api|endpoint|webhook|integration)",
            r"\b(third-?party|external\s+service|dependency)",
            r"\b(async|concurrent|parallel|race\s+condition)",
        ],
        "score": 15,
        "factor": "Integration complexity",
    },
    # Performance-critical (+10)
    "performance": {
        "patterns": [
            r"\b(performance|optimi[sz]e|slow|fast|latency)",
            r"\b(memory|cpu|cache|buffer|pool)",
            r"\b(n\+1|query|index|bottleneck)",
        ],
        "score": 10,
        "factor": "Performance consideration",
    },
    # Testing complexity (+10)
    "testing": {
        "patterns": [
            r"\b(test\s+coverage|edge\s+case|corner\s+case)",
            r"\b(mock|stub|fixture|integration\s+test)",
            r"\b(flaky|intermittent|race)",
        ],
        "score": 10,
        "factor": "Testing complexity",
    },
    # Multi-step process (+10)
    "multi_step": {
        "patterns": [
            r"\b(step\s+\d|first|then|next|finally)",
            r"\b(workflow|process|pipeline|sequence)",
            r"\b(1\.|2\.|3\.)",
        ],
        "score": 10,
        "factor": "Multi-step process",
    },
    # Uncertainty signals (+15)
    "uncertainty": {
        "patterns": [
            r"\b(not\s+sure|uncertain|maybe|might|possibly)",
            r"\b(investigate|explore|research|understand)",
            r"\b(why|how\s+does|what\s+causes)",
        ],
        "score": 15,
        "factor": "Uncertainty/investigation needed",
    },
}

# Simplicity signals - patterns that decrease complexity
SIMPLICITY_SIGNALS = {
    # Single file (-10)
    "single_file": {
        "patterns": [
            r"\b(this|the|a)\s+(file|function|method|class)\b",
            r"\.py$|\.ts$|\.js$|\.json$",  # Specific file extension
        ],
        "score": -10,
        "factor": "Single file scope",
    },
    # Simple operations (-15)
    "simple_op": {
        "patterns": [
            r"\b(typo|spelling|rename|format|lint)",
            r"\b(add\s+comment|update\s+comment|docstring)",
            r"\b(bump\s+version|update\s+version)",
        ],
        "score": -15,
        "factor": "Simple operation",
    },
    # Clear specification (-10)
    "clear_spec": {
        "patterns": [
            r"\b(exactly|specifically|just|only|simply)",
            r"^(fix|add|update|remove|delete)\s+\w+$",
        ],
        "score": -10,
        "factor": "Clear specification",
    },
    # User provides code (-10)
    "user_code": {
        "patterns": [
            r"```\w*\n",  # Code block
            r"\bhere'?s?\s+(the|my)\s+code",
        ],
        "score": -10,
        "factor": "User provided code",
    },
}


def assess_complexity(
    prompt: str,
    files_mentioned: Optional[list[str]] = None,
    context: Optional[dict] = None,
) -> ComplexityResult:
    """
    Assess the complexity of a task based on prompt and context.

    Args:
        prompt: User's prompt text
        files_mentioned: List of file paths referenced
        context: Additional context (turn_count, recent_errors, etc.)

    Returns:
        ComplexityResult with level, score, and recommendations
    """
    score = 50  # Start at middle
    factors = []

    prompt_lower = prompt.lower()
    context = context or {}

    # Check complexity signals
    for signal_name, config in COMPLEXITY_SIGNALS.items():
        for pattern in config["patterns"]:
            if re.search(pattern, prompt_lower, re.IGNORECASE):
                score += config["score"]
                factors.append(f"+{config['score']}: {config['factor']}")
                break  # Only count each signal once

    # Check simplicity signals
    for signal_name, config in SIMPLICITY_SIGNALS.items():
        for pattern in config["patterns"]:
            if re.search(
                pattern,
                prompt_lower if signal_name != "user_code" else prompt,
                re.IGNORECASE,
            ):
                score += config["score"]  # Negative values reduce score
                factors.append(f"{config['score']}: {config['factor']}")
                break

    # Context adjustments
    if files_mentioned:
        file_count = len(files_mentioned)
        if file_count > 5:
            score += 15
            factors.append(f"+15: {file_count} files mentioned")
        elif file_count > 2:
            score += 8
            factors.append(f"+8: {file_count} files mentioned")

    # Prompt length adjustment
    if len(prompt) > 500:
        score += 10
        factors.append("+10: Long prompt (complex requirements)")
    elif len(prompt) < 50:
        score -= 10
        factors.append("-10: Short prompt (simple task)")

    # Question marks suggest uncertainty
    question_count = prompt.count("?")
    if question_count >= 3:
        score += 10
        factors.append(f"+10: Multiple questions ({question_count})")

    # Consecutive failures suggest complexity
    if context.get("consecutive_failures", 0) >= 2:
        score += 15
        factors.append("+15: Previous attempts failed")

    # Clamp score
    score = max(0, min(100, score))

    # Determine level
    if score <= TRIVIAL_THRESHOLD:
        level = "trivial"
    elif score <= STANDARD_THRESHOLD:
        level = "standard"
    else:
        level = "complex"

    # Generate recommendations
    recommendations = _generate_recommendations(level, factors)

    return ComplexityResult(
        level=level,
        score=score,
        factors=factors,
        recommendations=recommendations,
    )


def _generate_recommendations(level: str, factors: list[str]) -> list[str]:
    """Generate recommendations based on complexity level."""
    recs = []

    if level == "trivial":
        recs.append("Quick execution - minimal ceremony needed")
        recs.append("Single-pass solution likely sufficient")

    elif level == "standard":
        recs.append("Normal workflow - follow standard patterns")
        if any("Multi-file" in f for f in factors):
            recs.append("Grep for callers after signature changes")
        if any("Testing" in f for f in factors):
            recs.append("Run tests after changes")

    else:  # complex
        recs.append("Consider using Task agents for parallel exploration")
        if any("Architecture" in f for f in factors):
            recs.append("Use /council or mcp__pal__consensus for decision")
        if any("Uncertainty" in f for f in factors):
            recs.append("Use mcp__pal__thinkdeep for investigation")
        if any("Security" in f for f in factors):
            recs.append("Run /audit before committing")
        if any("Migration" in f for f in factors):
            recs.append("Create rollback plan before proceeding")
        recs.append("Break into steps if > 3 distinct operations")

    return recs


def get_hook_verbosity(complexity: ComplexityResult) -> str:
    """
    Determine hook verbosity level based on complexity.

    Returns:
        "minimal" - Skip most suggestions
        "normal" - Standard hook behavior
        "verbose" - Enhanced suggestions and gates
    """
    if complexity.is_trivial:
        return "minimal"
    elif complexity.is_complex:
        return "verbose"
    return "normal"


def should_skip_hook(
    hook_name: str,
    complexity: ComplexityResult,
    hook_priority: int = 50,
) -> bool:
    """
    Determine if a hook should be skipped based on complexity.

    Low-priority hooks (> 80) are skipped for trivial tasks.
    Only security hooks (< 30) run on trivial tasks.
    """
    if complexity.is_trivial:
        # Only run security/safety hooks (low priority numbers)
        return hook_priority > 45

    return False


def format_complexity_badge(complexity: ComplexityResult) -> str:
    """Format a compact badge showing complexity level."""
    emoji = {
        "trivial": "⚡",
        "standard": "📊",
        "complex": "🔬",
    }.get(complexity.level, "📊")

    return f"{emoji} {complexity.level.upper()} ({complexity.score})"


def get_complexity_context_injection(complexity: ComplexityResult) -> Optional[str]:
    """
    Generate context injection message for complex tasks.

    Only returns message for complex tasks to avoid noise.
    """
    if not complexity.is_complex:
        return None

    lines = [
        f"🔬 **COMPLEXITY DETECTED** (score: {complexity.score}/100)",
        "",
        "**Factors:**",
    ]

    # Show top 3 factors
    for factor in complexity.factors[:3]:
        lines.append(f"  • {factor}")

    if complexity.recommendations:
        lines.append("")
        lines.append("**Recommendations:**")
        for rec in complexity.recommendations[:3]:
            lines.append(f"  → {rec}")

    return "\n".join(lines)
