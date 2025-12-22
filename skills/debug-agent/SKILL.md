---
name: debug-agent
description: "🐛 Spawn debugger agent for stuck loops"
---

# /debug-agent - Fresh Debugging Perspective

**Purpose:** Spawn a debugger agent when stuck in a loop, getting fresh 200k context.

## When to Use

- 3+ edit attempts on same file without success
- Stuck in debugging loop (edit → test → fail → repeat)
- Need fresh perspective on mysterious bug
- `debugging_without_agent` reducer fired

## Execution

```
Task(
  subagent_type="debugger",
  description="Debug <issue summary>",
  prompt="Issue: <symptoms>\nAttempted: <what you tried>\nFiles: <relevant paths>\nFind root cause."
)
```

## Example

```
Task(
  subagent_type="debugger",
  description="Debug hydration mismatch",
  prompt="React hydration mismatch in ProductCard component.
Symptoms: 'Text content does not match server-rendered HTML'
Attempted: Wrapped random() in useEffect, added suppressHydrationWarning
Files: src/components/ProductCard.tsx, src/hooks/useProduct.ts
Find root cause and fix."
)
```

## Why This Works

| Problem | Solution |
|---------|----------|
| Tunnel vision | Fresh agent has no prior assumptions |
| Context pollution | Your 200k not consumed by debugging |
| Sunk cost fallacy | Agent starts clean, no attachment to failed approaches |

**Circuit breaker:** After 3 failed attempts, the debugger agent often finds what you missed.
