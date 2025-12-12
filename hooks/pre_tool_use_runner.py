#!/usr/bin/env python3
"""
Composite PreToolUse Runner: Runs all PreToolUse hooks in a single process.

PERFORMANCE: ~35ms for 24 hooks vs ~400ms for individual processes (10x faster)

HOOKS INDEX (by priority):
  ORCHESTRATION (0-5):
    3  exploration_cache   - Return cached exploration results
    3  parallel_bead_delegation - Force parallel Task agents for multiple open beads
    4  parallel_nudge      - Nudge sequential Task spawns → parallel + background
    4  beads_parallel      - Nudge sequential bd commands → batch/parallel
    4  bead_enforcement    - Require in_progress bead before Edit/Write

  SAFETY (5-20):
    5  recursion_guard     - Block nested .claude/.claude paths
    10 loop_detector       - Block bash loops
    15 background_enforcer - Require background for slow commands

  GATES (20-50):
    20 commit_gate         - Warn on git commit without upkeep
    25 tool_preference     - Nudge toward preferred tools
    30 oracle_gate         - Enforce think/council after failures
    35 integration_gate    - Require grep after function edits
    40 error_suppression   - Block until errors resolved
    45 content_gate        - Block eval/exec/SQL injection
    50 gap_detector        - Block edit without read

  QUALITY (55-95):
    55 production_gate     - Audit/void for .claude/ops writes
    60 deferral_gate       - Block "TODO: later" comments
    65 doc_theater_gate    - Block standalone .md files
    70 root_pollution_gate - Block home directory clutter
    75 recommendation_gate - Warn on duplicate infrastructure
    80 security_claim_gate - Warn on security-sensitive code
    85 epistemic_boundary  - Warn on unverified identifiers
    88 research_gate       - Block unverified libraries
    92 import_gate         - Warn on third-party imports
    95 modularization_nudge- Occasional modularization reminder

  SESSION (80-90):
    80 sunk_cost_detector  - Detect failure loops
    90 thinking_coach      - Detect reasoning flaws

ARCHITECTURE:
  - Hooks register via @register_hook(name, matcher, priority)
  - Lower priority = runs first
  - First DENY wins, contexts are aggregated
  - Single state load/save per invocation
"""

import _lib_path  # noqa: F401
import sys
import json
import os
import re
import time
from pathlib import Path
from typing import Optional, Callable
from dataclasses import dataclass
from session_state import (
    load_state,
    save_state,
    SessionState,
    track_block,
    clear_blocks,
    check_cascade_failure,
)

# =============================================================================
# PRE-COMPILED PATTERNS (Performance: compile once at module load)
# =============================================================================

# Bash loop detection patterns
_BASH_LOOP_PATTERNS = [
    re.compile(r"\bfor\s+\w+\s+in\b", re.IGNORECASE),
    re.compile(r"\bwhile\s+", re.IGNORECASE),
    re.compile(r"\buntil\s+", re.IGNORECASE),
    re.compile(r"\|\s*while\b", re.IGNORECASE),
    re.compile(r"\bxargs\s+.*\bsh\b", re.IGNORECASE),
    re.compile(r"\bfind\s+.*-exec\b", re.IGNORECASE),
]

# Allowed loop patterns (safe exceptions)
_BASH_ALLOWED_PATTERNS = [
    re.compile(r"for\s+\w+\s+in\s+\$\(", re.IGNORECASE),
    re.compile(r"for\s+\w+\s+in\s+[~./\w-]*\*", re.IGNORECASE),
    re.compile(r"while\s+read.*<<<", re.IGNORECASE),
    re.compile(r'python[3]?\s+.*-c\s+["\']', re.IGNORECASE),
    re.compile(
        r"\bfind\s+.*-exec\s+(chmod|chown|chgrp|rm|mv|cp|touch|mkdir|ln|stat)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"for\s+\w+\s+in\s+[\w.-]+\s+[\w.-]+(\s+[\w.-]+){0,5}\s*;", re.IGNORECASE
    ),
    re.compile(r"\btime\s+\(", re.IGNORECASE),
    # Allow brace expansion loops (small fixed iterations like {1..5}, {0..10})
    re.compile(r"for\s+\w+\s+in\s+\{\d+\.\.\d+\}", re.IGNORECASE),
]

# Script nudge loop patterns (simpler set)
_SCRIPT_NUDGE_PATTERNS = [
    re.compile(r"\bfor\s+\w+\s+in\b", re.IGNORECASE),
    re.compile(r"\bwhile\s+", re.IGNORECASE),
    re.compile(r"\bxargs\b", re.IGNORECASE),
    re.compile(r"\|\s*while\b", re.IGNORECASE),
]

# Heredoc detection - matches << 'DELIM', << "DELIM", << DELIM, <<-DELIM variants
_HEREDOC_PATTERN = re.compile(r"<<-?\s*['\"]?(\w+)['\"]?")


def strip_heredoc_content(command: str) -> str:
    """Extract only the shell command portion, excluding heredoc content.

    For 'cat > file << EOF\\ncontent\\nEOF', returns 'cat > file << EOF'.
    This prevents false positives when heredoc content mentions slow commands.
    """
    match = _HEREDOC_PATTERN.search(command)
    if not match:
        return command

    # Return everything up to and including the heredoc delimiter declaration
    heredoc_start = match.end()
    return command[:heredoc_start]


# Thinking coach flaw patterns
_FLAW_PATTERNS = [
    (re.compile(r"(don't|no) need to (read|check|verify)", re.IGNORECASE), "shortcut"),
    (re.compile(r"I (assume|believe) (the|this)", re.IGNORECASE), "assumption"),
    (
        re.compile(
            r"(this|that) (should|will) (definitely\s+)?(work|fix)", re.IGNORECASE
        ),
        "overconfidence",
    ),
]

# =============================================================================
# HOOK RESULT TYPE
# =============================================================================


@dataclass
class HookResult:
    """Result from a hook check."""

    decision: str = "approve"  # "approve" or "deny"
    reason: str = ""  # Reason for deny
    context: str = ""  # Additional context to inject

    @staticmethod
    def approve(context: str = "") -> "HookResult":
        return HookResult(decision="approve", context=context)

    @staticmethod
    def deny(reason: str) -> "HookResult":
        return HookResult(decision="deny", reason=reason)


# =============================================================================
# HOOK REGISTRY
# =============================================================================

# Format: (name, matcher_pattern, check_function, priority)
# Lower priority = runs first. Blocks stop execution.
# matcher_pattern: None = all tools, str = regex pattern
HOOKS: list[tuple[str, Optional[str], Callable, int]] = []


def register_hook(name: str, matcher: Optional[str], priority: int = 50):
    """Decorator to register a hook check function.

    Hooks can be disabled via environment variable:
        CLAUDE_HOOK_DISABLE_<NAME>=1

    Example:
        CLAUDE_HOOK_DISABLE_CONTENT_GATE=1 claude
    """

    def decorator(func: Callable[[dict, SessionState], HookResult]):
        # Check if hook is disabled via environment variable
        env_key = f"CLAUDE_HOOK_DISABLE_{name.upper()}"
        if os.environ.get(env_key, "0") == "1":
            return func  # Skip registration
        HOOKS.append((name, matcher, func, priority))
        return func

    return decorator


