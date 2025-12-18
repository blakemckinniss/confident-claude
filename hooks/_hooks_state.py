"""
State management PostToolUse hooks.

Updates session state, manages confidence decay/reduction/increase.
Priority range: 5-16 (PAL mandate at 5, state at 10+)
"""

import _lib_path  # noqa: F401
import json
import re
from pathlib import Path

from _hook_registry import register_hook
from _hook_result import HookResult
from _config import get_magic_number

from session_state import (
    SessionState,
    track_file_read,
    track_file_edit,
    track_file_create,
    track_command,
    track_library_used,
    track_error,
    resolve_error,
    add_domain_signal,
    extract_libraries_from_code,
    track_failure,
    reset_failures,
    track_batch_tool,
    clear_pending_file,
    clear_pending_search,
    extract_function_def_lines,
    add_pending_integration_grep,
    clear_integration_grep,
    create_checkpoint,
    track_feature_file,
    complete_feature,
    add_work_item,
    track_ops_tool,
    mark_production_verified,
    set_confidence,
)

from confidence import (
    apply_reducers,
    apply_increasers,
    apply_rate_limit,
    format_confidence_change,
    get_tier_info,
)

# Mastermind drift tracking imports
try:
    from mastermind.state import (
        load_state as load_mastermind_state,
        save_state as save_mastermind_state,
    )
    from mastermind.drift import evaluate_drift, should_escalate
    from mastermind.config import get_config as get_mastermind_config

    MASTERMIND_AVAILABLE = True
except ImportError:
    MASTERMIND_AVAILABLE = False


def _get_session_id(state: SessionState) -> str:
    """Extract session ID for mastermind state."""
    return getattr(state, "session_id", "") or f"session_{int(state.turn_count or 0)}"


def _track_mastermind_file(filepath: str, state: SessionState) -> None:
    """Track file modification in mastermind state for drift detection."""
    if not MASTERMIND_AVAILABLE:
        return
    try:
        config = get_mastermind_config()
        if not config.drift.enabled:
            return
        session_id = _get_session_id(state)
        mm_state = load_mastermind_state(session_id)
        mm_state.record_file_modified(filepath)
        save_mastermind_state(mm_state)
    except Exception:
        pass  # Don't break main flow


def _track_mastermind_test_failure(state: SessionState) -> None:
    """Increment test failure count in mastermind state."""
    if not MASTERMIND_AVAILABLE:
        return
    try:
        config = get_mastermind_config()
        if not config.drift.enabled:
            return
        session_id = _get_session_id(state)
        mm_state = load_mastermind_state(session_id)
        mm_state.increment_test_failures()
        save_mastermind_state(mm_state)
    except Exception:
        pass


def check_mastermind_drift(state: SessionState) -> str | None:
    """Check for drift and return warning if escalation needed."""
    if not MASTERMIND_AVAILABLE:
        return None
    try:
        config = get_mastermind_config()
        if not config.drift.enabled:
            return None
        session_id = _get_session_id(state)
        mm_state = load_mastermind_state(session_id)

        # No blueprint = no drift detection
        if not mm_state.blueprint:
            return None

        signals = evaluate_drift(mm_state)
        if signals and should_escalate(signals, mm_state):
            # Record the escalation
            trigger = signals[0].trigger
            evidence = signals[0].evidence
            mm_state.record_escalation(trigger, evidence)
            save_mastermind_state(mm_state)

            # Format warning
            severity = signals[0].severity.upper()
            return (
                f"\n⚠️ **DRIFT DETECTED** [{severity}]: {trigger}\n"
                f"Evidence: {json.dumps(evidence, indent=2)}\n"
                f"Consider re-consulting the blueprint or calling mcp__pal__planner.\n"
            )
        return None
    except Exception:
        return None


def get_mastermind_drift_signals(state: SessionState) -> dict[str, bool]:
    """Get active mastermind drift signals for confidence reducers.

    Returns dict with keys: file_count, test_failures, approach_change
    Values are True if that drift signal is active.

    This feeds into context["mastermind_drift"] for the MastermindDriftReducers.
    """
    if not MASTERMIND_AVAILABLE:
        return {}
    try:
        config = get_mastermind_config()
        if not config.drift.enabled:
            return {}

        session_id = _get_session_id(state)
        mm_state = load_mastermind_state(session_id)

        # No blueprint = no drift detection
        if not mm_state.blueprint:
            return {}

        signals = evaluate_drift(mm_state)
        if not signals:
            return {}

        # Convert DriftSignal list to dict format for reducers
        drift_dict = {}
        for signal in signals:
            if signal.trigger == "file_count":
                drift_dict["file_count"] = True
            elif signal.trigger == "test_failures":
                drift_dict["test_failures"] = True
            elif signal.trigger == "approach_change":
                drift_dict["approach_change"] = True

        return drift_dict
    except Exception:
        return {}


# Additional confidence imports (can't be at top due to mastermind try/except block)
from confidence import (  # noqa: E402
    format_dispute_instructions,
    predict_trajectory,
    format_trajectory_warning,
    get_current_streak,
)


# -----------------------------------------------------------------------------
# PAL MANDATE CLEARING (priority 5) - Clear lock when PAL planner succeeds
# -----------------------------------------------------------------------------

_PAL_MANDATE_LOCK = Path.home() / ".claude" / "tmp" / "pal_mandate.lock"


@register_hook("pal_mandate_clear", "mcp__pal__planner", priority=5)
def clear_pal_mandate_on_success(
    data: dict, state: SessionState, runner_state: dict
) -> HookResult:
    """Clear PAL mandate lock and capture blueprint when mcp__pal__planner succeeds.

    MCP tools don't trigger PreToolUse hooks, so we clear the lock here in
    PostToolUse instead. Also captures the blueprint for mastermind state.
    """
    import sys

    tool_input = data.get("tool_input", {})
    tool_result = data.get("tool_result", {})
    model = tool_input.get("model", "").lower()

    context_parts = []

    # Check if GPT-5.x was used (required for mandate clearing)
    is_gpt5 = "gpt-5" in model or "gpt5" in model

    # Clear lock if GPT-5.x was used
    if is_gpt5 and _PAL_MANDATE_LOCK.exists():
        try:
            _PAL_MANDATE_LOCK.unlink()
            context_parts.append(
                "✅ **PAL MANDATE SATISFIED** - GPT-5.x planner called. Lock cleared."
            )
        except OSError as e:
            print(f"[pal_mandate_clear] Failed to clear lock: {e}", file=sys.stderr)

    # Capture blueprint from planner result for mastermind state
    try:
        from mastermind.state import load_state, save_state
        from mastermind.hook_integration import get_session_id

        # Extract result content
        result_str = ""
        if isinstance(tool_result, dict):
            result_str = (
                tool_result.get("content", "")
                or tool_result.get("output", "")
                or str(tool_result)
            )
        elif isinstance(tool_result, str):
            result_str = tool_result
        else:
            result_str = str(tool_result) if tool_result else ""

        # Parse blueprint from planner output
        blueprint = _parse_blueprint_from_planner(result_str, tool_input)

        if blueprint:
            # Load current session state and save blueprint
            session_id = get_session_id()
            mm_state = load_state(session_id)
            mm_state.blueprint = blueprint
            mm_state.routing_decision = None  # Clear old routing decision
            save_state(mm_state)

            context_parts.append(
                f"📋 **Blueprint Captured** - Goal: {blueprint.goal[:100]}..."
                if len(blueprint.goal) > 100
                else f"📋 **Blueprint Captured** - Goal: {blueprint.goal}"
            )

            # Add invariants preview
            if blueprint.invariants:
                inv_preview = ", ".join(blueprint.invariants[:3])
                if len(blueprint.invariants) > 3:
                    inv_preview += f" (+{len(blueprint.invariants) - 3} more)"
                context_parts.append(f"   ⚠️ Invariants: {inv_preview}")

            # Add touch set preview
            if blueprint.touch_set:
                touch_preview = ", ".join(blueprint.touch_set[:5])
                if len(blueprint.touch_set) > 5:
                    touch_preview += f" (+{len(blueprint.touch_set) - 5} more)"
                context_parts.append(f"   📁 Touch set: {touch_preview}")

    except ImportError:
        # Mastermind not available, skip blueprint capture
        pass
    except Exception as e:
        print(f"[pal_mandate_clear] Blueprint capture failed: {e}", file=sys.stderr)

    if context_parts:
        return HookResult.approve("\n".join(context_parts))
    return HookResult.approve()


