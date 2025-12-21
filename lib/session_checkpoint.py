#!/usr/bin/env python3
"""
Session Checkpoint - State persistence across session boundaries.

Implements tiered state management:
- Tier 1: Critical (always persist) - ~20 fields
- Tier 2: Cache (persist if fresh) - ~35 fields
- Tier 3: Ephemeral (discard at Phase 3+) - 50+ fields

Uses PAL continuation_id as cross-session state store.

v1.0: Initial implementation
"""

import json
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

# Checkpoint storage constants
CHECKPOINT_DIR = Path.home() / ".claude/tmp/checkpoints"
CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)

# State retention limits
MAX_FILES_READ_HISTORY = 50
MAX_FILES_EDITED_HISTORY = 20
MAX_FILES_CREATED_HISTORY = 20
MAX_COMMANDS_SUCCEEDED_HISTORY = 20
MAX_COMMANDS_FAILED_HISTORY = 10
MAX_ERRORS_RECENT_HISTORY = 10
MAX_BEADS_COMMANDS_HISTORY = 10
MAX_LAST_TOOLS_HISTORY = 5
DEFAULT_CONFIDENCE = 75
MAX_CHECKPOINT_AGE_HOURS = 24
MAX_TIER3_AGE_HOURS = 1  # Ephemeral data expires quickly
MAX_CHECKPOINT_COUNT = 10


@dataclass
class Tier1State:
    """
    Mission-critical state that MUST persist across sessions.
    These fields cannot be reconstructed and are essential for recovery.
    """

    # Session identity
    session_id: str = ""
    project_root: str = ""
    working_directory: str = ""

    # Goal tracking (prevents drift after compaction)
    original_goal: str = ""
    goal_keywords: list = field(default_factory=list)
    goal_project_id: str = ""

    # Confidence (critical for gating)
    confidence: int = 75
    completion_confidence: int = 0

    # PAL context (second brain pointer)
    pal_continuation_id: str = ""

    # Serena activation (semantic search state)
    serena_activated: bool = False
    serena_project: str = ""

    # Ralph completion tracking
    ralph_mode: str = ""
    task_contract: dict = field(default_factory=dict)

    # Last tool for idempotency (last 5)
    last_tools: list = field(default_factory=list)

    # Checkpoint metadata
    checkpoint_id: str = ""
    checkpoint_timestamp: float = 0.0
    checkpoint_trigger: str = ""  # manual|auto|exhaustion


@dataclass
class Tier2State:
    """
    High-value cache that SHOULD persist but can be reconstructed.
    Expires after 24 hours or when stale.
    """

    # File tracking (can be re-read)
    files_read: list = field(default_factory=list)
    files_edited: list = field(default_factory=list)
    files_created: list = field(default_factory=list)

    # Tool execution history
    tool_counts: dict = field(default_factory=dict)
    commands_succeeded: list = field(default_factory=list)
    commands_failed: list = field(default_factory=list)

    # Error tracking
    errors_recent: list = field(default_factory=list)
    errors_unresolved: list = field(default_factory=list)

    # Hook execution metadata
    turn_count: int = 0
    nudge_history: dict = field(default_factory=dict)

    # Beads context (already cross-session via MCP)
    recent_beads_commands: list = field(default_factory=list)

    # Performance metrics
    hook_stats: dict = field(default_factory=dict)

    # Cache timestamp
    cached_at: float = 0.0


@dataclass
class Tier3State:
    """
    Ephemeral state that CAN be discarded at Phase 3+.
    Not checkpointed to PAL, only persisted locally.
    """

    # Verbose tracking
    edit_history: dict = field(default_factory=dict)
    approach_history: list = field(default_factory=list)
    progress_log: list = field(default_factory=list)

    # Debug information
    framework_errors: list = field(default_factory=list)
    evidence_ledger: list = field(default_factory=list)

    # Intermediate state
    pending_files: list = field(default_factory=list)
    pending_searches: list = field(default_factory=list)
    pending_integration_greps: list = field(default_factory=list)


@dataclass
class SessionCheckpoint:
    """Complete checkpoint containing all tiers."""

    version: str = "1.0"
    tier1: Tier1State = field(default_factory=Tier1State)
    tier2: Optional[Tier2State] = None
    tier3: Optional[Tier3State] = None

    # Metadata
    created_at: float = 0.0
    trigger: str = ""
    context_usage_percent: float = 0.0
    phase_at_checkpoint: int = 1


