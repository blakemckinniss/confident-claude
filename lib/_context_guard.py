#!/usr/bin/env python3
"""
Context Guard v1.0 - Proactive context window exhaustion safeguard.

ARCHITECTURE:
  1. Stop hook (priority 1) → Sets context_guard_active after first run
  2. UserPromptSubmit hook (priority 1) → Checks if new task fits in remaining context
  3. If insufficient → Generates /resume prompt instead of attempting task

ESTIMATION METHOD:
  - Uses transcript JSONL to get actual token usage (input + output + cache)
  - Char-to-token ratio for new prompt estimation: 1 token ≈ 3 chars (conservative)
  - Warning threshold: 75% of context window
  - Hard block threshold: 90% of context window

STATE STORAGE:
  - SessionState fields: context_guard_active, last_context_tokens, stop_hook_runs
  - Project-isolated via goal_project_id

RESUME PROMPT:
  - Includes: original goal, recent files, last progress, active beads
  - Designed for paste-into-new-session recovery
"""

import json
import os
from datetime import datetime
from pathlib import Path

# Thresholds (percentage of context window)
WARNING_THRESHOLD = 0.75  # 75% - soft warning
HARD_BLOCK_THRESHOLD = 0.90  # 90% - force resume
ACTIVATION_BUFFER_TOKENS = 20000  # Don't activate until session has 20k+ tokens

# Estimation
CHAR_TO_TOKEN_RATIO = 3  # 1 token ≈ 3 chars (conservative for code)
NEW_PROMPT_ESTIMATE_BUFFER = 1.5  # Multiply estimate by 1.5 for safety

# Default context window (if model info unavailable)
DEFAULT_CONTEXT_WINDOW = 200000


def get_context_usage_from_transcript(transcript_path: str) -> tuple[int, int]:
    """Get token usage from transcript JSONL.

    Returns: (used_tokens, context_window)
    """
    if not transcript_path or not Path(transcript_path).exists():
        return 0, DEFAULT_CONTEXT_WINDOW

    try:
        with open(transcript_path, "r") as f:
            lines = f.readlines()

        # Search backwards for most recent assistant message with usage
        for line in reversed(lines):
            try:
                data = json.loads(line.strip())
                if data.get("message", {}).get("role") != "assistant":
                    continue
                # Skip synthetic messages
                model = str(data.get("message", {}).get("model", "")).lower()
                if "synthetic" in model:
                    continue
                usage = data.get("message", {}).get("usage")
                if usage:
                    used = (
                        usage.get("input_tokens", 0)
                        + usage.get("output_tokens", 0)
                        + usage.get("cache_read_input_tokens", 0)
                        + usage.get("cache_creation_input_tokens", 0)
                    )
                    return used, DEFAULT_CONTEXT_WINDOW
            except (json.JSONDecodeError, KeyError):
                continue
        return 0, DEFAULT_CONTEXT_WINDOW
    except (OSError, PermissionError):
        return 0, DEFAULT_CONTEXT_WINDOW


def estimate_prompt_tokens(prompt: str) -> int:
    """Estimate tokens for a new prompt.

    Uses conservative char-to-token ratio with safety buffer.
    """
    char_count = len(prompt)
    estimated = char_count / CHAR_TO_TOKEN_RATIO
    return int(estimated * NEW_PROMPT_ESTIMATE_BUFFER)


def check_context_fit(
    used_tokens: int,
    context_window: int,
    new_prompt_tokens: int,
) -> tuple[str, float]:
    """Check if new prompt fits in remaining context.

    Returns: (status, usage_pct)
      - status: "ok", "warning", "block"
      - usage_pct: projected usage percentage
    """
    projected = used_tokens + new_prompt_tokens
    pct = projected / context_window if context_window > 0 else 1.0

    if pct >= HARD_BLOCK_THRESHOLD:
        return "block", pct
    elif pct >= WARNING_THRESHOLD:
        return "warning", pct
    else:
        return "ok", pct


def _get_pal_continuations() -> dict[str, str]:
    """Get PAL continuation_ids from mastermind state.

    PAL continuations are EXTREMELY valuable - they allow resuming
    reasoning context across sessions. This is cross-session memory gold.
    """
    try:
        import json
        from pathlib import Path

        mm_dir = Path.home() / ".claude/tmp/mastermind"
        if mm_dir.exists():
            state_files = list(mm_dir.glob("*/*/state.json"))
            if state_files:
                latest = max(state_files, key=lambda p: p.stat().st_mtime)
                data = json.loads(latest.read_text())
                return data.get("pal_continuations", {})
    except Exception:
        pass
    return {}