# =============================================================================
# HOOK IMPLEMENTATIONS (inline for now, can be split to modules later)
# =============================================================================


@register_hook("loop_detector", "Bash", priority=10)
def check_loop_detector(data: dict, state: SessionState) -> HookResult:
    """Block bash loops (Hard Block #6)."""
    from synapse_core import check_sudo_in_transcript

    tool_input = data.get("tool_input", {})
    command = tool_input.get("command", "")
    description = tool_input.get("description", "")
    transcript_path = data.get("transcript_path", "")

    if not command:
        return HookResult.approve()

    # SUDO bypass
    if "SUDO LOOP" in description.upper() or "SUDO_LOOP" in description.upper():
        return HookResult.approve()
    if check_sudo_in_transcript(transcript_path):
        return HookResult.approve()

    # Strip heredocs first, then quotes
    check_cmd = strip_heredoc_content(command)
    check_cmd = re.sub(r"'[^']*'", "'Q'", check_cmd)
    check_cmd = re.sub(r'"[^"]*"', '"Q"', check_cmd)

    # Use pre-compiled patterns from module level
    for pattern in _BASH_ALLOWED_PATTERNS:
        if pattern.search(check_cmd):
            return HookResult.approve()

    for pattern in _BASH_LOOP_PATTERNS:
        match = pattern.search(check_cmd)
        if match:
            return HookResult.deny(
                f"**BASH LOOP BLOCKED** (Hard Block #6)\n"
                f"Detected: `{match.group(0)}`\n"
                f"Use `parallel.py` or `swarm` instead.\n"
                f"Bypass: Include 'SUDO LOOP' in description."
            )


@register_hook("python_path_enforcer", "Bash", priority=12)
def check_python_path_enforcer(data: dict, state: SessionState) -> HookResult:
    """Enforce venv python usage instead of system python."""
    from synapse_core import log_block, format_block_acknowledgment

    tool_input = data.get("tool_input", {})
    command = tool_input.get("command", "")

    project_dir = os.environ.get("CLAUDE_PROJECT_DIR", str(Path.home()))
    venv_python = f"{project_dir}/.claude/.venv/bin/python"

    # Only enforce if venv exists
    if not os.path.exists(venv_python):
        return HookResult.approve()

    # Pattern: bare python/pip at start or after shell operators (exclude heredoc content)
    cmd_to_check = strip_heredoc_content(command)
    bare_python = re.search(r"(^|&&|\|\||;|\|)\s*(python3?|pip3?)\s", cmd_to_check)

    if bare_python and ".venv/bin" not in cmd_to_check:
        venv_bin = f"{project_dir}/.claude/.venv/bin"
        reason = f"Use venv: {venv_bin}/python or {venv_bin}/pip"
        log_block("python_path_enforcer", reason, "Bash", tool_input)
        return HookResult.deny(
            reason + format_block_acknowledgment("python_path_enforcer")
        )


@register_hook("script_nudge", "Bash", priority=14)
def check_script_nudge(data: dict, state: SessionState) -> HookResult:
    """Suggest writing scripts for complex manual work."""
    tool_input = data.get("tool_input", {})
    command = tool_input.get("command", "")

    PIPE_THRESHOLD = 3

    # Strip heredoc content to avoid false positives
    cmd_to_check = strip_heredoc_content(command)

    # Count pipes
    pipe_count = cmd_to_check.count("|")
    if pipe_count >= PIPE_THRESHOLD:
        return HookResult.approve(
            f"⚡ SCRIPT OPPORTUNITY: {pipe_count} pipes detected\n"
            f"→ Consider: .claude/tmp/solve_$(date +%s).py"
        )

    # Check for loop patterns (use pre-compiled patterns)
    for pattern in _SCRIPT_NUDGE_PATTERNS:
        if pattern.search(cmd_to_check):
            return HookResult.approve(
                "⚡ SCRIPT OPPORTUNITY: loop/iteration detected\n"
                "→ Consider: .claude/tmp/solve_$(date +%s).py"
            )


@register_hook("background_enforcer", "Bash", priority=15)
def check_background_enforcer(data: dict, state: SessionState) -> HookResult:
    """Enforce background execution for slow commands."""
    tool_input = data.get("tool_input", {})
    command = tool_input.get("command", "")
    run_in_background = tool_input.get("run_in_background", False)

    if run_in_background:
        return HookResult.approve()

    SLOW_COMMANDS = [
        "npm install",
        "npm ci",
        "npm run build",
        "npm test",
        "yarn install",
        "yarn build",
        "yarn test",
        "pip install",
        "pip3 install",
        "cargo build",
        "cargo test",
        "go build",
        "go test",
        "make",
        "cmake",
        "docker build",
        "docker-compose up",
        "tsc",
        "webpack",
        "vite build",
        "pytest",
        "python -m pytest",
    ]

    # Strip heredoc content to avoid false positives on content mentioning slow commands
    cmd_to_check = strip_heredoc_content(command).lower()
    for slow in SLOW_COMMANDS:
        if slow in cmd_to_check:
            return HookResult.deny(
                f"⛔ USE BACKGROUND EXECUTION\n"
                f"Command contains `{slow}` which is slow.\n"
                f"Re-issue with: run_in_background=true"
            )


@register_hook("probe_gate", "Bash", priority=18)
def check_probe_gate(data: dict, state: SessionState) -> HookResult:
    """Suggest probing unfamiliar library APIs before using them."""
    tool_input = data.get("tool_input", {})
    command = tool_input.get("command", "")

    # Libraries that benefit from runtime probing
    PROBEABLE_LIBS = {
        "pandas": "DataFrame, Series methods",
        "polars": "LazyFrame, expressions",
        "numpy": "array operations",
        "requests": "Response object",
        "httpx": "async client",
        "boto3": "client/resource methods",
        "anthropic": "messages API",
        "openai": "chat completions",
        "playwright": "page methods",
        "fastapi": "app, router",
        "sqlalchemy": "session, query",
    }

    PYTHON_RUN_PATTERNS = [r"python3?\s+", r"pytest", r"ipython"]

    # Check if Python-related command
    is_python_cmd = any(re.search(p, command) for p in PYTHON_RUN_PATTERNS)
    if not is_python_cmd:
        return HookResult.approve()

    # Extract library mentions
    found_libs = []
    for lib, api_hint in PROBEABLE_LIBS.items():
        if re.search(rf"\b{lib}\b", command, re.IGNORECASE):
            # Check if already probed this session
            probed = getattr(state, "probed_libs", [])
            if lib.lower() not in [p.lower() for p in probed]:
                found_libs.append((lib, api_hint))

    if found_libs and len(found_libs) <= 2:
        suggestions = [f"• `{lib}` ({hint})" for lib, hint in found_libs[:2]]
        return HookResult.approve(
            "🔬 PROBE SUGGESTION: Unfamiliar library API\n"
            + "\n".join(suggestions)
            + '\n→ `probe "<lib>.<object>"` prevents API guessing'
        )


