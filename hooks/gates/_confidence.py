#!/usr/bin/env python3
"""
Confidence System Gates - Entity Model self-regulation hooks.

These gates implement the Entity Model's self-survival instincts:
- Homeostatic drive: Active pull toward stasis zone (80-90%)
- Threat anticipation: Proactive warnings before risky actions
- Tool gating: Block dangerous tools at low confidence
- Oracle enforcement: Mandate external consultation after failures
- External suggestions: Suggest alternatives at low confidence
- Integration gate: Enforce grep after function edits
- Error suppression: Block tools until errors resolved

Extracted from pre_tool_use_runner.py for modularity.
"""

from session_state import SessionState, track_block, clear_blocks
from ._common import register_hook, HookResult


# =============================================================================
# HOMEOSTATIC DRIVE (Priority 16) - Active recovery nudges below stasis
# =============================================================================


@register_hook("homeostatic_drive", None, priority=16)
def check_homeostatic_drive(data: dict, state: SessionState) -> HookResult:
    """
    Active pull toward stasis zone (80-90%) - the Entity Model's self-regulation.

    When below stasis floor, proactively suggest recovery actions.
    This is the "healing instinct" - the system actively seeks equilibrium.
    """
    from _confidence_constants import STASIS_FLOOR
    from confidence import get_tier_info

    # Skip if confidence not initialized or in healthy zone
    if state.confidence == 0 or state.confidence >= STASIS_FLOOR:
        return HookResult.approve()

    # Calculate deficit
    deficit = STASIS_FLOOR - state.confidence
    _, emoji, _ = get_tier_info(state.confidence)

    # Don't spam - track nudge frequency
    nudge_key = "_homeostatic_nudge_turn"
    last_nudge = state.nudge_history.get(nudge_key, 0)
    if state.turn_count - last_nudge < 3:  # Max once per 3 turns
        return HookResult.approve()

    state.nudge_history[nudge_key] = state.turn_count

    # Build contextual recovery suggestions based on what's cheap/available
    suggestions = []
    suggestions.append("📊 git status/diff (+10)")
    suggestions.append("📖 Read relevant files (+1 each)")
    if deficit >= 10:
        suggestions.append("🧪 Run tests (+5 each)")
        suggestions.append("❓ AskUserQuestion (+8)")

    recovery_str = " | ".join(suggestions[:3])

    return HookResult.approve(
        f"{emoji} **BELOW STASIS** ({state.confidence}% < {STASIS_FLOOR}%) - "
        f"Gap: {deficit}\n"
        f"💚 Recovery: {recovery_str}"
    )


# =============================================================================
# THREAT ANTICIPATION (Priority 17) - Pre-action confidence warnings
# =============================================================================


@register_hook("threat_anticipation", "Edit|Write|Bash", priority=17)
def check_threat_anticipation(data: dict, state: SessionState) -> HookResult:
    """
    Proactive trajectory prediction before risky actions.

    Warns BEFORE actions that would crash confidence below stasis floor.
    This is the "danger sense" - the system anticipates and warns of threats.
    """
    from _confidence_streaks import predict_trajectory, format_trajectory_warning
    from _confidence_constants import STASIS_FLOOR

    # Skip if confidence not initialized
    if state.confidence == 0:
        return HookResult.approve()

    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})

    # Calculate planned impact
    planned_edits = 1 if tool_name in ("Edit", "Write") else 0
    planned_bash = 1 if tool_name == "Bash" else 0

    # Check for edit oscillation risk (same file edited multiple times)
    if tool_name in ("Edit", "Write"):
        file_path = tool_input.get("file_path", "")
        edit_count = state.files_edited.count(file_path) if file_path else 0
        if edit_count >= 2:
            # About to trigger edit_oscillation (-12)
            planned_edits += 12  # Account for the penalty

    # Predict trajectory
    trajectory = predict_trajectory(
        state,
        planned_edits=planned_edits,
        planned_bash=planned_bash,
        turns_ahead=2,
    )

    # Only warn if trajectory is concerning
    if not trajectory["warnings"] and trajectory["projected"] >= STASIS_FLOOR:
        return HookResult.approve()

    # Format warning
    warning = format_trajectory_warning(trajectory)
    if warning:
        return HookResult.approve(warning)

    return HookResult.approve()


# =============================================================================
# CONFIDENCE TOOL GATE (Priority 18) - Block tools at low confidence
# =============================================================================


@register_hook("confidence_tool_gate", None, priority=18)
def check_confidence_tool_gate(data: dict, state: SessionState) -> HookResult:
    """Gate tool usage based on confidence level."""
    # SUDO bypass
    if data.get("_sudo_bypass"):
        return HookResult.approve()

    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})

    # Framework maintenance bypass - can't fix confidence system if it blocks itself
    file_path = tool_input.get("file_path", "")
    if ".claude/" in file_path:
        return HookResult.approve()

    # Skip if confidence not initialized
    if state.confidence == 0:
        return HookResult.approve()

    # Lazy import - only load when actually gating
    # Safety-critical: explicit deny on ImportError (not fail-open)
    try:
        from confidence import check_tool_permission
    except ImportError as e:
        return HookResult.deny(
            f"⚠️ confidence_tool_gate unavailable ({e}). Refusing tool use. Say SUDO to bypass."
        )

    # Check tool permission
    is_permitted, block_message = check_tool_permission(
        state.confidence, tool_name, tool_input
    )

    if not is_permitted:
        track_block(state, "confidence_tool_gate")
        return HookResult.deny(block_message)

    # Clear blocks on successful passage
    clear_blocks(state, "confidence_tool_gate")
    return HookResult.approve()


