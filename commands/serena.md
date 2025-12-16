---
description: 🔮 Serena - Semantic code analysis via MCP (status, impact, validate, memories, context, search)
allowed-tools: mcp__serena__*, Bash, Read
---

# Serena MCP Integration

Run the serena ops script with: $ARGUMENTS

```bash
~/.claude/.venv/bin/python ~/.claude/ops/serena.py $ARGUMENTS
```

After running, execute the suggested MCP workflow hints to complete the operation.

## Available Subcommands

| Command | Purpose |
|---------|---------|
| `status` | Check Serena availability and project config |
| `impact <symbol>` | Analyze references to a symbol |
| `validate <file>` | Get symbols overview and diagnostics |
| `memories` | List project memories |
| `context` | Show all context sources |
| `search <pattern>` | Search codebase for pattern |

## Quick Examples

- `/serena status` - Check if Serena is available
- `/serena impact MyClass` - Find all references to MyClass
- `/serena validate src/main.ts` - Validate changes in file
- `/serena memories --search auth` - Search memories for "auth"
