#!/usr/bin/env python3
"""
PermissionRequest Hook Runner

Fires when Claude Code shows a permission dialog to the user.
Can auto-approve, auto-deny, or let the dialog show.

Opportunities:
1. Auto-approve safe operations (read-only, scratch dirs)
2. Auto-deny dangerous operations (rm -rf, force push)
3. Confidence-gated permissions
4. Audit trail logging
"""

import json
import sys
import os
from pathlib import Path
from datetime import datetime

# Add lib to path
sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

from _session_state_class import load_state


SCRATCH_DIRS = [
    os.path.expanduser("~/.claude/tmp/"),
    "/tmp/",
    os.path.expanduser("~/tmp/"),
]

DANGEROUS_BASH_PATTERNS = [
    "rm -rf /",
    "rm -rf ~",
    "rm -rf $HOME",
    "> /dev/sda",
    "mkfs.",
    "dd if=/dev/zero",
    ":(){:|:&};:",  # fork bomb
    "chmod -R 777 /",
    "push --force origin main",
    "push --force origin master",
    "push -f origin main",
    "push -f origin master",
]

READ_ONLY_TOOLS = ["Read", "Glob", "Grep", "LS"]
WRITE_TOOLS = ["Write", "Edit", "MultiEdit"]
MCP_READ_KEYWORDS = ["read", "get", "list", "search", "find"]

LOW_CONFIDENCE_THRESHOLD = 50
DEFAULT_CONFIDENCE = 75


def _check_auto_approve(tool_name: str, tool_input: dict) -> dict | None:
    """Check if operation should be auto-approved."""
    if tool_name in READ_ONLY_TOOLS:
        return {"behavior": "allow", "message": "Read operations auto-approved"}

    if tool_name in WRITE_TOOLS:
        file_path = tool_input.get("file_path", "") or tool_input.get("path", "")
        for scratch in SCRATCH_DIRS:
            if file_path.startswith(scratch):
                return {
                    "behavior": "allow",
                    "message": f"Scratch write auto-approved: {scratch}",
                }

    if tool_name.startswith("mcp__") and any(
        kw in tool_name for kw in MCP_READ_KEYWORDS
    ):
        return {"behavior": "allow", "message": "MCP read operation auto-approved"}

    return None


def _check_dangerous_bash(tool_name: str, tool_input: dict) -> dict | None:
    """Check for dangerous bash patterns."""
    if tool_name != "Bash":
        return None

    command = tool_input.get("command", "")
    for pattern in DANGEROUS_BASH_PATTERNS:
        if pattern in command:
            return {
                "behavior": "deny",
                "message": f"🚫 BLOCKED: Dangerous command pattern: {pattern}",
                "interrupt": True,
            }
    return None


def _check_confidence_gate(
    tool_name: str, tool_input: dict, confidence: int
) -> dict | None:
    """Check confidence-gated write permissions."""
    if confidence >= LOW_CONFIDENCE_THRESHOLD:
        return None

    if tool_name not in WRITE_TOOLS:
        return None

    file_path = tool_input.get("file_path", "") or tool_input.get("path", "")
    is_scratch = any(file_path.startswith(s) for s in SCRATCH_DIRS)

    if not is_scratch:
        return {
            "behavior": "deny",
            "message": f"🔴 Confidence too low ({confidence}%) for production writes.",
            "interrupt": False,
        }
    return None


def get_permission_decision(data: dict) -> dict | None:
    """Evaluate permission request and decide whether to allow/deny/ask."""
    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})

    state = load_state()
    confidence = state.confidence if state else DEFAULT_CONFIDENCE

    # Check patterns in order
    if decision := _check_auto_approve(tool_name, tool_input):
        return decision

    if decision := _check_dangerous_bash(tool_name, tool_input):
        return decision

    if decision := _check_confidence_gate(tool_name, tool_input, confidence):
        return decision

    # Audit log all requests
    log_permission_request(data, confidence)

    return None  # Let normal dialog show


def log_permission_request(data: dict, confidence: int):
    """Log permission request to audit file."""
    log_dir = Path.home() / ".claude" / "tmp" / "audit"
    log_dir.mkdir(parents=True, exist_ok=True)

    log_file = log_dir / "permission_requests.jsonl"

    entry = {
        "timestamp": datetime.now().isoformat(),
        "session_id": data.get("session_id", "unknown"),
        "tool_name": data.get("tool_name", ""),
        "tool_input_summary": summarize_input(data.get("tool_input", {})),
        "confidence": confidence,
        "message": data.get("message", ""),
    }

    try:
        with open(log_file, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass  # Non-critical


def summarize_input(tool_input: dict) -> str:
    """Create brief summary of tool input for logging."""
    if not tool_input:
        return ""

    # Extract key fields
    summary_parts = []

    if "file_path" in tool_input:
        summary_parts.append(f"file={tool_input['file_path']}")
    if "path" in tool_input:
        summary_parts.append(f"path={tool_input['path']}")
    if "command" in tool_input:
        cmd = tool_input["command"]
        # Truncate long commands
        if len(cmd) > 100:
            cmd = cmd[:100] + "..."
        summary_parts.append(f"cmd={cmd}")
    if "pattern" in tool_input:
        summary_parts.append(f"pattern={tool_input['pattern']}")

    return "; ".join(summary_parts) if summary_parts else str(tool_input)[:200]


def main():
    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError:
        sys.exit(0)

    decision = get_permission_decision(data)

    if decision:
        output = {
            "hookSpecificOutput": {
                "hookEventName": "PermissionRequest",
                "decision": decision,
            }
        }
        print(json.dumps(output))

    sys.exit(0)


if __name__ == "__main__":
    main()
