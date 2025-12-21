"""
Confidence Reducer PostToolUse hook.

Deterministic confidence reductions based on failure signals.
Priority 12 - runs after decay, applies pattern-based penalties.
"""

import _lib_path  # noqa: F401
import re
from pathlib import Path

from _hook_registry import register_hook
from _hook_result import HookResult
from session_state import SessionState, set_confidence
from confidence import (
    apply_reducers,
    apply_rate_limit,
    format_confidence_change,
    get_tier_info,
    format_dispute_instructions,
    predict_trajectory,
    format_trajectory_warning,
)

# Import shared utilities from _hooks_state
from _hooks_state import _extract_result_string, get_mastermind_drift_signals


# =============================================================================
# REDUCER CONTEXT BUILDING
# =============================================================================


def _build_reducer_context(
    tool_name: str, tool_input: dict, tool_result: dict, data: dict, state: SessionState
) -> dict:
    """Build base context for reducer evaluation."""
    # Build current_activity string for GoalDriftReducer
    activity_parts = [tool_name]
    if tool_name in ("Read", "Edit", "Write", "Glob", "Grep"):
        file_path = tool_input.get("file_path", "") or tool_input.get("path", "")
        if file_path:
            activity_parts.append(file_path)
        pattern = tool_input.get("pattern", "")
        if pattern:
            activity_parts.append(pattern)
    elif tool_name == "Bash":
        command = tool_input.get("command", "")
        if command:
            activity_parts.append(command[:200])

    result_str = _extract_result_string(tool_result)

    context = {
        "tool_name": tool_name,
        "tool_result": result_str,
        "current_activity": " ".join(activity_parts),
        "prompt": getattr(state, "last_user_prompt", ""),
        "assistant_output": data.get("assistant_output", ""),
    }

    # Add file_path for file-based reducers
    if tool_name in ("Edit", "Write", "Read"):
        file_path = tool_input.get("file_path", "")
        if file_path:
            context["file_path"] = file_path

    # Add content for code quality reducers
    if tool_name == "Edit":
        context["new_string"] = tool_input.get("new_string", "")
    elif tool_name == "Write":
        context["content"] = tool_input.get("content", "")

    # Framework alignment context (v4.8)
    # Serena availability and activation status
    context["serena_activated"] = getattr(state, "serena_activated", False)
    # Check if .serena/ exists in cwd (indicates serena is available)
    context["serena_available"] = Path(".serena").exists()

    # Grep path for GrepOverSerenaReducer
    if tool_name == "Grep":
        context["grep_path"] = tool_input.get("path", "")

    return context


# =============================================================================
# DETECTION FUNCTIONS
# =============================================================================


def _detect_tool_failures(
    tool_name: str, tool_input: dict, tool_result: dict, state: SessionState, ctx: dict
) -> None:
    """Detect tool failures and hook blocks."""
    # Bash exit code != 0
    if tool_name == "Bash" and isinstance(tool_result, dict):
        if tool_result.get("exit_code", 0) != 0:
            ctx["tool_failed"] = True

    # Edit/Write errors
    if tool_name in {"Edit", "Write", "MultiEdit"}:
        result_str = str(tool_result).lower() if tool_result else ""
        errors = [
            "file has not been read yet",
            "error:",
            "failed to",
            "permission denied",
            "no such file",
            "is not unique",
        ]
        if any(p in result_str for p in errors):
            ctx["tool_failed"] = True

    # Recent hook blocks
    if hasattr(state, "consecutive_blocks") and state.consecutive_blocks:
        for hook_name, entry in state.consecutive_blocks.items():
            if state.turn_count - entry.get("last_turn", 0) <= 2:
                ctx["hook_blocked"] = True
                break


