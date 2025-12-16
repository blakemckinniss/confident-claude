#!/usr/bin/env python3
"""
Serena Integration Utility

Provides convenient access to Serena MCP capabilities with workflow hints.
Outputs MCP call suggestions rather than executing directly (Claude executes).

Subcommands:
    status    - Check Serena availability and project status
    impact    - Analyze impact of changes to a symbol
    validate  - Validate code changes in a file
    memories  - List/search Serena project memories
    context   - Get unified context (Serena + framework + claude-mem)
    search    - Search for patterns in codebase

Usage:
    serena.py status
    serena.py impact <symbol_name> [--file PATH]
    serena.py validate <file_path>
    serena.py memories [--search QUERY]
    serena.py context [--focus AREA]
    serena.py search <pattern> [--path PATH]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def check_serena_available() -> tuple[bool, Path | None]:
    """Check if Serena is available in current directory or any parent."""
    cwd = Path.cwd()

    # Check current and parent directories
    for parent in [cwd, *cwd.parents]:
        serena_dir = parent / ".serena"
        if serena_dir.is_dir():
            return True, parent
        # Stop at home or root
        if parent == Path.home() or parent == Path("/"):
            break

    return False, None


def print_mcp_hint(tool: str, params: dict) -> None:
    """Print an MCP tool call hint for Claude to execute."""
    print("\n💡 MCP Workflow:")
    print(f"   Tool: mcp__serena__{tool}")
    if params:
        print("   Parameters:")
        for k, v in params.items():
            print(f"     {k}: {v}")


def cmd_status(args: argparse.Namespace) -> int:
    """Check Serena status."""
    available, project_root = check_serena_available()

    if not available:
        print("✗ Serena not available")
        print("  No .serena/ directory found in current path or parents")
        print("\n💡 To set up Serena:")
        print("  1. Ensure .serena/ exists in project root")
        print('  2. Run: mcp__serena__activate_project("<project_name>")')
        return 1

    print(f"✓ Serena available at: {project_root}")

    # Check for memories
    memories_dir = project_root / ".serena" / "memories"
    if memories_dir.is_dir():
        memories = list(memories_dir.glob("*.md"))
        print(f"  Memories: {len(memories)}")

    print_mcp_hint("get_current_config", {})
    print_mcp_hint("list_memories", {})

    return 0


def cmd_impact(args: argparse.Namespace) -> int:
    """Analyze symbol impact."""
    available, project_root = check_serena_available()
    if not available:
        print("✗ Serena not available - cannot analyze impact")
        return 1

    symbol = args.symbol
    print(f"Impact analysis for symbol: {symbol}")

    # Build MCP workflow
    print("\n📋 Suggested MCP workflow:")

    params = {"name_path_pattern": symbol, "include_body": False, "depth": 1}
    if args.file:
        params["relative_path"] = args.file

    print("\n1. Find the symbol:")
    print_mcp_hint("find_symbol", params)

    print("\n2. Find references to it:")
    ref_params = {"name_path": symbol}
    if args.file:
        ref_params["relative_path"] = args.file
    print_mcp_hint("find_referencing_symbols", ref_params)

    print("\n3. Think about collected information:")
    print_mcp_hint("think_about_collected_information", {})

    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    """Validate file changes."""
    available, project_root = check_serena_available()
    if not available:
        print("✗ Serena not available - cannot validate")
        return 1

    file_path = args.file
    print(f"Validation workflow for: {file_path}")

    print("\n📋 Suggested MCP workflow:")

    print("\n1. Get symbols overview:")
    print_mcp_hint("get_symbols_overview", {"relative_path": file_path})

    print("\n2. Check for diagnostics:")
    print("   Tool: mcp__ide__getDiagnostics")
    print(f"   Parameters: uri: file://{Path(file_path).resolve()}")

    print("\n3. Think about task adherence:")
    print_mcp_hint("think_about_task_adherence", {})

    return 0


def cmd_memories(args: argparse.Namespace) -> int:
    """List or search Serena memories."""
    available, project_root = check_serena_available()
    if not available:
        print("✗ Serena not available")
        return 1

    memories_dir = project_root / ".serena" / "memories"

    if not memories_dir.is_dir():
        print("No memories directory found")
        print_mcp_hint("list_memories", {})
        return 0

    memories = sorted(memories_dir.glob("*.md"))

    if args.search:
        print(f"Searching memories for: {args.search}")
        print_mcp_hint(
            "search_for_pattern",
            {
                "substring_pattern": args.search,
                "relative_path": ".serena/memories",
            },
        )
    else:
        print(f"Serena memories ({len(memories)}):")
        for m in memories:
            print(f"  - {m.name}")

        if memories:
            print("\n💡 To read a memory:")
            print_mcp_hint("read_memory", {"memory_file_name": "<name>.md"})

    return 0


def cmd_context(args: argparse.Namespace) -> int:
    """Get unified context."""
    available, project_root = check_serena_available()

    print("📦 Unified Context Sources:\n")

    # 1. Serena context
    if available:
        print("1. Serena (✓ available)")
        print_mcp_hint("get_current_config", {})
        print_mcp_hint("list_memories", {})
    else:
        print("1. Serena (✗ not available)")

    # 2. Framework context
    print("\n2. Framework memories")
    framework_mem = Path.home() / ".claude" / "memory"
    if framework_mem.is_dir():
        mems = list(framework_mem.glob("*.md"))
        print(f"   Found {len(mems)} memory files at {framework_mem}")

    # 3. Claude-mem context
    print("\n3. Claude-mem (skill)")
    print("   Use: /spark <topic> or mem-search skill")

    # 4. Beads context
    print("\n4. Beads status")
    print("   Run: bd ready | bd list --status=in_progress")

    if args.focus:
        print(f"\n🎯 Focus area: {args.focus}")
        print_mcp_hint(
            "search_for_pattern",
            {
                "substring_pattern": args.focus,
                "restrict_search_to_code_files": True,
            },
        )

    return 0


def cmd_search(args: argparse.Namespace) -> int:
    """Search codebase."""
    available, _ = check_serena_available()
    if not available:
        print("✗ Serena not available - use Grep tool instead")
        return 1

    pattern = args.pattern
    print(f"Search for: {pattern}")

    params = {
        "substring_pattern": pattern,
        "restrict_search_to_code_files": True,
    }
    if args.path:
        params["relative_path"] = args.path

    print_mcp_hint("search_for_pattern", params)

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Serena integration utility - provides MCP workflow hints"
    )
    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # status
    subparsers.add_parser("status", help="Check Serena availability")

    # impact
    impact_parser = subparsers.add_parser("impact", help="Analyze symbol impact")
    impact_parser.add_argument("symbol", help="Symbol name or path")
    impact_parser.add_argument("--file", "-f", help="Restrict to file")

    # validate
    validate_parser = subparsers.add_parser("validate", help="Validate file changes")
    validate_parser.add_argument("file", help="File to validate")

    # memories
    memories_parser = subparsers.add_parser("memories", help="List/search memories")
    memories_parser.add_argument("--search", "-s", help="Search query")

    # context
    context_parser = subparsers.add_parser("context", help="Get unified context")
    context_parser.add_argument("--focus", "-f", help="Focus area")

    # search
    search_parser = subparsers.add_parser("search", help="Search codebase")
    search_parser.add_argument("pattern", help="Search pattern")
    search_parser.add_argument("--path", "-p", help="Restrict to path")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 0

    commands = {
        "status": cmd_status,
        "impact": cmd_impact,
        "validate": cmd_validate,
        "memories": cmd_memories,
        "context": cmd_context,
        "search": cmd_search,
    }

    return commands[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
