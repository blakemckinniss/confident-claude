#!/usr/bin/env python3
"""
_prompt_thinking.py - Inject relevant past thinking into prompts (Priority 42).

This hook runs on UserPromptSubmit and injects relevant metacognitive context
from past sessions when the current prompt matches stored thinking patterns.

The goal is to give Claude "memory of how it reasoned" - not just what was done,
but the problem decomposition, hypotheses tested, and solutions synthesized.

Priority 42: After memory injector (40) but before context injector (45).
"""

import _lib_path  # noqa: F401
import re
from typing import List

from _prompt_registry import register_hook
from _hook_result import HookResult
from session_state import SessionState

try:
    from thinking_memory import (
        get_relevant_thinking_for_prompt,
        search_thinking_records,
        THINKING_INDEX_PATH,
    )
    THINKING_AVAILABLE = True
except ImportError:
    THINKING_AVAILABLE = False

# Configuration
MIN_PROMPT_LENGTH = 30  # Don't search for very short prompts
MIN_RELEVANCE_SCORE = 20  # Minimum score to inject thinking
MAX_INJECTION_CHARS = 1200  # Keep injection concise
COOLDOWN_TURNS = 8  # Don't inject every turn


def _should_inject_thinking(prompt: str, state: SessionState) -> bool:
    """Determine if we should inject thinking for this prompt."""
    if not THINKING_AVAILABLE:
        return False

    if not THINKING_INDEX_PATH.exists():
        return False

    # Skip short prompts
    if len(prompt) < MIN_PROMPT_LENGTH:
        return False

    # Skip if just a command
    if prompt.strip().startswith("/"):
        return False

    # Check cooldown using state
    last_injection = getattr(state, "last_thinking_injection_turn", 0)
    current_turn = getattr(state, "turn_count", 0)
    if current_turn - last_injection < COOLDOWN_TURNS:
        return False

    # Skip trivial requests
    trivial_patterns = [
        r"^(yes|no|ok|thanks|thank you|sure|got it)",
        r"^(commit|push|deploy|run|test|build)\s*$",
        r"^(SUDO|FP:|dispute)",
    ]
    prompt_lower = prompt.lower().strip()
    if any(re.match(p, prompt_lower, re.I) for p in trivial_patterns):
        return False

    return True


def _get_current_files_from_state(state: SessionState) -> List[str]:
    """Extract files from session state for relevance matching."""
    files = []

    # From recent edits
    recent_edits = getattr(state, "recent_edits", [])
    if isinstance(recent_edits, list):
        files.extend(recent_edits[:10])

    # From working context
    working_files = getattr(state, "working_files", [])
    if isinstance(working_files, list):
        files.extend(working_files[:10])

    return list(set(files))


def _format_thinking_injection(thinking_context: str) -> str:
    """Format the thinking context for injection."""
    if not thinking_context:
        return ""

    return f"""<thinking-memory>
{thinking_context}
</thinking-memory>

*Past reasoning patterns may inform your approach.*
"""


@register_hook("thinking_memory_injection", priority=42)
def check_thinking_memory_injection(data: dict, state: SessionState) -> HookResult:
    """Inject relevant past thinking when prompt matches stored patterns."""
    prompt = data.get("message", "")
    if not prompt:
        return HookResult.approve()

    if not _should_inject_thinking(prompt, state):
        return HookResult.approve()

    try:
        current_files = _get_current_files_from_state(state)

        # Get relevant thinking
        thinking_context = get_relevant_thinking_for_prompt(
            user_prompt=prompt,
            current_files=current_files,
            max_records=2,  # Keep it focused
        )

        if not thinking_context:
            return HookResult.approve()

        # Verify we have a sufficiently relevant match
        records = search_thinking_records(
            query=prompt,
            files=current_files,
            limit=1,
        )

        if not records or records[0].relevance_score < MIN_RELEVANCE_SCORE:
            return HookResult.approve()

        # Format for injection
        injection = _format_thinking_injection(thinking_context)

        # Truncate if too long
        if len(injection) > MAX_INJECTION_CHARS:
            injection = injection[:MAX_INJECTION_CHARS] + "\n...</thinking-memory>\n"

        # Update state to track injection
        state.last_thinking_injection_turn = getattr(state, "turn_count", 0)
        state.thinking_injections_count = getattr(state, "thinking_injections_count", 0) + 1

        return HookResult.approve(context=injection)

    except Exception:
        # Fail silently - thinking injection is optional
        return HookResult.approve()