@register_hook("commit_gate", "Bash", priority=20)
def check_commit_gate(data: dict, state: SessionState) -> HookResult:
    """Block git commit without upkeep."""
    tool_input = data.get("tool_input", {})
    command = tool_input.get("command", "")

    if "git commit" not in command:
        return HookResult.approve()

    # Check if upkeep was run recently
    from session_state import get_turns_since_op

    turns_since = get_turns_since_op(state, "upkeep")

    if turns_since > 20:
        return HookResult.approve(
            "⚠️ COMMIT GATE: Consider running `upkeep` before committing."
        )


@register_hook("tool_preference", "Bash|TodoWrite", priority=25)
def check_tool_preference(data: dict, state: SessionState) -> HookResult:
    """Nudge toward preferred tools."""
    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})

    if tool_name == "TodoWrite":
        return HookResult.approve(
            "💡 Consider using `bd` (beads) instead of TodoWrite for persistent task tracking."
        )

    if tool_name == "Bash":
        command = tool_input.get("command", "")
        # Prefer Read over cat
        if command.startswith("cat ") and "|" not in command:
            return HookResult.approve(
                "💡 Prefer `Read` tool over `cat` for reading files."
            )
        # Prefer Grep over grep
        if command.startswith(("grep ", "rg ")) and not any(
            x in command for x in ["|", "&&", ";"]
        ):
            return HookResult.approve(
                "💡 Prefer `Grep` tool over bash grep for searching."
            )


@register_hook("sunk_cost_detector", None, priority=80)
def check_sunk_cost(data: dict, state: SessionState) -> HookResult:
    """Detect sunk cost trap."""
    from session_state import check_sunk_cost as _check

    is_trapped, message = _check(state)
    if is_trapped:
        return HookResult.approve(message)


@register_hook("thinking_coach", None, priority=90)
def check_thinking_coach(data: dict, state: SessionState) -> HookResult:
    """Analyze thinking blocks for reasoning flaws."""
    from synapse_core import extract_thinking_blocks

    tool_name = data.get("tool_name", "")
    transcript_path = data.get("transcript_path", "")

    # Skip for read-only tools
    if tool_name in {"Read", "Glob", "Grep", "TodoWrite", "BashOutput"}:
        return HookResult.approve()

    if not transcript_path:
        return HookResult.approve()

    thinking_blocks = extract_thinking_blocks(transcript_path)
    if not thinking_blocks:
        return HookResult.approve()

    # Quick pattern check
    combined = " ".join(thinking_blocks[-2:])[-1000:]

    # Use pre-compiled patterns from module level
    for pattern, flaw_type in _FLAW_PATTERNS:
        if pattern.search(combined):
            return HookResult.approve(
                f"⚠️ THINKING COACH: Detected `{flaw_type}` pattern. Verify before proceeding."
            )


# =============================================================================
# READ CACHE (Priority 2) - Memoize file reads
# =============================================================================


@register_hook("read_cache", "Read", priority=2)
def check_read_cache(data: dict, state: SessionState) -> HookResult:
    """
    Return cached file content if file hasn't changed.

    Uses mtime-based validation for fast checks.
    Invalidated by Write/Edit hooks in post_tool_use_runner.
    """
    tool_input = data.get("tool_input", {})
    file_path = tool_input.get("file_path", "")

    if not file_path:
        return HookResult.approve()

    # Check for partial reads - don't cache those
    if tool_input.get("offset") or tool_input.get("limit"):
        return HookResult.approve()

    try:
        from cache.read_cache import check_read_cache as get_cached

        cached_content = get_cached(file_path)
        if cached_content:
            # Return cached content as context
            from pathlib import Path

            filename = Path(file_path).name
            return HookResult.approve_with_context(
                f"📦 **CACHED READ** ({filename})\n"
                f"File unchanged since last read. Cached content:\n\n"
                f"```\n{cached_content[:50000]}\n```\n"
                f"_(Use `fresh` in prompt to force re-read)_"
            )
    except Exception:
        pass


# =============================================================================
# EXPLORATION CACHE (Priority 3) - Memoize Explore agent calls
# =============================================================================


@register_hook("exploration_cache", "Task", priority=3)
def check_exploration_cache(data: dict, state: SessionState) -> HookResult:
    """
    Return cached exploration results for Explore agents.

    This delivers cache as tool output (not context injection) so Claude
    treats it as authoritative data rather than advisory noise.
    """
    tool_input = data.get("tool_input", {})
    subagent_type = tool_input.get("subagent_type", "")

    # Only intercept Explore agents
    if subagent_type.lower() != "explore":
        return HookResult.approve()

    prompt = tool_input.get("prompt", "")
    if not prompt:
        return HookResult.approve()

    # Check for bypass keywords
    prompt_lower = prompt.lower()
    if any(
        kw in prompt_lower for kw in ["force", "fresh", "re-explore", "bypass cache"]
    ):
        return HookResult.approve()

    # Detect project path
    try:
        from project_detector import detect_project

        project_info = detect_project()
        if not project_info or not project_info.get("path"):
            return HookResult.approve()
        project_path = project_info["path"]
    except Exception:
        return HookResult.approve()

    # Check exploration cache
    try:
        from cache.exploration_cache import check_exploration_cache as get_cached

        cached_result = get_cached(project_path, prompt)
        if cached_result:
            # Return cached result as context - Claude sees this as authoritative
            return HookResult.approve(cached_result)
    except Exception:
        pass

    # Check grounding cache for common grounding queries
    grounding_keywords = [
        "tech stack",
        "framework",
        "what is this project",
        "project structure",
        "dependencies",
        "entry point",
        "how is this project",
        "what does this project use",
    ]
    if any(kw in prompt_lower for kw in grounding_keywords):
        try:
            from cache.grounding_analyzer import get_or_create_grounding

            grounding = get_or_create_grounding(Path(project_path))
            if grounding:
                return HookResult.approve(grounding.to_markdown())
        except Exception:
            pass


