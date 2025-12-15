# Memory Index

**Navigation guide for 19 Serena memories.** Read this first to identify which memories are relevant to your task.

## Quick Reference

| Memory | Tokens | When to Read |
|--------|--------|--------------|
| `project_overview` | ~600 | **START HERE** - First memory for any task |
| `codebase_structure` | ~1200 | Need to find files or understand layout |
| `memory_index` | ~800 | You're reading it - navigation guide |

---

## By Task Type

### 🔧 "I need to modify hooks"
1. `hook_registry` - Registration patterns, priority ranges, HookResult API
2. Pick runner-specific memory:
   - `pre_tool_use_hooks` - 38 gate hooks (blocking)
   - `post_tool_use_hooks` - 23 tracking hooks (observing)
   - `stop_hooks` - 12 completion hooks
   - `prompt_suggestions` - 18 suggestion functions
   - `session_runners` - Lifecycle hooks (init, cleanup, compact)

### 📊 "I need to understand confidence"
1. `confidence_system` - Overview, zones, gates
2. Then specific:
   - `confidence_reducers` - 20+ penalty triggers
   - `confidence_increasers` - 20+ reward triggers

### 📦 "I need to add/modify ops tools"
1. `ops_tools` - Tool index, script pattern, categories
2. `slash_commands` - Command file format, complete index

### 🔍 "I need to find something"
1. `codebase_structure` - Directory layout, key files
2. `lib_modules` - Library module index (36 files)

### 📋 "I need to track tasks"
1. `beads_system` - bd CLI commands, workflow

### ✅ "I need to complete work properly"
1. `task_completion` - Checklist, quality gates
2. `style_conventions` - Naming, patterns, formats

---

## Memory Details

### Core (Read First)

| Memory | Purpose | Read When |
|--------|---------|-----------|
| `project_overview` | Tech stack, architecture summary, key deps | Starting any task |
| `codebase_structure` | Full directory layout with file counts | Looking for files |

### Hook System

| Memory | Purpose | Read When |
|--------|---------|-----------|
| `hook_registry` | Registration API, priority ranges, bypass | Adding/modifying any hook |
| `pre_tool_use_hooks` | 38 gates (confidence, quality, security) | Debugging blocked actions |
| `post_tool_use_hooks` | 23 trackers (state, quality, velocity) | Understanding context injection |
| `stop_hooks` | 12 completion checks (completion_gate) | Debugging "can't complete" |
| `prompt_suggestions` | 18 suggestion functions | Modifying prompt injection |
| `session_runners` | Init, cleanup, compact, subagent, status | Lifecycle/state issues |

### Confidence System

| Memory | Purpose | Read When |
|--------|---------|-----------|
| `confidence_system` | Zones, gates, overall mechanics | Understanding confidence behavior |
| `confidence_reducers` | All penalty patterns and triggers | Debugging confidence drops |
| `confidence_increasers` | All reward patterns and triggers | Understanding confidence gains |

### Tools & Commands

| Memory | Purpose | Read When |
|--------|---------|-----------|
| `ops_tools` | 36 ops scripts with categories | Adding ops tool |
| `slash_commands` | 66 commands with format | Adding slash command |

### Library

| Memory | Purpose | Read When |
|--------|---------|-----------|
| `lib_modules` | 36 lib files, modular structure | Importing from lib/ |
| `session_state` | SessionState fields, functions | Working with state |

### Workflow

| Memory | Purpose | Read When |
|--------|---------|-----------|
| `beads_system` | Task tracking with bd CLI | Managing tasks |
| `task_completion` | Quality checklist | Before claiming "done" |
| `style_conventions` | Naming, patterns | Writing new code |
| `suggested_commands` | Common bash/tool invocations | Quick reference |

---

## Memory Sizes (Approximate)

| Size | Memories |
|------|----------|
| Small (<500 tokens) | style_conventions, suggested_commands, task_completion |
| Medium (500-1000) | project_overview, beads_system, confidence_system |
| Large (1000-1500) | codebase_structure, lib_modules, hook_registry |
| XL (1500+) | pre_tool_use_hooks, post_tool_use_hooks, slash_commands |

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
   └─ READ: project_overview, codebase_structure
```

---

## Anti-Patterns

❌ **Don't read all memories** - Context waste, most won't be relevant
❌ **Don't skip project_overview** - Contains critical architecture context
❌ **Don't read reducer/increaser memories without confidence_system** - Need context first

✅ **Do use this index** - Read 1-3 targeted memories instead of guessing
✅ **Do start with project_overview** - Best ROI for initial context
✅ **Do read hook_registry before any hook work** - Common API/patterns
