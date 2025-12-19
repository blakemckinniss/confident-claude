---
name: fix
description: "Fix all issues, fill gaps, and verify work. Use when something is broken or incomplete."
---

# /fix - The Fixer

**Purpose:** Stop talking, start fixing. Run verification, find gaps, fix them.

## Execution Sequence

### Step 1: Detect What's Broken
```bash
# Run these in parallel:
git status                           # Uncommitted changes?
npm run build 2>&1 | head -50        # Build errors?
npm test 2>&1 | head -100            # Test failures?
ruff check . 2>&1 | head -30         # Lint errors?
```

### Step 2: Run Completeness Check
```bash
~/.claude/.venv/bin/python ~/.claude/ops/void.py <target_file>
```

### Step 3: Fix Each Issue
For each error found:
1. Read the file
2. Fix the specific issue
3. Re-run the check that found it
4. Move to next

### Step 4: Verify Fixed
```bash
# All must pass before claiming done:
npm run build && npm test && ruff check .
```

## Behavior Rules

- NO explaining what you'll do - just do it
- NO asking permission - fix obvious issues
- NO partial fixes - complete each fix before moving on
- If build/test passes, you're done. Stop.

## Triggers

Use this skill when:
- User says "fix", "broken", "not working"
- Build or tests are failing
- After making changes that might break things
