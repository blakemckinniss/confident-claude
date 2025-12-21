#!/usr/bin/env python3
"""
PreCompact Hook: Fires before compaction.

Hook Type: PreCompact
Matcher: manual | auto
Latency Target: <50ms

Injects persistent context into compaction summary via stdout.
This context survives compaction and remains in Claude's memory.

v2.0: Added confidence, goal, serena, beads, mastermind context.

Input: session_id, transcript_path, permission_mode, hook_event_name, trigger, custom_instructions
Output: stdout is added to compaction context
"""

import _lib_path  # noqa: F401
import sys
import json
import subprocess
from pathlib import Path

from session_state import load_state
from session_checkpoint import (
    create_checkpoint,
    save_checkpoint_local,
    cleanup_old_checkpoints,
)
from token_budget import get_budget_manager, Phase

MAX_OUTPUT_CHARS = 500
CHECKPOINT_REF_CHARS = 30  # Space reserved for checkpoint reference

# Canonical field order (highest priority first)
FIELD_ORDER = [
    "GOAL",
    "KEY",
    "CONF",
    "SERENA",
    "BEADS",
    "MM",
    "FILES",
    "UNVERIFIED",
    "ERR",
    "LIB",
]


def get_confidence_context(state) -> list[str]:
    """Extract confidence state for post-compaction continuity."""
    lines = []
    conf = state.confidence
    if conf >= 95:
        zone = "E"  # Expert
    elif conf >= 86:
        zone = "T"  # Trusted
    elif conf >= 71:
        zone = "C"  # Certainty
    elif conf >= 51:
        zone = "W"  # Working
    elif conf >= 31:
        zone = "H"  # Hypothesis
    else:
        zone = "I"  # Ignorance

    debt_count = len(state.repair_debt) if state.repair_debt else 0
    if debt_count:
        lines.append(f"CONF:{conf}%{zone}|D:{debt_count}")
    else:
        lines.append(f"CONF:{conf}%{zone}")

    return lines


def get_goal_context(state) -> list[str]:
    """Preserve original goal to prevent drift after compaction."""
    lines = []
    if state.original_goal:
        goal = state.original_goal[:80].replace("\n", " ").strip()
        if len(state.original_goal) > 80:
            goal += "..."
        lines.append(f"GOAL:{goal}")
        if state.goal_keywords:
            keywords = ",".join(k[:12] for k in state.goal_keywords[:4])
            lines.append(f"KEY:{keywords}")
    return lines


def _sanitize_project(name: str) -> str:
    """Whitelist alphanumeric, dash, underscore, dot only."""
    return "".join(c for c in name if c.isalnum() or c in "-_.")[:40]


def get_serena_context(state) -> list[str]:
    """Preserve Serena activation with auto-inject command."""
    lines = []
    if state.serena_activated and state.serena_project:
        project = _sanitize_project(state.serena_project)
        if project:
            lines.append(f'<serena-reactivate project="{project}"/>')
    return lines


def get_beads_context() -> list[str]:
    """Extract in-progress beads from database (lightweight)."""
    lines = []
    try:
        result = subprocess.run(
            ["bd", "list", "--status=in_progress"],
            capture_output=True,
            text=True,
            timeout=3,
        )
        if result.returncode == 0 and result.stdout.strip():
            bead_lines = [
                ln
                for ln in result.stdout.strip().split("\n")
                if ln.startswith("beads-")
            ]
            if bead_lines:
                bead_ids = [ln.split()[0][-8:] for ln in bead_lines[:3]]
                extra = len(bead_lines) - 3
                suffix = f"+{extra}" if extra > 0 else ""
                lines.append(f"BEADS:{','.join(bead_ids)}{suffix}")
    except Exception:
        pass
    return lines


def get_mastermind_context() -> list[str]:
    """Extract current mastermind classification if available."""
    lines = []
    try:
        mm_dir = Path.home() / ".claude/tmp/mastermind"
        if mm_dir.exists():
            state_files = list(mm_dir.glob("*/*/state.json"))
            if state_files:
                latest = max(state_files, key=lambda p: p.stat().st_mtime)
                data = json.loads(latest.read_text())
                classification = data.get("classification", "")
                blueprint = data.get("blueprint_active", False)
                if classification:
                    bp_flag = "+BP" if blueprint else ""
                    lines.append(f"MM:{classification[:8]}{bp_flag}")
    except Exception:
        pass
    return lines


