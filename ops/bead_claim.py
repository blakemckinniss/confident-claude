#!/usr/bin/env python3
"""
Bead Claim: Wrapper for Task agents to claim beads with lifecycle tracking.

Usage:
    bead_claim.py <bead_id> [--prompt "snippet"] [--project PATH]

This script:
1. Detects project context (or uses explicit --project)
2. Validates the bead exists and is claimable
3. Runs: bd update <bead_id> --status=in_progress
4. Records the claim in project-local agent_registry
5. Fires observation to claude-mem (via bd_bridge)

Task agents should use this instead of raw `bd update --status=in_progress`.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

# Add lib to path
sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

from agent_registry import claim_bead, get_assignment_for_bead, get_timeout_for_type
from project_context import find_project_root, get_project_name, ProjectNotFoundError


def get_bead_details(bead_id: str, project_root: Path | None = None) -> dict | None:
    """Get bead details from bd show."""
    result = subprocess.run(
        ["bd", "show", bead_id, "--json"],
        capture_output=True,
        text=True,
        cwd=project_root,
    )
    if result.returncode == 0 and result.stdout.strip():
        try:
            data = json.loads(result.stdout)
            if isinstance(data, list) and len(data) > 0:
                return data[0]
            elif isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass
    return None


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Claim a bead with lifecycle tracking (project-aware)"
    )
    parser.add_argument("bead_id", help="Bead ID to claim")
    parser.add_argument("--prompt", "-p", default="", help="Prompt snippet for context")
    parser.add_argument(
        "--agent-id", default=None, help="Agent session ID (auto-generated if omitted)"
    )
    parser.add_argument("--parent-id", default=None, help="Parent session ID")
    parser.add_argument(
        "--project", type=Path, help="Project root (auto-detected if omitted)"
    )

    args = parser.parse_args()

    # 0. Detect project context
    try:
        project_root = args.project or find_project_root()
        project_name = get_project_name(project_root)
    except ProjectNotFoundError:
        print(
            "❌ No project found. Run from project directory or use --project",
            file=sys.stderr,
        )
        return 1

    # 1. Check if bead exists
    bead = get_bead_details(args.bead_id, project_root)
    if not bead:
        print(f"❌ Bead not found: {args.bead_id}", file=sys.stderr)
        return 1

    # 2. Check if already claimed by another agent
    existing = get_assignment_for_bead(args.bead_id, project_root)
    if existing:
        print(
            f"⚠️ Bead {args.bead_id} already claimed by agent {existing.get('agent_session_id')}",
            file=sys.stderr,
        )
        # Don't fail - might be resuming same bead

    # 3. Check bead status
    status = bead.get("status", "")
    if status == "closed":
        print(f"❌ Bead {args.bead_id} is already closed", file=sys.stderr)
        return 1

    # 4. Run bd update to claim (in project directory)
    result = subprocess.run(
        ["bd", "update", args.bead_id, "--status=in_progress"],
        capture_output=True,
        text=True,
        cwd=project_root,
    )

    if result.returncode != 0:
        print("❌ Failed to update bead status", file=sys.stderr)
        if result.stderr:
            print(result.stderr, file=sys.stderr)
        return result.returncode

    # 5. Record claim in project-local registry
    issue_type = bead.get("issue_type", bead.get("type", "task"))
    timeout = get_timeout_for_type(issue_type)

    assignment = claim_bead(
        bead_id=args.bead_id,
        agent_session_id=args.agent_id,
        parent_session_id=args.parent_id or os.environ.get("CLAUDE_SESSION_ID", ""),
        prompt_snippet=args.prompt,
        expected_duration_minutes=timeout,
        project_root=project_root,
    )

    # 6. Output success
    print(f"✓ Claimed bead: {args.bead_id}")
    print(f"  Project: {project_name}")
    print(f"  Title: {bead.get('title', 'N/A')}")
    print(f"  Type: {issue_type}")
    print(f"  Timeout: {timeout} minutes")
    print(f"  Assignment ID: {assignment.get('assignment_id')}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