def _detect_repetition_patterns(
    tool_name: str, tool_input: dict, state: SessionState, ctx: dict
) -> None:
    """Detect sequential repetition and git spam."""
    # Sequential repetition (same tool 3+ consecutive turns)
    last_info = getattr(state, "last_tool_info", {})
    if last_info:
        last_tool = last_info.get("tool_name", "")
        last_turn = last_info.get("turn", 0)
        consecutive = last_info.get("consecutive", 1)
        if last_tool == tool_name and last_turn < state.turn_count:
            is_similar = True
            if tool_name == "Bash":
                last_cmd = last_info.get("bash_cmd", "")
                curr_cmd = tool_input.get("command", "")[:50]
                is_similar = last_cmd[:20] == curr_cmd[:20]
            if is_similar:
                new_consecutive = consecutive + 1
                state.last_tool_info["consecutive"] = new_consecutive
                if new_consecutive >= 3:
                    ctx["sequential_repetition_3plus"] = True
        else:
            if hasattr(state, "last_tool_info"):
                state.last_tool_info["consecutive"] = 1

    # Git spam (>3 git commands in 5 turns without writes)
    git_cmds = ["git log", "git diff", "git status", "git show", "git blame"]
    if tool_name == "Bash" and any(
        g in tool_input.get("command", "") for g in git_cmds
    ):
        git_turns = getattr(state, "git_explore_turns", [])
        git_turns.append(state.turn_count)
        git_turns = [t for t in git_turns if state.turn_count - t <= 5]
        state.git_explore_turns = git_turns
        if len(git_turns) > 3 and not state.files_edited[-5:]:
            ctx["git_spam"] = True


def _was_file_edited_after(
    file_path: str, last_read_turn: int, files_edited: list
) -> bool:
    """Check if file was edited after a given turn."""
    for entry in files_edited:
        if isinstance(entry, dict):
            if entry.get("path") == file_path and entry.get("turn", 0) > last_read_turn:
                return True
        elif isinstance(entry, str) and entry == file_path:
            return True
    return False


def _detect_time_wasters(
    tool_name: str, tool_input: dict, tool_result: dict, state: SessionState, ctx: dict
) -> None:
    """Detect time waster patterns (v4.2)."""
    # Re-read unchanged file
    if tool_name == "Read":
        file_path = tool_input.get("file_path", "")
        files_read = getattr(state, "files_read", {})
        # Guard: files_read must be dict, not list
        if not isinstance(files_read, dict):
            files_read = {}
        if file_path and file_path in files_read:
            last_read_turn = files_read.get(file_path, {}).get("turn", 0)
            if not _was_file_edited_after(
                file_path, last_read_turn, getattr(state, "files_edited", [])
            ):
                ctx["reread_unchanged"] = True

    # Huge output dump
    if len(str(tool_result) if tool_result else "") > 5000:
        ctx["huge_output_dump"] = True


def _detect_incomplete_refactor(
    tool_name: str, tool_input: dict, tool_result: dict, state: SessionState, ctx: dict
) -> None:
    """Detect incomplete refactors (v4.4)."""
    file_path = tool_input.get("file_path", "")

    # Step 1: On Edit, track potential renames
    if tool_name == "Edit":
        old_str = tool_input.get("old_string", "")
        new_str = tool_input.get("new_string", "")
        replace_all = tool_input.get("replace_all", False)

        if old_str and new_str and not replace_all:
            old_ids = set(re.findall(r"\b([A-Za-z_][A-Za-z0-9_]{2,})\b", old_str))
            new_ids = set(re.findall(r"\b([A-Za-z_][A-Za-z0-9_]{2,})\b", new_str))
            removed_ids = old_ids - new_ids
            if removed_ids:
                pending = getattr(state, "pending_rename_check", [])
                for rid in removed_ids:
                    if len(rid) >= 4:
                        pending.append(
                            {"name": rid, "turn": state.turn_count, "file": file_path}
                        )
                state.pending_rename_check = [
                    p for p in pending if state.turn_count - p["turn"] <= 3
                ][-5:]

    # Step 2: On Grep, check if pending renames found elsewhere
    if tool_name == "Grep":
        pattern = tool_input.get("pattern", "")
        result_str = str(tool_result)[:2000].lower()
        pending = getattr(state, "pending_rename_check", [])

        for p in pending:
            if p["name"].lower() in pattern.lower():
                if "no matches" not in result_str and "0 results" not in result_str:
                    ctx["incomplete_refactor"] = True
                    break


