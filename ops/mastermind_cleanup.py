#!/usr/bin/env python3
"""Clean up stale mastermind session state files.

Usage:
    mastermind_cleanup.py [--dry-run] [--max-age-hours N] [--verbose]

Options:
    --dry-run         Show what would be deleted without deleting
    --max-age-hours   Maximum age in hours before cleanup (default: 24)
    --verbose         Show details about each file
"""

import argparse
import sys
import time
from pathlib import Path

# State files location
STATE_DIR = Path.home() / ".claude" / "tmp"
STATE_PATTERN = "mastermind_*.json"

# Default max age: 24 hours
DEFAULT_MAX_AGE_HOURS = 24


def cleanup_stale_states(
    max_age_hours: int = DEFAULT_MAX_AGE_HOURS,
    dry_run: bool = False,
    verbose: bool = False,
) -> dict:
    """Remove mastermind state files older than max_age_hours.

    Args:
        max_age_hours: Delete files older than this many hours
        dry_run: If True, only report what would be deleted
        verbose: If True, print details about each file

    Returns:
        Dict with cleanup statistics
    """
    if not STATE_DIR.exists():
        return {"total": 0, "deleted": 0, "kept": 0, "errors": 0}

    now = time.time()

    stats = {"total": 0, "deleted": 0, "kept": 0, "errors": 0, "bytes_freed": 0}
    deleted_files = []

    for state_file in STATE_DIR.glob(STATE_PATTERN):
        stats["total"] += 1

        try:
            mtime = state_file.stat().st_mtime
            age_hours = (now - mtime) / 3600
            size = state_file.stat().st_size

            if age_hours > max_age_hours:
                if verbose:
                    print(f"  🗑️  {state_file.name} (age: {age_hours:.1f}h, size: {size}b)")

                if not dry_run:
                    state_file.unlink()
                    stats["bytes_freed"] += size

                stats["deleted"] += 1
                deleted_files.append(state_file.name)
            else:
                stats["kept"] += 1
                if verbose:
                    print(f"  ✓  {state_file.name} (age: {age_hours:.1f}h)")

        except OSError as e:
            stats["errors"] += 1
            if verbose:
                print(f"  ❌ {state_file.name}: {e}", file=sys.stderr)

    return stats


def main():
    parser = argparse.ArgumentParser(
        description="Clean up stale mastermind session state files"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be deleted without deleting",
    )
    parser.add_argument(
        "--max-age-hours",
        type=int,
        default=DEFAULT_MAX_AGE_HOURS,
        help=f"Maximum age in hours before cleanup (default: {DEFAULT_MAX_AGE_HOURS})",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Show details about each file"
    )

    args = parser.parse_args()

    print("🧹 Mastermind State Cleanup")
    print(f"   Directory: {STATE_DIR}")
    print(f"   Max age: {args.max_age_hours} hours")
    if args.dry_run:
        print("   Mode: DRY RUN (no files will be deleted)")
    print()

    stats = cleanup_stale_states(
        max_age_hours=args.max_age_hours,
        dry_run=args.dry_run,
        verbose=args.verbose,
    )

    print()
    print("📊 Results:")
    print(f"   Total files: {stats['total']}")
    print(f"   Deleted: {stats['deleted']}")
    print(f"   Kept: {stats['kept']}")
    if stats["errors"]:
        print(f"   Errors: {stats['errors']}")
    if stats["bytes_freed"]:
        print(f"   Freed: {stats['bytes_freed'] / 1024:.1f} KB")

    if args.dry_run and stats["deleted"]:
        print()
        print("💡 Run without --dry-run to actually delete files")


if __name__ == "__main__":
    main()
