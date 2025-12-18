---
description: 🔮 /si <symbol> - Serena impact analysis shortcut
allowed-tools: mcp__serena__find_symbol, mcp__serena__find_referencing_symbols, mcp__serena__think_about_collected_information
---

# Symbol Impact Analysis: $ARGUMENTS

Analyze the impact of changes to symbol `$ARGUMENTS` using Serena semantic tools.

## Workflow

1. First, find the symbol definition:
   - Use `mcp__serena__find_symbol` with `name_path_pattern: "$ARGUMENTS"`, `include_body: false`, `depth: 1`

2. Then find all references:
   - Use `mcp__serena__find_referencing_symbols` with `name_path: "$ARGUMENTS"`

3. Finally, think about the collected information:
   - Use `mcp__serena__think_about_collected_information`

Report: Symbol location, all callers/references, and potential impact of modifications.
