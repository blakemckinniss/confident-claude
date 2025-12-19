---
name: context
description: "Gather project context quickly. Use at session start or when switching projects."
---

# /context - Quick Orientation

**Purpose:** Rapidly understand a project's structure, stack, and conventions.

## Execution Sequence

### Step 1: Project Identity
```bash
# What is this project?
cat README.md 2>/dev/null | head -50
cat package.json 2>/dev/null | jq '{name, description, scripts}'
cat pyproject.toml 2>/dev/null | head -30
cat Cargo.toml 2>/dev/null | head -20
```

### Step 2: Structure Overview
```bash
# Directory structure
ls -la
tree -L 2 -d 2>/dev/null || find . -maxdepth 2 -type d | head -30

# Key files
ls -la src/ 2>/dev/null
ls -la app/ 2>/dev/null
ls -la lib/ 2>/dev/null
```

### Step 3: Check for Project Instructions
```bash
# Claude-specific
cat CLAUDE.md 2>/dev/null
cat .claude/CLAUDE.md 2>/dev/null

# Serena memories
mcp__serena__list_memories 2>/dev/null
```

### Step 4: Recent Activity
```bash
# What's been happening?
git log --oneline -10
git status

# Any active work?
bd list --status=in_progress
bd ready
```

### Step 5: Dependencies & Stack
```bash
# Node
cat package.json 2>/dev/null | jq '.dependencies, .devDependencies'

# Python
cat requirements.txt 2>/dev/null | head -20
cat pyproject.toml 2>/dev/null | grep -A 20 "dependencies"
```

## Output Format

After gathering context, summarize:

```
## Project: <name>
Stack: <languages/frameworks>
Key dirs: <src/, app/, lib/>
Entry points: <main files>
Test command: <how to run tests>
Build command: <how to build>
Active work: <in-progress beads>
```

## Behavior Rules

- Run checks in parallel where possible
- Skip sections that don't apply (no package.json = skip node stuff)
- Keep output concise - this is orientation, not deep dive
- Note any CLAUDE.md or project-specific conventions found
