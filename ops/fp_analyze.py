#!/usr/bin/env python3
"""
FP Pattern Analyzer - Cross-session learning from false positives.

Analyzes ~/.claude/tmp/fp_history.jsonl to detect:
- Reducers with high FP rates (broken detection logic)
- Temporal patterns (certain times/workflows)
- Reason clustering (common false positive scenarios)

Usage:
    fp_analyze.py              # Full analysis
    fp_analyze.py --summary    # Quick summary
    fp_analyze.py --reducer X  # Focus on specific reducer
    fp_analyze.py --since 7d   # Only last 7 days

Entity Model: This is the "immune memory" - learning from past
nerve damage to prevent future misfires.
"""

import argparse
import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

FP_HISTORY_FILE = Path.home() / ".claude" / "tmp" / "fp_history.jsonl"


def load_fp_history(since_days: int | None = None) -> list[dict]:
    """Load FP history, optionally filtered by time."""
    if not FP_HISTORY_FILE.exists():
        return []

    entries = []
    cutoff = None
    if since_days:
        cutoff = datetime.now() - timedelta(days=since_days)

    with FP_HISTORY_FILE.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                if cutoff:
                    ts = datetime.fromisoformat(entry["timestamp"])
                    if ts < cutoff:
                        continue
                entries.append(entry)
            except (json.JSONDecodeError, KeyError):
                continue

    return entries


def analyze_patterns(entries: list[dict]) -> dict:
    """Analyze FP patterns for insights."""
    if not entries:
        return {"total": 0, "reducers": {}, "insights": []}

    # Count by reducer
    reducer_counts = Counter(e["reducer"] for e in entries)

    # Group reasons by reducer
    reducer_reasons: dict[str, list[str]] = defaultdict(list)
    for e in entries:
        if e.get("reason"):
            reducer_reasons[e["reducer"]].append(e["reason"])

    # Time analysis
    hourly_counts: dict[int, int] = defaultdict(int)
    daily_counts: dict[str, int] = defaultdict(int)
    for e in entries:
        try:
            ts = datetime.fromisoformat(e["timestamp"])
            hourly_counts[ts.hour] += 1
            daily_counts[ts.strftime("%A")] += 1
        except (ValueError, KeyError):
            continue

    # Generate insights
    insights = []

    # High-frequency reducers (potential bugs)
    total = len(entries)
    for reducer, count in reducer_counts.most_common(5):
        pct = (count / total) * 100
        if count >= 3 and pct >= 20:
            insights.append(
                {
                    "type": "high_frequency",
                    "severity": "high" if pct >= 40 else "medium",
                    "reducer": reducer,
                    "count": count,
                    "percentage": round(pct, 1),
                    "message": f"{reducer} accounts for {pct:.0f}% of all FPs - likely broken detection",
                }
            )

    # Recent spike detection
    if len(entries) >= 5:
        recent = entries[-5:]
        recent_reducers = Counter(e["reducer"] for e in recent)
        for reducer, count in recent_reducers.items():
            if count >= 3:
                insights.append(
                    {
                        "type": "recent_spike",
                        "severity": "high",
                        "reducer": reducer,
                        "count": count,
                        "message": f"{reducer} triggered {count} FPs in last 5 entries - immediate attention needed",
                    }
                )

    # Common reasons (pattern extraction)
    for reducer, reasons in reducer_reasons.items():
        if len(reasons) >= 2:
            reason_counts = Counter(reasons)
            common = reason_counts.most_common(1)[0]
            if common[1] >= 2:
                insights.append(
                    {
                        "type": "common_reason",
                        "severity": "medium",
                        "reducer": reducer,
                        "reason": common[0],
                        "count": common[1],
                        "message": f"{reducer}: '{common[0]}' cited {common[1]} times - specific pattern to fix",
                    }
                )

    return {
        "total": total,
        "reducers": dict(reducer_counts),
        "reasons_by_reducer": dict(reducer_reasons),
        "hourly_distribution": dict(hourly_counts),
        "daily_distribution": dict(daily_counts),
        "insights": insights,
    }


