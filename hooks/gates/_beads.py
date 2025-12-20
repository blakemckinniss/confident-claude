#!/usr/bin/env python3
"""
Beads/Parallel Execution Gates - Task orchestration and bead enforcement.

These gates manage parallel task execution and bead tracking:
- Parallel nudge: Encourage concurrent Task spawns
- Beads parallel: Batch sequential beads commands
- Bead enforcement: Require in_progress bead for substantive work
- Parallel bead delegation: Force parallelism when multiple beads ready
- Recursion guard: Block catastrophic folder duplication

Extracted from pre_tool_use_runner.py for modularity.
"""

import re

from session_state import SessionState
from ._common import register_hook, HookResult
from ._bash import strip_heredoc_content

# =============================================================================
# SHARED STATE FOR BEADS CACHING
# =============================================================================

# Cache for bd command results (shared with pre_tool_use_runner.py)
_BD_CACHE: dict = {}
_BD_CACHE_TURN: int = 0

# =============================================================================
# HELPER CONSTANTS AND FUNCTIONS
# =============================================================================

# Agent types that benefit from background execution
_LONG_RUNNING_AGENTS = {
    "explore": "exploring large codebases",
    "plan": "generating detailed plans",
    "code-reviewer": "comprehensive code review",
    "deep-security": "security audits",
    "scout": "codebase exploration",
}


def _track_background_task(
    state: SessionState, subagent_type: str, prompt: str
) -> None:
    """Record background task for later check-in reminder."""
    if not hasattr(state, "background_tasks"):
        state.background_tasks = []
    state.background_tasks = (
        state.background_tasks
        + [{"type": subagent_type, "prompt": prompt[:50], "turn": state.turn_count}]
    )[-5:]


def _update_task_counters(state: SessionState, prompt: str) -> None:
    """Update sequential task detection counters."""
    current_turn = state.turn_count
    if state.last_task_turn != current_turn:
        if state.last_task_turn > 0 and state.task_spawns_this_turn == 1:
            state.consecutive_single_tasks += 1
        elif state.task_spawns_this_turn > 1:
            state.consecutive_single_tasks = 0
        state.task_spawns_this_turn = 0
        state.last_task_turn = current_turn
    state.task_spawns_this_turn += 1
    if prompt:
        state.task_prompts_recent = (state.task_prompts_recent + [prompt[:100]])[-5:]


# =============================================================================
# PARALLEL NUDGE (Priority 4) - Encourage concurrent Task spawns
# =============================================================================


@register_hook("parallel_nudge", "Task", priority=4)
def check_parallel_nudge(data: dict, state: SessionState) -> HookResult:
    """Nudge sequential Task spawns toward parallel execution + background promotion."""
    tool_input = data.get("tool_input", {})
    prompt = tool_input.get("prompt", "")
    subagent_type = tool_input.get("subagent_type", "").lower()

    if tool_input.get("resume"):
        return HookResult.approve()

    if tool_input.get("run_in_background"):
        _track_background_task(state, subagent_type, prompt)
        return HookResult.approve()

    messages = []
    if subagent_type in _LONG_RUNNING_AGENTS:
        messages.append(
            f"💡 **Background opportunity**: {subagent_type} agents can run with "
            f"`run_in_background: true` - continue working while it runs, check with TaskOutput later."
        )

    _update_task_counters(state, prompt)

    # Multiple tasks this turn = good parallel behavior
    if state.task_spawns_this_turn > 1:
        state.consecutive_single_tasks = 0
        return (
            HookResult.approve("\n".join(messages))
            if messages
            else HookResult.approve()
        )

    # Sequential single-Task pattern
    if state.consecutive_single_tasks >= 3:
        state.parallel_nudge_count += 1
        messages.insert(
            0,
            "⚡ **PARALLEL AGENTS**: 3+ sequential Tasks detected. "
            "Spawn ALL independent Tasks in ONE message for concurrent execution.",
        )
    elif state.consecutive_single_tasks >= 2:
        state.parallel_nudge_count += 1
        messages.insert(
            0,
            "💡 **Parallel opportunity**: Multiple independent Tasks? Spawn them all in one message.",
        )

    return HookResult.approve("\n".join(messages)) if messages else HookResult.approve()


# =============================================================================
# BEADS PARALLEL (Priority 4) - Batch sequential beads commands
# =============================================================================


