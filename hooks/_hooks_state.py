"""
State management PostToolUse hooks and shared utilities.

Hooks:
  - check_serena_activation (priority 9)
  - check_state_updater (priority 10)

Shared utilities used by other _hooks_state_*.py modules:
  - _extract_result_string: Extract string from tool results
  - get_mastermind_drift_signals: Get drift signals for reducers

Related modules (extracted for maintainability):
  - _hooks_state_pal.py: PAL mandate hook (priority 5)
  - _hooks_state_decay.py: Confidence decay (priority 11)
  - _hooks_state_reducers.py: Confidence reducers (priority 12)
  - _hooks_state_increasers.py: Confidence increasers (priority 14-16)
"""

import _lib_path  # noqa: F401
import json
import re
from pathlib import Path

from _hook_registry import register_hook
from _hook_result import HookResult

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


# PAL mandate hook moved to _hooks_state_pal.py


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

    # Track files read via cat/head/tail (normalize paths for gap_detector matching)
    if success:
        read_cmds = ["cat ", "head ", "tail ", "less ", "more "]
        if any(command.startswith(cmd) or f" {cmd}" in command for cmd in read_cmds):
            for part in command.split()[1:]:
                if not part.startswith("-") and ("/" in part or "." in part):
                    # Normalize path: expand ~ and resolve to absolute path
                    normalized = part
                    if part.startswith("~"):
                        normalized = str(Path(part).expanduser())
                    elif not part.startswith("/"):
                        # Relative path - make absolute from cwd
                        normalized = str(Path.cwd() / part)
                    # Resolve any .. or . in path (keep original on OSError)
                    try:
                        normalized = str(Path(normalized).resolve())
                    except OSError:
                        pass  # Keep expanded path if resolve fails
                    track_file_read(state, normalized)

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


# Confidence decay hook (priority 11) moved to _hooks_state_decay.py


# Confidence reducer hook (priority 12) moved to _hooks_state_reducers.py
# Confidence increaser hooks (priority 14-16) moved to _hooks_state_increasers.py
