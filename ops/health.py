#!/usr/bin/env python3
"""
Entity Model Health Check - Self-diagnostic immune system scan.

Validates framework health across multiple dimensions:
- Hook registration: Are all hooks loading correctly?
- Confidence system: Is the regulatory system functioning?
- FP history: Are there patterns indicating broken detection?
- Session state: Is state persisting correctly?

Usage:
    health.py              # Full health check
    health.py --quick      # Just critical checks
    health.py --json       # JSON output for scripts

Entity Model: This is the "immune system scan" - proactive
self-diagnosis to catch problems before they cause harm.
"""

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

CLAUDE_DIR = Path.home() / ".claude"
FP_HISTORY_FILE = CLAUDE_DIR / "tmp" / "fp_history.jsonl"
CONFIDENCE_JOURNAL = CLAUDE_DIR / "tmp" / "confidence_journal.log"
MEMORY_DIR = CLAUDE_DIR / "memory"


def get_state_file() -> Path:
    """Find the active session state file (per-project or global fallback)."""
    # Check for project-specific state first
    projects_dir = MEMORY_DIR / "projects"
    if projects_dir.exists():
        # Find most recently modified project state
        project_states = list(projects_dir.glob("*/session_state.json"))
        if project_states:
            return max(project_states, key=lambda p: p.stat().st_mtime)

    # Global fallback
    global_state = MEMORY_DIR / "session_state_v3.json"
    if global_state.exists():
        return global_state

    # Legacy location
    return CLAUDE_DIR / "tmp" / "session_state.json"


def check_hooks() -> dict:
    """Check hook registration status."""
    result = {"status": "healthy", "issues": [], "counts": {}}

    hooks_dir = CLAUDE_DIR / "hooks"
    runners = [
        "pre_tool_use_runner.py",
        "post_tool_use_runner.py",
        "user_prompt_submit_runner.py",
        "stop_runner.py",
    ]

    for runner in runners:
        runner_path = hooks_dir / runner
        if not runner_path.exists():
            result["issues"].append(f"Missing runner: {runner}")
            result["status"] = "degraded"
            continue

        try:
            content = runner_path.read_text()
            hook_count = content.count("@register_hook")
            result["counts"][runner.replace("_runner.py", "")] = hook_count
        except Exception as e:
            result["issues"].append(f"Cannot read {runner}: {e}")

    try:
        sys.path.insert(0, str(hooks_dir))
        import ast
        for runner in runners:
            runner_path = hooks_dir / runner
            if runner_path.exists():
                ast.parse(runner_path.read_text())
    except SyntaxError as e:
        result["issues"].append(f"Syntax error: {e.filename}:{e.lineno}")
        result["status"] = "critical"
    except Exception:
        _ = None  # Non-critical errors ignored

    total = sum(result["counts"].values())
    result["total_hooks"] = total

    return result


def check_confidence_system() -> dict:
    """Check confidence system health."""
    result = {"status": "healthy", "issues": [], "metrics": {}}
    state_file = get_state_file()

    if not state_file.exists():
        result["issues"].append("No session state file")
        result["status"] = "unknown"
        return result

    try:
        state = json.loads(state_file.read_text())
        confidence = state.get("confidence", 0)
        result["metrics"]["current_confidence"] = confidence
        result["metrics"]["turn_count"] = state.get("turn_count", 0)
        result["metrics"]["streak"] = state.get("nudge_history", {}).get(
            "_confidence_streak", 0
        )

        if confidence < 0 or confidence > 100:
            result["issues"].append(f"Invalid confidence: {confidence}")
            result["status"] = "critical"
        elif confidence < 50:
            result["issues"].append(f"Low confidence: {confidence}%")
            result["status"] = "warning"
        elif confidence < 80:
            result["issues"].append(f"Below stasis: {confidence}%")
            result["status"] = "degraded"

    except Exception as e:
        result["issues"].append(f"Cannot read state: {e}")
        result["status"] = "critical"

    if CONFIDENCE_JOURNAL.exists():
        try:
            lines = CONFIDENCE_JOURNAL.read_text().strip().split("\n")[-20:]
            crashes = []
            for line in lines:
                if "→" in line:
                    try:
                        after_val = int(line.split("→")[1].split()[0])
                        if after_val < 50:
                            crashes.append(line)
                    except (ValueError, IndexError):
                        continue
            if crashes:
                result["metrics"]["recent_crashes"] = len(crashes)
                if len(crashes) > 3:
                    result["issues"].append(f"{len(crashes)} recent confidence crashes")
                    result["status"] = "warning"
        except Exception:
            _ = None  # Journal analysis non-critical

    return result


