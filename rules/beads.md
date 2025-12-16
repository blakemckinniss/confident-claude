# Beads Task Tracking

**All task tracking uses beads (`bd`).** The TodoWrite tool is FORBIDDEN.

## Quick Reference

| Action | Command |
|--------|---------|
| Find work | `bd ready` |
| Create task | `bd create "Title"` |
| Start work | `bd update <id> --status=in_progress` |
| Complete | `bd close <id>` |
| Dependencies | `bd dep add <issue> <depends-on>` |
| Check status | `bd list` |

## Session Workflow

1. `bd ready` - see available work
2. `bd update <id> --status=in_progress` - claim task
3. Do the work
4. `bd close <id>` - mark complete

## Why Beads Over TodoWrite

- Persists across sessions (TodoWrite is ephemeral)
- Tracks dependencies and blockers
- Enables context recovery via `bd prime`
- Works across projects

## Advanced Commands

```bash
bd list --status=open      # All open issues
bd list --status=in_progress  # Active work
bd show <id>               # Detailed view with deps
bd blocked                 # Show blocked issues
bd stats                   # Project statistics
bd doctor                  # Health check
bd sync --from-main        # Pull from main branch
```

## Project Isolation

- **Beads database**: GLOBAL (`~/.claude/.beads/beads.db`) - tasks visible everywhere
- **Agent assignments**: PER-PROJECT (`<project>/.beads/agent_assignments.jsonl`)

Each project has its own `.beads/` directory for agent lifecycle tracking.

## Agent Lifecycle (Task Agents)

When spawning Task agents to work on beads:

```bash
# Agent claims bead (writes to project's agent_assignments.jsonl)
~/.claude/.venv/bin/python ~/.claude/ops/bead_claim.py <bead_id>

# Agent releases bead when done
~/.claude/.venv/bin/python ~/.claude/ops/bead_release.py <bead_id>
```

### Orphan Recovery

Beads claimed by crashed/stuck agents are auto-recovered:

| Status | Threshold | Action |
|--------|-----------|--------|
| Stale | 30+ min | Warning |
| Stalled | 60+ min | Alert |
| Orphan | 120+ min | Auto-revert to open |

```bash
# Check for orphans across all projects
~/.claude/.venv/bin/python ~/.claude/ops/bead_orphan_check.py --all

# Run daemon for continuous monitoring
~/.claude/.venv/bin/python ~/.claude/ops/bead_lifecycle_daemon.py --daemon
```