@register_hook("parallel_nudge", "Task", priority=4)
def check_parallel_nudge(data: dict, state: SessionState) -> HookResult:
    """
    Nudge sequential Task spawns toward parallel execution + background promotion.

    PATTERNS DETECTED:
    1. Sequential single Tasks → nudge to spawn multiple in one message
    2. Long-running agent types → suggest run_in_background=true
    3. Track background tasks for later check-in reminders
    """
    tool_input = data.get("tool_input", {})
    prompt = tool_input.get("prompt", "")
    subagent_type = tool_input.get("subagent_type", "").lower()

    # Skip resume operations (continuing existing work)
    if tool_input.get("resume"):
        return HookResult.approve()

    # Track background tasks
    if tool_input.get("run_in_background"):
        # Record for later check-in reminder
        if not hasattr(state, "background_tasks"):
            state.background_tasks = []
        state.background_tasks = (
            state.background_tasks
            + [{"type": subagent_type, "prompt": prompt[:50], "turn": state.turn_count}]
        )[-5:]
        return HookResult.approve()

    current_turn = state.turn_count
    messages = []

    # === BACKGROUND PROMOTION ===
    # Agent types that benefit from background execution
    long_running_agents = {
        "explore": "exploring large codebases",
        "plan": "generating detailed plans",
        "code-reviewer": "comprehensive code review",
        "deep-security": "security audits",
        "scout": "codebase exploration",
    }
    if subagent_type in long_running_agents:
        messages.append(
            f"💡 **Background opportunity**: {subagent_type} agents can run with "
            f"`run_in_background: true` - continue working while it runs, check with TaskOutput later."
        )

    # === SEQUENTIAL TASK DETECTION ===
    # Reset counter if new turn
    if state.last_task_turn != current_turn:
        if state.last_task_turn > 0 and state.task_spawns_this_turn == 1:
            state.consecutive_single_tasks += 1
        elif state.task_spawns_this_turn > 1:
            state.consecutive_single_tasks = 0
        state.task_spawns_this_turn = 0
        state.last_task_turn = current_turn

    state.task_spawns_this_turn += 1

    # Track recent prompts
    if prompt:
        state.task_prompts_recent = (state.task_prompts_recent + [prompt[:100]])[-5:]

    # Multiple tasks this turn = good parallel behavior
    if state.task_spawns_this_turn > 1:
        state.consecutive_single_tasks = 0
        return (
            HookResult.approve("\n".join(messages))
            if messages
            else HookResult.approve()
        )

    # Sequential single-Task pattern
    if state.consecutive_single_tasks >= 2:
        state.parallel_nudge_count += 1
        if state.consecutive_single_tasks >= 3:
            messages.insert(
                0,
                "⚡ **PARALLEL AGENTS**: 3+ sequential Tasks detected. "
                "Spawn ALL independent Tasks in ONE message for concurrent execution.",
            )
        else:
            messages.insert(
                0,
                "💡 **Parallel opportunity**: Multiple independent Tasks? Spawn them all in one message.",
            )

    return HookResult.approve("\n".join(messages)) if messages else HookResult.approve()


@register_hook("beads_parallel", "Bash", priority=4)
def check_beads_parallel(data: dict, state: SessionState) -> HookResult:
    """
    Nudge sequential beads (bd) commands toward parallel execution.

    PATTERN: Multiple bd create/update/close commands should be batched or parallelized.
    """
    tool_input = data.get("tool_input", {})
    command = tool_input.get("command", "")

    # Only care about beads commands
    if not re.search(r"\bbd\s+(create|update|close|dep)", command):
        return HookResult.approve()

    # Track beads commands
    if not hasattr(state, "recent_beads_commands"):
        state.recent_beads_commands = []

    current_turn = state.turn_count

    # Clean old entries (older than 3 turns)
    state.recent_beads_commands = [
        cmd
        for cmd in state.recent_beads_commands
        if current_turn - cmd.get("turn", 0) <= 3
    ]

    # Check for sequential beads pattern
    recent_count = len(state.recent_beads_commands)

    # Record this command
    state.recent_beads_commands.append({"cmd": command[:50], "turn": current_turn})

    # Nudge after 2+ recent beads commands
    if recent_count >= 2:
        # Check if these could be batched
        if "bd close" in command:
            return HookResult.approve(
                "⚡ **BEADS BATCH**: Multiple bd commands detected. "
                "`bd close` supports multiple IDs: `bd close id1 id2 id3`. "
                "Batch operations are faster than sequential."
            )
        elif "bd create" in command:
            return HookResult.approve(
                "⚡ **BEADS PARALLEL**: Multiple bd create commands? "
                "Run them in parallel Bash calls in one message, or use Task agents with run_in_background."
            )

    return HookResult.approve()


# =============================================================================
# BEAD-ENFORCED PARALLEL WORKFLOW
# =============================================================================

# Cache for bd queries (avoid repeated subprocess calls)
_BD_CACHE: dict = {}
_BD_CACHE_TURN: int = 0


def _get_open_beads(state: SessionState) -> list:
    """Get open beads, cached per turn."""
    global _BD_CACHE, _BD_CACHE_TURN

    current_turn = state.turn_count
    if _BD_CACHE_TURN == current_turn and "open_beads" in _BD_CACHE:
        return _BD_CACHE.get("open_beads", [])

    # Cache miss - query bd
    try:
        import subprocess

        result = subprocess.run(
            ["bd", "list", "--status=open,in_progress", "--json"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        if result.returncode == 0:
            beads = json.loads(result.stdout) if result.stdout.strip() else []
            _BD_CACHE = {"open_beads": beads}
            _BD_CACHE_TURN = current_turn
            return beads
    except Exception:
        pass

    return []


def _get_in_progress_beads(state: SessionState) -> list:
    """Get beads currently being worked on."""
    beads = _get_open_beads(state)
    return [b for b in beads if b.get("status") == "in_progress"]


@register_hook("bead_enforcement", "Edit|Write", priority=4)
def check_bead_enforcement(data: dict, state: SessionState) -> HookResult:
    """
    Enforce bead tracking for substantive work.

    BLOCKS Edit/Write on project files without an in_progress bead.
    Skips: .claude/ paths, tmp files, config files.
    """
    tool_input = data.get("tool_input", {})
    file_path = tool_input.get("file_path", "")

    if not file_path:
        return HookResult.approve()

    # Skip framework/config paths - always allowed
    skip_patterns = [
        r"\.claude/",
        r"\.git/",
        r"/tmp/",
        r"\.env",
        r"package-lock\.json",
        r"\.lock$",
        r"node_modules/",
    ]
    if any(re.search(p, file_path) for p in skip_patterns):
        return HookResult.approve()

    # Check for in_progress beads
    in_progress = _get_in_progress_beads(state)

    if not in_progress:
        # No active bead - nudge to create one
        return HookResult.approve(
            "⚠️ **BEAD REQUIRED**: No in_progress bead. Before editing project files:\n"
            '1. `bd create --title="..." --type=task|bug|feature`\n'
            "2. `bd update <id> --status=in_progress`\n"
            "Or say SUDO to bypass."
        )

    return HookResult.approve()


@register_hook("parallel_bead_delegation", "Task", priority=3)
def check_parallel_bead_delegation(data: dict, state: SessionState) -> HookResult:
    """
    Force parallel Task delegation when multiple beads are open.

    PATTERN: If 2+ beads open, nudge to spawn parallel agents for each.
    BLOCKING: After 3+ sequential single-agent patterns with multiple beads available.
    """
    tool_input = data.get("tool_input", {})

    # Skip if already running in background or resuming
    if tool_input.get("run_in_background") or tool_input.get("resume"):
        return HookResult.approve()

    # Get open beads
    open_beads = _get_open_beads(state)
    open_count = len(open_beads)

    if open_count < 2:
        return HookResult.approve()

    # Multiple beads open - check if we're being sequential
    current_turn = state.turn_count

    # Track this spawn
    if state.last_task_turn != current_turn:
        state.task_spawns_this_turn = 0
        state.last_task_turn = current_turn
    state.task_spawns_this_turn += 1

    # First Task this turn with multiple beads - strong nudge
    if state.task_spawns_this_turn == 1:
        bead_list = ", ".join(
            f"`{b.get('id', '?')[:12]}` ({b.get('title', '?')[:30]})"
            for b in open_beads[:4]
        )
        return HookResult.approve(
            f"⚡ **PARALLEL BEADS**: {open_count} beads open: {bead_list}\n"
            f"Spawn {open_count} Task agents in ONE message to work them in parallel.\n"
            "Each agent can `bd update <id> --status=in_progress` and work independently."
        )

    # Already spawning multiple - good
    return HookResult.approve()


@register_hook("recursion_guard", "Edit|Write|Bash", priority=5)
def check_recursion_guard(data: dict, state: SessionState) -> HookResult:
    """Block catastrophic folder duplication."""

    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})

    RECURSIVE_PATTERNS = [
        r"\.claude/.*\.claude/",
        r"projects/[^/]+/projects/",
        r"\.claude/tmp/.*\.claude/tmp/",
    ]

    paths_to_check = []

    if tool_name in ("Write", "Edit"):
        file_path = tool_input.get("file_path", "")
        if file_path:
            paths_to_check.append(file_path)
    elif tool_name == "Bash":
        command = tool_input.get("command", "")
        # Strip heredoc content to avoid matching paths in heredoc body
        cmd_to_check = strip_heredoc_content(command)
        # Extract paths from mkdir, touch, cp, mv
        paths_to_check.extend(
            re.findall(r'mkdir\s+(?:-p\s+)?["\']?([^"\';\s&|]+)', cmd_to_check)
        )
        paths_to_check.extend(
            re.findall(r'["\']?(/[^"\';\s&|]+|\.claude/[^"\';\s&|]+)', cmd_to_check)
        )

    for path in paths_to_check:
        for pattern in RECURSIVE_PATTERNS:
            if re.search(pattern, path):
                return HookResult.deny(
                    f"🔁 **RECURSION CATASTROPHE BLOCKED**\n"
                    f"Path: {path}\n"
                    f"Use flat paths instead of nested duplicates."
                )


