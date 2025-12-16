#!/usr/bin/env python3
"""
Record a false positive for a confidence reducer.

Usage:
    fp.py <reducer_name> [reason]

Examples:
    fp.py edit_oscillation
    fp.py edit_oscillation "legitimate iterative work"
    fp.py cascade_block "single complex feature"

This records the FP, restores confidence, and increases future cooldown
for that reducer (adaptive learning).

Claude: Use this when you see a false positive confidence reduction.
"""

import sys
from pathlib import Path

# Add lib path
sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

from session_state import load_state, save_state, update_confidence
from confidence import (
    dispute_reducer,
    format_confidence_change,
    REDUCERS,
)


def main():
    if len(sys.argv) < 2:
        print("Usage: fp.py <reducer_name> [reason]")
        print(f"Valid reducers: {[r.name for r in REDUCERS]}")
        sys.exit(1)

    reducer_name = sys.argv[1]
    reason = " ".join(sys.argv[2:]) if len(sys.argv) > 2 else ""

    state = load_state()
    old_confidence = state.confidence

    restore_amount, message = dispute_reducer(state, reducer_name, reason)

    if restore_amount > 0:
        update_confidence(state, restore_amount, f"FP:{reducer_name}")

        # SET BLOCKING STATE - fp.py is NOT a dismiss button
        # This MUST be cleared by editing the reducer or saying SUDO
        state.fp_pending_fix = {
            "reducer": reducer_name,
            "turn": state.turn_count,
            "reason": reason,
        }

        save_state(state)
        change_msg = format_confidence_change(
            old_confidence, state.confidence, f"(FP: {reducer_name})"
        )
        print(f"{message}\n{change_msg}")

        # CRITICAL WARNING - this is the behavioral change
        print(
            "\n🚨 **FP PENDING FIX** - You MUST fix this reducer before continuing other work."
        )
        print("   Target: lib/_confidence_reducers.py or the hook that fired")
        print("   Bypass: User says SUDO or edit the reducer file")
        print("   Hard Block #14: FP = Priority 0")
    else:
        print(message)
        sys.exit(1)


if __name__ == "__main__":
    main()
