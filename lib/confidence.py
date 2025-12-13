#!/usr/bin/env python3
"""
Dynamic Confidence Regulation System

Core engine for mechanical confidence tracking with deterministic reducers
that bypass self-assessment bias.

Design Principles:
1. Reducers fire WITHOUT judgment - mechanical signals only
2. Escalation is MANDATORY at low confidence
3. Trust regain requires explicit user approval for large boosts
4. Visibility: user always sees confidence state and zone changes
"""

import re
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

# Import tier system from epistemology (avoid duplication)
from epistemology import (
    TIER_CERTAINTY,
    TIER_HYPOTHESIS,
    TIER_IGNORANCE,
    TIER_PRIVILEGES,
    TIER_TRUSTED,
    TIER_WORKING,
)

if TYPE_CHECKING:
    from session_state import SessionState

# =============================================================================
# CONSTANTS
# =============================================================================

# Confidence thresholds
THRESHOLD_MANDATORY_EXTERNAL = 30  # Below this: external LLM MANDATORY
THRESHOLD_REQUIRE_RESEARCH = 50  # Below this: research REQUIRED
THRESHOLD_PRODUCTION_ACCESS = 51  # Below this: no production writes

# Tier emoji mapping
TIER_EMOJI = {
    "IGNORANCE": "\U0001f534",  # Red circle
    "HYPOTHESIS": "\U0001f7e0",  # Orange circle
    "WORKING": "\U0001f7e1",  # Yellow circle
    "CERTAINTY": "\U0001f7e2",  # Green circle
    "TRUSTED": "\U0001f49a",  # Green heart
    "EXPERT": "\U0001f48e",  # Gem
}

# Default starting confidence for new sessions
DEFAULT_CONFIDENCE = 70  # Start at WORKING level - must prove up or down

# =============================================================================
# REDUCER REGISTRY (MECHANICAL - NO JUDGMENT)
# =============================================================================


@dataclass
class ConfidenceReducer:
    """A deterministic confidence reducer that fires on specific signals."""

    name: str
    delta: int  # Negative value
    description: str
    cooldown_turns: int = 3  # Minimum turns between triggers

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        """Check if this reducer should fire. Override in subclasses."""
        # Cooldown check
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        return False


@dataclass
class ToolFailureReducer(ConfidenceReducer):
    """Triggers on Bash/command failures."""

    name: str = "tool_failure"
    delta: int = -5
    description: str = "Tool execution failed (exit code != 0)"
    cooldown_turns: int = 1

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        # Check for recent command failures
        return len(state.commands_failed) > 0 and (
            state.commands_failed[-1].get("timestamp", 0) > time.time() - 60
        )


@dataclass
class CascadeBlockReducer(ConfidenceReducer):
    """Triggers when same hook blocks 3+ times in 5 turns."""

    name: str = "cascade_block"
    delta: int = -15
    description: str = "Same hook blocked 3+ times recently"
    cooldown_turns: int = 5

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        # Check consecutive_blocks from session_state
        for hook_name, entry in state.consecutive_blocks.items():
            if entry.get("count", 0) >= 3:
                return True
        return False


@dataclass
class SunkCostReducer(ConfidenceReducer):
    """Triggers on 3+ consecutive failures."""

    name: str = "sunk_cost"
    delta: int = -20
    description: str = "3+ consecutive failures on same approach"
    cooldown_turns: int = 5

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        return state.consecutive_failures >= 3


@dataclass
class UserCorrectionReducer(ConfidenceReducer):
    """Triggers when user corrects Claude."""

    name: str = "user_correction"
    delta: int = -10
    description: str = "User corrected or contradicted response"
    cooldown_turns: int = 3
    patterns: list = field(
        default_factory=lambda: [
            r"\bthat'?s?\s+(?:not\s+)?(?:wrong|incorrect)\b",
            r"\bno,?\s+(?:that|it)\b",
            r"\bactually\s+(?:it|that|you)\b",
            r"\bfix\s+that\b",
            r"\byou\s+(?:made|have)\s+(?:a\s+)?(?:mistake|error)\b",
            r"\bwrong\s+(?:file|path|function|approach)\b",
        ]
    )

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        prompt = context.get("prompt", "").lower()
        for pattern in self.patterns:
            if re.search(pattern, prompt, re.IGNORECASE):
                return True
        return False