@register_hook("beads_parallel", "Bash", priority=4)
def check_beads_parallel(data: dict, state: SessionState) -> HookResult:
    """
    Nudge sequential beads (bd) commands toward parallel execution.

    PATTERN: Multiple bd create/update/close commands should be batched or parallelized.
    """
    global _BD_CACHE, _BD_CACHE_TURN

    tool_input = data.get("tool_input", {})
    command = tool_input.get("command", "")

    # Only care about beads commands
    if not re.search(r"\bbd\s+(create|update|close|dep)", command):
        return HookResult.approve()

    # Invalidate cache - bd state is changing
    _BD_CACHE = {}
    _BD_CACHE_TURN = 0

    # Track beads commands
    if not hasattr(state, "recent_beads_commands"):
        state.recent_beads_commands = []

    current_turn = state.turn_count

    # Clean old entries (older than 3 turns)
    state.recent_beads_commands = [
        cmd
        for cmd in state.recent_beads_commands
        if current_turn - cmd.get("turn", 0) <= 3
    ]

    # Check for sequential beads pattern
    recent_count = len(state.recent_beads_commands)

    # Record this command
    state.recent_beads_commands.append({"cmd": command[:50], "turn": current_turn})

    # Nudge after 2+ recent beads commands
    if recent_count >= 2:
        # Check if these could be batched
        if "bd close" in command:
            return HookResult.approve(
                "⚡ **BEADS BATCH**: Multiple bd commands detected. "
                "`bd close` supports multiple IDs: `bd close id1 id2 id3`. "
                "Batch operations are faster than sequential."
            )
        elif "bd create" in command:
            return HookResult.approve(
                "⚡ **BEADS PARALLEL**: Multiple bd create commands? "
                "Run them in parallel Bash calls in one message, or use Task agents with run_in_background."
            )

    return HookResult.approve()


# =============================================================================
# BEAD ENFORCEMENT (Priority 4) - Require in_progress bead for substantive work
# =============================================================================


