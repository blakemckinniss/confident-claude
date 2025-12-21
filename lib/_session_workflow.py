#!/usr/bin/env python3
"""
Session Workflow - Nudge system, features, work items, checkpoints, handoff.
"""

import time
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from _session_state_class import SessionState

# Nudge cooldowns
NUDGE_COOLDOWNS = {
    "goal_drift": 8,
    "library_research": 5,
    "multiple_edits": 10,
    "unresolved_error": 3,
    "sunk_cost": 5,
    "batch_opportunity": 4,
    "iteration_loop": 3,
    "stub_warning": 10,
    "default": 5,
}

ESCALATION_THRESHOLD = 3


def _content_hash(content: str) -> int:
    """Simple hash of content for dedup."""
    return hash(content[:100])


def should_nudge(
    state: "SessionState", nudge_type: str, content: str = ""
) -> tuple[bool, str]:
    """Check if a nudge should be shown based on history."""
    history = state.nudge_history.get(nudge_type, {})
    cooldown = NUDGE_COOLDOWNS.get(nudge_type, NUDGE_COOLDOWNS["default"])

    last_turn = history.get("last_turn", -999)
    turns_since = state.turn_count - last_turn

    if turns_since < cooldown:
        if content and history.get("last_content_hash") == _content_hash(content):
            return False, "suppress"
        if content and history.get("last_content_hash") != _content_hash(content):
            return True, "normal"
        return False, "suppress"

    times_ignored = history.get("times_ignored", 0)
    if times_ignored >= ESCALATION_THRESHOLD:
        return True, "escalate"

    return True, "normal"


def record_nudge(state: "SessionState", nudge_type: str, content: str = ""):
    """Record that a nudge was shown."""
    if nudge_type not in state.nudge_history:
        state.nudge_history[nudge_type] = {}

    history = state.nudge_history[nudge_type]
    history["last_turn"] = state.turn_count
    history["times_shown"] = history.get("times_shown", 0) + 1
    if content:
        history["last_content_hash"] = _content_hash(content)


def start_feature(state: "SessionState", description: str) -> str:
    """Start tracking a new feature/task."""
    feature_id = f"F{int(time.time())}"

    if state.current_feature:
        complete_feature(state, "interrupted")

    state.current_feature = description[:200]
    state.current_feature_started = time.time()
    state.current_feature_start_turn = state.turn_count
    state.current_feature_files = []

    return feature_id


def complete_feature(state: "SessionState", status: str = "completed"):
    """Complete the current feature and log it."""
    if not state.current_feature:
        return

    entry = {
        "feature_id": f"F{int(state.current_feature_started)}",
        "description": state.current_feature,
        "status": status,
        "files": list(set(state.current_feature_files))[-10:],
        "errors": len(
            [
                e
                for e in state.errors_recent
                if e.get("timestamp", 0) > state.current_feature_started
            ]
        ),
        "started": state.current_feature_started,
        "completed": time.time(),
        "turns": state.turn_count - state.current_feature_start_turn,
    }
    state.progress_log.append(entry)
    state.progress_log = state.progress_log[-20:]

    state.current_feature = ""
    state.current_feature_started = 0.0
    state.current_feature_start_turn = 0
    state.current_feature_files = []


def track_feature_file(state: "SessionState", filepath: str):
    """Track a file as part of current feature work."""
    if filepath and filepath not in state.current_feature_files:
        state.current_feature_files.append(filepath)
        state.current_feature_files = state.current_feature_files[-20:]


def add_work_item(
    state: "SessionState",
    item_type: str,
    source: str,
    description: str,
    priority: int = 50,
) -> str:
    """Add an auto-discovered work item to the queue."""
    item_id = f"W{int(time.time() * 1000) % 100000}"

    for existing in state.work_queue:
        if existing.get("type") == item_type:
            if existing.get("description", "")[:50] == description[:50]:
                return existing.get("id", item_id)

    item = {
        "id": item_id,
        "type": item_type,
        "source": source[:100],
        "description": description[:200],
        "priority": priority,
        "discovered_at": time.time(),
        "status": "pending",
    }
    state.work_queue.append(item)
    state.work_queue = state.work_queue[-30:]

    return item_id


