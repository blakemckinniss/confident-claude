#!/usr/bin/env python3
"""
Bead Lifecycle Daemon

Background service that monitors agent↔bead assignments and auto-reverts
orphaned beads when agents crash or timeout.

Scan interval: 5 minutes
Stale threshold: 30 minutes (no heartbeat)
Stalled threshold: 60 minutes (marked as stalled)
Orphan threshold: 120 minutes (auto-reverted to open)

Logs to: ~/.claude/.beads/lifecycle.log

Usage:
    bead_lifecycle_daemon.py              # Run as daemon (blocking)
    bead_lifecycle_daemon.py --once       # Single scan then exit
    bead_lifecycle_daemon.py --status     # Show daemon status
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

# Configuration
SCAN_INTERVAL_SECONDS = 300  # 5 minutes
STALE_THRESHOLD_MINUTES = 30  # No heartbeat for 30 min = stale
STALLED_THRESHOLD_MINUTES = 60  # 60 min = marked stalled
ORPHAN_THRESHOLD_MINUTES = 120  # 120 min = auto-revert

LOG_FILE = Path.home() / ".claude" / ".beads" / "lifecycle.log"
PID_FILE = Path.home() / ".claude" / ".beads" / "lifecycle.pid"


def log(message: str, level: str = "INFO") -> None:
    """Log message to file and stdout."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] [{level}] {message}"
    print(line)

    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a") as f:
            f.write(line + "\n")
    except OSError:
        pass


def run_bd(*args: str) -> subprocess.CompletedProcess:
    """Run bd command."""
    return subprocess.run(["bd", *args], capture_output=True, text=True)


def revert_bead_to_open(bead_id: str) -> bool:
    """Revert a bead to open status via bd CLI."""
    result = run_bd("update", bead_id, "--status=open")
    return result.returncode == 0


def scan_and_process() -> dict[str, int]:
    """
    Scan for stale assignments and take action.

    Returns:
        Dict with counts: warnings, stalled, reverted
    """
    stats = {"warnings": 0, "stalled": 0, "reverted": 0, "errors": 0}

    # Get all active assignments
    active = get_active_assignments()
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
            log(f"Cannot parse timestamp for {bead_id}", "WARN")
            continue

        # Determine action based on elapsed time
        if elapsed_minutes > ORPHAN_THRESHOLD_MINUTES:
            # Auto-revert to open
            log(
                f"ORPHAN: {bead_id} (agent {agent_id}) - {elapsed_minutes:.0f}min idle, reverting to open"
            )
            if revert_bead_to_open(bead_id):
                release_bead(bead_id, status="timed_out")
                stats["reverted"] += 1
            else:
                log(f"Failed to revert {bead_id}", "ERROR")
                stats["errors"] += 1

        elif elapsed_minutes > STALLED_THRESHOLD_MINUTES:
            # Mark as stalled (warning, but don't revert yet)
            log(
                f"STALLED: {bead_id} (agent {agent_id}) - {elapsed_minutes:.0f}min idle"
            )
            stats["stalled"] += 1

        elif elapsed_minutes > STALE_THRESHOLD_MINUTES:
            # Warning only
            log(
                f"STALE: {bead_id} (agent {agent_id}) - {elapsed_minutes:.0f}min since heartbeat"
            )
            stats["warnings"] += 1

    return stats


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
        # Check if process exists
        os.kill(pid, 0)
        return True, pid
    except (ValueError, ProcessLookupError, PermissionError):
        # Stale PID file
        return False, None


def show_status() -> int:
    """Show daemon status."""
    running, pid = is_running()

    if running:
        print(f"✓ Daemon running (PID {pid})")
    else:
        print("✗ Daemon not running")

    # Show recent log entries
    if LOG_FILE.exists():
        print(f"\nRecent log ({LOG_FILE}):")
        try:
            lines = LOG_FILE.read_text().strip().split("\n")
            for line in lines[-10:]:
                print(f"  {line}")
        except OSError:
            print("  (unable to read log)")

    # Show active assignments
    active = get_active_assignments()
    print(f"\nActive assignments: {len(active)}")
    for a in active[:5]:
        print(f"  - {a.get('bead_id')}: agent {a.get('agent_session_id', '')[:8]}")

    return 0 if running else 1


def run_daemon() -> None:
    """Run the daemon loop."""
    running, pid = is_running()
    if running:
        print(f"Daemon already running (PID {pid})")
        sys.exit(1)

    write_pid()
    log("Daemon started")

    try:
        while True:
            stats = scan_and_process()

            total = stats["warnings"] + stats["stalled"] + stats["reverted"]
            if total > 0:
                log(
                    f"Scan complete: {stats['warnings']} warnings, {stats['stalled']} stalled, {stats['reverted']} reverted"
                )

            time.sleep(SCAN_INTERVAL_SECONDS)

    except KeyboardInterrupt:
        log("Daemon stopped (SIGINT)")
    finally:
        remove_pid()


def run_once() -> int:
    """Run a single scan and exit."""
    log("Running single scan")
    stats = scan_and_process()

    total = stats["warnings"] + stats["stalled"] + stats["reverted"]
    if total == 0:
        print("No issues found")
    else:
        print(
            f"Processed: {stats['warnings']} warnings, {stats['stalled']} stalled, {stats['reverted']} reverted"
        )

    return 0 if stats["errors"] == 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Bead lifecycle daemon - monitors and cleans up orphaned beads"
    )
    parser.add_argument("--once", action="store_true", help="Run single scan then exit")
    parser.add_argument("--status", action="store_true", help="Show daemon status")

    args = parser.parse_args()

    if args.status:
        return show_status()
    elif args.once:
        return run_once()
    else:
        run_daemon()
        return 0


if __name__ == "__main__":
    sys.exit(main())