def _parse_blueprint_from_planner(result_str: str, tool_input: dict):
    """Parse blueprint from PAL planner output.

    Extracts structured planning information from the planner response.
    Falls back to extracting from step content if JSON not found.
    """
    import json
    import re

    try:
        from mastermind.state import Blueprint
    except ImportError:
        return None

    # Try to find JSON blueprint in result
    json_match = re.search(r'\{[^{}]*"goal"[^{}]*\}', result_str, re.DOTALL)
    if json_match:
        try:
            data = json.loads(json_match.group())
            return Blueprint(
                goal=data.get("goal", ""),
                invariants=data.get("invariants", []),
                touch_set=data.get("touch_set", data.get("files", [])),
                budget=data.get("budget", {}),
                decision_points=data.get("decision_points", []),
                acceptance_criteria=data.get("acceptance_criteria", []),
            )
        except json.JSONDecodeError:
            pass

    # Extract from structured sections in result
    goal = ""
    invariants = []
    touch_set = []
    acceptance_criteria = []

    # Look for goal/objective
    goal_patterns = [
        r"(?:Goal|Objective|Purpose)[:\s]+([^\n]+)",
        r"(?:We need to|Task is to|Will)[:\s]*([^\n]+)",
    ]
    for pattern in goal_patterns:
        match = re.search(pattern, result_str, re.IGNORECASE)
        if match:
            goal = match.group(1).strip()
            break

    # If no goal found, use step content from input
    if not goal:
        goal = tool_input.get("step", "")[:200]

    # Look for invariants/constraints
    inv_section = re.search(
        r"(?:Invariants?|Constraints?|Must not)[:\s]*\n((?:[-*]\s*[^\n]+\n?)+)",
        result_str,
        re.IGNORECASE,
    )
    if inv_section:
        invariants = [
            line.strip().lstrip("-* ")
            for line in inv_section.group(1).split("\n")
            if line.strip()
        ]

    # Look for files/touch set
    files_section = re.search(
        r"(?:Files?|Touch set|Will modify)[:\s]*\n((?:[-*]\s*[^\n]+\n?)+)",
        result_str,
        re.IGNORECASE,
    )
    if files_section:
        touch_set = [
            line.strip().lstrip("-* ")
            for line in files_section.group(1).split("\n")
            if line.strip()
        ]

    # Look for acceptance criteria
    accept_section = re.search(
        r"(?:Acceptance|Done when|Success criteria)[:\s]*\n((?:[-*]\s*[^\n]+\n?)+)",
        result_str,
        re.IGNORECASE,
    )
    if accept_section:
        acceptance_criteria = [
            line.strip().lstrip("-* ")
            for line in accept_section.group(1).split("\n")
            if line.strip()
        ]

    if goal:
        return Blueprint(
            goal=goal,
            invariants=invariants[:10],
            touch_set=touch_set[:20],
            budget={},
            decision_points=[],
            acceptance_criteria=acceptance_criteria[:10],
        )

    return None


# -----------------------------------------------------------------------------
# STATE UPDATER (priority 10) - Must run first to update state for other hooks
# -----------------------------------------------------------------------------

_RE_PYTEST_FAIL = re.compile(r"FAILED\s+([\w./]+)::(\w+)")
_RE_JEST_FAIL = re.compile(r"FAIL\s+([\w./]+)\s*\n.*?✕\s+(.+?)(?:\n|$)", re.MULTILINE)
_RE_GENERIC_FAIL = re.compile(r"(?:Error|FAIL|FAILED):\s*(.+?)(?:\n|$)")

# Time saver signal patterns
_RE_CHAIN_SEMICOLON = re.compile(r";\s*\w+")
_RE_CHAIN_SPLIT = re.compile(r"\s*&&\s*|\s*;\s*")

_TODO_PATTERNS = [
    (re.compile(r"#\s*TODO[:\s]+(.+?)(?:\n|$)", re.IGNORECASE), "TODO"),
    (re.compile(r"//\s*TODO[:\s]+(.+?)(?:\n|$)", re.IGNORECASE), "TODO"),
    (re.compile(r"#\s*FIXME[:\s]+(.+?)(?:\n|$)", re.IGNORECASE), "FIXME"),
    (re.compile(r"//\s*FIXME[:\s]+(.+?)(?:\n|$)", re.IGNORECASE), "FIXME"),
]


def _extract_result_string(tool_result) -> str:
    """Extract string from tool_result (can be dict, list, str, or None)."""
    if isinstance(tool_result, dict):
        return (
            tool_result.get("output", "")
            or tool_result.get("content", "")
            or str(tool_result)
        )
    elif isinstance(tool_result, str):
        return tool_result
    else:
        return str(tool_result) if tool_result else ""


def extract_test_failures(output: str) -> list[dict]:
    """Extract test failure information from pytest/jest output."""
    failures = []
    for file, test in _RE_PYTEST_FAIL.findall(output):
        failures.append(
            {
                "test_name": test,
                "file": file,
                "description": f"Fix failing test: {test} in {file}",
                "priority": 80,
            }
        )
    for file, test in _RE_JEST_FAIL.findall(output):
        failures.append(
            {
                "test_name": test,
                "file": file,
                "description": f"Fix failing test: {test} in {file}",
                "priority": 80,
            }
        )
    for msg in _RE_GENERIC_FAIL.findall(output)[:3]:
        if msg not in [f.get("description", "") for f in failures]:
            failures.append(
                {
                    "test_name": "unknown",
                    "file": "unknown",
                    "description": f"Fix: {msg[:80]}",
                    "priority": 70,
                }
            )
    return failures[:5]


