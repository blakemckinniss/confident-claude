#!/usr/bin/env python3
"""
Confidence Realignment - Rock bottom recovery protocol.

When confidence hits rock bottom (<=10), forces explicit realignment
with user through guided questions.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from session_state import SessionState

from _confidence_constants import THRESHOLD_ROCK_BOTTOM, ROCK_BOTTOM_RECOVERY_TARGET

# =============================================================================

# Realignment questions to ask when at rock bottom
REALIGNMENT_QUESTIONS = [
    {
        "question": "What is the primary goal you want me to accomplish right now?",
        "header": "Goal",
        "options": [
            {
                "label": "Continue current task",
                "description": "Keep working on what we were doing",
            },
            {
                "label": "New task",
                "description": "Start fresh with a different objective",
            },
            {"label": "Debug/fix issues", "description": "Focus on resolving problems"},
        ],
    },
    {
        "question": "How should I approach this work?",
        "header": "Approach",
        "options": [
            {
                "label": "Careful & thorough",
                "description": "Take time, verify everything",
            },
            {
                "label": "Fast & iterative",
                "description": "Move quickly, fix issues as they come",
            },
            {
                "label": "Ask before acting",
                "description": "Check with you before each step",
            },
        ],
    },
    {
        "question": "What went wrong that led to this confidence drop?",
        "header": "Issue",
        "options": [
            {
                "label": "Misunderstood request",
                "description": "I wasn't clear on what you wanted",
            },
            {
                "label": "Technical errors",
                "description": "Code/commands failed repeatedly",
            },
            {"label": "Wrong approach", "description": "Strategy wasn't working"},
            {"label": "Nothing wrong", "description": "Confidence dropped unfairly"},
        ],
    },
]


def is_rock_bottom(confidence: int) -> bool:
    """Check if confidence is at rock bottom threshold."""
    return confidence <= THRESHOLD_ROCK_BOTTOM


def get_realignment_questions() -> list[dict]:
    """Get the realignment questions for AskUserQuestion tool."""
    return REALIGNMENT_QUESTIONS


def check_realignment_complete(state: "SessionState") -> bool:
    """Check if realignment has been completed this session."""
    return state.nudge_history.get("rock_bottom_realignment", {}).get(
        "completed", False
    )


def mark_realignment_complete(state: "SessionState") -> int:
    """Mark realignment as complete and return new confidence."""
    state.nudge_history["rock_bottom_realignment"] = {
        "completed": True,
        "turn": state.turn_count,
    }
    return ROCK_BOTTOM_RECOVERY_TARGET


def reset_realignment(state: "SessionState"):
    """Reset realignment tracking (called when confidence rises above rock bottom)."""
    if "rock_bottom_realignment" in state.nudge_history:
        state.nudge_history["rock_bottom_realignment"]["completed"] = False


# =============================================================================
# MEAN REVERSION INTEGRATION