@dataclass
class GoalDriftReducer(ConfidenceReducer):
    """Triggers when activity diverges from original goal."""

    name: str = "goal_drift"
    delta: int = -8
    description: str = "Activity diverged from original goal"
    cooldown_turns: int = 8

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        # Use existing goal drift detection from session_state
        if not state.original_goal or not state.goal_keywords:
            return False
        if state.turn_count - state.goal_set_turn < 5:
            return False
        # Check keyword overlap
        current = context.get("current_activity", "").lower()
        if not current:
            return False
        matches = sum(1 for kw in state.goal_keywords if kw in current)
        overlap = matches / len(state.goal_keywords) if state.goal_keywords else 0
        return overlap < 0.2


@dataclass
class EditOscillationReducer(ConfidenceReducer):
    """Triggers when edits revert previous changes (actual oscillation)."""

    name: str = "edit_oscillation"
    delta: int = -12
    description: str = "Edits reverting previous changes (back-forth pattern)"
    cooldown_turns: int = 5

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False

        # Check for actual oscillation pattern in edit_history
        # Oscillation = latest edit's NEW content matches a PREVIOUS state
        # (i.e., reverting back to something we had before)
        edit_history = getattr(state, "edit_history", {})
        for filepath, history in edit_history.items():
            if len(history) < 3:  # Need at least 3 edits to detect oscillation
                continue
            # Collect ALL states from edits before the previous one
            # (skip immediately previous edit - that's normal iteration)
            # Track both old and new hashes to catch: v0→v1→v0→v1 patterns
            previous_states: set[str] = set()
            for h in history[:-2]:
                if h[0]:
                    previous_states.add(h[0])
                if h[1]:
                    previous_states.add(h[1])
            # Check if latest edit's new_hash matches any older state
            latest = history[-1]
            latest_new_hash = latest[1]
            if latest_new_hash and latest_new_hash in previous_states:
                return True  # Detected revert to previous state

        return False


@dataclass
class ContradictionReducer(ConfidenceReducer):
    """Triggers on contradictory claims within session."""

    name: str = "contradiction"
    delta: int = -10
    description: str = "Made contradictory claims"
    cooldown_turns: int = 5
    # This needs to be detected externally and passed in context
    # as "contradiction_detected": True

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        return context.get("contradiction_detected", False)


# Registry of all reducers
REDUCERS: list[ConfidenceReducer] = [
    ToolFailureReducer(),
    CascadeBlockReducer(),
    SunkCostReducer(),
    UserCorrectionReducer(),
    GoalDriftReducer(),
    EditOscillationReducer(),
    ContradictionReducer(),
]


# =============================================================================
# INCREASER REGISTRY
# =============================================================================


@dataclass
class ConfidenceIncreaser:
    """A confidence increaser that fires on success signals."""

    name: str
    delta: int  # Positive value
    description: str
    requires_approval: bool = False
    cooldown_turns: int = 1

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        """Check if this increaser should fire. Override in subclasses."""
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        return False


@dataclass
class TestPassIncreaser(ConfidenceIncreaser):
    """Triggers when tests pass."""

    name: str = "test_pass"
    delta: int = 5
    description: str = "Tests passed successfully"
    requires_approval: bool = False
    cooldown_turns: int = 1

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        # Check recent commands for test passes
        for cmd in state.commands_succeeded[-5:]:
            cmd_str = cmd.get("command", "").lower()
            if any(t in cmd_str for t in ["pytest", "jest", "cargo test", "npm test"]):
                return True
        return False