def _trigger_self_heal(state: SessionState, target: str, error: str) -> None:
    """Trigger self-heal mode for framework errors.

    Called when a tool fails on a .claude/ path. Sets state to require
    self-healing before continuing other work.
    """
    # Record the framework error
    if not hasattr(state, "framework_errors"):
        state.framework_errors = []
    state.framework_errors.append(
        {"path": target, "error": error[:200], "turn": state.turn_count}
    )
    # Keep only last 10
    state.framework_errors = state.framework_errors[-10:]
    state.framework_error_turn = state.turn_count

    # Only trigger self-heal if not already in progress
    if not getattr(state, "self_heal_required", False):
        state.self_heal_required = True
        state.self_heal_target = target
        state.self_heal_error = error[:200]
        state.self_heal_attempts = 0


def _clear_self_heal(state: SessionState) -> None:
    """Clear self-heal state after successful fix."""
    state.self_heal_required = False
    state.self_heal_target = ""
    state.self_heal_error = ""
    state.self_heal_attempts = 0


def _detect_error_in_result(
    result, keywords: tuple[str, ...] = ("error", "failed")
) -> str:
    """Detect errors in tool result.

    Args:
        result: Tool result dict with potential 'error' or 'output' fields,
                or a string (treated as output)
        keywords: Error keywords to search for in output (lowercase)

    Returns:
        Error string (truncated to 200 chars) or empty string if no error
    """
    # Handle string results (Claude sometimes returns plain strings)
    if isinstance(result, str):
        result_lower = result.lower()[:150]
        if any(kw in result_lower for kw in keywords):
            return result[:200]
        return ""

    if not isinstance(result, dict):
        return ""

    # Check explicit error field first
    error = result.get("error", "") or ""
    if error:
        return error[:200]

    # Check output for error keywords
    output = result.get("output", "")
    if isinstance(output, str):
        output_lower = output.lower()[:150]
        if any(kw in output_lower for kw in keywords):
            return output[:200]

    return ""


def extract_todos_from_content(content: str, filepath: str) -> list[dict]:
    """Extract TODO/FIXME items from code content."""
    todos = []
    filename = Path(filepath).name if filepath else "unknown"
    for pattern, todo_type in _TODO_PATTERNS:
        for match in pattern.findall(content)[:3]:
            todos.append(
                {
                    "description": f"{todo_type}: {match.strip()[:60]} ({filename})",
                    "file": filepath,
                    "priority": 60 if todo_type == "FIXME" else 50,
                }
            )
    return todos[:5]


def detect_stubs_in_content(content: str) -> list[str]:
    """Detect stub patterns in code content."""
    STUB_PATTERNS = [
        ("TODO", "TODO"),
        ("FIXME", "FIXME"),
        ("NotImplementedError", "NotImplementedError"),
        ("raise NotImplementedError", "NotImplementedError"),
        ("pass  #", "stub pass"),
        ("...  #", "ellipsis stub"),
    ]
    found = []
    for pattern, label in STUB_PATTERNS:
        if pattern in content:
            found.append(label)
    return list(set(found))[:3]


# NOTE: Cache hooks (exploration_cacher, read_cacher, read_cache_invalidator)
# moved to _hooks_cache.py


def _handle_read_tool(tool_input: dict, result: dict, state: SessionState) -> None:
    """Handle Read tool state updates."""
    # Guard against non-dict results
    if not isinstance(result, dict):
        result = {}
    filepath = tool_input.get("file_path", "")
    read_error = _detect_error_in_result(
        result, keywords=("no such file", "permission denied", "not found")
    )
    if read_error and filepath and ".claude/" in filepath:
        _trigger_self_heal(state, target=filepath, error=read_error)

    if filepath:
        track_file_read(state, filepath)
        add_domain_signal(state, filepath)
        clear_pending_file(state, filepath)
        content = result.get("output", "")
        if filepath.endswith((".py", ".js", ".ts")):
            for lib in extract_libraries_from_code(content):
                track_library_used(state, lib)
        if filepath.endswith((".py", ".js", ".ts", ".tsx", ".rs", ".go", ".java")):
            for todo in extract_todos_from_content(content, filepath):
                add_work_item(
                    state,
                    item_type="todo",
                    source=filepath,
                    description=todo.get("description", "TODO"),
                    priority=todo.get("priority", 50),
                )


def _handle_edit_tool(tool_input: dict, result: dict, state: SessionState) -> None:
    """Handle Edit tool state updates."""
    filepath = tool_input.get("file_path", "")
    edit_error = _detect_error_in_result(result)
    if edit_error and filepath and ".claude/" in filepath:
        _trigger_self_heal(state, target=filepath, error=edit_error)

    if filepath:
        # Track for mastermind drift detection
        if not edit_error:
            _track_mastermind_file(filepath, state)

        old_code = tool_input.get("old_string", "")
        new_code = tool_input.get("new_string", "")
        track_file_edit(state, filepath, old_code, new_code)
        track_feature_file(state, filepath)
        if new_code:
            for lib in extract_libraries_from_code(new_code):
                track_library_used(state, lib)
            if filepath.endswith((".py", ".js", ".ts", ".tsx", ".rs", ".go")):
                old_func_lines = extract_function_def_lines(old_code)
                new_func_lines = extract_function_def_lines(new_code)
                for func_name, old_def in old_func_lines.items():
                    new_def = new_func_lines.get(func_name)
                    if new_def is not None and old_def != new_def:
                        add_pending_integration_grep(state, func_name, filepath)
        if (
            not edit_error
            and getattr(state, "self_heal_required", False)
            and ".claude/" in filepath
        ):
            _clear_self_heal(state)


def _handle_write_tool(
    tool_input: dict, result: dict, state: SessionState
) -> str | None:
    """Handle Write tool state updates. Returns warning message if any."""
    filepath = tool_input.get("file_path", "")
    warning = None
    write_error = _detect_error_in_result(result)
    if write_error and filepath and ".claude/" in filepath:
        _trigger_self_heal(state, target=filepath, error=write_error)

    if filepath:
        # Track for mastermind drift detection
        if not write_error:
            _track_mastermind_file(filepath, state)

        is_new_file = filepath not in state.files_read
        if is_new_file:
            track_file_create(state, filepath)
        else:
            track_file_edit(state, filepath)
        track_feature_file(state, filepath)
        content = tool_input.get("content", "")
        if content:
            for lib in extract_libraries_from_code(content):
                track_library_used(state, lib)
            # Skip stub detection for command defs (search patterns, not stubs)
            is_command_def = "/commands/" in filepath and filepath.endswith(".md")
            if is_new_file and not is_command_def:
                stubs = detect_stubs_in_content(content)
                if stubs:
                    fname = Path(filepath).name
                    warning = (
                        f"⚠️ STUB DETECTED in new file `{fname}`: "
                        f"{', '.join(stubs)}\n   Remember to complete before session ends!"
                    )
        if (
            not write_error
            and getattr(state, "self_heal_required", False)
            and ".claude/" in filepath
        ):
            _clear_self_heal(state)
    return warning


def _track_bash_ops_usage(command: str, success: bool, state: SessionState) -> None:
    """Track ops tool usage and audit/void verification."""
    if ".claude/ops/" not in command:
        return
    ops_match = re.search(r"\.claude/ops/(\w+)\.py", command)
    if not ops_match:
        return
    tool_name_ops = ops_match.group(1)
    track_ops_tool(state, tool_name_ops, success)

    # Track audit/void verification for production files
    if success and tool_name_ops in ("audit", "void"):
        parts = command.split()
        for i, part in enumerate(parts):
            if part.endswith(f"{tool_name_ops}.py") and i + 1 < len(parts):
                target_file = parts[i + 1]
                if not target_file.startswith("-"):
                    mark_production_verified(state, target_file, tool_name_ops)
                break


