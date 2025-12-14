#!/usr/bin/env python3
"""
Composite PostToolUse Runner: Runs all PostToolUse hooks in a single process.

PERFORMANCE: ~40ms for 8 hooks vs ~300ms for individual processes (7x faster)

HOOKS INDEX (by priority):
  STATE (0-20):
    10 state_updater       - Track files read/edited, commands, libraries, errors
    11 confidence_decay    - Natural decay + tool boosts (context-scaled)
    12 confidence_reducer  - Apply deterministic confidence reductions on failures
    14 confidence_increaser - Apply confidence increases on success signals
    16 thinking_quality_boost - Reward good reasoning (evidence, verification, diagnosis)

  QUALITY GATES (22-50):
    22 assumption_check    - Surface hidden assumptions in code changes
    25 verification_reminder - Remind to verify after fix iterations
    30 ui_verification     - Remind to screenshot after CSS/UI changes
    35 code_quality_gate   - Detect anti-patterns (N+1, O(n³), blocking I/O, nesting)
    37 state_mutation_guard - Detect React/Python mutation anti-patterns
    40 dev_toolchain_suggest - Suggest lint/format/typecheck per language
    45 large_file_helper   - Line range guidance for big files
    48 crawl4ai_promo      - Promote crawl4ai over WebFetch for web content
    50 tool_awareness      - Remind about Playwright, Zen MCP, WebSearch, Task agents

  TRACKERS (55-80):
    55 scratch_enforcer    - Detect repetitive patterns, suggest scripts
    60 auto_learn          - Capture lessons from errors, quality hints
    65 velocity_tracker    - Detect oscillation/spinning patterns
    70 info_gain_tracker   - Detect reads without progress

ARCHITECTURE:
  - Hooks register via @register_hook(name, matcher, priority)
  - Lower priority = runs first
  - All hooks run (no blocking for PostToolUse)
  - Contexts are aggregated and returned
  - Single state load/save per invocation
"""

import _lib_path  # noqa: F401
import sys
import json
import os
import re
import time
from typing import Optional, Callable
from pathlib import Path
from collections import Counter

# Performance: centralized configuration
from _cooldown import (
    assumption_cooldown,
    mutation_cooldown,
    toolchain_keyed,
    large_file_keyed,
    tool_awareness_keyed,
    crawl4ai_promo_keyed,
    beads_sync_cooldown,
)
from _patterns import is_scratch_path

from session_state import (
    load_state,
    save_state,
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
    # Adaptive threshold learning (v3.7)
    get_adaptive_threshold,
    record_threshold_trigger,
    # Ops tool tracking (v3.9)
    track_ops_tool,
    mark_production_verified,
    set_confidence,
)
from _hook_result import HookResult

# Confidence system imports (v4.0)
from confidence import (
    apply_reducers,
    apply_increasers,
    apply_rate_limit,
    format_confidence_change,
    get_tier_info,
    format_dispute_instructions,
    # v4.6: Trajectory prediction
    predict_trajectory,
    format_trajectory_warning,
    get_current_streak,
)

# Quality scanner (ruff + radon)
try:
    from _quality_scanner import scan_file as quality_scan_file, format_report

    QUALITY_SCANNER_AVAILABLE = True
except ImportError:
    QUALITY_SCANNER_AVAILABLE = False
    quality_scan_file = None
    format_report = None

# =============================================================================
# PRE-COMPILED PATTERNS (Performance: compile once at module load)
# =============================================================================

# Assumption detection patterns
_ASSUMPTION_PATTERNS = [
    (re.compile(r"\bNone\b"), "Assuming value is not None - verify nullability"),
    (re.compile(r"\[0\]|\[-1\]"), "Assuming collection is non-empty - check edge case"),
    (
        re.compile(r"\.get\([^,)]+\)"),
        "Using .get() - verify default behavior is correct",
    ),
    (re.compile(r"try:\s*\n\s*\w"), "Assuming exception handling covers all cases"),
    (re.compile(r"await\s+\w+"), "Assuming async operation succeeds - handle failures"),
    (re.compile(r"open\(|Path\(.*\)\.read"), "Assuming file exists and is readable"),
    (re.compile(r"json\.loads|JSON\.parse"), "Assuming valid JSON input"),
    (re.compile(r'\[\s*["\'][^"\']+["\']\s*\]'), "Assuming key exists in dict/object"),
]

# UI file detection patterns
_UI_FILE_PATTERNS = [
    re.compile(r"\.css$", re.IGNORECASE),
    re.compile(r"\.scss$", re.IGNORECASE),
    re.compile(r"\.less$", re.IGNORECASE),
    re.compile(r"\.sass$", re.IGNORECASE),
    re.compile(r"style", re.IGNORECASE),
    re.compile(r"theme", re.IGNORECASE),
    re.compile(r"\.tsx$", re.IGNORECASE),
    re.compile(r"\.vue$", re.IGNORECASE),
    re.compile(r"\.svelte$", re.IGNORECASE),
]

# Style content patterns
_STYLE_CONTENT_PATTERNS = [
    re.compile(r"className\s*="),
    re.compile(r"style\s*=\s*\{"),
    re.compile(r"styled\."),
    re.compile(r"css`"),
    re.compile(r"@apply\s+"),
    re.compile(r"sx\s*=\s*\{"),
    re.compile(r'class\s*=\s*["\'][\w\s-]+["\']'),
    re.compile(r"(background|color|margin|padding|display|flex|grid|width|height)\s*:"),
]

# React/JS mutation patterns
_JS_MUTATION_PATTERNS = [
    (
        re.compile(r"\.(push|pop|shift|unshift|splice)\s*\("),
        "Array mutation ({0}) - use spread: [...arr, item]",
    ),
    (re.compile(r"\.sort\s*\(\s*\)"), "In-place sort - use [...arr].sort()"),
    (re.compile(r"\.reverse\s*\(\s*\)"), "In-place reverse - use [...arr].reverse()"),
    (
        re.compile(r"set[A-Z]\w*\(\s*\w+\s*\.\s*\w+\s*="),
        "State mutation in setter - use spread: setState({{...prev, key: val}})",
    ),
]

# Python mutation patterns - now AST-based in _ast_utils.find_mutable_defaults()

# Spread operator check for JS mutation guard
_SPREAD_CHECK = re.compile(r"\[\.\.\.\w+\]\s*$")

# =============================================================================
# HOOK REGISTRY
# =============================================================================

# Format: (name, matcher_pattern, check_function, priority)
# Lower priority = runs first
# matcher_pattern: None = all tools, str = regex pattern
HOOKS: list[tuple[str, Optional[str], Callable, int]] = []


def register_hook(name: str, matcher: Optional[str], priority: int = 50):
    """Decorator to register a hook check function.

    Hooks can be disabled via environment variable:
        CLAUDE_HOOK_DISABLE_<NAME>=1

    Example:
        CLAUDE_HOOK_DISABLE_ASSUMPTION_CHECK=1 claude
    """

    def decorator(func: Callable[[dict, SessionState, dict], HookResult]):
        # Check if hook is disabled via environment variable
        env_key = f"CLAUDE_HOOK_DISABLE_{name.upper()}"
        if os.environ.get(env_key, "0") == "1":
            return func  # Skip registration
        HOOKS.append((name, matcher, func, priority))
        return func

    return decorator


# =============================================================================
# HOOK IMPLEMENTATIONS
# =============================================================================

# -----------------------------------------------------------------------------
# STATE UPDATER (priority 10) - Must run first to update state for other hooks
# -----------------------------------------------------------------------------

_RE_PYTEST_FAIL = re.compile(r"FAILED\s+([\w./]+)::(\w+)")
_RE_JEST_FAIL = re.compile(r"FAIL\s+([\w./]+)\s*\n.*?✕\s+(.+?)(?:\n|$)", re.MULTILINE)
_RE_GENERIC_FAIL = re.compile(r"(?:Error|FAIL|FAILED):\s*(.+?)(?:\n|$)")