@register_hook("oracle_gate", "Edit|Write|Bash", priority=30)
def check_oracle_gate(data: dict, state: SessionState) -> HookResult:
    """Enforce oracle consultation after repeated failures."""
    from session_state import get_turns_since_op
    from synapse_core import check_sudo_in_transcript

    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})
    transcript_path = data.get("transcript_path", "")

    # SUDO bypass
    if check_sudo_in_transcript(transcript_path):
        return HookResult.approve()

    # Skip diagnostic bash commands
    if tool_name == "Bash":
        command = tool_input.get("command", "")
        diagnostic = ["ls", "cat", "grep", "find", "echo", "pwd", "which"]
        if any(command.strip().startswith(p) for p in diagnostic):
            return HookResult.approve()
        if any(r in command for r in ["oracle", "think", "council"]):
            return HookResult.approve()

    failures = state.consecutive_failures

    # Check if oracle/think was run recently
    min_turns = min(
        get_turns_since_op(state, "oracle"),
        get_turns_since_op(state, "think"),
        get_turns_since_op(state, "council"),
    )
    if min_turns <= 5:
        return HookResult.approve()

    if failures == 2:
        return HookResult.approve(
            "⚠️ **ORACLE NUDGE** (2 consecutive failures)\n"
            'Consider: `think "Why is this failing?"` before attempt #3.'
        )

    if failures >= 3:
        return HookResult.deny(
            f"**ORACLE GATE BLOCKED** (Three-Strike Rule)\n"
            f"**{failures} failures** without oracle/think consultation.\n"
            f'Run `think "Debug: <problem>"` or user says "SUDO CONTINUE".'
        )


@register_hook("integration_gate", "Edit|Write|Task", priority=35)
def check_integration_gate(data: dict, state: SessionState) -> HookResult:
    """Enforce grep after function edits."""
    from session_state import check_integration_blindness

    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})

    # Auto-expire old pending greps (> 5 turns old)
    current_turn = state.turn_count
    state.pending_integration_greps = [
        g
        for g in state.pending_integration_greps
        if current_turn - g.get("turn", 0) <= 5
    ]

    should_block, message = check_integration_blindness(state, tool_name, tool_input)
    if should_block:
        return HookResult.deny(message)


@register_hook("error_suppression_gate", "Edit|Write|MultiEdit|Task", priority=40)
def check_error_suppression(data: dict, state: SessionState) -> HookResult:
    """Block non-diagnostic tools until errors are resolved."""
    import time as time_mod

    tool_name = data.get("tool_name", "")

    # Always allow diagnostic tools
    DIAGNOSTIC_TOOLS = {
        "Read",
        "Grep",
        "Glob",
        "Bash",
        "BashOutput",
        "WebFetch",
        "WebSearch",
        "TodoWrite",
    }
    if tool_name in DIAGNOSTIC_TOOLS:
        return HookResult.approve()

    # Check for recent unresolved errors (within 5 min)
    ERROR_TTL = 300
    cutoff = time_mod.time() - ERROR_TTL
    recent_errors = [
        e for e in state.errors_unresolved if e.get("timestamp", 0) > cutoff
    ]

    if not recent_errors:
        return HookResult.approve()

    latest = recent_errors[-1]
    error_type = latest.get("type", "Unknown")[:60]

    return HookResult.deny(
        f"**ERROR SUPPRESSION BLOCKED**\n"
        f"Unresolved: {error_type}\n"
        f"Fix the error before continuing. Use Bash/Read/Grep to debug."
    )


