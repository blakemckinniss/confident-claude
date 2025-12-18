# Memory Index

**Navigation guide for Serena memories.** Read this first to identify which memories are relevant.

## Memory Categories

| Category | Count | Purpose |
|----------|-------|---------|
| **Core structural** | ~15 | Architecture, tools, hooks - read these |
| **Session logs** | ~130 | Ephemeral session_* files - auto-generated, rarely need |

## Quick Reference

| Memory | When to Read |
|--------|--------------|
| `project_overview` | **START HERE** - First memory for any task |
| `codebase_structure` | Need to find files or understand layout |
| `memory_index` | You're reading it - navigation guide |

---

## By Task Type

### 🔧 "I need to modify hooks"
1. `hook_registry` - Registration patterns, priority ranges, HookResult API
2. Pick runner-specific memory:
   - `pre_tool_use_hooks` - 47 gate hooks (blocking)
   - `post_tool_use_hooks` - Tracking hooks (observing)
   - `stop_hooks` - 16 completion hooks
   - `prompt_suggestions` - Suggestion functions
   - `session_runners` - Lifecycle hooks (init, cleanup, compact)

### 📊 "I need to understand confidence"
1. `confidence_system` - Overview, zones, gates
2. Then specific:
   - `confidence_reducers` - Penalty triggers
   - `confidence_increasers` - Reward triggers

### 📦 "I need to add/modify ops tools"
1. `ops_tools` - 51 tools, script pattern, categories
2. `slash_commands` - 75 commands, file format

### 🔍 "I need to find something"
1. `codebase_structure` - Directory layout
2. `lib_modules` - 62 library modules

### 📋 "I need to track tasks"
1. `beads_system` - bd CLI commands, workflow

### ✅ "I need to complete work properly"
1. `task_completion` - Checklist, quality gates
2. `style_conventions` - Naming, patterns

### 🤖 "I need to understand mastermind"
1. `project_overview` - Architecture summary
2. Check `~/.claude/rules/mastermind.md` for full reference

---

## Core Memory Details

### Architecture & Overview
| Memory | Purpose |
|--------|---------|
| `project_overview` | Tech stack, 65 hooks, 51 ops, 75 commands |
| `codebase_structure` | Full directory layout |

### Hook System
| Memory | Purpose |
|--------|---------|
| `hook_registry` | Registration API, 65 total hooks |
| `pre_tool_use_hooks` | 47 gates (confidence, quality, security) |
| `post_tool_use_hooks` | Tracking (state, quality, velocity) |
| `stop_hooks` | 16 completion checks |
| `prompt_suggestions` | Prompt injection |
| `session_runners` | Init, cleanup, compact, subagent, status |

### Confidence System
| Memory | Purpose |
|--------|---------|
| `confidence_system` | Zones, gates, mechanics |
| `confidence_reducers` | Penalty patterns |
| `confidence_increasers` | Reward patterns |

### Tools & Commands
| Memory | Purpose |
|--------|---------|
| `ops_tools` | 51 ops scripts |
| `slash_commands` | 75 commands |

### Library
| Memory | Purpose |
|--------|---------|
| `lib_modules` | 62 lib files |
| `session_state` | SessionState fields |

### Workflow
| Memory | Purpose |
|--------|---------|
| `beads_system` | Task tracking |
| `task_completion` | Quality checklist |
| `style_conventions` | Naming patterns |
| `integration_synergy` | Unified system architecture |

---

## Session Memories (~130 files)

Session memories (`session_2025-*`) are **auto-generated ephemeral logs**. They capture:
- Work done in specific sessions
- Decisions made
- Problems encountered

**When to read them:**
- Investigating what happened in a past session
- Finding context for a specific date/time
- Never need to read them for normal development

**Pruning:** Run `serena_memory_lifecycle.py` to clean old sessions.

---

## Decision Tree

```
What are you doing?
│
├─ Finding files/code?
│  └─ READ: codebase_structure
│
├─ Modifying hooks?
│  ├─ READ: hook_registry (always)
│  └─ READ: [specific runner memory]
│
├─ Debugging confidence?
│  ├─ Dropping? → READ: confidence_reducers
│  └─ Not rising? → READ: confidence_increasers
│
├─ Adding tools?
│  ├─ Ops script? → READ: ops_tools
│  └─ Slash cmd? → READ: slash_commands
│
├─ Working with state?
│  └─ READ: session_state, lib_modules
│
├─ Tracking tasks?
│  └─ READ: beads_system
│
└─ General orientation?
   └─ READ: project_overview
```

---

## Anti-Patterns

❌ **Don't read all memories** - Context waste
❌ **Don't read session_* memories** - Unless investigating specific past session
❌ **Don't skip project_overview** - Critical architecture context

✅ **Do use this index** - Read 1-3 targeted memories
✅ **Do start with project_overview** - Best ROI
✅ **Do read hook_registry before hook work** - Common API

*Updated: 2025-12-17*
