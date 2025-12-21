#!/usr/bin/env python3
"""
Agent Pre-flight Validation Gate - Prevent wasted agent context on predictable blocks.

PROBLEM: If multiple agents are spawned and they ALL hit the same hard block
(confidence gate, beads enforcement, etc.), we've wasted 50k+ tokens per agent.

SOLUTION: Pre-flight validation that runs BEFORE spawning agents to detect
predictable blocks and surface them early.

CHECKS:
1. Confidence level - Don't spawn writing agents if confidence < 30%
2. Recent block cascade - If same block fired 3+ times recently, warn
3. Tool prerequisites - If agent likely needs Edit, check confidence first
4. Known blockers - Track blocks from recent agent failures

Priority: 2 (very early - before parallel_bead_delegation at 3)
"""

from typing import Optional

from session_state import SessionState
from ._common import register_hook, HookResult

# =============================================================================
# AGENT CAPABILITY MAPPING
# =============================================================================

# Agents and what tools they typically use (for pre-flight checks)
_AGENT_TOOL_PROFILES = {
    # Writing agents - need confidence > 30%
    "refactorer": {
        "writes": True,
        "min_confidence": 30,
        "tools": ["Edit", "Write", "Grep"],
    },
    "debugger": {
        "writes": True,
        "min_confidence": 30,
        "tools": ["Edit", "Bash", "Read"],
    },
    "code-reviewer": {"writes": False, "min_confidence": 0, "tools": ["Read", "Grep"]},
    # Read-only agents - always safe
    "explore": {
        "writes": False,
        "min_confidence": 0,
        "tools": ["Read", "Grep", "Glob"],
    },
    "researcher": {
        "writes": False,
        "min_confidence": 0,
        "tools": ["WebSearch", "WebFetch"],
    },
    "plan": {"writes": False, "min_confidence": 0, "tools": ["Read", "Grep"]},
    # Mixed agents
    "general-purpose": {
        "writes": True,
        "min_confidence": 30,
        "tools": ["Edit", "Bash", "Read"],
    },
    "planner": {"writes": False, "min_confidence": 0, "tools": ["Read", "Grep"]},
    # Security/specialized agents
    "scout": {"writes": False, "min_confidence": 0, "tools": ["Read", "Grep", "Glob"]},
    "deep-security": {
        "writes": False,
        "min_confidence": 0,
        "tools": ["Read", "Grep", "Bash"],
    },
    # Claude-code-guide for documentation lookups
    "claude-code-guide": {
        "writes": False,
        "min_confidence": 0,
        "tools": ["Read", "Glob", "WebFetch", "WebSearch"],
    },
    # Repomix explorer
    "repomix-explorer:explorer": {
        "writes": False,
        "min_confidence": 0,
        "tools": ["mcp__plugin_repomix-mcp_repomix__*"],
    },
}

# Blocks that are "predictable" - if they fired recently, warn before spawning
_PREDICTABLE_BLOCKS = {
    "confidence_tool_gate": "Confidence too low for writing tools",
    "bead_enforcement": "No bead claimed - agent edits will be blocked",
    "loop_detector": "Bash patterns being blocked",
    "background_enforcer": "Commands require background execution",
    "content_gate": "Code content being rejected (AST issues)",
}


def _get_recent_blocks(state: SessionState, lookback: int = 10) -> dict[str, int]:
    """Get blocks that fired in the last N turns with their counts.

    Uses existing consecutive_blocks from session_state (populated by track_block).
    """
    blocks = {}
    consecutive_blocks = getattr(state, "consecutive_blocks", {})

    for hook_name, entry in consecutive_blocks.items():
        last_turn = entry.get("last_turn", 0)
        if state.turn_count - last_turn <= lookback:
            blocks[hook_name] = entry.get("count", 0)

    return blocks


def _check_agent_prerequisites(
    subagent_type: str, state: SessionState
) -> Optional[str]:
    """Check if agent can succeed given current state. Returns warning or None."""
    profile = _AGENT_TOOL_PROFILES.get(subagent_type.lower(), {})

    # Check confidence for writing agents
    if profile.get("writes", False):
        min_conf = profile.get("min_confidence", 30)
        if state.confidence < min_conf:
            return (
                f"⚠️ **PRE-FLIGHT WARNING**: `{subagent_type}` agent needs Edit/Write access, "
                f"but confidence is {state.confidence}% (min: {min_conf}%). "
                f"Agent may waste tokens hitting confidence gate. "
                f"Consider: read-only agent, or raise confidence first."
            )

    return None


