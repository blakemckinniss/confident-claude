---
name: careful
description: "Careful editing mode for critical files. Extra verification before and after."
---

# /careful - High-Stakes Editing

**Purpose:** Extra guardrails when editing critical code (auth, payments, data, config).

## When to Use

- Files containing: auth, session, payment, billing, migration, config
- Shared utilities used by many files
- Database schema changes
- Any file with "DO NOT EDIT" or similar warnings

## Pre-Edit Checklist

### 1. Understand Current State
```bash
# Read the full file first
Read <file>

# Check recent changes
git log -5 --oneline -- <file>
git blame <file> | head -50

# Find all callers
grep -r "function_name" --include="*.{ts,tsx,py}" .
```

### 2. Create Safety Net
```bash
# Track this work
bd create "Careful edit: <description>" --type=task
bd update <id> --status=in_progress
```

### 3. Understand Impact
```bash
# If using Serena
mcp__serena__find_referencing_symbols for changed functions
```

## During Edit

- Make ONE focused change at a time
- Keep the diff minimal
- Preserve existing behavior unless explicitly changing it
- Add comments explaining non-obvious changes

## Post-Edit Checklist

### 1. Verify Syntax
```bash
# TypeScript
npx tsc --noEmit

# Python
python -m py_compile <file>
ruff check <file>
```

### 2. Run Related Tests
```bash
# Find and run related tests
pytest tests/*<module_name>* -v
npm test -- --grep "<module_name>"
```

### 3. Check Callers Still Work
```bash
# Re-run the grep from pre-edit
# Verify each caller handles new behavior
```

### 4. Audit
```bash
~/.claude/.venv/bin/python ~/.claude/ops/audit.py <file>
```

## Behavior Rules

- NO bulk changes - one thing at a time
- NO "while I'm here" additions
- MUST verify callers after signature changes
- Close bead only after all checks pass
