---
name: commit
description: "Stage, verify, and commit changes. Handles the full commit workflow."
---

# /commit - Smart Commit

**Purpose:** Execute the full commit workflow, not just `git commit`.

## Execution Sequence

### Step 1: Pre-commit Checks
```bash
~/.claude/.venv/bin/python ~/.claude/ops/upkeep.py
```
If upkeep fails, fix issues before continuing.

### Step 2: Review Changes
```bash
git status
git diff --staged
git diff
```

### Step 3: Stage Appropriately
```bash
# Stage specific files, not blindly `git add .`
git add <relevant_files>
```

Never stage:
- `.env` files
- `node_modules/`
- `.claude/tmp/`
- Unrelated changes

### Step 4: Commit
```bash
git commit -m "$(cat <<'EOF'
type: concise description

- bullet points for details if needed
EOF
)"
```

Commit types: `feat`, `fix`, `refactor`, `docs`, `test`, `chore`

### Step 5: Offer Push
Ask user: "Push to origin? (y/n)"

## Behavior Rules

- Run upkeep BEFORE committing (Hard Block #4)
- Never commit secrets or env files
- Write commit message based on actual diff, not assumptions
- Keep commits focused - one logical change per commit

## Triggers

Use this skill when:
- User says "commit", "save changes", "checkpoint"
- After completing a feature or fix