def _check_block_cascade(state: SessionState) -> Optional[str]:
    """Check if recent blocks suggest agents will fail."""
    recent_blocks = _get_recent_blocks(state, lookback=5)

    # Check for cascade patterns
    warnings = []
    for hook_name, count in recent_blocks.items():
        if count >= 2 and hook_name in _PREDICTABLE_BLOCKS:
            warnings.append(
                f"  • `{hook_name}` fired {count}x: {_PREDICTABLE_BLOCKS[hook_name]}"
            )

    if warnings:
        return (
            "⚠️ **PRE-FLIGHT WARNING**: Recent blocks detected that may affect agents:\n"
            + "\n".join(warnings)
            + "\n"
            "Spawned agents may hit same blocks. Resolve blockers first, or SUDO PREFLIGHT to bypass."
        )

    return None


def _track_agent_spawn(state: SessionState, subagent_type: str, prompt: str) -> None:
    """Track agent spawns for cascade detection."""
    if not hasattr(state, "agent_spawn_history"):
        state.agent_spawn_history = []

    state.agent_spawn_history = (
        state.agent_spawn_history
        + [
            {
                "type": subagent_type,
                "turn": state.turn_count,
                "prompt_preview": prompt[:50] if prompt else "",
            }
        ]
    )[-10:]  # Keep last 10


# =============================================================================
# PRE-FLIGHT GATE (Priority 2) - Before any other Task gates
# =============================================================================


@register_hook("agent_preflight", "Task", priority=2)
def check_agent_preflight(data: dict, state: SessionState) -> HookResult:
    """
    Pre-flight validation for Task agents - prevent wasted context.

    PHILOSOPHY: It's better to warn/block ONCE at master thread level
    than to let 5 agents each waste 50k tokens hitting the same block.

    CHECKS:
    1. Agent capability vs current state (confidence, beads)
    2. Recent block cascade detection
    3. Known blocker patterns

    BYPASS: Say "SUDO PREFLIGHT" to spawn anyway.
    """
    # SUDO bypass
    if data.get("_sudo_bypass"):
        return HookResult.approve()

    tool_input = data.get("tool_input", {})
    subagent_type = tool_input.get("subagent_type", "").lower()
    prompt = tool_input.get("prompt", "")

    # Skip validation for resume (agent already has context)
    if tool_input.get("resume"):
        return HookResult.approve()

    # Track this spawn attempt
    _track_agent_spawn(state, subagent_type, prompt)

    warnings = []

    # Check 1: Agent prerequisites (confidence, etc.)
    prereq_warning = _check_agent_prerequisites(subagent_type, state)
    if prereq_warning:
        warnings.append(prereq_warning)

    # Check 2: Recent block cascade
    cascade_warning = _check_block_cascade(state)
    if cascade_warning:
        warnings.append(cascade_warning)

    # Check 3: Multiple agents spawning into known blocker
    # If this is the 3rd+ agent spawn this turn AND we have active blocks, escalate
    spawns_this_turn = sum(
        1
        for s in getattr(state, "agent_spawn_history", [])
        if s.get("turn") == state.turn_count
    )

    if spawns_this_turn >= 3 and warnings:
        # HARD BLOCK - too many agents spawning into known blockers
        return HookResult.deny(
            f"🚫 **PARALLEL SPAWN BLOCKED**: Spawning {spawns_this_turn}+ agents into known blockers.\n"
            + "\n".join(warnings)
            + "\n"
            "Fix the underlying issue first. SUDO PREFLIGHT to force."
        )

    # Soft warning for single agent
    if warnings:
        return HookResult.approve("\n".join(warnings))

    return HookResult.approve()


# Note: Block tracking uses existing track_block() from session_state.
# Gates that deny() should call track_block(state, "hook_name") to record
# for cascade detection. See _session_thresholds.py for implementation.