def generate_resume_prompt(
    state,  # SessionState
    transcript_path: str,
    user_prompt: str,
) -> str:
    """Generate a /resume continuation prompt for a fresh session.

    Includes context recovery elements:
    - Original goal
    - Recent files modified
    - Last progress notes
    - Active beads
    - PAL continuation_ids (CRITICAL for cross-session context!)
    - The interrupted prompt
    """
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")

    # Extract key context from state
    original_goal = getattr(state, "original_goal", "") or "Not set"
    files_edited = list(set(getattr(state, "files_edited", [])[-10:]))
    files_created = list(set(getattr(state, "files_created", [])[-5:]))
    handoff_next_steps = getattr(state, "handoff_next_steps", [])
    current_feature = getattr(state, "current_feature", "")
    pal_continuations = _get_pal_continuations()

    # Build resume prompt
    lines = [
        "# Session Continuation",
        "",
        f"**Timestamp:** {timestamp}",
        "**Reason:** Context window exhaustion - proactive handoff",
        "",
        "## Original Goal",
        f"{original_goal[:500]}",
        "",
    ]

    if current_feature:
        lines.extend(
            [
                "## Current Feature/Task",
                f"{current_feature}",
                "",
            ]
        )

    if files_edited:
        lines.extend(
            [
                "## Files Modified This Session",
            ]
        )
        for f in files_edited[:8]:
            lines.append(f"- `{f}`")
        lines.append("")

    if files_created:
        lines.extend(
            [
                "## Files Created",
            ]
        )
        for f in files_created[:5]:
            lines.append(f"- `{f}`")
        lines.append("")

    if handoff_next_steps:
        lines.extend(
            [
                "## Next Steps (from previous context)",
            ]
        )
        if isinstance(handoff_next_steps, list):
            for step in handoff_next_steps[:5]:
                lines.append(f"- {step}")
        else:
            lines.append(str(handoff_next_steps)[:300])
        lines.append("")

    # 🔥 PAL CONTINUATIONS - CRITICAL FOR CROSS-SESSION CONTEXT
    if pal_continuations:
        lines.extend(
            [
                "## 🔥 PAL Continuation IDs (CRITICAL - USE THESE!)",
                "",
                "**These allow resuming prior reasoning context.**",
                "**ALWAYS pass continuation_id to PAL tools!**",
                "",
            ]
        )
        for tool_type, cont_id in pal_continuations.items():
            lines.append(f'- `mcp__pal__{tool_type}`: `continuation_id="{cont_id}"`')
        lines.extend(
            [
                "",
                "⚠️ **IMPORTANT:** When using ANY mcp__pal__* tool, pass the matching",
                "continuation_id to resume context instead of starting fresh!",
                "",
            ]
        )

    lines.extend(
        [
            "## Interrupted Prompt",
            "The user's prompt that triggered this handoff:",
            "```",
            user_prompt[:1000],
            "```",
            "",
            "---",
            "",
            "**To continue:** Paste this into a new Claude Code session.",
            "Run `/resume` first to load session state, then continue.",
        ]
    )

    return "\n".join(lines)


def format_context_warning(
    used_tokens: int,
    context_window: int,
    projected_pct: float,
    new_prompt_tokens: int,
) -> str:
    """Format a soft warning about context usage."""
    remaining = context_window - used_tokens
    return (
        f"**Context Warning** ({projected_pct:.0%} projected)\n\n"
        f"Current: {used_tokens:,} / {context_window:,} tokens\n"
        f"Remaining: {remaining:,} tokens\n"
        f"New prompt estimate: ~{new_prompt_tokens:,} tokens\n\n"
        f"Consider wrapping up or running `/resume` to start fresh."
    )


def format_context_block(
    used_tokens: int,
    context_window: int,
    projected_pct: float,
    resume_prompt: str,
) -> str:
    """Format a hard block with resume prompt."""
    return (
        f"## Context Exhaustion ({projected_pct:.0%} projected)\n\n"
        f"**Current usage:** {used_tokens:,} / {context_window:,} tokens\n\n"
        "The new task cannot fit in remaining context. "
        "To continue effectively, start a fresh session.\n\n"
        "---\n\n"
        "### Resume Prompt\n\n"
        "Copy the following into a new session:\n\n"
        f"```markdown\n{resume_prompt}\n```"
    )


def should_activate_guard(used_tokens: int) -> bool:
    """Determine if context guard should activate.

    Only activates after session has accumulated significant context.
    """
    return used_tokens >= ACTIVATION_BUFFER_TOKENS


def get_project_id() -> str:
    """Get current project identifier for isolation."""
    cwd = os.getcwd()
    # Use CWD as project identifier
    return cwd