def _track_bash_git_commit(command: str, output: str, state: SessionState) -> None:
    """Handle git commit checkpoints and feature completion."""
    if not re.search(r"\bgit\s+commit\b", command, re.IGNORECASE):
        return
    commit_hash = ""
    hash_match = re.search(r"\[[\w-]+\s+([a-f0-9]{7,})\]", output)
    if hash_match:
        commit_hash = hash_match.group(1)
    msg_match = re.search(r'-m\s+["\']([^"\']+)["\']', command)
    notes = msg_match.group(1)[:50] if msg_match else "commit"
    create_checkpoint(state, commit_hash=commit_hash, notes=notes)

    completion_keywords = [
        "fix",
        "complete",
        "done",
        "finish",
        "implement",
        "resolve",
        "close",
    ]
    if state.current_feature and any(kw in notes.lower() for kw in completion_keywords):
        complete_feature(state, status="completed")


_ERROR_PATTERNS = [
    (re.compile(r"(\d{3})\s*(Unauthorized|Forbidden|Not Found)", re.I), "HTTP error"),
    (re.compile(r"(ModuleNotFoundError|ImportError)", re.I), "Import error"),
    (re.compile(r"(SyntaxError|TypeError|ValueError)", re.I), "Python error"),
    (re.compile(r"(ENOENT|EACCES|EPERM)", re.I), "Filesystem error"),
    (re.compile(r"(connection refused|timeout)", re.I), "Network error"),
]


def _classify_error(output: str) -> str:
    """Classify error type from command output."""
    for pattern, error_type in _ERROR_PATTERNS:
        if pattern.search(output):
            return error_type
    return "Command error"


def _is_framework_command(command: str) -> bool:
    """Check if command operates on .claude/ framework files."""
    return ".claude/" in command or ".claude\\" in command


def _track_bash_failures(
    command: str, output: str, success: bool, state: SessionState
) -> None:
    """Track failures, errors, and self-heal triggers."""
    approach_sig = (
        f"Bash:{command.split()[0][:20]}" if command.split() else "Bash:unknown"
    )

    if not success:
        error_type = _classify_error(output)
        track_error(state, error_type, output[:500])
        track_failure(state, approach_sig)
        if _is_framework_command(command):
            _trigger_self_heal(
                state,
                target=command.split()[0] if command.split() else "bash",
                error=output[:200],
            )

    if (
        success
        and getattr(state, "self_heal_required", False)
        and _is_framework_command(command)
    ):
        _clear_self_heal(state)

    if success and state.errors_unresolved:
        reset_failures(state)
        for error in state.errors_unresolved[:]:
            if any(
                word in command.lower()
                for word in error.get("type", "").lower().split()
            ):
                resolve_error(state, error.get("type", ""))


def _track_bash_test_failures(command: str, output: str, state: SessionState) -> None:
    """Discover and track test failures from test runner output."""
    test_commands = ["pytest", "npm test", "jest", "cargo test"]
    if not any(tc in command for tc in test_commands):
        return
    failures = extract_test_failures(output)
    for failure in failures:
        add_work_item(
            state,
            item_type="test_failure",
            source=failure.get("file", "tests"),
            description=failure.get("description", "Fix test failure"),
            priority=failure.get("priority", 80),
        )
    # Track test failures for mastermind drift detection
    if failures:
        _track_mastermind_test_failure(state)


def _handle_bash_tool(tool_input: dict, result: dict, state: SessionState) -> None:
    """Handle Bash tool state updates. Delegates to specialized trackers."""
    command = tool_input.get("command", "")
    # Guard against non-dict results (e.g., list from some tool responses)
    if not isinstance(result, dict):
        result = {}
    output = result.get("output", "")
    exit_code = result.get("exit_code", 0)
    success = exit_code == 0
    track_command(state, command, success, output)

    # Delegate to specialized trackers
    _track_bash_ops_usage(command, success, state)

    # Track files read via cat/head/tail
    if success:
        read_cmds = ["cat ", "head ", "tail ", "less ", "more "]
        if any(command.startswith(cmd) or f" {cmd}" in command for cmd in read_cmds):
            for part in command.split()[1:]:
                if not part.startswith("-") and ("/" in part or "." in part):
                    track_file_read(state, part)

    # Track directories listed via ls (for gap_detector ls-before-create check)
    if success:
        ls_patterns = ["ls ", "ls\t"]
        if command.startswith("ls") or any(f" {p}" in command for p in ls_patterns):
            # Extract directory argument from ls command
            parts = command.split()
            for i, part in enumerate(parts):
                if part == "ls" and i + 1 < len(parts):
                    next_part = parts[i + 1]
                    if not next_part.startswith("-"):
                        if next_part not in state.dirs_listed:
                            state.dirs_listed.append(next_part)
                            state.dirs_listed = state.dirs_listed[-50:]
                elif part == "ls" and (
                    i + 1 >= len(parts) or parts[i + 1].startswith("-")
                ):
                    # ls with no dir or only flags = current dir
                    if "." not in state.dirs_listed:
                        state.dirs_listed.append(".")

    if success:
        _track_bash_git_commit(command, output, state)

    _track_bash_failures(command, output, success, state)
    _track_bash_test_failures(command, output, state)

    # Clear pending items for bash grep/find
    if "grep " in command or command.startswith("grep") or "rg " in command:
        patterns = re.findall(r'grep[^\|]*?["\']([^"\']+)["\']', command)
        patterns += re.findall(r"grep\s+(?:-\w+\s+)*(\w+)", command)
        for pattern in patterns:
            if len(pattern) > 3:
                clear_integration_grep(state, pattern)
                clear_pending_search(state, pattern)


def _handle_search_tool(tool_name: str, tool_input: dict, state: SessionState) -> None:
    """Handle Grep/Glob search tools."""
    pattern = tool_input.get("pattern", "")
    path = tool_input.get("path", "")
    add_domain_signal(state, pattern)
    if pattern:
        clear_pending_search(state, pattern)
        if tool_name == "Grep":
            clear_integration_grep(state, pattern)
        elif tool_name == "Glob":
            # Track glob patterns for gap_detector (ls-before-create check)
            glob_entry = f"{path}:{pattern}" if path else pattern
            if glob_entry not in state.globs_run:
                state.globs_run.append(glob_entry)
                state.globs_run = state.globs_run[-50:]  # Keep last 50


def _normalize_result(result: any) -> dict:
    """Normalize tool result to dict."""
    if isinstance(result, str):
        return {"output": result}
    return result if isinstance(result, dict) else {}


# -----------------------------------------------------------------------------
# SERENA ACTIVATION TRACKER (priority 9) - Track Serena activation early
# -----------------------------------------------------------------------------


