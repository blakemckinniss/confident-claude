---
description: 🧠 Serena Memory - Lifecycle management (status, stale, prune, refresh)
allowed-tools: Bash, Read, mcp__serena__*
---

# Serena Memory Lifecycle

Run the memory lifecycle tool with: $ARGUMENTS

```bash
~/.claude/.venv/bin/python ~/.claude/ops/serena_memory_lifecycle.py $ARGUMENTS
```

## Available Subcommands

| Command | Purpose |
|---------|---------|
| `status` | Show memory health overview |
| `stale` | List stale memories with details |
| `validate [name]` | Check memory accuracy |
| `prune [--dry-run]` | Archive outdated memories |
| `refresh [--auto]` | Generate refresh instructions |
| `init` | Initialize metadata tracking |

## Quick Examples

- `/serena-mem status` - Overview of all memory health
- `/serena-mem stale` - See which memories need updating
- `/serena-mem refresh --auto` - Get commands to refresh structural memories
- `/serena-mem prune --dry-run` - Preview what would be archived
