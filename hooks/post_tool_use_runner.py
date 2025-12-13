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
    16 thinking_confidence - Analyze reasoning quality in thinking blocks (context-scaled)

  QUALITY GATES (22-50):
    22 assumption_check    - Surface hidden assumptions in code changes
    25 completion_gate     - Remind to verify after fix iterations
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


@register_hook("state_updater", None, priority=10)
def check_state_updater(
    data: dict, state: SessionState, runner_state: dict
) -> HookResult:
    """Update session state based on tool usage."""
    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})
    result = data.get("tool_result", {})
    # Normalize string results to dict format
    if isinstance(result, str):
        result = {"output": result}
    elif not isinstance(result, dict):
        result = {}
    warning = None

    # Update tool count
    state.tool_counts[tool_name] = state.tool_counts.get(tool_name, 0) + 1
    track_batch_tool(state, tool_name, tools_in_message=1)

    # Process by tool type
    if tool_name == "Read":
        filepath = tool_input.get("file_path", "")
        # SELF-HEAL: Detect Read failures on framework files
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

    elif tool_name == "Edit":
        filepath = tool_input.get("file_path", "")
        # SELF-HEAL: Detect Edit failures on framework files
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
                        # Only track if signature CHANGED (not removed)
                        # Removed functions cause immediate errors at call sites
                        if new_def is not None and old_def != new_def:
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

        # Track ops tool usage (v3.9)
        if ".claude/ops/" in command:
            # Extract tool name from command
            ops_match = re.search(r"\.claude/ops/(\w+)\.py", command)
            if ops_match:
                tool_name_ops = ops_match.group(1)
                track_ops_tool(state, tool_name_ops, success)

                # Track audit/void verification for production files
                if success and tool_name_ops in ("audit", "void"):
                    # Extract target file from command args
                    # Pattern: audit.py <filepath> or void.py <filepath>
                    parts = command.split()
                    for i, part in enumerate(parts):
                        if part.endswith(f"{tool_name_ops}.py") and i + 1 < len(parts):
                            target_file = parts[i + 1]
                            # Normalize path
                            if not target_file.startswith("-"):
                                mark_production_verified(
                                    state, target_file, tool_name_ops
                                )
                            break

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


