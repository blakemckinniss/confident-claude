#!/usr/bin/env python3
"""
Bead Lifecycle Daemon

Background service that monitors agent↔bead assignments across ALL projects
and auto-reverts orphaned beads when agents crash or timeout.

Scan interval: 5 minutes
Stale threshold: 30 minutes (no heartbeat)
Stalled threshold: 60 minutes (marked as stalled)
Orphan threshold: 120 minutes (auto-reverted to open)

Logs to: ~/.claude/.beads/lifecycle.log (global log)

Usage:
    bead_lifecycle_daemon.py              # Run as daemon (blocking)
    bead_lifecycle_daemon.py --once       # Single scan then exit
    bead_lifecycle_daemon.py --status     # Show daemon status
    bead_lifecycle_daemon.py --project PATH  # Scan specific project only
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Add lib to path for agent_registry
sys.path.insert(0, str(Path.home() / ".claude" / "lib"))
from agent_registry import (
    release_bead,
    get_active_assignments,
)
from project_context import (
    get_all_project_roots,
    get_project_name,
    get_lifecycle_log,
)

# Configuration
SCAN_INTERVAL_SECONDS = 300  # 5 minutes
STALE_THRESHOLD_MINUTES = 30  # No heartbeat for 30 min = stale
STALLED_THRESHOLD_MINUTES = 60  # 60 min = marked stalled
ORPHAN_THRESHOLD_MINUTES = 120  # 120 min = auto-revert

# Global log for daemon status
GLOBAL_LOG_FILE = Path.home() / ".claude" / ".beads" / "lifecycle.log"
PID_FILE = Path.home() / ".claude" / ".beads" / "lifecycle.pid"


def log(message: str, level: str = "INFO", project_root: Path | None = None) -> None:
    """Log message to file and stdout."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] [{level}] {message}"
    print(line)

    # Write to global log
    try:
        GLOBAL_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(GLOBAL_LOG_FILE, "a") as f:
            f.write(line + "\n")
    except OSError:
        pass

    # Also write to project-specific log if provided
    if project_root:
        try:
            project_log = get_lifecycle_log(project_root)
            project_log.parent.mkdir(parents=True, exist_ok=True)
            with open(project_log, "a") as f:
                f.write(line + "\n")
        except OSError:
            pass


