"""
Confidence Decay PostToolUse hook.

Dynamic confidence system with survival mechanics and fatigue.
Priority 11 - runs after state_updater, applies decay/boosts.

Entity Model v4.9: Fatigue system - decay accelerates with session length.
"""

import _lib_path  # noqa: F401
import json
from pathlib import Path

from _config import get_magic_number
from _hook_registry import register_hook
from _hook_result import HookResult
from session_state import SessionState, set_confidence
from confidence import apply_rate_limit


# =============================================================================
# MULTIPLIER FUNCTIONS (confidence-based and context-based scaling)
# =============================================================================


def _get_penalty_multiplier(confidence: int) -> float:
    """Scale penalties based on confidence level.

    Higher confidence = harder to maintain (bigger penalties).
    Lower confidence = already struggling (reduced penalties).

    This prevents coasting at high confidence - mistakes cost more
    when you're confident, creating pressure to stay careful.
    """
    if confidence >= 95:
        return 2.0  # Double penalties at peak confidence
    elif confidence >= 85:
        return 1.5  # 50% extra penalty in trusted zone
    elif confidence >= 70:
        return 1.0  # Normal penalties in working zone
    elif confidence >= 50:
        return 0.75  # Reduced penalties when struggling
    else:
        return 0.5  # Half penalties when in crisis


def _get_boost_multiplier(confidence: int) -> float:
    """Scale boosts based on confidence level - INVERSE of penalty scaling.

    Lower confidence = BIGGER boosts (survival mode, desperate for trust).
    Higher confidence = SMALLER boosts (already trusted, hard to justify more).

    Creates a self-correcting system:
    - When struggling: every bit of research/consultation is precious
    - When comfortable: coasting won't increase trust
    """
    if confidence < 30:
        return 3.0  # Desperate mode - every insight is gold
    elif confidence < 50:
        return 2.0  # Struggling - info gathering is rewarded heavily
    elif confidence < 70:
        return 1.5  # Working hard - research still pays off
    elif confidence < 85:
        return 1.0  # Normal - standard boost values
    else:
        return 0.5  # Comfortable - can't easily boost higher


# Context window scaling
_DEFAULT_CONTEXT_WINDOW = get_magic_number("default_context_window", 200000)


def _get_context_percentage(transcript_path: str) -> float:
    """Calculate context window usage percentage from transcript.

    Reads the most recent assistant message's usage data to determine
    how much of the context window has been consumed.

    Returns 0.0 if unable to determine (safe default).
    """
    if not transcript_path:
        return 0.0

    try:
        transcript = Path(transcript_path)
        if not transcript.exists():
            return 0.0

        with open(transcript, "r") as f:
            lines = f.readlines()

        # Find most recent assistant message with usage data
        for line in reversed(lines):
            try:
                data = json.loads(line.strip())
                msg = data.get("message", {})
                if msg.get("role") != "assistant":
                    continue
                # Skip synthetic messages
                model = str(msg.get("model", "")).lower()
                if "synthetic" in model:
                    continue

                usage = msg.get("usage")
                if usage:
                    used = (
                        usage.get("input_tokens", 0)
                        + usage.get("output_tokens", 0)
                        + usage.get("cache_read_input_tokens", 0)
                        + usage.get("cache_creation_input_tokens", 0)
                    )
                    if used > 0:
                        return (used / _DEFAULT_CONTEXT_WINDOW) * 100
            except (json.JSONDecodeError, KeyError):
                continue

        return 0.0
    except Exception:
        return 0.0


def _get_context_multiplier(context_pct: float) -> tuple[float, float]:
    """Scale adjustments based on context usage.

    Returns (penalty_mult, boost_mult) tuple:
    - penalty_mult: Multiplier for penalties (higher context = bigger penalties)
    - boost_mult: Multiplier for boosts (higher context = smaller boosts)

    At high context usage, mistakes are more costly because:
    - Less room to recover with fresh context
    - Accumulated complexity increases error probability
    - User may be frustrated with long unproductive sessions
    """
    if context_pct >= 80:
        # Critical context usage - maximum pressure
        return (2.0, 0.5)  # Double penalties, halve boosts
    elif context_pct >= 60:
        # High context usage - significant pressure
        return (1.5, 0.75)  # 50% more penalties, 25% less boosts
    elif context_pct >= 40:
        # Medium context usage - mild pressure
        return (1.25, 0.9)  # 25% more penalties, 10% less boosts
    else:
        # Low context usage - normal operation
        return (1.0, 1.0)  # No modification