@register_hook("content_gate", "Edit|Write", priority=45)
def check_content_gate(data: dict, state: SessionState) -> HookResult:
    """Block dangerous code patterns (eval, SQL injection, etc.)."""
    from synapse_core import check_sudo_in_transcript

    tool_input = data.get("tool_input", {})
    transcript_path = data.get("transcript_path", "")

    content = tool_input.get("content", "") or tool_input.get("new_string", "")
    file_path = tool_input.get("file_path", "")

    if not content or not file_path:
        return HookResult.approve()

    # Framework escape hatch
    if ".claude/lib/" in file_path or ".claude/hooks/" in file_path:
        return HookResult.approve()

    # Tmp files are allowed
    if ".claude/tmp/" in file_path:
        return HookResult.approve()

    has_sudo = check_sudo_in_transcript(transcript_path)

    # For Python files: Use AST analysis (more accurate, ignores strings/comments)
    if file_path.endswith(".py"):
        try:
            from ast_analysis import has_critical_violations

            is_critical, violations = has_critical_violations(content)
            if is_critical:
                # Format violations for error message
                msgs = [f"- {v.message} (line {v.line})" for v in violations[:3]]
                return HookResult.deny(
                    "**CONTENT BLOCKED** (AST analysis):\n"
                    + "\n".join(msgs)
                    + "\nFix the vulnerabilities."
                )
        except Exception:
            pass  # Fall through to regex if AST fails

    # Fallback: Regex patterns for non-Python or if AST failed
    CRITICAL_PATTERNS = [
        (r"\b(eval|exec)\s*\(", "Code injection (eval/exec)"),
        (r'f["\']SELECT\s+', "SQL injection risk"),
    ]

    for pattern, message in CRITICAL_PATTERNS:
        if re.search(pattern, content, re.IGNORECASE):
            return HookResult.deny(
                f"**CONTENT BLOCKED**: {message}\nFix the vulnerability."
            )

    # Block patterns (SUDO bypass allowed)
    if not has_sudo:
        BLOCK_PATTERNS = [
            (r"subprocess\.[^(]+\([^)]*shell\s*=\s*True", "shell=True risk"),
            (r"except\s*:\s*$", "Bare except"),
            (r"from\s+\w+\s+import\s+\*", "Wildcard import"),
        ]

        for pattern, message in BLOCK_PATTERNS:
            if re.search(pattern, content, re.MULTILINE):
                if "__init__.py" not in file_path:
                    return HookResult.deny(
                        f"**CONTENT BLOCKED**: {message}\nSay SUDO to bypass."
                    )


# =============================================================================
# GOD COMPONENT GATE (Priority 48) - Prevent monolithic files
# =============================================================================


@register_hook("god_component_gate", "Edit|Write", priority=48)
def check_god_component_gate(data: dict, state: SessionState) -> HookResult:
    """
    Block edits that would create God components.

    Uses three layers:
    1. Allowlist - Known-large file patterns, explicit markers
    2. Complexity - AST-based function/import counting
    3. Churn - Edit frequency tracking (escalates warning to block)
    """
    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})
    file_path = tool_input.get("file_path", "")

    if not file_path:
        return HookResult.approve()

    # Skip scratch files and framework infrastructure
    if ".claude/tmp/" in file_path or "/.claude/" in file_path:
        return HookResult.approve()

    # SUDO bypass
    from synapse_core import check_sudo_in_transcript

    transcript_path = data.get("transcript_path", "")
    if check_sudo_in_transcript(transcript_path):
        return HookResult.approve()

    # Get the content that WILL exist after the edit
    try:
        from pathlib import Path

        path = Path(file_path)

        if tool_name == "Write":
            # Write replaces entire file
            content = tool_input.get("content", "")
        elif tool_name == "Edit":
            # Edit modifies existing content
            if not path.exists():
                return HookResult.approve()
            existing = path.read_text()
            old_string = tool_input.get("old_string", "")
            new_string = tool_input.get("new_string", "")
            if old_string not in existing:
                return HookResult.approve()  # Let gap_detector handle this
            content = existing.replace(old_string, new_string, 1)
        else:
            return HookResult.approve()

        if not content:
            return HookResult.approve()

    except Exception:
        return HookResult.approve()

    # Track edit count for churn detection
    edit_count = (
        state.get_file_edit_count(file_path)
        if hasattr(state, "get_file_edit_count")
        else 0
    )

    # Run detection
    try:
        from analysis.god_component_detector import (
            detect_god_component,
            format_detection_message,
        )

        result = detect_god_component(file_path, content, edit_count)

        if result.severity == "block":
            message = format_detection_message(result)
            return HookResult.deny(
                f"{message}\n\n"
                f"**Bypass options:**\n"
                f"1. Add `# LARGE_FILE_OK: <reason>` as first line of file (permanent bypass)\n"
                f"2. Say SUDO to bypass once\n"
                f"3. Files in `.claude/tmp/` are never blocked"
            )
        elif result.severity == "warn":
            message = format_detection_message(result)
            return HookResult.approve_with_context(message)

    except Exception:
        pass


@register_hook("gap_detector", "Edit|Write", priority=50)
def check_gap_detector(data: dict, state: SessionState) -> HookResult:
    """Block editing file without reading it first + verify old_string is current."""
    from session_state import was_file_read
    from pathlib import Path

    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})

    if tool_name != "Edit":
        return HookResult.approve()

    file_path = tool_input.get("file_path", "")
    if not file_path:
        return HookResult.approve()

    # Exceptions - scratch files skip all checks
    is_scratch = ".claude/tmp/" in file_path
    if is_scratch:
        return HookResult.approve()

    file_exists = Path(file_path).exists() if file_path else False
    if not file_exists:
        return HookResult.approve()

    old_string = tool_input.get("old_string", "")

    # ALWAYS verify old_string matches current file (prevents silent corruption)
    # This is the critical safety check - even if file was "read", context may be stale
    if old_string and len(old_string) > 10:
        try:
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                current_content = f.read()
            if old_string not in current_content:
                filename = Path(file_path).name
                # Show a snippet of what we're looking for
                snippet = old_string[:60].replace("\n", "\\n")
                return HookResult.deny(
                    f"**STALE EDIT BLOCKED**: `old_string` not found in current `{filename}`.\n"
                    f"Looking for: `{snippet}...`\n"
                    f"Re-read the file - content may have changed."
                )
            # old_string verified - approve (implicit proof of context)
            return HookResult.approve()
        except (OSError, IOError, UnicodeDecodeError):
            pass  # Fall through to standard checks

    # Check if file was read OR already edited
    file_seen = was_file_read(state, file_path) or file_path in state.files_edited
    if file_seen:
        return HookResult.approve()

    filename = Path(file_path).name
    return HookResult.deny(
        f"**GAP DETECTED**: Editing `{filename}` without reading first.\n"
        f"Use Read tool first to understand the file structure."
    )


@register_hook("production_gate", "Write", priority=55)
def check_production_gate(data: dict, state: SessionState) -> HookResult:
    """Enforce audit+void before writing to .claude/ops/ or .claude/lib/."""
    from pathlib import Path

    tool_input = data.get("tool_input", {})
    file_path = tool_input.get("file_path", "")

    if not file_path:
        return HookResult.approve()

    # Only check protected paths
    PROTECTED = [".claude/ops/", ".claude/lib/"]
    is_protected = any(p in file_path for p in PROTECTED)
    if not is_protected:
        return HookResult.approve()

    # New files get a warning, not a block
    if not Path(file_path).exists():
        return HookResult.approve(
            "⚠️ New production file - run audit+void after creation"
        )

    # Check content for stubs
    content = tool_input.get("content", "")
    if content:
        STUB_PATTERNS = ["# TODO", "# FIXME", "raise NotImplementedError", "pass  #"]
        for pattern in STUB_PATTERNS:
            if pattern in content:
                return HookResult.deny(
                    f"**PRODUCTION GATE BLOCKED**: Stub detected ({pattern})\n"
                    f"Complete all TODOs before writing to production."
                )

    return HookResult.approve("✓ Production gate passed")


