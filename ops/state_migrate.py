#!/usr/bin/env python3
"""
State Migration Helper - Migrate global state to current project.

Usage:
    state_migrate.py status    # Show migration status
    state_migrate.py migrate   # Copy global state to current project
    state_migrate.py cleanup   # Archive old global state file
"""

import argparse
import json
import shutil
import sys
from pathlib import Path
from datetime import datetime

# Add lib to path
LIB_DIR = Path(__file__).resolve().parent.parent / "lib"
sys.path.insert(0, str(LIB_DIR))

from _session_constants import (
    MEMORY_DIR,
    STATE_FILE,
    get_project_state_file,
)
from project_detector import detect_project


def cmd_status(args):
    """Show migration status."""
    global_file = STATE_FILE
    ctx = detect_project()
    project_file = get_project_state_file()

    print(f"📍 Current project: {ctx.project_name} ({ctx.project_id})")
    print(f"   Type: {ctx.project_type}")
    print(f"   Root: {ctx.root_path}")
    print()

    print(f"📂 Global state file: {global_file}")
    if global_file.exists():
        size = global_file.stat().st_size
        mtime = datetime.fromtimestamp(global_file.stat().st_mtime)
        print(f"   ✓ Exists ({size:,} bytes, modified {mtime:%Y-%m-%d %H:%M})")

        # Show key stats from global state
        try:
            with open(global_file) as f:
                data = json.load(f)
            print(f"   Session: {data.get('session_id', 'unknown')}")
            print(f"   Turn count: {data.get('turn_count', 0)}")
            print(f"   Confidence: {data.get('confidence', 'unknown')}")
            print(f"   Files read: {len(data.get('files_read', []))}")
            print(f"   Files edited: {len(data.get('files_edited', []))}")
        except (json.JSONDecodeError, IOError):
            print("   ⚠ Could not read state data")
    else:
        print("   ✗ Does not exist (already cleaned up or never created)")
    print()

    print(f"📂 Project state file: {project_file}")
    if project_file.exists():
        size = project_file.stat().st_size
        mtime = datetime.fromtimestamp(project_file.stat().st_mtime)
        print(f"   ✓ Exists ({size:,} bytes, modified {mtime:%Y-%m-%d %H:%M})")
    else:
        print("   ✗ Does not exist (will be created on first use)")
    print()

    # Recommendations
    if global_file.exists() and not project_file.exists():
        print("💡 Recommendation: Run 'migrate' to copy global state to this project")
    elif global_file.exists() and project_file.exists():
        print("💡 Recommendation: Run 'cleanup' to archive the old global state")
    elif not global_file.exists():
        print("✓ Global state already cleaned up. Project isolation is active.")


def cmd_migrate(args):
    """Migrate global state to current project."""
    global_file = STATE_FILE
    ctx = detect_project()
    project_file = get_project_state_file()

    if not global_file.exists():
        print("⚠ No global state file to migrate")
        return 1

    if project_file.exists() and not args.force:
        print(f"⚠ Project state already exists: {project_file}")
        print("  Use --force to overwrite")
        return 1

    # Copy global state to project
    project_file.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(global_file, project_file)

    print(f"✓ Migrated global state to: {project_file}")
    print(f"  Project: {ctx.project_name} ({ctx.project_id})")

    if args.cleanup:
        return cmd_cleanup(args)
    else:
        print("\n💡 Run 'cleanup' to archive the old global state file")

    return 0


def cmd_cleanup(args):
    """Archive old global state file."""
    global_file = STATE_FILE

    if not global_file.exists():
        print("✓ Global state file already cleaned up")
        return 0

    # Archive to memory/_archive/
    archive_dir = MEMORY_DIR / "_archive"
    archive_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    archive_path = archive_dir / f"session_state_v3_{timestamp}.json"

    shutil.move(str(global_file), str(archive_path))

    print(f"✓ Archived global state to: {archive_path}")
    print("  Project isolation is now fully active.")

    # Also clean up the old lock file if it exists
    old_lock = MEMORY_DIR / "session_state.lock"
    if old_lock.exists():
        old_lock.unlink()
        print(f"✓ Removed old lock file: {old_lock}")

    return 0


def main():
    parser = argparse.ArgumentParser(
        description="State migration helper for project isolation"
    )
    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # status
    status_parser = subparsers.add_parser("status", help="Show migration status")
    status_parser.set_defaults(func=cmd_status)

    # migrate
    migrate_parser = subparsers.add_parser("migrate", help="Migrate global state to current project")
    migrate_parser.add_argument("--force", "-f", action="store_true", help="Overwrite existing project state")
    migrate_parser.add_argument("--cleanup", "-c", action="store_true", help="Also cleanup global state after migration")
    migrate_parser.set_defaults(func=cmd_migrate)

    # cleanup
    cleanup_parser = subparsers.add_parser("cleanup", help="Archive old global state file")
    cleanup_parser.set_defaults(func=cmd_cleanup)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    return args.func(args)


if __name__ == "__main__":
    sys.exit(main() or 0)