@dataclass
class BuildSuccessIncreaser(ConfidenceIncreaser):
    """Triggers when builds succeed."""

    name: str = "build_success"
    delta: int = 5
    description: str = "Build completed successfully"
    requires_approval: bool = False
    cooldown_turns: int = 1

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        for cmd in state.commands_succeeded[-5:]:
            cmd_str = cmd.get("command", "").lower()
            if any(
                t in cmd_str
                for t in ["npm build", "cargo build", "make", "tsc", "go build"]
            ):
                return True
        return False


@dataclass
class UserOkIncreaser(ConfidenceIncreaser):
    """Triggers on positive user feedback."""

    name: str = "user_ok"
    delta: int = 5
    description: str = "User confirmed correctness"
    requires_approval: bool = False
    cooldown_turns: int = 2
    patterns: list = field(
        default_factory=lambda: [
            r"\b(?:looks?\s+)?good\b",
            r"\bok(?:ay)?\b",
            r"\bcorrect\b",
            r"\bperfect\b",
            r"\bnice\b",
            r"\bthanks?\b",
            r"\byes\b",
        ]
    )

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        prompt = context.get("prompt", "").lower().strip()
        # Short positive responses only (avoid false positives in long prompts)
        if len(prompt) > 50:
            return False
        for pattern in self.patterns:
            if re.search(pattern, prompt, re.IGNORECASE):
                return True
        return False


@dataclass
class TrustRegainedIncreaser(ConfidenceIncreaser):
    """Triggers on explicit trust restoration request (requires approval)."""

    name: str = "trust_regained"
    delta: int = 15
    description: str = "User explicitly restored trust"
    requires_approval: bool = True
    cooldown_turns: int = 5
    trigger_patterns: list = field(
        default_factory=lambda: [
            r"\btrust\s+regained\b",
            r"\bconfidence\s+(?:restored|boost(?:ed)?)\b",
            r"\bCONFIDENCE_BOOST_APPROVED\b",
        ]
    )

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        prompt = context.get("prompt", "")
        for pattern in self.trigger_patterns:
            if re.search(pattern, prompt, re.IGNORECASE):
                return True
        return False


# Registry of all increasers
INCREASERS: list[ConfidenceIncreaser] = [
    TestPassIncreaser(),
    BuildSuccessIncreaser(),
    UserOkIncreaser(),
    TrustRegainedIncreaser(),
]


# =============================================================================
# CORE FUNCTIONS
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
        return "WORKING", TIER_EMOJI["WORKING"], "Scratch + git read"
    elif TIER_CERTAINTY[0] <= confidence <= TIER_CERTAINTY[1]:
        return "CERTAINTY", TIER_EMOJI["CERTAINTY"], "Production with gates"
    elif TIER_TRUSTED[0] <= confidence <= TIER_TRUSTED[1]:
        return "TRUSTED", TIER_EMOJI["TRUSTED"], "Production with warnings"
    else:
        return "EXPERT", TIER_EMOJI["EXPERT"], "Maximum freedom"


def format_confidence_status(confidence: int) -> str:
    """Format confidence for status line display."""
    tier_name, emoji, _ = get_tier_info(confidence)
    return f"{emoji}{confidence}% {tier_name}"


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


