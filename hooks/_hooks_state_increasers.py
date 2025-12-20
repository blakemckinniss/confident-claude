"""
Confidence Increaser PostToolUse hooks.

Success signal confidence increases and thinking quality rewards.
Priority 14 (increaser) and 16 (thinking quality).
"""

import _lib_path  # noqa: F401
import re

from _hook_registry import register_hook
from _hook_result import HookResult
from session_state import SessionState, set_confidence
from confidence import (
    apply_increasers,
    apply_rate_limit,
    format_confidence_change,
    get_tier_info,
    get_current_streak,
)

# Import shared utilities
from _hooks_state import _extract_result_string
from _hooks_state_decay import _track_researched_libraries


# =============================================================================
# CONSTANTS
# =============================================================================

_RE_CHAIN_SEMICOLON = re.compile(r";\s*\w+")
_RE_CHAIN_SPLIT = re.compile(r"\s*&&\s*|\s*;\s*")

_RESEARCH_TOOLS = frozenset(
    {"WebSearch", "WebFetch", "mcp__crawl4ai__crawl", "mcp__crawl4ai__search"}
)
_SEARCH_TOOLS = frozenset({"Grep", "Glob", "Task"})
_DELEGATION_AGENTS = frozenset({"Explore", "scout", "Plan"})

# PAL tools that provide reasoning delegation (v4.19)
_PAL_REASONING_TOOLS = frozenset(
    {
        "mcp__pal__thinkdeep",
        "mcp__pal__debug",
        "mcp__pal__analyze",
        "mcp__pal__codereview",
        "mcp__pal__planner",
        "mcp__pal__consensus",
        "mcp__pal__precommit",
        "mcp__pal__chat",
    }
)

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

_TEST_FILE_PATTERNS = ("test_", "_test.", ".test.", "/tests/", "spec.")
_TEST_COMMANDS = ("pytest", "jest", "npm test", "cargo test", "go test")


# =============================================================================
# PAL SIGNAL BUILDING
# =============================================================================


def _build_pal_signals(
    tool_name: str, tool_input: dict, state: SessionState, context: dict
) -> None:
    """Build context for PAL maximization signals (v4.19).

    Tracks PAL usage to reward offloading reasoning to external LLMs.
    PAL provides 'free' auxiliary context - using it preserves Claude's context.
    """
    # Initialize PAL tracking in session state if needed
    if not hasattr(state, "pal_tracking"):
        state.pal_tracking = {
            "calls_this_turn": 0,
            "last_debug_turn": -100,
            "debug_attempts_since_pal": 0,
        }

    pal_tracking = state.pal_tracking

    # Track PAL tool usage
    if tool_name.startswith("mcp__pal__"):
        context["pal_used_this_turn"] = True
        pal_tracking["calls_this_turn"] = pal_tracking.get("calls_this_turn", 0) + 1

        # Track mcp__pal__debug specifically
        if tool_name == "mcp__pal__debug":
            pal_tracking["last_debug_turn"] = state.turn_count
            pal_tracking["debug_attempts_since_pal"] = 0  # Reset on PAL debug

        # Check for continuation_id reuse
        continuation_id = tool_input.get("continuation_id", "")
        if continuation_id:
            context["continuation_reuse"] = True

    # Expose PAL call count for ParallelPalIncreaser
    context["pal_calls_this_turn"] = pal_tracking.get("calls_this_turn", 0)

    # Check if PAL debug was used recently (within 5 turns)
    last_debug = pal_tracking.get("last_debug_turn", -100)
    context["pal_debug_used_recently"] = (state.turn_count - last_debug) <= 5

    # Track debug attempts without PAL (for DebugLoopNoPalReducer)
    # Increment when Edit/Bash follows a failure without PAL debug
    if tool_name in {"Edit", "Bash"} and not context.get("pal_used_this_turn"):
        # Check if we're in a debug session (recent failures)
        recent_failures = len(getattr(state, "commands_failed", []))
        if recent_failures > 0:
            pal_tracking["debug_attempts_since_pal"] = (
                pal_tracking.get("debug_attempts_since_pal", 0) + 1
            )

    context["debug_attempts_without_pal"] = pal_tracking.get(
        "debug_attempts_since_pal", 0
    )