@register_hook("deferral_gate", "Edit|Write|MultiEdit", priority=60)
def check_deferral_gate(data: dict, state: SessionState) -> HookResult:
    """Block deferral theater language."""
    from synapse_core import check_sudo_in_transcript

    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})
    transcript_path = data.get("transcript_path", "")

    # Get content
    content = ""
    if tool_name == "Write":
        content = tool_input.get("content", "")
    elif tool_name == "Edit":
        content = tool_input.get("new_string", "")

    if not content:
        return HookResult.approve()

    # Bypass
    if "SUDO DEFER" in content.upper() or check_sudo_in_transcript(transcript_path):
        return HookResult.approve()

    DEFERRAL_PATTERNS = [
        (r"#\s*(TODO|FIXME):\s*(implement\s+)?later", "TODO later"),
        (r"#\s*low\s+priority", "low priority"),
        (r"#\s*nice\s+to\s+have", "nice to have"),
        (r"#\s*could\s+(do|add)\s+later", "could do later"),
        (r"#\s*worth\s+investigating", "worth investigating"),
        (r"#\s*consider\s+adding", "consider adding"),
    ]

    for pattern, name in DEFERRAL_PATTERNS:
        if re.search(pattern, content, re.IGNORECASE):
            return HookResult.deny(
                f"**DEFERRAL THEATER BLOCKED** (Principle #19)\n"
                f"Detected: {name}\n"
                f"Either do it NOW or delete the thought. Add 'SUDO DEFER' to bypass."
            )


@register_hook("doc_theater_gate", "Write", priority=65)
def check_doc_theater_gate(data: dict, state: SessionState) -> HookResult:
    """Block creation of standalone documentation files."""
    from synapse_core import check_sudo_in_transcript
    from pathlib import Path

    tool_input = data.get("tool_input", {})
    transcript_path = data.get("transcript_path", "")
    file_path = tool_input.get("file_path", "")

    if not file_path or not file_path.endswith(".md"):
        return HookResult.approve()

    if check_sudo_in_transcript(transcript_path):
        return HookResult.approve()

    # Allowed locations
    ALLOWED = [
        r"/CLAUDE\.md$",
        r"\.claude/agents/.*\.md$",  # Custom agent definitions
        r"\.claude/commands/.*\.md$",
        r"\.claude/memory/.*\.md$",
        r"\.claude/reminders/.*\.md$",
        r"\.claude/plans/.*\.md$",
        r"\.claude/rules/.*\.md$",  # Claude Code rules directory
        r"\.claude/skills/.*\.md$",  # Claude Code skills directory
        r"projects/.*/.*\.md$",
    ]
    for pattern in ALLOWED:
        if re.search(pattern, file_path):
            return HookResult.approve()

    # Doc theater patterns
    DOC_PATTERNS = ["README.md", "GUIDE.md", "SCHEMA", "DOCS.md", "ARCHITECTURE.md"]
    filename = Path(file_path).name.upper()
    for pattern in DOC_PATTERNS:
        if pattern.upper() in filename:
            return HookResult.deny(
                f"**DOC THEATER BLOCKED**\n"
                f"File: {Path(file_path).name}\n"
                f"Put docs INLINE (docstrings, comments). Say SUDO to bypass."
            )

    # Generic .md outside allowed locations
    return HookResult.deny(
        "**DOC THEATER BLOCKED**: Standalone .md outside allowed locations.\n"
        "Use .claude/memory/*.md or inline docs. Say SUDO to bypass."
    )


@register_hook("root_pollution_gate", "Edit|Write", priority=70)
def check_root_pollution_gate(data: dict, state: SessionState) -> HookResult:
    """Block files that would clutter home directory."""
    from pathlib import Path

    tool_input = data.get("tool_input", {})
    file_path = tool_input.get("file_path", "")

    if not file_path:
        return HookResult.approve()

    HOME = Path.home()
    try:
        abs_path = Path(file_path).resolve()
        if not abs_path.is_relative_to(HOME):
            return HookResult.approve()
        rel_path = abs_path.relative_to(HOME)
    except (ValueError, OSError):
        return HookResult.approve()

    parts = rel_path.parts
    if not parts:
        return HookResult.approve()

    # Allowed directories
    ALLOWED_DIRS = {"projects", ".claude", ".vscode", ".beads", ".git", "ai"}
    first = parts[0]

    if first in ALLOWED_DIRS or first.startswith("."):
        return HookResult.approve()

    # Single file at home root
    if len(parts) == 1:
        ALLOWED_FILES = {"CLAUDE.md", ".gitignore", ".claudeignore"}
        if first in ALLOWED_FILES or first.startswith("."):
            return HookResult.approve()
        return HookResult.deny(
            f"**HOME CLEANLINESS**: '{first}' would clutter home.\n"
            f"Use ~/projects/<name>/, ~/ai/<name>/, or ~/.claude/tmp/"
        )


@register_hook("recommendation_gate", "Write", priority=75)
def check_recommendation_gate(data: dict, state: SessionState) -> HookResult:
    """Block duplicate functionality creation."""
    from pathlib import Path

    tool_input = data.get("tool_input", {})
    file_path = tool_input.get("file_path", "")

    if not file_path:
        return HookResult.approve()

    # Infrastructure patterns
    INFRA_PATTERNS = [
        r"setup[_-]?\w*\.sh$",
        r"bootstrap[_-]?\w*\.sh$",
        r"\.claude/hooks/\w+_gate\.py$",
        r"\.claude/ops/\w+\.py$",
    ]

    is_infra = any(re.search(p, file_path, re.IGNORECASE) for p in INFRA_PATTERNS)
    if not is_infra:
        return HookResult.approve()

    # Check if file already exists (editing vs creating)
    if Path(file_path).exists():
        return HookResult.approve()

    # For new infra files, just warn
    return HookResult.approve(
        f"⚠️ Creating new infrastructure: {Path(file_path).name}\n"
        f"Read `.claude/memory/__capabilities.md` first to avoid duplication."
    )