def get_next_work_item(state: "SessionState") -> Optional[dict]:
    """Get the highest priority pending work item."""
    pending = [w for w in state.work_queue if w.get("status") == "pending"]
    if not pending:
        return None

    type_weights = {
        "error": 1.5,
        "test_failure": 1.3,
        "gap": 1.1,
        "todo": 1.0,
        "stub": 0.8,
    }

    def score(item):
        base = item.get("priority", 50)
        type_mult = type_weights.get(item.get("type", ""), 1.0)
        age = time.time() - item.get("discovered_at", 0)
        recency = max(0, 1 - age / 86400)
        return base * type_mult + recency * 10

    return max(pending, key=score)


def create_checkpoint(state: "SessionState", commit_hash: str = "", notes: str = ""):
    """Record a checkpoint for recovery."""
    checkpoint = {
        "checkpoint_id": f"CP{int(time.time())}",
        "commit_hash": commit_hash,
        "feature": state.current_feature,
        "timestamp": time.time(),
        "turn": state.turn_count,
        "files_edited": list(state.files_edited[-10:]),
        "notes": notes[:100],
    }
    state.checkpoints.append(checkpoint)
    state.checkpoints = state.checkpoints[-10:]
    state.last_checkpoint_turn = state.turn_count


def prepare_handoff(state: "SessionState") -> dict:
    """Prepare session handoff data for context bridging."""
    summary_parts = []

    completed = [p for p in state.progress_log if p.get("status") == "completed"]
    if completed:
        recent = completed[-3:]
        summary_parts.append(
            f"Completed: {', '.join(p['description'][:30] for p in recent)}"
        )

    if state.current_feature:
        summary_parts.append(f"In progress: {state.current_feature[:50]}")

    if state.errors_unresolved:
        summary_parts.append(f"Unresolved errors: {len(state.errors_unresolved)}")

    state.handoff_summary = (
        " | ".join(summary_parts) if summary_parts else "No significant progress"
    )

    next_items = sorted(
        [w for w in state.work_queue if w.get("status") == "pending"],
        key=lambda x: x.get("priority", 0),
        reverse=True,
    )[:5]
    state.handoff_next_steps = [
        {"type": w["type"], "description": w["description"][:80]} for w in next_items
    ]

    state.handoff_blockers = [
        {"type": e.get("type", "error")[:30], "details": e.get("details", "")[:50]}
        for e in state.errors_unresolved[:3]
    ]

    # 🔥 PAL CONTINUATIONS - Cross-session memory gold!
    pal_continuations = {}
    try:
        import json
        from pathlib import Path

        mm_dir = Path.home() / ".claude/tmp/mastermind"
        if mm_dir.exists():
            state_files = list(mm_dir.glob("*/*/state.json"))
            if state_files:
                latest = max(state_files, key=lambda p: p.stat().st_mtime)
                data = json.loads(latest.read_text())
                pal_continuations = data.get("pal_continuations", {})
    except Exception:
        pass

    return {
        "summary": state.handoff_summary,
        "next_steps": state.handoff_next_steps,
        "blockers": state.handoff_blockers,
        "pal_continuations": pal_continuations,  # 🔥 CRITICAL for context resume
    }


def extract_work_from_errors(state: "SessionState"):
    """Auto-extract work items from recent errors."""
    for error in state.errors_unresolved:
        error_type = error.get("type", "unknown")
        details = error.get("details", "")

        existing_ids = {w.get("source") for w in state.work_queue}
        error_key = f"error:{error_type[:20]}"
        if error_key in existing_ids:
            continue

        priority = 70
        if "syntax" in error_type.lower():
            priority = 90
        elif "import" in error_type.lower():
            priority = 85
        elif "test" in error_type.lower():
            priority = 80

        add_work_item(
            state,
            item_type="error",
            source=error_key,
            description=f"Fix: {error_type} - {details[:100]}",
            priority=priority,
        )
