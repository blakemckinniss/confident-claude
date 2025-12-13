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