@register_hook("security_claim_gate", "Edit|Write", priority=80)
def check_security_claim_gate(data: dict, state: SessionState) -> HookResult:
    """Require audit for security-sensitive code."""
    from synapse_core import check_sudo_in_transcript
    from pathlib import Path

    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})
    transcript_path = data.get("transcript_path", "")
    file_path = tool_input.get("file_path", "")

    content = ""
    if tool_name == "Write":
        content = tool_input.get("content", "")
    elif tool_name == "Edit":
        content = tool_input.get("new_string", "")

    # Bypass
    if "SUDO SECURITY" in content.upper() or check_sudo_in_transcript(transcript_path):
        return HookResult.approve()

    # Skip trusted paths
    EXCLUDED = [".claude/hooks/", ".claude/tmp/", ".claude/ops/"]
    if any(ex in file_path for ex in EXCLUDED):
        return HookResult.approve()

    # Security patterns in filename
    SECURITY_PATTERNS = [
        "auth",
        "login",
        "password",
        "credential",
        "token",
        "secret",
        "jwt",
        "oauth",
    ]
    path_lower = file_path.lower()
    is_security_file = any(p in path_lower for p in SECURITY_PATTERNS)

    # Security patterns in content
    CONTENT_PATTERNS = [r"password\s*=", r"secret\s*=", r"\.encrypt\(", r"\.decrypt\("]
    has_security_content = any(
        re.search(p, content, re.IGNORECASE) for p in CONTENT_PATTERNS
    )

    if is_security_file or has_security_content:
        audited = getattr(state, "audited_files", [])
        if file_path not in audited:
            return HookResult.approve(
                f"⚠️ SECURITY-SENSITIVE: Consider `audit {Path(file_path).name}` before editing."
            )


@register_hook("epistemic_boundary", "Edit|Write", priority=85)
def check_epistemic_boundary(data: dict, state: SessionState) -> HookResult:
    """Catch claims not backed by session evidence (AST-based)."""

    tool_input = data.get("tool_input", {})
    file_path = tool_input.get("file_path", "")

    if ".claude/tmp/" in file_path or ".claude/memory" in file_path:
        return HookResult.approve()

    # Only use AST for Python files
    if not file_path.endswith(".py"):
        return HookResult.approve()

    code = tool_input.get("new_string", "") or tool_input.get("content", "")
    if not code or len(code) < 50:
        return HookResult.approve()

    files_read = state.files_read or []

    # AST-based call extraction (ignores strings/comments, more accurate)
    from _ast_utils import extract_non_builtin_calls

    calls = extract_non_builtin_calls(code)

    if not calls:
        return HookResult.approve()

    # Check if likely sources were read
    unverified = []
    for call in list(calls)[:5]:
        found = any(call.lower() in f.lower() for f in files_read if f)
        if not found and not any(call.lower() in file_path.lower() for _ in [1]):
            unverified.append(call)

    if unverified and len(unverified) >= 2:
        return HookResult.approve(
            f"🔬 EPISTEMIC: Using {', '.join(unverified[:3])} - source files not read this session."
        )


@register_hook("research_gate", "Edit|Write", priority=88)
def check_research_gate(data: dict, state: SessionState) -> HookResult:
    """Block writes using unverified external libraries."""
    from session_state import RESEARCH_REQUIRED_LIBS, extract_libraries_from_code

    tool_input = data.get("tool_input", {})
    file_path = tool_input.get("file_path", "")

    # Skip non-Python or scratch
    if not file_path.endswith(".py") or ".claude/tmp/" in file_path:
        return HookResult.approve()

    code = tool_input.get("new_string", "") or tool_input.get("content", "")
    if not code or len(code) < 30:
        return HookResult.approve()

    libs = extract_libraries_from_code(code)
    researched = state.libraries_researched or []

    STABLE = {
        "os",
        "sys",
        "json",
        "re",
        "pathlib",
        "typing",
        "requests",
        "pytest",
        "pydantic",
    }

    unresearched = []
    for lib in libs:
        lib_lower = lib.lower()
        if lib_lower in STABLE:
            continue
        if lib_lower in [r.lower() for r in researched]:
            continue
        if any(req.lower() in lib_lower for req in RESEARCH_REQUIRED_LIBS):
            unresearched.append(lib)

    if unresearched:
        return HookResult.deny(
            f"**RESEARCH GATE BLOCKED**\n"
            f"Unverified: {', '.join(unresearched[:3])}\n"
            f'Run `research "{unresearched[0]} API"` or say VERIFIED.'
        )


@register_hook("import_gate", "Write", priority=92)
def check_import_gate(data: dict, state: SessionState) -> HookResult:
    """Warn about potentially missing imports (AST-based)."""
    tool_input = data.get("tool_input", {})
    file_path = tool_input.get("file_path", "")
    content = tool_input.get("content", "")

    if not file_path.endswith(".py") or not content:
        return HookResult.approve()

    # AST-based import extraction (handles all import forms, ignores strings/comments)
    from _ast_utils import extract_non_stdlib_imports

    third_party = extract_non_stdlib_imports(content)
    if third_party:
        return HookResult.approve(
            f"📦 Third-party imports: {', '.join(sorted(third_party)[:5])} - ensure installed."
        )


@register_hook("modularization_nudge", "Edit|Write", priority=95)
def check_modularization(data: dict, state: SessionState) -> HookResult:
    """Remind to modularize before creating code."""

    tool_input = data.get("tool_input", {})
    file_path = tool_input.get("file_path", "")

    if not file_path:
        return HookResult.approve()

    # Skip non-code files
    SKIP_EXT = {".md", ".txt", ".json", ".yaml", ".yml", ".sh", ".env"}
    ext = os.path.splitext(file_path)[1].lower()
    if ext in SKIP_EXT:
        return HookResult.approve()

    # Skip scratch
    if ".claude/tmp/" in file_path:
        return HookResult.approve()

    # Only show occasionally (every 10 edits)
    if state.turn_count % 10 != 0:
        return HookResult.approve()

    return HookResult.approve(
        "📦 MODULARIZATION: Search first, separate concerns, use descriptive filenames."
    )


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

    # Collect results
    contexts = []

    for name, matcher, check_func, priority in sorted_hooks:
        if not matches_tool(matcher, tool_name):
            continue

        try:
            result = check_func(data, state)

            # First deny wins - but check for cascade failure first
            if result.decision == "deny":
                # Track this block for cascade detection
                track_block(state, name)

                # Check if we're in a cascade failure state
                is_cascade, escalation_msg = check_cascade_failure(state, name)
                if is_cascade:
                    # Allow with escalation instead of hard block
                    contexts.append(
                        f"⚠️ **CASCADE DETECTED** ({name} blocked 3+ times):\n"
                        f"{result.reason}\n\n{escalation_msg}"
                    )
                    # Don't return deny - let the operation through with warning
                    continue

                return {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "deny",
                        "permissionDecisionReason": result.reason,
                    }
                }

            # Clear cascade tracking on successful hook pass
            clear_blocks(state, name)

            # Collect contexts
            if result.context:
                contexts.append(result.context)

        except Exception as e:
            # Log error but don't block
            print(f"[runner] Hook {name} error: {e}", file=sys.stderr)

    # Build output
    output = {"hookSpecificOutput": {"hookEventName": "PreToolUse"}}
    if contexts:
        output["hookSpecificOutput"]["additionalContext"] = "\n\n".join(contexts[:3])

    return output


def main():
    """Main entry point."""
    start = time.time()

    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse"}}))
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
    if elapsed > 50:
        print(f"[runner] Slow: {elapsed:.1f}ms", file=sys.stderr)

    sys.exit(0)


if __name__ == "__main__":
    main()