def extract_tier1_from_session(state) -> Tier1State:
    """Extract Tier 1 fields from SessionState."""
    return Tier1State(
        session_id=getattr(state, "session_id", ""),
        project_root=getattr(state, "goal_project_id", ""),
        working_directory="",  # Will be set from environment
        original_goal=getattr(state, "original_goal", ""),
        goal_keywords=list(getattr(state, "goal_keywords", [])),
        goal_project_id=getattr(state, "goal_project_id", ""),
        confidence=getattr(state, "confidence", 75),
        completion_confidence=getattr(state, "completion_confidence", 0),
        pal_continuation_id="",  # Set by caller with PAL response
        serena_activated=getattr(state, "serena_activated", False),
        serena_project=getattr(state, "serena_project", ""),
        ralph_mode=getattr(state, "ralph_mode", ""),
        task_contract=dict(getattr(state, "task_contract", {})),
        last_tools=list(getattr(state, "last_5_tools", []))[-5:],
        checkpoint_timestamp=time.time(),
    )


def extract_tier2_from_session(state) -> Tier2State:
    """Extract Tier 2 fields from SessionState."""
    return Tier2State(
        files_read=list(getattr(state, "files_read", []))[-50:],
        files_edited=list(getattr(state, "files_edited", []))[-20:],
        files_created=list(getattr(state, "files_created", []))[-20:],
        tool_counts=dict(getattr(state, "tool_counts", {})),
        commands_succeeded=list(getattr(state, "commands_succeeded", []))[-20:],
        commands_failed=list(getattr(state, "commands_failed", []))[-10:],
        errors_recent=list(getattr(state, "errors_recent", []))[-10:],
        errors_unresolved=list(getattr(state, "errors_unresolved", [])),
        turn_count=getattr(state, "turn_count", 0),
        nudge_history=dict(getattr(state, "nudge_history", {})),
        recent_beads_commands=list(getattr(state, "recent_beads_commands", []))[-10:],
        hook_stats={},  # Populated separately
        cached_at=time.time(),
    )


def extract_tier3_from_session(state) -> Tier3State:
    """Extract Tier 3 fields from SessionState."""
    return Tier3State(
        edit_history=dict(getattr(state, "edit_history", {})),
        approach_history=list(getattr(state, "approach_history", [])),
        progress_log=list(getattr(state, "progress_log", [])),
        framework_errors=list(getattr(state, "framework_errors", [])),
        evidence_ledger=list(getattr(state, "evidence_ledger", [])),
        pending_files=list(getattr(state, "pending_files", [])),
        pending_searches=list(getattr(state, "pending_searches", [])),
        pending_integration_greps=list(getattr(state, "pending_integration_greps", [])),
    )


def create_checkpoint(
    state,
    trigger: str,
    context_usage_percent: float,
    phase: int,
    include_tier2: bool = True,
    include_tier3: bool = False,
) -> SessionCheckpoint:
    """
    Create a checkpoint from current SessionState.

    Args:
        state: SessionState instance
        trigger: What triggered checkpoint (manual|auto|exhaustion)
        context_usage_percent: Current context window usage
        phase: Current phase (1-4)
        include_tier2: Include Tier 2 cache (default True)
        include_tier3: Include Tier 3 ephemeral (default False, only at Phase 1)
    """
    checkpoint = SessionCheckpoint(
        tier1=extract_tier1_from_session(state),
        created_at=time.time(),
        trigger=trigger,
        context_usage_percent=context_usage_percent,
        phase_at_checkpoint=phase,
    )

    if include_tier2:
        checkpoint.tier2 = extract_tier2_from_session(state)

    if include_tier3 and phase == 1:
        checkpoint.tier3 = extract_tier3_from_session(state)

    return checkpoint


def save_checkpoint_local(checkpoint: SessionCheckpoint) -> Path:
    """Save checkpoint to local JSON file."""
    checkpoint_id = f"cp_{int(time.time())}_{checkpoint.tier1.session_id[:8]}"
    checkpoint.tier1.checkpoint_id = checkpoint_id

    path = CHECKPOINT_DIR / f"{checkpoint_id}.json"

    data = {
        "version": checkpoint.version,
        "tier1": asdict(checkpoint.tier1),
        "tier2": asdict(checkpoint.tier2) if checkpoint.tier2 else None,
        "tier3": asdict(checkpoint.tier3) if checkpoint.tier3 else None,
        "created_at": checkpoint.created_at,
        "trigger": checkpoint.trigger,
        "context_usage_percent": checkpoint.context_usage_percent,
        "phase_at_checkpoint": checkpoint.phase_at_checkpoint,
    }

    path.write_text(json.dumps(data, indent=2))
    return path


