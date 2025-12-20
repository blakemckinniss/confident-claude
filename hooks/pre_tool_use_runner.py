#!/usr/bin/env python3
"""
Composite PreToolUse Runner: Runs all PreToolUse hooks in a single process.

PERFORMANCE: ~35ms for 24 hooks vs ~400ms for individual processes (10x faster)

HOOKS INDEX (by priority):
  ORCHESTRATION (0-5):
    1  fp_fix_enforcer     - HARD BLOCK until false positive is fixed (Hard Block #14)
    2  self_heal_enforcer  - Block unrelated work until framework errors fixed
    3  exploration_cache   - Return cached exploration results
    3  parallel_bead_delegation - Force parallel Task agents for multiple open beads
    4  parallel_nudge      - Nudge sequential Task spawns → parallel + background
    4  beads_parallel      - Nudge sequential bd commands → batch/parallel
    4  bead_enforcement    - Require in_progress bead before Edit/Write

  SAFETY (5-20):
    5  recursion_guard     - Block nested .claude/.claude paths
    10 loop_detector       - Block bash loops
    14 inline_server_background - Block server & curl/sleep patterns
    15 background_enforcer - Require background for slow commands
    18 confidence_tool_gate - Block tools at low confidence levels

  GATES (20-50):
    20 commit_gate         - Warn on git commit without upkeep
    25 tool_preference     - Nudge toward preferred tools
    30 oracle_gate         - Enforce think/council after failures
    32 confidence_external_suggestion - Suggest alternatives at low confidence
    35 integration_gate    - Require grep after function edits
    40 error_suppression   - Block until errors resolved
    45 content_gate        - Block eval/exec/SQL injection
    47 crawl4ai_preference - Suggest crawl4ai over WebFetch
    50 gap_detector        - Block edit without read

  QUALITY (55-95):
    55 production_gate     - Audit/void for .claude/ops writes
    60 deferral_gate       - Block "TODO: later" comments
    65 doc_theater_gate    - Block standalone .md files
    70 root_pollution_gate - Block home directory clutter
    75 recommendation_gate - Warn on duplicate infrastructure
    80 security_claim_gate - Warn on security-sensitive code
    85 epistemic_boundary  - Warn on unverified identifiers
    88 research_gate       - Block unverified libraries
    92 import_gate         - Warn on third-party imports
    95 modularization_nudge- Occasional modularization reminder
    96 curiosity_injection - Metacognitive prompts before major edits

  SESSION (80-90):
    80 sunk_cost_detector  - Detect failure loops
    90 thinking_coach      - Detect reasoning flaws

ARCHITECTURE:
  - Hooks register via @register_hook(name, matcher, priority)
  - Lower priority = runs first
  - First DENY wins, contexts are aggregated
  - Single state load/save per invocation
"""

import _lib_path  # noqa: F401
import sys
import json
import os
import re
import time
from pathlib import Path
from typing import Optional, Callable

# PERFORMANCE: Minimal top-level imports. Heavy modules loaded lazily inside hooks.
# This reduces import time from ~55ms to ~20ms per invocation.

# Core session state - needed for run_hooks orchestration
from session_state import (
    load_state,
    save_state,
    SessionState,
    track_block,
    clear_blocks,
    check_cascade_failure,
)
from _hook_result import HookResult
from _logging import log_debug

# LAZY IMPORTS - These are loaded inside hooks that need them:
# - confidence (check_tool_permission, get_tier_info) -> confidence_tool_gate, homeostatic_drive, threat_anticipation
# - _beads (get_open_beads, etc.) -> bead_enforcement, parallel_bead_delegation
# - _confidence_constants -> homeostatic_drive, threat_anticipation
# - _confidence_streaks -> threat_anticipation

# =============================================================================
# MODULE-LEVEL STATE (for hooks that need cross-invocation caching)
# =============================================================================
_BD_CACHE: dict = {}  # Beads cache for beads_parallel hook
_BD_CACHE_TURN: int = 0  # Turn when cache was last valid


# =============================================================================
# SHARED HELPERS
# =============================================================================

# NOTE: _detect_serena_project moved to hooks/gates/_serena.py

