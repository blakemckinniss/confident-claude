#!/usr/bin/env python3
"""
Session Batch - Batch tracking, pending files/searches, integration blindness.
"""

import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from _session_state_class import SessionState

# Batch tool sets
STRICT_BATCH_TOOLS = frozenset({"Read", "Grep", "Glob"})
SOFT_BATCH_TOOLS = frozenset({"WebFetch", "WebSearch"})
BATCHABLE_TOOLS = STRICT_BATCH_TOOLS | SOFT_BATCH_TOOLS

# Function definition patterns
FUNCTION_PATTERNS = [
    (re.compile(r"\bdef\s+(\w+)\s*\("), "python"),
    (re.compile(r"\basync\s+def\s+(\w+)\s*\("), "python"),
    (re.compile(r"\bfunction\s+(\w+)\s*\("), "js"),
    (re.compile(r"\b(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?\([^)]*\)\s*=>"), "js"),
    (re.compile(r"\bexport\s+(?:const|let|var)\s+(\w+)\s*="), "js"),
    (re.compile(r"^\s+(\w+)\s*\([^)]*\)\s*\{", re.MULTILINE), "js"),
    (re.compile(r"\bfn\s+(\w+)\s*[<(]"), "rust"),
    (re.compile(r"\bfunc\s+(\w+)\s*\("), "go"),
]

_FUNC_DEF_PATTERNS = [
    (re.compile(r"^(\s*def\s+(\w+)\s*\([^)]*\)\s*(?:->.*?)?:)"), 2),
    (re.compile(r"^(\s*(?:async\s+)?function\s+(\w+)\s*\([^)]*\))"), 2),
    (re.compile(r"^(\s*(?:pub\s+)?fn\s+(\w+)\s*[<(][^{]*)"), 2),
    (re.compile(r"^(\s*func\s+(\w+)\s*\([^)]*\))"), 2),
]

_RE_PYTHON_COMMENT = re.compile(r"#.*$", re.MULTILINE)
_RE_JS_COMMENT = re.compile(r"//.*$", re.MULTILINE)


def track_batch_tool(state: "SessionState", tool_name: str, tools_in_message: int):
    """Track batch/sequential tool usage patterns."""
    if tool_name not in BATCHABLE_TOOLS:
        return

    state.last_message_tool_count = tools_in_message

    if tools_in_message == 1:
        state.consecutive_single_reads += 1
    else:
        state.consecutive_single_reads = 0


def add_pending_file(state: "SessionState", filepath: str):
    """Add a file to pending reads."""
    if filepath and filepath not in state.pending_files:
        state.pending_files.append(filepath)
        state.pending_files = state.pending_files[-20:]


def add_pending_search(state: "SessionState", pattern: str):
    """Add a search pattern to pending searches."""
    if pattern and pattern not in state.pending_searches:
        state.pending_searches.append(pattern)
        state.pending_searches = state.pending_searches[-10:]


def clear_pending_file(state: "SessionState", filepath: str):
    """Clear a file from pending."""
    if filepath in state.pending_files:
        state.pending_files.remove(filepath)


def clear_pending_search(state: "SessionState", pattern: str):
    """Clear a search from pending."""
    if pattern in state.pending_searches:
        state.pending_searches.remove(pattern)


def extract_function_def_lines(code: str) -> dict[str, str]:
    """Extract function definition lines for signature change detection."""
    result = {}
    for line in code.split("\n"):
        for pattern, name_group in _FUNC_DEF_PATTERNS:
            match = pattern.match(line)
            if match:
                result[match.group(name_group)] = " ".join(match.group(1).strip().split())
                break
    return result


def add_pending_integration_grep(state: "SessionState", function_name: str, file_path: str):
    """Add a function that needs grep verification after edit."""
    GREP_COOLDOWN = 3
    grepped_turn = state.grepped_functions.get(function_name, -999)
    if state.turn_count - grepped_turn <= GREP_COOLDOWN:
        return

    entry = {
        "function": function_name,
        "file": file_path,
        "turn": state.turn_count,
    }
    existing = [p["function"] for p in state.pending_integration_greps]
    if function_name not in existing:
        state.pending_integration_greps.append(entry)
    state.pending_integration_greps = state.pending_integration_greps[-5:]


def clear_integration_grep(state: "SessionState", pattern: str):
    """Clear pending integration grep if pattern matches function name."""
    for p in state.pending_integration_greps:
        func_name = p["function"]
        if func_name in pattern or pattern in func_name:
            state.grepped_functions[func_name] = state.turn_count

    if len(pattern) > 3:
        state.grepped_functions[pattern] = state.turn_count

    if len(state.grepped_functions) > 20:
        sorted_funcs = sorted(
            state.grepped_functions.items(), key=lambda x: x[1], reverse=True
        )
        state.grepped_functions = dict(sorted_funcs[:20])

    state.pending_integration_greps = [
        p
        for p in state.pending_integration_greps
        if p["function"] not in pattern and pattern not in p["function"]
    ]


def get_pending_integration_greps(state: "SessionState") -> list[dict]:
    """Get pending integration greps (max age: 10 turns)."""
    return [
        p
        for p in state.pending_integration_greps
        if state.turn_count - p.get("turn", 0) <= 10
    ]


def check_integration_blindness(
    state: "SessionState", tool_name: str, tool_input: dict
) -> tuple[bool, str]:
    """Check if there are pending integration greps that should block."""
    pending = get_pending_integration_greps(state)
    if not pending:
        return False, ""

    diagnostic_tools = {"Read", "Grep", "Glob", "Bash", "BashOutput", "TodoWrite"}
    if tool_name in diagnostic_tools:
        return False, ""

    if tool_name == "Task":
        subagent_type = tool_input.get("subagent_type", "").lower()
        read_only_agents = {
            "scout", "digest", "parallel", "explore", "chore", "plan", "claude-code-guide"
        }
        if subagent_type in read_only_agents:
            return False, ""

    if tool_name in {"Edit", "Write"}:
        file_path = tool_input.get("file_path", "")
        non_code_extensions = {
            ".md", ".json", ".txt", ".yaml", ".yml", ".toml", ".ini",
            ".cfg", ".csv", ".css", ".scss", ".sass", ".less",
        }
        if Path(file_path).suffix.lower() in non_code_extensions:
            return False, ""

        pending_files = {p["file"] for p in pending}
        if file_path not in pending_files:
            return False, ""

    func_list = ", ".join(f"`{p['function']}`" for p in pending[:3])
    agent_hint = ""
    if tool_name == "Task":
        agent_hint = "\nNote: Read-only agents (scout, digest, parallel, Explore, chore) are allowed."

    return True, (
        f"**INTEGRATION BLINDNESS BLOCKED** (Hard Block #6)\n"
        f"Edited functions: {func_list}\n"
        f'REQUIRED: Run `grep -r "function_name"` to find callers before continuing.\n'
        f"Pattern: After function edit, grep is MANDATORY.{agent_hint}"
    )
