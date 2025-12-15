# Session Lifecycle Runners

## Overview

5 runners that handle session lifecycle events outside the main tool flow. These manage initialization, cleanup, compaction, subagent completion, and status display.

## Runner Index

| Runner | Event | Purpose |
|--------|-------|---------|
| `session_init.py` | SessionStart | Initialize state, detect resume, dependency check |
| `session_cleanup.py` | SessionEnd | Persist learnings, cleanup tmp/, generate summary |
| `subagent_stop.py` | SubagentStop | Quality checks on Task agent completion |
| `pre_compact.py` | PreCompact | Inject critical context into compaction |
| `statusline.py` | Statusline | Render status bar with system metrics |

---

## session_init.py (SessionStart)

**Purpose**: Initialize session state and surface actionable context.

**Latency Target**: <200ms

**Features**:
- Detects stale state from previous sessions
- Initializes fresh SessionState with unique session_id
- Refreshes ops script discovery (`_discover_ops_scripts`)
- Clears accumulated errors/gaps from dead sessions
- Runs dependency check (API keys, packages, binaries)
- Surfaces resume context (files, tasks, errors)

**Imports** (conditional):
- `project_detector` - Project-aware state management
- `spark_core` - Pre-warm synapse map
- `dependency_check` - Validate dependencies

**Key Files Referenced**:
- `~/.claude/memory/punch_list.json` - Scope's pending items
- `~/.claude/memory/__infrastructure.md` - Prevents duplicate creation
- `~/.claude/memory/__capabilities.md` - Prevents functional duplication

**Output**: Silent by default, outputs status only if resuming or issues detected.

---

## session_cleanup.py (SessionEnd)

**Purpose**: Persist learnings and clean up session artifacts.

**Latency Target**: <500ms (background operations)

**Features**:
- Persists learned patterns to long-term memory
- Updates `__lessons.md` with session insights
- Cleans up `~/.claude/tmp/` temporary files
- Generates session summary for telemetry
- Saves final state snapshot
- Prepares handoff data for next session

**Key Functions**:
- `get_session_summary()` - Extract session metrics
- `prepare_handoff()` - Package handoff context
- `complete_feature()` - Mark features as done
- `extract_work_from_errors()` - Convert errors to work items

**Key Files**:
- `~/.claude/memory/__lessons.md` - Accumulated lessons
- `~/.claude/memory/session_log.jsonl` - Session history
- `~/.claude/memory/progress.json` - Autonomous agent progress
- `~/.claude/memory/handoff.json` - Session handoff data

**Output**: Silent - performs cleanup in background.

---

## subagent_stop.py (SubagentStop)

**Purpose**: Quality checks when Task tool agents complete.

**Latency Target**: <100ms

**Checks**:
1. **Session blocks** - Subagent may have triggered blocking issues
2. **Stub detection** - Check created files for placeholder code
3. **Unverified edits** - Flag edits without verification

**Input Schema**:
```json
{
  "session_id": "...",
  "transcript_path": "...",
  "permission_mode": "...",
  "hook_event_name": "SubagentStop",
  "stop_hook_active": true
}
```

**Output**:
```json
{"decision": "block", "reason": "..."} // or empty for pass
```

**Key Functions**:
- `check_stubs_in_created_files()` - Scan for stub patterns
- `get_session_blocks()` / `clear_session_blocks()` - Block tracking

---

## pre_compact.py (PreCompact)

**Purpose**: Inject critical context that survives compaction.

**Latency Target**: <50ms

**Trigger**: `manual` or `auto` compaction

**Context Injected**:
- 📁 Files created this session (last 3)
- ✏️ Files edited count
- ⚠️ Unverified integration greps
- ❌ Unresolved errors count
- 📦 Libraries in use (top 5)

**Input Schema**:
```json
{
  "session_id": "...",
  "transcript_path": "...",
  "trigger": "manual|auto",
  "custom_instructions": "..."
}
```

**Output**: Stdout text is added to compaction summary.

**Key Function**: `get_critical_context(state)` - Extract survival context

---

## statusline.py (Statusline)

**Purpose**: Render status bar with system and session metrics.

**Latency Target**: <100ms (heavily cached)

**Display Format**:
```
Line 1: Model | Context% | CPU | RAM | Disk | Services | Network
Line 2: Session | Folder | Confidence | Git
```

**Metrics Collected**:
| Metric | TTL | Source |
|--------|-----|--------|
| GPU/VRAM | 2s | nvidia-smi |
| Services | 5s | docker ps, pgrep |
| ComfyUI | 10s | Service check |
| Network | 10s | Connectivity test |
| Git | 3s | git status |
| Dev ports | 3s | Port scan (3000, 5173, 8000, etc.) |

**Caching**:
- Cache file: `/tmp/.claude_statusline_cache.json`
- TTL-based invalidation per metric type
- Thread pool for parallel metric collection

**Dev Ports Monitored**:
- 3000/3001: React, Next.js
- 5173/5174: Vite
- 8000: Django, FastAPI
- 8080: Generic
- 8888: Jupyter

---

## Lifecycle Flow

```
SessionStart
    ↓
session_init.py → Initialize state, check deps
    ↓
[Main session - PreToolUse/PostToolUse/Stop hooks]
    ↓
PreCompact (if triggered)
    ↓
pre_compact.py → Inject survival context
    ↓
SubagentStop (per Task agent)
    ↓
subagent_stop.py → Quality check agents
    ↓
SessionEnd
    ↓
session_cleanup.py → Persist, cleanup
```

## State Files

| File | Purpose | Runner |
|------|---------|--------|
| `cache/session_state.json` | Main session state | All |
| `memory/__lessons.md` | Accumulated lessons | cleanup |
| `memory/session_log.jsonl` | Session history | cleanup |
| `memory/handoff.json` | Handoff data | cleanup |
| `/tmp/.claude_statusline_cache.json` | Statusline cache | statusline |