_TODO_PATTERNS = [
    (re.compile(r"#\s*TODO[:\s]+(.+?)(?:\n|$)", re.IGNORECASE), "TODO"),
    (re.compile(r"//\s*TODO[:\s]+(.+?)(?:\n|$)", re.IGNORECASE), "TODO"),
    (re.compile(r"#\s*FIXME[:\s]+(.+?)(?:\n|$)", re.IGNORECASE), "FIXME"),
    (re.compile(r"//\s*FIXME[:\s]+(.+?)(?:\n|$)", re.IGNORECASE), "FIXME"),
]


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


# =============================================================================
# EXPLORATION CACHE (Priority 5) - Cache Explore agent results
# =============================================================================


@register_hook("exploration_cacher", "Task", priority=5)
def check_exploration_cacher(
    data: dict, state: SessionState, runner_state: dict
) -> HookResult:
    """
    Cache exploration results after Task(Explore) completes.

    This stores the agent's output so future similar queries can be served
    from cache instead of re-running the agent.
    """
    tool_input = data.get("tool_input", {})
    subagent_type = tool_input.get("subagent_type", "")

    # Only cache Explore agents
    if subagent_type.lower() != "explore":
        return HookResult.allow()

    prompt = tool_input.get("prompt", "")
    result = data.get("tool_result", {})

    # Get the agent's response
    agent_output = ""
    if isinstance(result, dict):
        agent_output = (
            result.get("content", "") or result.get("output", "") or str(result)
        )
    elif isinstance(result, str):
        agent_output = result

    # Don't cache empty or error results
    if not agent_output or len(agent_output) < 50:
        return HookResult.allow()
    if "error" in agent_output.lower()[:100]:
        return HookResult.allow()

    # Detect project path
    try:
        from project_detector import detect_project

        project_info = detect_project()
        if not project_info or not project_info.get("path"):
            return HookResult.allow()
        project_path = project_info["path"]
    except Exception:
        return HookResult.allow()

    # Cache the result
    try:
        from cache.exploration_cache import cache_exploration

        cache_exploration(
            project_path=Path(project_path),
            query=prompt,
            result=agent_output[:5000],  # Limit size
            directory_path="",  # Could be extracted from prompt
            touched_files=[],  # Would need instrumentation to track
        )
    except Exception:
        pass

    return HookResult.allow()


# =============================================================================
# READ CACHE (Priority 6) - Cache Read results, Invalidate on Write/Edit
# =============================================================================


@register_hook("read_cacher", "Read", priority=6)
def check_read_cacher(
    data: dict, state: SessionState, runner_state: dict
) -> HookResult:
    """
    Cache successful Read results for memoization.

    Only caches full file reads (no offset/limit).
    """
    tool_input = data.get("tool_input", {})
    file_path = tool_input.get("file_path", "")

    if not file_path:
        return HookResult.allow()

    # Don't cache partial reads
    if tool_input.get("offset") or tool_input.get("limit"):
        return HookResult.allow()

    result = data.get("tool_result", {})

    # Get the file content from result
    content = ""
    if isinstance(result, dict):
        content = result.get("content", "") or result.get("output", "") or ""
    elif isinstance(result, str):
        content = result

    # Don't cache errors or empty results
    if not content or "error" in content.lower()[:50]:
        return HookResult.allow()

    try:
        from cache.read_cache import cache_read_result

        cache_read_result(file_path, content)
    except Exception:
        pass

    return HookResult.allow()


@register_hook("read_cache_invalidator", "Write|Edit", priority=6)
def check_read_cache_invalidator(
    data: dict, state: SessionState, runner_state: dict
) -> HookResult:
    """
    Invalidate read cache when files are written or edited.

    Ensures cache consistency after modifications.
    """
    tool_input = data.get("tool_input", {})
    file_path = tool_input.get("file_path", "")

    if not file_path:
        return HookResult.allow()

    try:
        from cache.read_cache import invalidate_read_cache

        invalidate_read_cache(file_path)
    except Exception:
        pass

    return HookResult.allow()


def _handle_read_tool(tool_input: dict, result: dict, state: SessionState) -> None:
    """Handle Read tool state updates."""
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
            if is_new_file:
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


def _track_bash_failures(
    command: str, output: str, success: bool, state: SessionState
) -> None:
    """Track failures, errors, and self-heal triggers."""
    approach_sig = (
        f"Bash:{command.split()[0][:20]}" if command.split() else "Bash:unknown"
    )

    # Detect and classify errors
    if not success or "error" in output.lower() or "failed" in output.lower():
        error_patterns = [
            (r"(\d{3})\s*(Unauthorized|Forbidden|Not Found)", "HTTP error"),
            (r"(ModuleNotFoundError|ImportError)", "Import error"),
            (r"(SyntaxError|TypeError|ValueError)", "Python error"),
            (r"(ENOENT|EACCES|EPERM)", "Filesystem error"),
            (r"(connection refused|timeout)", "Network error"),
        ]
        error_type = "Command error"
        for pattern, etype in error_patterns:
            if re.search(pattern, output, re.IGNORECASE):
                error_type = etype
                break
        if not success:
            track_error(state, error_type, output[:500])
            track_failure(state, approach_sig)

            # SELF-HEAL: Detect framework errors
            if ".claude/" in command or ".claude\\" in command:
                _trigger_self_heal(
                    state,
                    target=command.split()[0] if command.split() else "bash",
                    error=output[:200],
                )

    # SELF-HEAL: Clear if successful operation on framework files
    if success and getattr(state, "self_heal_required", False):
        if ".claude/" in command or ".claude\\" in command:
            _clear_self_heal(state)

    # Resolve errors on success
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
    for failure in extract_test_failures(output):
        add_work_item(
            state,
            item_type="test_failure",
            source=failure.get("file", "tests"),
            description=failure.get("description", "Fix test failure"),
            priority=failure.get("priority", 80),
        )


def _handle_bash_tool(tool_input: dict, result: dict, state: SessionState) -> None:
    """Handle Bash tool state updates. Delegates to specialized trackers."""
    command = tool_input.get("command", "")
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


