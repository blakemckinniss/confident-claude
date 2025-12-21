#!/usr/bin/env python3
"""Analyze Groq routing decisions for threshold tuning.

Usage:
    routing_analysis.py [--session SESSION_ID] [--json]

Examples:
    routing_analysis.py                    # Analyze all sessions
    routing_analysis.py --session abc123   # Analyze specific session
    routing_analysis.py --json             # Output as JSON
"""

import argparse
import json
import sys
from pathlib import Path

# Add lib to path
sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

from mastermind.telemetry import get_routing_analysis, TELEMETRY_DIR


def format_analysis(analysis: dict) -> str:
    """Format analysis for human reading."""
    if "error" in analysis:
        return f"❌ {analysis['error']}"

    lines = [
        f"📊 Routing Analysis ({analysis['event_count']} decisions)",
        "",
        "## Classification Distribution",
    ]

    dist = analysis.get("classification_distribution", {})
    total = sum(dist.values())
    for cls, count in sorted(dist.items()):
        pct = count / total * 100 if total else 0
        bar = "█" * int(pct / 5)
        lines.append(f"  {cls:10} {count:4} ({pct:5.1f}%) {bar}")

    lines.append("")
    lines.append("## Context Signal Correlation")

    signals = analysis.get("context_signal_correlation", {})
    for cls, sigs in signals.items():
        if any(v > 0 for v in sigs.values()):
            sig_strs = [f"{k}={v}" for k, v in sigs.items() if v > 0]
            lines.append(f"  {cls}: {', '.join(sig_strs)}")

    lines.append("")
    lines.append("## Average Confidence by Class")

    avg_conf = analysis.get("average_confidence_by_class", {})
    for cls, conf in sorted(avg_conf.items()):
        lines.append(f"  {cls:10} {conf:.1f}%")

    suggestions = analysis.get("suggested_adjustments", [])
    if suggestions:
        lines.append("")
        lines.append("## Suggested Adjustments")
        for s in suggestions:
            lines.append(f"  ⚠️ {s}")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Analyze Groq routing decisions")
    parser.add_argument("--session", help="Specific session ID to analyze")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    # Check telemetry directory exists
    if not TELEMETRY_DIR.exists():
        print(f"❌ No telemetry directory at {TELEMETRY_DIR}")
        sys.exit(1)

    analysis = get_routing_analysis(args.session)

    if args.json:
        print(json.dumps(analysis, indent=2))
    else:
        print(format_analysis(analysis))


if __name__ == "__main__":
    main()
