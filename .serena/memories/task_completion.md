# Task Completion Checklist

## Before Claiming "Done"

### 1. Code Quality
```bash
# Lint all modified files
ruff check <modified_files>

# Fix any issues
ruff check --fix <modified_files>

# Format code
ruff format <modified_files>
```

### 2. Testing
```bash
# Run relevant tests
~/.claude/.venv/bin/pytest ~/.claude/tests/

# If modifying hooks, test manually
echo '{"tool":"ToolName","input":{}}' | ~/.claude/hooks/py ~/.claude/hooks/<runner>.py
```

### 3. Security (for ops/ changes)
```bash
# Run audit
~/.claude/hooks/py ~/.claude/ops/audit.py <file>

# Run void check
~/.claude/hooks/py ~/.claude/ops/void.py <file>
```

### 4. Git Workflow
```bash
# Check status
git status

# Stage changes
git add <files>

# Sync beads (for ephemeral branches)
bd sync --from-main

# Commit
git commit -m "descriptive message"
```

### 5. Task Tracking
```bash
# Close completed beads
bd close <id>
```

## Quality Gates

The confidence system enforces these automatically:

1. **Confidence >= 80%** required to claim "complete" or "done"
2. **No unresolved errors** in session state
3. **Lint must pass** for confidence boost
4. **Tests must pass** for confidence boost

## Verification Commands

```bash
# Quick verification
ruff check <file> && echo "✓ Lint passed"

# Full verification for production code
~/.claude/hooks/py ~/.claude/ops/audit.py <file>
~/.claude/hooks/py ~/.claude/ops/void.py <file>
```

## Pre-Commit (upkeep)

Before any commit, run:
```bash
~/.claude/hooks/py ~/.claude/ops/upkeep.py
```

This syncs requirements, checks for issues, and validates the codebase.
