#!/usr/bin/env python3
"""
Bead Orphan Check

Manual utility to check for and optionally fix orphaned bead assignments.
Scans current project or all discovered projects.

Usage:
    bead_orphan_check.py              # Check current project
    bead_orphan_check.py --all        # Check all projects
    bead_orphan_check.py --auto-fix   # Auto-revert orphaned beads
    bead_orphan_check.py --verbose    # Show all assignments
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# Add lib to path
sys.path.insert(0, str(Path.home() / ".claude" / "lib"))
from agent_registry import (
    get_active_assignments,
    release_bead,
    cleanup_old_assignments,
)
from project_context import (
    find_project_root,
    get_all_project_roots,
    get_project_name,
    ProjectNotFoundError,
)

# Thresholds (same as daemon)
STALE_THRESHOLD_MINUTES = 30
STALLED_THRESHOLD_MINUTES = 60
ORPHAN_THRESHOLD_MINUTES = 120


def run_bd(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    """Run bd command."""
    return subprocess.run(["bd", *args], capture_output=True, text=True, cwd=cwd)


def revert_bead_to_open(bead_id: str, project_root: Path | None = None) -> bool:
    """Revert a bead to open status."""
    result = run_bd("update", bead_id, "--status=open", cwd=project_root)
    return result.returncode == 0


def categorize_assignments(active: list[dict]) -> dict[str, list[dict]]:
    """Categorize assignments by staleness."""
    now = datetime.now(timezone.utc)

    categories = {
        "healthy": [],
        "stale": [],
        "stalled": [],
        "orphan": [],
    }

    for assignment in active:
        last_hb = assignment.get("last_heartbeat", assignment.get("claimed_at", ""))
        if not last_hb:
            categories["orphan"].append(assignment)
            continue

        try:
            hb_time = datetime.fromisoformat(last_hb.replace("Z", "+00:00"))
            elapsed = (now - hb_time).total_seconds() / 60
            assignment["_elapsed_minutes"] = elapsed
        except (ValueError, TypeError):
            categories["orphan"].append(assignment)
            continue

        if elapsed > ORPHAN_THRESHOLD_MINUTES:
            categories["orphan"].append(assignment)
        elif elapsed > STALLED_THRESHOLD_MINUTES:
            categories["stalled"].append(assignment)
        elif elapsed > STALE_THRESHOLD_MINUTES:
            categories["stale"].append(assignment)
        else:
            categories["healthy"].append(assignment)

    return categories


def format_assignment(a: dict, verbose: bool = False) -> str:
    """Format an assignment for display."""
    bead_id = a.get("bead_id", "?")
    agent_id = a.get("agent_session_id", "?")[:8]
    elapsed = a.get("_elapsed_minutes", 0)
    prompt = a.get("prompt_snippet", "")[:40]

    base = f"{bead_id} (agent {agent_id}) - {elapsed:.0f}min"
    if verbose and prompt:
        base += f"\n    └─ {prompt}..."

    return base


def check_project(
    project_root: Path,
    auto_fix: bool = False,
    verbose: bool = False,
) -> dict[str, int]:
    """Check a single project for orphaned assignments."""
    stats = {"healthy": 0, "stale": 0, "stalled": 0, "orphan": 0, "fixed": 0}
    project_name = get_project_name(project_root)

    active = get_active_assignments(project_root)
    if not active:
        return stats

    categories = categorize_assignments(active)

    print(f"\n📁 {project_name} ({project_root})")
    print(f"   Active assignments: {len(active)}")

    if categories["healthy"]:
        stats["healthy"] = len(categories["healthy"])
        print(f"   ✓ Healthy: {len(categories['healthy'])}")
        if verbose:
            for a in categories["healthy"]:
                print(f"     {format_assignment(a, verbose)}")

    if categories["stale"]:
        stats["stale"] = len(categories["stale"])
        print(
            f"   ⚠ Stale ({STALE_THRESHOLD_MINUTES}+ min): {len(categories['stale'])}"
        )
        for a in categories["stale"]:
            print(f"     {format_assignment(a, verbose)}")

    if categories["stalled"]:
        stats["stalled"] = len(categories["stalled"])
        print(
            f"   ⚠ Stalled ({STALLED_THRESHOLD_MINUTES}+ min): {len(categories['stalled'])}"
        )
        for a in categories["stalled"]:
            print(f"     {format_assignment(a, verbose)}")

    if categories["orphan"]:
        stats["orphan"] = len(categories["orphan"])
        print(
            f"   ✗ Orphaned ({ORPHAN_THRESHOLD_MINUTES}+ min): {len(categories['orphan'])}"
        )
        for a in categories["orphan"]:
            print(f"     {format_assignment(a, verbose)}")

        if auto_fix:
            for a in categories["orphan"]:
                bead_id = a.get("bead_id", "")
                if bead_id and revert_bead_to_open(bead_id, project_root):
                    release_bead(bead_id, status="timed_out", project_root=project_root)
                    print(f"     → Reverted {bead_id} to open")
                    stats["fixed"] += 1
                else:
                    print(f"     → Failed to revert {bead_id}")

    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description="Check for orphaned bead assignments")
    parser.add_argument(
        "--all",
        "-a",
        action="store_true",
        help="Check all discovered projects",
    )
    parser.add_argument(
        "--auto-fix",
        action="store_true",
        help="Automatically revert orphaned beads to open status",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show detailed assignment info",
    )
    parser.add_argument(
        "--cleanup",
        type=int,
        metavar="DAYS",
        help="Clean up assignments older than N days",
    )
    parser.add_argument(
        "--project",
        "-p",
        type=Path,
        help="Check specific project path",
    )

    args = parser.parse_args()

    # Determine which projects to check
    if args.project:
        projects = [args.project]
    elif args.all:
        projects = get_all_project_roots()
    else:
        # Current project only
        try:
            projects = [find_project_root()]
        except ProjectNotFoundError:
            print("✗ No project found in current directory")
            print(
                "  Use --all to scan all projects, or --project PATH for specific project"
            )
            return 1

    if not projects:
        print("No projects found")
        return 0

    # Handle cleanup
    if args.cleanup:
        total_removed = 0
        for project_root in projects:
            removed = cleanup_old_assignments(args.cleanup, project_root)
            if removed > 0:
                print(
                    f"Removed {removed} old assignments from {get_project_name(project_root)}"
                )
            total_removed += removed
        print(
            f"Total removed: {total_removed} assignments older than {args.cleanup} days"
        )
        return 0

    # Check each project
    totals = {"healthy": 0, "stale": 0, "stalled": 0, "orphan": 0, "fixed": 0}

    print(f"Checking {len(projects)} project(s)...")

    for project_root in projects:
        stats = check_project(project_root, args.auto_fix, args.verbose)
        for key in totals:
            totals[key] += stats[key]

    # Summary
    print(f"\n{'─' * 40}")
    print(
        f"Summary: {totals['healthy']} healthy, {totals['stale']} stale, "
        f"{totals['stalled']} stalled, {totals['orphan']} orphan"
    )

    if totals["fixed"]:
        print(f"Fixed: {totals['fixed']} orphans reverted to open")
    elif totals["orphan"] and not args.auto_fix:
        print("\nRun with --auto-fix to revert orphans to open status")

    return 1 if totals["orphan"] > totals["fixed"] else 0


if __name__ == "__main__":
    sys.exit(main())