def run_bd(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    """Run bd command in specified directory."""
    return subprocess.run(
        ["bd", *args],
        capture_output=True,
        text=True,
        cwd=cwd,
    )


def revert_bead_to_open(bead_id: str, project_root: Path | None = None) -> bool:
    """Revert a bead to open status via bd CLI."""
    result = run_bd("update", bead_id, "--status=open", cwd=project_root)
    return result.returncode == 0


def scan_project(project_root: Path) -> dict[str, int]:
    """
    Scan a single project for stale assignments.

    Returns:
        Dict with counts: warnings, stalled, reverted, errors
    """
    stats = {"warnings": 0, "stalled": 0, "reverted": 0, "errors": 0}
    project_name = get_project_name(project_root)

    # Get all active assignments for this project
    active = get_active_assignments(project_root)
    if not active:
        return stats

    now = datetime.now(timezone.utc)

    for assignment in active:
        bead_id = assignment.get("bead_id", "")
        agent_id = assignment.get("agent_session_id", "")[:8]

        # Calculate elapsed time
        last_hb = assignment.get("last_heartbeat", assignment.get("claimed_at", ""))
        if not last_hb:
            continue

        try:
            hb_time = datetime.fromisoformat(last_hb.replace("Z", "+00:00"))
            elapsed_minutes = (now - hb_time).total_seconds() / 60
        except (ValueError, TypeError):
            log(
                f"[{project_name}] Cannot parse timestamp for {bead_id}",
                "WARN",
                project_root,
            )
            continue

        # Determine action based on elapsed time
        if elapsed_minutes > ORPHAN_THRESHOLD_MINUTES:
            # Auto-revert to open
            log(
                f"[{project_name}] ORPHAN: {bead_id} (agent {agent_id}) - {elapsed_minutes:.0f}min idle, reverting",
                "INFO",
                project_root,
            )
            if revert_bead_to_open(bead_id, project_root):
                release_bead(bead_id, status="timed_out", project_root=project_root)
                stats["reverted"] += 1
            else:
                log(
                    f"[{project_name}] Failed to revert {bead_id}",
                    "ERROR",
                    project_root,
                )
                stats["errors"] += 1

        elif elapsed_minutes > STALLED_THRESHOLD_MINUTES:
            log(
                f"[{project_name}] STALLED: {bead_id} (agent {agent_id}) - {elapsed_minutes:.0f}min idle",
                "WARN",
                project_root,
            )
            stats["stalled"] += 1

        elif elapsed_minutes > STALE_THRESHOLD_MINUTES:
            log(
                f"[{project_name}] STALE: {bead_id} (agent {agent_id}) - {elapsed_minutes:.0f}min since heartbeat",
                "WARN",
                project_root,
            )
            stats["warnings"] += 1

    return stats


def scan_all_projects() -> dict[str, int]:
    """Scan all discovered projects for stale assignments."""
    totals = {"warnings": 0, "stalled": 0, "reverted": 0, "errors": 0, "projects": 0}

    for project_root in get_all_project_roots():
        stats = scan_project(project_root)
        totals["warnings"] += stats["warnings"]
        totals["stalled"] += stats["stalled"]
        totals["reverted"] += stats["reverted"]
        totals["errors"] += stats["errors"]
        totals["projects"] += 1

    return totals


def write_pid() -> None:
    """Write PID file for status checking."""
    PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(str(os.getpid()))


def remove_pid() -> None:
    """Remove PID file on exit."""
    try:
        PID_FILE.unlink()
    except OSError:
        pass


def is_running() -> tuple[bool, int | None]:
    """Check if daemon is already running."""
    if not PID_FILE.exists():
        return False, None

    try:
        pid = int(PID_FILE.read_text().strip())
        os.kill(pid, 0)
        return True, pid
    except (ValueError, ProcessLookupError, PermissionError):
        return False, None


def show_status() -> int:
    """Show daemon status and all project assignments."""
    running, pid = is_running()

    if running:
        print(f"✓ Daemon running (PID {pid})")
    else:
        print("✗ Daemon not running")

    # Show recent global log entries
    if GLOBAL_LOG_FILE.exists():
        print(f"\nRecent log ({GLOBAL_LOG_FILE}):")
        try:
            lines = GLOBAL_LOG_FILE.read_text().strip().split("\n")
            for line in lines[-10:]:
                print(f"  {line}")
        except OSError:
            print("  (unable to read log)")

    # Show all projects and their assignments
    projects = get_all_project_roots()
    print(f"\nDiscovered projects: {len(projects)}")

    total_active = 0
    for project_root in projects:
        active = get_active_assignments(project_root)
        name = get_project_name(project_root)
        if active:
            print(f"\n  {name} ({project_root}): {len(active)} active")
            for a in active[:3]:
                print(
                    f"    - {a.get('bead_id')}: agent {a.get('agent_session_id', '')[:8]}"
                )
            if len(active) > 3:
                print(f"    ... and {len(active) - 3} more")
            total_active += len(active)
        else:
            print(f"\n  {name}: no active assignments")

    print(f"\nTotal active assignments: {total_active}")
    return 0 if running else 1


def run_daemon() -> None:
    """Run the daemon loop."""
    running, pid = is_running()
    if running:
        print(f"Daemon already running (PID {pid})")
        sys.exit(1)

    write_pid()
    log("Daemon started - scanning all projects")

    try:
        while True:
            stats = scan_all_projects()

            total = stats["warnings"] + stats["stalled"] + stats["reverted"]
            if total > 0:
                log(
                    f"Scan complete ({stats['projects']} projects): "
                    f"{stats['warnings']} warnings, {stats['stalled']} stalled, {stats['reverted']} reverted"
                )

            time.sleep(SCAN_INTERVAL_SECONDS)

    except KeyboardInterrupt:
        log("Daemon stopped (SIGINT)")
    finally:
        remove_pid()


def run_once(project_root: Path | None = None) -> int:
    """Run a single scan and exit."""
    if project_root:
        log(f"Running single scan for {get_project_name(project_root)}")
        stats = scan_project(project_root)
        stats["projects"] = 1
    else:
        log("Running single scan for all projects")
        stats = scan_all_projects()

    total = stats["warnings"] + stats["stalled"] + stats["reverted"]
    if total == 0:
        print(f"No issues found across {stats.get('projects', 1)} project(s)")
    else:
        print(
            f"Processed ({stats.get('projects', 1)} projects): "
            f"{stats['warnings']} warnings, {stats['stalled']} stalled, {stats['reverted']} reverted"
        )

    return 0 if stats["errors"] == 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Bead lifecycle daemon - monitors and cleans up orphaned beads across all projects"
    )
    parser.add_argument("--once", action="store_true", help="Run single scan then exit")
    parser.add_argument("--status", action="store_true", help="Show daemon status")
    parser.add_argument("--project", type=Path, help="Scan specific project only")

    args = parser.parse_args()

    if args.status:
        return show_status()
    elif args.once:
        return run_once(args.project)
    else:
        run_daemon()
        return 0


if __name__ == "__main__":
    sys.exit(main())
