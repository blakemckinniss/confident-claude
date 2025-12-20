#!/usr/bin/env python3
"""
Session Goals - Goal tracking, drift detection, and sunk cost detection.
"""

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from _session_state_class import SessionState


def set_goal(state: "SessionState", prompt: str):
    """Set the original goal if not already set."""
    if state.original_goal:
        return

    skip_patterns = [
        r"^(hi|hello|hey|thanks|ok|yes|no|sure)\b",
        r"^(commit|push|pr|status|help)\b",
        r"^/",
    ]
    prompt_lower = prompt.lower().strip()
    for pattern in skip_patterns:
        if re.match(pattern, prompt_lower):
            return

    state.original_goal = prompt[:200]
    state.goal_set_turn = state.turn_count

    stop_words = {
        "the",
        "a",
        "an",
        "is",
        "are",
        "to",
        "for",
        "in",
        "on",
        "with",
        "and",
        "or",
        "but",
        "can",
        "you",
        "i",
        "me",
        "my",
        "this",
        "that",
        "it",
        "be",
        "do",
        "have",
        "will",
        "would",
        "could",
        "should",
    }
    words = re.findall(r"\b[a-z]{3,}\b", prompt_lower)
    state.goal_keywords = [w for w in words if w not in stop_words][:10]


def check_goal_drift(state: "SessionState", current_activity: str) -> tuple[bool, str]:
    """Check if current activity has drifted from original goal."""
    if not state.original_goal or not state.goal_keywords:
        return False, ""

    if state.turn_count - state.goal_set_turn < 5:
        return False, ""

    activity_lower = current_activity.lower()
    matches = sum(1 for kw in state.goal_keywords if kw in activity_lower)
    overlap_ratio = matches / len(state.goal_keywords) if state.goal_keywords else 0

    # FIX: Lowered threshold from 20% to 10%
    # 20% was too strict - related subtasks often share <20% keywords
    # but are still aligned with the original goal (e.g., audit → fix specific issue)
    if overlap_ratio < 0.1:
        return (
            True,
            f'📍 GOAL ANCHOR: "{state.original_goal[:80]}..."\n🔀 CURRENT: {current_activity[:60]}\n⚠️ Low overlap ({overlap_ratio:.0%}) - verify alignment',
        )

    return False, ""


# =============================================================================
# SUNK COST DETECTOR
# =============================================================================


def track_failure(state: "SessionState", approach_signature: str):
    """Track a failure for the current approach."""
    state.consecutive_failures += 1
    state.last_failure_turn = state.turn_count

    for entry in state.approach_history:
        if entry.get("signature") == approach_signature:
            entry["failures"] = entry.get("failures", 0) + 1


def reset_failures(state: "SessionState"):
    """Reset failure count (on success)."""
    state.consecutive_failures = 0


def check_sunk_cost(state: "SessionState") -> tuple[bool, str]:
    """Check if stuck in sunk cost trap."""
    if state.consecutive_failures >= 3:
        return (
            True,
            f"🔄 SUNK COST: {state.consecutive_failures} consecutive failures.\n💡 If starting fresh, would you still pick this approach?",
        )

    for entry in state.approach_history:
        turns = entry.get("turns", 0)
        failures = entry.get("failures", 0)
        if turns >= 5 and failures >= 2:
            sig = entry.get("signature", "unknown")[:40]
            return (
                True,
                f"🔄 SUNK COST: {turns} turns on `{sig}` with {failures} failures.\n💡 Consider: pivot vs persist?",
            )

    return False, ""