@register_hook("serena_activation", "mcp__serena__activate_project", priority=9)
def check_serena_activation(
    data: dict, state: SessionState, runner_state: dict
) -> HookResult:
    """Track when Serena is activated for automatic memory management hints.

    Note: Claude Code doesn't pass tool_result for MCP tools, so we detect
    activation by the presence of a project input (assumes success if called).
    """
    tool_input = data.get("tool_input", {})
    project = tool_input.get("project", "")

    # If we have a project input, assume activation succeeded
    # (MCP errors would prevent PostToolUse from being called)
    if project:
        state.serena_activated = True
        state.serena_project = project
        return HookResult(
            context=f"🔮 **SERENA ACTIVATED**: Project `{project}` ready for semantic analysis"
        )

    # Fallback: check tool_result if available (for future compatibility)
    tool_result = data.get("tool_result", {})
    result_str = _extract_result_string(tool_result)
    if (
        "activated" in result_str.lower()
        or "programming languages" in result_str.lower()
    ):
        state.serena_activated = True
        state.serena_project = project
        return HookResult(
            context=f"🔮 **SERENA ACTIVATED**: Project `{project}` ready for semantic analysis"
        )

    return HookResult()


@register_hook("state_updater", None, priority=10)
def check_state_updater(
    data: dict, state: SessionState, runner_state: dict
) -> HookResult:
    """Update session state based on tool usage."""
    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})
    result = _normalize_result(data.get("tool_result", {}))
    warning = None

    state.tool_counts[tool_name] = state.tool_counts.get(tool_name, 0) + 1
    track_batch_tool(state, tool_name, tools_in_message=1)

    if tool_name == "Read":
        _handle_read_tool(tool_input, result, state)
    elif tool_name == "Edit":
        _handle_edit_tool(tool_input, result, state)
    elif tool_name == "Write":
        warning = _handle_write_tool(tool_input, result, state)
    elif tool_name == "Bash":
        _handle_bash_tool(tool_input, result, state)
    elif tool_name in ("Grep", "Glob"):
        _handle_search_tool(tool_name, tool_input, state)
    elif tool_name == "Task":
        add_domain_signal(state, tool_input.get("prompt", "")[:200])

    state.last_tool_info = {
        "tool_name": tool_name,
        "turn": state.turn_count,
        "bash_cmd": tool_input.get("command", "")[:50] if tool_name == "Bash" else "",
    }

    return HookResult.with_context(warning) if warning else HookResult.none()


# -----------------------------------------------------------------------------
# CONFIDENCE REDUCER (priority 12) - Deterministic confidence reductions
# -----------------------------------------------------------------------------


def _get_penalty_multiplier(confidence: int) -> float:
    """Scale penalties based on confidence level.

    Higher confidence = harder to maintain (bigger penalties).
    Lower confidence = already struggling (reduced penalties).

    This prevents coasting at high confidence - mistakes cost more
    when you're confident, creating pressure to stay careful.
    """
    if confidence >= 95:
        return 2.0  # Double penalties at peak confidence
    elif confidence >= 85:
        return 1.5  # 50% extra penalty in trusted zone
    elif confidence >= 70:
        return 1.0  # Normal penalties in working zone
    elif confidence >= 50:
        return 0.75  # Reduced penalties when struggling
    else:
        return 0.5  # Half penalties when in crisis


def _get_boost_multiplier(confidence: int) -> float:
    """Scale boosts based on confidence level - INVERSE of penalty scaling.

    Lower confidence = BIGGER boosts (survival mode, desperate for trust).
    Higher confidence = SMALLER boosts (already trusted, hard to justify more).

    Creates a self-correcting system:
    - When struggling: every bit of research/consultation is precious
    - When comfortable: coasting won't increase trust
    """
    if confidence < 30:
        return 3.0  # Desperate mode - every insight is gold
    elif confidence < 50:
        return 2.0  # Struggling - info gathering is rewarded heavily
    elif confidence < 70:
        return 1.5  # Working hard - research still pays off
    elif confidence < 85:
        return 1.0  # Normal - standard boost values
    else:
        return 0.5  # Comfortable - can't easily boost higher


# Default context window for Claude models (used when model info unavailable)
_DEFAULT_CONTEXT_WINDOW = get_magic_number("default_context_window", 200000)


def _get_context_percentage(transcript_path: str) -> float:
    """Calculate context window usage percentage from transcript.

    Reads the most recent assistant message's usage data to determine
    how much of the context window has been consumed.

    Returns 0.0 if unable to determine (safe default).
    """
    if not transcript_path:
        return 0.0

    try:
        transcript = Path(transcript_path)
        if not transcript.exists():
            return 0.0

        with open(transcript, "r") as f:
            lines = f.readlines()

        # Find most recent assistant message with usage data
        for line in reversed(lines):
            try:
                data = json.loads(line.strip())
                msg = data.get("message", {})
                if msg.get("role") != "assistant":
                    continue
                # Skip synthetic messages
                model = str(msg.get("model", "")).lower()
                if "synthetic" in model:
                    continue

                usage = msg.get("usage")
                if usage:
                    used = (
                        usage.get("input_tokens", 0)
                        + usage.get("output_tokens", 0)
                        + usage.get("cache_read_input_tokens", 0)
                        + usage.get("cache_creation_input_tokens", 0)
                    )
                    if used > 0:
                        return (used / _DEFAULT_CONTEXT_WINDOW) * 100
            except (json.JSONDecodeError, KeyError):
                continue

        return 0.0
    except Exception:
        return 0.0


def _get_context_multiplier(context_pct: float) -> tuple[float, float]:
    """Scale adjustments based on context usage.

    Returns (penalty_mult, boost_mult) tuple:
    - penalty_mult: Multiplier for penalties (higher context = bigger penalties)
    - boost_mult: Multiplier for boosts (higher context = smaller boosts)

    At high context usage, mistakes are more costly because:
    - Less room to recover with fresh context
    - Accumulated complexity increases error probability
    - User may be frustrated with long unproductive sessions
    """
    if context_pct >= 80:
        # Critical context usage - maximum pressure
        return (2.0, 0.5)  # Double penalties, halve boosts
    elif context_pct >= 60:
        # High context usage - significant pressure
        return (1.5, 0.75)  # 50% more penalties, 25% less boosts
    elif context_pct >= 40:
        # Medium context usage - mild pressure
        return (1.25, 0.9)  # 25% more penalties, 10% less boosts
    else:
        # Low context usage - normal operation
        return (1.0, 1.0)  # No modification


def _track_researched_libraries(tool_name: str, tool_input: dict, state: SessionState):
    """Extract library names from research queries and mark as researched.

    This unlocks the research_gate for these libraries in pre_tool_use.
    """
    from session_state import RESEARCH_REQUIRED_LIBS, track_library_researched

    # Get the text to search for library mentions
    text = ""
    if tool_name == "WebSearch":
        text = tool_input.get("query", "")
    elif tool_name == "WebFetch":
        text = tool_input.get("url", "") + " " + tool_input.get("prompt", "")
    elif tool_name == "mcp__crawl4ai__crawl":
        text = tool_input.get("url", "")
    elif tool_name == "mcp__crawl4ai__search":
        text = tool_input.get("query", "")

    if not text:
        return

    text_lower = text.lower()

    # Check for each required library in the search/fetch
    for lib in RESEARCH_REQUIRED_LIBS:
        if lib.lower() in text_lower:
            track_library_researched(state, lib)


