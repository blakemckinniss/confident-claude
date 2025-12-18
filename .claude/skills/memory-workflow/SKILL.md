---
name: memory-workflow
description: |
  Remember something, recall past work, what did we do before, lessons learned,
  decisions made, context from previous sessions, persistent memory, evidence,
  cross-session recall, project history, past conversations, knowledge base.

  Trigger phrases: remember this, store for later, what did we do before,
  recall past work, lessons learned, decisions we made, search memories,
  find previous session, save this knowledge, note this down, log this,
  persistent storage, cross-session, remember for next time, don't forget,
  we discussed this before, last time we, previously we decided,
  project history, conversation history, past context, earlier today,
  yesterday we, last week, previous session, old conversation,
  knowledge management, organizational memory, team knowledge, shared learning,
  capture insight, record decision, document rationale, why did we,
  what was the reason, decision log, architecture decision record, ADR.
---

# Memory Workflow

Tools for persistent memory across sessions.

## Primary Tools

### remember.py - Store Memories
```bash
remember.py add lessons "What was learned"
remember.py add decisions "Decision and rationale"
remember.py add context "Important context"
remember.py view [type]
```

### spark.py - Recall Memories
```bash
spark.py "<topic>"
```

### evidence.py - Session Evidence
```bash
evidence.py review
evidence.py session <id>
```

### Claude-Mem MCP
- `mcp__...__search` - Full search
- `mcp__...__decisions` - Find decisions
- `mcp__...__changes` - Find changes
- `mcp__...__how_it_works` - Architecture

## Slash Commands
- `/remember add <type> "<text>"` - Store
- `/remember view` - View all
- `/spark "<topic>"` - Recall
- `/evidence review` - Session evidence

## Memory Types
| Type | Use For |
|------|---------|
| `lessons` | Learned from errors |
| `decisions` | Design choices |
| `context` | Project context |
