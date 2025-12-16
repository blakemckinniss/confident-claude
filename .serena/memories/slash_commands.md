# Slash Commands System

## Overview

Slash commands are markdown files in `~/.claude/commands/` that wrap ops scripts and provide quick access to common operations.

## Location
- **Commands**: `~/.claude/commands/*.md` (66 commands)
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

## Complete Command Index (66 commands)

### 🧠 Cognition & Decision Making
| Command | Tool | Purpose |
|---------|------|---------|
| `/council` | council.py | Multi-perspective analysis (Judge, Critic, Skeptic, Thinker, Oracle) |
| `/judge` | oracle.py | Value assurance, ROI, YAGNI, anti-bikeshedding |
| `/critic` | oracle.py | 10th Man, attacks assumptions and exposes blind spots |
| `/skeptic` | oracle.py | Hostile review, finds ways things will fail |
| `/think` | think.py | Problem decomposition into sequential steps |
| `/consult` | oracle.py | High-level reasoning via OpenRouter |
| `/oracle` | oracle.py | External LLM consultation (judge, critic, skeptic personas) |
| `/opt` | - | Optimality check - is X the best choice? |
| `/bestway` | - | Evaluates optimal approaches for implementing X |
| `/wcwd` | - | Implementation brainstorm - explores options for X in Y |
| `/cs` | - | Quick feasibility and advisability check |
| `/worth` | - | Is X worth adding to this project? |
| `/har` | - | Have Any Recommendations for improving X? |

### 🔎 Investigation & Research
| Command | Tool | Purpose |
|---------|------|---------|
| `/research` | research.py | Web search (Tavily API) |
| `/docs` | docs.py | Fetch latest library documentation (Context7) |
| `/probe` | probe.py | Runtime API introspection |
| `/xray` | xray.py | AST structural code search |
| `/spark` | spark.py | Associative memory retrieval |
| `/find` | - | Instant file search across Windows + WSL2 |
| `/firecrawl` | firecrawl.py | Scrape websites to clean markdown/HTML/JSON |
| `/groq` | groq.py | Fast LLM inference via Groq API |

### ✅ Verification & Quality
| Command | Tool | Purpose |
|---------|------|---------|
| `/verify` | verify.py | State verification (file_exists, grep_text, port_open, command_success) |
| `/audit` | audit.py | Code quality audit (security, complexity, style) |
| `/void` | void.py | Completeness check (stubs, missing CRUD, error handling) |
| `/gaps` | gaps.py | Find implementation gaps |
| `/drift` | drift.py | Project consistency and style drift |
| `/dc` | - | Double Check - verify work, fix critical gaps |
| `/audit-hooks` | audit_hooks.py | Audit hooks against Claude Code spec |
| `/dyr` | - | Do You Respect - verify Claude follows a principle |
| `/cwms` | - | Can We Make Sure - verify and enforce X is true |

### 🛠️ Workflow & Operations
| Command | Tool | Purpose |
|---------|------|---------|
| `/scope` | scope.py | Definition of Done with checkpoints |
| `/upkeep` | upkeep.py | Pre-commit maintenance (sync requirements, check scratch) |
| `/commit` | - | Smart commit - stage, commit, offer push |
| `/detour` | detour.py | Manage blocking issue stack |
| `/fix` | - | Fix all issues, fill gaps, verify work |
| `/roi` | - | ROI Maximizer - highest-value by impact/effort |
| `/yes` | - | Autonomous Mode - execute what's best |
| `/doit` | - | Execute last discussed action without re-explaining |
| `/no` | - | Reject proposal and get alternatives |
| `/imp` | - | Research + optimal setup of X for this project |
| `/test` | - | Evaluate if something deserves test coverage |

### 💾 Memory & Context
| Command | Tool | Purpose |
|---------|------|---------|
| `/remember` | remember.py | Persistent memory (add lessons/decisions/context, view) |
| `/recall` | - | Recall memories |
| `/evidence` | evidence.py | Review evidence gathered |
| `/compress` | compress_session.py | Convert session JSONL to token-efficient format |

### 🔧 System & Browser
| Command | Tool | Purpose |
|---------|------|---------|
| `/sysinfo` | sysinfo.py | WSL2 system health (CPU/mem/disk/services) |
| `/deps` | dependency_check.py | Check dependencies (API keys, packages, binaries) |
| `/inventory` | inventory.py | Scan available binaries and system tools |
| `/housekeeping` | housekeeping.py | Manage .claude disk space |
| `/bdg` | bdg.py | Browser Debugger - Chrome DevTools Protocol CLI |
| `/playwright` | playwright.py | Browser automation setup and verification |
| `/win` | - | Windows Manager - install/uninstall via winget |

### 📋 Task Tracking
| Command | Tool | Purpose |
|---------|------|---------|
| `/bd` | - | Beads - persistent task tracking |
| `/hooks` | hooks.py | Audit, test, and fix Claude Code hooks |
| `/capabilities` | capabilities.py | Regenerate hook/ops functionality index |

### 🔮 Integration Synergy (Serena + Beads)
| Command | Tool | Purpose |
|---------|------|---------|
| `/new-project` | new_project.py | Create fully-integrated project (.beads, .claude, .serena) |
| `/serena` | serena.py | Serena MCP wrapper (status, impact, validate, memories) |
| `/si` | - | Symbol impact analysis shortcut |
| `/sv` | - | File validation shortcut |
| `/sm` | - | Project memories shortcut |

### 🚀 Advanced
| Command | Tool | Purpose |
|---------|------|---------|
| `/swarm` | swarm.py | Massive parallel oracle reasoning (10-1000 agents) |
| `/orchestrate` | orchestrate.py | Claude API code_execution for batch tasks |
| `/vo` | - | Run gaps.py + oracle analysis on changes |
| `/cr` | coderabbit.py | Run AI code review on uncommitted changes |
| `/cc` | - | Command Creator - create new slash commands |

### 🎯 Utility
| Command | Tool | Purpose |
|---------|------|---------|
| `/f` | - | Fix Console Errors - diagnose browser errors |
| `/better` | - | Improvement Analyzer - ways to make things better |
| `/useful` | - | Usefulness Amplifier - make X more actionable |
| `/reddit` | - | Open reddit.com in Chrome |
| `/comfy` | - | ComfyUI utilities |

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
