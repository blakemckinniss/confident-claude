---
name: plan-agent
description: "📋 Spawn Plan agent for multi-step work"
---

# /plan-agent - Delegate Planning

**Purpose:** Spawn Plan agent for ANY multi-step implementation.

## When to Use

- Task involves 2+ files
- New feature implementation
- Architecture decisions
- Refactoring work
- ANY "complex" classified task

## Execution

```
Task(
  subagent_type="Plan",
  description="Plan <feature>",
  prompt="Plan implementation of <feature>.
Requirements: <what it should do>
Constraints: <technical constraints>
Return: Step-by-step implementation plan with file changes."
)
```

## Example

```
Task(
  subagent_type="Plan",
  description="Plan auth system",
  prompt="Plan authentication system implementation.
Requirements: JWT tokens, refresh flow, session management
Constraints: Must integrate with existing user model in src/models/user.ts
Return: Ordered implementation steps, file changes, dependencies."
)
```

## Why Plan Agent

| Approach | Context Cost |
|----------|--------------|
| Inline planning | 2-5k tokens in YOUR context |
| Plan agent | 0 tokens - returns only the plan |

**Bonus:** Plan agent can explore codebase during planning without burning your context.