def _detect_sequential_file_ops(tool_name: str, state: SessionState, ctx: dict) -> None:
    """Detect 3+ sequential file ops that could be parallelized."""
    file_ops = {"Read", "Edit", "Write", "Glob", "Grep"}
    if tool_name not in file_ops:
        return

    # Track recent file ops
    recent_ops = getattr(state, "recent_file_ops", [])
    recent_ops.append({"tool": tool_name, "turn": state.turn_count})
    # Keep only last 5 turns
    recent_ops = [op for op in recent_ops if state.turn_count - op["turn"] <= 3]
    state.recent_file_ops = recent_ops

    # Check for 3+ sequential file ops without other work
    if len(recent_ops) >= 3:
        ctx["sequential_file_ops"] = True


def _detect_unbacked_verification(
    tool_name: str, tool_result: dict, state: SessionState, ctx: dict
) -> None:
    """Detect 'verified' claims without actual verification evidence."""
    # Only check after assistant output
    output = str(tool_result.get("output", "")).lower()
    verification_claims = ["verified", "confirmed", "validated", "checked and"]

    if not any(claim in output for claim in verification_claims):
        return

    # Check for recent verification actions
    recent_verifications = getattr(state, "verification_actions", [])
    recent = [v for v in recent_verifications if state.turn_count - v <= 3]

    if not recent:
        ctx["unbacked_verification"] = True


def _detect_fixed_without_chain(
    tool_name: str, tool_result: dict, state: SessionState, ctx: dict
) -> None:
    """Detect 'fixed' claims without read→edit→verify chain."""
    output = str(tool_result.get("output", "")).lower()
    fix_claims = ["fixed", "resolved", "corrected the", "patched"]

    if not any(claim in output for claim in fix_claims):
        return

    # Check for proper fix chain: read + edit + (test or lint)
    recent_reads = len([f for f in state.files_read[-10:] if isinstance(f, str)])
    recent_edits = len(state.files_edited[-5:]) if state.files_edited else 0

    if recent_reads == 0 or recent_edits == 0:
        ctx["fixed_without_chain"] = True


def _detect_change_without_test(
    tool_name: str, tool_input: dict, state: SessionState, ctx: dict
) -> None:
    """Detect production code changes without test coverage."""
    if tool_name not in ("Edit", "Write"):
        return

    file_path = tool_input.get("file_path", "")
    # Skip test files and non-code
    if "test" in file_path.lower() or not file_path.endswith((".py", ".ts", ".js")):
        return

    # Track production edits
    prod_edits = getattr(state, "production_edits_without_test", 0)
    tests_run_since = getattr(state, "tests_run_since_edit", 0)

    if tests_run_since == 0:
        state.production_edits_without_test = prod_edits + 1
        if state.production_edits_without_test >= 3:
            ctx["change_without_test"] = True


def _detect_contradiction(tool_result: dict, state: SessionState, ctx: dict) -> None:
    """Detect contradictory statements in output."""
    output = str(tool_result.get("output", "")).lower()

    # Simple contradiction patterns
    contradictions = [
        ("works correctly", "doesn't work"),
        ("no issues", "found issues"),
        ("passes", "fails"),
        ("fixed", "still broken"),
    ]

    for pos, neg in contradictions:
        if pos in output and neg in output:
            ctx["contradiction_detected"] = True
            break


def _detect_trivial_question(state: SessionState, ctx: dict) -> None:
    """Detect questions that could be answered by reading code.

    Triggers when asking obvious questions about code that's already been read
    or could be answered with a simple search.
    """
    prompt = getattr(state, "last_user_prompt", "").lower()
    if not prompt:
        return

    # Trivial question patterns
    trivial_patterns = [
        "what does this do",
        "what is this",
        "how does this work",
        "what's in this file",
        "can you explain",
        "what are the",
    ]

    # Check if asking about something already read
    is_trivial = any(pattern in prompt for pattern in trivial_patterns)
    if not is_trivial:
        return

    # Check if we've already read relevant files (should know the answer)
    recent_reads = len(state.files_read[-5:]) if state.files_read else 0
    if recent_reads >= 2:
        # Already read files but asking trivial questions = should know
        ctx["trivial_question"] = True