def check_tool_permission(
    confidence: int, tool_name: str, tool_input: dict
) -> tuple[bool, str]:
    """
    Check if a tool is permitted at current confidence level.

    Returns:
        Tuple[bool, str]: (is_permitted, block_message)
    """
    _, emoji, _ = get_tier_info(confidence)

    # Always-allowed tools (diagnostic, read-only)
    always_allowed = {
        "Read",
        "Grep",
        "Glob",
        "WebSearch",
        "WebFetch",
        "TodoRead",
        "AskUserQuestion",
    }
    if tool_name in always_allowed:
        return True, ""

    # External LLM tools always allowed (they're the escalation path)
    external_llm_tools = {
        "mcp__pal__thinkdeep",
        "mcp__pal__debug",
        "mcp__pal__codereview",
    }
    if tool_name.startswith("mcp__pal__") or tool_name in external_llm_tools:
        return True, ""

    # Task tool - allow read-only agent types
    if tool_name == "Task":
        read_only_agents = {
            "scout",
            "digest",
            "parallel",
            "explore",
            "chore",
            "plan",
            "claude-code-guide",
        }
        subagent_type = tool_input.get("subagent_type", "").lower()
        if subagent_type in read_only_agents:
            return True, ""

    # Check confidence-based restrictions
    file_path = tool_input.get("file_path", "")
    is_scratch = ".claude/tmp" in file_path or "/tmp/" in file_path

    # IGNORANCE (< 30): Only read-only tools
    if confidence < 30:
        if tool_name in {"Edit", "Write", "Bash", "NotebookEdit"}:
            return False, (
                f"{emoji} **BLOCKED: {tool_name}**\n"
                f"Confidence too low ({confidence}% IGNORANCE).\n"
                "External consultation REQUIRED first.\n"
                "Use: mcp__pal__thinkdeep, /think, or /oracle"
            )

    # HYPOTHESIS (30-50): Scratch only
    elif confidence < 51:
        if tool_name in {"Edit", "Write"} and not is_scratch:
            return False, (
                f"{emoji} **BLOCKED: {tool_name}** to production\n"
                f"Confidence ({confidence}% HYPOTHESIS) only allows scratch writes.\n"
                "Options:\n"
                "1. Write to ~/.claude/tmp/ instead\n"
                "2. Research to increase confidence\n"
                "3. Say SUDO to bypass"
            )
        if tool_name == "Bash":
            # Check for state-modifying commands
            command = tool_input.get("command", "").lower()
            risky_patterns = [
                "git push",
                "git commit",
                "rm -rf",
                "deploy",
                "kubectl apply",
            ]
            if any(p in command for p in risky_patterns):
                return False, (
                    f"{emoji} **BLOCKED: Risky Bash command**\n"
                    f"Confidence ({confidence}% HYPOTHESIS) blocks production commands.\n"
                    "Research first or say SUDO to bypass."
                )

    return True, ""


def get_escalation_tools() -> list[dict]:
    """Get ordered list of escalation tools with fallbacks."""
    return [
        {
            "name": "mcp__pal__thinkdeep",
            "type": "mcp",
            "description": "Deep multi-step analysis via PAL MCP",
            "priority": 1,
        },
        {
            "name": "mcp__pal__debug",
            "type": "mcp",
            "description": "Debugging analysis via PAL MCP",
            "priority": 2,
        },
        {
            "name": "groq",
            "type": "ops",
            "command": "~/.claude/ops/groq.py --model kimi-k2",
            "description": "Fast inference via Groq (fallback)",
            "priority": 3,
        },
        {
            "name": "oracle",
            "type": "ops",
            "command": "~/.claude/ops/oracle.py --persona judge",
            "description": "Expert consultation via OpenRouter (fallback)",
            "priority": 4,
        },
    ]


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
# REDUCER/INCREASER APPLICATION
# =============================================================================


def apply_reducers(state: "SessionState", context: dict) -> list[tuple[str, int, str]]:
    """
    Apply all applicable reducers and return list of triggered ones.

    Returns:
        List of (reducer_name, delta, description) tuples
    """
    triggered = []

    # Get last trigger turns from state (stored in nudge_history)
    for reducer in REDUCERS:
        key = f"confidence_reducer_{reducer.name}"
        last_trigger = state.nudge_history.get(key, {}).get("last_turn", -999)

        if reducer.should_trigger(context, state, last_trigger):
            triggered.append((reducer.name, reducer.delta, reducer.description))
            # Record trigger
            if key not in state.nudge_history:
                state.nudge_history[key] = {}
            state.nudge_history[key]["last_turn"] = state.turn_count

    return triggered


