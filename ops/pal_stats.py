#!/usr/bin/env python3
"""PAL continuation_id efficiency statistics (v4.28.1).

Surfaces continuation_id reuse rates and efficiency grades from telemetry.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Add lib to path
sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

from mastermind.telemetry import (
    CONTINUATION_GRADE_A_THRESHOLD,
    CONTINUATION_GRADE_B_THRESHOLD,
    TELEMETRY_DIR,
    get_continuation_reuse_stats,
)


def get_grade_emoji(grade: str) -> str:
    """Get emoji for efficiency grade."""
    return {"A": "🏆", "B": "👍", "C": "⚠️"}.get(grade, "❓")


def format_stats(stats: dict) -> str:
    """Format stats for display."""
    if stats.get("total_events", 0) == 0:
        return "No PAL continuation events found."

    lines = []
    grade = stats.get("efficiency_grade", "?")
    emoji = get_grade_emoji(grade)

    lines.append(f"{emoji} PAL Continuation Efficiency: Grade {grade}")
    lines.append(f"   Reuse Rate: {stats.get('reuse_rate_pct', 0)}%")
    lines.append("")

    by_event = stats.get("by_event", {})
    lines.append("📊 Event Summary:")
    lines.append(f"   Captured: {by_event.get('captured', 0)}")
    lines.append(f"   Reused:   {by_event.get('reused', 0)} ✅")
    lines.append(f"   Wasted:   {by_event.get('wasted', 0)} ❌")
    lines.append("")

    by_tool = stats.get("by_tool", {})
    if by_tool:
        lines.append("🔧 By Tool:")
        for tool, counts in sorted(by_tool.items()):
            reused = counts.get("reused", 0)
            wasted = counts.get("wasted", 0)
            total = reused + wasted
            rate = (reused / total * 100) if total > 0 else 0
            lines.append(f"   {tool}: {rate:.0f}% reuse ({reused}/{total})")

    return "\n".join(lines)


def list_sessions() -> list[str]:
    """List available session IDs from telemetry."""
    if not TELEMETRY_DIR.exists():
        return []
    return [p.stem for p in TELEMETRY_DIR.glob("*.jsonl")]


def aggregate_stats(session_ids: list[str]) -> dict:
    """Aggregate stats across multiple sessions."""
    totals = {"captured": 0, "reused": 0, "wasted": 0}
    by_tool: dict[str, dict[str, int]] = {}

    for sid in session_ids:
        stats = get_continuation_reuse_stats(sid)
        if stats.get("total_events", 0) == 0:
            continue

        by_event = stats.get("by_event", {})
        for event_type in ["captured", "reused", "wasted"]:
            totals[event_type] += by_event.get(event_type, 0)

        for tool, counts in stats.get("by_tool", {}).items():
            if tool not in by_tool:
                by_tool[tool] = {"captured": 0, "reused": 0, "wasted": 0}
            for event_type in ["captured", "reused", "wasted"]:
                by_tool[tool][event_type] += counts.get(event_type, 0)

    total_calls = totals["reused"] + totals["wasted"]
    reuse_rate = (totals["reused"] / total_calls * 100) if total_calls > 0 else 0

    return {
        "session_count": len(session_ids),
        "total_events": sum(totals.values()),
        "by_event": totals,
        "by_tool": by_tool,
        "reuse_rate_pct": round(reuse_rate, 1),
        "waste_count": totals["wasted"],
        "efficiency_grade": "A"
        if reuse_rate >= CONTINUATION_GRADE_A_THRESHOLD
        else "B"
        if reuse_rate >= CONTINUATION_GRADE_B_THRESHOLD
        else "C",
    }


def main():
    parser = argparse.ArgumentParser(description="PAL continuation_id statistics")
    parser.add_argument(
        "session_id",
        nargs="?",
        help="Session ID (default: current or 'all' for aggregate)",
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--list", action="store_true", help="List available sessions")
    args = parser.parse_args()

    if args.list:
        sessions = list_sessions()
        if not sessions:
            print("No telemetry sessions found.")
        else:
            print(f"Found {len(sessions)} sessions:")
            for sid in sorted(sessions)[-10:]:  # Last 10
                print(f"  {sid}")
        return

    if args.session_id == "all":
        sessions = list_sessions()
        if not sessions:
            print("No telemetry sessions found.")
            return
        stats = aggregate_stats(sessions)
        stats["scope"] = "aggregate"
    elif args.session_id:
        stats = get_continuation_reuse_stats(args.session_id)
    else:
        # Try to find current session from environment or most recent
        sessions = list_sessions()
        if not sessions:
            print("No telemetry sessions found. Use --list to check.")
            return
        # Use most recent
        stats = get_continuation_reuse_stats(sorted(sessions)[-1])
        stats["note"] = f"Using most recent session: {sorted(sessions)[-1]}"

    if args.json:
        print(json.dumps(stats, indent=2))
    else:
        print(format_stats(stats))
        if stats.get("note"):
            print(f"\n💡 {stats['note']}")


if __name__ == "__main__":
    main()
