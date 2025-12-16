#!/usr/bin/env python3
"""
Bead Orphan Check

Manual utility to check for and optionally fix orphaned bead assignments.
Useful for quick diagnostics without running the full daemon.

Usage:
    bead_orphan_check.py              # Show orphan status
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

# Thresholds (same as daemon)
STALE_THRESHOLD_MINUTES = 30
STALLED_THRESHOLD_MINUTES = 60
ORPHAN_THRESHOLD_MINUTES = 120


def run_bd(*args: str) -> subprocess.CompletedProcess:
    """Run bd command."""
    return subprocess.run(["bd", *args], capture_output=True, text=True)


def revert_bead_to_open(bead_id: str) -> bool:
    """Revert a bead to open status."""
    result = run_bd("update", bead_id, "--status=open")
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Check for orphaned bead assignments")
    parser.add_argument(
        "--auto-fix",
        action="store_true",
        help="Automatically revert orphaned beads to open status",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Show detailed assignment info"
    )
    parser.add_argument(
        "--cleanup",
        type=int,
        metavar="DAYS",
        help="Clean up assignments older than N days",
    )

    args = parser.parse_args()

    # Handle cleanup
    if args.cleanup:
        removed = cleanup_old_assignments(args.cleanup)
        print(f"Removed {removed} assignments older than {args.cleanup} days")
        return 0

    # Get and categorize assignments
    active = get_active_assignments()

    if not active:
        print("✓ No active assignments")
        return 0

    categories = categorize_assignments(active)

    # Display results
    print(f"Active assignments: {len(active)}\n")

    if categories["healthy"]:
        print(f"✓ Healthy ({len(categories['healthy'])})")
        if args.verbose:
            for a in categories["healthy"]:
                print(f"  {format_assignment(a, args.verbose)}")
        print()

    if categories["stale"]:
        print(
            f"⚠ Stale ({len(categories['stale'])} - no heartbeat for {STALE_THRESHOLD_MINUTES}+ min)"
        )
        for a in categories["stale"]:
            print(f"  {format_assignment(a, args.verbose)}")
        print()

    if categories["stalled"]:
        print(
            f"⚠ Stalled ({len(categories['stalled'])} - idle for {STALLED_THRESHOLD_MINUTES}+ min)"
        )
        for a in categories["stalled"]:
            print(f"  {format_assignment(a, args.verbose)}")
        print()

    if categories["orphan"]:
        print(
            f"✗ Orphaned ({len(categories['orphan'])} - idle for {ORPHAN_THRESHOLD_MINUTES}+ min)"
        )
        for a in categories["orphan"]:
            print(f"  {format_assignment(a, args.verbose)}")
        print()

        if args.auto_fix:
            print("Auto-fixing orphans...")
            fixed = 0
            for a in categories["orphan"]:
                bead_id = a.get("bead_id", "")
                if bead_id and revert_bead_to_open(bead_id):
                    release_bead(bead_id, status="timed_out")
                    print(f"  ✓ Reverted {bead_id} to open")
                    fixed += 1
                else:
                    print(f"  ✗ Failed to revert {bead_id}")
            print(f"\nFixed {fixed}/{len(categories['orphan'])} orphans")
        else:
            print("Run with --auto-fix to revert orphans to open status")

    # Return status based on orphans
    return 1 if categories["orphan"] else 0


if __name__ == "__main__":
    sys.exit(main())
