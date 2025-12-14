#!/usr/bin/env python3
"""
Session Confidence - Confidence tracking and evidence ledger.
"""

import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from _session_state_class import SessionState


def get_turns_since_op(state: "SessionState", op_name: str) -> int:
    """Get turns since an ops command was run."""
    last_turn = state.ops_turns.get(op_name, -1)
    if last_turn < 0:
        return 999
    return state.turn_count - last_turn


def add_evidence(state: "SessionState", evidence_type: str, content: str):
    """Add evidence to the ledger."""
    state.evidence_ledger.append(
        {
            "type": evidence_type,
            "content": content[:200],
            "turn": state.turn_count,
            "timestamp": time.time(),
        }
    )


def update_confidence(state: "SessionState", delta: int, reason: str = ""):
    """Update confidence level with bounds checking."""
    old = state.confidence
    state.confidence = max(0, min(100, state.confidence + delta))
    if reason:
        add_evidence(state, "confidence_change", f"{old} -> {state.confidence}: {reason}")


def set_confidence(state: "SessionState", value: int, reason: str = ""):
    """Set confidence to absolute value with audit trail."""
    old = state.confidence
    state.confidence = max(0, min(100, value))
    if old != state.confidence:
        add_evidence(
            state,
            "confidence_set",
            f"{old} -> {state.confidence}: {reason or 'direct set'}",
        )
        try:
            from confidence import log_confidence_change

            log_confidence_change(state, old, state.confidence, reason or "direct set")
        except ImportError:
            pass
