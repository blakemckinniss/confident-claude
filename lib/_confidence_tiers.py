#!/usr/bin/env python3
"""
Confidence Tiers - Zone-based capabilities and tool permissions.

Maps confidence levels to tiers (IGNORANCE -> EXPERT) with associated
privileges and restrictions.
"""

import re
from typing import TYPE_CHECKING

from epistemology import (
    TIER_CERTAINTY,
    TIER_HYPOTHESIS,
    TIER_IGNORANCE,
    TIER_TRUSTED,
    TIER_WORKING,
)

if TYPE_CHECKING:
    pass

from _confidence_constants import (
    THRESHOLD_MANDATORY_EXTERNAL,
    THRESHOLD_REQUIRE_RESEARCH,
    TIER_EMOJI,
)

# =============================================================================


def get_tier_info(confidence: int) -> tuple[str, str, str]:
    """
    Get confidence tier name, emoji, and description.

    Returns:
        Tuple[str, str, str]: (tier_name, emoji, description)
    """
    if TIER_IGNORANCE[0] <= confidence <= TIER_IGNORANCE[1]:
        return "IGNORANCE", TIER_EMOJI["IGNORANCE"], "Read/Research ONLY"
    elif TIER_HYPOTHESIS[0] <= confidence <= TIER_HYPOTHESIS[1]:
        return "HYPOTHESIS", TIER_EMOJI["HYPOTHESIS"], "Scratch only"
    elif TIER_WORKING[0] <= confidence <= TIER_WORKING[1]:
        return "WORKING", TIER_EMOJI["WORKING"], "Production with warnings (graduated)"
    elif TIER_CERTAINTY[0] <= confidence <= TIER_CERTAINTY[1]:
        return "CERTAINTY", TIER_EMOJI["CERTAINTY"], "Production with gates"
    elif TIER_TRUSTED[0] <= confidence <= TIER_TRUSTED[1]:
        return "TRUSTED", TIER_EMOJI["TRUSTED"], "Production with warnings"
    else:
        return "EXPERT", TIER_EMOJI["EXPERT"], "Maximum freedom"


def format_confidence_change(old: int, new: int, reason: str = "") -> str:
    """Format a confidence change for display."""
    delta = new - old
    sign = "+" if delta > 0 else ""
    old_tier, old_emoji, _ = get_tier_info(old)
    new_tier, new_emoji, _ = get_tier_info(new)

    msg = f"Confidence: {old_emoji}{old}% \u2192 {new_emoji}{new}% ({sign}{delta}"
    if reason:
        msg += f" {reason}"
    msg += ")"

    # Zone change alert
    if old_tier != new_tier:
        msg += f"\n\u26a0\ufe0f ZONE CHANGE: {old_tier} \u2192 {new_tier}"

    return msg


def should_require_research(confidence: int, context: dict) -> tuple[bool, str]:
    """
    Check if research should be required based on confidence.

    Returns:
        Tuple[bool, str]: (should_require, message)
    """
    if confidence >= THRESHOLD_REQUIRE_RESEARCH:
        return False, ""

    _, emoji, _ = get_tier_info(confidence)
    return True, (
        f"{emoji} **LOW CONFIDENCE: {confidence}%**\n"
        "Research is RECOMMENDED before proceeding.\n"
        "Use: /research, /docs, WebSearch, or mcp__pal__apilookup"
    )


def should_mandate_external(confidence: int) -> tuple[bool, str]:
    """
    Check if external LLM consultation is MANDATORY.

    Returns:
        Tuple[bool, str]: (is_mandatory, message)
    """
    if confidence >= THRESHOLD_MANDATORY_EXTERNAL:
        return False, ""

    _, emoji, _ = get_tier_info(confidence)
    return True, (
        f"{emoji} **CONFIDENCE CRITICALLY LOW: {confidence}% (IGNORANCE)**\n\n"
        "External consultation is **MANDATORY**. Pick one:\n"
        "1. `mcp__pal__thinkdeep` - Deep analysis via PAL MCP\n"
        "2. `/think` - Problem decomposition\n"
        "3. `/oracle` - Expert consultation\n"
        "4. `/research` - Verify with current docs\n\n"
        "Say **SUDO** to bypass (not recommended)."
    )


