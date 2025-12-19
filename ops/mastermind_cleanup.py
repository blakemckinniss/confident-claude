#!/usr/bin/env python3
"""Clean up stale mastermind session state files.

Usage:
    mastermind_cleanup.py [--dry-run] [--max-age-hours N] [--verbose]

Options:
    --dry-run         Show what would be deleted without deleting
    --max-age-hours   Maximum age in hours before cleanup (default: 168 / 7 days)
    --verbose         Show details about each file
"""

import argparse
import shutil
import sys
import time
from pathlib import Path

# State files location
STATE_DIR = Path.home() / ".claude" / "tmp"
MASTERMIND_DIR = STATE_DIR / "mastermind"
LEGACY_PATTERN = "mastermind_*.json"

# Default max age: 7 days (168 hours)
DEFAULT_MAX_AGE_HOURS = 168


def cleanup_stale_states(
    max_age_hours: int = DEFAULT_MAX_AGE_HOURS,
    dry_run: bool = False,
    verbose: bool = False,
) -> dict:
    """Remove mastermind state files older than max_age_hours.

    Handles both:
    - Legacy: ~/.claude/tmp/mastermind_*.json (flat files)
    - Current: ~/.claude/tmp/mastermind/{project}/{session}/state.json (nested dirs)

    Args:
        max_age_hours: Delete files older than this many hours
        dry_run: If True, only report what would be deleted
        verbose: If True, print details about each file

    Returns:
        Dict with cleanup statistics
    """
    now = time.time()
    stats = {
        "total": 0,
        "deleted": 0,
        "kept": 0,
        "errors": 0,
        "bytes_freed": 0,
        "dirs_removed": 0,
    }

    # Clean legacy flat files
    if STATE_DIR.exists():
        for state_file in STATE_DIR.glob(LEGACY_PATTERN):
            stats["total"] += 1
            try:
                mtime = state_file.stat().st_mtime
                age_hours = (now - mtime) / 3600
                size = state_file.stat().st_size

                if age_hours > max_age_hours:
                    if verbose:
                        print(
                            f"  🗑️  [legacy] {state_file.name} (age: {age_hours:.1f}h)"
                        )
                    if not dry_run:
                        state_file.unlink()
                        stats["bytes_freed"] += size
                    stats["deleted"] += 1
                else:
                    stats["kept"] += 1
                    if verbose:
                        print(
                            f"  ✓  [legacy] {state_file.name} (age: {age_hours:.1f}h)"
                        )
            except OSError as e:
                stats["errors"] += 1
                if verbose:
                    print(f"  ❌ {state_file.name}: {e}", file=sys.stderr)

    # Clean new nested directory structure
    if MASTERMIND_DIR.exists():
        for project_dir in MASTERMIND_DIR.iterdir():
            if not project_dir.is_dir():
                continue

            for session_dir in project_dir.iterdir():
                if not session_dir.is_dir():
                    continue

                state_file = session_dir / "state.json"
                if not state_file.exists():
                    # Empty session dir - clean it up
                    if not dry_run:
                        try:
                            session_dir.rmdir()
                            stats["dirs_removed"] += 1
                        except OSError:
                            pass
                    continue

                stats["total"] += 1
                try:
                    mtime = state_file.stat().st_mtime
                    age_hours = (now - mtime) / 3600
                    size = state_file.stat().st_size

                    rel_path = f"{project_dir.name}/{session_dir.name}"

                    if age_hours > max_age_hours:
                        if verbose:
                            print(f"  🗑️  {rel_path} (age: {age_hours:.1f}h)")
                        if not dry_run:
                            shutil.rmtree(session_dir)
                            stats["bytes_freed"] += size
                            stats["dirs_removed"] += 1
                        stats["deleted"] += 1
                    else:
                        stats["kept"] += 1
                        if verbose:
                            print(f"  ✓  {rel_path} (age: {age_hours:.1f}h)")
                except OSError as e:
                    stats["errors"] += 1
                    if verbose:
                        print(f"  ❌ {rel_path}: {e}", file=sys.stderr)

            # Clean empty project dirs
            if not dry_run:
                try:
                    if project_dir.exists() and not any(project_dir.iterdir()):
                        project_dir.rmdir()
                        stats["dirs_removed"] += 1
                except OSError:
                    pass

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
    print(f"   Total sessions: {stats['total']}")
    print(f"   Deleted: {stats['deleted']}")
    print(f"   Kept: {stats['kept']}")
    if stats["dirs_removed"]:
        print(f"   Dirs removed: {stats['dirs_removed']}")
    if stats["errors"]:
        print(f"   Errors: {stats['errors']}")
    if stats["bytes_freed"]:
        print(f"   Freed: {stats['bytes_freed'] / 1024:.1f} KB")

    if args.dry_run and stats["deleted"]:
        print()
        print("💡 Run without --dry-run to actually delete files")


if __name__ == "__main__":
    main()