def check_fp_history() -> dict:
    """Check false positive history for patterns."""
    result = {"status": "healthy", "issues": [], "metrics": {}}

    if not FP_HISTORY_FILE.exists():
        result["metrics"]["total_fps"] = 0
        return result

    try:
        entries = []
        cutoff = datetime.now() - timedelta(days=14)

        with FP_HISTORY_FILE.open() as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    ts = datetime.fromisoformat(entry["timestamp"])
                    if ts >= cutoff:
                        entries.append(entry)
                except (json.JSONDecodeError, KeyError):
                    continue

        result["metrics"]["total_fps"] = len(entries)

        if entries:
            from collections import Counter

            reducer_counts = Counter(e.get("reducer", "unknown") for e in entries)
            result["metrics"]["by_reducer"] = dict(reducer_counts.most_common(5))

            for reducer, count in reducer_counts.items():
                if count >= 5:
                    result["issues"].append(f"High FP rate: {reducer} ({count} FPs)")
                    result["status"] = "warning"
                elif count >= 3:
                    result["issues"].append(f"Elevated FP rate: {reducer} ({count} FPs)")
                    if result["status"] == "healthy":
                        result["status"] = "degraded"

    except Exception as e:
        result["issues"].append(f"Cannot analyze FP history: {e}")
        result["status"] = "unknown"

    return result


def check_session_state() -> dict:
    """Check session state sanity."""
    result = {"status": "healthy", "issues": [], "metrics": {}}
    state_file = get_state_file()

    if not state_file.exists():
        result["status"] = "unknown"
        result["issues"].append("No session state")
        return result

    try:
        state = json.loads(state_file.read_text())

        required = ["confidence", "turn_count", "files_read", "files_edited"]
        for field in required:
            if field not in state:
                result["issues"].append(f"Missing field: {field}")
                result["status"] = "degraded"

        state_size = state_file.stat().st_size
        result["metrics"]["state_size_kb"] = round(state_size / 1024, 1)

        if state_size > 100_000:
            result["issues"].append(f"State file bloated: {state_size/1024:.0f}KB")
            result["status"] = "warning"

        files_read = len(state.get("files_read", []))
        files_edited = len(state.get("files_edited", []))
        result["metrics"]["files_read"] = files_read
        result["metrics"]["files_edited"] = files_edited

        if files_read > 500:
            result["issues"].append(f"Excessive files_read: {files_read}")
            result["status"] = "warning"

    except Exception as e:
        result["issues"].append(f"Cannot read state: {e}")
        result["status"] = "critical"

    return result


def run_health_check(quick: bool = False) -> dict:
    """Run full health check."""
    results = {
        "timestamp": datetime.now().isoformat(),
        "overall": "healthy",
        "checks": {},
    }

    results["checks"]["hooks"] = check_hooks()
    results["checks"]["confidence"] = check_confidence_system()

    if not quick:
        results["checks"]["fp_history"] = check_fp_history()
        results["checks"]["session_state"] = check_session_state()

    statuses = [c["status"] for c in results["checks"].values()]
    if "critical" in statuses:
        results["overall"] = "critical"
    elif "warning" in statuses:
        results["overall"] = "warning"
    elif "degraded" in statuses:
        results["overall"] = "degraded"
    elif "unknown" in statuses:
        results["overall"] = "unknown"

    return results


def format_output(results: dict) -> str:
    """Format results for display."""
    lines = []

    status_emoji = {
        "healthy": "💚",
        "degraded": "🟡",
        "warning": "🟠",
        "critical": "🔴",
        "unknown": "⚪",
    }

    emoji = status_emoji.get(results["overall"], "⚪")
    lines.append(f"{emoji} **ENTITY HEALTH**: {results['overall'].upper()}")
    lines.append("")

    for name, check in results["checks"].items():
        check_emoji = status_emoji.get(check["status"], "⚪")
        lines.append(f"### {check_emoji} {name.replace('_', ' ').title()}")

        if check.get("metrics"):
            for key, value in check["metrics"].items():
                if isinstance(value, dict):
                    lines.append(f"  {key}:")
                    for k, v in value.items():
                        lines.append(f"    - {k}: {v}")
                else:
                    lines.append(f"  {key}: {value}")

        if check.get("issues"):
            for issue in check["issues"]:
                lines.append(f"  ⚠️ {issue}")

        lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Entity Model health check")
    parser.add_argument("--quick", action="store_true", help="Quick check only")
    parser.add_argument("--json", action="store_true", help="JSON output")
    args = parser.parse_args()

    results = run_health_check(quick=args.quick)

    if args.json:
        print(json.dumps(results, indent=2))
    else:
        print(format_output(results))

    if results["overall"] == "critical":
        sys.exit(2)
    elif results["overall"] in ("warning", "degraded"):
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