def apply_increasers(
    state: "SessionState", context: dict
) -> list[tuple[str, int, str, bool]]:
    """
    Apply all applicable increasers and return list of triggered ones.

    Returns:
        List of (increaser_name, delta, description, requires_approval) tuples
    """
    triggered = []

    for increaser in INCREASERS:
        key = f"confidence_increaser_{increaser.name}"
        last_trigger = state.nudge_history.get(key, {}).get("last_turn", -999)

        if increaser.should_trigger(context, state, last_trigger):
            triggered.append(
                (
                    increaser.name,
                    increaser.delta,
                    increaser.description,
                    increaser.requires_approval,
                )
            )
            # Record trigger (only for non-approval-required)
            if not increaser.requires_approval:
                if key not in state.nudge_history:
                    state.nudge_history[key] = {}
                state.nudge_history[key]["last_turn"] = state.turn_count

    return triggered


# =============================================================================
# FALSE POSITIVE DISPUTE SYSTEM
# =============================================================================

# Patterns that indicate user is disputing a confidence reduction
# Note: patterns are matched against lowercased prompt
DISPUTE_PATTERNS = [
    r"\bfalse\s+positive\b",
    r"\bfp\s*:\s*(\w+)\b",  # fp: reducer_name (lowercase)
    r"\bdispute\s+(\w+)\b",
    r"\bthat\s+(?:was|is)\s+wrong\b",
    r"\bshouldn'?t\s+have\s+(?:reduced|dropped)\b",
    r"\bwrongly\s+(?:reduced|penalized)\b",
    r"\blegitimate\s+(?:edit|change|work)\b",
    r"\bnot\s+(?:oscillating|spinning|stuck)\b",
]


def get_adaptive_cooldown(state: "SessionState", reducer_name: str) -> int:
    """Get adaptive cooldown for a reducer based on false positive history.

    High false positive rates increase cooldowns to reduce future triggers.
    """
    base_cooldown = next(
        (r.cooldown_turns for r in REDUCERS if r.name == reducer_name), 3
    )

    # Get FP count from state
    fp_key = f"reducer_fp_{reducer_name}"
    fp_count = state.nudge_history.get(fp_key, {}).get("count", 0)

    # Scale cooldown: each FP adds 50% more cooldown, max 3x
    if fp_count == 0:
        return base_cooldown

    multiplier = min(3.0, 1.0 + (fp_count * 0.5))
    return int(base_cooldown * multiplier)


def record_false_positive(state: "SessionState", reducer_name: str, reason: str = ""):
    """Record a false positive for adaptive learning.

    This increases future cooldowns for this reducer.
    """
    fp_key = f"reducer_fp_{reducer_name}"
    if fp_key not in state.nudge_history:
        state.nudge_history[fp_key] = {"count": 0, "reasons": []}

    state.nudge_history[fp_key]["count"] = (
        state.nudge_history[fp_key].get("count", 0) + 1
    )

    # Keep last 5 reasons for debugging
    if reason:
        reasons = state.nudge_history[fp_key].get("reasons", [])
        reasons.append(reason[:100])
        state.nudge_history[fp_key]["reasons"] = reasons[-5:]

    state.nudge_history[fp_key]["last_turn"] = state.turn_count


