---
description: 🏗️ New Project - Create fully-integrated project with beads + serena + claude
allowed-tools: Bash, Read, mcp__serena__activate_project
---

# Create New Project: $ARGUMENTS

Create a new project in ~/projects/ with full Integration Synergy setup.

```bash
~/.claude/.venv/bin/python ~/.claude/ops/new_project.py $ARGUMENTS
```

## What Gets Created

| Directory | Purpose |
|-----------|---------|
| `.beads/` | Task tracking (bd CLI) - project-isolated |
| `.claude/commands/` | Project-specific slash commands |
| `.serena/memories/` | Semantic analysis + project knowledge |
| `CLAUDE.md` | Project instructions for Claude |
| `src/` | Source code directory |
| `.git/` | Version control |

## Usage Examples

```bash
# Minimal project
/new-project my-app

# With description
/new-project my-app --description "A cool new app"

# Full template (more directories)
/new-project my-app --template full
```

## After Creation

1. `cd ~/projects/<name>`
2. Activate Serena: `mcp__serena__activate_project("<name>")`
3. Check beads: `bd ready`
4. Start working!