# =============================================================================
# RESEARCH LIBRARY TRACKING
# =============================================================================


def _track_researched_libraries(tool_name: str, tool_input: dict, state: SessionState):
    """Extract library names from research queries and mark as researched.

    This unlocks the research_gate for these libraries in pre_tool_use.
    """
    from session_state import RESEARCH_REQUIRED_LIBS, track_library_researched

    # Get the text to search for library mentions
    text = ""
    if tool_name == "WebSearch":
        text = tool_input.get("query", "")
    elif tool_name == "WebFetch":
        text = tool_input.get("url", "") + " " + tool_input.get("prompt", "")
    elif tool_name == "mcp__crawl4ai__crawl":
        text = tool_input.get("url", "")
    elif tool_name == "mcp__crawl4ai__search":
        text = tool_input.get("query", "")

    if not text:
        return

    text_lower = text.lower()

    # Check for each required library in the search/fetch
    for lib in RESEARCH_REQUIRED_LIBS:
        if lib.lower() in text_lower:
            track_library_researched(state, lib)


# =============================================================================
# DECAY BOOST/PENALTY CALCULATIONS
# =============================================================================

# Decay boost lookup tables
_PAL_HIGH_BOOST = frozenset(
    ("thinkdeep", "debug", "codereview", "consensus", "precommit")
)
_PAL_LOW_BOOST = frozenset(("chat", "challenge", "apilookup"))
_DECAY_BOOST_FIXED = {
    "AskUserQuestion": (2, "user-clarification"),
    "Task": (1.5, "agent-delegation"),
    "WebSearch": (0.5, "web-research"),
    "WebFetch": (0.5, "web-research"),
}


def _calculate_decay_boost(
    tool_name: str, tool_input: dict, state: SessionState
) -> tuple[float, str]:
    """Calculate recovery action boosts for confidence decay."""
    # PAL external consultation
    if tool_name.startswith("mcp__pal__"):
        pal_tool = tool_name.replace("mcp__pal__", "")
        if pal_tool in _PAL_HIGH_BOOST:
            return 2, f"pal-{pal_tool}"
        if pal_tool in _PAL_LOW_BOOST:
            return 1, f"pal-{pal_tool}"
        return 0, ""

    # Fixed boosts
    if tool_name in _DECAY_BOOST_FIXED:
        return _DECAY_BOOST_FIXED[tool_name]

    # Read - diminishing returns
    if tool_name == "Read":
        read_count = len([f for f in state.files_read if f])
        boost = 0.5 if read_count <= 3 else (0.25 if read_count <= 6 else 0.1)
        return boost, f"file-read({read_count})"

    # Memory access or web crawl
    if tool_name.startswith("mcp__"):
        if "mem" in tool_name.lower():
            return 0.5, "memory-access"
        if tool_name.startswith("mcp__crawl4ai__"):
            return 0.5, "web-crawl"

    return 0, ""


def _calculate_decay_penalty(
    tool_name: str, tool_input: dict, state: SessionState
) -> tuple[float, str]:
    """Calculate penalties for risky actions.

    Returns (penalty_value, penalty_reason).
    """
    if tool_name in ("Edit", "Write"):
        penalty = 0
        reason_parts = []
        file_path = tool_input.get("file_path", "")

        # Base edit penalty with cooldown (max 1 per 3 turns)
        edit_risk_key = "_edit_risk_last_turn"
        last_edit_risk = getattr(state, edit_risk_key, 0)
        if state.turn_count - last_edit_risk >= 3:
            penalty = 1
            reason_parts.append("edit-risk")
            setattr(state, edit_risk_key, state.turn_count)

        # Edit without reading first = extra penalty
        if file_path and file_path not in state.files_read:
            penalty += 2
            reason_parts = ["edit-without-read"]

        # Check for stubs in new code
        new_code = tool_input.get("new_string", "") or tool_input.get("content", "")
        if new_code:
            stub_patterns = [
                "pass  # TODO",
                "raise NotImplementedError",
                "# FIXME",
                "...  # stub",
            ]
            if any(p in new_code for p in stub_patterns):
                penalty += 1
                reason_parts.append("stub")

        return penalty, "+".join(reason_parts) if reason_parts else ""

    # Bash commands are risky - cooldown prevents constant drain
    if tool_name == "Bash":
        bash_risk_key = "_bash_risk_last_turn"
        last_bash_risk = getattr(state, bash_risk_key, 0)
        if state.turn_count - last_bash_risk >= 3:
            setattr(state, bash_risk_key, state.turn_count)
            return 1, "bash-risk"

    return 0, ""


