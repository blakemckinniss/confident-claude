#!/usr/bin/env python3
"""
Command Awareness: Suggests relevant slash commands based on prompt context.

Parses .claude/commands/*.md frontmatter and provides assertive suggestions
like "Use /bdg to control Chrome" or "Use /commit for smart git commit".
"""

import os
import re
from pathlib import Path
from typing import Optional

_LIB_DIR = Path(__file__).parent
_CLAUDE_DIR = _LIB_DIR.parent
_COMMANDS_DIR = _CLAUDE_DIR / "commands"

# Cache: (mtime, commands_dict)
_COMMANDS_CACHE: Optional[tuple] = None

# Keyword → command mappings for assertive suggestions
# Format: pattern → (command, suggestion)
COMMAND_TRIGGERS = {
    # Task tracking (beads) - HIGHEST PRIORITY
    r"task|todo|track|planning|multi.?step|complex (task|work)|several (things|steps|tasks)": (
        "/bd", "Use `/bd ready` to see available tasks, `/bd create` to add new ones"
    ),
    r"what.*(work|task|do next)|where (was i|did i leave)|pick up|resume": (
        "/bd", "Use `/bd ready` to see tasks ready to work on"
    ),
    r"done with|finished|completed|close (the |this )?(task|issue|ticket)": (
        "/bd", "Use `/bd close <id>` to mark tasks complete"
    ),
    r"depends on|blocked by|blocking|prerequisite|before (i|we) can": (
        "/bd", "Use `/bd dep add <issue> <blocks>` to track dependencies"
    ),
    # Browser/UI testing
    r"browser|chrome|devtools|dom|screenshot|ui test": (
        "/bdg", "Use `/bdg start` to launch Chrome, then `/bdg navigate <url>` to test"
    ),
    # Git operations
    r"commit|push|stage|git add": (
        "/commit", "Use `/commit` for smart staging and commit with proper message"
    ),
    # Code review
    r"code review|review (my |the |this )?code|pr review|pull request": (
        "/cr", "Use `/cr` to run CodeRabbit AI review on your changes"
    ),
    # Complex decisions
    r"should (i|we)|which (approach|option|way)|decide|tradeoff": (
        "/council", "Use `/council` for multi-perspective analysis (Judge, Critic, Skeptic)"
    ),
    # Debugging/investigation
    r"debug|investigate|root cause|why (is|does|did)": (
        "/think", "Use `/think` to decompose the problem into steps"
    ),
    # Verification
    r"verify|check|make sure|confirm|validate": (
        "/verify", "Use `/verify file_exists/grep_text/port_open` to confirm system state"
    ),
    # Security/audit
    r"security|vulnerab|audit|xss|injection|owasp": (
        "/audit", "Use `/audit <file>` for security, complexity, and style analysis"
    ),
    # Best practices
    r"best (way|practice|approach)|how should|optimal": (
        "/bestway", "Use `/bestway` to evaluate optimal approaches"
    ),
    # Feasibility
    r"can (i|we|claude)|is it possible|feasible": (
        "/cs", "Use `/cs` for quick feasibility and advisability check"
    ),
    # Memory/recall
    r"remember|previous|earlier|last (time|session)|we discussed": (
        "/recall", "Use `/recall <topic>` to search past session context"
    ),
    # Improvement
    r"improve|better|optimize|enhance|refactor": (
        "/better", "Use `/better <target>` to identify concrete improvements"
    ),
    # Completeness
    r"missing|incomplete|stub|todo|gap|finish": (
        "/void", "Use `/void <file>` to find stubs, missing CRUD, and gaps"
    ),
    # Research/docs
    r"documentation|docs|api|how does .* work": (
        "/research", "Use `/research` for live web search via Tavily"
    ),
    # System info
    r"system|cpu|memory|disk|wsl|service": (
        "/sysinfo", "Use `/sysinfo` for WSL2 system health (CPU/mem/disk/services)"
    ),
    # Skeptical review
    r"risk|fail|wrong|problem with|issue with|flaw": (
        "/skeptic", "Use `/skeptic` for hostile review - finds ways things will fail"
    ),
}


def _parse_commands() -> dict:
    """Parse command files and extract metadata."""
    global _COMMANDS_CACHE

    if not _COMMANDS_DIR.exists():
        return {}

    # Get latest mtime
    try:
        latest_mtime = max(
            f.stat().st_mtime for f in _COMMANDS_DIR.glob("*.md")
            if not f.name.startswith("README")
        )
    except ValueError:
        return {}

    # Check cache
    if _COMMANDS_CACHE and _COMMANDS_CACHE[0] >= latest_mtime:
        return _COMMANDS_CACHE[1]

    commands = {}
    for cmd_file in _COMMANDS_DIR.glob("*.md"):
        if cmd_file.name.startswith("README"):
            continue

        try:
            content = cmd_file.read_text()
            name = cmd_file.stem

            # Parse frontmatter
            desc_match = re.search(r'^description:\s*(.+)$', content, re.MULTILINE)
            hint_match = re.search(r'^argument-hint:\s*(.*)$', content, re.MULTILINE)

            commands[name] = {
                "name": f"/{name}",
                "description": desc_match.group(1).strip() if desc_match else "",
                "hint": hint_match.group(1).strip() if hint_match else "",
            }
        except Exception:
            continue

    _COMMANDS_CACHE = (latest_mtime, commands)
    return commands


def suggest_commands(prompt: str, max_suggestions: int = 2) -> list[str]:
    """
    Return assertive command suggestions based on prompt content.

    Returns list of strings like:
    - "Use `/bdg start` to launch Chrome for testing"
    - "Use `/commit` for smart staging and commit"
    """
    if not prompt or len(prompt) < 10:
        return []

    prompt_lower = prompt.lower()
    suggestions = []
    seen_commands = set()

    for pattern, (command, suggestion) in COMMAND_TRIGGERS.items():
        if command in seen_commands:
            continue

        try:
            if re.search(pattern, prompt_lower):
                suggestions.append(suggestion)
                seen_commands.add(command)

                if len(suggestions) >= max_suggestions:
                    break
        except re.error:
            continue

    return suggestions


def get_command_info(name: str) -> Optional[dict]:
    """Get info about a specific command."""
    commands = _parse_commands()
    # Handle with or without leading slash
    clean_name = name.lstrip("/")
    return commands.get(clean_name)


def list_commands() -> list[dict]:
    """List all available commands."""
    commands = _parse_commands()
    return list(commands.values())


# CLI interface
if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: command_awareness.py <prompt> | --list")
        sys.exit(1)

    if sys.argv[1] == "--list":
        for cmd in list_commands():
            print(f"{cmd['name']:20} {cmd['description']}")
    else:
        prompt = " ".join(sys.argv[1:])
        suggestions = suggest_commands(prompt)
        if suggestions:
            print("Suggestions:")
            for s in suggestions:
                print(f"  → {s}")
        else:
            print("No command suggestions for this prompt")