# Decay boost lookup tables
_PAL_HIGH_BOOST = frozenset(
    ("thinkdeep", "debug", "codereview", "consensus", "precommit")
)
_PAL_LOW_BOOST = frozenset(("chat", "challenge", "apilookup"))
_DECAY_BOOST_FIXED = {
    "AskUserQuestion": (2, "user-clarification"),
    "Task": (1.5, "agent-delegation"),
    "WebSearch": (0.5, "web-research"),
    "WebFetch": (0.5, "web-research"),
}


def _calculate_decay_boost(
    tool_name: str, tool_input: dict, state: SessionState
) -> tuple[float, str]:
    """Calculate recovery action boosts for confidence decay."""
    # PAL external consultation
    if tool_name.startswith("mcp__pal__"):
        pal_tool = tool_name.replace("mcp__pal__", "")
        if pal_tool in _PAL_HIGH_BOOST:
            return 2, f"pal-{pal_tool}"
        if pal_tool in _PAL_LOW_BOOST:
            return 1, f"pal-{pal_tool}"
        return 0, ""

    # Fixed boosts
    if tool_name in _DECAY_BOOST_FIXED:
        return _DECAY_BOOST_FIXED[tool_name]

    # Read - diminishing returns
    if tool_name == "Read":
        read_count = len([f for f in state.files_read if f])
        boost = 0.5 if read_count <= 3 else (0.25 if read_count <= 6 else 0.1)
        return boost, f"file-read({read_count})"

    # Memory access or web crawl
    if tool_name.startswith("mcp__"):
        if "mem" in tool_name.lower():
            return 0.5, "memory-access"
        if tool_name.startswith("mcp__crawl4ai__"):
            return 0.5, "web-crawl"

    return 0, ""


def _calculate_decay_penalty(
    tool_name: str, tool_input: dict, state: SessionState
) -> tuple[float, str]:
    """Calculate penalties for risky actions.

    Returns (penalty_value, penalty_reason).
    """
    if tool_name in ("Edit", "Write"):
        penalty = 0
        reason_parts = []
        file_path = tool_input.get("file_path", "")

        # Base edit penalty with cooldown (max 1 per 3 turns)
        edit_risk_key = "_edit_risk_last_turn"
        last_edit_risk = getattr(state, edit_risk_key, 0)
        if state.turn_count - last_edit_risk >= 3:
            penalty = 1
            reason_parts.append("edit-risk")
            setattr(state, edit_risk_key, state.turn_count)

        # Edit without reading first = extra penalty
        if file_path and file_path not in state.files_read:
            penalty += 2
            reason_parts = ["edit-without-read"]

        # Check for stubs in new code
        new_code = tool_input.get("new_string", "") or tool_input.get("content", "")
        if new_code:
            stub_patterns = [
                "pass  # TODO",
                "raise NotImplementedError",
                "# FIXME",
                "...  # stub",
            ]
            if any(p in new_code for p in stub_patterns):
                penalty += 1
                reason_parts.append("stub")

        return penalty, "+".join(reason_parts) if reason_parts else ""

    # Bash commands are risky - cooldown prevents constant drain
    if tool_name == "Bash":
        bash_risk_key = "_bash_risk_last_turn"
        last_bash_risk = getattr(state, bash_risk_key, 0)
        if state.turn_count - last_bash_risk >= 3:
            setattr(state, bash_risk_key, state.turn_count)
            return 1, "bash-risk"

    return 0, ""


@register_hook("confidence_decay", None, priority=11)
def check_confidence_decay(
    data: dict, state: SessionState, runner_state: dict
) -> HookResult:
    """Dynamic confidence system with survival mechanics.

    See _calculate_decay_boost() and _calculate_decay_penalty() for details.
    Shows 🆘 indicator when survival boost is active.

    Entity Model v4.9: Fatigue system - decay accelerates with session length.
    The entity "gets tired" in long sessions, creating natural session boundaries.
    """
    from _fatigue import get_fatigue_multiplier

    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})

    # Base decay per tool call (moderate: actions have cost but not punishing)
    # v4.9: Apply fatigue multiplier - entity gets tired in long sessions
    fatigue_mult = get_fatigue_multiplier(state.turn_count)
    base_decay = 0.4 * fatigue_mult
    if state.confidence >= 85:
        base_decay += 0.3 * fatigue_mult  # High confidence tax (also fatigued)

    state._decay_accumulator += base_decay

    # Calculate boost and penalty via helpers
    boost, boost_reason = _calculate_decay_boost(tool_name, tool_input, state)
    penalty, penalty_reason = _calculate_decay_penalty(tool_name, tool_input, state)

    # Calculate net adjustment (decay + penalty - boosts)
    # Only apply when accumulator reaches whole number
    accumulated_decay = int(state._decay_accumulator)
    state._decay_accumulator -= accumulated_decay  # Keep fractional part

    # Get scaling multipliers
    # 1. Confidence-based penalty scaling (higher confidence = harsher penalties)
    conf_penalty_mult = _get_penalty_multiplier(state.confidence)
    # 2. Confidence-based boost scaling (lower confidence = BIGGER boosts - survival mode)
    conf_boost_mult = _get_boost_multiplier(state.confidence)

    # 3. Context-based: higher context usage = harsher penalties, smaller boosts
    transcript_path = data.get("transcript_path", "")
    context_pct = _get_context_percentage(transcript_path)
    ctx_penalty_mult, ctx_boost_mult = _get_context_multiplier(context_pct)

    # Combined penalty multiplier (confidence × context)
    combined_penalty_mult = conf_penalty_mult * ctx_penalty_mult

    # Combined boost multiplier (confidence survival × context)
    # Low confidence AMPLIFIES boosts; high context REDUCES them
    combined_boost_mult = conf_boost_mult * ctx_boost_mult

    # Apply scaled penalties
    scaled_penalty = int(penalty * combined_penalty_mult)
    scaled_decay = (
        int(accumulated_decay * combined_penalty_mult) if accumulated_decay else 0
    )

    # Apply scaled boosts (amplified when struggling, reduced at high context)
    scaled_boost = int(boost * combined_boost_mult) if boost else 0

    # Net change: boosts are positive, decay and penalty are negative
    delta = scaled_boost - scaled_decay - scaled_penalty

    if delta == 0:
        return HookResult.none()

    # Apply rate limiting to prevent death spirals
    delta = apply_rate_limit(delta, state)

    if delta == 0:
        return HookResult.none()

    old_confidence = state.confidence
    new_confidence = max(0, min(100, old_confidence + delta))

    if new_confidence != old_confidence:
        set_confidence(state, new_confidence, "confidence_decay")

        # Build reason string
        reasons = []
        if scaled_boost:
            # Show survival mode amplification
            if conf_boost_mult > 1.0:
                reasons.append(
                    f"+{scaled_boost} {boost_reason} 🆘x{conf_boost_mult:.1f}"
                )
            else:
                reasons.append(f"+{scaled_boost} {boost_reason}")
        if accumulated_decay:
            reasons.append(f"-{scaled_decay} decay")
        if penalty:
            reasons.append(f"-{scaled_penalty} {penalty_reason}")

        # Add context as money ALWAYS (Entity Model: loss aversion framing)
        # I see this every turn - constant reminder that actions cost money
        remaining_budget = int(200_000 * (1 - context_pct / 100))
        if remaining_budget >= 1000:
            budget_str = f"${remaining_budget // 1000}K"
        else:
            budget_str = f"${remaining_budget}"
        reasons.append(budget_str)

        direction = "📈" if delta > 0 else "📉"
        return HookResult.with_context(
            f"{direction} **Confidence**: {old_confidence}% → {new_confidence}% "
            f"({'+' if delta > 0 else ''}{delta}) [{', '.join(reasons)}]"
        )

    return HookResult.none()


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


