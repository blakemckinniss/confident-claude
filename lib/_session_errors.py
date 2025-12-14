#!/usr/bin/env python3
"""
Session Error Tracking - Track and resolve errors.
"""

import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from _session_state_class import SessionState


def track_error(state: "SessionState", error_type: str, details: str = ""):
    """Track an error."""
    error = {
        "type": error_type,
        "details": details[:500],
        "timestamp": time.time(),
        "resolved": False,
    }
    state.errors_recent.append(error)
    state.errors_unresolved.append(error)


def resolve_error(state: "SessionState", error_pattern: str):
    """Mark errors matching pattern as resolved."""
    state.errors_unresolved = [
        e
        for e in state.errors_unresolved
        if error_pattern.lower() not in e.get("type", "").lower()
        and error_pattern.lower() not in e.get("details", "").lower()
    ]


def has_unresolved_errors(state: "SessionState") -> bool:
    """Check if there are unresolved errors."""
    cutoff = time.time() - 600
    recent_unresolved = [
        e for e in state.errors_unresolved if e.get("timestamp", 0) > cutoff
    ]
    return len(recent_unresolved) > 0
