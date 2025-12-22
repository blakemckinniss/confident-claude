---
name: explore-agent
description: "🔍 Spawn Explore agent for codebase understanding"
---

# /explore-agent - Delegate Exploration

**Purpose:** Spawn an Explore agent to understand codebase structure, preserving your context.

## When to Use

- Need to understand a new codebase area
- Searching for files/patterns across many directories
- Would otherwise use 5+ Grep/Glob/Read calls sequentially
- Want to preserve master thread context (200k limit)

## Execution

```
Task(
  subagent_type="Explore",
  description="<3-5 word summary>",
  prompt="<detailed exploration goal>",
  run_in_background=true  # Optional: run async
)
```

## Examples

**Find authentication code:**
```
Task(
  subagent_type="Explore",
  description="Find auth implementation",
  prompt="Find all authentication-related code: login, session management, JWT handling, middleware. Return file paths and key function names."
)
```

**Understand module structure:**
```
Task(
  subagent_type="Explore",
  description="Map reducer architecture",
  prompt="Map the lib/reducers/ package: what categories exist, how are they organized, what's the base class pattern?"
)
```

## Token Economy

| Approach | Context Cost |
|----------|--------------|
| 5+ sequential Grep/Read | 3-8k tokens in YOUR context |
| Explore agent | 0 tokens - agent uses its own 200k |

**Result:** Agent returns summary, your context stays clean.
