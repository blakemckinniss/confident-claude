#!/usr/bin/env python3
"""Mastermind rollout management.

Usage:
    mastermind_rollout.py status     - Show current rollout status
    mastermind_rollout.py phase N    - Set rollout phase (0-4)
    mastermind_rollout.py enable     - Enable router (phase 1+)
    mastermind_rollout.py disable    - Disable mastermind
    mastermind_rollout.py stats      - Show telemetry stats
"""

import json
import sys
from pathlib import Path

CONFIG_PATH = Path.home() / ".claude" / "config" / "mastermind.json"
TELEMETRY_DIR = Path.home() / ".claude" / "tmp" / "mastermind_telemetry"

PHASES = {
    0: ("dark_launch", "Router runs but doesn't affect execution"),
    1: ("explicit_override_only", "Only ^ override triggers planning"),
    2: ("auto_planner_complex", "Auto-plan for complex tasks"),
    3: ("drift_escalation", "Mid-session drift detection enabled"),
    4: ("threshold_tuning", "Full system with tuned thresholds"),
}


def load_config() -> dict:
    if CONFIG_PATH.exists():
        return json.loads(CONFIG_PATH.read_text())
    return {}


def save_config(config: dict) -> None:
    CONFIG_PATH.write_text(json.dumps(config, indent=2))


def show_status():
    config = load_config()
    phase = config.get("rollout_phase", 0)
    phase_name, phase_desc = PHASES.get(phase, ("unknown", "Unknown phase"))

    print(f"🎯 Mastermind Rollout Status")
    print(f"=" * 40)
    print(f"Phase: {phase} ({phase_name})")
    print(f"Description: {phase_desc}")
    print()

    router = config.get("session_start_router", {})
    planner = config.get("planner", {})
    drift = config.get("drift_detection", {})

    print(f"Router enabled: {router.get('enabled', False)}")
    print(f"Planner enabled: {planner.get('enabled', False)}")
    print(f"Drift detection: {drift.get('enabled', False)}")
    print()

    # Show telemetry stats
    if TELEMETRY_DIR.exists():
        sessions = list(TELEMETRY_DIR.glob("*.jsonl"))
        print(f"Telemetry sessions: {len(sessions)}")


def set_phase(phase: int):
    if phase not in PHASES:
        print(f"❌ Invalid phase: {phase}. Valid: 0-4")
        sys.exit(1)

    config = load_config()
    config["rollout_phase"] = phase

    # Configure components based on phase
    if phase == 0:
        # Dark launch - everything disabled
        config.setdefault("session_start_router", {})["enabled"] = False
        config.setdefault("planner", {})["enabled"] = False
        config.setdefault("drift_detection", {})["enabled"] = False
    elif phase == 1:
        # Explicit override only
        config["session_start_router"]["enabled"] = True
        config["planner"]["enabled"] = True
        config["drift_detection"]["enabled"] = False
    elif phase == 2:
        # Auto-planner for complex
        config["session_start_router"]["enabled"] = True
        config["planner"]["enabled"] = True
        config["drift_detection"]["enabled"] = False
    elif phase == 3:
        # Drift escalation
        config["session_start_router"]["enabled"] = True
        config["planner"]["enabled"] = True
        config["drift_detection"]["enabled"] = True
    elif phase == 4:
        # Full system
        config["session_start_router"]["enabled"] = True
        config["planner"]["enabled"] = True
        config["drift_detection"]["enabled"] = True

    save_config(config)
    phase_name, _ = PHASES[phase]
    print(f"✅ Set rollout phase to {phase} ({phase_name})")


def enable():
    config = load_config()
    if config.get("rollout_phase", 0) == 0:
        set_phase(1)
    else:
        config.setdefault("session_start_router", {})["enabled"] = True
        save_config(config)
        print("✅ Mastermind router enabled")


def disable():
    config = load_config()
    config.setdefault("session_start_router", {})["enabled"] = False
    config.setdefault("planner", {})["enabled"] = False
    config.setdefault("drift_detection", {})["enabled"] = False
    save_config(config)
    print("✅ Mastermind disabled")


def show_stats():
    if not TELEMETRY_DIR.exists():
        print("No telemetry data yet")
        return

    sessions = list(TELEMETRY_DIR.glob("*.jsonl"))
    print(f"📊 Mastermind Telemetry Stats")
    print(f"=" * 40)
    print(f"Total sessions: {len(sessions)}")

    if not sessions:
        return

    # Count events
    event_counts = {}
    for session in sessions[-10:]:  # Last 10 sessions
        for line in session.read_text().strip().split("\n"):
            if line:
                event = json.loads(line)
                event_type = event.get("event_type", "unknown")
                event_counts[event_type] = event_counts.get(event_type, 0) + 1

    print(f"\nRecent events (last 10 sessions):")
    for event_type, count in sorted(event_counts.items()):
        print(f"  {event_type}: {count}")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "status":
        show_status()
    elif cmd == "phase":
        if len(sys.argv) < 3:
            print("Usage: mastermind_rollout.py phase N")
            sys.exit(1)
        set_phase(int(sys.argv[2]))
    elif cmd == "enable":
        enable()
    elif cmd == "disable":
        disable()
    elif cmd == "stats":
        show_stats()
    else:
        print(f"Unknown command: {cmd}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