# Tool permission constants (module-level for O(1) lookup)
_ALWAYS_ALLOWED_TOOLS = frozenset(
    {
        "Read",
        "Grep",
        "Glob",
        "WebSearch",
        "WebFetch",
        "TodoRead",
        "AskUserQuestion",
    }
)
_WRITE_TOOLS = frozenset({"Edit", "Write", "Bash", "NotebookEdit"})
_FILE_WRITE_TOOLS = frozenset({"Edit", "Write"})
_READ_ONLY_AGENTS = frozenset(
    {
        "scout",
        "digest",
        "parallel",
        "explore",
        "chore",
        "plan",
        "claude-code-guide",
    }
)
_RISKY_BASH_PATTERNS = ("git push", "git commit", "rm -rf", "deploy", "kubectl")

# High-risk paths that shift required confidence upward (Blast Radius)
_HIGH_RISK_PATH_PATTERNS = (
    "/migrations/",
    "/auth/",
    "/security/",
    "/.env",
    "/credentials",
    "/secrets/",
    "/deploy/",
    "/production/",
    "/database/",
    "docker-compose.prod",
    "Dockerfile",
    ".github/workflows/",
)
_HIGH_RISK_CONFIDENCE_BOOST = 15  # Require 15% more confidence for high-risk paths


def _is_high_risk_path(file_path: str) -> bool:
    """Check if file path is high-risk (requires elevated confidence)."""
    if not file_path:
        return False
    return any(pattern in file_path for pattern in _HIGH_RISK_PATH_PATTERNS)


def _get_effective_confidence_requirement(file_path: str, base_requirement: int) -> int:
    """Get effective confidence requirement, boosted for high-risk paths."""
    if _is_high_risk_path(file_path):
        return min(95, base_requirement + _HIGH_RISK_CONFIDENCE_BOOST)
    return base_requirement


def _is_tool_always_allowed(tool_name: str, tool_input: dict) -> bool:
    """Check if tool is unconditionally allowed."""
    if tool_name in _ALWAYS_ALLOWED_TOOLS:
        return True
    if tool_name.startswith("mcp__pal__"):
        return True
    if tool_name == "Task":
        subagent = tool_input.get("subagent_type", "").lower()
        return subagent in _READ_ONLY_AGENTS
    return False


def _check_hypothesis_bash(
    command: str, confidence: int, emoji: str
) -> tuple[bool, str]:
    """Check bash command restrictions in HYPOTHESIS tier."""
    cmd_lower = command.lower()
    if any(p in cmd_lower for p in _RISKY_BASH_PATTERNS):
        recovery = get_confidence_recovery_options(confidence, target=51)
        return False, (
            f"{emoji} **BLOCKED: Risky Bash command**\n"
            f"Confidence ({confidence}% HYPOTHESIS) blocks production commands.\n\n"
            f"{recovery}"
        )
    return True, ""