# =============================================================================
# Thinking coach flaw patterns
_FLAW_PATTERNS = [
    (re.compile(r"(don't|no) need to (read|check|verify)", re.IGNORECASE), "shortcut"),
    (re.compile(r"I (assume|believe) (the|this)", re.IGNORECASE), "assumption"),
    (
        re.compile(
            r"(this|that) (should|will) (definitely\s+)?(work|fix)", re.IGNORECASE
        ),
        "overconfidence",
    ),
]

# =============================================================================
# HOOK REGISTRY
# =============================================================================

# Format: (name, matcher_pattern, check_function, priority)
# Lower priority = runs first. Blocks stop execution.
# matcher_pattern: None = all tools, str = regex pattern
HOOKS: list[tuple[str, Optional[str], Callable, int]] = []


def register_hook(name: str, matcher: Optional[str], priority: int = 50):
    """Decorator to register a hook check function.

    Hooks can be disabled via environment variable:
        CLAUDE_HOOK_DISABLE_<NAME>=1

    Example:
        CLAUDE_HOOK_DISABLE_CONTENT_GATE=1 claude
    """

    def decorator(func: Callable[[dict, SessionState], HookResult]):
        # Check if hook is disabled via environment variable
        env_key = f"CLAUDE_HOOK_DISABLE_{name.upper()}"
        if os.environ.get(env_key, "0") == "1":
            return func  # Skip registration
        HOOKS.append((name, matcher, func, priority))
        return func

    return decorator


# =============================================================================
# IMPORT MODULAR GATES
# =============================================================================
# Gates are being extracted to hooks/gates/ for better organization.
# Import them here so their @register_hook decorators execute.
from gates import HOOKS as GATES_HOOKS  # noqa: E402
from gates._bash import strip_heredoc_content  # noqa: E402

HOOKS.extend(GATES_HOOKS)

# =============================================================================
# HOOK IMPLEMENTATIONS (remaining inline hooks)
# =============================================================================


@register_hook("sunk_cost_detector", None, priority=80)
def check_sunk_cost(data: dict, state: SessionState) -> HookResult:
    """Detect sunk cost trap."""
    from session_state import check_sunk_cost as _check

    is_trapped, message = _check(state)
    if is_trapped:
        return HookResult.approve(message)
    return HookResult.approve()


@register_hook("thinking_coach", None, priority=90)
def check_thinking_coach(data: dict, state: SessionState) -> HookResult:
    """Analyze thinking blocks for reasoning flaws."""
    from synapse_core import extract_thinking_blocks

    tool_name = data.get("tool_name", "")
    transcript_path = data.get("transcript_path", "")

    # Skip for read-only tools
    if tool_name in {"Read", "Glob", "Grep", "TodoWrite", "BashOutput"}:
        return HookResult.approve()

    if not transcript_path:
        return HookResult.approve()

    thinking_blocks = extract_thinking_blocks(transcript_path)
    if not thinking_blocks:
        return HookResult.approve()

    # Quick pattern check
    combined = " ".join(thinking_blocks[-2:])[-1000:]

    # Use pre-compiled patterns from module level
    for pattern, flaw_type in _FLAW_PATTERNS:
        if pattern.search(combined):
            return HookResult.approve(
                f"⚠️ THINKING COACH: Detected `{flaw_type}` pattern. Verify before proceeding."
            )
    return HookResult.approve()


# =============================================================================
# READ CACHE (Priority 2) - Memoize file reads
# =============================================================================


@register_hook("read_cache", "Read", priority=2)
def check_read_cache(data: dict, state: SessionState) -> HookResult:
    """
    Return cached file content if file hasn't changed.

    Uses mtime-based validation for fast checks.
    Invalidated by Write/Edit hooks in post_tool_use_runner.
    """
    tool_input = data.get("tool_input", {})
    file_path = tool_input.get("file_path", "")

    if not file_path:
        return HookResult.approve()

    # Check for partial reads - don't cache those
    if tool_input.get("offset") or tool_input.get("limit"):
        return HookResult.approve()

    try:
        from cache.read_cache import check_read_cache as get_cached

        cached_content = get_cached(file_path)
        if cached_content:
            # Return cached content as context
            from pathlib import Path

            filename = Path(file_path).name
            return HookResult.approve_with_context(
                f"📦 **CACHED READ** ({filename})\n"
                f"File unchanged since last read. Cached content:\n\n"
                f"```\n{cached_content[:50000]}\n```\n"
                f"_(Use `fresh` in prompt to force re-read)_"
            )
    except Exception as e:
        log_debug("pre_tool_use_runner", f"read cache lookup failed: {e}")
    return HookResult.approve()


