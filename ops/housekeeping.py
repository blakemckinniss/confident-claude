#!/usr/bin/env python3
"""
The Housekeeper - Disk space management for .claude runtime directories

Manages retention policies for accumulating directories that session hooks don't touch:
- debug/: 7 days (heaviest accumulator - 1.2GB+)
- file-history/: 30 days
- session-env/: 14 days
- shell-snapshots/: 7 days
- todos/: 30 days

NOTE: This is DIFFERENT from session_cleanup.py (which only cleans .claude/tmp/)
and stop_cleanup.py (which checks for abandoned work, not disk space).

Usage:
    housekeeping.py              # Dry run - show what would be deleted
    housekeeping.py --execute    # Actually delete files
    housekeeping.py --status     # Show current disk usage
"""

import argparse
import shutil
import sys
import time
from pathlib import Path

CLAUDE_DIR = Path(__file__).parent.parent

# Retention policies in days
RETENTION_DAYS = {
    "debug": 7,
    "file-history": 30,
    "session-env": 14,
    "shell-snapshots": 7,
    "todos": 30,
}

# Mastermind state files cleanup (hours, not days - these accumulate fast)
MASTERMIND_STATE_MAX_HOURS = 24


def get_dir_size(path: Path) -> int:
    """Get total size of directory in bytes."""
    total = 0
    try:
        for entry in path.rglob("*"):
            if entry.is_file():
                try:
                    total += entry.stat().st_size
                except (OSError, PermissionError):
                    pass
    except (OSError, PermissionError):
        pass
    return total


def format_size(size_bytes: int) -> str:
    """Format bytes as human-readable string."""
    for unit in ["B", "KB", "MB", "GB"]:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


def get_age_days(path: Path) -> float:
    """Get age of file/directory in days based on mtime."""
    try:
        mtime = path.stat().st_mtime
        return (time.time() - mtime) / 86400
    except (OSError, PermissionError):
        return 0


def find_expired(target_dir: Path, max_days: int) -> list:
    """Find files/directories older than max_days."""
    expired = []
    if not target_dir.exists():
        return expired

    try:
        for entry in target_dir.iterdir():
            age = get_age_days(entry)
            if age > max_days:
                if entry.is_file():
                    size = entry.stat().st_size
                else:
                    size = get_dir_size(entry)
                expired.append((entry, age, size))
    except (OSError, PermissionError):
        pass

    return sorted(expired, key=lambda x: -x[2])


def delete_path(path: Path) -> bool:
    """Delete file or directory recursively."""
    try:
        if path.is_file():
            path.unlink()
        else:
            shutil.rmtree(path)
        return True
    except (OSError, PermissionError) as e:
        print(f"  Error deleting {path}: {e}", file=sys.stderr)
        return False


def show_status():
    """Show current disk usage of managed directories."""
    print("=== .claude Directory Status ===\n")

    total = 0
    for dirname, max_days in RETENTION_DAYS.items():
        target = CLAUDE_DIR / dirname
        if target.exists():
            size = get_dir_size(target)
            total += size

            try:
                items = list(target.iterdir())
                count = len(items)
            except (OSError, PermissionError):
                count = 0

            expired = find_expired(target, max_days)
            expired_size = sum(e[2] for e in expired)

            status = ""
            if expired:
                status = f" ({len(expired)} expired, {format_size(expired_size)} reclaimable)"

            print(
                f"{dirname:20} {format_size(size):>10}  ({count} items, {max_days}d retention){status}"
            )
        else:
            print(f"{dirname:20} {'N/A':>10}  (not found)")

    print(f"\n{'TOTAL':20} {format_size(total):>10}")


def cleanup_mastermind_states(execute: bool = False) -> tuple[int, int]:
    """Clean up old mastermind session state files.

    Returns (count, bytes) of files deleted/reclaimable.
    """
    state_dir = CLAUDE_DIR / "tmp"
    pattern = "mastermind_*.json"
    max_age_seconds = MASTERMIND_STATE_MAX_HOURS * 3600
    now = time.time()

    count = 0
    total_bytes = 0

    if not state_dir.exists():
        return 0, 0

    expired = []
    for f in state_dir.glob(pattern):
        try:
            age_seconds = now - f.stat().st_mtime
            if age_seconds > max_age_seconds:
                expired.append((f, age_seconds / 3600, f.stat().st_size))
        except OSError:
            pass

    if not expired:
        return 0, 0

    print(
        f"tmp/mastermind_*.json - {len(expired)} files older than {MASTERMIND_STATE_MAX_HOURS}h"
    )

    for path, age_hours, size in sorted(expired, key=lambda x: -x[2])[:5]:
        marker = "  "
        if execute:
            try:
                path.unlink()
                marker = "x "
                count += 1
                total_bytes += size
            except OSError:
                marker = "! "
        print(f"  {marker}{path.name} ({age_hours:.1f}h, {format_size(size)})")

    if len(expired) > 5:
        remaining = len(expired) - 5
        remaining_size = sum(e[2] for e in expired[5:])
        print(f"  ... and {remaining} more ({format_size(remaining_size)})")

        if execute:
            for path, _, size in expired[5:]:
                try:
                    path.unlink()
                    count += 1
                    total_bytes += size
                except OSError:
                    pass

    print()
    return count, total_bytes


def run_housekeeping(execute: bool = False):
    """Run housekeeping with optional execution."""
    mode = "EXECUTE" if execute else "DRY RUN"
    print(f"=== Housekeeping [{mode}] ===\n")

    total_reclaimable = 0
    total_deleted = 0

    # Clean mastermind state files first (accumulate fastest)
    mm_count, mm_bytes = cleanup_mastermind_states(execute)
    if execute:
        total_deleted += mm_bytes
    else:
        total_reclaimable += mm_bytes

    for dirname, max_days in RETENTION_DAYS.items():
        target = CLAUDE_DIR / dirname
        expired = find_expired(target, max_days)

        if not expired:
            continue

        dir_size = sum(e[2] for e in expired)
        total_reclaimable += dir_size

        print(
            f"{dirname}/ - {len(expired)} items older than {max_days} days ({format_size(dir_size)})"
        )

        for path, age, size in expired[:5]:
            marker = "  "
            if execute:
                if delete_path(path):
                    marker = "x "
                    total_deleted += size
                else:
                    marker = "! "
            print(f"  {marker}{path.name} ({age:.0f}d, {format_size(size)})")

        if len(expired) > 5:
            remaining = len(expired) - 5
            remaining_size = sum(e[2] for e in expired[5:])
            print(f"  ... and {remaining} more ({format_size(remaining_size)})")

            if execute:
                for path, _, size in expired[5:]:
                    if delete_path(path):
                        total_deleted += size

        print()

    if total_reclaimable == 0:
        print("Nothing to clean up!")
    else:
        if execute:
            print(f"Removed: {format_size(total_deleted)}")
        else:
            print(f"Reclaimable: {format_size(total_reclaimable)}")
            print("\nRun with --execute to delete these files")


def main():
    parser = argparse.ArgumentParser(
        description="Manage .claude runtime directory disk space"
    )
    parser.add_argument("--execute", action="store_true", help="Actually delete files")
    parser.add_argument("--status", action="store_true", help="Show disk usage only")
    args = parser.parse_args()

    if args.status:
        show_status()
    else:
        run_housekeeping(execute=args.execute)


if __name__ == "__main__":
    main()
