#!/usr/bin/env python3
"""
Serena Memory Lifecycle Management

Automates memory staleness detection, validation, and pruning for Serena projects.

Subcommands:
    status    - Show memory health overview
    stale     - Detect stale memories (referenced files changed)
    validate  - Check memory accuracy against codebase
    prune     - Remove/archive outdated memories
    refresh   - Auto-update structural memories (counts, lists)
    init      - Initialize memory metadata tracking

Usage:
    serena_memory_lifecycle.py status [--project PATH]
    serena_memory_lifecycle.py stale [--days N] [--project PATH]
    serena_memory_lifecycle.py validate [MEMORY_NAME] [--project PATH]
    serena_memory_lifecycle.py prune [--dry-run] [--project PATH]
    serena_memory_lifecycle.py refresh [--auto] [--project PATH]
    serena_memory_lifecycle.py init [--project PATH]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

# Memory metadata format (stored in .serena/memory_metadata.json)
# {
#   "memory_name.md": {
#     "created": "2024-12-13T10:00:00",
#     "last_validated": "2024-12-16T10:00:00",
#     "references": ["hooks/foo.py", "lib/bar.py"],
#     "checksums": {"hooks/foo.py": "abc123"},
#     "type": "structural|conceptual|procedural",
#     "auto_refresh": true/false
#   }
# }


def find_serena_root(start: Path | None = None) -> Path | None:
    """Find the .serena/ directory in current or parent directories."""
    cwd = start or Path.cwd()
    for parent in [cwd, *cwd.parents]:
        serena_dir = parent / ".serena"
        if serena_dir.is_dir():
            return parent
        if parent == Path.home() or parent == Path("/"):
            break
    return None


def get_metadata_path(project_root: Path) -> Path:
    """Get path to memory metadata file."""
    return project_root / ".serena" / "memory_metadata.json"


def load_metadata(project_root: Path) -> dict[str, Any]:
    """Load memory metadata, creating if doesn't exist."""
    meta_path = get_metadata_path(project_root)
    if meta_path.exists():
        return json.loads(meta_path.read_text())
    return {}


def save_metadata(project_root: Path, metadata: dict[str, Any]) -> None:
    """Save memory metadata."""
    meta_path = get_metadata_path(project_root)
    meta_path.write_text(json.dumps(metadata, indent=2, default=str))


def file_checksum(path: Path) -> str | None:
    """Compute MD5 checksum of file."""
    if not path.exists():
        return None
    return hashlib.md5(path.read_bytes()).hexdigest()[:12]


def extract_file_references(memory_content: str) -> list[str]:
    """Extract file paths referenced in memory content."""
    patterns = [
        r"`([a-zA-Z_/.-]+\.(?:py|ts|js|md|json|yml|yaml))`",  # backtick paths
        r"(?:^|\s)([a-zA-Z_/.-]+\.(?:py|ts|js|md|json|yml|yaml))(?:\s|$|:|\))",  # bare paths
        r"(?:hooks|ops|lib|commands)/[a-zA-Z_.-]+\.(?:py|md)",  # known dirs
    ]
    refs = set()
    for pattern in patterns:
        refs.update(re.findall(pattern, memory_content))
    return sorted(refs)


def get_git_file_changed(project_root: Path, file_path: str, since_days: int = 7) -> bool:
    """Check if file changed in git since N days ago."""
    try:
        since = (datetime.now() - timedelta(days=since_days)).strftime("%Y-%m-%d")
        result = subprocess.run(
            ["git", "log", "--since", since, "--oneline", "--", file_path],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=5,
        )
        return bool(result.stdout.strip())
    except Exception:
        return False


def analyze_memory(
    project_root: Path, memory_name: str, metadata: dict
) -> dict[str, Any]:
    """Analyze a single memory for staleness."""
    memories_dir = project_root / ".serena" / "memories"
    memory_path = memories_dir / memory_name

    if not memory_path.exists():
        return {"status": "missing", "memory": memory_name}

    content = memory_path.read_text()
    mtime = datetime.fromtimestamp(memory_path.stat().st_mtime)
    age_days = (datetime.now() - mtime).days

    # Extract references from content
    refs = extract_file_references(content)

    # Get metadata if exists
    meta = metadata.get(memory_name, {})
    stored_checksums = meta.get("checksums", {})

    # Check each reference for changes
    changed_refs = []
    for ref in refs:
        ref_path = project_root / ref
        if ref_path.exists():
            current_checksum = file_checksum(ref_path)
            stored_checksum = stored_checksums.get(ref, None)
            if stored_checksum and current_checksum != stored_checksum:
                changed_refs.append(ref)
            elif get_git_file_changed(project_root, ref, since_days=age_days):
                changed_refs.append(ref)

    # Determine staleness
    is_stale = bool(changed_refs) or age_days > 30

    return {
        "memory": memory_name,
        "status": "stale" if is_stale else "fresh",
        "age_days": age_days,
        "mtime": mtime.isoformat(),
        "references": refs,
        "changed_refs": changed_refs,
        "type": meta.get("type", "unknown"),
        "auto_refresh": meta.get("auto_refresh", False),
    }