# =============================================================================
# ORACLE GATE (Priority 30) - Enforce consultation after failures
# =============================================================================


@register_hook("oracle_gate", "Edit|Write|Bash", priority=30)
def check_oracle_gate(data: dict, state: SessionState) -> HookResult:
    """Enforce oracle consultation after repeated failures."""
    from session_state import get_turns_since_op

    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})
    # SUDO bypass
    if data.get("_sudo_bypass"):
        return HookResult.approve()

    # Skip diagnostic bash commands
    if tool_name == "Bash":
        command = tool_input.get("command", "")
        diagnostic = ["ls", "cat", "grep", "find", "echo", "pwd", "which"]
        if any(command.strip().startswith(p) for p in diagnostic):
            return HookResult.approve()
        if any(r in command for r in ["oracle", "think", "council"]):
            return HookResult.approve()

    failures = state.consecutive_failures

    # Check if oracle/think was run recently
    min_turns = min(
        get_turns_since_op(state, "oracle"),
        get_turns_since_op(state, "think"),
        get_turns_since_op(state, "council"),
    )
    if min_turns <= 5:
        return HookResult.approve()

    if failures == 2:
        return HookResult.approve(
            "⚠️ **ORACLE NUDGE** (2 consecutive failures)\n"
            'Consider: `think "Why is this failing?"` before attempt #3.'
        )

    if failures >= 3:
        return HookResult.deny(
            f"**ORACLE GATE BLOCKED** (Three-Strike Rule)\n"
            f"**{failures} failures** without oracle/think consultation.\n"
            f'Run `think "Debug: <problem>"` or user says "SUDO CONTINUE".'
        )
    return HookResult.approve()


# =============================================================================
# EXTERNAL SUGGESTION (Priority 32) - Suggest alternatives at low confidence
# =============================================================================


@register_hook("confidence_external_suggestion", None, priority=32)
def check_confidence_external_suggestion(data: dict, state: SessionState) -> HookResult:
    """Suggest external consultation and alternatives at low confidence."""
    # Skip if confidence not initialized or high enough
    if state.confidence == 0 or state.confidence >= 50:
        return HookResult.approve()

    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})

    # Don't suggest for diagnostic/read-only tools
    read_only_tools = {"Read", "Grep", "Glob", "WebSearch", "WebFetch", "TodoRead"}
    if tool_name in read_only_tools:
        return HookResult.approve()

    # Don't suggest for external consultation tools (that's what we're suggesting!)
    if tool_name.startswith("mcp__pal__"):
        return HookResult.approve()

    # Lazy import - only load confidence utilities when needed
    from confidence import should_mandate_external, suggest_alternatives, get_tier_info

    parts = []

    # Check if external consultation is mandatory
    mandatory, mandatory_msg = should_mandate_external(state.confidence)
    if mandatory:
        parts.append(mandatory_msg)

    # Suggest alternatives based on confidence
    task_desc = tool_input.get("description", "") or tool_input.get("prompt", "")[:50]
    alternatives = suggest_alternatives(state.confidence, task_desc)
    if alternatives:
        parts.append(alternatives)

    if parts:
        tier_name, emoji, _ = get_tier_info(state.confidence)
        header = (
            f"{emoji} **Low Confidence Warning: {state.confidence}% ({tier_name})**\n"
        )
        return HookResult.approve(header + "\n\n".join(parts))

    return HookResult.approve()


# =============================================================================
# INTEGRATION GATE (Priority 35) - Enforce grep after function edits
# =============================================================================


@register_hook("integration_gate", "Edit|Write|Task", priority=35)
def check_integration_gate(data: dict, state: SessionState) -> HookResult:
    """Enforce grep after function edits."""
    from session_state import check_integration_blindness

    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})

    # Auto-expire old pending greps (> 5 turns old)
    current_turn = state.turn_count
    state.pending_integration_greps = [
        g
        for g in state.pending_integration_greps
        if current_turn - g.get("turn", 0) <= 5
    ]

    should_block, message = check_integration_blindness(state, tool_name, tool_input)
    if should_block:
        return HookResult.deny(message)
    return HookResult.approve()


# =============================================================================
# ERROR SUPPRESSION GATE (Priority 40) - Block tools until errors resolved
# =============================================================================


@register_hook("error_suppression_gate", "Edit|Write|MultiEdit|Task", priority=40)
def check_error_suppression(data: dict, state: SessionState) -> HookResult:
    """Block non-diagnostic tools until errors are resolved."""
    import time as time_mod

    tool_name = data.get("tool_name", "")

    # Always allow diagnostic tools
    DIAGNOSTIC_TOOLS = {
        "Read",
        "Grep",
        "Glob",
        "Bash",
        "BashOutput",
        "WebFetch",
        "WebSearch",
        "TodoWrite",
    }
    if tool_name in DIAGNOSTIC_TOOLS:
        return HookResult.approve()

    # Check for recent unresolved errors (within 5 min)
    ERROR_TTL = 300
    cutoff = time_mod.time() - ERROR_TTL
    recent_errors = [
        e for e in state.errors_unresolved if e.get("timestamp", 0) > cutoff
    ]

    if not recent_errors:
        return HookResult.approve()

    latest = recent_errors[-1]
    error_type = latest.get("type", "Unknown")[:60]

    return HookResult.deny(
        f"**ERROR SUPPRESSION BLOCKED**\n"
        f"Unresolved: {error_type}\n"
        f"Fix the error before continuing. Use Bash/Read/Grep to debug."
    )