def get_files_context(state) -> list[str]:
    """Extract file modification summary."""
    lines = []
    parts = []
    if state.files_created:
        parts.append(f"{len(state.files_created)}new")
    if state.files_edited:
        parts.append(f"{len(state.files_edited)}ed")
    if parts:
        lines.append(f"FILES:{'+'.join(parts)}")

    if state.pending_integration_greps:
        funcs = [
            p.get("function", "?")[:12] for p in state.pending_integration_greps[:2]
        ]
        extra = len(state.pending_integration_greps) - 2
        suffix = f"+{extra}" if extra > 0 else ""
        lines.append(f"UNVERIFIED:{','.join(funcs)}{suffix}")

    if state.errors_unresolved:
        lines.append(f"ERR:{len(state.errors_unresolved)}")

    return lines


def get_libs_context(state) -> list[str]:
    """Extract libraries in use."""
    lines = []
    if state.libraries_used:
        libs = ",".join(lib[:10] for lib in state.libraries_used[:4])
        extra = len(state.libraries_used) - 4
        suffix = f"+{extra}" if extra > 0 else ""
        lines.append(f"LIB:{libs}{suffix}")
    return lines


def build_minimal_fallback(state) -> str:
    """Fallback if full context exceeds limit - goal + conf + serena only."""
    parts = []
    if state.original_goal:
        goal = state.original_goal[:60].replace("\n", " ").strip()
        parts.append(f"GOAL:{goal}...")
    parts.append(f"CONF:{state.confidence}%")
    if state.serena_activated and state.serena_project:
        project = _sanitize_project(state.serena_project)
        if project:
            parts.append(f'<serena-reactivate project="{project}"/>')
    return " | ".join(parts)


def create_session_checkpoint(state, trigger: str) -> str:
    """Create and save a session checkpoint before compaction."""
    try:
        # Get current phase from budget manager
        mgr = get_budget_manager()
        phase = mgr.get_phase()
        usage_pct = mgr.state.usage_percent

        # Create checkpoint with appropriate tiers based on phase
        include_tier2 = phase.value <= Phase.SIGNALS.value  # Include if not critical
        include_tier3 = phase == Phase.VERBOSE  # Only at full verbosity

        checkpoint = create_checkpoint(
            state=state,
            trigger=trigger,
            context_usage_percent=usage_pct,
            phase=phase.value,
            include_tier2=include_tier2,
            include_tier3=include_tier3,
        )

        # Save locally
        save_checkpoint_local(checkpoint)

        # Cleanup old checkpoints
        cleanup_old_checkpoints()

        return checkpoint.tier1.checkpoint_id
    except Exception:
        return ""


def main():
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        data = {}

    trigger = data.get("trigger", "unknown")
    state = load_state()

    # Create checkpoint before compaction
    checkpoint_id = create_session_checkpoint(state, trigger)

    # Build context in priority order
    all_lines = []

    # Add checkpoint reference first (highest priority for recovery)
    if checkpoint_id:
        all_lines.append(f"CP:{checkpoint_id[-12:]}")

    all_lines.extend(get_goal_context(state))
    all_lines.extend(get_confidence_context(state))
    all_lines.extend(get_serena_context(state))
    all_lines.extend(get_beads_context())
    all_lines.extend(get_mastermind_context())
    all_lines.extend(get_files_context(state))
    all_lines.extend(get_libs_context(state))

    # Format output
    if all_lines:
        header = f"─ COMPACT({trigger}) ─"
        context_str = " | ".join(all_lines)
        output = f"{header}\n{context_str}"

        # Hard fallback if exceeds limit
        if len(output) > MAX_OUTPUT_CHARS:
            output = f"{header}\n{build_minimal_fallback(state)}"
    else:
        output = f"─ COMPACT({trigger}) ─\nNo context."

    print(output)
    sys.exit(0)


if __name__ == "__main__":
    main()
