# Beads Task Tracking System

## Overview

Beads (`bd`) is a persistent cross-session task tracking system that replaces ephemeral TodoWrite. Tasks persist in `.beads/` directory and sync via git.

## Why Beads Over TodoWrite

- **Persistence**: Survives session restarts
- **Dependencies**: Tracks blockers between tasks
- **Git integration**: Syncs across branches
- **Context recovery**: `bd prime` restores context after compaction

## CLI Commands

### Finding Work
```bash
bd ready                    # Show issues ready to work (no blockers)
bd list --status=open       # All open issues
bd list --status=in_progress  # Active work
bd show <id>               # Detailed view with dependencies
bd blocked                 # Show blocked issues
```

### Creating & Updating
```bash
bd create --title="..." --type=task|bug|feature
bd update <id> --status=in_progress   # Claim work
bd update <id> --assignee=username    # Assign
bd close <id>                         # Mark complete
bd close <id1> <id2> ...             # Close multiple (efficient)
```

### Dependencies
```bash
bd dep add <issue> <depends-on>   # Issue depends on depends-on
bd blocked                        # Show all blocked issues
```

### Sync & Health
```bash
bd sync --from-main    # Pull beads updates from main branch
bd sync --status       # Check sync status
bd stats              # Project statistics
bd doctor             # Health check
bd prime              # Restore context after compaction
```

## Hook Integration

### Location
- **Helper module**: `hooks/_beads.py`
- **Enforcement**: `hooks/pre_tool_use_runner.py`

### Key Functions (`hooks/_beads.py`)

```python
def get_open_beads() -> list[dict]:
    """Get all open beads from bd list."""

def get_in_progress_beads() -> list[dict]:
    """Get beads with status=in_progress."""

def get_independent_beads() -> list[dict]:
    """Get beads without unresolved dependencies."""

def generate_parallel_task_calls(beads: list[dict]) -> str:
    """Generate parallel Task tool calls for multiple beads."""
```

### Enforcement Rules

1. **Bead required for edits**: After grace period, cannot Edit/Write project files without `in_progress` bead
2. **Parallel nudge**: When 2+ beads are open, nudges toward parallel Task spawns
3. **Auto-sync**: `check_beads_auto_sync` in post_tool_use_runner syncs on git commits

## Session State Integration

```python
# lib/session_state.py
recent_beads_commands: list = []  # [{cmd, turn}]
bead_enforcement_blocks: int = 0  # Cascade detection
```

## Workflow Pattern

```bash
# Start session
bd ready              # Find available work

# Claim task
bd update beads-xxx --status=in_progress

# Do work...

# Complete
bd close beads-xxx
bd sync --from-main   # Pull latest
git add . && git commit -m "..."
```

## Data Location

```
.beads/
├── issues/           # Individual issue files (YAML)
├── README.md         # Instructions
└── .beads.lock       # Sync state
```
