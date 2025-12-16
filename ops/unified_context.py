#!/usr/bin/env python3
"""
Unified Context Aggregator

Aggregates context from multiple sources into a single dump:
- Serena project memories and config
- Framework memories (~/.claude/memory/)
- Claude-mem recent observations
- Beads status (open, in_progress, blocked)
- Session state

Useful for session handoffs and context recovery.

Usage:
    unified_context.py [--format json|text] [--focus AREA]
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path


def get_serena_context(project_root: Path | None = None) -> dict:
    """Get Serena project context if available."""
    context = {"available": False, "memories": [], "project": None}

    # Find .serena directory
    search_paths = [Path.cwd()]
    if project_root:
        search_paths.insert(0, project_root)

    serena_root = None
    for start in search_paths:
        for parent in [start, *start.parents]:
            if (parent / ".serena").is_dir():
                serena_root = parent
                break
            if parent == Path.home():
                break
        if serena_root:
            break

    if not serena_root:
        return context

    context["available"] = True
    context["project"] = serena_root.name

    # List memories
    memories_dir = serena_root / ".serena" / "memories"
    if memories_dir.is_dir():
        context["memories"] = [m.name for m in sorted(memories_dir.glob("*.md"))]

    return context


def get_framework_context() -> dict:
    """Get framework memory context."""
    context = {"memories": [], "capabilities": None}

    memory_dir = Path.home() / ".claude" / "memory"
    if memory_dir.is_dir():
        context["memories"] = [m.name for m in sorted(memory_dir.glob("*.md"))]

        # Check for capabilities file
        caps = memory_dir / "__capabilities.md"
        if caps.exists():
            context["capabilities"] = str(caps)

    return context


def get_claudemem_context(limit: int = 10) -> dict:
    """Get recent claude-mem observations."""
    context = {"available": False, "recent": [], "error": None}

    try:
        import urllib.request

        url = "http://127.0.0.1:37777/api/status"
        req = urllib.request.Request(url, method="GET")
        req.add_header("Content-Type", "application/json")

        with urllib.request.urlopen(req, timeout=2) as resp:
            if resp.status == 200:
                context["available"] = True
                # Note: Would need to call search endpoint for recent observations
                # For now just indicate availability
    except Exception as e:
        context["error"] = str(e)

    return context


def get_beads_context() -> dict:
    """Get beads/task tracking context."""
    context = {"open": [], "in_progress": [], "blocked": [], "error": None}

    try:
        # Get open beads
        result = subprocess.run(
            ["bd", "list", "--status=open", "--json"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            context["open"] = json.loads(result.stdout)

        # Get in_progress beads
        result = subprocess.run(
            ["bd", "list", "--status=in_progress", "--json"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            context["in_progress"] = json.loads(result.stdout)

        # Get blocked beads
        result = subprocess.run(
            ["bd", "blocked", "--json"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            context["blocked"] = json.loads(result.stdout)

    except Exception as e:
        context["error"] = str(e)

    return context


def get_session_context() -> dict:
    """Get current session state."""
    context = {"session_id": None, "confidence": None, "cwd": str(Path.cwd())}

    # Try to get session ID
    session_id = os.environ.get("CLAUDE_SESSION_ID")
    if not session_id:
        state_file = Path.home() / ".claude" / "tmp" / "session_state_v3.json"
        if state_file.exists():
            try:
                with open(state_file) as f:
                    state = json.load(f)
                    session_id = state.get("session_id")
                    context["confidence"] = state.get("confidence")
            except (json.JSONDecodeError, OSError):
                pass

    context["session_id"] = session_id
    return context


def aggregate_context(focus: str | None = None) -> dict:
    """Aggregate all context sources."""
    return {
        "timestamp": datetime.now().isoformat(),
        "focus": focus,
        "serena": get_serena_context(),
        "framework": get_framework_context(),
        "claudemem": get_claudemem_context(),
        "beads": get_beads_context(),
        "session": get_session_context(),
    }


def format_text(context: dict) -> str:
    """Format context as readable text."""
    lines = ["=" * 60, "UNIFIED CONTEXT DUMP", "=" * 60, ""]

    # Timestamp
    lines.append(f"Generated: {context['timestamp']}")
    if context["focus"]:
        lines.append(f"Focus: {context['focus']}")
    lines.append("")

    # Session
    session = context["session"]
    lines.append("## Session")
    lines.append(f"  ID: {session.get('session_id', 'unknown')}")
    lines.append(f"  CWD: {session.get('cwd')}")
    if session.get("confidence"):
        lines.append(f"  Confidence: {session['confidence']}%")
    lines.append("")

    # Serena
    serena = context["serena"]
    lines.append("## Serena")
    if serena["available"]:
        lines.append(f"  Project: {serena['project']}")
        lines.append(f"  Memories: {len(serena['memories'])}")
        for m in serena["memories"][:5]:
            lines.append(f"    - {m}")
        if len(serena["memories"]) > 5:
            lines.append(f"    ... and {len(serena['memories']) - 5} more")
    else:
        lines.append("  Not available")
    lines.append("")

    # Framework
    framework = context["framework"]
    lines.append("## Framework Memories")
    lines.append(f"  Count: {len(framework['memories'])}")
    for m in framework["memories"][:5]:
        lines.append(f"    - {m}")
    if len(framework["memories"]) > 5:
        lines.append(f"    ... and {len(framework['memories']) - 5} more")
    lines.append("")

    # Claude-mem
    claudemem = context["claudemem"]
    lines.append("## Claude-mem")
    lines.append(f"  Available: {claudemem['available']}")
    if claudemem.get("error"):
        lines.append(f"  Error: {claudemem['error']}")
    lines.append("")

    # Beads
    beads = context["beads"]
    lines.append("## Beads Status")
    lines.append(f"  Open: {len(beads['open'])}")
    lines.append(f"  In Progress: {len(beads['in_progress'])}")
    lines.append(f"  Blocked: {len(beads['blocked'])}")

    if beads["in_progress"]:
        lines.append("  Active work:")
        for b in beads["in_progress"][:3]:
            lines.append(f"    - [{b.get('id', '?')[:12]}] {b.get('title', '?')[:50]}")

    if beads.get("error"):
        lines.append(f"  Error: {beads['error']}")
    lines.append("")

    lines.append("=" * 60)
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Aggregate unified context")
    parser.add_argument(
        "--format",
        "-f",
        choices=["json", "text"],
        default="text",
        help="Output format",
    )
    parser.add_argument("--focus", help="Focus area for context")

    args = parser.parse_args()

    context = aggregate_context(args.focus)

    if args.format == "json":
        print(json.dumps(context, indent=2, default=str))
    else:
        print(format_text(context))

    return 0


if __name__ == "__main__":
    sys.exit(main())
