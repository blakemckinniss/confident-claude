#!/usr/bin/env python3
"""
Bead Release: Wrapper for Task agents to release beads with lifecycle tracking.

Usage:
    bead_release.py <bead_id> [--status completed|abandoned]

This script:
1. Runs: bd close <bead_id>
2. Updates the agent_registry to mark assignment complete
3. Fires observation to claude-mem (via bd_bridge)

Task agents should use this instead of raw `bd close`.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

# Add lib to path
sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

from agent_registry import release_bead, get_assignment_for_bead


def get_bead_details(bead_id: str) -> dict | None:
    """Get bead details from bd show."""
    result = subprocess.run(
        ["bd", "show", bead_id, "--json"],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0 and result.stdout.strip():
        try:
            data = json.loads(result.stdout)
            if isinstance(data, list) and len(data) > 0:
                return data[0]
            elif isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            return None
    return None


def fire_observation_to_mem(bead_id: str, bead: dict, status: str) -> None:
    """Fire observation to claude-mem via bridge."""
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        from bd_bridge import fire_observation

        fire_observation(
            tool_name="BeadsClose",
            tool_input={"id": bead_id},
            tool_response={
                "status": status,
                "id": bead_id,
                "title": bead.get("title", ""),
                "issue_type": bead.get("issue_type", bead.get("type", "task")),
            },
        )
    except ImportError:
        # Bridge not available, observation skipped silently
        return


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Release a bead with lifecycle tracking"
    )
    parser.add_argument("bead_id", help="Bead ID to release")
    parser.add_argument(
        "--status",
        "-s",
        choices=["completed", "abandoned"],
        default="completed",
        help="Release status (default: completed)",
    )
    parser.add_argument(
        "--reason", "-r", default="", help="Reason for abandonment (if abandoned)"
    )

    args = parser.parse_args()

    # 1. Check if we have an assignment for this bead
    assignment = get_assignment_for_bead(args.bead_id)
    agent_id = assignment.get("agent_session_id") if assignment else None

    # 2. Get bead details before closing
    bead = get_bead_details(args.bead_id)
    if not bead:
        print(f"⚠️ Bead not found (may already be closed): {args.bead_id}", file=sys.stderr)

    # 3. Run bd close
    result = subprocess.run(
        ["bd", "close", args.bead_id],
        capture_output=True,
        text=True,
    )

    # Output bd result
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)

    # 4. Update registry even if bd close failed (bead might already be closed)
    released = release_bead(
        bead_id=args.bead_id,
        agent_session_id=agent_id,
        status=args.status,
    )

    if released:
        print(f"  Registry updated: {args.status}")
    elif assignment:
        print("  Registry: assignment already released")

    # 5. Fire observation via bridge (if bd close succeeded and we have bead info)
    if result.returncode == 0 and bead:
        fire_observation_to_mem(args.bead_id, bead, args.status)

    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