# =============================================================================
# NATURAL SIGNAL BUILDING
# =============================================================================


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


# =============================================================================
# BASH SIGNAL BUILDING
# =============================================================================


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


# =============================================================================
# OBJECTIVE SIGNAL BUILDING
# =============================================================================


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


# =============================================================================
# TEST ENFORCEMENT TRACKING
# =============================================================================


def _track_test_enforcement(
    tool_name: str,
    tool_input: dict,
    tool_response: dict,
    state: SessionState,
    context: dict,
) -> None:
    """Track test enforcement signals (v4.20).

    Updates session state for:
    - test_frameworks_run: Which test frameworks have been executed
    - last_test_run_turn: When tests were last run
    - files_modified_since_test: Files modified that need test verification
    - test_files_created: Test files created this session (for orphan detection)
    """
    from pathlib import Path

    # Import test detection utilities
    try:
        import sys

        lib_path = str(Path.home() / ".claude" / "lib")
        if lib_path not in sys.path:
            sys.path.insert(0, lib_path)
        from _test_detection import (
            is_test_file,
            is_test_command,
            get_test_framework_from_command,
        )
    except ImportError:
        return  # Graceful degradation if module not available

    # Initialize state fields if needed
    if not hasattr(state, "test_frameworks_run"):
        state.test_frameworks_run = set()
    if not hasattr(state, "last_test_run_turn"):
        state.last_test_run_turn = 0
    if not hasattr(state, "files_modified_since_test"):
        state.files_modified_since_test = set()
    if not hasattr(state, "test_files_created"):
        state.test_files_created = {}
    if not hasattr(state, "test_creation_order"):
        state.test_creation_order = []

    # Track test execution from Bash commands
    if tool_name == "Bash":
        command = tool_input.get("command", "")
        if is_test_command(command):
            framework = get_test_framework_from_command(command)
            if framework:
                state.test_frameworks_run.add(framework)
            state.last_test_run_turn = state.turn_count

            # Clear files_modified_since_test on successful test run
            if context.get("tests_passed", False):
                state.files_modified_since_test.clear()

                # Mark any created test files as executed
                for path, info in state.test_files_created.items():
                    if not info.get("executed", False):
                        info["executed"] = True
                        info["executed_turn"] = state.turn_count

    # Track file modifications
    if tool_name in ("Edit", "Write"):
        file_path = tool_input.get("file_path", "")
        if file_path:
            # Add to files modified since last test
            state.files_modified_since_test.add(file_path)

            # Track test file creation
            if is_test_file(file_path):
                if tool_name == "Write" and file_path not in state.test_files_created:
                    state.test_files_created[file_path] = {
                        "created_turn": state.turn_count,
                        "executed": False,
                    }
                # Track creation order for test-first detection
                state.test_creation_order.append((file_path, True, state.turn_count))
            else:
                # Track non-test file for test-first detection
                state.test_creation_order.append((file_path, False, state.turn_count))

            # Keep creation order bounded
            if len(state.test_creation_order) > 50:
                state.test_creation_order = state.test_creation_order[-50:]


# =============================================================================
# TIME SAVER SIGNAL BUILDING
# =============================================================================


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


# =============================================================================
# COMPLETION SIGNAL BUILDING
# =============================================================================


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


# =============================================================================
# MAIN INCREASER HOOK
# =============================================================================


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
        "tool_input": tool_input,
        "assistant_output": data.get("assistant_output", ""),
    }

    # PAL tracking (v4.19) - track PAL usage for maximization signals
    _build_pal_signals(tool_name, tool_input, state, context)

    # Build signals from each category
    _build_natural_signals(tool_name, tool_input, data, state, context)

    if tool_name == "Bash":
        _build_bash_signals(tool_input, data, context)

    _build_objective_signals(tool_name, tool_input, data, context)
    _track_test_enforcement(tool_name, tool_input, tool_result, state, context)
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


# =============================================================================
# THINKING QUALITY BOOST HOOK
# =============================================================================

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