# =============================================================================
# SELF-HEAL ENFORCER (Priority 2) - Framework must fix itself first
# =============================================================================


@register_hook("fp_fix_enforcer", None, priority=1)
def check_fp_fix_enforcer(data: dict, state: SessionState) -> HookResult:
    """
    HARD BLOCK: Enforce fixing false positives before continuing work.

    When fp.py is run, it sets state.fp_pending_fix. This hook blocks ALL
    non-diagnostic work until either:
    1. The reducer/hook file is edited (fix attempt)
    2. User says SUDO (bypass)
    3. 15 turns pass (timeout - probably session context lost)

    This implements Hard Block #14: FP = Priority 0.
    """
    pending = getattr(state, "fp_pending_fix", None)
    if not pending:
        return HookResult.approve()

    # SUDO bypass
    if data.get("_sudo_bypass"):
        state.fp_pending_fix = None
        return HookResult.approve()

    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})

    # Always allow investigation tools
    if tool_name in ("Read", "Grep", "Glob", "LS", "WebSearch", "WebFetch"):
        return HookResult.approve()

    # Check if editing the fix targets (reducer or hook files)
    if tool_name in ("Edit", "Write"):
        file_path = tool_input.get("file_path", "")
        fix_targets = [
            "_confidence_reducers.py",
            "_confidence_increasers.py",
            "pre_tool_use_runner.py",
            "post_tool_use_runner.py",
            "_hooks_state.py",
        ]
        if any(t in file_path for t in fix_targets):
            # This is a fix attempt - clear the pending state
            state.fp_pending_fix = None
            return HookResult.approve(
                "✅ **FP FIX ATTEMPT** - Editing reducer/hook file. Pending fix cleared."
            )

    # Timeout after 15 turns (context probably lost)
    turns_since = state.turn_count - pending.get("turn", 0)
    if turns_since > 15:
        state.fp_pending_fix = None
        return HookResult.approve(
            "⚠️ FP fix timeout (15 turns) - clearing pending state"
        )

    # BLOCK everything else
    reducer = pending.get("reducer", "unknown")
    reason = pending.get("reason", "")

    return HookResult.deny(
        f"🚨 **FP FIX REQUIRED** (Hard Block #14)\n"
        f"Reducer: `{reducer}`\n"
        f"Reason: {reason[:80] if reason else 'Not specified'}\n\n"
        f"**You ran fp.py but didn't fix the root cause.**\n"
        f"Edit `lib/_confidence_reducers.py` or the hook that fired.\n"
        f"User: Say SUDO to bypass."
    )


@register_hook("self_heal_enforcer", None, priority=2)
def check_self_heal_enforcer(data: dict, state: SessionState) -> HookResult:
    """
    Block unrelated work when framework self-heal is required.

    TRIGGER: When a tool fails on .claude/ paths, self_heal_required is set.
    BEHAVIOR:
      - Attempts 1-2: Nudge toward fixing the framework error
      - Attempt 3: Hard block with escalation to user
    ALLOWED: Read, Grep, Glob (investigation), and operations on .claude/ paths
    BYPASS: SUDO clears self-heal requirement
    """
    if not getattr(state, "self_heal_required", False):
        return HookResult.approve()

    # SUDO bypass - clear self-heal and continue
    if data.get("_sudo_bypass"):
        state.self_heal_required = False
        state.self_heal_target = ""
        state.self_heal_error = ""
        state.self_heal_attempts = 0
        return HookResult.approve()

    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})

    # Always allow investigation tools
    if tool_name in ("Read", "Grep", "Glob", "LS"):
        return HookResult.approve()

    # Always allow operations targeting .claude/ (self-heal attempts)
    target_path = ""
    if tool_name == "Edit":
        target_path = tool_input.get("file_path", "")
    elif tool_name == "Write":
        target_path = tool_input.get("file_path", "")
    elif tool_name == "Bash":
        target_path = tool_input.get("command", "")

    if ".claude/" in target_path or ".claude\\" in target_path:
        # Track attempt
        state.self_heal_attempts = getattr(state, "self_heal_attempts", 0) + 1
        return HookResult.approve()

    # Unrelated work - escalate based on attempts
    attempts = getattr(state, "self_heal_attempts", 0)
    target = getattr(state, "self_heal_target", "unknown")
    error = getattr(state, "self_heal_error", "unknown error")
    max_attempts = getattr(state, "self_heal_max_attempts", 3)

    if attempts >= max_attempts:
        # Hard block - escalate to user
        return HookResult.deny(
            f"🚨 **SELF-HEAL BLOCKED** ({attempts}/{max_attempts}): `{target}` - {error[:80]}. Fix or SUDO."
        )

    # Soft nudge - remind but allow
    return HookResult.approve(
        f"⚠️ Self-heal ({attempts + 1}/{max_attempts}): `{target}` - {error[:60]}"
    )