def format_summary(analysis: dict) -> str:
    """Format a quick summary."""
    if analysis["total"] == 0:
        return "📊 No false positives recorded yet. Framework nervous system healthy."

    lines = [
        f"📊 **FP Analysis Summary** ({analysis['total']} total FPs)",
        "",
    ]

    # Top reducers
    reducers = analysis["reducers"]
    if reducers:
        lines.append("**Top FP Reducers:**")
        for reducer, count in sorted(reducers.items(), key=lambda x: -x[1])[:5]:
            pct = (count / analysis["total"]) * 100
            bar = "█" * min(10, int(pct / 10)) + "░" * (10 - min(10, int(pct / 10)))
            lines.append(f"  {bar} {reducer}: {count} ({pct:.0f}%)")
        lines.append("")

    # Insights
    if analysis["insights"]:
        lines.append("**🚨 Actionable Insights:**")
        for insight in analysis["insights"]:
            severity_icon = "🔴" if insight["severity"] == "high" else "🟡"
            lines.append(f"  {severity_icon} {insight['message']}")
        lines.append("")

    return "\n".join(lines)


def format_full_report(analysis: dict) -> str:
    """Format a detailed report."""
    if analysis["total"] == 0:
        return format_summary(analysis)

    lines = [format_summary(analysis)]

    # Reasons detail
    if analysis.get("reasons_by_reducer"):
        lines.append("**Reasons by Reducer:**")
        for reducer, reasons in analysis["reasons_by_reducer"].items():
            if reasons:
                lines.append(f"  {reducer}:")
                for reason in reasons[-3:]:
                    lines.append(f"    - {reason}")
        lines.append("")

    # Time patterns
    hourly = analysis.get("hourly_distribution", {})
    if hourly:
        peak_hour = max(hourly.items(), key=lambda x: x[1])[0] if hourly else None
        if peak_hour is not None:
            lines.append(f"**Peak FP Hour:** {peak_hour}:00 ({hourly[peak_hour]} FPs)")
            lines.append("")

    return "\n".join(lines)


def format_reducer_focus(analysis: dict, reducer: str) -> str:
    """Format report focused on specific reducer."""
    count = analysis["reducers"].get(reducer, 0)
    if count == 0:
        return f"No false positives recorded for '{reducer}'."

    pct = (count / analysis["total"]) * 100
    reasons = analysis.get("reasons_by_reducer", {}).get(reducer, [])

    lines = [
        f"📊 **{reducer}** FP Analysis",
        "",
        f"Count: {count} ({pct:.1f}% of all FPs)",
        "",
    ]

    if reasons:
        lines.append("**Reasons given:**")
        for reason in reasons:
            lines.append(f"  - {reason}")
        lines.append("")

    # Check for insights about this reducer
    for insight in analysis["insights"]:
        if insight.get("reducer") == reducer:
            lines.append(f"⚠️ {insight['message']}")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Analyze FP patterns for framework learning"
    )
    parser.add_argument("--summary", action="store_true", help="Quick summary only")
    parser.add_argument("--reducer", type=str, help="Focus on specific reducer")
    parser.add_argument("--since", type=str, help="Time filter (e.g., 7d, 30d)")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    # Parse since
    since_days = None
    if args.since:
        if args.since.endswith("d"):
            since_days = int(args.since[:-1])
        else:
            since_days = int(args.since)

    entries = load_fp_history(since_days)
    analysis = analyze_patterns(entries)

    if args.json:
        print(json.dumps(analysis, indent=2, default=str))
    elif args.reducer:
        print(format_reducer_focus(analysis, args.reducer))
    elif args.summary:
        print(format_summary(analysis))
    else:
        print(format_full_report(analysis))


if __name__ == "__main__":
    main()