@register_hook("confidence_decay", None, priority=11)
def check_confidence_decay(
    data: dict, state: SessionState, runner_state: dict
) -> HookResult:
    """Dynamic confidence system with survival mechanics.

    DECAY (harsh - every action costs):
    - Base: -1.0 per tool call
    - High confidence tax: +0.5 extra above 85%

    RECOVERY ACTIONS (amplified when struggling):
    - PAL consultation (thinkdeep/debug/etc): +2 base
    - AskUserQuestion: +2 base
    - Task delegation: +1.5 base
    - Read/Memory/Web: +0.5 base

    PENALTIES (scaled by confidence):
    - Edit/Write: -1 base, -2 extra without read, -1 stub
    - Bash: -1

    SURVIVAL MODE (prevents death spiral):
    - Below 30%: 3x boost multiplier (desperate)
    - Below 50%: 2x boost multiplier (struggling)
    - Below 70%: 1.5x boost multiplier (working hard)
    - 70-84%: 1x (normal)
    - 85%+: 0.5x (can't coast to higher)

    Shows 🆘 indicator when survival boost is active.
    """
    tool_name = data.get("tool_name", "")

    # Track accumulated fractional decay
    if not hasattr(state, "_decay_accumulator"):
        state._decay_accumulator = 0.0

    # Base decay per tool call (harsh: every action costs confidence)
    base_decay = 1.0

    # High confidence tax: above 85%, decay faster (complacency penalty)
    if state.confidence >= 85:
        base_decay += 0.5  # 1.5 total at high confidence

    state._decay_accumulator += base_decay

    # Boosts for RECOVERY ACTIONS - these help regain trust
    # Base values are modest; boost_multiplier amplifies when struggling
    boost = 0
    boost_reason = ""
    tool_input = data.get("tool_input", {})

    # === RECOVERY ACTIONS (rewarded more when struggling) ===

    # PAL external consultation - shows humility, seeking help
    if tool_name.startswith("mcp__pal__"):
        pal_tool = tool_name.replace("mcp__pal__", "")
        if pal_tool in ("thinkdeep", "debug", "codereview", "consensus", "precommit"):
            # Heavy consultation = major recovery action
            boost = 2
            boost_reason = f"pal-{pal_tool}"
        elif pal_tool in ("chat", "challenge", "apilookup"):
            # Light consultation
            boost = 1
            boost_reason = f"pal-{pal_tool}"

    # User clarification - reaching out shows humility
    elif tool_name == "AskUserQuestion":
        boost = 2
        boost_reason = "user-clarification"

    # Agent delegation - distributing work wisely
    elif tool_name == "Task":
        boost = 1.5
        boost_reason = "agent-delegation"

    # === INFORMATION GATHERING (modest boosts with diminishing returns) ===

    elif tool_name == "Read":
        # Diminishing returns: first 3 reads = +0.5, then +0.25, then +0.1
        read_count = len([f for f in state.files_read if f])  # Count files read
        if read_count <= 3:
            boost = 0.5
        elif read_count <= 6:
            boost = 0.25
        else:
            boost = 0.1  # Spam reads barely help
        boost_reason = f"file-read({read_count})"

    elif tool_name.startswith("mcp__") and "mem" in tool_name.lower():
        boost = 0.5
        boost_reason = "memory-access"

    elif tool_name in ("WebSearch", "WebFetch"):
        boost = 0.5
        boost_reason = "web-research"

    elif tool_name.startswith("mcp__crawl4ai__"):
        boost = 0.5
        boost_reason = "web-crawl"

    # Grep/Glob/EnterPlanMode - no boost (searching/planning ≠ understanding)

    # Penalties for risky actions (in addition to decay)
    penalty = 0
    penalty_reason = ""

    if tool_name in ("Edit", "Write"):
        file_path = tool_input.get("file_path", "")

        # Base edit penalty: every edit is a risk (could introduce bugs)
        penalty = 1
        penalty_reason = "edit-risk"

        # Edit without reading first = extra penalty for skipping context
        if file_path and file_path not in state.files_read:
            penalty += 2
            penalty_reason = "edit-without-read"

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
                penalty_reason += "+stub"

    # Bash commands are risky - state changes, potential failures
    elif tool_name == "Bash":
        penalty = 1
        penalty_reason = "bash-risk"

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
        state.confidence = new_confidence  # Direct assignment, already bounds-checked

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


@register_hook("confidence_reducer", None, priority=12)
def check_confidence_reducer(
    data: dict, state: SessionState, runner_state: dict
) -> HookResult:
    """Apply deterministic confidence reductions based on failure signals.

    Reducers fire MECHANICALLY without judgment:
    - tool_failure: -5 (Bash exit != 0)
    - cascade_block: -15 (same hook blocks 3+ times)
    - sunk_cost: -20 (3+ consecutive failures)
    - edit_oscillation: -12 (same file edited 3+ times)
    """
    tool_name = data.get("tool_name", "")
    tool_result = data.get("tool_result", {})

    # Build context for reducers
    context = {
        "tool_name": tool_name,
        "tool_result": tool_result,
    }

    # Check for tool failure (Bash exit code != 0)
    if tool_name == "Bash":
        if isinstance(tool_result, dict):
            exit_code = tool_result.get("exit_code", 0)
            if exit_code != 0:
                context["tool_failed"] = True

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
    state.confidence = new_confidence  # Direct assignment

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

    return HookResult.with_context(
        f"📉 **Confidence Reduced**\n{change_msg}\n\n"
        f"Current: {emoji} {new_confidence}% - {desc}"
        f"{dispute_hint}"
    )


