---
name: completeness-checking
description: |
  Find gaps, missing code, incomplete implementations, stubs, TODO comments,
  missing error handling, missing tests, dead code, unused exports, orphan files,
  coverage gaps, audit code, void check, completeness verification.

  Trigger phrases: find gaps, what's missing, incomplete code, stub implementation,
  TODO comments, missing error handling, missing tests, dead code, unused code,
  orphan files, coverage gaps, audit this, void check, completeness check,
  is this complete, did I miss anything, find stubs, NotImplementedError,
  pass statements, placeholder code, unfinished, partial implementation,
  missing CRUD operations, missing validation, missing edge cases.
---

# Completeness Checking

Tools for finding gaps and missing implementations.

## Primary Tools

### void.py - Completeness Check
```bash
void.py <file_or_dir>
```
Finds:
- Stub implementations (`pass`, `...`, `NotImplementedError`)
- Missing CRUD operations
- Missing error handling
- TODO/FIXME comments
- Incomplete patterns

### gaps.py - Gap Analysis
```bash
gaps.py <file_or_dir>
```
Similar to void but with different heuristics.

### audit.py - Security/Quality Audit
```bash
audit.py <file>
```
Static analysis and anti-pattern detection.

## Slash Commands

| Command | Purpose |
|---------|---------|
| `/void <path>` | Completeness check |
| `/gaps <path>` | Gap analysis |
| `/audit <path>` | Security audit |
| `/vo <path>` | Void + oracle analysis |

## What They Find

### Stubs & Placeholders
```python
def process():
    pass  # ← DETECTED

def handler():
    ...  # ← DETECTED

def todo():
    raise NotImplementedError  # ← DETECTED
```

### Missing Patterns
- Create without Delete
- Read without error handling
- Update without validation
- API without authentication check

### Dead Code
- Unused imports
- Unreachable branches
- Orphaned helper functions
- Stale test files

## Pre-Production Checklist

Before deploying to `~/.claude/ops/`:
```bash
audit.py <file>   # Security check
void.py <file>    # Completeness check
```

Both must pass for production writes.

## Integration with Workflow

```bash
# After implementing feature
void.py src/feature/

# Before PR
gaps.py .

# Production code gate
audit.py ~/.claude/ops/new_tool.py && void.py ~/.claude/ops/new_tool.py
```