def cmd_status(args: argparse.Namespace) -> int:
    """Show memory health overview."""
    project_root = find_serena_root(Path(args.project) if args.project else None)
    if not project_root:
        print("✗ No .serena/ directory found")
        return 1

    memories_dir = project_root / ".serena" / "memories"
    if not memories_dir.is_dir():
        print("✗ No memories directory found")
        return 1

    metadata = load_metadata(project_root)
    memories = sorted(memories_dir.glob("*.md"))

    print(f"📊 Serena Memory Status: {project_root.name}")
    print(f"   Memories: {len(memories)}")
    print(f"   Metadata tracked: {len(metadata)}")
    print()

    fresh_count = 0
    stale_count = 0
    unknown_count = 0

    for mem in memories:
        analysis = analyze_memory(project_root, mem.name, metadata)
        status = analysis["status"]
        age = analysis.get("age_days", "?")
        changed = len(analysis.get("changed_refs", []))

        if status == "fresh":
            icon = "✓"
            fresh_count += 1
        elif status == "stale":
            icon = "⚠"
            stale_count += 1
        else:
            icon = "?"
            unknown_count += 1

        extra = f" ({changed} refs changed)" if changed else ""
        print(f"   {icon} {mem.stem}: {age}d old{extra}")

    print()
    print(f"Summary: {fresh_count} fresh, {stale_count} stale, {unknown_count} unknown")

    if stale_count > 0:
        print("\n💡 Run `serena_memory_lifecycle.py stale` for details")
        print("💡 Run `serena_memory_lifecycle.py refresh --auto` to auto-update")

    return 0


def cmd_stale(args: argparse.Namespace) -> int:
    """Detect stale memories."""
    project_root = find_serena_root(Path(args.project) if args.project else None)
    if not project_root:
        print("✗ No .serena/ directory found")
        return 1

    memories_dir = project_root / ".serena" / "memories"
    metadata = load_metadata(project_root)
    memories = sorted(memories_dir.glob("*.md"))

    stale = []
    for mem in memories:
        analysis = analyze_memory(project_root, mem.name, metadata)
        if analysis["status"] == "stale":
            stale.append(analysis)

    if not stale:
        print("✓ All memories are fresh")
        return 0

    print(f"⚠ Found {len(stale)} stale memories:\n")

    for s in stale:
        print(f"📄 {s['memory']}")
        print(f"   Age: {s['age_days']} days")
        if s["changed_refs"]:
            print(f"   Changed files:")
            for ref in s["changed_refs"]:
                print(f"     - {ref}")
        print()

    print("💡 Actions:")
    print("   - `mcp__serena__read_memory` to review content")
    print("   - `mcp__serena__edit_memory` to update specific sections")
    print("   - `mcp__serena__delete_memory` to remove if obsolete")
    print("   - `serena_memory_lifecycle.py refresh --auto` to auto-update structural memories")

    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    """Validate memory accuracy."""
    project_root = find_serena_root(Path(args.project) if args.project else None)
    if not project_root:
        print("✗ No .serena/ directory found")
        return 1

    memories_dir = project_root / ".serena" / "memories"
    metadata = load_metadata(project_root)

    if args.memory:
        memories = [memories_dir / f"{args.memory}.md"]
        if not memories[0].exists():
            memories = [memories_dir / args.memory]
    else:
        memories = sorted(memories_dir.glob("*.md"))

    print(f"🔍 Validating {len(memories)} memories...\n")

    issues = []
    for mem in memories:
        if not mem.exists():
            issues.append({"memory": mem.name, "issue": "File not found"})
            continue

        content = mem.read_text()
        refs = extract_file_references(content)

        # Check if referenced files exist
        missing_refs = []
        for ref in refs:
            ref_path = project_root / ref
            if not ref_path.exists():
                missing_refs.append(ref)

        if missing_refs:
            issues.append({
                "memory": mem.name,
                "issue": "Missing references",
                "refs": missing_refs,
            })

        # Check for obvious outdated patterns
        outdated_patterns = [
            (r"TODO|FIXME|XXX", "Contains TODO markers"),
            (r"\d{4}-\d{2}-\d{2}", "Contains hardcoded dates"),
        ]
        for pattern, desc in outdated_patterns:
            if re.search(pattern, content):
                issues.append({"memory": mem.name, "issue": desc})

    if not issues:
        print("✓ All memories validated successfully")
        return 0

    print(f"⚠ Found {len(issues)} issues:\n")
    for issue in issues:
        print(f"📄 {issue['memory']}: {issue['issue']}")
        if "refs" in issue:
            for ref in issue["refs"]:
                print(f"     - {ref}")

    return 1