def dispute_reducer(
    state: "SessionState", reducer_name: str, reason: str = ""
) -> tuple[int, str]:
    """User disputes a confidence reduction as false positive.

    Returns:
        Tuple of (confidence_restored, message)
    """
    # Find the reducer
    reducer = next((r for r in REDUCERS if r.name == reducer_name), None)
    if not reducer:
        # Try fuzzy match
        for r in REDUCERS:
            if reducer_name.lower() in r.name.lower():
                reducer = r
                break

    if not reducer:
        return (
            0,
            f"Unknown reducer: {reducer_name}. Valid: {[r.name for r in REDUCERS]}",
        )

    # Record the false positive
    record_false_positive(state, reducer.name, reason)

    # Restore confidence
    restore_amount = abs(reducer.delta)
    fp_count = state.nudge_history.get(f"reducer_fp_{reducer.name}", {}).get("count", 1)
    new_cooldown = get_adaptive_cooldown(state, reducer.name)

    return restore_amount, (
        f"✅ **False Positive Recorded**: {reducer.name}\n"
        f"  • Confidence restored: +{restore_amount}\n"
        f"  • Total FPs for this reducer: {fp_count}\n"
        f"  • New adaptive cooldown: {new_cooldown} turns\n"
    )


def detect_dispute_in_prompt(prompt: str) -> tuple[bool, str, str]:
    """Detect if user is disputing a confidence reduction.

    Returns:
        Tuple of (is_dispute, reducer_name, reason)
    """
    prompt_lower = prompt.lower()

    for pattern in DISPUTE_PATTERNS:
        match = re.search(pattern, prompt_lower)
        if match:
            # Try to extract reducer name from match groups
            reducer_name = ""
            if match.groups():
                reducer_name = match.group(1)

            # If no reducer name in pattern, try to find it in prompt
            if not reducer_name:
                for reducer in REDUCERS:
                    if reducer.name in prompt_lower:
                        reducer_name = reducer.name
                        break

            # Extract reason (rest of prompt after pattern)
            reason = prompt[match.end() :].strip()[:100]

            return True, reducer_name, reason

    return False, "", ""


def get_recent_reductions(state: "SessionState", turns: int = 3) -> list[str]:
    """Get reducers that fired recently (for dispute context)."""
    recent = []
    current_turn = state.turn_count

    for reducer in REDUCERS:
        key = f"confidence_reducer_{reducer.name}"
        last_turn = state.nudge_history.get(key, {}).get("last_turn", -999)
        if current_turn - last_turn <= turns:
            recent.append(reducer.name)

    return recent


def format_dispute_instructions(reducer_names: list[str]) -> str:
    """Format instructions for disputing a reduction."""
    if not reducer_names:
        return ""

    reducers_str = ", ".join(reducer_names)
    return (
        f"\n💡 **False positive?** Options:\n"
        f"   • Claude: Run `~/.claude/ops/fp.py <reducer> [reason]`\n"
        f"   • User: Say `FP: <reducer>` or `dispute <reducer>`\n"
        f"   Recent reducers: {reducers_str}"
    )


def generate_approval_prompt(
    current_confidence: int, requested_delta: int, reasons: list[str]
) -> str:
    """Generate approval prompt for large confidence boosts."""
    new_confidence = min(100, current_confidence + requested_delta)
    old_tier, old_emoji, _ = get_tier_info(current_confidence)
    new_tier, new_emoji, _ = get_tier_info(new_confidence)

    # List what will be unlocked
    old_privs = TIER_PRIVILEGES.get(old_tier, {})
    new_privs = TIER_PRIVILEGES.get(new_tier, {})
    unlocks = []
    for priv, allowed in new_privs.items():
        if allowed and not old_privs.get(priv, False):
            unlocks.append(f"  \u2705 {priv.replace('_', ' ').title()}")

    unlock_str = "\n".join(unlocks) if unlocks else "  (no new permissions)"

    return (
        f"\U0001f50d **Confidence Boost Request**\n\n"
        f"Current: {old_emoji}{current_confidence}% {old_tier}\n"
        f"Proposed: {new_emoji}{new_confidence}% {new_tier} (+{requested_delta})\n\n"
        f"This will unlock:\n{unlock_str}\n\n"
        f"Reply: **CONFIDENCE_BOOST_APPROVED** to confirm"
    )