# -----------------------------------------------------------------------------
# CONFIDENCE INCREASER (priority 14) - Success signal confidence increases
# -----------------------------------------------------------------------------


@register_hook("confidence_increaser", None, priority=14)
def check_confidence_increaser(
    data: dict, state: SessionState, runner_state: dict
) -> HookResult:
    """Apply confidence increases based on success signals.

    Auto-increases (+5, no approval):
    - test_pass: Tests passed successfully
    - build_success: Build completed successfully

    Large increases (+15, requires approval):
    - trust_regained: User explicitly restored trust
    """
    tool_name = data.get("tool_name", "")
    tool_result = data.get("tool_result", {})

    # Build context for increasers
    context = {
        "tool_name": tool_name,
        "tool_result": tool_result,
    }

    # Check for successful test/build commands
    if tool_name == "Bash":
        if isinstance(tool_result, dict):
            exit_code = tool_result.get("exit_code", 0)
            output = tool_result.get("output", "").lower()

            if exit_code == 0:
                # Check for test success patterns
                if any(
                    p in output
                    for p in ["passed", "tests passed", "ok", "success", "✓"]
                ):
                    context["tests_passed"] = True
                # Check for build success
                if any(p in output for p in ["built", "compiled", "build successful"]):
                    context["build_succeeded"] = True

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
        state.confidence = new_confidence  # Direct assignment

        reasons = [f"{name}: +{delta}" for name, delta, _ in auto_increases]
        change_msg = format_confidence_change(
            old_confidence, new_confidence, ", ".join(reasons)
        )

        _, emoji, desc = get_tier_info(new_confidence)
        messages.append(
            f"📈 **Confidence Increased**\n{change_msg}\n\n"
            f"Current: {emoji} {new_confidence}% - {desc}"
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
# THINKING CONFIDENCE (priority 16) - Micro-adjust based on reasoning quality
# -----------------------------------------------------------------------------

# Patterns that indicate uncertainty/confusion (reduce confidence)
_THINKING_UNCERTAINTY_PATTERNS = [
    # Uncertainty & hedging
    (
        re.compile(r"\b(I'm not sure|not certain|unclear|confus)", re.I),
        -1,
        "uncertainty",
    ),
    (re.compile(r"\b(maybe|might|could be|possibly|perhaps)\b", re.I), -1, "hedging"),
    (re.compile(r"\b(I think|I believe|I assume)\b", re.I), -1, "assumption"),
    (re.compile(r"\b(should work|hopefully|probably)\b", re.I), -1, "hope-driven"),
    # Confusion & backtracking
    (
        re.compile(r"\b(wait|hmm+|let me reconsider|let me think)\b", re.I),
        -2,
        "confusion",
    ),
    (
        re.compile(r"\b(actually|no wait|I was wrong|that's wrong)\b", re.I),
        -2,
        "backtrack",
    ),
    (
        re.compile(r"\b(this is (tricky|complex|difficult|confusing))\b", re.I),
        -1,
        "complexity",
    ),
    # Logical fallacies
    (
        re.compile(r"\b(must be|has to be|obviously means)\b", re.I),
        -1,
        "jumping-conclusion",
    ),
    (re.compile(r"\b(always|never|every time|impossible)\b", re.I), -1, "absolutism"),
    (re.compile(r"\b(the user (wants|expects|needs))\b", re.I), -1, "mind-reading"),
    # Indecisive assertions
    (re.compile(r"\b(I (could|might|may) (try|do|use))\b", re.I), -1, "indecisive"),
    (
        re.compile(r"\b(one option|another approach|alternatively)\b", re.I),
        -1,
        "waffling",
    ),
    # Skipping verification
    (
        re.compile(
            r"\b(skip|don't need to|no need to) (check|verify|read|test)\b", re.I
        ),
        -2,
        "skip-verify",
    ),
    (
        re.compile(r"\b(assume|assuming) (it|this|that) (works|exists|is)\b", re.I),
        -1,
        "blind-assumption",
    ),
]

# Patterns that indicate clear reasoning (maintain/boost confidence)
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


@register_hook("thinking_confidence", None, priority=16)
def check_thinking_confidence(
    data: dict, state: SessionState, runner_state: dict
) -> HookResult:
    """Micro-adjust confidence based on reasoning quality in thinking blocks.

    Analyzes the thinking that led to this tool call for:
    - Uncertainty markers: hedging, assumptions, confusion (-1 to -2)
    - Clarity markers: certainty, verified reasoning (+1)

    Max adjustment per tool call: -5 to +2
    """
    from synapse_core import extract_thinking_blocks

    transcript_path = data.get("transcript_path", "")
    if not transcript_path:
        return HookResult.none()

    thinking_blocks = extract_thinking_blocks(transcript_path)
    if not thinking_blocks:
        return HookResult.none()

    # Analyze most recent thinking (last 2 blocks, last 2000 chars)
    recent_thinking = " ".join(thinking_blocks[-2:])[-2000:]
    if not recent_thinking:
        return HookResult.none()

    # Calculate adjustment
    adjustment = 0
    triggered = []

    # Check uncertainty patterns (penalties)
    for pattern, delta, label in _THINKING_UNCERTAINTY_PATTERNS:
        matches = len(pattern.findall(recent_thinking))
        if matches > 0:
            # Cap at 2 matches per pattern to avoid over-penalizing
            adj = delta * min(matches, 2)
            adjustment += adj
            triggered.append(f"{label}:{adj}")

    # Check confidence patterns (small boosts)
    for pattern, delta, label in _THINKING_CONFIDENCE_PATTERNS:
        if pattern.search(recent_thinking):
            adjustment += delta
            triggered.append(f"{label}:+{delta}")

    # Cap total adjustment to avoid wild swings
    adjustment = max(-5, min(2, adjustment))

    if adjustment == 0:
        return HookResult.none()

    # Apply context-based scaling
    context_pct = _get_context_percentage(transcript_path)
    ctx_penalty_mult, ctx_boost_mult = _get_context_multiplier(context_pct)

    # Scale adjustment based on context
    if adjustment < 0:
        # Penalties: multiply by context pressure
        scaled_adjustment = int(adjustment * ctx_penalty_mult)
    else:
        # Boosts: reduce at high context
        scaled_adjustment = int(adjustment * ctx_boost_mult)

    if scaled_adjustment == 0:
        return HookResult.none()

    # Apply rate limiting to prevent death spiral stacking
    scaled_adjustment = apply_rate_limit(scaled_adjustment, state)

    if scaled_adjustment == 0:
        return HookResult.none()

    # Apply micro-adjustment
    old_confidence = state.confidence
    new_confidence = max(0, min(100, old_confidence + scaled_adjustment))

    if new_confidence != old_confidence:
        state.confidence = new_confidence  # Direct assignment
        direction = "📉" if scaled_adjustment < 0 else "📈"

        # Add context indicator if significant
        ctx_suffix = f", CTX:{context_pct:.0f}%" if context_pct >= 40 else ""
        return HookResult.with_context(
            f"{direction} **Thinking confidence**: {old_confidence}% → {new_confidence}% "
            f"({'+' if scaled_adjustment > 0 else ''}{scaled_adjustment}) "
            f"[{', '.join(triggered[:3])}{ctx_suffix}]"
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

    # Debug statements (skip for CLI tools in ops/ where print IS the output)
    is_python = file_path.endswith(".py")
    is_js = file_path.endswith((".js", ".ts", ".jsx", ".tsx"))
    is_cli_tool = "/ops/" in file_path or "/.claude/hooks/" in file_path
    debug_count = (
        len(PATTERN_DEBUG_PY.findall(code))
        if is_python
        else (len(PATTERN_DEBUG_JS.findall(code)) if is_js else 0)
    )
    if debug_count > threshold_debug and not is_cli_tool:
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