# =============================================================================
# EXPLORATION CACHE (Priority 3) - Memoize Explore agent calls
# =============================================================================


_CACHE_BYPASS_KEYWORDS = frozenset(["force", "fresh", "re-explore", "bypass cache"])
_GROUNDING_KEYWORDS = (
    "tech stack",
    "framework",
    "what is this project",
    "project structure",
    "dependencies",
    "entry point",
    "how is this project",
    "what does this project use",
)


def _check_grounding_cache(prompt_lower: str, project_path: str) -> str | None:
    """Check grounding cache for common grounding queries."""
    if not any(kw in prompt_lower for kw in _GROUNDING_KEYWORDS):
        return None
    try:
        from cache.grounding_analyzer import get_or_create_grounding

        grounding = get_or_create_grounding(Path(project_path))
        return grounding.to_markdown() if grounding else None
    except Exception:
        return None


@register_hook("exploration_cache", "Task", priority=3)
def check_exploration_cache(data: dict, state: SessionState) -> HookResult:
    """Return cached exploration results for Explore agents."""
    tool_input = data.get("tool_input", {})
    if tool_input.get("subagent_type", "").lower() != "explore":
        return HookResult.approve()

    prompt = tool_input.get("prompt", "")
    if not prompt:
        return HookResult.approve()

    prompt_lower = prompt.lower()
    if any(kw in prompt_lower for kw in _CACHE_BYPASS_KEYWORDS):
        return HookResult.approve()

    try:
        from project_detector import detect_project

        project_info = detect_project()
        if not project_info or not project_info.get("path"):
            return HookResult.approve()
        project_path = project_info["path"]
    except Exception:
        return HookResult.approve()

    # Check exploration cache
    try:
        from cache.exploration_cache import check_exploration_cache as get_cached

        if cached := get_cached(project_path, prompt):
            return HookResult.approve(cached)
    except Exception as e:
        log_debug("pre_tool_use_runner", f"exploration cache lookup failed: {e}")

    # Check grounding cache
    if grounding := _check_grounding_cache(prompt_lower, project_path):
        return HookResult.approve(grounding)

    return HookResult.approve()


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
# BEAD-ENFORCED PARALLEL WORKFLOW
# =============================================================================


