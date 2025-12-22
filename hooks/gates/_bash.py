#!/usr/bin/env python3
"""
Bash Command Gates - Shell command safety and optimization hooks.

These gates enforce best practices for bash commands:
- Loop detection: Block inefficient shell loops, suggest alternatives
- Script nudging: Suggest tmp scripts for complex commands
- Background enforcement: Require background for slow commands
- Server pattern detection: Block inline server backgrounding
- Tool preferences: Nudge toward better tools

Extracted from pre_tool_use_runner.py for modularity.
"""

import os
import re
from pathlib import Path

from session_state import SessionState
from ._common import register_hook, HookResult


# =============================================================================
# PRE-COMPILED PATTERNS (Performance: compile once at module load)
# =============================================================================

# Bash loop detection patterns - BLOCK inefficient shell loops
# Philosophy: Block patterns that spawn shell per iteration.
_BASH_LOOP_PATTERNS = [
    # Inefficient: piping to while loop (loses exit codes, spawns subshell)
    re.compile(r"\|\s*while\b", re.IGNORECASE),
    # Inefficient: xargs spawning shell per item
    re.compile(r"\bxargs\s+.*\b(sh|bash)\s+-c\b", re.IGNORECASE),
    # Inefficient: for loop over command substitution (spawns subshell per iteration)
    re.compile(r"\bfor\s+\w+\s+in\s+\$\([^)]*\bfind\b", re.IGNORECASE),
    re.compile(r"\bfor\s+\w+\s+in\s+\$\([^)]*\bls\b", re.IGNORECASE),
    # Inefficient: process substitution to while
    re.compile(r"\bwhile\s+.*<\s*<\(", re.IGNORECASE),
]

# Efficient patterns - NEVER block (they're the solution, not the problem)
_BASH_EFFICIENT_PATTERNS = [
    re.compile(r"\bfind\s+.*-exec\b", re.IGNORECASE),  # find -exec: runs in C
    re.compile(r"\bfind\s+.*-execdir\b", re.IGNORECASE),  # safer variant
    re.compile(r"\bxargs\s+(?!.*\b(sh|bash)\s+-c)", re.IGNORECASE),  # no shell
    re.compile(r"\bparallel\b", re.IGNORECASE),  # GNU parallel
]

