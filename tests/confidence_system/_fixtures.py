"""Shared test fixtures for confidence tests."""

import sys
from pathlib import Path

# Add paths for imports
_lib = str(Path(__file__).parent.parent.parent / "lib")
_hooks = str(Path(__file__).parent.parent.parent / "hooks")
if _lib not in sys.path:
    sys.path.insert(0, _lib)
if _hooks not in sys.path:
    sys.path.insert(0, _hooks)


class MockSessionState:
    """Properly configured mock for SessionState with required attributes."""

    def __init__(self):
        self.turn_count = 10
        self.confidence = 75  # CERTAINTY zone (1.0x cooldown multiplier)
        self.nudge_history = {}
        self.reducer_triggers = {}
        self.increaser_triggers = {}
        self.edit_counts = {}
        self.consecutive_blocks = {}
        self.consecutive_failures = 0
        self.files_read = []
        self.commands_failed = []
        self.commands_succeeded = []
        self.edit_history = {}
        self.original_goal = ""
        self.goal_keywords = set()
        self.goal_set_turn = 0

    def get(self, key, default=None):
        return getattr(self, key, default)