# =============================================================================
# MAIN DECAY HOOK
# =============================================================================


@register_hook("confidence_decay", None, priority=11)
def check_confidence_decay(
    data: dict, state: SessionState, runner_state: dict
) -> HookResult:
    """Dynamic confidence system with survival mechanics.

    See _calculate_decay_boost() and _calculate_decay_penalty() for details.
    Shows 🆘 indicator when survival boost is active.

    Entity Model v4.9: Fatigue system - decay accelerates with session length.
    The entity "gets tired" in long sessions, creating natural session boundaries.
    """
    from _fatigue import get_fatigue_multiplier

    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})

    # Base decay per tool call (moderate: actions have cost but not punishing)
    # v4.9: Apply fatigue multiplier - entity gets tired in long sessions
    fatigue_mult = get_fatigue_multiplier(state.turn_count)
    base_decay = 0.4 * fatigue_mult
    if state.confidence >= 85:
        base_decay += 0.3 * fatigue_mult  # High confidence tax (also fatigued)

    state._decay_accumulator += base_decay

    # Calculate boost and penalty via helpers
    boost, boost_reason = _calculate_decay_boost(tool_name, tool_input, state)
    penalty, penalty_reason = _calculate_decay_penalty(tool_name, tool_input, state)

    # Calculate net adjustment (decay + penalty - boosts)
    # Only apply when accumulator reaches whole number
    accumulated_decay = int(state._decay_accumulator)
    state._decay_accumulator -= accumulated_decay  # Keep fractional part

    # Get scaling multipliers
    # 1. Confidence-based penalty scaling (higher confidence = harsher penalties)
    conf_penalty_mult = _get_penalty_multiplier(state.confidence)
    # 2. Confidence-based boost scaling (lower confidence = BIGGER boosts - survival mode)
    conf_boost_mult = _get_boost_multiplier(state.confidence)

    # 3. Context-based: higher context usage = harsher penalties, smaller boosts
    transcript_path = data.get("transcript_path", "")
    context_pct = _get_context_percentage(transcript_path)
    ctx_penalty_mult, ctx_boost_mult = _get_context_multiplier(context_pct)

    # Combined penalty multiplier (confidence × context)
    combined_penalty_mult = conf_penalty_mult * ctx_penalty_mult

    # Combined boost multiplier (confidence survival × context)
    # Low confidence AMPLIFIES boosts; high context REDUCES them
    combined_boost_mult = conf_boost_mult * ctx_boost_mult

    # Apply scaled penalties
    scaled_penalty = int(penalty * combined_penalty_mult)
    scaled_decay = (
        int(accumulated_decay * combined_penalty_mult) if accumulated_decay else 0
    )

    # Apply scaled boosts (amplified when struggling, reduced at high context)
    scaled_boost = int(boost * combined_boost_mult) if boost else 0

    # Net change: boosts are positive, decay and penalty are negative
    delta = scaled_boost - scaled_decay - scaled_penalty

    if delta == 0:
        return HookResult.none()

    # Apply rate limiting to prevent death spirals
    delta = apply_rate_limit(delta, state)

    if delta == 0:
        return HookResult.none()

    old_confidence = state.confidence
    new_confidence = max(0, min(100, old_confidence + delta))

    if new_confidence != old_confidence:
        set_confidence(state, new_confidence, "confidence_decay")

        # Build reason string
        reasons = []
        if scaled_boost:
            # Show survival mode amplification
            if conf_boost_mult > 1.0:
                reasons.append(
                    f"+{scaled_boost} {boost_reason} 🆘x{conf_boost_mult:.1f}"
                )
            else:
                reasons.append(f"+{scaled_boost} {boost_reason}")
        if accumulated_decay:
            reasons.append(f"-{scaled_decay} decay")
        if penalty:
            reasons.append(f"-{scaled_penalty} {penalty_reason}")

        # Add context as money ALWAYS (Entity Model: loss aversion framing)
        # I see this every turn - constant reminder that actions cost money
        remaining_budget = int(200_000 * (1 - context_pct / 100))
        if remaining_budget >= 1000:
            budget_str = f"${remaining_budget // 1000}K"
        else:
            budget_str = f"${remaining_budget}"
        reasons.append(budget_str)

        direction = "📈" if delta > 0 else "📉"
        return HookResult.with_context(
            f"{direction} **Confidence**: {old_confidence}% → {new_confidence}% "
            f"({'+' if delta > 0 else ''}{delta}) [{', '.join(reasons)}]"
        )

    return HookResult.none()
