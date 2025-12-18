#!/usr/bin/env python3
"""
Session Tracking - Domain, file, library, command, ops tool, and error tracking.
"""

import hashlib
import json
import re
import time
from pathlib import Path
from typing import TYPE_CHECKING

from _session_constants import (
    Domain,
    _DOMAIN_SIGNAL_PATTERNS,
    RESEARCH_REQUIRED_LIBS,
    STDLIB_PATTERNS,
    OPS_USAGE_FILE,
)

if TYPE_CHECKING:
    from _session_state_class import SessionState


# =============================================================================
# DOMAIN DETECTION
# =============================================================================


def detect_domain(state: "SessionState") -> tuple[str, float]:
    """Detect domain from accumulated signals."""
    if not state.domain_signals:
        return Domain.UNKNOWN, 0.0

    scores = {
        d: 0
        for d in [Domain.INFRASTRUCTURE, Domain.DEVELOPMENT, Domain.EXPLORATION, Domain.DATA]
    }

    combined_signals = " ".join(state.domain_signals[-20:]).lower()

    for domain, compiled_patterns in _DOMAIN_SIGNAL_PATTERNS.items():
        for pattern in compiled_patterns:
            matches = len(pattern.findall(combined_signals))
            scores[domain] += matches

    if max(scores.values()) == 0:
        return Domain.UNKNOWN, 0.0

    winner = max(scores, key=scores.get)
    total = sum(scores.values())
    confidence = scores[winner] / total if total > 0 else 0

    return winner, confidence


def add_domain_signal(state: "SessionState", signal: str):
    """Add a signal for domain detection."""
    state.domain_signals.append(signal)
    state.domain, state.domain_confidence = detect_domain(state)


# =============================================================================
# FILE TRACKING
# =============================================================================


def track_file_read(state: "SessionState", filepath: str):
    """Track that a file was read."""
    if filepath and filepath not in state.files_read:
        state.files_read.append(filepath)
    add_domain_signal(state, filepath)


def track_file_edit(
    state: "SessionState",
    filepath: str,
    old_string: str = "",
    new_string: str = "",
):
    """Track that a file was edited."""
    if filepath:
        if filepath not in state.files_edited:
            state.files_edited.append(filepath)
        state.edit_counts[filepath] = state.edit_counts.get(filepath, 0) + 1

        if old_string or new_string:
            old_hash = hashlib.md5(old_string.encode()).hexdigest()[:8] if old_string else ""
            new_hash = hashlib.md5(new_string.encode()).hexdigest()[:8] if new_string else ""
            if filepath not in state.edit_history:
                state.edit_history[filepath] = []
            state.edit_history[filepath].append((old_hash, new_hash, time.time()))
            state.edit_history[filepath] = state.edit_history[filepath][-10:]

    add_domain_signal(state, filepath)


def track_file_create(state: "SessionState", filepath: str):
    """Track that a file was created."""
    if filepath and filepath not in state.files_created:
        state.files_created.append(filepath)
    add_domain_signal(state, filepath)


def was_file_read(state: "SessionState", filepath: str) -> bool:
    """Check if a file was read this session."""
    return filepath in state.files_read


# =============================================================================
# LIBRARY TRACKING
# =============================================================================


def extract_libraries_from_code(code: str) -> list:
    """Extract library imports from code."""
    libs = []
    py_imports = re.findall(r"(?:from|import)\s+([\w.]+)", code)
    libs.extend(py_imports)
    js_imports = re.findall(r"(?:require|from)\s*['\"]([^'\"]+)['\"]", code)
    libs.extend(js_imports)

    cleaned = []
    for lib in libs:
        top_level = lib.split(".")[0].split("/")[0]
        if top_level and not _is_stdlib(top_level):
            cleaned.append(top_level)

    return list(set(cleaned))


def _is_stdlib(lib: str) -> bool:
    """Check if library is standard library."""
    for pattern in STDLIB_PATTERNS:
        if re.match(pattern, lib):
            return True
    return False


def track_library_used(state: "SessionState", lib: str):
    """Track that a library is being used."""
    if lib and lib not in state.libraries_used:
        state.libraries_used.append(lib)


def track_library_researched(state: "SessionState", lib: str):
    """Track that a library was researched."""
    if lib and lib not in state.libraries_researched:
        state.libraries_researched.append(lib)


def needs_research(state: "SessionState", lib: str) -> bool:
    """Check if a library needs research before use."""
    if lib in state.libraries_researched:
        return False
    if _is_stdlib(lib):
        return False
    lib_lower = lib.lower()
    for research_lib in RESEARCH_REQUIRED_LIBS:
        if research_lib in lib_lower or lib_lower in research_lib:
            return True
    return False