# Allowed loop patterns (legitimate shell loops)
_BASH_ALLOWED_PATTERNS = [
    # Small fixed iteration (for i in 1 2 3)
    re.compile(
        r"for\s+\w+\s+in\s+[\w.-]+\s+[\w.-]+(\s+[\w.-]+){0,5}\s*;", re.IGNORECASE
    ),
    # Brace expansion (for i in {1..5})
    re.compile(r"for\s+\w+\s+in\s+\{\d+\.\.\d+\}", re.IGNORECASE),
    # Glob expansion (for f in *.txt)
    re.compile(r"for\s+\w+\s+in\s+[~./\w-]*\*", re.IGNORECASE),
    # Here-string (while read <<< "string")
    re.compile(r"while\s+read.*<<<", re.IGNORECASE),
    # Python one-liner
    re.compile(r'python[3]?\s+.*-c\s+["\']', re.IGNORECASE),
    # time wrapper
    re.compile(r"\btime\s+\(", re.IGNORECASE),
    # while true/while :  (daemon loops - intentional)
    re.compile(r"\bwhile\s+(true|:)\s*;", re.IGNORECASE),
    # until with simple condition
    re.compile(r"\buntil\s+\[", re.IGNORECASE),
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

# Git commit message detection - matches -m "..." or -m '...' with multi-line content
_GIT_COMMIT_MSG_PATTERN = re.compile(r'git\s+commit\s+[^-]*-m\s*["\']', re.IGNORECASE)


def strip_heredoc_content(command: str) -> str:
    """Extract only the shell command portion, excluding heredoc/message content.

    Strips:
    - Heredoc content: 'cat > file << EOF\\ncontent\\nEOF' -> 'cat > file << EOF'
    - Git commit messages: 'git commit -m "content"' -> 'git commit -m "'

    This prevents false positives when content mentions patterns like 'npm run dev'.
    """
    result = command

    # Strip heredoc content
    match = _HEREDOC_PATTERN.search(result)
    if match:
        result = result[: match.end()]

    # Strip git commit message content (keep just 'git commit -m "')
    match = _GIT_COMMIT_MSG_PATTERN.search(result)
    if match:
        result = result[: match.end()]

    return result


# =============================================================================
# LOOP DETECTOR (Priority 10) - Block inefficient bash loops
# =============================================================================


@register_hook("loop_detector", "Bash", priority=10)
def check_loop_detector(data: dict, state: SessionState) -> HookResult:
    """Block inefficient bash loops, allow efficient alternatives like find -exec."""
    tool_input = data.get("tool_input", {})
    command = tool_input.get("command", "")
    description = tool_input.get("description", "")

    if not command:
        return HookResult.approve()

    # Subagent bypass: Fresh agents shouldn't be blocked (v4.32)
    if state.turn_count <= 3:
        return HookResult.approve()

    # SUDO bypass (pre-computed in run_hooks)
    if "SUDO LOOP" in description.upper() or "SUDO_LOOP" in description.upper():
        return HookResult.approve()
    if data.get("_sudo_bypass"):
        return HookResult.approve()

    # Strip heredocs first, then quotes
    check_cmd = strip_heredoc_content(command)
    check_cmd = re.sub(r"'[^']*'", "'Q'", check_cmd)
    check_cmd = re.sub(r'"[^"]*"', '"Q"', check_cmd)

    # FIRST: Allow efficient patterns unconditionally (find -exec, xargs, parallel)
    # These are the SOLUTION, not the problem - never block them
    for pattern in _BASH_EFFICIENT_PATTERNS:
        if pattern.search(check_cmd):
            return HookResult.approve()

    # SECOND: Allow legitimate shell loop patterns
    for pattern in _BASH_ALLOWED_PATTERNS:
        if pattern.search(check_cmd):
            return HookResult.approve()

    # THIRD: Block only inefficient patterns (piping to while, for over $(find), etc.)
    for pattern in _BASH_LOOP_PATTERNS:
        match = pattern.search(check_cmd)
        if match:
            return HookResult.deny(
                f"⛔ INEFFICIENT LOOP: `{match.group(0)}` "
                "→ Use find -exec/xargs/parallel. SUDO LOOP to bypass."
            )
    return HookResult.approve()


# =============================================================================
# PYTHON PATH ENFORCER (Priority 12) - Suggest venv python
# =============================================================================


@register_hook("python_path_enforcer", "Bash", priority=12)
def check_python_path_enforcer(data: dict, state: SessionState) -> HookResult:
    """Suggest venv python usage instead of system python (soft nudge, not blocking)."""
    tool_input = data.get("tool_input", {})
    command = tool_input.get("command", "")

    project_dir = os.environ.get("CLAUDE_PROJECT_DIR", str(Path.home()))
    venv_python = f"{project_dir}/.claude/.venv/bin/python"

    # Only suggest if venv exists
    if not os.path.exists(venv_python):
        return HookResult.approve()

    # Pattern: bare python/pip at start or after shell operators (exclude heredoc content)
    cmd_to_check = strip_heredoc_content(command)
    bare_python = re.search(r"(^|&&|\|\||;|\|)\s*(python3?|pip3?)\s", cmd_to_check)

    if bare_python and ".venv/bin" not in cmd_to_check:
        venv_bin = f"{project_dir}/.claude/.venv/bin"
        # Soft nudge instead of block - suggest but allow
        return HookResult.approve(
            f"💡 Tip: Use `{venv_bin}/python` for consistent deps"
        )
    return HookResult.approve()


# =============================================================================
# SCRIPT NUDGE (Priority 14) - Suggest scripts for complex commands
# =============================================================================


@register_hook("script_nudge", "Bash", priority=14)
def check_script_nudge(data: dict, state: SessionState) -> HookResult:
    """Suggest writing scripts for complex manual work.

    Detects:
    - 3+ pipes/operators (complex chains)
    - Loop patterns (for/while/xargs)
    - Complex data transforms (awk/sed/jq with long expressions)

    Benefits of tmp scripts:
    - Debuggable (add print statements, step through)
    - Reusable (run again with tweaks)
    - Background-capable (run_in_background=true)
    - Testable (can add assertions)
    """
    tool_input = data.get("tool_input", {})
    command = tool_input.get("command", "")

    # Already using a script? Good behavior - no nudge needed
    if ".claude/tmp/" in command or ".claude/ops/" in command:
        return HookResult.approve()

    # Strip heredoc content to avoid false positives
    cmd_to_check = strip_heredoc_content(command)

    # Exempt git commit (heredoc messages look complex but aren't)
    if "git commit" in cmd_to_check:
        return HookResult.approve()

    # Count structural complexity
    pipe_count = cmd_to_check.count("|")
    semicolon_count = cmd_to_check.count(";")
    and_count = cmd_to_check.count("&&")
    total_complexity = pipe_count + semicolon_count + and_count

    if total_complexity >= 3:
        return HookResult.approve(
            f"💡 SCRIPT OPPORTUNITY: {total_complexity} operators detected\n"
            "   Benefits: debuggable, reusable, can run in background\n"
            "   → Write to: ~/.claude/tmp/<task>.py\n"
            "   → Run with: run_in_background=true for long tasks"
        )

    # Check for loop patterns (use pre-compiled patterns)
    for pattern in _SCRIPT_NUDGE_PATTERNS:
        if pattern.search(cmd_to_check):
            return HookResult.approve(
                "💡 SCRIPT OPPORTUNITY: loop/iteration detected\n"
                "   Benefits: debuggable, reusable, can run in background\n"
                "   → Write to: ~/.claude/tmp/<task>.py"
            )

    # Check for complex data transforms
    data_transform_patterns = [
        (r"awk\s+'[^']{25,}'", "awk"),
        (r'awk\s+"[^"]{25,}"', "awk"),
        (r"sed\s+(-e\s+){2,}", "sed"),
        (r"jq\s+'[^']{35,}'", "jq"),
    ]
    for pattern, tool in data_transform_patterns:
        if re.search(pattern, cmd_to_check):
            return HookResult.approve(
                f"💡 SCRIPT OPPORTUNITY: complex {tool} expression\n"
                "   Python is more readable for data transforms:\n"
                "   → json.load() for JSON, csv module for CSV\n"
                "   → Write to: ~/.claude/tmp/<task>.py"
            )

    return HookResult.approve()


# =============================================================================
# INLINE SERVER BACKGROUND (Priority 14) - Block server & curl patterns
# =============================================================================


@register_hook("inline_server_background", "Bash", priority=14)
def check_inline_server_background(data: dict, state: SessionState) -> HookResult:
    """Block inline server backgrounding pattern - use run_in_background instead.

    Anti-pattern: `uvicorn app:app & sleep 2 && curl localhost:8000`
    This creates race conditions, hangs, and unpredictable behavior.

    Correct pattern: Use run_in_background=true for the server,
    then separate Bash calls to interact with it.
    """
    tool_input = data.get("tool_input", {})
    command = tool_input.get("command", "")

    if not command or "&" not in command:
        return HookResult.approve()

    # SUDO bypass
    if data.get("_sudo_bypass"):
        return HookResult.approve()

    # Strip heredoc content to avoid false positives
    cmd_to_check = strip_heredoc_content(command)

    # Server-like commands that should use run_in_background
    SERVER_PATTERNS = [
        r"\buvicorn\b",
        r"\bgunicorn\b",
        r"\bflask\s+run\b",
        r"\bnpm\s+(run\s+)?(dev|start|serve)\b",
        r"\byarn\s+(dev|start|serve)\b",
        r"\bpnpm\s+(dev|start|serve)\b",
        r"\bpython\s+-m\s+http\.server\b",
        r"\bpython\s+.*\bapp\.py\b",
        r"\bnode\s+.*server",
        r"\bng\s+serve\b",
        r"\bvite\b",
        r"\bnext\s+dev\b",
        r"\brails\s+server\b",
        r"\bcargo\s+run\b.*--.*server",
        r"\bgo\s+run\b.*server",
    ]

    # Commands that indicate interaction with the backgrounded server
    INTERACTION_PATTERNS = [
        r"\bcurl\b",
        r"\bwget\b",
        r"\bhttpie\b",
        r"\bhttp\s+",  # httpie alias
        r"\bsleep\b",
        r"\bpkill\b",
        r"\bkill\b",
    ]

    # Check if command has server backgrounded with &
    has_backgrounded_server = False
    server_name = ""
    for pattern in SERVER_PATTERNS:
        match = re.search(pattern, cmd_to_check, re.IGNORECASE)
        if not match:
            continue
        after_match = cmd_to_check[match.end() :]
        if re.search(r"(?<![>&])&(?![>&0-9])", after_match):
            has_backgrounded_server = True
            server_name = match.group(0)
            break

    if not has_backgrounded_server:
        return HookResult.approve()

    # Check if there's interaction after the &
    has_interaction = any(
        re.search(pattern, cmd_to_check, re.IGNORECASE)
        for pattern in INTERACTION_PATTERNS
    )

    if has_interaction:
        return HookResult.deny(
            f"⛔ **INLINE SERVER BACKGROUND BLOCKED**\n"
            f"Pattern: `{server_name} ... & ... curl/sleep`\n\n"
            f"This creates race conditions and hangs. Instead:\n"
            f"1. Run server with `run_in_background: true`\n"
            f"2. Wait for startup (check logs with TaskOutput)\n"
            f"3. Then run curl/tests in separate Bash call\n\n"
            f"Say SUDO to bypass."
        )

    return HookResult.approve()


# =============================================================================
# BACKGROUND ENFORCER (Priority 15) - Require background for slow commands
# =============================================================================


@register_hook("background_enforcer", "Bash", priority=15)
def check_background_enforcer(data: dict, state: SessionState) -> HookResult:
    """Enforce background execution for slow commands (unless truncated/fast).

    EXCEPTION: When ralph_mode is active and completion_confidence is low,
    allow foreground test runs so evidence can be captured for completion gate.
    """
    tool_input = data.get("tool_input", {})
    command = tool_input.get("command", "")
    run_in_background = tool_input.get("run_in_background", False)

    if run_in_background:
        return HookResult.approve()

    # RALPH EVIDENCE EXCEPTION: Allow foreground tests/builds when completion evidence needed
    # This prevents circular block: stop_hook demands evidence, but pre_tool blocks foreground commands
    if state.ralph_mode and state.completion_confidence < 80:
        cmd_lower = command.lower()
        # Test commands provide test_pass evidence (+25)
        test_commands = [
            "pytest",
            "python -m pytest",
            "npm test",
            "yarn test",
            "cargo test",
            "go test",
            "jest",
            "vitest",
        ]
        if any(tc in cmd_lower for tc in test_commands):
            return HookResult.approve(
                "✅ Foreground test allowed (ralph evidence collection)"
            )
        # Build commands provide build_success evidence (+20)
        build_commands = [
            "npm run build",
            "yarn build",
            "cargo build",
            "go build",
            "tsc",
            "webpack",
            "vite build",
        ]
        if any(bc in cmd_lower for bc in build_commands):
            return HookResult.approve(
                "✅ Foreground build allowed (ralph evidence collection)"
            )

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

    # Patterns that truncate output or are inherently fast
    FAST_PATTERNS = [
        "| head",
        "|head",
        "| tail",
        "|tail",
        "--help",
        "-h ",
        "--version",
        "-V ",
        "timeout ",
    ]

    cmd_to_check = strip_heredoc_content(command).lower()

    for fast in FAST_PATTERNS:
        if fast in cmd_to_check:
            return HookResult.approve()

    for slow in SLOW_COMMANDS:
        if slow in cmd_to_check:
            return HookResult.deny(
                f"⛔ BACKGROUND REQUIRED: `{slow}` is slow → run_in_background=true"
            )
    return HookResult.approve()


# =============================================================================
# PROBE GATE (Priority 18) - Suggest probing unfamiliar APIs
# =============================================================================


@register_hook("probe_gate", "Bash", priority=18)
def check_probe_gate(data: dict, state: SessionState) -> HookResult:
    """Suggest probing unfamiliar library APIs before using them."""
    tool_input = data.get("tool_input", {})
    command = tool_input.get("command", "")

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

    is_python_cmd = any(re.search(p, command) for p in PYTHON_RUN_PATTERNS)
    if not is_python_cmd:
        return HookResult.approve()

    found_libs = []
    for lib, api_hint in PROBEABLE_LIBS.items():
        if re.search(rf"\b{lib}\b", command, re.IGNORECASE):
            probed = getattr(state, "probed_libs", [])
            if lib.lower() not in [p.lower() for p in probed]:
                found_libs.append((lib, api_hint))

    if found_libs and len(found_libs) <= 2:
        libs = ", ".join(lib for lib, _ in found_libs[:2])
        return HookResult.approve(
            f'🔬 PROBE? Unfamiliar: {libs} → `probe "<lib>.<obj>"`'
        )
    return HookResult.approve()


# =============================================================================
# COMMIT GATE (Priority 20) - Suggest upkeep before commit
# =============================================================================


@register_hook("commit_gate", "Bash", priority=20)
def check_commit_gate(data: dict, state: SessionState) -> HookResult:
    """Block git commit without upkeep."""
    tool_input = data.get("tool_input", {})
    command = tool_input.get("command", "")

    if "git commit" not in command:
        return HookResult.approve()

    from session_state import get_turns_since_op

    turns_since = get_turns_since_op(state, "upkeep")

    if turns_since > 20:
        return HookResult.approve(
            "⚠️ COMMIT GATE: Consider running `upkeep` before committing."
        )
    return HookResult.approve()


# =============================================================================
# TOOL PREFERENCE (Priority 25) - Nudge toward better tools
# =============================================================================


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
        if command.startswith("cat ") and "|" not in command:
            return HookResult.approve(
                "💡 Prefer `Read` tool over `cat` for reading files."
            )
        if command.startswith(("grep ", "rg ")) and not any(
            x in command for x in ["|", "&&", ";"]
        ):
            return HookResult.approve(
                "💡 Prefer `Grep` tool over bash grep for searching."
            )
    return HookResult.approve()


# =============================================================================
# HF CLI REDIRECT (Priority 26) - Redirect deprecated huggingface-cli
# =============================================================================


@register_hook("hf_cli_redirect", "Bash", priority=26)
def check_hf_cli_redirect(data: dict, state: SessionState) -> HookResult:
    """Block deprecated huggingface-cli, redirect to hf command."""
    command = data.get("tool_input", {}).get("command", "")
    if "huggingface-cli" in command:
        return HookResult.deny(
            "**BLOCKED**: `huggingface-cli` is deprecated.\n"
            "Use `hf` instead (e.g., `hf auth login`, `hf auth whoami`).\n"
            "The `hf` command is installed at `~/.local/bin/hf`."
        )
    return HookResult.approve()