def cmd_prune(args: argparse.Namespace) -> int:
    """Remove/archive outdated memories."""
    project_root = find_serena_root(Path(args.project) if args.project else None)
    if not project_root:
        print("✗ No .serena/ directory found")
        return 1

    memories_dir = project_root / ".serena" / "memories"
    metadata = load_metadata(project_root)

    # Find candidates for pruning
    candidates = []
    for mem in sorted(memories_dir.glob("*.md")):
        analysis = analyze_memory(project_root, mem.name, metadata)

        # Prune criteria:
        # - Very old (>60 days) with no recent validation
        # - All references are missing
        # - Marked as deprecated in metadata

        refs = analysis.get("references", [])
        missing_refs = [r for r in refs if not (project_root / r).exists()]

        if len(refs) > 0 and len(missing_refs) == len(refs):
            candidates.append({
                "memory": mem.name,
                "reason": "All referenced files missing",
                "path": mem,
            })
        elif analysis.get("age_days", 0) > 60:
            meta = metadata.get(mem.name, {})
            last_validated = meta.get("last_validated")
            if not last_validated:
                candidates.append({
                    "memory": mem.name,
                    "reason": f"Old ({analysis['age_days']}d) and never validated",
                    "path": mem,
                })

    if not candidates:
        print("✓ No memories need pruning")
        return 0

    print(f"🗑️ Found {len(candidates)} prune candidates:\n")
    for c in candidates:
        print(f"   - {c['memory']}: {c['reason']}")

    if args.dry_run:
        print("\n💡 Dry run - no changes made")
        print("   Remove --dry-run to actually prune")
        return 0

    # Archive rather than delete
    archive_dir = project_root / ".serena" / "memories_archive"
    archive_dir.mkdir(exist_ok=True)

    for c in candidates:
        src = c["path"]
        dst = archive_dir / c["memory"]
        src.rename(dst)
        print(f"   Archived: {c['memory']}")

        # Remove from metadata
        if c["memory"] in metadata:
            del metadata[c["memory"]]

    save_metadata(project_root, metadata)
    print(f"\n✓ Archived {len(candidates)} memories to .serena/memories_archive/")

    return 0


