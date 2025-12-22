#!/usr/bin/env python3
"""
Blast Radius Gate - Escalate confidence requirements based on Groq risk_signals.

When Groq router returns risk_signals with high blast_radius or low reversibility,
this gate BLOCKS write operations unless confidence is elevated.

v4.34: Initial implementation integrating Phase 1 metadata.

Priority 19: Runs after confidence_tool_gate (18), before oracle_gate (30).
"""

from session_state import SessionState
from ._common import register_hook, HookResult


# Blast radius to confidence delta mapping
_BLAST_RADIUS_ESCALATION = {
    "local": 0,  # No escalation
    "module": 5,  # +5% required
    "service": 10,  # +10% required
    "multi_service": 15,  # +15% required
    "prod_wide": 20,  # +20% required
}

# Reversibility to confidence delta mapping
_REVERSIBILITY_ESCALATION = {
    "easy": 0,  # No escalation
    "moderate": 5,  # +5% required
    "hard": 10,  # +10% required
    "irreversible": 20,  # +20% required
}

# Base confidence requirements by zone
_BASE_REQUIREMENTS = {
    "Edit": 51,  # WORKING zone minimum
    "Write": 51,
    "MultiEdit": 51,
    "Bash": 51,  # State-changing bash
}


def _get_risk_signals(state: SessionState) -> dict | None:
    """Get risk_signals from mastermind state or session state."""
    # Try session state first (injected by prompt hook)
    risk_signals = state.get("mastermind_risk_signals")
    if risk_signals:
        return risk_signals

    # Try loading from MastermindState
    try:
        session_id = state.get("session_id")
        if not session_id:
            return None

        from lib.mastermind.state import load_state

        mm_state = load_state(session_id)
        # risk_signals is inside routing_decision
        if (
            mm_state
            and mm_state.routing_decision
            and mm_state.routing_decision.risk_signals
        ):
            rs = mm_state.routing_decision.risk_signals
            return {
                "blast_radius": rs.blast_radius,
                "reversibility": rs.reversibility,
                "requires_review": rs.requires_review,
                "confidence_override": rs.confidence_override,
                "risk_factors": rs.risk_factors,
            }
    except (ImportError, AttributeError, OSError):
        pass

    return None


def _is_state_changing_bash(command: str) -> bool:
    """Check if bash command modifies state (vs read-only)."""
    readonly_prefixes = (
        "ls",
        "cat",
        "head",
        "tail",
        "pwd",
        "which",
        "tree",
        "stat",
        "echo",
        "grep",
        "find",
        "git status",
        "git log",
        "git diff",
        "git show",
        "git branch",
        "ruff check",
        "pytest",
        "python -m pytest",
    )
    cmd = command.strip()
    return not any(cmd.startswith(p) for p in readonly_prefixes)


@register_hook("blast_radius_gate", "Edit|Write|MultiEdit|Bash", priority=19)
def check_blast_radius_gate(data: dict, state: SessionState) -> HookResult:
    """
    Escalate confidence requirements based on Groq's risk_signals.

    High blast_radius or low reversibility → higher confidence required.
    BLOCKS writes if confidence insufficient for the risk level.

    SUDO to bypass.
    """
    # SUDO bypass
    if data.get("_sudo_bypass"):
        return HookResult.approve("⚠️ Blast radius gate bypassed via SUDO")

    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})

    # Skip Bash if read-only
    if tool_name == "Bash":
        command = tool_input.get("command", "")
        if not _is_state_changing_bash(command):
            return HookResult.approve()

    # Get risk signals
    risk_signals = _get_risk_signals(state)
    if not risk_signals:
        return HookResult.approve()  # No risk info, no escalation

    # Calculate escalation
    blast_radius = risk_signals.get("blast_radius", "local")
    reversibility = risk_signals.get("reversibility", "easy")
    confidence_override = risk_signals.get("confidence_override")

    # Use explicit override if provided
    if confidence_override is not None:
        required = int(confidence_override * 100)
    else:
        # Calculate from blast_radius + reversibility
        base = _BASE_REQUIREMENTS.get(tool_name, 51)
        blast_delta = _BLAST_RADIUS_ESCALATION.get(blast_radius, 0)
        rev_delta = _REVERSIBILITY_ESCALATION.get(reversibility, 0)
        # Take max of blast/rev delta (don't double-stack)
        required = base + max(blast_delta, rev_delta)

    # Cap at 95 (EXPERT zone starts at 95)
    required = min(required, 95)

    current = state.confidence

    # Check if confidence is sufficient
    if current >= required:
        # Warn if close to threshold
        if current - required <= 5:
            return HookResult.approve(
                f"⚠️ **Risk escalation active** ({blast_radius}/{reversibility})\n"
                f"Required: {required}% | Current: {current}% | Margin: {current - required}%"
            )
        return HookResult.approve()

    # BLOCK - insufficient confidence for risk level
    deficit = required - current
    risk_factors = risk_signals.get("risk_factors", [])
    factors_str = ", ".join(risk_factors[:3]) if risk_factors else "none specified"

    return HookResult.deny(
        f"🛑 **BLAST RADIUS GATE** - Elevated confidence required\n\n"
        f"**Risk Profile:**\n"
        f"- Blast radius: `{blast_radius}`\n"
        f"- Reversibility: `{reversibility}`\n"
        f"- Risk factors: {factors_str}\n\n"
        f"**Confidence Gap:**\n"
        f"- Required: {required}%\n"
        f"- Current: {current}%\n"
        f"- Deficit: {deficit}%\n\n"
        f"**Recovery Options:**\n"
        f"1. Run tests (+5 each)\n"
        f"2. `mcp__pal__codereview` for validation (+5)\n"
        f"3. `AskUserQuestion` for confirmation (+8)\n"
        f"4. `git status/diff` (+3)\n\n"
        f"**Bypass:** Say `SUDO` (logged)"
    )


__all__ = ["check_blast_radius_gate"]
