---
description: 🔮 /sm [search] - Serena memories shortcut
allowed-tools: mcp__serena__list_memories, mcp__serena__read_memory, mcp__serena__search_for_pattern
---

# Serena Project Memories

$ARGUMENTS

## Workflow

If no search query provided:
1. List all memories:
   - Use `mcp__serena__list_memories`

If search query provided (`$ARGUMENTS`):
1. Search memories for the pattern:
   - Use `mcp__serena__search_for_pattern` with:
     - `substring_pattern: "$ARGUMENTS"`
     - `relative_path: ".serena/memories"`

2. Read relevant memories:
   - Use `mcp__serena__read_memory` with `memory_file_name: "<found_file>.md"`

Report: List of memories or search results with relevant content.
