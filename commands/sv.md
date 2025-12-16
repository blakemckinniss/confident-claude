---
description: 🔮 /sv <file> - Serena validate file shortcut
allowed-tools: mcp__serena__get_symbols_overview, mcp__ide__getDiagnostics, mcp__serena__think_about_task_adherence
---

# Validate File: $ARGUMENTS

Validate code in `$ARGUMENTS` using Serena semantic analysis.

## Workflow

1. Get symbols overview:
   - Use `mcp__serena__get_symbols_overview` with `relative_path: "$ARGUMENTS"`

2. Check for diagnostics/errors:
   - Use `mcp__ide__getDiagnostics` if available

3. Think about task adherence:
   - Use `mcp__serena__think_about_task_adherence`

Report: Symbol structure, any diagnostics/errors, and whether changes align with the current task.