@register_hook("bead_enforcement", "Edit|Write", priority=4)
def check_bead_enforcement(data: dict, state: SessionState) -> HookResult:
    """
    Enforce bead tracking for substantive work.

    HARD BLOCKS Edit/Write on project files without an in_progress bead.

    SAFEGUARDS:
    - Grace period: First 2 turns of session get nudge, not block
    - Trivial files: README, CHANGELOG, docs skip blocking
    - Cascade protection: If bd binary fails, degrade to nudge
    - Small edits: Single-line changes get nudge, not block
    - SUDO bypass always available
    """
    # Lazy import - only load _beads when this hook runs
    from _beads import get_in_progress_beads, get_open_beads

    # SUDO bypass
    if data.get("_sudo_bypass"):
        return HookResult.approve()

    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})
    file_path = tool_input.get("file_path", "")

    if not file_path:
        return HookResult.approve()

    # === SKIP PATTERNS (always allowed) ===
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

    # === TRIVIAL FILE PATTERNS (nudge only, no block) ===
    trivial_patterns = [
        r"README",
        r"CHANGELOG",
        r"LICENSE",
        r"\.md$",  # Markdown docs
        r"\.txt$",  # Plain text
        r"\.json$",  # Config files
        r"\.ya?ml$",  # YAML config
        r"\.toml$",  # TOML config
    ]
    is_trivial = any(re.search(p, file_path, re.IGNORECASE) for p in trivial_patterns)

    # === SMALL EDIT CHECK (for Edit tool) ===
    is_small_edit = False
    if tool_name == "Edit":
        old_string = tool_input.get("old_string", "")
        new_string = tool_input.get("new_string", "")
        # Small edit = less than 5 lines changed
        old_lines = len(old_string.split("\n"))
        new_lines = len(new_string.split("\n"))
        is_small_edit = max(old_lines, new_lines) <= 5

    # === GRACE PERIOD (first 2 turns) ===
    is_grace_period = state.turn_count <= 2

    # === CHECK FOR IN_PROGRESS BEADS ===
    in_progress = get_in_progress_beads(state)

    if in_progress:
        # Reset enforcement counter - user is tracking work properly
        if hasattr(state, "bead_enforcement_blocks"):
            state.bead_enforcement_blocks = 0
        return HookResult.approve()

    # No active bead - determine enforcement level
    # Track enforcement attempts for cascade detection
    if not hasattr(state, "bead_enforcement_blocks"):
        state.bead_enforcement_blocks = 0

    # === DEGRADED MODE (bd binary failed or cascade) ===
    open_beads = get_open_beads(state)
    bd_failed = open_beads == [] and state.bead_enforcement_blocks >= 3

    if bd_failed:
        # bd might be broken - degrade to nudge
        return HookResult.approve(
            "⚠️ **BEAD TRACKING**: Consider `bd create` for tracking. "
            "(Degraded mode - bd may be unavailable)"
        )

    # === SOFT ENFORCEMENT (nudge only) ===
    if is_grace_period or is_trivial or is_small_edit:
        return HookResult.approve(
            "💡 **BEAD RECOMMENDED**: No in_progress bead. Consider:\n"
            '1. `bd create --title="..." --type=task`\n'
            "2. `bd update <id-from-output> --status=in_progress`"
        )

    # === HARD BLOCK ===
    state.bead_enforcement_blocks = state.bead_enforcement_blocks + 1

    return HookResult.deny(
        '🚫 **BEAD REQUIRED**: Run `bd create --title="..."` then `bd update <id> --status=in_progress` (separate calls). SUDO to bypass.'
    )


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


# NOTE: Serena gates (check_serena_activation_gate, check_code_tools_require_serena)
# moved to hooks/gates/_serena.py - imported via gates package above


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


# NOTE: Confidence system gates (homeostatic_drive, threat_anticipation,
#       confidence_tool_gate, oracle_gate, confidence_external_suggestion,
#       integration_gate, error_suppression_gate)
# moved to hooks/gates/_confidence.py - imported via gates package above

# NOTE: Content gates (content_gate, god_component_gate, gap_detector, production_gate,
#       deferral_gate, doc_theater_gate, root_pollution_gate, recommendation_gate,
#       security_claim_gate, epistemic_boundary, research_gate, import_gate,
#       modularization_nudge, curiosity_injection, crawl4ai_preference)
# moved to hooks/gates/_content.py - imported via gates package above

# =============================================================================
# MAIN RUNNER
# =============================================================================

# Pre-built lookup for fast hook filtering (built after HOOKS.sort())
HOOKS_BY_TOOL: dict[str, list] = {}  # Populated by _build_hook_index()
_HOOK_MATCHERS: dict[str, re.Pattern] = {}  # Pre-compiled regex patterns


def _build_hook_index():
    """Build optimized hook lookup index at module load.

    Creates:
    - _HOOK_MATCHERS: Pre-compiled regex for each unique matcher
    - HOOKS_BY_TOOL["__all__"]: Hooks that match all tools (matcher=None)
    """
    global HOOKS_BY_TOOL, _HOOK_MATCHERS
    HOOKS_BY_TOOL = {"__all__": []}
    _HOOK_MATCHERS = {}

    for hook in HOOKS:
        name, matcher, check_func, priority = hook
        if matcher is None:
            HOOKS_BY_TOOL["__all__"].append(hook)
        elif matcher not in _HOOK_MATCHERS:
            # Pre-compile regex pattern
            _HOOK_MATCHERS[matcher] = re.compile(f"^({matcher})$")


