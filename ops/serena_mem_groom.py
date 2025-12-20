#!/usr/bin/env python3
"""
Serena Memory Grooming Tool.

Manages Serena project memories:
- Lists all memories with age and type classification
- Prunes old session memories (keeps last N)
- Validates structural memories
- Shows memory statistics

Usage:
    serena_mem_groom.py [--status|--prune|--validate]

Options:
    --status    Show memory statistics (default)
    --prune     Remove old session memories
    --validate  Mark structural memories as validated
    --force     Skip confirmation for destructive operations
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

# Structural memories (kept forever, not session ephemera)
STRUCTURAL_MEMORIES = {
    "beads_system.md",
    "codebase_structure.md",
    "confidence_increasers.md",
    "confidence_reducers.md",
    "confidence_system.md",
    "hook_registry.md",
    "integration_synergy.md",
    "lib_modules.md",
    "memory_index.md",
    "ops_tools.md",
    "post_tool_use_hooks.md",
    "pre_tool_use_hooks.md",
    "project_overview.md",
    "prompt_suggestions.md",
    "session_runners.md",
    "session_state.md",
    "slash_commands.md",
    "stop_hooks.md",
    "style_conventions.md",
    "suggested_commands.md",
    "task_completion.md",
}

# Keep this many session memories
SESSION_MEMORY_KEEP = 30


def find_serena_memories() -> Path | None:
    """Find .serena/memories directory."""
    cwd = Path.cwd()
    for parent in [cwd, *cwd.parents]:
        candidate = parent / ".serena" / "memories"
        if candidate.is_dir():
            return candidate
        if parent == Path.home():
            break
    return None


def classify_memories(memories_dir: Path) -> dict:
    """Classify memories into structural, session, and unknown."""
    result = {"structural": [], "session": [], "unknown": []}

    for mem_file in memories_dir.glob("*.md"):
        mtime = datetime.fromtimestamp(mem_file.stat().st_mtime)
        age_days = (datetime.now() - mtime).days
        size_kb = mem_file.stat().st_size / 1024

        info = {
            "name": mem_file.name,
            "path": mem_file,
            "age_days": age_days,
            "size_kb": round(size_kb, 1),
            "mtime": mtime.isoformat(),
        }

        if mem_file.name in STRUCTURAL_MEMORIES:
            result["structural"].append(info)
        elif mem_file.name.startswith("session_"):
            result["session"].append(info)
        else:
            result["unknown"].append(info)

    # Sort sessions by age (newest first)
    result["session"].sort(key=lambda x: x["age_days"])

    return result


def show_status(memories_dir: Path):
    """Show memory statistics."""
    classified = classify_memories(memories_dir)

    print(f"📂 Serena Memories: {memories_dir}")
    print()

    # Structural memories
    print(f"📚 **Structural** ({len(classified['structural'])} files)")
    for mem in sorted(classified["structural"], key=lambda x: x["name"]):
        stale = "⚠️" if mem["age_days"] > 14 else "✓"
        print(f"   {stale} {mem['name']} ({mem['age_days']}d, {mem['size_kb']}KB)")

    print()

    # Session memories
    sessions = classified["session"]
    keep_count = min(len(sessions), SESSION_MEMORY_KEEP)
    prune_count = max(0, len(sessions) - SESSION_MEMORY_KEEP)

    print(
        f"📝 **Session** ({len(sessions)} files, keep {keep_count}, prune {prune_count})"
    )
    if sessions:
        newest = sessions[0]
        oldest = sessions[-1] if len(sessions) > 1 else newest
        print(f"   Newest: {newest['name']} ({newest['age_days']}d)")
        if prune_count > 0:
            print(f"   Oldest (to prune): {oldest['name']} ({oldest['age_days']}d)")

    print()

    # Unknown memories
    if classified["unknown"]:
        print(f"❓ **Unknown** ({len(classified['unknown'])} files)")
        for mem in classified["unknown"]:
            print(f"   {mem['name']} ({mem['age_days']}d, {mem['size_kb']}KB)")
        print()

    # Summary
    total = sum(len(v) for v in classified.values())
    total_size = sum(m["size_kb"] for v in classified.values() for m in v)
    print(f"📊 Total: {total} files, {round(total_size, 1)}KB")
    if prune_count > 0:
        print(f"💡 Run with --prune to remove {prune_count} old session memories")


def prune_sessions(memories_dir: Path, force: bool = False):
    """Prune old session memories."""
    classified = classify_memories(memories_dir)
    sessions = classified["session"]

    if len(sessions) <= SESSION_MEMORY_KEEP:
        print(f"✓ Only {len(sessions)} session memories, nothing to prune")
        return

    to_prune = sessions[SESSION_MEMORY_KEEP:]

    if not force:
        print(f"Will delete {len(to_prune)} session memories:")
        for mem in to_prune[:5]:
            print(f"  - {mem['name']} ({mem['age_days']}d old)")
        if len(to_prune) > 5:
            print(f"  ... and {len(to_prune) - 5} more")
        print()
        confirm = input("Proceed? [y/N] ").strip().lower()
        if confirm != "y":
            print("Aborted")
            return

    pruned = 0
    for mem in to_prune:
        try:
            mem["path"].unlink()
            pruned += 1
        except (OSError, PermissionError) as e:
            print(f"Failed to delete {mem['name']}: {e}")

    print(f"🧹 Pruned {pruned} session memories")


def validate_structural(memories_dir: Path):
    """Mark structural memories as validated."""
    metadata_file = memories_dir.parent / "memory_metadata.json"

    metadata = {}
    if metadata_file.exists():
        try:
            metadata = json.loads(metadata_file.read_text())
        except json.JSONDecodeError:
            pass

    now = datetime.now().isoformat()
    validated = 0

    for mem_file in memories_dir.glob("*.md"):
        if mem_file.name in STRUCTURAL_MEMORIES:
            metadata[mem_file.name] = {"last_validated": now}
            validated += 1

    metadata_file.write_text(json.dumps(metadata, indent=2))
    print(f"✓ Validated {validated} structural memories")


def main():
    parser = argparse.ArgumentParser(description="Serena memory grooming tool")
    parser.add_argument(
        "--status", action="store_true", help="Show statistics (default)"
    )
    parser.add_argument(
        "--prune", action="store_true", help="Prune old session memories"
    )
    parser.add_argument(
        "--validate", action="store_true", help="Validate structural memories"
    )
    parser.add_argument("--force", action="store_true", help="Skip confirmation")

    args = parser.parse_args()

    memories_dir = find_serena_memories()
    if not memories_dir:
        print("❌ No .serena/memories directory found")
        sys.exit(1)

    if args.prune:
        prune_sessions(memories_dir, args.force)
    elif args.validate:
        validate_structural(memories_dir)
    else:
        show_status(memories_dir)


if __name__ == "__main__":
    main()
