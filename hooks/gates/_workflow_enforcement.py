#!/usr/bin/env python3
"""
Workflow Enforcement Gates (v4.32) - HARD BLOCKS for mandatory prerequisites.

These gates enforce the MUST-do workflow requirements:
1. PAL MCP MUST init for non-trivial tasks
2. Memory (claude-mem OR serena) MUST be searched for non-trivial
3. Research MUST happen for complex tasks
4. Bead MUST be claimed for non-trivial tasks
5. Active beads MUST be checked (informational)

All gates respect:
- SUDO bypass (workflow_bypass_until_turn)
- Trivial task classification (workflow_classification == "trivial")
- Bootstrap tools (the tools that satisfy the prerequisite)

Priority ordering (lower = runs first):
- Priority 3: Active beads check (informational)
- Priority 5: PAL gate
- Priority 6: Memory gate
- Priority 7: Research gate
- Priority 8: Bead gate
"""

from pathlib import Path
import shlex
import subprocess
import json
import sys

from ._common import register_hook, HookResult

# Tools that are always allowed (read-only, bootstrap, or PAL)
ALWAYS_ALLOWED = {
    # Read-only tools
    "Read",
    "Grep",
    "Glob",
    "LS",
    "WebSearch",
    "WebFetch",
    # PAL tools (bootstrap for PAL gate)
    "mcp__pal__chat",
    "mcp__pal__debug",
    "mcp__pal__thinkdeep",
    "mcp__pal__planner",
    "mcp__pal__consensus",
    "mcp__pal__codereview",
    "mcp__pal__precommit",
    "mcp__pal__analyze",
    "mcp__pal__apilookup",
    "mcp__pal__challenge",
    "mcp__pal__clink",
    "mcp__pal__listmodels",
    "mcp__pal__version",
    # Memory tools (bootstrap for memory gate)
    "mcp__plugin_claude-mem_mem-search__search",
    "mcp__plugin_claude-mem_mem-search__timeline",
    "mcp__plugin_claude-mem_mem-search__get_recent_context",
    "mcp__plugin_claude-mem_mem-search__get_observation",
    "mcp__plugin_claude-mem_mem-search__get_observations",
    "mcp__mem-search__search",
    "mcp__mem-search__timeline",
    "mcp__mem-search__get_recent_context",
    "mcp__serena__list_memories",
    "mcp__serena__read_memory",
    # Serena activation (required first)
    "mcp__serena__activate_project",
    "mcp__serena__initial_instructions",
    "mcp__serena__check_onboarding_performed",
    "mcp__serena__onboarding",
    "mcp__serena__get_current_config",
    # Research tools (bootstrap for research gate)
    "mcp__crawl4ai__crawl",
    "mcp__crawl4ai__ddg_search",
    "mcp__serena__search_for_pattern",
    "mcp__serena__find_symbol",
    "mcp__serena__get_symbols_overview",
    "mcp__serena__find_file",
    "mcp__serena__list_dir",
    "mcp__serena__find_referencing_symbols",
    # Task agents (can satisfy prerequisites)
    "Task",
    # Beads tools (bootstrap for bead gate)
    "mcp__beads__create_bead",
    "mcp__beads__update_bead",
    "mcp__beads__list_beads",
    "mcp__beads__get_ready",
    "mcp__beads__show_bead",
    "mcp__beads__close_bead",
    # User interaction
    "AskUserQuestion",
    "TodoWrite",
    "TodoRead",
    # Skill execution
    "Skill",
}

# Tools that trigger writes (these get blocked by gates)
WRITE_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit", "Bash"}


def _is_sudo_bypass_active(state) -> bool:
    """Check if SUDO bypass is active."""
    return getattr(state, "workflow_bypass_until_turn", 0) > getattr(
        state, "turn_count", 0
    )


def _get_classification(state) -> str:
    """Get workflow classification from state.

    Checks workflow_classification first, then falls back to mastermind_classification.
    Returns empty string if not yet classified (allows bootstrap).
    """
    # Primary field set by workflow system
    classification = getattr(state, "workflow_classification", "")
    if classification:
        return classification
    # Fallback to mastermind classification (legacy/compatibility)
    return getattr(state, "mastermind_classification", "")


def _get_prerequisites(state) -> dict:
    """Get workflow prerequisites dict."""
    return getattr(
        state,
        "workflow_prerequisites",
        {
            "groq_routed": False,
            "pal_initialized": False,
            "memory_searched": False,
            "research_done": False,
            "bead_claimed": False,
            "active_beads_checked": False,
        },
    )


# Cache for bead lookup to avoid repeated subprocess calls
_bead_cache: dict = {"beads": [], "turn": -1}


