"""Variance reporting for mastermind drift escalations.

Generates structured reports when drift triggers fire.
Supports delta consults via continuation_id.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .state import MastermindState, Blueprint
from .drift import DriftSignal


@dataclass
class VarianceReport:
    """Structured variance report for delta consult."""
    epoch_id: int
    turn: int
    triggers: list[str]
    what_changed: str
    evidence: dict[str, Any]
    options: list[str]
    recommendation: str


def generate_variance_report(
    state: MastermindState,
    signals: list[DriftSignal],
    blueprint: Blueprint | None = None,
) -> VarianceReport:
    """Generate variance report from drift signals."""
    _bp = blueprint or state.blueprint  # Reserved for future use

    # Summarize what changed
    changes = []
    evidence: dict[str, Any] = {}
    triggers = []

    for signal in signals:
        triggers.append(signal.trigger)
        evidence[signal.trigger] = signal.evidence

        if signal.trigger == "file_count":
            outside = signal.evidence.get("outside_touch_set", [])
            changes.append(f"Modified {len(outside)} files outside touch_set")
        elif signal.trigger == "test_failures":
            count = signal.evidence.get("failure_count", 0)
            changes.append(f"{count} test failures")
        elif signal.trigger == "approach_change":
            changes.append("Approach diverged from original plan")

    what_changed = "; ".join(changes) if changes else "Unknown drift detected"

    # Generate options
    options = [
        "1. Expand touch_set to include new files",
        "2. Revert to original approach",
        "3. Update blueprint with new strategy",
        "4. Continue with current approach (acknowledge drift)",
    ]

    # Simple recommendation based on signal types
    if "test_failures" in triggers:
        recommendation = "Fix failing tests before proceeding"
    elif "approach_change" in triggers:
        recommendation = "Review approach change with user"
    else:
        recommendation = "Consider expanding touch_set if changes are justified"

    return VarianceReport(
        epoch_id=state.epoch_id,
        turn=state.turn_count,
        triggers=triggers,
        what_changed=what_changed,
        evidence=evidence,
        options=options,
        recommendation=recommendation,
    )


def format_variance_for_planner(report: VarianceReport) -> str:
    """Format variance report for delta consult with planner."""
    lines = [
        "# Variance Report (Delta Consult)",
        "",
        f"**Epoch:** {report.epoch_id} | **Turn:** {report.turn}",
        f"**Triggers:** {', '.join(report.triggers)}",
        "",
        "## What Changed",
        report.what_changed,
        "",
        "## Evidence",
    ]

    for trigger, data in report.evidence.items():
        lines.append(f"### {trigger}")
        if isinstance(data, dict):
            for k, v in data.items():
                if isinstance(v, list):
                    lines.append(f"- {k}: {', '.join(str(x) for x in v[:5])}")
                else:
                    lines.append(f"- {k}: {v}")
        lines.append("")

    lines.extend([
        "## Options",
        *report.options,
        "",
        f"**Recommendation:** {report.recommendation}",
    ])

    return "\n".join(lines)


def format_variance_for_user(report: VarianceReport) -> str:
    """Format variance report for user notification."""
    return f"""⚠️ **Drift Detected** (Epoch {report.epoch_id})

{report.what_changed}

Triggers: {', '.join(report.triggers)}
Recommendation: {report.recommendation}

Use `^` prefix to force re-planning, or continue if drift is acceptable."""
