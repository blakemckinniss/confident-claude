---
description: 📋 Beads - Persistent task tracking (create, list, close, dependencies)
argument-hint: <cmd> [args]
---

# Beads Task Tracking

Run beads commands for persistent task tracking across sessions.

**Argument:** $ARGUMENTS

## Quick Reference

| Command | Description |
|---------|-------------|
| `bd ready` | Show tasks ready to work (no blockers) |
| `bd list` | List all open tasks |
| `bd create --title="..." --type=task` | Create new task |
| `bd update <id> --status=in_progress` | Start working on task |
| `bd close <id>` | Mark task complete |
| `bd close <id1> <id2> ...` | Close multiple tasks |
| `bd show <id>` | Show task details |
| `bd dep add <issue> <blocks>` | Add dependency |
| `bd blocked` | Show blocked tasks |
| `bd stats` | Project statistics |

## Protocol

1. **If no arguments provided**, run `bd ready` to show available work
2. **If arguments provided**, run `bd $ARGUMENTS`
3. After any bd command, briefly summarize the result

## Examples

- `/bd` → runs `bd ready`
- `/bd list --status=open` → shows open tasks
- `/bd create --title="Fix login bug" --type=bug`
- `/bd close beads-001 beads-002`

## Why Beads over TodoWrite

- **Persists** across sessions (TodoWrite is ephemeral)
- **Dependencies** - track what blocks what
- **Context recovery** - `bd prime` restores state after compaction
- **Multi-project** - works across different workspaces
