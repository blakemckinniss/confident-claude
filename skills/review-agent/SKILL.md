---
name: review-agent
description: "👁️ Spawn code-reviewer agent after implementation"
---

# /review-agent - Post-Implementation Review

**Purpose:** Spawn code-reviewer agent to catch issues you missed.

## When to Use

- After significant implementation (5+ files edited)
- Before committing major changes
- `review_without_agent` reducer fired
- Want second pair of eyes without polluting context

## Execution

```
Task(
  subagent_type="code-reviewer",
  description="Review <feature/change>",
  prompt="Review these changes for: security, performance, maintainability, edge cases.
Files: <list of changed files>
Focus: <specific concerns if any>",
  run_in_background=true
)
```

## Example

```
Task(
  subagent_type="code-reviewer",
  description="Review auth refactor",
  prompt="Review authentication refactor for security issues.
Files changed:
- src/auth/login.ts
- src/auth/session.ts
- src/middleware/auth.ts
- src/utils/jwt.ts
Focus: Token handling, session expiry, CSRF protection.",
  run_in_background=true
)
```

## Why Background

Code review can run while you continue other work:

```
# Spawn reviewer in background
Task(..., run_in_background=true)

# Continue with other tasks...

# Check results when ready
TaskOutput(task_id="<id>", block=false)
```

## Token Economy

Reviewer gets full 200k to thoroughly analyze code - your context untouched.
