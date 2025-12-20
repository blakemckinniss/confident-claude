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

## Full Auto-Management (v2.0)

The beads system is now FULLY AUTOMATIC - zero manual `bd` commands needed:

### Auto-Create from Prompts
- **Hook**: `auto_create_bead_from_prompt` (priority 3) in `_prompt_suggestions.py`
- Detects task-like keywords (implement, fix, add, create, etc.)
- Auto-creates bead with title from prompt
- Auto-claims it immediately
- Cooldown prevents spam (5 turns)

### Auto-Claim on Edit
- **Hook**: `bead_enforcement` (priority 4) in `gates/_beads.py`
- When Edit/Write starts with no in_progress bead:
  - First tries to claim an existing open bead
  - If none, auto-creates from file context
- Graceful degradation if bd unavailable

### Auto-Close on Completion
- **Hook**: `auto_close_beads` (priority 77) in `stop_runner.py`
- At session end, closes auto-created beads if:
  - Files were edited successfully
  - No unresolved errors remain
- Tracks beads via `state.auto_created_beads`

### Agent Lifecycle
- **Subagent stop**: `release_agent_beads()` in `subagent_stop.py`
- **Session cleanup**: `sync_and_cleanup_beads()` in `session_cleanup.py`
- Orphan recovery for stale assignments (120+ min)

## Hook Integration

### Location
- **Helper module**: `hooks/_beads.py`
- **Gates**: `hooks/gates/_beads.py`
- **Lifecycle**: `hooks/subagent_stop.py`, `hooks/session_cleanup.py`

### Key Functions (`hooks/_beads.py`)

```python
def get_open_beads() -> list[dict]:
    """Get all open beads from bd list."""

def get_in_progress_beads() -> list[dict]:
    """Get beads with status=in_progress."""

def get_independent_beads() -> list[dict]:
    """Get beads without unresolved dependencies."""

def generate_parallel_task_calls(beads: list[dict]) -> str:
    """Generate parallel Task tool calls with lifecycle instructions."""

def claim_bead_for_agent(bead_id, agent_id) -> dict:
    """Claim bead for agent lifecycle tracking."""

def release_bead_for_agent(bead_id, agent_id) -> bool:
    """Release bead from agent."""

def get_stale_bead_assignments(timeout_minutes) -> list:
    """Find orphaned agent assignments."""
```

### Automatic Lifecycle Hooks

| Hook | Event | Action |
|------|-------|--------|
| `subagent_stop.py` | SubagentStop | Auto-releases beads claimed by agent |
| `session_cleanup.py` | SessionEnd | Syncs beads, recovers orphaned assignments |
| `session_init.py` | SessionStart | Background beads sync |
| `_prompt_suggestions.py` | UserPromptSubmit | Periodic background sync (10 min) |
| `_hooks_tracking.py` | PostToolUse (git) | Auto-sync on commit/push |

### Enforcement Rules

1. **Bead required for edits**: After grace period, cannot Edit/Write project files without `in_progress` bead
2. **Parallel nudge**: When 2+ beads are open, nudges toward parallel Task spawns
3. **Auto-sync**: `check_beads_auto_sync` syncs on git commits
4. **Orphan recovery**: Session cleanup auto-recovers beads stale >2 hours
5. **Agent release**: Subagent stop auto-releases claimed beads

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
