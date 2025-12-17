# Session State Management

## Overview

`SessionState` is a comprehensive dataclass that tracks everything about the current session. It persists across hooks within a session and enables cross-hook communication.

## Location
- **Definition**: `lib/session_state.py`
- **Constants**: `lib/_session_constants.py`
- **State files** (checked in order):
  1. Per-project: `~/.claude/memory/projects/{project_id}/session_state.json`
  2. Global fallback: `~/.claude/memory/session_state_v3.json`

## Core State Categories

### Identity & Timing
```python
session_id: str = ""
started_at: float = 0
last_activity_time: float = 0  # For mean reversion calculation
turn_count: int = 0
```

### Domain Detection
```python
domain: str = Domain.UNKNOWN  # development, devops, research, etc.
domain_signals: list = []
domain_confidence: float = 0.0
```

### File Tracking
```python
files_read: list = []
files_edited: list = []
files_created: list = []
edit_counts: dict = {}  # file -> count
edit_history: dict = {}  # file -> [(old_hash, new_hash, ts), ...]
```

### Confidence System
```python
confidence: int = 70  # 0-100%, default WORKING tier
reputation_debt: int = 0  # Trust debt
evidence_ledger: list = []
_decay_accumulator: float = 0.0
```

### Goal Tracking (Meta-cognition)
```python
original_goal: str = ""  # First substantive user prompt
goal_set_turn: int = 0
goal_keywords: list = []
last_user_prompt: str = ""
```

### Failure Detection
```python
approach_history: list = []  # [{approach, turns, failures}]
consecutive_failures: int = 0
consecutive_blocks: dict = {}  # {hook_name: {count, first_turn, last_turn}}
```

### Autonomous Agent Patterns (v3.6)
```python
# Progress tracking
progress_log: list = []
current_feature: str = ""
current_feature_files: list = []

# Work queue (auto-discovered)
work_queue: list = []  # [{id, type, source, description, priority, status}]

# Checkpoints
checkpoints: list = []
last_checkpoint_turn: int = 0

# Session handoff
handoff_summary: str = ""
handoff_next_steps: list = []
handoff_blockers: list = []
```

### Self-Healing (v3.10)
```python
framework_errors: list = []  # [{path, error, turn}]
self_heal_required: bool = False
self_heal_target: str = ""
self_heal_attempts: int = 0
self_heal_max_attempts: int = 3
```

## Key Functions

### State I/O
```python
# lib/session_state.py
load_state() -> SessionState
save_state(state: SessionState)
reset_state()
update_state(**kwargs)  # Atomic update with lock
```

### File Tracking
```python
track_file_read(path: str)
track_file_edit(path: str)
track_file_create(path: str)
was_file_read(path: str) -> bool
```

### Confidence Updates
```python
update_confidence(delta: int, reason: str)
set_confidence(value: int)
```

### Goal Drift Detection
```python
set_goal(prompt: str)
check_goal_drift(current_activity: str) -> float  # Returns overlap %
```

### Failure Tracking
```python
track_failure(approach: str)
reset_failures()
check_sunk_cost() -> bool  # 3+ consecutive failures
```

### Nudge Management
```python
should_nudge(nudge_type: str, content: str) -> bool
record_nudge(nudge_type: str, content: str)
```

### Adaptive Thresholds
```python
get_adaptive_threshold(name: str) -> int
record_threshold_trigger(name: str)
```

## State File Locking

```python
STATE_LOCK_FILE = Path("~/.claude/cache/.state_lock")

def _acquire_state_lock() -> int:
    """Acquire file lock, returns fd."""
    
def _release_state_lock(fd: int):
    """Release file lock."""
```

## Usage in Hooks

```python
from lib.session_state import load_state, save_state

def check_something(data: dict, state: SessionState, config: dict) -> HookResult:
    # state is pre-loaded and passed in
    
    # Track file read
    if data.get("tool") == "Read":
        track_file_read(data["input"]["file_path"])
    
    # Check edit frequency
    edit_count = state.edit_counts.get(file_path, 0)
    if edit_count > 3:
        return HookResult.deny("Too many edits to same file")
    
    return HookResult.approve()
```

## Mean Reversion

State applies mean reversion on load to pull confidence toward 85%:

```python
def _apply_mean_reversion_on_load(state: SessionState):
    """Pull confidence toward target based on idle time."""
    # Called automatically in load_state()
```