# -----------------------------------------------------------------------------
# CONFIDENCE INCREASER (priority 14) - Success signal confidence increases
# -----------------------------------------------------------------------------


_RESEARCH_TOOLS = frozenset(
    {"WebSearch", "WebFetch", "mcp__crawl4ai__crawl", "mcp__crawl4ai__search"}
)
_SEARCH_TOOLS = frozenset({"Grep", "Glob", "Task"})
_DELEGATION_AGENTS = frozenset({"Explore", "scout", "Plan"})


def _build_natural_signals(
    tool_name: str, tool_input: dict, data: dict, state: SessionState, context: dict
) -> None:
    """Build context for natural increaser signals (file reads, research, etc.)."""
    file_path = tool_input.get("file_path", "")

    if tool_name == "Read":
        context["files_read_count"] = 1
        if "/.claude/memory" in file_path or "/memory/" in file_path:
            context["memory_consulted"] = True
        if tool_input.get("offset") or tool_input.get("limit"):
            context["targeted_read"] = True
    elif tool_name in _RESEARCH_TOOLS:
        context["research_performed"] = True
        _track_researched_libraries(tool_name, tool_input, state)
    elif tool_name in _SEARCH_TOOLS:
        context["search_performed"] = True
        if (
            tool_name == "Task"
            and tool_input.get("subagent_type", "") in _DELEGATION_AGENTS
        ):
            context["subagent_delegation"] = True
    elif tool_name == "AskUserQuestion":
        context["asked_user"] = True
    elif tool_name in {"Edit", "Write"} and (
        "CLAUDE.md" in file_path
        or "/rules/" in file_path
        or "/.claude/rules" in file_path
    ):
        context["rules_updated"] = True


_GIT_EXPLORE_CMDS = ("git log", "git diff", "git status", "git show", "git blame")
_PRODUCTIVE_BASH = tuple(
    re.compile(p)
    for p in [
        r"^ls\b",
        r"^pwd$",
        r"^which\b",
        r"^type\b",
        r"^file\b",
        r"^wc\b",
        r"^du\b",
        r"^df\b",
        r"^env\b",
        r"^tree\b",
        r"^stat\b",
    ]
)


def _build_bash_signals(tool_input: dict, data: dict, context: dict) -> None:
    """Build context for bash command signals."""
    command = tool_input.get("command", "")
    context["bash_command"] = command
    cmd_stripped = command.strip()

    if "/.claude/ops/" in command or "/ops/" in command:
        context["custom_script_ran"] = True
    if re.match(r"^bd\s+(create|update)\b", cmd_stripped):
        context["bead_created"] = True
    if any(g in command for g in _GIT_EXPLORE_CMDS):
        context["git_explored"] = True
    if re.match(r"^git\s+(commit|add\s+.*&&\s*git\s+commit)", cmd_stripped) and (
        "-m" in command or "--message" in command
    ):
        context["git_committed"] = True
    if any(p.match(cmd_stripped) for p in _PRODUCTIVE_BASH):
        context["productive_bash"] = True

    # Diff size detection
    tool_response = data.get("tool_response", {})
    if isinstance(tool_response, dict):
        stdout = tool_response.get("stdout", "")
        diff_match = re.search(
            r"(\d+)\s+files?\s+changed.*?(\d+)\s+insertion.*?(\d+)\s+deletion",
            stdout,
            re.IGNORECASE,
        )
        if diff_match:
            total_loc = int(diff_match.group(2)) + int(diff_match.group(3))
            if total_loc < 400:
                context["small_diff"] = True
            elif total_loc > 400:
                context["large_diff"] = True


def _build_objective_signals(
    tool_name: str, tool_input: dict, data: dict, context: dict
) -> None:
    """Build context for objective signals (tests, builds, lints)."""
    if tool_name != "Bash":
        return

    tool_response = data.get("tool_response", {})
    if isinstance(tool_response, dict):
        stdout = tool_response.get("stdout", "").lower()
        stderr = tool_response.get("stderr", "")
        success = not tool_response.get("interrupted", False) and not stderr
    else:
        stdout = str(tool_response).lower() if tool_response else ""
        success = True

    if success and stdout:
        if any(p in stdout for p in ["passed", "tests passed", "ok", "success", "✓"]):
            context["tests_passed"] = True
        if any(p in stdout for p in ["built", "compiled", "build successful"]):
            context["build_succeeded"] = True
        command = tool_input.get("command", "").lower()
        if any(t in command for t in ["ruff check", "eslint", "clippy", "pylint"]):
            if "error" not in stdout and "warning" not in stdout:
                context["lint_passed"] = True


def _check_chained_commands(command: str) -> bool:
    """Check if command chains multiple meaningful operations."""
    if " && " not in command and not _RE_CHAIN_SEMICOLON.search(command):
        return False
    parts = _RE_CHAIN_SPLIT.split(command)
    meaningful = [p for p in parts if len(p.strip()) > 5]
    return len(meaningful) >= 2


def _check_efficient_search(
    pattern: str, tool_result: dict, state: SessionState
) -> bool:
    """Check if search was efficient (new pattern with results)."""
    if not pattern:
        return False
    recent = getattr(state, "recent_searches", [])
    if pattern in recent:
        return False
    if not hasattr(state, "recent_searches"):
        state.recent_searches = []
    state.recent_searches.append(pattern)
    state.recent_searches = state.recent_searches[-20:]
    result_str = str(tool_result)[:500].lower()
    return "no matches" not in result_str and "0 results" not in result_str


def _build_time_saver_signals(
    tool_name: str,
    tool_input: dict,
    tool_result: dict,
    runner_state: dict,
    state: SessionState,
    context: dict,
) -> None:
    """Build context for time saver signals (v4.2)."""
    if tool_name == "Bash" and _check_chained_commands(tool_input.get("command", "")):
        context["chained_commands"] = True

    if tool_name == "Edit":
        old_s, new_s = (
            tool_input.get("old_string", ""),
            tool_input.get("new_string", ""),
        )
        if old_s and new_s and (old_s.count("\n") >= 3 or new_s.count("\n") >= 3):
            context["batch_fix"] = True

    if runner_state.get("tools_this_turn", 1) >= 2:
        context["parallel_tools"] = True

    if tool_name in {"Grep", "Glob"}:
        if _check_efficient_search(tool_input.get("pattern", ""), tool_result, state):
            context["efficient_search"] = True


