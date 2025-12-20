"""
Memory Integration - claude-mem awareness in the hook system.

Enhances hook context to suggest memory queries when appropriate:
1. Stuck loop assistance - suggest searching memory for past solutions
2. Pre-edit awareness - remind about memory when editing problem files

The actual memory queries are performed by Claude using MCP tools.
This module injects helpful suggestions and the stuck loop module
tracks when memory tools are used (via RESEARCH_TOOLS).

Priority range: 75-79 (runs before circuit breaker at 82)
"""

import _lib_path  # noqa: F401
from pathlib import Path

from _hook_registry import register_hook
from _hook_result import HookResult
from _cooldown import is_on_cooldown, reset_cooldown
from session_state import SessionState

# =============================================================================
# CONFIGURATION
# =============================================================================

# Cooldowns to prevent suggestion spam
MEMORY_SUGGEST_COOLDOWN = 12
PREFLIGHT_SUGGEST_COOLDOWN = 15

# Symptom to query mapping for more targeted suggestions
SYMPTOM_QUERIES: dict[str, str] = {
    "blank_page": "blank page rendering issue",
    "not_rendering": "component not rendering",
    "hydration_issue": "hydration error React Next.js",
    "auth_issue": "authentication login error",
    "state_persistence": "state not persisting",
    "redirect_issue": "redirect loop login",
    "null_error": "null undefined TypeError",
    "timeout": "timeout connection error",
    "cors_issue": "CORS cross-origin error",
    "not_found": "404 not found error",
    "server_error": "500 server error",
    "type_error": "TypeError cannot read property",
}


def _format_memory_suggestion(
    symptoms: list[tuple[str, int, str]], file_path: str | None = None
) -> str:
    """Format a suggestion to query memory for past solutions."""
    lines = ["📎 **Check Memory for Prior Art**:\n"]

    # Build suggested queries based on symptoms
    if symptoms:
        recent_symptom = symptoms[-1][0]
        query_hint = SYMPTOM_QUERIES.get(
            recent_symptom, recent_symptom.replace("_", " ")
        )

        lines.append(f"   Suggested query: `{query_hint}`\n")
        lines.append("   ```")
        lines.append(
            f'   mcp__mem-search__search(query="{query_hint}", obs_type="bugfix")'
        )
        lines.append("   ```\n")

    if file_path:
        file_name = Path(file_path).name
        lines.append(f'   Or search by file: `files="{file_name}"`\n')

    lines.append("💡 Memory search is faster than web search - try it first!")
    lines.append("   Past solutions may already exist for this exact issue.")

    return "\n".join(lines)


def _format_file_reminder(file_path: str) -> str:
    """Format a reminder about checking file history."""
    file_name = Path(file_path).name

    return (
        f"📎 **Memory Available**: Consider checking history for `{file_name}`\n"
        f"   ```\n"
        f'   mcp__mem-search__search(files="{file_name}", obs_type="bugfix")\n'
        f"   ```\n"
        f"💡 Past issues with this file may have documented solutions"
    )


# =============================================================================
# HOOK: MEMORY SUGGESTION FOR STUCK LOOPS (priority 79)
# Runs BEFORE circuit breaker (82) to suggest memory search first
# =============================================================================


@register_hook("memory_suggestion", "Edit|Write", priority=79)
def suggest_memory_search(
    data: dict, state: SessionState, runner_state: dict
) -> HookResult:
    """Suggest memory search when stuck signals are detected.

    This hook runs before the circuit breaker to remind about memory
    as a faster alternative to web search.
    """
    stuck = runner_state.get("stuck_loop_state", {})

    symptoms_seen = stuck.get("symptoms_seen", [])
    fix_attempts = stuck.get("fix_attempts", {})

    # Need at least 2 symptoms or 2+ fix attempts on any file
    has_symptoms = len(symptoms_seen) >= 2
    has_attempts = any(len(attempts) >= 2 for attempts in fix_attempts.values())

    if not has_symptoms and not has_attempts:
        return HookResult.none()

    # Skip if research was done recently
    if stuck.get("research_done", False):
        turns_since = state.turn_count - stuck.get("last_research_turn", 0)
        if turns_since < 5:
            return HookResult.none()

    # Check cooldown
    cooldown_key = "memory_suggestion"
    if is_on_cooldown(cooldown_key, MEMORY_SUGGEST_COOLDOWN):
        return HookResult.none()

    tool_input = data.get("tool_input", {})
    file_path = tool_input.get("file_path", "")

    reset_cooldown(cooldown_key)
    context = _format_memory_suggestion(symptoms_seen, file_path)

    return HookResult.with_context(context)


# =============================================================================
# HOOK: PRE-EDIT MEMORY REMINDER (priority 76)
# Gentle reminder about memory for files being edited multiple times
# =============================================================================

REMINDER_EXEMPT_PATTERNS = (
    "/.claude/tmp/",
    "/.claude/plans/",
    "/test",
    "/tests/",
    "_test.py",
    ".test.",
    "CLAUDE.md",
    "/.serena/",
)


@register_hook("memory_reminder", "Edit|Write", priority=76)
def remind_about_memory(
    data: dict, state: SessionState, runner_state: dict
) -> HookResult:
    """Remind about memory search for files being edited repeatedly."""
    tool_input = data.get("tool_input", {})
    file_path = tool_input.get("file_path", "")

    if not file_path:
        return HookResult.none()

    if any(pattern in file_path for pattern in REMINDER_EXEMPT_PATTERNS):
        return HookResult.none()

    # Track file edit counts
    file_edits = runner_state.setdefault("file_edit_counts", {})
    file_name = Path(file_path).name
    edit_count = file_edits.get(file_name, 0) + 1
    file_edits[file_name] = edit_count

    # Only remind after 2+ edits
    if edit_count < 2:
        return HookResult.none()

    cooldown_key = f"memory_reminder_{file_name}"
    if is_on_cooldown(cooldown_key, PREFLIGHT_SUGGEST_COOLDOWN):
        return HookResult.none()

    # Only on 2nd and 4th edit
    if edit_count not in (2, 4):
        return HookResult.none()

    reset_cooldown(cooldown_key)
    return HookResult.with_context(_format_file_reminder(file_path))


# =============================================================================
# HELPER: PROMPT ENRICHMENT (for user_prompt_submit integration)
# =============================================================================

DEBUG_INDICATORS = frozenset(
    [
        "fix",
        "bug",
        "error",
        "broken",
        "not working",
        "doesn't work",
        "failed",
        "issue",
        "problem",
        "debug",
    ]
)


def get_memory_prompt_hint(prompt_text: str) -> str | None:
    """Generate a hint about using memory search for debugging prompts.

    Returns:
        Hint string or None if not a debug prompt
    """
    if not prompt_text or len(prompt_text) < 20:
        return None

    prompt_lower = prompt_text.lower()
    is_debug = any(indicator in prompt_lower for indicator in DEBUG_INDICATORS)

    if not is_debug:
        return None

    query_hint = prompt_text[:50].strip()
    if len(prompt_text) > 50:
        query_hint = query_hint.rsplit(" ", 1)[0] + "..."

    return (
        f"📎 **Memory Tip**: Check if this was solved before\n"
        f'   `mcp__mem-search__search(query="{query_hint}")`'
    )
