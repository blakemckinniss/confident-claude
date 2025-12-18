---
name: session-management
description: |
  Session context, context recovery, compress session, detour management,
  blocking issues, session cleanup, context limits, token management,
  long conversations, session handoff, prime context, recover context.

  Trigger phrases: compress session, save context, context recovery, prime,
  blocking issue, detour, blocked by, context too long, running out of context,
  session cleanup, handoff, continue later, pick up where we left off,
  what were we doing, recover session, load context, session state,
  long conversation, token limit, context window, summarize session.
---

# Session Management

Tools for managing session context and blocking issues.

## Context Recovery

### Prime Context (after compaction/new session)
```bash
bd prime  # Auto-called by hooks when .beads/ detected
```

### Memory Search
```bash
spark "<topic>"  # Retrieve associative memories
```

### Recent Context
```
mcp__plugin_claude-mem_claude-mem-search__get_recent_context
```

## Session Compression

### Compress Session
```bash
/compress [session.jsonl] [output.txt]
```
Converts JSONL session to token-efficient format.

### Manual Compression
```bash
compress_session.py --latest
compress_session.py <session.jsonl> output.txt
```

## Detour Management

When blocked by an issue:

### Check Detours
```bash
/detour status  # Show blocking stack
```

### Add Detour
```bash
/detour  # Push current blocker
```

### Resolve/Abandon
```bash
/detour resolve [id]   # Issue resolved
/detour abandon [id]   # Give up on blocker
/detour clear          # Clear all
```

## Beads for Session Continuity

```bash
bd ready              # Find available work
bd list --status=in_progress  # What's active
bd show <id>          # Detailed view
bd prime              # Recover full context
```

## Token Economy

### Reduce Context Usage
- Use Task tool with subagent_type=Explore for searches
- Prefer `head -N` for long outputs
- Use `/compress` for long sessions

### When Context Gets Long
1. Complete current task
2. Run `/compress` to save state
3. Start fresh session
4. Run `bd prime` to recover

## Session Close Protocol

Before ending session:
```bash
git status              # Check changes
git add <files>         # Stage code
bd sync --from-main     # Pull beads updates
git commit -m "..."     # Commit
```