@register_hook("state_updater", None, priority=10)
def check_state_updater(
    data: dict, state: SessionState, runner_state: dict
) -> HookResult:
    """Update session state based on tool usage.

    Delegates to helper functions for each tool type.
    """
    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})
    result = data.get("tool_result", {})
    if isinstance(result, str):
        result = {"output": result}
    elif not isinstance(result, dict):
        result = {}
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

    elif tool_name == "Grep":
        pattern = tool_input.get("pattern", "")
        add_domain_signal(state, pattern)
        if pattern:
            clear_pending_search(state, pattern)
            clear_integration_grep(state, pattern)

    elif tool_name == "Glob":
        pattern = tool_input.get("pattern", "")
        add_domain_signal(state, pattern)
        if pattern:
            clear_pending_search(state, pattern)

    elif tool_name == "Task":
        prompt = tool_input.get("prompt", "")
        add_domain_signal(state, prompt[:200])

    # Track last tool for sequential repetition detection
    bash_cmd = ""
    if tool_name == "Bash":
        bash_cmd = tool_input.get("command", "")[
            :50
        ]  # First 50 chars for pattern matching
    state.last_tool_info = {
        "tool_name": tool_name,
        "turn": state.turn_count,
        "bash_cmd": bash_cmd,
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
_DEFAULT_CONTEXT_WINDOW = 200000


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


def _calculate_decay_boost(
    tool_name: str, tool_input: dict, state: SessionState
) -> tuple[float, str]:
    """Calculate recovery action boosts for confidence decay.

    Returns (boost_value, boost_reason).
    """
    # PAL external consultation - shows humility, seeking help
    if tool_name.startswith("mcp__pal__"):
        pal_tool = tool_name.replace("mcp__pal__", "")
        if pal_tool in ("thinkdeep", "debug", "codereview", "consensus", "precommit"):
            return 2, f"pal-{pal_tool}"
        elif pal_tool in ("chat", "challenge", "apilookup"):
            return 1, f"pal-{pal_tool}"

    # User clarification - reaching out shows humility
    if tool_name == "AskUserQuestion":
        return 2, "user-clarification"

    # Agent delegation - distributing work wisely
    if tool_name == "Task":
        return 1.5, "agent-delegation"

    # Read - diminishing returns
    if tool_name == "Read":
        read_count = len([f for f in state.files_read if f])
        if read_count <= 3:
            return 0.5, f"file-read({read_count})"
        elif read_count <= 6:
            return 0.25, f"file-read({read_count})"
        return 0.1, f"file-read({read_count})"

    # Memory access
    if tool_name.startswith("mcp__") and "mem" in tool_name.lower():
        return 0.5, "memory-access"

    # Web research
    if tool_name in ("WebSearch", "WebFetch"):
        return 0.5, "web-research"

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
    """
    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})

    # Base decay per tool call (moderate: actions have cost but not punishing)
    base_decay = 0.4
    if state.confidence >= 85:
        base_decay += 0.3  # High confidence tax

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

        # Add context pressure indicator if significant
        if context_pct >= 40:
            reasons.append(f"CTX:{context_pct:.0f}%")

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

    context = {
        "tool_name": tool_name,
        "tool_result": tool_result,
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


def _detect_time_wasters(
    tool_name: str, tool_input: dict, tool_result: dict, state: SessionState, ctx: dict
) -> None:
    """Detect time waster patterns (v4.2)."""
    # Re-read unchanged file
    if tool_name == "Read":
        file_path = tool_input.get("file_path", "")
        if file_path:
            files_read = getattr(state, "files_read", {})
            files_edited = getattr(state, "files_edited", [])
            if file_path in files_read:
                last_read_turn = files_read.get(file_path, {}).get("turn", 0)
                edited_after = False
                for entry in files_edited:
                    if isinstance(entry, dict):
                        if entry.get("path") == file_path:
                            if entry.get("turn", 0) > last_read_turn:
                                edited_after = True
                                break
                    elif isinstance(entry, str) and entry == file_path:
                        edited_after = True
                        break
                if not edited_after:
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

    # Build context and detect patterns
    context = _build_reducer_context(tool_name, tool_input, tool_result, data, state)
    _detect_tool_failures(tool_name, tool_input, tool_result, state, context)
    _detect_repetition_patterns(tool_name, tool_input, state, context)
    _detect_time_wasters(tool_name, tool_input, tool_result, state, context)
    _detect_incomplete_refactor(tool_name, tool_input, tool_result, state, context)

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


def _build_natural_signals(
    tool_name: str, tool_input: dict, data: dict, state: SessionState, context: dict
) -> None:
    """Build context for natural increaser signals (file reads, research, etc.)."""
    # File reads = gathering evidence (+1)
    if tool_name == "Read":
        file_path = tool_input.get("file_path", "")
        context["files_read_count"] = 1
        if "/.claude/memory" in file_path or "/memory/" in file_path:
            context["memory_consulted"] = True
        # v4.6: Targeted read with offset/limit saves tokens
        if tool_input.get("offset") or tool_input.get("limit"):
            context["targeted_read"] = True

    # Research tools = due diligence (+2)
    if tool_name in {
        "WebSearch",
        "WebFetch",
        "mcp__crawl4ai__crawl",
        "mcp__crawl4ai__search",
    }:
        context["research_performed"] = True
        _track_researched_libraries(tool_name, tool_input, state)

    # Search tools = gathering understanding (+2)
    if tool_name in {"Grep", "Glob", "Task"}:
        context["search_performed"] = True
        # v4.6: Subagent delegation saves main context
        if tool_name == "Task":
            subagent_type = tool_input.get("subagent_type", "")
            if subagent_type in {"Explore", "scout", "Plan"}:
                context["subagent_delegation"] = True

    # Asking user = epistemic humility (+20)
    if tool_name == "AskUserQuestion":
        context["asked_user"] = True

    # Rules/docs updates = system improvement (+3)
    if tool_name in {"Edit", "Write"}:
        file_path = tool_input.get("file_path", "")
        if (
            "CLAUDE.md" in file_path
            or "/rules/" in file_path
            or "/.claude/rules" in file_path
        ):
            context["rules_updated"] = True


def _build_bash_signals(tool_input: dict, data: dict, context: dict) -> None:
    """Build context for bash command signals."""
    command = tool_input.get("command", "")
    context["bash_command"] = command

    # Custom ops scripts = using tools (+5)
    if "/.claude/ops/" in command or "/ops/" in command:
        context["custom_script_ran"] = True

    # Bead creation = planning work (+10)
    if re.match(r"^bd\s+(create|update)\b", command.strip()):
        context["bead_created"] = True

    # Git exploration = understanding context (+10)
    git_explore_cmds = ["git log", "git diff", "git status", "git show", "git blame"]
    if any(g in command for g in git_explore_cmds):
        context["git_explored"] = True

    # Git commit with message = saving work (+3)
    if re.match(r"^git\s+(commit|add\s+.*&&\s*git\s+commit)", command.strip()):
        if "-m" in command or "--message" in command:
            context["git_committed"] = True

    # Productive bash = non-risky inspection commands (+1)
    productive_patterns = [
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
    if any(re.match(p, command.strip()) for p in productive_patterns):
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


def _build_time_saver_signals(
    tool_name: str,
    tool_input: dict,
    tool_result: dict,
    runner_state: dict,
    state: SessionState,
    context: dict,
) -> None:
    """Build context for time saver signals (v4.2)."""
    # Chained commands (+1)
    if tool_name == "Bash":
        command = tool_input.get("command", "")
        if " && " in command or re.search(r";\s*\w+", command):
            parts = re.split(r"\s*&&\s*|\s*;\s*", command)
            meaningful = [p for p in parts if len(p.strip()) > 5]
            if len(meaningful) >= 2:
                context["chained_commands"] = True

    # Batch fix (+3)
    if tool_name == "Edit":
        old_string = tool_input.get("old_string", "")
        new_string = tool_input.get("new_string", "")
        if old_string and new_string:
            if old_string.count("\n") >= 3 or new_string.count("\n") >= 3:
                context["batch_fix"] = True

    # Parallel tools (+3)
    if runner_state.get("tools_this_turn", 1) >= 2:
        context["parallel_tools"] = True

    # Efficient search (+2)
    if tool_name in {"Grep", "Glob"}:
        pattern = tool_input.get("pattern", "")
        recent_searches = getattr(state, "recent_searches", [])
        if pattern and pattern not in recent_searches:
            if not hasattr(state, "recent_searches"):
                state.recent_searches = []
            state.recent_searches.append(pattern)
            state.recent_searches = state.recent_searches[-20:]
            result_str = str(tool_result)[:500].lower()
            if "no matches" not in result_str and "0 results" not in result_str:
                context["efficient_search"] = True


def _build_completion_signals(
    tool_name: str, tool_input: dict, state: SessionState, context: dict
) -> None:
    """Build context for completion quality signals (v4.4/v4.5)."""
    # First attempt success (+3)
    if tool_name == "Bash":
        command = tool_input.get("command", "").lower()
        if "bd close" in command:
            if getattr(state, "consecutive_failures", 0) == 0:
                context["first_attempt_success"] = True

    # Scoped change (+2)
    if tool_name in {"Edit", "Write"}:
        file_path = tool_input.get("file_path", "")
        goal_keywords = getattr(state, "goal_keywords", [])
        if file_path and goal_keywords:
            file_lower = file_path.lower()
            if any(kw.lower() in file_lower for kw in goal_keywords):
                context["scoped_change"] = True

    # Test coverage tracking (v4.5)
    if tool_name in {"Edit", "Write"}:
        file_path = tool_input.get("file_path", "")
        if file_path:
            is_test_file = any(
                p in file_path.lower()
                for p in ["test_", "_test.", ".test.", "/tests/", "spec."]
            )
            if is_test_file:
                state._test_file_edited_turn = state.turn_count
            else:
                last_test_edit = getattr(state, "_test_file_edited_turn", 0)
                last_test_run = getattr(state, "_tests_run_turn", 0)
                turns_since = state.turn_count - last_test_edit
                if last_test_edit > last_test_run and turns_since <= 5:
                    context["test_ignored"] = True

    # Track when tests are run
    if tool_name == "Bash":
        command = tool_input.get("command", "").lower()
        test_cmds = ["pytest", "jest", "npm test", "cargo test", "go test"]
        if any(t in command for t in test_cmds):
            state._tests_run_turn = state.turn_count


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

    # Build context for increasers
    context = {
        "tool_name": tool_name,
        "tool_result": tool_result,
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


# -----------------------------------------------------------------------------
# ASSUMPTION CHECK (priority 22) - Heuristic-based, no Groq call
# -----------------------------------------------------------------------------


@register_hook("assumption_check", "Edit|Write", priority=22)
def check_assumptions(
    data: dict, state: SessionState, runner_state: dict
) -> HookResult:
    """Surface hidden assumptions in code changes (heuristic-based)."""
    tool_input = data.get("tool_input", {})
    file_path = tool_input.get("file_path", "")

    # Skip scratch/temp files
    if is_scratch_path(file_path):
        return HookResult.none()

    code = tool_input.get("new_string", "") or tool_input.get("content", "")
    if not code or len(code) < 100:
        return HookResult.none()

    # Check cooldown (don't spam)
    if assumption_cooldown.is_active():
        return HookResult.none()

    # Find assumptions (use pre-compiled patterns)
    found = []
    for pattern, assumption in _ASSUMPTION_PATTERNS:
        if pattern.search(code):
            found.append(assumption)
            if len(found) >= 2:
                break

    if found:
        assumption_cooldown.reset()
        return HookResult.with_context(
            "🤔 **ASSUMPTION CHECK**:\n" + "\n".join(f"  • {a}" for a in found[:2])
        )

    return HookResult.none()


# -----------------------------------------------------------------------------
# VERIFICATION REMINDER (priority 25)
# -----------------------------------------------------------------------------


@register_hook("verification_reminder", "Edit|Write|MultiEdit", priority=25)
def check_verification_reminder(
    data: dict, state: SessionState, runner_state: dict
) -> HookResult:
    """Remind to verify after fix iterations."""
    tool_input = data.get("tool_input", {})
    file_path = tool_input.get("file_path", "")

    fix_indicators = []

    # File edited multiple times
    edit_count = sum(1 for f in state.files_edited if f == file_path)
    if edit_count >= 2:
        fix_indicators.append(f"edited {edit_count}x")

    # Recent errors exist
    if state.errors_unresolved:
        fix_indicators.append("unresolved errors exist")

    # "fix" in filename
    if "fix" in file_path.lower():
        fix_indicators.append("'fix' in filename")

    verify_run = getattr(state, "verify_run", False)

    if fix_indicators and not verify_run:
        return HookResult.with_context(f"⚠️ VERIFY REMINDER: {', '.join(fix_indicators)} → run `verify` or tests before claiming fixed")

    return HookResult.none()


# -----------------------------------------------------------------------------
# UI VERIFICATION GATE (priority 30)
# -----------------------------------------------------------------------------


@register_hook("ui_verification_gate", "Edit|Write|MultiEdit", priority=30)
def check_ui_verification(
    data: dict, state: SessionState, runner_state: dict
) -> HookResult:
    """Require browser screenshot after CSS/UI changes."""
    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})
    file_path = tool_input.get("file_path", "")

    content = ""
    if tool_name == "Write":
        content = tool_input.get("content", "")
    elif tool_name == "Edit":
        content = tool_input.get("new_string", "")

    # Use pre-compiled patterns from module level
    indicators = []
    for pattern in _UI_FILE_PATTERNS:
        if pattern.search(file_path):
            indicators.append(f"UI file: {pattern.pattern}")
            break

    for pattern in _STYLE_CONTENT_PATTERNS:
        if pattern.search(content):
            indicators.append("style pattern detected")
            break

    if not indicators:
        return HookResult.none()

    browser_used = getattr(state, "browser_screenshot_taken", False)
    if browser_used:
        return HookResult.none()

    return HookResult.with_context(f"📸 UI VERIFY: {', '.join(indicators[:2])} → `browser page screenshot -o .claude/tmp/ui_check.png`")


# -----------------------------------------------------------------------------
# CODE QUALITY GATE (priority 35)
# Uses adaptive thresholds from session_state (v3.7) - self-tuning based on usage
# Fallback defaults if adaptive system unavailable:
# -----------------------------------------------------------------------------

# Fallback defaults (overridden by adaptive thresholds when available)
MAX_METHOD_LINES = 60
MAX_CONDITIONALS = 12
MAX_DEBUG_STATEMENTS = 5
MAX_NESTING_DEPTH = 5

PATTERN_CONDITIONALS = re.compile(
    r"\b(if|elif|else|for|while|except|try|switch|case)\b"
)
PATTERN_TRY_BLOCK = re.compile(r"\b(try\s*:|try\s*\{)")
PATTERN_EXCEPT_BLOCK = re.compile(r"\b(except|catch)\b")
PATTERN_DEBUG_PY = re.compile(r"\bprint\s*\(", re.IGNORECASE)
PATTERN_DEBUG_JS = re.compile(r"\bconsole\.(log|debug|info|warn|error)\s*\(")
PATTERN_N_PLUS_ONE = re.compile(
    r"for\s+.*?\s+in\s+.*?:\s*\n?\s*.*?(query|fetch|load|select|find|get)\s*\(",
    re.MULTILINE | re.IGNORECASE,
)
# Nested loops: Match actual indented nesting (outer loop then indented inner loop)
PATTERN_NESTED_LOOPS = re.compile(
    r"^[ ]{0,8}(for|while)\s+[^\n]+:\s*\n"  # Outer loop
    r"(?:[ ]{4,}[^\n]*\n)*?"  # Skip lines until...
    r"[ ]{4,}(for|while)\s+[^\n]+:",  # Inner loop (more indented)
    re.MULTILINE,
)

# NEW: Additional performance anti-patterns from old system
PATTERN_STRING_CONCAT_LOOP = re.compile(
    r"for\s+.*?[:{]\s*\n?\s*.*?\+=\s*['\"]", re.MULTILINE
)
# Triple loop: Match actual indented nesting, not just 3 keywords anywhere
# Pattern: for/while at col 0-4, then indented for/while, then more indented for/while
PATTERN_TRIPLE_LOOP = re.compile(
    r"^[ ]{0,4}(for|while)\s+[^\n]+:\s*\n"  # Outer loop at indent 0-4
    r"(?:[ ]{4,}[^\n]*\n)*?"  # Skip lines until...
    r"[ ]{4,8}(for|while)\s+[^\n]+:\s*\n"  # Middle loop at indent 4-8
    r"(?:[ ]{8,}[^\n]*\n)*?"  # Skip lines until...
    r"[ ]{8,}(for|while)\s+[^\n]+:",  # Inner loop at indent 8+
    re.MULTILINE,
)
PATTERN_BLOCKING_IO_NODE = re.compile(
    r"\b(readFileSync|writeFileSync|existsSync|execSync)\s*\("
)
PATTERN_BLOCKING_IO_PY = re.compile(
    r"\bopen\s*\([^)]+\)\s*\.\s*read\s*\(\s*\)(?!\s*#.*async)"
)
PATTERN_MAGIC_NUMBERS = re.compile(
    r"(?<![.\w])(?:0x[a-fA-F0-9]+|\d{3,})(?![.\w])"
)  # Numbers >= 100 or hex
PATTERN_TODO_FIXME = re.compile(r"\b(TODO|FIXME|HACK|XXX)\b", re.IGNORECASE)


def _check_structure_patterns(
    code: str, file_path: str, state: SessionState
) -> tuple[list[str], list[tuple[str, int]]]:
    """Check structural code patterns (length, complexity, nesting)."""
    hints = []
    triggered = []

    threshold_lines = get_adaptive_threshold(state, "quality_long_method")
    threshold_complexity = get_adaptive_threshold(state, "quality_high_complexity")
    threshold_nesting = get_adaptive_threshold(state, "quality_deep_nesting")

    # Long method
    lines = code.count("\n") + 1
    if lines > threshold_lines:
        hints.append(f"📏 **Long Code Block**: {lines} lines (<{int(threshold_lines)})")
        triggered.append(("quality_long_method", lines))

    # High complexity
    conditionals = len(PATTERN_CONDITIONALS.findall(code))
    if conditionals > threshold_complexity:
        hints.append(f"🌀 **High Complexity**: {conditionals} conditionals")
        triggered.append(("quality_high_complexity", conditionals))

    # Deep nesting
    max_indent = max(
        (len(ln) - len(ln.lstrip()) for ln in code.split("\n") if ln.strip()), default=0
    )
    nesting_levels = max_indent // 4
    if nesting_levels > threshold_nesting:
        hints.append(f"🪆 **Deep Nesting**: {nesting_levels} levels")
        triggered.append(("quality_deep_nesting", nesting_levels))

    return hints, triggered


def _check_perf_patterns(code: str, file_path: str) -> list[str]:
    """Check performance-related anti-patterns."""
    hints = []
    is_python = file_path.endswith(".py")
    is_js = file_path.endswith((".js", ".ts", ".jsx", ".tsx"))

    # N+1 query
    if PATTERN_N_PLUS_ONE.search(code):
        hints.append("⚡ **Potential N+1**: DB/API call in loop")

    # Nested loops
    if PATTERN_TRIPLE_LOOP.search(code):
        hints.append("🔄 **Triple Nested Loops**: O(n³) complexity!")
    elif PATTERN_NESTED_LOOPS.search(code):
        hints.append("🔄 **Nested Loops**: O(n²) complexity")

    # String concat in loops
    if PATTERN_STRING_CONCAT_LOOP.search(code):
        hints.append("📝 **String Concat in Loop**: Use join() instead")

    # Blocking I/O
    if is_js and PATTERN_BLOCKING_IO_NODE.search(code):
        hints.append("🐌 **Blocking I/O**: Use async fs methods")
    elif is_python and PATTERN_BLOCKING_IO_PY.search(code):
        hints.append("🐌 **Blocking Read**: Use `with open()` pattern")

    return hints


def _check_quality_markers(
    code: str, file_path: str, state: SessionState
) -> tuple[list[str], list[tuple[str, int]]]:
    """Check code quality markers (debug, magic numbers, TODOs)."""
    hints = []
    triggered = []
    is_python = file_path.endswith(".py")
    is_js = file_path.endswith((".js", ".ts", ".jsx", ".tsx"))
    is_cli_tool = "/ops/" in file_path or "/.claude/hooks/" in file_path

    # Missing error handling
    if PATTERN_TRY_BLOCK.search(code) and not PATTERN_EXCEPT_BLOCK.search(code):
        hints.append("⚠️ **Missing Error Handler**: try without catch/except")

    # Debug statements (skip CLI tools)
    threshold_debug = get_adaptive_threshold(state, "quality_debug_statements")
    debug_count = (
        len(PATTERN_DEBUG_PY.findall(code))
        if is_python
        else (len(PATTERN_DEBUG_JS.findall(code)) if is_js else 0)
    )
    if debug_count > threshold_debug and not is_cli_tool:
        hints.append(f"🐛 **Debug Statements**: {debug_count} found")
        triggered.append(("quality_debug_statements", debug_count))

    # Magic numbers
    threshold_magic = get_adaptive_threshold(state, "quality_magic_numbers")
    magic_count = len(PATTERN_MAGIC_NUMBERS.findall(code))
    if magic_count > threshold_magic:
        hints.append(f"🔢 **Magic Numbers**: {magic_count} literals")
        triggered.append(("quality_magic_numbers", magic_count))

    # Tech debt markers
    threshold_debt = get_adaptive_threshold(state, "quality_tech_debt_markers")
    todo_count = len(PATTERN_TODO_FIXME.findall(code))
    if todo_count > threshold_debt:
        hints.append(f"📝 **Tech Debt**: {todo_count} TODO/FIXME markers")
        triggered.append(("quality_tech_debt_markers", todo_count))

    return hints, triggered


@register_hook("code_quality_gate", "Edit|Write", priority=35)
def check_code_quality(
    data: dict, state: SessionState, runner_state: dict
) -> HookResult:
    """Detect code quality anti-patterns with adaptive thresholds."""
    tool_input = data.get("tool_input", {})
    file_path = tool_input.get("file_path", "")

    code_extensions = (
        ".py",
        ".js",
        ".ts",
        ".jsx",
        ".tsx",
        ".go",
        ".rs",
        ".java",
        ".rb",
        ".sh",
    )
    if not file_path.endswith(code_extensions):
        return HookResult.none()

    code = tool_input.get("content", "") or tool_input.get("new_string", "")
    if not code or len(code) < 50:
        return HookResult.none()

    # Collect hints from specialized checkers
    hints = []
    triggered_patterns = []

    struct_hints, struct_triggered = _check_structure_patterns(code, file_path, state)
    hints.extend(struct_hints)
    triggered_patterns.extend(struct_triggered)

    hints.extend(_check_perf_patterns(code, file_path))

    marker_hints, marker_triggered = _check_quality_markers(code, file_path, state)
    hints.extend(marker_hints)
    triggered_patterns.extend(marker_triggered)

    if hints:
        for pattern_name, value in triggered_patterns:
            record_threshold_trigger(state, pattern_name, value)
        return HookResult.with_context(
            "🔍 **Code Quality Check**:\n" + "\n".join(hints[:4])
        )

    return HookResult.none()


# -----------------------------------------------------------------------------
# QUALITY SCANNER (priority 36) - ruff + radon code quality
# -----------------------------------------------------------------------------


@register_hook("quality_scanner", "Edit|Write", priority=36)
def check_quality_scan(
    data: dict, state: SessionState, runner_state: dict
) -> HookResult:
    """Scan code for quality issues using ruff (lint) and radon (complexity).

    Fast rule-based analysis - no ML model required.
    Advisory only - warns but doesn't block.
    """
    if not QUALITY_SCANNER_AVAILABLE or quality_scan_file is None:
        return HookResult.none()

    tool_input = data.get("tool_input", {})
    file_path = tool_input.get("file_path", "")

    # Only scan Python files (ruff/radon are Python-focused)
    if not file_path.endswith(".py"):
        return HookResult.none()

    # Skip scratch/tmp files
    if is_scratch_path(file_path):
        return HookResult.none()

    # Scan file for quality issues
    result = quality_scan_file(file_path, complexity_threshold="C")

    if result is None:
        return HookResult.none()

    # Quality issues found - advisory warning
    report = format_report(result)
    if report:
        return HookResult.with_context(report)

    return HookResult.none()


# -----------------------------------------------------------------------------
# STATE MUTATION GUARD (priority 37) - React/JS + Python anti-patterns
# -----------------------------------------------------------------------------


@register_hook("state_mutation_guard", "Edit|Write", priority=37)
def check_state_mutations(
    data: dict, state: SessionState, runner_state: dict
) -> HookResult:
    """Detect state mutation anti-patterns in React/JS and Python."""
    tool_input = data.get("tool_input", {})
    file_path = tool_input.get("file_path", "")

    if is_scratch_path(file_path):
        return HookResult.none()

    code = tool_input.get("new_string", "") or tool_input.get("content", "")
    if not code or len(code) < 50:
        return HookResult.none()

    # Check cooldown
    if mutation_cooldown.is_active():
        return HookResult.none()

    warnings = []
    is_js = file_path.endswith((".js", ".ts", ".jsx", ".tsx"))
    is_py = file_path.endswith(".py")

    if is_js:
        for pattern, msg in _JS_MUTATION_PATTERNS:
            match = pattern.search(code)
            if match:
                # Skip if clearly on spread [...arr].sort()
                if match.group(0) in (".sort()", ".reverse()"):
                    context = code[max(0, match.start() - 10) : match.start()]
                    if _SPREAD_CHECK.search(context):
                        continue
                try:
                    warnings.append(
                        msg.format(
                            match.group(1) if match.lastindex else match.group(0)
                        )
                    )
                except (IndexError, AttributeError):
                    warnings.append(msg.format("method"))

    elif is_py:
        # AST-based mutable default detection (more accurate than regex)
        from _ast_utils import find_mutable_defaults

        mutable_issues = find_mutable_defaults(code)
        for func_name, line, mtype in mutable_issues[:2]:
            warnings.append(
                f"Mutable default {mtype} in {func_name}() - use None and set in body"
            )

    if warnings:
        mutation_cooldown.reset()
        return HookResult.with_context(
            "⚠️ **State Mutation Warning**:\n"
            + "\n".join(f"  • {w}" for w in warnings[:2])
        )

    return HookResult.none()


# -----------------------------------------------------------------------------
# DEV TOOLCHAIN SUGGESTIONS (priority 40) - Language-specific lint/format/check
# -----------------------------------------------------------------------------

# Language -> (formatter, linter, typechecker)
DEV_TOOLCHAIN = {
    ".py": ("ruff format {file}", "ruff check --fix {file}", "mypy {file}"),
    ".ts": (
        "npx prettier --write {file}",
        "npx eslint --fix {file}",
        "npx tsc --noEmit",
    ),
    ".tsx": (
        "npx prettier --write {file}",
        "npx eslint --fix {file}",
        "npx tsc --noEmit",
    ),
    ".js": ("npx prettier --write {file}", "npx eslint --fix {file}", None),
    ".jsx": ("npx prettier --write {file}", "npx eslint --fix {file}", None),
    ".json": ("npx prettier --write {file}", None, None),
    ".css": ("npx prettier --write {file}", None, None),
    ".scss": ("npx prettier --write {file}", None, None),
    ".html": ("npx prettier --write {file}", None, None),
    ".md": ("npx prettier --write {file}", None, None),
    ".yaml": ("npx prettier --write {file}", None, None),
    ".yml": ("npx prettier --write {file}", None, None),
}


@register_hook("dev_toolchain_suggest", "Edit|Write", priority=40)
def check_dev_toolchain(
    data: dict, state: SessionState, runner_state: dict
) -> HookResult:
    """Suggest language-appropriate dev tools after edits."""
    tool_input = data.get("tool_input", {})
    file_path = tool_input.get("file_path", "")

    if is_scratch_path(file_path):
        return HookResult.none()

    # Find matching extension
    ext = None
    for e in DEV_TOOLCHAIN:
        if file_path.endswith(e):
            ext = e
            break

    if not ext:
        return HookResult.none()

    # Check cooldown per extension (5 min per language)
    if toolchain_keyed.is_active(ext):
        return HookResult.none()

    formatter, linter, typechecker = DEV_TOOLCHAIN[ext]
    suggestions = []

    if formatter:
        suggestions.append(f"Format: `{formatter.format(file=Path(file_path).name)}`")
    if linter:
        suggestions.append(f"Lint: `{linter.format(file=Path(file_path).name)}`")
    if typechecker:
        suggestions.append(f"Typecheck: `{typechecker}`")

    if suggestions:
        toolchain_keyed.reset(ext)
        return HookResult.with_context(
            f"🛠️ **Dev Tools** ({ext}):\n  " + "\n  ".join(suggestions[:2])
        )

    return HookResult.none()


# -----------------------------------------------------------------------------
# LARGE FILE HELPER (priority 45) - Line range guidance for big files
# -----------------------------------------------------------------------------

LARGE_FILE_THRESHOLD = 500


@register_hook("large_file_helper", "Read", priority=45)
def check_large_file(data: dict, state: SessionState, runner_state: dict) -> HookResult:
    """Provide line range guidance for large files."""
    tool_input = data.get("tool_input", {})
    tool_result = data.get("tool_result", {})
    file_path = tool_input.get("file_path", "")

    if not file_path:
        return HookResult.none()

    # Check if file is large (estimate from output)
    output = tool_result.get("output", "")
    line_count = output.count("\n")

    if line_count < LARGE_FILE_THRESHOLD:
        return HookResult.none()

    # Check cooldown per file (10 min)
    if large_file_keyed.is_active(file_path):
        return HookResult.none()

    large_file_keyed.reset(file_path)
    filename = Path(file_path).name
    return HookResult.with_context(
        f"📄 **Large File** ({line_count}+ lines): `{filename}`\n"
        f"  For edits, use line-range reads: `Read {filename} lines X-Y`\n"
        f"  Look for section markers: `// === SECTION ===` or `# --- SECTION ---`"
    )


# -----------------------------------------------------------------------------
# CRAWL4AI PROMOTION (priority 48) - Suggest crawl4ai over WebFetch
# -----------------------------------------------------------------------------


@register_hook("crawl4ai_promo", "WebFetch", priority=48)
def promote_crawl4ai(data: dict, state: SessionState, runner_state: dict) -> HookResult:
    """Promote crawl4ai MCP when WebFetch is used - crawl4ai is superior for web content."""
    tool_input = data.get("tool_input", {})
    url = tool_input.get("url", "")

    if not url:
        return HookResult.none()

    # Extract domain for keyed cooldown
    domain_match = re.search(r"https?://([^/]+)", url)
    domain = domain_match.group(1) if domain_match else "unknown"

    # Skip if recently promoted for this domain
    if crawl4ai_promo_keyed.is_active(domain):
        return HookResult.none()

    crawl4ai_promo_keyed.reset(domain)

    return HookResult.with_context(
        "🌟 **Crawl4AI Available** - Superior to WebFetch:\n"
        "  • Full JavaScript rendering (SPAs, dynamic content)\n"
        "  • Bypasses Cloudflare, bot detection, CAPTCHAs\n"
        "  • Returns clean LLM-friendly markdown\n"
        "  → `mcp__crawl4ai__crawl` for this URL\n"
        "  → `mcp__crawl4ai__search` to discover related URLs"
    )


# -----------------------------------------------------------------------------
# TOOL AWARENESS (priority 50) - Remind about available tools
# -----------------------------------------------------------------------------

TOOL_AWARENESS_PATTERNS = {
    "playwright": {
        "pattern": re.compile(
            r"\b(manual.*test|test.*manual|browser.*test|click|navigate|form|button|webpage|e2e|integration test|screenshot)\b",
            re.IGNORECASE,
        ),
        "reminder": "🎭 **Playwright Available**: Use `mcp__playwright__*` tools for browser automation instead of manual testing.",
        "threshold": 2,
    },
    "pal_mcp": {
        "pattern": re.compile(
            r"\b(uncertain|not sure|complex|difficult|stuck|investigate|how to|unsure|maybe)\b",
            re.IGNORECASE,
        ),
        "reminder": "🤝 **PAL MCP Available**: `mcp__pal__chat/thinkdeep/debug` for deep analysis when uncertain.",
        "threshold": 3,
    },
    "websearch": {
        "pattern": re.compile(
            r"\b(latest|recent|current|new version|updated|documentation|best practice|2024|2025)\b",
            re.IGNORECASE,
        ),
        "reminder": "🔍 **WebSearch Available**: Search for latest docs/patterns instead of relying on training data.",
        "threshold": 2,
    },
    "task_agent": {
        "pattern": re.compile(
            r"\b(then|and then|after that|next|also|first.*then)\b", re.IGNORECASE
        ),
        "reminder": "🤖 **Task Agent**: For 3+ sequential tasks, use parallel Task agents for speed.",
        "threshold": 4,
    },
}


@register_hook("tool_awareness", "Read|Bash|Task", priority=50)
def check_tool_awareness(
    data: dict, state: SessionState, runner_state: dict
) -> HookResult:
    """Remind about available tools when relevant patterns detected."""
    tool_result = data.get("tool_result", {})
    output = (
        tool_result.get("output", "")
        if isinstance(tool_result, dict)
        else str(tool_result)
    )

    if not output or len(output) < 50:
        return HookResult.none()

    for tool_name, config in TOOL_AWARENESS_PATTERNS.items():
        # Skip if recently reminded (keyed cooldown)
        if tool_awareness_keyed.is_active(tool_name):
            continue

        matches = len(config["pattern"].findall(output))
        if matches >= config["threshold"]:
            tool_awareness_keyed.reset(tool_name)
            return HookResult.with_context(config["reminder"])

    return HookResult.none()


# -----------------------------------------------------------------------------
# SCRATCH ENFORCER (priority 55)
# -----------------------------------------------------------------------------

SCRATCH_STATE_FILE = (
    Path(__file__).parent.parent / "memory" / "scratch_enforcer_state.json"
)
REPETITION_WINDOW = 300

REPETITIVE_PATTERNS = {
    "multi_file_edit": {
        "tools": ["Edit", "Write"],
        "threshold": 4,
        "suggestion": "Consider writing a .claude/tmp/ script to batch these edits",
    },
    "multi_file_read": {
        "tools": ["Read"],
        "threshold": 5,
        "suggestion": "Use Glob/Grep or write a .claude/tmp/ analysis script",
    },
    "multi_bash": {
        "tools": ["Bash"],
        "threshold": 4,
        "suggestion": "Chain commands with && or write a .claude/tmp/ script",
    },
    "multi_grep": {
        "tools": ["Grep"],
        "threshold": 4,
        "suggestion": "Write a .claude/tmp/ script for complex multi-pattern search",
    },
}


@register_hook("scratch_enforcer", None, priority=55)
def check_scratch_enforcer(
    data: dict, state: SessionState, runner_state: dict
) -> HookResult:
    """Detect repetitive manual work, suggest scripts."""
    tool_name = data.get("tool_name", "")
    if not tool_name:
        return HookResult.none()

    # Load scratch state with safe key access
    scratch_state = runner_state.get("scratch_state", {})
    # Ensure all required keys exist (handles partial data from old versions)
    scratch_state.setdefault("tool_counts", {})
    scratch_state.setdefault("last_reset", time.time())
    scratch_state.setdefault("suggestions_given", [])

    # Reset if window expired
    if time.time() - scratch_state.get("last_reset", 0) > REPETITION_WINDOW:
        scratch_state = {
            "tool_counts": {},
            "last_reset": time.time(),
            "suggestions_given": [],
        }

    # Increment counter
    scratch_state["tool_counts"][tool_name] = (
        scratch_state["tool_counts"].get(tool_name, 0) + 1
    )

    # Check patterns
    suggestion = None
    for pattern_name, config in REPETITIVE_PATTERNS.items():
        if pattern_name in scratch_state.get("suggestions_given", []):
            continue
        total = sum(scratch_state["tool_counts"].get(t, 0) for t in config["tools"])
        if total >= config["threshold"]:
            scratch_state["suggestions_given"].append(pattern_name)
            suggestion = config["suggestion"]
            break

    runner_state["scratch_state"] = scratch_state

    if suggestion:
        return HookResult.with_context(
            f"🔄 REPETITIVE PATTERN DETECTED:\n   {suggestion}\n   (.claude/tmp/ scripts are faster than manual iteration)"
        )

    return HookResult.none()


# -----------------------------------------------------------------------------
# AUTO LEARN (priority 60)
# -----------------------------------------------------------------------------

MEMORY_DIR = Path(__file__).parent.parent / "memory"
LESSONS_FILE = MEMORY_DIR / "__lessons.md"

LEARNABLE_PATTERNS = [
    (r"ModuleNotFoundError: No module named '([^']+)'", "Missing module: {0}"),
    (r"ImportError: cannot import name '([^']+)'", "Import error: {0}"),
    (
        r"AttributeError: '(\w+)' object has no attribute '(\w+)'",
        "{0} has no attribute {1}",
    ),
    (
        r"TypeError: ([^(]+)\(\) got an unexpected keyword argument '(\w+)'",
        "{0} doesn't accept '{1}' argument",
    ),
    (r"FileNotFoundError: \[Errno 2\].*'([^']+)'", "File not found: {0}"),
    (r"🛑 GAP: (.+)", "Gap detected: {0}"),
    (r"BLOCKED: (.+)", "Blocked: {0}"),
    (r"command not found: (\w+)", "Command not found: {0}"),
    (r"Permission denied", "Permission denied"),
    (r"fatal: (.+)", "Git error: {0}"),
]

IGNORE_PATTERNS = [
    r"^\s*$",
    r"warning:",
    r"^\d+ passed",
    r"ModuleNotFoundError.*No module named 'test_'",
]


@register_hook("auto_learn", None, priority=60)
def check_auto_learn(data: dict, state: SessionState, runner_state: dict) -> HookResult:
    """Capture lessons from errors and provide quality hints."""
    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})
    tool_output = data.get("tool_output", "")
    messages = []

    # Error learning (Bash only)
    if (
        tool_name == "Bash"
        and tool_output
        and ("error" in tool_output.lower() or "failed" in tool_output.lower())
    ):
        skip = any(re.search(p, tool_output, re.IGNORECASE) for p in IGNORE_PATTERNS)
        if not skip:
            for pattern, template in LEARNABLE_PATTERNS:
                match = re.search(pattern, tool_output)
                if match:
                    try:
                        lesson = template.format(*match.groups())
                        messages.append(f"🐘 Auto-learned: {lesson[:60]}...")
                    except (IndexError, KeyError):
                        pass
                    break

    # Quality hints
    if tool_name in ("Write", "Edit"):
        file_path = tool_input.get("file_path", "")
        if file_path.endswith(".py"):
            hint_id = "py_ruff"
            if hint_id not in runner_state.get("hints_shown", []):
                runner_state.setdefault("hints_shown", []).append(hint_id)
                messages.append(
                    "💡 Run `ruff check --fix && ruff format` after editing Python"
                )

    elif tool_name == "Bash":
        command = tool_input.get("command", "")
        if re.search(r"\bgrep\s+-r", command) and "rg " not in command:
            hint_id = "use_rg"
            if hint_id not in runner_state.get("hints_shown", []):
                runner_state.setdefault("hints_shown", []).append(hint_id)
                messages.append(
                    "💡 Use `rg` (ripgrep) instead of `grep -r` for 10-100x speed"
                )

    if messages:
        return HookResult.with_context("\n".join(messages[:2]))

    return HookResult.none()


# -----------------------------------------------------------------------------
# VELOCITY TRACKER (priority 65)
# Uses adaptive thresholds to prevent false positives from annoying users
# -----------------------------------------------------------------------------


def _check_self_check_pattern(
    tool_name: str, tool_input: dict, state: SessionState
) -> str | None:
    """Detect Edit-then-Read self-distrust pattern."""
    if tool_name != "Read" or len(state.last_5_tools) < 2:
        return None
    current_file = tool_input.get("file_path", "")
    if not current_file or state.last_5_tools[-1] not in ("Edit", "Write"):
        return None
    recent_edits = state.files_edited[-3:] if state.files_edited else []
    if current_file in recent_edits:
        name = current_file.split("/")[-1] if "/" in current_file else current_file
        return (
            f"🔄 SELF-CHECK: Edited then re-read `{name}`.\n"
            f"💡 Trust your edit or verify with a test, not re-reading."
        )
    return None


def _check_oscillation_pattern(last_5: list, state: SessionState) -> str | None:
    """Detect Read→Edit→Read→Edit oscillation."""
    pattern = "".join(
        "R" if t == "Read" else "E" for t in last_5 if t in ("Read", "Edit", "Write")
    )
    if "RERE" in pattern or "ERER" in pattern:
        record_threshold_trigger(state, "velocity_oscillation", 1)
        return (
            "🔄 OSCILLATION: Read→Edit→Read→Edit pattern.\n"
            "💡 Step back: progress or checking repeatedly?"
        )
    return None


def _check_search_loop(last_5: list, state: SessionState) -> str | None:
    """Detect low diversity search loops."""
    threshold = get_adaptive_threshold(state, "iteration_same_tool")
    if threshold == float("inf") or len(last_5) != 5:
        return None
    unique = len(set(last_5))
    if unique <= 2 and all(t in ("Read", "Glob", "Grep") for t in last_5):
        record_threshold_trigger(state, "iteration_same_tool", 5 - unique)
        return "🔄 SEARCH LOOP: 5+ searches without action.\n💡 Enough info to act?"
    return None


def _check_reread_pattern(state: SessionState) -> str | None:
    """Detect excessive re-reading of same file."""
    threshold = get_adaptive_threshold(state, "batch_sequential_reads")
    if threshold == float("inf"):
        return None
    recent = state.files_read[-10:] if len(state.files_read) >= 10 else state.files_read
    counts = Counter(recent)
    repeated = [(f, c) for f, c in counts.items() if c >= int(threshold)]
    if repeated:
        file, count = repeated[0]
        name = file.split("/")[-1] if "/" in file else file
        record_threshold_trigger(state, "batch_sequential_reads", count)
        return f"🔄 RE-READ: `{name}` read {count}x.\n💡 What are you looking for?"
    return None


@register_hook("velocity_tracker", "Read|Edit|Write|Bash|Glob|Grep", priority=65)
def check_velocity(data: dict, state: SessionState, runner_state: dict) -> HookResult:
    """Detect spinning vs actual progress with adaptive thresholds."""
    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})
    last_5 = state.last_5_tools

    if len(last_5) < 3:
        return HookResult.none()
    if get_adaptive_threshold(state, "velocity_oscillation") == float("inf"):
        return HookResult.none()

    if msg := _check_self_check_pattern(tool_name, tool_input, state):
        return HookResult.with_context(msg)

    if len(last_5) < 4:
        return HookResult.none()

    if msg := _check_oscillation_pattern(last_5, state):
        return HookResult.with_context(msg)
    if msg := _check_search_loop(last_5, state):
        return HookResult.with_context(msg)
    if msg := _check_reread_pattern(state):
        return HookResult.with_context(msg)

    return HookResult.none()


# -----------------------------------------------------------------------------
# INFO GAIN TRACKER (priority 70)
# -----------------------------------------------------------------------------

INFO_GAIN_STATE_FILE = MEMORY_DIR / "info_gain_state.json"
READS_BEFORE_WARN = 5  # Warn earlier (old system used 4)
READS_BEFORE_CRYSTALLIZE = 8  # Suggest crystallizing knowledge

READ_TOOLS = {"Read", "Grep", "Glob"}
PROGRESS_TOOLS = {"Edit", "Write"}
PROGRESS_BASH_PATTERNS = [
    "pytest",
    "npm test",
    "npm run",
    "cargo test",
    "cargo build",
    "python3 .claude/ops/verify",
    "python3 .claude/ops/audit",
    "git commit",
    "git add",
    "pip install",
    "npm install",
]


@register_hook("info_gain_tracker", None, priority=70)
def check_info_gain(data: dict, state: SessionState, runner_state: dict) -> HookResult:
    """Detect reads without progress."""
    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})

    # Get or init info gain state with safe key access
    ig_state = runner_state.get("info_gain_state", {})
    # Ensure all required keys exist (handles partial data from old versions)
    ig_state.setdefault("reads_since_progress", 0)
    ig_state.setdefault("files_read_this_burst", [])
    ig_state.setdefault("last_stall_warn", 0)

    if tool_name in READ_TOOLS:
        ig_state["reads_since_progress"] = ig_state.get("reads_since_progress", 0) + 1
        filepath = tool_input.get("file_path", "") or tool_input.get("pattern", "")
        if filepath:
            ig_state.setdefault("files_read_this_burst", []).append(filepath)
            ig_state["files_read_this_burst"] = ig_state["files_read_this_burst"][-10:]

        reads = ig_state["reads_since_progress"]
        time_since_warn = time.time() - ig_state.get("last_stall_warn", 0)

        if reads >= READS_BEFORE_WARN and time_since_warn > 60:
            ig_state["last_stall_warn"] = time.time()
            files = ig_state.get("files_read_this_burst", [])[-5:]
            file_names = [Path(f).name if f else "?" for f in files]
            file_list = ", ".join(file_names) if file_names else "multiple files"
            runner_state["info_gain_state"] = ig_state

            # Escalate message if many reads without action
            severity = "⚠️" if reads < READS_BEFORE_CRYSTALLIZE else "🛑"
            hint = " → crystallize to .claude/tmp/" if reads >= READS_BEFORE_CRYSTALLIZE else ""
            return HookResult.with_context(
                f"{severity} INFO GAIN: {reads} reads ({file_list}) - act or need more?{hint}"
            )

    elif tool_name in PROGRESS_TOOLS:
        ig_state["reads_since_progress"] = 0
        ig_state["files_read_this_burst"] = []

    elif tool_name == "Bash":
        command = tool_input.get("command", "")
        if any(p in command.lower() for p in PROGRESS_BASH_PATTERNS):
            ig_state["reads_since_progress"] = 0
            ig_state["files_read_this_burst"] = []

    runner_state["info_gain_state"] = ig_state
    return HookResult.none()


# -----------------------------------------------------------------------------
# BEADS AUTO-SYNC (priority 72) - Sync beads after git operations
# -----------------------------------------------------------------------------


@register_hook("beads_auto_sync", "Bash", priority=72)
def check_beads_auto_sync(
    data: dict, state: SessionState, runner_state: dict
) -> HookResult:
    """Automatically sync beads after git commit/push operations."""
    import subprocess
    import shutil

    tool_input = data.get("tool_input", {})
    tool_result = data.get("tool_result", {})
    command = tool_input.get("command", "")

    # Only trigger on git commit or git push
    if not re.search(r"\bgit\s+(commit|push)\b", command, re.IGNORECASE):
        return HookResult.none()

    # Check if command succeeded
    success = True
    if isinstance(tool_result, dict):
        stderr = tool_result.get("stderr", "")
        exit_code = tool_result.get("exit_code", 0)
        success = exit_code == 0 and "error" not in stderr.lower()

    if not success:
        return HookResult.none()

    # Check cooldown - don't sync too frequently
    if beads_sync_cooldown.is_active():
        return HookResult.none()

    # Check if bd command exists
    bd_path = shutil.which("bd")
    if not bd_path:
        return HookResult.none()

    # Check if .beads directory exists (beads is active for this project)
    beads_dir = Path.cwd() / ".beads"
    if not beads_dir.exists():
        # Also check home directory
        beads_dir = Path.home() / ".claude" / ".beads"
        if not beads_dir.exists():
            return HookResult.none()

    # Run bd sync in background (non-blocking)
    try:
        subprocess.Popen(
            [bd_path, "sync"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,  # Detach from parent process
        )
        beads_sync_cooldown.reset()
        return HookResult.with_context("🔄 Beads auto-synced in background")
    except (OSError, IOError):
        return HookResult.none()


# =============================================================================
# MAIN RUNNER
# =============================================================================


def matches_tool(matcher: Optional[str], tool_name: str) -> bool:
    """Check if tool matches the hook's matcher pattern."""
    if matcher is None:
        return True
    return bool(re.match(f"^({matcher})$", tool_name))


def run_hooks(data: dict, state: SessionState) -> dict:
    """Run all applicable hooks and return aggregated result."""
    tool_name = data.get("tool_name", "")

    # Sort by priority
    # Hooks pre-sorted at module load

    # Shared state for hooks in this run
    runner_state = {}

    # Collect contexts
    contexts = []

    for name, matcher, check_func, priority in HOOKS:
        if not matches_tool(matcher, tool_name):
            continue

        try:
            result = check_func(data, state, runner_state)
            if result.context:
                contexts.append(result.context)
        except Exception as e:
            print(f"[post-runner] Hook {name} error: {e}", file=sys.stderr)

    # Save scratch state to disk
    if "scratch_state" in runner_state:
        try:
            SCRATCH_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            SCRATCH_STATE_FILE.write_text(json.dumps(runner_state["scratch_state"]))
        except IOError:
            pass

    # Build output
    output = {"hookSpecificOutput": {"hookEventName": "PostToolUse"}}
    if contexts:
        output["hookSpecificOutput"]["additionalContext"] = "\n\n".join(contexts[:5])

    return output


# Pre-sort hooks by priority at module load (avoid re-sorting on every call)
HOOKS.sort(key=lambda x: x[3])


def main():
    """Main entry point."""
    start = time.time()

    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse"}}))
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
    if elapsed > 100:
        print(f"[post-runner] Slow: {elapsed:.1f}ms", file=sys.stderr)

    sys.exit(0)


if __name__ == "__main__":
    main()