def check_tool_permission(
    confidence: int, tool_name: str, tool_input: dict
) -> tuple[bool, str]:
    """
    Check if a tool is permitted at current confidence level.

    Returns:
        Tuple[bool, str]: (is_permitted, block_message)
    """
    if _is_tool_always_allowed(tool_name, tool_input):
        return True, ""

    _, emoji, _ = get_tier_info(confidence)
    file_path = tool_input.get("file_path", "")
    is_scratch = ".claude/tmp" in file_path or "/tmp/" in file_path

    # IGNORANCE (< 30): Block all write tools
    if confidence < 30 and tool_name in _WRITE_TOOLS:
        recovery = get_confidence_recovery_options(confidence, target=30)
        return False, (
            f"{emoji} **BLOCKED: {tool_name}**\n"
            f"Confidence too low ({confidence}% IGNORANCE).\n\n"
            f"{recovery}"
        )

    # HYPOTHESIS (30-50): Scratch only for file writes, restrict risky bash
    if 30 <= confidence < 51:
        if tool_name in _FILE_WRITE_TOOLS and not is_scratch:
            recovery = get_confidence_recovery_options(confidence, target=51)
            return False, (
                f"{emoji} **BLOCKED: {tool_name}** to production\n"
                f"Confidence ({confidence}% HYPOTHESIS) only allows scratch writes.\n"
                f"Write to `~/.claude/tmp/` for scratch, or earn confidence:\n\n"
                f"{recovery}"
            )
        if tool_name == "Bash":
            return _check_hypothesis_bash(
                tool_input.get("command", ""), confidence, emoji
            )

    # WORKING (51-70): Graduated production access with warnings
    if 51 <= confidence <= 70 and tool_name in _FILE_WRITE_TOOLS and not is_scratch:
        # Check blast radius - high-risk paths need higher confidence
        effective_requirement = _get_effective_confidence_requirement(file_path, 51)
        if confidence < effective_requirement:
            recovery = get_confidence_recovery_options(
                confidence, target=effective_requirement
            )
            return False, (
                f"{emoji} **BLOCKED: High-risk path requires {effective_requirement}%**\n"
                f"Path `{file_path}` is high-risk. Current: {confidence}%.\n\n"
                f"{recovery}"
            )

        # 51-60%: Warn strongly, recommend verification first
        if confidence <= 60:
            return True, (
                f"⚠️ **WORKING ZONE WARNING** ({confidence}%)\n"
                f"Production write allowed, but confidence is low.\n"
                f"**Strongly recommend**: Run tests/lint after this change.\n"
                f"Gap to CERTAINTY: {71 - confidence}%"
            )

        # 61-70%: Mild warning
        return True, (
            f"📝 WORKING: {confidence}% | Consider running tests after changes"
        )

    # CERTAINTY (71-85): Allow with gates - require audit/void for ops/hooks
    if 71 <= confidence <= 85 and tool_name in _FILE_WRITE_TOOLS and not is_scratch:
        # Blast radius check first
        effective_requirement = _get_effective_confidence_requirement(file_path, 71)
        if confidence < effective_requirement:
            recovery = get_confidence_recovery_options(
                confidence, target=effective_requirement
            )
            return False, (
                f"{emoji} **BLOCKED: High-risk path requires {effective_requirement}%**\n"
                f"Path `{file_path}` is high-risk. Current: {confidence}%.\n\n"
                f"{recovery}"
            )

        # Gate enforcement for critical framework paths
        if _is_gate_required_path(file_path):
            return True, (
                f"🚧 **CERTAINTY GATE** ({confidence}%)\n"
                f"Writing to framework path: `{_get_short_path(file_path)}`\n"
                f"**Required before commit:** `audit` AND `void` on this file.\n"
                f"Or reach TRUSTED (86%+) for gate-free writes."
            )

    # TRUSTED+ (86+): Allow (with blast radius check for high-risk)
    if tool_name in _FILE_WRITE_TOOLS and not is_scratch:
        effective_requirement = _get_effective_confidence_requirement(file_path, 71)
        if confidence < effective_requirement:
            recovery = get_confidence_recovery_options(
                confidence, target=effective_requirement
            )
            return False, (
                f"{emoji} **BLOCKED: High-risk path requires {effective_requirement}%**\n"
                f"Path `{file_path}` is high-risk. Current: {confidence}%.\n\n"
                f"{recovery}"
            )

    return True, ""


def _is_gate_required_path(file_path: str) -> bool:
    """Check if path requires gate verification (audit/void) in CERTAINTY zone."""
    gate_patterns = (
        ".claude/ops/",
        ".claude/hooks/",
        ".claude/lib/",
        "/ops/",
        "/hooks/",
    )
    return any(pattern in file_path for pattern in gate_patterns)


def _get_short_path(file_path: str) -> str:
    """Get shortened path for display."""
    if ".claude/" in file_path:
        return file_path.split(".claude/")[-1]
    return file_path.split("/")[-1]


