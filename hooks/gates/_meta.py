#!/usr/bin/env python3
"""
Meta/Recovery Gates - Framework self-regulation and caching hooks.

These gates handle framework-level concerns:
- Self-heal enforcement: Require fixing framework errors before other work
- FP fix enforcement: Require fixing false positives after fp.py
- Sunk cost detection: Warn about repeated failures
- Thinking coach: Analyze thinking blocks for reasoning flaws
- Read cache: Return cached file content if unchanged
- Exploration cache: Memoize Explore agent results

Extracted from pre_tool_use_runner.py for modularity.
"""

import re
from pathlib import Path

from session_state import SessionState
from ._common import register_hook, HookResult
from _logging import log_debug

# =============================================================================
# THINKING COACH PATTERNS
# =============================================================================

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
# EXPLORATION CACHE CONSTANTS
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


# =============================================================================
# FP FIX ENFORCER (Priority 1) - Require fixing false positives
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


# =============================================================================
# SELF-HEAL ENFORCER (Priority 2) - Fix framework errors first
# =============================================================================


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
# READ CACHE (Priority 2) - Return cached file content
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
# EXPLORATION CACHE (Priority 3) - Memoize Explore agent calls
# =============================================================================


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


# =============================================================================
# SUNK COST DETECTOR (Priority 80)
# =============================================================================


@register_hook("sunk_cost_detector", None, priority=80)
def check_sunk_cost(data: dict, state: SessionState) -> HookResult:
    """Detect sunk cost trap."""
    from session_state import check_sunk_cost as _check

    is_trapped, message = _check(state)
    if is_trapped:
        return HookResult.approve(message)
    return HookResult.approve()


# =============================================================================
# THINKING COACH (Priority 90) - Analyze thinking blocks for flaws
# =============================================================================


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
# THINKING SUGGESTER (Priority 91) - Inject tool suggestions based on thinking
# =============================================================================


@register_hook("thinking_suggester", None, priority=91)
def check_thinking_suggester(data: dict, state: SessionState) -> HookResult:
    """
    Analyze thinking blocks to surface relevant tools and capabilities.

    Complements thinking_coach by providing proactive suggestions
    rather than just warnings about flaws.
    """
    from _thinking_suggester import check_thinking_suggestions

    # Delegate to the dedicated module
    return check_thinking_suggestions(data, state, {})
