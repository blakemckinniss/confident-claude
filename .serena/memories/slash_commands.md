# Slash Commands System

## Overview

Slash commands are markdown files in `~/.claude/commands/` that wrap ops scripts and provide quick access to common operations.

## Location
- **Commands**: `~/.claude/commands/*.md` (~65 commands)
- **Ops scripts**: `~/.claude/ops/*.py` (underlying tools)

## Command File Format

```markdown
---
description: 🛡️ Brief description shown in /help
argument-hint: [arg_name]
allowed-tools: Bash
---

!`python3 $CLAUDE_PROJECT_DIR/.claude/ops/script.py $ARGUMENTS`
```

### Frontmatter Fields

| Field | Purpose |
|-------|---------|
| `description` | Help text (emoji + brief description) |
| `argument-hint` | Shows expected arguments |
| `allowed-tools` | Tool permissions (usually `Bash`) |

### Variables

| Variable | Value |
|----------|-------|
| `$ARGUMENTS` | All arguments after command |
| `$1`, `$2`, etc. | Positional arguments |
| `$CLAUDE_PROJECT_DIR` | Project root directory |

## Command Categories

### 🧠 Cognition (Decision Making)
| Command | Tool | Purpose |
|---------|------|---------|
| `/council` | council.py | Multi-perspective analysis (Judge, Critic, Skeptic) |
| `/judge` | oracle.py | Value assurance, ROI, YAGNI |
| `/critic` | oracle.py | 10th Man, attacks assumptions |
| `/skeptic` | oracle.py | Hostile review, finds failure modes |
| `/think` | think.py | Problem decomposition |
| `/consult` | oracle.py | High-level reasoning |

### 🔎 Investigation
| Command | Tool | Purpose |
|---------|------|---------|
| `/research` | research.py | Web search (Tavily API) |
| `/probe` | probe.py | Runtime API introspection |
| `/xray` | xray.py | AST structural code search |
| `/spark` | spark.py | Associative memory retrieval |
| `/docs` | docs.py | Documentation lookup |

### ✅ Verification
| Command | Tool | Purpose |
|---------|------|---------|
| `/verify` | verify.py | State verification |
| `/audit` | audit.py | Code quality (ruff, bandit, radon) |
| `/void` | void.py | Completeness check |
| `/drift` | drift.py | Style consistency |

### 🛠️ Operations
| Command | Tool | Purpose |
|---------|------|---------|
| `/scope` | scope.py | Definition of Done tracker |
| `/remember` | remember.py | Persistent memory |
| `/upkeep` | upkeep.py | Pre-commit maintenance |
| `/inventory` | inventory.py | System tool scanner |
| `/sysinfo` | sysinfo.py | System health |
| `/housekeeping` | housekeeping.py | Disk cleanup |

### 🔧 Utilities
| Command | Tool | Purpose |
|---------|------|---------|
| `/bd` | (shell) | Beads task tracking |
| `/commit` | (git) | Smart commit |
| `/gaps` | gaps.py | Find implementation gaps |
| `/detour` | detour.py | Blocking issue stack |

## Usage Examples

```bash
# Decision making
/council "Should we migrate to microservices?"
/judge "Add GraphQL layer"

# Research before coding
/research "FastAPI dependency injection 2025"
/probe "fastapi.Depends"

# Verification
/verify command_success "pytest tests/"
/audit path/to/file.py

# Task management
/scope init "Implement payment processing"
/scope check 1
```

## Creating New Commands

1. Create `~/.claude/commands/newcmd.md`
2. Add YAML frontmatter with description
3. Add execution line with `!` prefix
4. Command auto-appears in `/help`

```markdown
---
description: 🆕 My new command
argument-hint: [target]
allowed-tools: Bash
---

!`python3 $CLAUDE_PROJECT_DIR/.claude/ops/newtool.py $ARGUMENTS`
```