def _get_hooks_for_tool(tool_name: str) -> list:
    """Get applicable hooks for a tool, using cached lookup when possible."""
    if tool_name not in HOOKS_BY_TOOL:
        # Build list for this tool on first access
        applicable = list(HOOKS_BY_TOOL["__all__"])  # Start with "match all" hooks

        for hook in HOOKS:
            name, matcher, check_func, priority = hook
            if matcher is None:
                continue  # Already included in __all__
            # Use pre-compiled pattern
            pattern = _HOOK_MATCHERS.get(matcher)
            if pattern and pattern.match(tool_name):
                applicable.append(hook)

        # Sort by priority (should already be sorted, but ensure)
        applicable.sort(key=lambda x: x[3])
        HOOKS_BY_TOOL[tool_name] = applicable

    return HOOKS_BY_TOOL[tool_name]


def matches_tool(matcher: Optional[str], tool_name: str) -> bool:
    """Check if tool matches the hook's matcher pattern."""
    if matcher is None:
        return True
    return bool(re.match(f"^({matcher})$", tool_name))


def run_hooks(data: dict, state: SessionState) -> dict:
    """Run all applicable hooks and return aggregated result."""
    # Clear integration cache at start of each hook run to avoid stale detection
    # (e.g., Serena availability from a previous project directory)
    from _integration import clear_cache as clear_integration_cache

    clear_integration_cache()

    tool_name = data.get("tool_name", "")

    # Pre-compute SUDO bypass once for all hooks (avoids 18 redundant transcript reads)
    transcript_path = data.get("transcript_path", "")
    if transcript_path:
        from synapse_core import check_sudo_in_transcript

        data["_sudo_bypass"] = check_sudo_in_transcript(transcript_path)
    else:
        data["_sudo_bypass"] = False

    # Use pre-filtered hook list (built at module load, cached per tool name)
    applicable_hooks = _get_hooks_for_tool(tool_name)

    # Collect results
    contexts = []

    for name, matcher, check_func, priority in applicable_hooks:
        try:
            result = check_func(data, state)

            # First deny wins - but check for cascade failure first
            if result.decision == "deny":
                # Track this block for cascade detection
                track_block(state, name)

                # Check if we're in a cascade failure state
                is_cascade, escalation_msg = check_cascade_failure(state, name)
                if is_cascade:
                    # Allow with escalation instead of hard block
                    contexts.append(
                        f"⚠️ **CASCADE DETECTED** ({name} blocked 3+ times):\n"
                        f"{result.reason}\n\n{escalation_msg}"
                    )
                    # Don't return deny - let the operation through with warning
                    continue

                return {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "deny",
                        "permissionDecisionReason": result.reason,
                    }
                }

            # Clear cascade tracking on successful hook pass
            clear_blocks(state, name)

            # Collect contexts
            if result.context:
                contexts.append(result.context)

        except Exception as e:
            # Log error but don't block
            print(f"[runner] Hook {name} error: {e}", file=sys.stderr)

    # Build output
    output = {"hookSpecificOutput": {"hookEventName": "PreToolUse"}}
    if contexts:
        output["hookSpecificOutput"]["additionalContext"] = "\n\n".join(contexts[:3])

    return output


# Pre-sort hooks by priority at module load (avoid re-sorting on every call)
HOOKS.sort(key=lambda x: x[3])

# Build optimized hook index after sorting
_build_hook_index()


def main():
    """Main entry point."""
    start = time.time()

    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse"}}))
        sys.exit(0)

    # Single state load
    state = load_state()

    # Run all hooks
    result = run_hooks(data, state)

    # Single state save
    save_state(state)

    # Output result
    print(json.dumps(result))

    # Debug timing (to stderr)
    elapsed = (time.time() - start) * 1000
    if elapsed > 50:
        print(f"[runner] Slow: {elapsed:.1f}ms", file=sys.stderr)

    sys.exit(0)


if __name__ == "__main__":
    main()
