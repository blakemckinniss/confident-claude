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
    needs_research: bool = False,
    research_topics: list[str] | None = None,
    # v4.26: Enhanced context signals for routing analysis
    context_signals: dict[str, Any] | None = None,
) -> None:
    """Log router classification decision.

    Args:
        context_signals: Optional dict with routing context including:
            - stuck_loop: bool - circuit breaker state
            - bead_goals: list[str] - active task descriptions
            - recent_reducers: list[str] - recently fired reducers
            - pal_continuation: bool - whether PAL continuation exists
            - agent_confidence: int - current confidence level
    """
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
            "needs_research": needs_research,
            "research_topics": research_topics or [],
            "context_signals": context_signals or {},
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


# Phase 4: Threshold effectiveness telemetry


def log_threshold_check(
    session_id: str,
    turn: int,
    threshold_type: str,
    current_value: int,
    threshold_value: int,
    triggered: bool,
    epoch_id: int,
) -> None:
    """Log threshold evaluation for effectiveness analysis.

    Args:
        session_id: Session identifier
        turn: Current turn number
        threshold_type: Type of threshold (file_count, test_failures)
        current_value: Current metric value
        threshold_value: Configured threshold
        triggered: Whether threshold was exceeded
        epoch_id: Current epoch for blueprint tracking
    """
    log_event(
        "threshold_check",
        session_id,
        turn,
        {
            "threshold_type": threshold_type,
            "current_value": current_value,
            "threshold_value": threshold_value,
            "triggered": triggered,
            "headroom": threshold_value - current_value,
            "utilization_pct": (current_value / threshold_value * 100)
            if threshold_value
            else 0,
            "epoch_id": epoch_id,
        },
    )


def log_threshold_update(
    session_id: str,
    turn: int,
    changes: dict[str, tuple[int, int]],
    reason: str | None = None,
) -> None:
    """Log threshold configuration change.

    Args:
        session_id: Session identifier
        turn: Current turn number
        changes: Dict of {threshold_name: (old_value, new_value)}
        reason: Optional reason for threshold adjustment
    """
    log_event(
        "threshold_update",
        session_id,
        turn,
        {
            "changes": {k: {"old": v[0], "new": v[1]} for k, v in changes.items()},
            "reason": reason,
        },
    )


def get_routing_analysis(session_id: str | None = None) -> dict[str, Any]:
    """Analyze Groq routing decisions for threshold tuning (v4.26).

    If session_id provided, analyzes that session.
    Otherwise, analyzes all sessions in telemetry directory.

    Returns:
        Analysis of routing patterns including:
        - classification_distribution: counts by classification level
        - context_signal_correlation: which signals correlate with which classifications
        - confidence_accuracy: how often high-confidence routes were correct
        - suggested_adjustments: threshold tuning recommendations
    """
    if session_id:
        events = read_session_telemetry(session_id)
    else:
        # Aggregate across all sessions
        events = []
        for path in TELEMETRY_DIR.glob("*.jsonl"):
            events.extend(read_session_telemetry(path.stem))

    router_events = [e for e in events if e.event_type == "router_decision"]

    if not router_events:
        return {"error": "No routing decisions found", "event_count": 0}

    # Classification distribution
    classification_counts: dict[str, int] = {}
    for e in router_events:
        cls = e.data.get("classification", "unknown")
        classification_counts[cls] = classification_counts.get(cls, 0) + 1

    # Context signal correlation
    signal_by_classification: dict[str, dict[str, int]] = {
        "trivial": {"stuck_loop": 0, "has_errors": 0, "low_confidence": 0},
        "medium": {"stuck_loop": 0, "has_errors": 0, "low_confidence": 0},
        "complex": {"stuck_loop": 0, "has_errors": 0, "low_confidence": 0},
    }

    confidence_accuracy: dict[str, list[float]] = {
        "trivial": [],
        "medium": [],
        "complex": [],
    }

    for e in router_events:
        cls = e.data.get("classification", "unknown")
        if cls not in signal_by_classification:
            continue

        signals = e.data.get("context_signals", {})
        if signals.get("stuck_loop"):
            signal_by_classification[cls]["stuck_loop"] += 1
        if signals.get("has_errors"):
            signal_by_classification[cls]["has_errors"] += 1
        if signals.get("agent_confidence", 100) < 70:
            signal_by_classification[cls]["low_confidence"] += 1

        confidence_accuracy[cls].append(e.data.get("confidence", 0))

    # Calculate average confidence per classification
    avg_confidence = {}
    for cls, confidences in confidence_accuracy.items():
        if confidences:
            avg_confidence[cls] = sum(confidences) / len(confidences)

    # Generate suggestions
    suggestions = []
    total = len(router_events)

    # Check if stuck_loop correlates with classification
    if signal_by_classification.get("trivial", {}).get("stuck_loop", 0) > 0:
        suggestions.append(
            "ISSUE: stuck_loop=true classified as trivial - should be medium/complex"
        )

    # Check classification distribution
    trivial_pct = classification_counts.get("trivial", 0) / total * 100 if total else 0
    complex_pct = classification_counts.get("complex", 0) / total * 100 if total else 0

    if trivial_pct > 70:
        suggestions.append(
            f"Classification skew: {trivial_pct:.0f}% trivial - consider tightening threshold"
        )
    if complex_pct > 50:
        suggestions.append(
            f"Over-classification: {complex_pct:.0f}% complex - consider relaxing threshold"
        )

    return {
        "event_count": len(router_events),
        "classification_distribution": classification_counts,
        "context_signal_correlation": signal_by_classification,
        "average_confidence_by_class": avg_confidence,
        "suggested_adjustments": suggestions,
    }


def get_threshold_effectiveness(session_id: str) -> dict[str, Any]:
    """Analyze threshold effectiveness for a session.

    Returns metrics on how well thresholds are calibrated:
    - How often each threshold triggered
    - Average headroom when not triggered
    - Utilization distribution
    """
    events = read_session_telemetry(session_id)
    threshold_events = [e for e in events if e.event_type == "threshold_check"]

    if not threshold_events:
        return {"session_id": session_id, "threshold_checks": 0}

    by_type: dict[str, list[dict]] = {}
    for e in threshold_events:
        t_type = e.data.get("threshold_type", "unknown")
        if t_type not in by_type:
            by_type[t_type] = []
        by_type[t_type].append(e.data)

    effectiveness: dict[str, Any] = {
        "session_id": session_id,
        "threshold_checks": len(threshold_events),
        "by_type": {},
    }

    for t_type, checks in by_type.items():
        triggered_count = sum(1 for c in checks if c.get("triggered"))
        avg_utilization = sum(c.get("utilization_pct", 0) for c in checks) / len(checks)
        avg_headroom = sum(
            c.get("headroom", 0) for c in checks if not c.get("triggered")
        )
        non_triggered = [c for c in checks if not c.get("triggered")]

        effectiveness["by_type"][t_type] = {
            "total_checks": len(checks),
            "triggered_count": triggered_count,
            "trigger_rate_pct": triggered_count / len(checks) * 100,
            "avg_utilization_pct": avg_utilization,
            "avg_headroom_when_ok": avg_headroom / len(non_triggered)
            if non_triggered
            else 0,
        }

    return effectiveness