# =============================================================================
# MAIN REDUCER HOOK
# =============================================================================


@register_hook("confidence_reducer", None, priority=12)
def check_confidence_reducer(
    data: dict, state: SessionState, runner_state: dict
) -> HookResult:
    """Apply deterministic confidence reductions based on failure signals.

    Delegates to helper functions for each detection category.
    """
    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})
    tool_result = data.get("tool_result", {})
    # Guard against non-dict results
    if not isinstance(tool_result, dict):
        tool_result = {}

    # Build context and detect patterns
    context = _build_reducer_context(tool_name, tool_input, tool_result, data, state)
    _detect_tool_failures(tool_name, tool_input, tool_result, state, context)
    _detect_repetition_patterns(tool_name, tool_input, state, context)
    _detect_time_wasters(tool_name, tool_input, tool_result, state, context)
    _detect_incomplete_refactor(tool_name, tool_input, tool_result, state, context)
    # New context flag detections (v4.9)
    _detect_sequential_file_ops(tool_name, state, context)
    _detect_unbacked_verification(tool_name, tool_result, state, context)
    _detect_fixed_without_chain(tool_name, tool_result, state, context)
    _detect_change_without_test(tool_name, tool_input, state, context)
    _detect_contradiction(tool_result, state, context)
    _detect_trivial_question(state, context)
    # Mastermind drift signals (v4.10) - unified nervous system
    drift_signals = get_mastermind_drift_signals(state)
    if drift_signals:
        context["mastermind_drift"] = drift_signals

    # Apply reducers
    triggered = apply_reducers(state, context)

    # Persist reducer history for mastermind routing context (v4.26)
    if triggered:
        import time

        if not hasattr(state, "reducer_history") or state.reducer_history is None:
            state.reducer_history = []
        for name, delta, desc in triggered:
            state.reducer_history.append(
                {
                    "name": name,
                    "delta": delta,
                    "turn": state.turn_count,
                    "timestamp": time.time(),
                }
            )
        # Keep only last 50 entries to prevent unbounded growth
        if len(state.reducer_history) > 50:
            state.reducer_history = state.reducer_history[-50:]

    if not triggered:
        return HookResult.none()

    # Calculate total reduction and apply with rate limiting
    old_confidence = state.confidence
    total_delta = sum(delta for _, delta, _ in triggered)
    total_delta = apply_rate_limit(total_delta, state)  # Prevent death spirals
    new_confidence = max(0, min(100, old_confidence + total_delta))

    # Update state
    set_confidence(state, new_confidence, "reducer triggered")

    # Format feedback
    reasons = [f"{name}: {delta}" for name, delta, _ in triggered]
    change_msg = format_confidence_change(
        old_confidence, new_confidence, ", ".join(reasons)
    )

    # Add tier info for context
    _, emoji, desc = get_tier_info(new_confidence)

    # Include dispute instructions
    reducer_names = [name for name, _, _ in triggered]
    dispute_hint = format_dispute_instructions(reducer_names)

    # v4.6: Add trajectory warning if heading toward a gate
    trajectory = predict_trajectory(
        state, planned_edits=1, planned_bash=1, turns_ahead=3
    )
    trajectory_warning = (
        format_trajectory_warning(trajectory) if trajectory["will_gate"] else ""
    )
    if trajectory_warning:
        trajectory_warning = f"\n\n{trajectory_warning}"

    return HookResult.with_context(
        f"📉 **Confidence Reduced**\n{change_msg}\n\n"
        f"Current: {emoji} {new_confidence}% - {desc}"
        f"{dispute_hint}{trajectory_warning}"
    )
