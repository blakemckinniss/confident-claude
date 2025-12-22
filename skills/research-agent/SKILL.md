---
name: research-agent
description: "🔬 Spawn researcher agent for web lookups"
---

# /research-agent - Delegate Research

**Purpose:** Spawn researcher agent for ANY web research, preserving context.

## When to Use

- IMMEDIATELY when you need web information
- Before your 2nd WebSearch/crawl4ai call
- API documentation lookup
- Library usage research
- Best practices investigation

## Execution

```
Task(
  subagent_type="researcher",
  description="Research <topic>",
  prompt="Research <topic>. Find: current best practices, API patterns, common pitfalls. Return actionable summary.",
  run_in_background=true
)
```

## Examples

```
Task(
  subagent_type="researcher",
  description="Research React 19 patterns",
  prompt="Research React 19 server components. Find: when to use, migration patterns, performance implications, common mistakes."
)
```

## Why IMMEDIATELY

| Call # | Action |
|--------|--------|
| 1st search | SPAWN researcher instead |
| 2nd search | You've already wasted context |
| 3+ searches | Massive context pollution |

**Rule:** If you think "I should search for X", spawn researcher instead.
