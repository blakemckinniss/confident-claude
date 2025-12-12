#!/usr/bin/env python3
"""
Composite PostToolUse Runner: Runs all PostToolUse hooks in a single process.

PERFORMANCE: ~40ms for 8 hooks vs ~300ms for individual processes (7x faster)

HOOKS INDEX (by priority):
  STATE (0-20):
    10 state_updater       - Track files read/edited, commands, libraries, errors

  QUALITY GATES (22-50):
    22 assumption_check    - Surface hidden assumptions in code changes
    25 completion_gate     - Remind to verify after fix iterations
    30 ui_verification     - Remind to screenshot after CSS/UI changes
    35 code_quality_gate   - Detect anti-patterns (N+1, O(n³), blocking I/O, nesting)
    37 state_mutation_guard - Detect React/Python mutation anti-patterns
    40 dev_toolchain_suggest - Suggest lint/format/typecheck per language
    45 large_file_helper   - Line range guidance for big files
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
from dataclasses import dataclass
from pathlib import Path
from collections import Counter

# Performance: centralized configuration
from _cooldown import (
    assumption_cooldown,
    mutation_cooldown,
    toolchain_keyed,
    large_file_keyed,
    tool_awareness_keyed,
    beads_sync_cooldown,
)

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
)

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
# HOOK RESULT TYPE
# =============================================================================


@dataclass
class HookResult:
    """Result from a hook check."""

    context: str = ""  # Additional context to inject

    @staticmethod
    def none() -> "HookResult":
        return HookResult()

    @staticmethod
    def with_context(context: str) -> "HookResult":
        return HookResult(context=context)


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


@register_hook("state_updater", None, priority=10)
def check_state_updater(
    data: dict, state: SessionState, runner_state: dict
) -> HookResult:
    """Update session state based on tool usage."""
    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})
    result = data.get("tool_result", {})
    warning = None

    # Update tool count
    state.tool_counts[tool_name] = state.tool_counts.get(tool_name, 0) + 1
    track_batch_tool(state, tool_name, tools_in_message=1)

    # Process by tool type
    if tool_name == "Read":
        filepath = tool_input.get("file_path", "")
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

    elif tool_name == "Edit":
        filepath = tool_input.get("file_path", "")
        # SELF-HEAL: Detect Edit failures on framework files
        edit_error = result.get("error", "") or ""
        if not edit_error and isinstance(result, dict):
            # Check for error indicators in output
            output = result.get("output", "")
            if isinstance(output, str) and (
                "error" in output.lower()[:100] or "failed" in output.lower()[:100]
            ):
                edit_error = output[:200]
        if edit_error and filepath and ".claude/" in filepath:
            _trigger_self_heal(state, target=filepath, error=edit_error)

        if filepath:
            track_file_edit(state, filepath)
            track_feature_file(state, filepath)
            new_code = tool_input.get("new_string", "")
            if new_code:
                for lib in extract_libraries_from_code(new_code):
                    track_library_used(state, lib)
                if filepath.endswith((".py", ".js", ".ts", ".tsx", ".rs", ".go")):
                    old_code = tool_input.get("old_string", "")
                    old_func_lines = extract_function_def_lines(old_code)
                    new_func_lines = extract_function_def_lines(new_code)
                    for func_name, old_def in old_func_lines.items():
                        new_def = new_func_lines.get(func_name)
                        if new_def is None or old_def != new_def:
                            add_pending_integration_grep(state, func_name, filepath)
            # SELF-HEAL: Clear if successful edit on framework files (no error)
            if (
                not edit_error
                and getattr(state, "self_heal_required", False)
                and ".claude/" in filepath
            ):
                _clear_self_heal(state)

    elif tool_name == "Write":
        filepath = tool_input.get("file_path", "")
        # SELF-HEAL: Detect Write failures on framework files
        write_error = result.get("error", "") or ""
        if not write_error and isinstance(result, dict):
            output = result.get("output", "")
            if isinstance(output, str) and (
                "error" in output.lower()[:100] or "failed" in output.lower()[:100]
            ):
                write_error = output[:200]
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
                        warning = f"⚠️ STUB DETECTED in new file `{fname}`: {', '.join(stubs)}\n   Remember to complete before session ends!"
            # SELF-HEAL: Clear if successful write on framework files
            if (
                not write_error
                and getattr(state, "self_heal_required", False)
                and ".claude/" in filepath
            ):
                _clear_self_heal(state)

    elif tool_name == "Bash":
        command = tool_input.get("command", "")
        output = result.get("output", "")
        exit_code = result.get("exit_code", 0)
        success = exit_code == 0
        track_command(state, command, success, output)

        # Track files read via cat/head/tail
        if success:
            read_cmds = ["cat ", "head ", "tail ", "less ", "more "]
            if any(
                command.startswith(cmd) or f" {cmd}" in command for cmd in read_cmds
            ):
                parts = command.split()
                for part in parts[1:]:
                    if not part.startswith("-") and ("/" in part or "." in part):
                        track_file_read(state, part)

        # Checkpoint on git commit
        if success and re.search(r"\bgit\s+commit\b", command, re.IGNORECASE):
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
            if state.current_feature and any(
                kw in notes.lower() for kw in completion_keywords
            ):
                complete_feature(state, status="completed")

        # Track failures
        approach_sig = (
            f"Bash:{command.split()[0][:20]}" if command.split() else "Bash:unknown"
        )
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

                # SELF-HEAL: Detect framework errors (errors in .claude/ paths)
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

        if success and state.errors_unresolved:
            reset_failures(state)
            for error in state.errors_unresolved[:]:
                if any(
                    word in command.lower()
                    for word in error.get("type", "").lower().split()
                ):
                    resolve_error(state, error.get("type", ""))

        # Test failure discovery
        if (
            "pytest" in command
            or "npm test" in command
            or "jest" in command
            or "cargo test" in command
        ):
            for failure in extract_test_failures(output):
                add_work_item(
                    state,
                    item_type="test_failure",
                    source=failure.get("file", "tests"),
                    description=failure.get("description", "Fix test failure"),
                    priority=failure.get("priority", 80),
                )

        # Clear pending items for bash grep/find
        if "grep " in command or command.startswith("grep") or "rg " in command:
            patterns = re.findall(r'grep[^\|]*?["\']([^"\']+)["\']', command)
            patterns += re.findall(r"grep\s+(?:-\w+\s+)*(\w+)", command)
            for pattern in patterns:
                if len(pattern) > 3:
                    clear_integration_grep(state, pattern)
                    clear_pending_search(state, pattern)

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

    return HookResult.with_context(warning) if warning else HookResult.none()


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
    if ".claude/tmp/" in file_path or ".claude/memory/" in file_path:
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
# COMPLETION GATE (priority 25)
# -----------------------------------------------------------------------------


@register_hook("completion_gate", "Edit|Write|MultiEdit", priority=25)
def check_completion_gate(
    data: dict, state: SessionState, runner_state: dict
) -> HookResult:
    """Block 'fixed/done/complete' claims without verification."""
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
        return HookResult.with_context(
            f"**VERIFY REMINDER** (Hard Block #3)\n"
            f"Indicators: {', '.join(fix_indicators)}\n"
            f"Before claiming 'fixed': run `verify` or tests.\n"
            f'Pattern: verify command_success "<test_cmd>"'
        )

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

    return HookResult.with_context(
        f"**UI VERIFICATION NEEDED** (Auto-Invoke Rule)\n"
        f"Detected: {', '.join(indicators[:2])}\n"
        f"Before claiming UI works, run:\n"
        f"```bash\nbrowser page screenshot -o .claude/tmp/ui_check.png\n```"
    )


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
PATTERN_NESTED_LOOPS = re.compile(
    r"(for|while)\s+[^{:]+[{:]\s*[\s\S]*?(for|while)\s+[^{:]+[{:]", re.MULTILINE
)

# NEW: Additional performance anti-patterns from old system
PATTERN_STRING_CONCAT_LOOP = re.compile(
    r"for\s+.*?[:{]\s*\n?\s*.*?\+=\s*['\"]", re.MULTILINE
)
PATTERN_TRIPLE_LOOP = re.compile(
    r"for\s+.*?(for|while)\s+.*?(for|while)\s+", re.MULTILINE | re.DOTALL
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

    hints = []
    triggered_patterns = []  # Track which patterns fired for adaptive learning

    # Get adaptive thresholds (auto-adjust based on usage patterns)
    threshold_lines = get_adaptive_threshold(state, "quality_long_method")
    threshold_complexity = get_adaptive_threshold(state, "quality_high_complexity")
    threshold_debug = get_adaptive_threshold(state, "quality_debug_statements")
    threshold_nesting = get_adaptive_threshold(state, "quality_deep_nesting")

    # Long method
    lines = code.count("\n") + 1
    if lines > threshold_lines:
        hints.append(
            f"📏 **Long Code Block**: {lines} lines. Consider breaking into smaller functions (<{int(threshold_lines)} lines)."
        )
        triggered_patterns.append(("quality_long_method", lines))

    # High complexity
    conditionals = len(PATTERN_CONDITIONALS.findall(code))
    if conditionals > threshold_complexity:
        hints.append(
            f"🌀 **High Complexity**: {conditionals} conditionals. Consider simplifying."
        )
        triggered_patterns.append(("quality_high_complexity", conditionals))

    # Missing error handling
    if PATTERN_TRY_BLOCK.search(code) and not PATTERN_EXCEPT_BLOCK.search(code):
        hints.append(
            "⚠️ **Missing Error Handler**: Try block without catch/except clause."
        )

    # Debug statements
    is_python = file_path.endswith(".py")
    is_js = file_path.endswith((".js", ".ts", ".jsx", ".tsx"))
    debug_count = (
        len(PATTERN_DEBUG_PY.findall(code))
        if is_python
        else (len(PATTERN_DEBUG_JS.findall(code)) if is_js else 0)
    )
    if debug_count > threshold_debug:
        stmt = "print()" if is_python else "console.log()"
        hints.append(
            f"🐛 **Debug Statements**: {debug_count} {stmt} found. Remove before committing."
        )
        triggered_patterns.append(("quality_debug_statements", debug_count))

    # N+1 query
    if PATTERN_N_PLUS_ONE.search(code):
        hints.append(
            "⚡ **Potential N+1**: Database/API call inside loop. Consider bulk fetching."
        )

    # Nested loops - differentiate O(n²) vs O(n³)
    if PATTERN_TRIPLE_LOOP.search(code):
        hints.append(
            "🔄 **Triple Nested Loops**: O(n³) complexity! Consider hash maps or restructuring."
        )
    elif PATTERN_NESTED_LOOPS.search(code):
        hints.append("🔄 **Nested Loops**: O(n²) complexity.")

    # String concatenation in loops (perf killer)
    if PATTERN_STRING_CONCAT_LOOP.search(code):
        hints.append(
            "📝 **String Concat in Loop**: Use array.join() or list + ''.join() instead of +="
        )

    # Blocking I/O
    if is_js and PATTERN_BLOCKING_IO_NODE.search(code):
        hints.append(
            "🐌 **Blocking I/O**: Use async fs methods instead of Sync variants."
        )
    elif is_python and PATTERN_BLOCKING_IO_PY.search(code):
        hints.append(
            "🐌 **Blocking Read**: Consider `with open() as f: f.read()` pattern."
        )

    # Deep nesting detection (uses adaptive threshold)
    max_indent = 0
    for line in code.split("\n"):
        if line.strip():
            indent = len(line) - len(line.lstrip())
            max_indent = max(max_indent, indent)
    nesting_levels = max_indent // 4  # Assuming 4-space indent
    if nesting_levels > threshold_nesting:
        hints.append(
            f"🪆 **Deep Nesting**: {nesting_levels} levels. Extract to helper functions."
        )
        triggered_patterns.append(("quality_deep_nesting", nesting_levels))

    # Too many magic numbers (uses adaptive threshold)
    threshold_magic = get_adaptive_threshold(state, "quality_magic_numbers")
    magic_count = len(PATTERN_MAGIC_NUMBERS.findall(code))
    if magic_count > threshold_magic:
        hints.append(
            f"🔢 **Magic Numbers**: {magic_count} numeric literals. Use named constants."
        )
        triggered_patterns.append(("quality_magic_numbers", magic_count))

    # Tech debt accumulation (uses adaptive threshold)
    threshold_debt = get_adaptive_threshold(state, "quality_tech_debt_markers")
    todo_count = len(PATTERN_TODO_FIXME.findall(code))
    if todo_count > threshold_debt:
        hints.append(
            f"📝 **Tech Debt**: {todo_count} TODO/FIXME markers in this change."
        )
        triggered_patterns.append(("quality_tech_debt_markers", todo_count))

    if hints:
        # Record all triggered patterns for adaptive learning
        for pattern_name, value in triggered_patterns:
            record_threshold_trigger(state, pattern_name, value)
        return HookResult.with_context(
            "🔍 **Code Quality Check**:\n" + "\n".join(hints[:4])
        )

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

    if ".claude/tmp/" in file_path or ".claude/memory/" in file_path:
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

    if ".claude/tmp/" in file_path or ".claude/memory/" in file_path:
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


@register_hook("velocity_tracker", "Read|Edit|Write|Bash|Glob|Grep", priority=65)
def check_velocity(data: dict, state: SessionState, runner_state: dict) -> HookResult:
    """Detect spinning vs actual progress with adaptive thresholds."""
    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})
    last_5 = state.last_5_tools
    if len(last_5) < 3:
        return HookResult.none()

    # Check if velocity warnings are in cooldown (adaptive learning)
    oscillation_threshold = get_adaptive_threshold(state, "velocity_oscillation")
    if oscillation_threshold == float("inf"):
        return HookResult.none()  # In cooldown, skip all velocity checks

    # SELF-CHECK PATTERN: Edit then immediately re-read same file
    # This indicates distrust of own work - should verify with tests instead
    if tool_name == "Read" and len(last_5) >= 2:
        current_file = tool_input.get("file_path", "")
        if current_file and last_5[-1] in ("Edit", "Write"):
            # Check if this file was recently edited (last 3 edits)
            recent_edits = state.files_edited[-3:] if state.files_edited else []
            if current_file in recent_edits:
                name = (
                    current_file.split("/")[-1] if "/" in current_file else current_file
                )
                return HookResult.with_context(
                    f"🔄 SELF-CHECK: Edited then re-read `{name}`.\n"
                    f"💡 Trust your edit or verify with a test, not re-reading."
                )

    # Need at least 4 tools for pattern detection
    if len(last_5) < 4:
        return HookResult.none()

    # Read→Edit→Read→Edit oscillation
    read_edit_pattern = []
    for tool in last_5:
        if tool in ("Read", "Edit", "Write"):
            read_edit_pattern.append("R" if tool == "Read" else "E")
    pattern_str = "".join(read_edit_pattern)
    if "RERE" in pattern_str or "ERER" in pattern_str:
        record_threshold_trigger(state, "velocity_oscillation", 1)
        return HookResult.with_context(
            "🔄 OSCILLATION: Read→Edit→Read→Edit pattern detected.\n💡 Step back: Are you making progress or checking the same thing repeatedly?"
        )

    # Low tool diversity (check adaptive threshold for iteration)
    iteration_threshold = get_adaptive_threshold(state, "iteration_same_tool")
    if iteration_threshold != float("inf") and len(last_5) == 5:
        unique_tools = len(set(last_5))
        if unique_tools <= 2 and all(t in ("Read", "Glob", "Grep") for t in last_5):
            record_threshold_trigger(state, "iteration_same_tool", 5 - unique_tools)
            return HookResult.with_context(
                "🔄 SEARCH LOOP: 5+ searches without action.\n💡 Do you have enough info to act, or are you avoiding a decision?"
            )

    # Re-reading same file (uses batch_sequential_reads threshold)
    reread_threshold = get_adaptive_threshold(state, "batch_sequential_reads")
    if reread_threshold != float("inf"):
        recent_reads = (
            state.files_read[-10:] if len(state.files_read) >= 10 else state.files_read
        )
        read_counts = Counter(recent_reads)
        repeated = [
            (f, c) for f, c in read_counts.items() if c >= int(reread_threshold)
        ]
        if repeated:
            file, count = repeated[0]
            name = file.split("/")[-1] if "/" in file else file
            record_threshold_trigger(state, "batch_sequential_reads", count)
            return HookResult.with_context(
                f"🔄 RE-READ: `{name}` read {count}x recently.\n💡 What are you looking for that you haven't found?"
            )

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
            crystallize_hint = ""
            if reads >= READS_BEFORE_CRYSTALLIZE:
                crystallize_hint = (
                    "\n\n  💡 **CRYSTALLIZE**: Write what you know to `.claude/tmp/notes.md`\n"
                    "     to solidify understanding before continuing."
                )

            return HookResult.with_context(
                f"\n{severity} INFORMATION GAIN CHECK:\n"
                f"  Reads since last action: {reads}\n"
                f"  Files: {file_list}\n\n"
                f"  **Questions to answer:**\n"
                f"  1. What specific question am I trying to answer?\n"
                f"  2. Did the last read give me actionable info?\n"
                f"  3. Should I act on what I know, or do I need more?{crystallize_hint}\n"
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
    sorted_hooks = sorted(HOOKS, key=lambda x: x[3])

    # Shared state for hooks in this run
    runner_state = {}

    # Collect contexts
    contexts = []

    for name, matcher, check_func, priority in sorted_hooks:
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