def suggest_alternatives(confidence: int, task_description: str = "") -> str:
    """
    Suggest alternative approaches based on confidence level.

    Lower confidence = more alternatives suggested.
    """
    if confidence >= 50:
        return ""

    alternatives = []

    # At IGNORANCE, suggest 2-3 alternatives
    if confidence < 30:
        alternatives = [
            "\U0001f4a1 **Alternative Approaches** (confidence critically low):",
            "1. **Research first**: Use /research, /docs, or WebSearch",
            "2. **External consultation**: mcp__pal__thinkdeep or /oracle",
            "3. **Decompose problem**: /think to break down the task",
        ]
    # At HYPOTHESIS, suggest 1-2 alternatives
    elif confidence < 50:
        alternatives = [
            "\U0001f4a1 **Consider**:",
            "1. **Research**: Verify approach with /research or /docs",
            "2. **Consultation**: Quick check with /oracle if uncertain",
        ]

    return "\n".join(alternatives)


def assess_prompt_complexity(prompt: str) -> tuple[int, list[str]]:
    """
    Assess prompt complexity and return initial confidence adjustment.

    Returns:
        Tuple[int, list[str]]: (confidence_delta, reasons)
    """
    delta = 0
    reasons = []

    prompt_lower = prompt.lower()

    # Complexity indicators (reduce confidence)
    complexity_patterns = [
        (r"\b(complex|complicated|difficult|tricky)\b", -10, "complex task indicated"),
        (r"\b(refactor|rewrite|overhaul|redesign)\b", -8, "major refactoring"),
        (r"\b(async|concurrent|parallel|thread)\b", -5, "concurrency involved"),
        (r"\b(security|auth|crypto|encrypt)\b", -5, "security-sensitive"),
        (r"\b(database|sql|migration)\b", -5, "database operations"),
        (r"\b(deploy|production|live)\b", -8, "production impact"),
    ]

    for pattern, adj, reason in complexity_patterns:
        if re.search(pattern, prompt_lower):
            delta += adj
            reasons.append(reason)

    # Familiarity indicators (increase confidence)
    familiarity_patterns = [
        (r"\b(simple|easy|quick|small)\b", 5, "simple task"),
        (r"\b(fix typo|rename|update comment)\b", 10, "trivial change"),
    ]

    for pattern, adj, reason in familiarity_patterns:
        if re.search(pattern, prompt_lower):
            delta += adj
            reasons.append(reason)

    return delta, reasons


# =============================================================================
# RECOVERY OPTIONS
# =============================================================================


def get_confidence_recovery_options(current_confidence: int, target: int = 70) -> str:
    """Generate full ledger of ways to recover confidence."""
    deficit = target - current_confidence
    if deficit <= 0:
        return ""

    lines = [
        f"**Current**: {current_confidence}% | **Need**: {target}% | **Gap**: {deficit}",
        "",
        "**Ways to earn confidence:**",
    ]

    lines.append("```")
    lines.append("📈 +5  test_pass      pytest | jest | cargo test | npm test")
    lines.append("📈 +5  build_success  npm build | cargo build | tsc | make")
    lines.append("📈 +5  custom_script  ~/.claude/ops/* (audit, void, think, etc)")
    lines.append("📈 +3  lint_pass      ruff check | eslint | cargo clippy")
    lines.append("```")

    lines.append("")
    lines.append("**Due diligence (natural balance to decay):**")
    lines.append("```")
    lines.append("📈 +1  file_read      Read files to gather evidence")
    lines.append("📈 +2  research       WebSearch | WebFetch | crawl4ai")
    lines.append("📈 +3  rules_update   Edit CLAUDE.md or /rules/")
    lines.append("```")

    lines.append("")
    lines.append("**Context-building (+10 each):**")
    lines.append("```")
    lines.append("📈 +10 memory_consult Read ~/.claude/memory/ files")
    lines.append("📈 +10 bead_create    bd create | bd update (task tracking)")
    lines.append("📈 +10 git_explore    git log | git diff | git status | git show")
    lines.append("```")

    lines.append("")
    lines.append("**User interaction:**")
    lines.append("```")
    lines.append("📈 +20 ask_user       AskUserQuestion (epistemic humility)")
    lines.append("📈 +2  user_ok        Short positive feedback (ok, thanks)")
    lines.append("📈 +15 trust_regained CONFIDENCE_BOOST_APPROVED")
    lines.append("```")

    lines.append("")
    lines.append("**Bypass**: Say `SUDO` (logged) | `FP: <reducer>` to dispute")

    return "\n".join(lines)


# =============================================================================
# RATE LIMITING HELPERS
