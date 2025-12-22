---
name: refactor-agent
description: "🔄 Spawn refactorer agent for symbol changes"
---

# /refactor-agent - Safe Refactoring

**Purpose:** Spawn refactorer for ANY symbol rename or move.

## When to Use

- Renaming a function/class/variable
- Moving code between files
- Changing function signatures
- ANY change that might have callers

## Execution

```
Task(
  subagent_type="refactorer",
  description="Refactor <symbol>",
  prompt="Refactor <symbol>.
Change: <old> → <new>
Files: <known files, or 'find all'>
Ensure: All callers updated, no broken references."
)
```

## Example

```
Task(
  subagent_type="refactorer",
  description="Rename getUserById to findUser",
  prompt="Rename function getUserById to findUser.
Location: src/services/user.ts
Find all callers across codebase and update.
Verify no broken imports after change."
)
```

## Why MANDATORY

Manual refactoring failure modes:
1. Miss a caller → runtime error
2. Miss an import → build failure
3. Miss a test → false confidence
4. Incomplete rename → inconsistent codebase

Refactorer agent greps EVERYTHING with fresh 200k context.

**Rule:** If you're about to rename ANYTHING, spawn refactorer first.