def _auto_create_and_claim_bead(
    file_path: str, state: SessionState
) -> tuple[bool, str]:
    """Auto-create a bead from file context and claim it.

    Returns (success, message).
    """
    import subprocess
    from pathlib import Path

    bd_path = Path.home() / ".local" / "bin" / "bd"
    if not bd_path.exists():
        return False, "bd not found"

    # Extract title from file path
    path = Path(file_path)
    filename = path.stem
    parent = path.parent.name if path.parent.name not in (".", "") else ""

    # Generate descriptive title
    if parent:
        title = f"Work on {parent}/{filename}"
    else:
        title = f"Work on {filename}"

    # Limit title length
    title = title[:60]

    try:
        # Create bead
        result = subprocess.run(
            [str(bd_path), "create", f"--title={title}", "--type=task"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return False, f"create failed: {result.stderr}"

        # Extract bead ID from output (format: "Created: claude-xxxx")
        import re as regex

        match = regex.search(r"(claude-\w+)", result.stdout)
        if not match:
            return False, "could not parse bead ID"

        bead_id = match.group(1)

        # Claim the bead
        result = subprocess.run(
            [str(bd_path), "update", bead_id, "--status=in_progress"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return False, f"claim failed: {result.stderr}"

        # Track the auto-created bead
        if not hasattr(state, "auto_created_beads"):
            state.auto_created_beads = []
        state.auto_created_beads.append(bead_id)

        return True, f"📋 **Auto-created bead**: `{bead_id}` - {title}"

    except subprocess.TimeoutExpired:
        return False, "bd command timed out"
    except Exception as e:
        return False, str(e)


@register_hook("bead_enforcement", "Edit|Write", priority=4)
def check_bead_enforcement(data: dict, state: SessionState) -> HookResult:
    """
    Auto-manage bead tracking for substantive work.

    FULLY AUTOMATIC:
    - If no in_progress bead, auto-creates one from file context
    - Auto-claims the created bead
    - No manual bd commands needed

    SAFEGUARDS:
    - Skip patterns: .claude/, .git/, tmp/, etc. don't trigger
    - Trivial files: README, docs get tracked but don't block
    - Cascade protection: If bd fails repeatedly, degrade gracefully
    - SUDO bypass always available
    """
    # Lazy import - only load _beads when this hook runs
    from _beads import get_in_progress_beads, get_open_beads

    # SUDO bypass
    if data.get("_sudo_bypass"):
        return HookResult.approve()

    tool_input = data.get("tool_input", {})
    file_path = tool_input.get("file_path", "")

    if not file_path:
        return HookResult.approve()

    # === SKIP PATTERNS (always allowed, no tracking needed) ===
    skip_patterns = [
        r"\.claude/",
        r"\.git/",
        r"/tmp/",
        r"\.env",
        r"package-lock\.json",
        r"\.lock$",
        r"node_modules/",
        r"__pycache__/",
    ]
    if any(re.search(p, file_path) for p in skip_patterns):
        return HookResult.approve()

    # === CHECK FOR IN_PROGRESS BEADS ===
    in_progress = get_in_progress_beads(state)

    if in_progress:
        # Already tracking - all good
        if hasattr(state, "bead_enforcement_blocks"):
            state.bead_enforcement_blocks = 0
        return HookResult.approve()

    # No active bead - check if we have open beads to claim
    if not hasattr(state, "bead_enforcement_blocks"):
        state.bead_enforcement_blocks = 0

    open_beads = get_open_beads(state)

    # === AUTO-CLAIM: If open beads exist, claim the first one ===
    if open_beads:
        import subprocess
        from pathlib import Path

        bd_path = Path.home() / ".local" / "bin" / "bd"
        bead_id = open_beads[0].get("id", "")
        bead_title = open_beads[0].get("title", "untitled")[:40]

        if bd_path.exists() and bead_id:
            try:
                result = subprocess.run(
                    [str(bd_path), "update", bead_id, "--status=in_progress"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if result.returncode == 0:
                    return HookResult.approve(
                        f"📋 **Auto-claimed bead**: `{bead_id[:12]}` - {bead_title}"
                    )
            except Exception:
                pass

    # === AUTO-CREATE: No open beads, create one ===
    # Check for cascade/degraded mode
    if state.bead_enforcement_blocks >= 3:
        return HookResult.approve(
            "⚠️ **BEAD TRACKING**: Auto-management degraded (bd may be unavailable)"
        )

    success, message = _auto_create_and_claim_bead(file_path, state)

    if success:
        state.bead_enforcement_blocks = 0
        return HookResult.approve(message)
    else:
        state.bead_enforcement_blocks += 1
        # Don't block - degrade gracefully
        return HookResult.approve(
            f"⚠️ **BEAD AUTO-CREATE FAILED**: {message}. Continuing without tracking."
        )


# =============================================================================
# PARALLEL BEAD DELEGATION (Priority 3) - Force parallelism when beads ready
# =============================================================================


@register_hook("parallel_bead_delegation", "Task", priority=3)
def check_parallel_bead_delegation(data: dict, state: SessionState) -> HookResult:
    """
    Force parallel Task delegation when multiple beads are open.

    SAFEGUARDS:
    - Dependency check: Only suggests independent beads (no blockers)
    - Max 4 agents: Prevents overwhelming parallelism
    - Recency filter: Prioritizes recently updated beads
    - Generated structure: Provides copy-pasteable Task calls
    - Sequential detection: Uses shared counter with parallel_nudge

    NOTE: Does NOT update task_spawns_this_turn - parallel_nudge handles that.
    Uses consecutive_single_tasks for escalation (shared counter).
    """
    # Lazy import - only load _beads when this hook runs
    from _beads import get_independent_beads, generate_parallel_task_calls

    tool_input = data.get("tool_input", {})

    # Skip if already running in background or resuming
    if tool_input.get("run_in_background") or tool_input.get("resume"):
        return HookResult.approve()

    # Get independent beads (filtered for parallel work)
    independent_beads = get_independent_beads(state)
    bead_count = len(independent_beads)

    if bead_count < 2:
        return HookResult.approve()

    # Use shared counter - consecutive_single_tasks tracks sequential single-Task turns
    # This counter is managed by parallel_nudge (priority 4); we just read and escalate

    # Generate the parallel task structure
    task_structure = generate_parallel_task_calls(independent_beads)

    # Escalate based on shared sequential pattern counter
    # Note: parallel_nudge (priority 4) runs after us and updates the counter
    if state.consecutive_single_tasks >= 3:
        # HARD BLOCK after 3+ sequential singles with beads available
        return HookResult.deny(
            f"🚫 **PARALLEL REQUIRED**: {bead_count} beads ready. Spawn multiple Tasks in ONE message. SUDO to bypass.\n{task_structure}"
        )
    elif state.consecutive_single_tasks >= 2:
        # Strong nudge at 2
        return HookResult.approve(
            f"⚡ {bead_count} beads ready for parallel:\n{task_structure}"
        )
    elif bead_count >= 2:
        # Soft nudge when beads available
        bead_list = ", ".join(f"`{b.get('id', '?')[:12]}`" for b in independent_beads)
        return HookResult.approve(f"💡 Parallel: {bead_list}")

    return HookResult.approve()


# =============================================================================
# RECURSION GUARD (Priority 5) - Block catastrophic folder duplication
# =============================================================================


@register_hook("recursion_guard", "Edit|Write|Bash", priority=5)
def check_recursion_guard(data: dict, state: SessionState) -> HookResult:
    """Block catastrophic folder duplication."""

    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})

    RECURSIVE_PATTERNS = [
        r"\.claude/.*\.claude/",
        r"projects/[^/]+/projects/",
        r"\.claude/tmp/.*\.claude/tmp/",
    ]

    paths_to_check = []

    if tool_name in ("Write", "Edit"):
        file_path = tool_input.get("file_path", "")
        if file_path:
            paths_to_check.append(file_path)
    elif tool_name == "Bash":
        command = tool_input.get("command", "")
        # Strip heredoc content to avoid matching paths in heredoc body
        cmd_to_check = strip_heredoc_content(command)
        # Extract paths from mkdir, touch, cp, mv
        paths_to_check.extend(
            re.findall(r'mkdir\s+(?:-p\s+)?["\']?([^"\';\s&|]+)', cmd_to_check)
        )
        paths_to_check.extend(
            re.findall(r'["\']?(/[^"\';\s&|]+|\.claude/[^"\';\s&|]+)', cmd_to_check)
        )

    for path in paths_to_check:
        for pattern in RECURSIVE_PATTERNS:
            if re.search(pattern, path):
                return HookResult.deny(
                    f"🔁 **RECURSION CATASTROPHE BLOCKED**\n"
                    f"Path: {path}\n"
                    f"Use flat paths instead of nested duplicates."
                )
    return HookResult.approve()