def _get_in_progress_beads(state=None) -> list:
    """Get list of in_progress beads for current project (cached per turn)."""
    # Use cache if same turn
    current_turn = getattr(state, "turn_count", 0) if state else 0
    if _bead_cache["turn"] == current_turn and current_turn > 0:
        return _bead_cache["beads"]

    try:
        result = subprocess.run(
            ["bd", "list", "--status=in_progress", "--format=json"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=Path.home() / ".claude",
        )
        if result.returncode == 0 and result.stdout.strip():
            beads = json.loads(result.stdout)
            _bead_cache["beads"] = beads
            _bead_cache["turn"] = current_turn
            return beads
        _bead_cache["beads"] = []
        _bead_cache["turn"] = current_turn
        return []
    except subprocess.TimeoutExpired:
        print("[workflow] bd list timed out", file=sys.stderr)
        return []
    except json.JSONDecodeError as e:
        print(f"[workflow] bd list invalid JSON: {e}", file=sys.stderr)
        return []
    except FileNotFoundError:
        # bd not installed - not an error, just no beads
        return []
    except OSError as e:
        print(f"[workflow] bd list failed: {e}", file=sys.stderr)
        return []


# =============================================================================
# Gate 1: Active Beads Check (Priority 3) - INFORMATIONAL
# =============================================================================


@register_hook("workflow_beads_check", None, priority=3)
def check_workflow_beads_check(data: dict, state) -> HookResult:
    """
    INFORMATIONAL: Surface active beads before any work.

    Priority 3: Very early, after Serena (0) but before other workflow gates.
    Always approves but injects context about active beads.
    """
    prereqs = _get_prerequisites(state)

    # Only check once per session
    if prereqs.get("active_beads_checked"):
        return HookResult.approve()

    # Skip if SUDO bypass
    if _is_sudo_bypass_active(state):
        return HookResult.approve()

    # Check for active beads (pass state for caching)
    in_progress = _get_in_progress_beads(state)

    # Mark as checked (unconditional assignment ensures persistence)
    prereqs["active_beads_checked"] = True
    state.workflow_prerequisites = prereqs

    if in_progress:
        bead_list = ", ".join(
            f"`{b.get('id', '?')[:12]}` ({b.get('title', 'untitled')[:30]})"
            for b in in_progress[:5]
        )
        return HookResult.approve(
            f"🎯 **Active beads detected:** {bead_list}\n"
            f"Consider claiming or closing before starting new work."
        )

    return HookResult.approve()


# =============================================================================
# Gate 2: PAL Initialization Gate (Priority 5) - HARD BLOCK
# =============================================================================


@register_hook("workflow_pal_gate", None, priority=5)
def check_workflow_pal_gate(data: dict, state) -> HookResult:
    """
    HARD BLOCK: PAL MCP MUST be initialized for non-trivial tasks.

    Fires early (Priority 5) to force PAL consultation before changes.
    Blocks ALL write tools until at least one mcp__pal__* call made.
    """
    tool_name = data.get("tool_name", "")

    # Always allow non-write tools
    if tool_name not in WRITE_TOOLS:
        return HookResult.approve()

    # SUDO bypass
    if _is_sudo_bypass_active(state):
        return HookResult.approve()

    # Check classification
    classification = _get_classification(state)

    # If not yet classified, allow (mastermind hasn't run yet)
    if not classification:
        return HookResult.approve()

    # Trivial tasks bypass
    if classification == "trivial":
        return HookResult.approve()

    # Check if PAL initialized
    prereqs = _get_prerequisites(state)
    if prereqs.get("pal_initialized"):
        return HookResult.approve()

    # Get suggested PAL tool from mastermind
    suggested = getattr(state, "mastermind_pal_suggested", "chat")

    return HookResult.deny(
        f"🚨 **PAL MCP REQUIRED** ({classification} task)\n\n"
        f"Non-trivial tasks MUST consult PAL before making changes.\n\n"
        f"**Run:** `mcp__pal__{suggested}` with your task context\n"
        f"**Or:** `mcp__pal__chat` for general consultation\n\n"
        f"_Say SUDO to bypass (logged)_"
    )


# =============================================================================
# Gate 3: Memory Search Gate (Priority 6) - HARD BLOCK
# =============================================================================


@register_hook("workflow_memory_gate", None, priority=6)
def check_workflow_memory_gate(data: dict, state) -> HookResult:
    """
    HARD BLOCK: Memory search MUST happen for non-trivial tasks.

    Requires either:
    - claude-mem search (mcp__plugin_claude-mem_mem-search__search)
    - serena memories (mcp__serena__list_memories + read_memory)
    """
    tool_name = data.get("tool_name", "")

    # Always allow non-write tools
    if tool_name not in WRITE_TOOLS:
        return HookResult.approve()

    # SUDO bypass
    if _is_sudo_bypass_active(state):
        return HookResult.approve()

    # Check classification
    classification = _get_classification(state)
    if not classification or classification == "trivial":
        return HookResult.approve()

    # Check if memory searched
    prereqs = _get_prerequisites(state)
    if prereqs.get("memory_searched"):
        return HookResult.approve()

    return HookResult.deny(
        f"🧠 **MEMORY SEARCH REQUIRED** ({classification} task)\n\n"
        f"Non-trivial tasks MUST search memory for prior context.\n\n"
        f"**Options:**\n"
        f"- `mcp__plugin_claude-mem_mem-search__search` (claude-mem)\n"
        f"- `/sm` skill (serena memories)\n"
        f"- `mcp__serena__list_memories` then `read_memory`\n\n"
        f"_Say SUDO to bypass (logged)_"
    )


# =============================================================================
# Gate 4: Research Gate (Priority 7) - HARD BLOCK (complex only)
# =============================================================================


@register_hook("workflow_research_gate", None, priority=7)
def check_workflow_research_gate(data: dict, state) -> HookResult:
    """
    HARD BLOCK: Research MUST happen for complex tasks.

    Requires ANY of:
    - WebSearch, crawl4ai (web research)
    - Task(Explore), Task(researcher) (agent exploration)
    - Serena search tools (code exploration)
    - 3+ Grep/Glob calls (exploration pattern)
    """
    tool_name = data.get("tool_name", "")

    # Always allow non-write tools
    if tool_name not in WRITE_TOOLS:
        return HookResult.approve()

    # SUDO bypass
    if _is_sudo_bypass_active(state):
        return HookResult.approve()

    # Only applies to complex tasks
    classification = _get_classification(state)
    if classification != "complex":
        return HookResult.approve()

    # Check if research done
    prereqs = _get_prerequisites(state)
    if prereqs.get("research_done"):
        return HookResult.approve()

    return HookResult.deny(
        "🔬 **RESEARCH REQUIRED** (complex task)\n\n"
        "Complex tasks MUST include exploration/research before changes.\n\n"
        "**Options:**\n"
        "- `WebSearch` or `mcp__crawl4ai__ddg_search` (web)\n"
        "- `Task(subagent_type='Explore')` (codebase exploration)\n"
        "- `mcp__serena__search_for_pattern` (code search)\n"
        "- `Task(subagent_type='researcher')` (research agent)\n\n"
        "_Say SUDO to bypass (logged)_"
    )


# =============================================================================
# Gate 5: Bead Requirement Gate (Priority 8) - HARD BLOCK
# =============================================================================


@register_hook("workflow_bead_gate", None, priority=8)
def check_workflow_bead_gate(data: dict, state) -> HookResult:
    """
    HARD BLOCK: Bead MUST be claimed for non-trivial tasks.

    Enforces explicit bead creation/claim before making changes.
    Does NOT auto-create (forces intentional tracking).
    """
    tool_name = data.get("tool_name", "")

    # Always allow non-write tools
    if tool_name not in WRITE_TOOLS:
        return HookResult.approve()

    # SUDO bypass
    if _is_sudo_bypass_active(state):
        return HookResult.approve()

    # Check classification
    classification = _get_classification(state)
    if not classification or classification == "trivial":
        return HookResult.approve()

    # Check if bead claimed
    prereqs = _get_prerequisites(state)
    if prereqs.get("bead_claimed"):
        return HookResult.approve()

    # Check for actual in_progress beads (pass state for caching)
    in_progress = _get_in_progress_beads(state)
    if in_progress:
        # Mark as claimed and approve (unconditional assignment)
        prereqs["bead_claimed"] = True
        state.workflow_prerequisites = prereqs
        return HookResult.approve()

    # Get goal from state for suggested title - sanitize for shell safety
    raw_goal = getattr(state, "original_goal", "")[:50] or "task"
    # Strip control chars and newlines, then shell-quote
    safe_goal = "".join(
        ch for ch in raw_goal if ch.isprintable() and ch not in "\r\n\t"
    )
    quoted_goal = shlex.quote(safe_goal)

    return HookResult.deny(
        f"📿 **BEAD REQUIRED** ({classification} task)\n\n"
        f"Non-trivial tasks MUST be tracked with beads.\n\n"
        f"**Create & claim:**\n"
        f"```bash\n"
        f"bd create --title={quoted_goal} --type=task\n"
        f"bd update <bead-id> --status=in_progress\n"
        f"```\n\n"
        f"**Or claim existing:** `bd list` then `bd update <id> --status=in_progress`\n\n"
        f"_Say SUDO to bypass (logged)_"
    )