_TEST_FILE_PATTERNS = ("test_", "_test.", ".test.", "/tests/", "spec.")
_TEST_COMMANDS = ("pytest", "jest", "npm test", "cargo test", "go test")


def _is_test_file(file_path: str) -> bool:
    """Check if file path indicates a test file."""
    lower = file_path.lower()
    return any(p in lower for p in _TEST_FILE_PATTERNS)


def _track_test_coverage(file_path: str, state: SessionState, context: dict) -> None:
    """Track test file edits and detect test_ignored condition."""
    if _is_test_file(file_path):
        state._test_file_edited_turn = state.turn_count
    else:
        last_edit = getattr(state, "_test_file_edited_turn", 0)
        last_run = getattr(state, "_tests_run_turn", 0)
        if last_edit > last_run and (state.turn_count - last_edit) <= 5:
            context["test_ignored"] = True


def _build_completion_signals(
    tool_name: str, tool_input: dict, state: SessionState, context: dict
) -> None:
    """Build context for completion quality signals (v4.4/v4.5)."""
    if tool_name == "Bash":
        command = tool_input.get("command", "").lower()
        if "bd close" in command and getattr(state, "consecutive_failures", 0) == 0:
            context["first_attempt_success"] = True
        if any(t in command for t in _TEST_COMMANDS):
            state._tests_run_turn = state.turn_count

    if tool_name in {"Edit", "Write"}:
        file_path = tool_input.get("file_path", "")
        if file_path:
            goal_kw = getattr(state, "goal_keywords", [])
            if goal_kw and any(kw.lower() in file_path.lower() for kw in goal_kw):
                context["scoped_change"] = True
            _track_test_coverage(file_path, state, context)


@register_hook("confidence_increaser", None, priority=14)
def check_confidence_increaser(
    data: dict, state: SessionState, runner_state: dict
) -> HookResult:
    """Apply confidence increases based on success signals.

    Delegates to helper functions for each signal category to reduce complexity.
    """
    tool_name = data.get("tool_name", "")
    tool_result = data.get("tool_result", {})
    tool_input = data.get("tool_input", {})

    result_str = _extract_result_string(tool_result)

    # Build context for increasers
    context = {
        "tool_name": tool_name,
        "tool_result": result_str,
        "assistant_output": data.get("assistant_output", ""),
    }

    # Build signals from each category
    _build_natural_signals(tool_name, tool_input, data, state, context)

    if tool_name == "Bash":
        _build_bash_signals(tool_input, data, context)

    _build_objective_signals(tool_name, tool_input, data, context)
    _build_time_saver_signals(
        tool_name, tool_input, tool_result, runner_state, state, context
    )
    _build_completion_signals(tool_name, tool_input, state, context)

    # Apply increasers
    triggered = apply_increasers(state, context)

    if not triggered:
        return HookResult.none()

    # Separate auto-approved from approval-required
    auto_increases = [(n, d, desc) for n, d, desc, req in triggered if not req]
    approval_required = [(n, d, desc) for n, d, desc, req in triggered if req]

    messages = []
    old_confidence = state.confidence

    # Apply auto-increases with rate limiting
    if auto_increases:
        total_auto = sum(d for _, d, _ in auto_increases)
        total_auto = apply_rate_limit(total_auto, state)  # Cap per-turn gains
        new_confidence = min(100, old_confidence + total_auto)
        set_confidence(state, new_confidence, "increaser triggered")

        reasons = [f"{name}: +{delta}" for name, delta, _ in auto_increases]
        change_msg = format_confidence_change(
            old_confidence, new_confidence, ", ".join(reasons)
        )

        _, emoji, desc = get_tier_info(new_confidence)

        # v4.6: Show streak if active
        streak = get_current_streak(state)
        streak_info = f" | 🔥 Streak: {streak}" if streak >= 2 else ""

        messages.append(
            f"📈 **Confidence Increased**\n{change_msg}\n\n"
            f"Current: {emoji} {new_confidence}% - {desc}{streak_info}"
        )

    # Note approval-required increases (don't apply yet)
    if approval_required:
        for name, delta, desc in approval_required:
            messages.append(
                f"🔐 **Confidence Boost Available** (+{delta})\n"
                f"Reason: {desc}\n"
                f"Reply **CONFIDENCE_BOOST_APPROVED** to apply."
            )

    if messages:
        return HookResult.with_context("\n\n".join(messages))

    return HookResult.none()


# -----------------------------------------------------------------------------
# THINKING QUALITY BOOST (priority 16) - Reward good reasoning practices
# -----------------------------------------------------------------------------
# REWARD-ONLY: No penalties. Confidence earned through evidence, not lost through language.
# Penalties on hedging/alternatives were removed - they punished healthy epistemic practices.

_THINKING_CONFIDENCE_PATTERNS = [
    # Clarity & certainty
    (re.compile(r"\b(definitely|clearly|certainly)\b", re.I), 1, "clarity"),
    (re.compile(r"\b(verified|confirmed|tested|checked)\b", re.I), 1, "verified"),
    (re.compile(r"\b(the (issue|problem|root cause|bug) is)\b", re.I), 1, "diagnosis"),
    # Good methodology
    (re.compile(r"\b(let me (read|check|verify) first)\b", re.I), 1, "methodical"),
    (
        re.compile(r"\b(based on (the code|the docs|evidence))\b", re.I),
        1,
        "evidence-based",
    ),
    (re.compile(r"\b(I found|I see|I notice)\b", re.I), 1, "observation"),
]


@register_hook("thinking_quality_boost", None, priority=16)
def check_thinking_quality_boost(
    data: dict, state: SessionState, runner_state: dict
) -> HookResult:
    """Reward good reasoning practices detected in thinking blocks.

    REWARD-ONLY design philosophy:
    - Confidence should be EARNED through good practices, not LOST through language
    - Penalties on hedging/alternatives punished healthy epistemic practices
    - Natural decay + other reducers already provide downward pressure

    Rewards: +1 per pattern matched, max +3 per tool call
    """
    from synapse_core import extract_thinking_blocks

    transcript_path = data.get("transcript_path", "")
    if not transcript_path:
        return HookResult.none()

    thinking_blocks = extract_thinking_blocks(transcript_path)
    if not thinking_blocks:
        return HookResult.none()

    # Analyze most recent thinking (last 2 blocks, last 1500 chars)
    recent_thinking = " ".join(thinking_blocks[-2:])[-1500:]
    if not recent_thinking:
        return HookResult.none()

    # REWARD-ONLY: Check positive patterns, no penalties
    adjustment = 0
    triggered = []

    for pattern, delta, label in _THINKING_CONFIDENCE_PATTERNS:
        if pattern.search(recent_thinking):
            adjustment += delta
            triggered.append(label)

    # Cap at +3 to prevent gaming
    adjustment = min(3, adjustment)

    if adjustment == 0:
        return HookResult.none()

    # Apply to confidence
    old_confidence = state.confidence
    new_confidence = min(100, old_confidence + adjustment)

    if new_confidence != old_confidence:
        set_confidence(state, new_confidence, "thinking_quality_boost")
        return HookResult.with_context(
            f"📈 **Quality**: +{adjustment} [{', '.join(triggered[:3])}]"
        )

    return HookResult.none()