def cmd_refresh(args: argparse.Namespace) -> int:
    """Auto-update structural memories."""
    project_root = find_serena_root(Path(args.project) if args.project else None)
    if not project_root:
        print("✗ No .serena/ directory found")
        return 1

    metadata = load_metadata(project_root)

    # Identify structural memories that can be auto-refreshed
    # These typically contain file counts, directory listings, etc.
    refreshable = [
        "codebase_structure",
        "lib_modules",
        "ops_tools",
        "slash_commands",
        "hook_registry",
    ]

    print("🔄 Checking refreshable memories...\n")

    needs_refresh = []
    for mem_name in refreshable:
        meta = metadata.get(f"{mem_name}.md", {})
        if meta.get("auto_refresh", True):  # Default to refreshable
            analysis = analyze_memory(project_root, f"{mem_name}.md", metadata)
            if analysis["status"] == "stale" or analysis.get("changed_refs"):
                needs_refresh.append(mem_name)
                print(f"   ⚠ {mem_name}: needs refresh")
            else:
                print(f"   ✓ {mem_name}: current")

    if not needs_refresh:
        print("\n✓ All structural memories are current")
        return 0

    if not args.auto:
        print(f"\n💡 {len(needs_refresh)} memories need refresh")
        print("   Run with --auto to generate refresh instructions")
        return 0

    print("\n📋 Refresh Instructions:\n")
    print("Run these MCP commands to refresh stale memories:\n")

    for mem_name in needs_refresh:
        print(f"# Refresh {mem_name}")
        print(f"# 1. Get current state:")
        if mem_name == "codebase_structure":
            print(f"mcp__serena__list_dir(relative_path='.', recursive=True)")
        elif mem_name == "lib_modules":
            print(f"mcp__serena__list_dir(relative_path='lib', recursive=True)")
        elif mem_name == "ops_tools":
            print(f"mcp__serena__list_dir(relative_path='ops', recursive=False)")
        elif mem_name == "slash_commands":
            print(f"mcp__serena__list_dir(relative_path='commands', recursive=False)")
        elif mem_name == "hook_registry":
            print(f"mcp__serena__find_symbol(name_path_pattern='register_*')")

        print(f"# 2. Update memory:")
        print(f"mcp__serena__edit_memory(memory_file_name='{mem_name}.md', ...)")
        print()

    # Update validation timestamps
    now = datetime.now().isoformat()
    for mem_name in refreshable:
        key = f"{mem_name}.md"
        if key not in metadata:
            metadata[key] = {}
        metadata[key]["last_validated"] = now

    save_metadata(project_root, metadata)

    return 0


def cmd_init(args: argparse.Namespace) -> int:
    """Initialize memory metadata tracking."""
    project_root = find_serena_root(Path(args.project) if args.project else None)
    if not project_root:
        print("✗ No .serena/ directory found")
        return 1

    memories_dir = project_root / ".serena" / "memories"
    if not memories_dir.is_dir():
        print("✗ No memories directory found")
        return 1

    metadata = load_metadata(project_root)
    memories = sorted(memories_dir.glob("*.md"))

    print(f"🔧 Initializing metadata for {len(memories)} memories...\n")

    now = datetime.now().isoformat()

    for mem in memories:
        content = mem.read_text()
        refs = extract_file_references(content)
        mtime = datetime.fromtimestamp(mem.stat().st_mtime)

        # Compute checksums for referenced files
        checksums = {}
        for ref in refs:
            ref_path = project_root / ref
            if ref_path.exists():
                checksums[ref] = file_checksum(ref_path)

        # Determine memory type
        mem_type = "unknown"
        if any(kw in mem.stem for kw in ["structure", "modules", "tools", "commands", "registry"]):
            mem_type = "structural"
        elif any(kw in mem.stem for kw in ["system", "conventions", "overview"]):
            mem_type = "conceptual"
        elif any(kw in mem.stem for kw in ["completion", "workflow", "hooks"]):
            mem_type = "procedural"

        metadata[mem.name] = {
            "created": mtime.isoformat(),
            "last_validated": now,
            "references": refs,
            "checksums": checksums,
            "type": mem_type,
            "auto_refresh": mem_type == "structural",
        }

        print(f"   ✓ {mem.stem}: {len(refs)} refs, type={mem_type}")

    save_metadata(project_root, metadata)
    print(f"\n✓ Metadata saved to {get_metadata_path(project_root)}")

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Serena memory lifecycle management"
    )
    parser.add_argument("--project", "-p", help="Project path (default: auto-detect)")
    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # status
    subparsers.add_parser("status", help="Show memory health overview")

    # stale
    stale_parser = subparsers.add_parser("stale", help="Detect stale memories")
    stale_parser.add_argument("--days", "-d", type=int, default=7, help="Days threshold")

    # validate
    validate_parser = subparsers.add_parser("validate", help="Validate memory accuracy")
    validate_parser.add_argument("memory", nargs="?", help="Specific memory to validate")

    # prune
    prune_parser = subparsers.add_parser("prune", help="Remove outdated memories")
    prune_parser.add_argument("--dry-run", action="store_true", help="Don't actually delete")

    # refresh
    refresh_parser = subparsers.add_parser("refresh", help="Auto-update structural memories")
    refresh_parser.add_argument("--auto", action="store_true", help="Generate refresh instructions")

    # init
    subparsers.add_parser("init", help="Initialize memory metadata")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 0

    commands = {
        "status": cmd_status,
        "stale": cmd_stale,
        "validate": cmd_validate,
        "prune": cmd_prune,
        "refresh": cmd_refresh,
        "init": cmd_init,
    }

    return commands[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
