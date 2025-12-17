"""Observability and telemetry for mastermind.

Logs structured events to JSONL per session.
Events: router_decision, planner_called, escalation_triggered, etc.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

from .config import get_config

# Default telemetry directory
TELEMETRY_DIR = Path.home() / ".claude" / "tmp" / "mastermind_telemetry"


@dataclass
class TelemetryEvent:
    """Base telemetry event."""
    event_type: str
    session_id: str
    timestamp: float
    turn: int
    data: dict[str, Any]


def get_telemetry_path(session_id: str) -> Path:
    """Get path for session telemetry file."""
    TELEMETRY_DIR.mkdir(parents=True, exist_ok=True)
    return TELEMETRY_DIR / f"{session_id}.jsonl"


def log_event(
    event_type: str,
    session_id: str,
    turn: int,
    data: dict[str, Any],
) -> None:
    """Log a telemetry event to session JSONL file."""
    config = get_config()

    if not config.telemetry.enabled:
        return

    event = TelemetryEvent(
        event_type=event_type,
        session_id=session_id,
        timestamp=time.time(),
        turn=turn,
        data=data,
    )

    path = get_telemetry_path(session_id)
    with open(path, "a") as f:
        f.write(json.dumps(asdict(event)) + "\n")


def log_router_decision(
    session_id: str,
    turn: int,
    classification: str,
    confidence: float,
    reason_codes: list[str],
    latency_ms: int,
    user_override: str | None = None,
) -> None:
    """Log router classification decision."""
    config = get_config()
    if not config.telemetry.log_router_decisions:
        return

    log_event(
        "router_decision",
        session_id,
        turn,
        {
            "classification": classification,
            "confidence": confidence,
            "reason_codes": reason_codes,
            "latency_ms": latency_ms,
            "user_override": user_override,
        },
    )


def log_planner_called(
    session_id: str,
    turn: int,
    model: str,
    context_tokens: int,
    latency_ms: int,
    blueprint_goal: str | None = None,
    error: str | None = None,
) -> None:
    """Log planner invocation."""
    config = get_config()
    if not config.telemetry.log_planner_calls:
        return

    log_event(
        "planner_called",
        session_id,
        turn,
        {
            "model": model,
            "context_tokens": context_tokens,
            "latency_ms": latency_ms,
            "blueprint_goal": blueprint_goal,
            "error": error,
        },
    )


def log_escalation(
    session_id: str,
    turn: int,
    trigger: str,
    epoch_id: int,
    evidence: dict[str, Any],
) -> None:
    """Log drift escalation."""
    config = get_config()
    if not config.telemetry.log_escalations:
        return

    log_event(
        "escalation_triggered",
        session_id,
        turn,
        {
            "trigger": trigger,
            "epoch_id": epoch_id,
            "evidence": evidence,
        },
    )


def read_session_telemetry(session_id: str) -> list[TelemetryEvent]:
    """Read all telemetry events for a session."""
    path = get_telemetry_path(session_id)

    if not path.exists():
        return []

    events = []
    with open(path) as f:
        for line in f:
            if line.strip():
                data = json.loads(line)
                events.append(TelemetryEvent(**data))

    return events


def get_session_summary(session_id: str) -> dict[str, Any]:
    """Get summary statistics for a session."""
    events = read_session_telemetry(session_id)

    if not events:
        return {"session_id": session_id, "event_count": 0}

    event_counts: dict[str, int] = {}
    for e in events:
        event_counts[e.event_type] = event_counts.get(e.event_type, 0) + 1

    return {
        "session_id": session_id,
        "event_count": len(events),
        "event_types": event_counts,
        "first_event": events[0].timestamp,
        "last_event": events[-1].timestamp,
        "duration_seconds": events[-1].timestamp - events[0].timestamp,
    }