def load_checkpoint_local(checkpoint_id: str) -> Optional[SessionCheckpoint]:
    """Load checkpoint from local JSON file with schema validation.

    Schema versioning prevents stale state injection:
    - Version mismatch → discard checkpoint (incompatible schema)
    - Age > MAX_CHECKPOINT_AGE_HOURS → discard Tier2/Tier3
    """
    path = CHECKPOINT_DIR / f"{checkpoint_id}.json"
    if not path.exists():
        return None

    try:
        data = json.loads(path.read_text())

        # Schema version validation - prevent incompatible checkpoint loading
        checkpoint_version = data.get("version", "1.0")
        if checkpoint_version != "1.0":
            # Future: implement migration logic for version upgrades
            # For now, reject incompatible versions
            return None

        # Age validation for tier-based loading
        created_at = data.get("created_at", 0)
        age_hours = (time.time() - created_at) / 3600 if created_at else float("inf")

        # Always load Tier1
        tier1_data = data.get("tier1", {})
        tier1 = Tier1State(**tier1_data)

        # Load Tier2 only if checkpoint is fresh enough
        tier2 = None
        if data.get("tier2") and age_hours < MAX_CHECKPOINT_AGE_HOURS:
            tier2 = Tier2State(**data["tier2"])

        # Load Tier3 only if very fresh - ephemeral by nature
        tier3 = None
        if data.get("tier3") and age_hours < MAX_TIER3_AGE_HOURS:
            tier3 = Tier3State(**data["tier3"])

        checkpoint = SessionCheckpoint(
            version=checkpoint_version,
            tier1=tier1,
            tier2=tier2,
            tier3=tier3,
            created_at=created_at,
            trigger=data.get("trigger", ""),
            context_usage_percent=data.get("context_usage_percent", 0),
            phase_at_checkpoint=data.get("phase_at_checkpoint", 1),
        )
        return checkpoint
    except Exception:
        return None


def find_latest_checkpoint() -> Optional[str]:
    """Find the most recent checkpoint ID."""
    checkpoints = list(CHECKPOINT_DIR.glob("cp_*.json"))
    if not checkpoints:
        return None

    # Sort by modification time
    latest = max(checkpoints, key=lambda p: p.stat().st_mtime)
    return latest.stem


def cleanup_old_checkpoints(max_age_hours: int = 24, max_count: int = 10) -> int:
    """Remove old checkpoints to prevent disk bloat."""
    checkpoints = list(CHECKPOINT_DIR.glob("cp_*.json"))
    now = time.time()
    max_age_seconds = max_age_hours * 3600
    removed = 0

    # Sort by age (oldest first)
    checkpoints.sort(key=lambda p: p.stat().st_mtime)

    for cp in checkpoints:
        age = now - cp.stat().st_mtime
        # Remove if too old OR if we have too many
        if age > max_age_seconds or len(checkpoints) - removed > max_count:
            cp.unlink()
            removed += 1

    return removed


def format_checkpoint_for_pal(checkpoint: SessionCheckpoint) -> str:
    """
    Format checkpoint for PAL continuation storage.
    Returns a condensed string representation.
    """
    t1 = checkpoint.tier1
    parts = [
        f"SESSION_CHECKPOINT v{checkpoint.version}",
        f"ID: {t1.checkpoint_id}",
        f"Trigger: {checkpoint.trigger}",
        f"Context: {checkpoint.context_usage_percent:.1f}%",
        f"Phase: {checkpoint.phase_at_checkpoint}",
        "",
        "=== TIER 1 (Critical) ===",
        f"Goal: {t1.original_goal[:100]}..."
        if len(t1.original_goal) > 100
        else f"Goal: {t1.original_goal}",
        f"Keywords: {','.join(t1.goal_keywords[:5])}",
        f"Confidence: {t1.confidence}%",
        f"Completion: {t1.completion_confidence}%",
        f"Ralph: {t1.ralph_mode or 'inactive'}",
        f"Serena: {t1.serena_project if t1.serena_activated else 'inactive'}",
    ]

    if checkpoint.tier2:
        t2 = checkpoint.tier2
        parts.extend(
            [
                "",
                "=== TIER 2 (Cache) ===",
                f"Files: {len(t2.files_read)}r/{len(t2.files_edited)}e/{len(t2.files_created)}c",
                f"Turns: {t2.turn_count}",
                f"Errors: {len(t2.errors_unresolved)} unresolved",
            ]
        )

    return "\n".join(parts)