# =============================================================================
# COMMAND TRACKING
# =============================================================================


def track_command(state: "SessionState", command: str, success: bool, output: str = ""):
    """Track a command execution."""
    from _session_errors import track_error

    cmd_record = {
        "command": command[:200],
        "success": success,
        "timestamp": time.time(),
        "output": output[:500] if output else "",
    }

    if success:
        state.commands_succeeded.append(cmd_record)
    else:
        state.commands_failed.append(cmd_record)
        track_error(state, f"Command failed: {command[:100]}", output[:500])

    add_domain_signal(state, command)

    if "pytest" in command or "npm test" in command or "cargo test" in command:
        state.tests_run = True

    if "verify.py" in command:
        state.last_verify = time.time()

    if "deploy" in command.lower():
        state.last_deploy = {
            "command": command[:200],
            "timestamp": time.time(),
            "success": success,
        }

    if "research.py" in command or "probe.py" in command:
        parts = command.split()
        for i, part in enumerate(parts):
            if part in ["research.py", "probe.py"] and i + 1 < len(parts):
                topic = parts[i + 1].strip("'\"")
                track_library_researched(state, topic)


# =============================================================================
# OPS TOOL TRACKING
# =============================================================================


def track_ops_tool(state: "SessionState", tool_name: str, success: bool = True):
    """Track ops tool usage for analytics."""
    if tool_name not in state.ops_tool_usage:
        state.ops_tool_usage[tool_name] = {
            "count": 0,
            "last_turn": 0,
            "successes": 0,
            "failures": 0,
        }
    state.ops_tool_usage[tool_name]["count"] += 1
    state.ops_tool_usage[tool_name]["last_turn"] = state.turn_count
    if success:
        state.ops_tool_usage[tool_name]["successes"] += 1
    else:
        state.ops_tool_usage[tool_name]["failures"] += 1

    _persist_ops_tool_usage(tool_name, success)


def _persist_ops_tool_usage(tool_name: str, success: bool):
    """Persist ops tool usage to cross-session file."""
    try:
        data = {}
        if OPS_USAGE_FILE.exists():
            data = json.loads(OPS_USAGE_FILE.read_text())

        if tool_name not in data:
            data[tool_name] = {
                "total_uses": 0,
                "successes": 0,
                "failures": 0,
                "first_used": time.strftime("%Y-%m-%d"),
                "last_used": "",
                "sessions": 0,
            }
        data[tool_name]["total_uses"] += 1
        data[tool_name]["last_used"] = time.strftime("%Y-%m-%d %H:%M")
        if success:
            data[tool_name]["successes"] += 1
        else:
            data[tool_name]["failures"] += 1

        tmp = OPS_USAGE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2))
        tmp.rename(OPS_USAGE_FILE)
    except Exception:
        pass


def get_ops_tool_stats() -> dict:
    """Get cross-session ops tool usage statistics."""
    if OPS_USAGE_FILE.exists():
        try:
            return json.loads(OPS_USAGE_FILE.read_text())
        except Exception:
            pass
    return {}


def get_unused_ops_tools(days_threshold: int = 30) -> list:
    """Get ops tools not used in the last N days."""
    from datetime import datetime, timedelta

    stats = get_ops_tool_stats()
    cutoff = datetime.now() - timedelta(days=days_threshold)
    unused = []

    ops_dir = Path.home() / ".claude" / "ops"
    if ops_dir.exists():
        all_tools = {f.stem for f in ops_dir.glob("*.py")}
        for tool in all_tools:
            if tool not in stats:
                unused.append(tool)
            else:
                last_used = stats[tool].get("last_used", "")
                if last_used:
                    try:
                        last_dt = datetime.strptime(last_used[:10], "%Y-%m-%d")
                        if last_dt < cutoff:
                            unused.append(tool)
                    except Exception:
                        pass
    return unused


def mark_production_verified(state: "SessionState", filepath: str, tool: str):
    """Mark a file as having passed audit or void this session."""
    if filepath not in state.verified_production_files:
        state.verified_production_files[filepath] = {}
    state.verified_production_files[filepath][f"{tool}_turn"] = state.turn_count


def is_production_verified(state: "SessionState", filepath: str) -> tuple[bool, str]:
    """Check if a file has passed both audit and void this session."""
    verified = state.verified_production_files.get(filepath, {})
    has_audit = "audit_turn" in verified
    has_void = "void_turn" in verified

    if has_audit and has_void:
        return True, ""
    elif has_audit:
        return False, "void"
    elif has_void:
        return False, "audit"
    else:
        return False, "both"
