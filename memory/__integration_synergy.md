# Integration Synergy

Deep integration between claude-mem + serena + beads + hooks as a unified system with project isolation.

## Architecture

```
~/.claude/                              # Framework (shared runtime)
├── lib/
│   ├── project_context.py              # Project detection (walks up for .beads/ or CLAUDE.md)
│   └── agent_registry.py               # Project-aware agent assignment tracking
├── ops/
│   ├── bd_bridge.py                    # Beads→claude-mem observation bridge
│   ├── bead_claim.py                   # Agent claims bead with lifecycle tracking
│   ├── bead_release.py                 # Agent releases bead with status
│   ├── bead_lifecycle_daemon.py        # Background orphan recovery (120min timeout)
│   ├── bead_orphan_check.py            # Manual multi-project orphan diagnostic
│   ├── serena.py                       # Serena MCP workflow hints
│   ├── unified_context.py              # Aggregates all context sources
│   ├── integration_install.py          # One-shot installer (--check/--install)
│   └── new_project.py                  # Project scaffolding with full integration
├── commands/
│   ├── serena.md                       # /serena - Serena MCP wrapper
│   ├── si.md                           # /si <symbol> - Impact analysis
│   ├── sv.md                           # /sv <file> - Validate file
│   ├── sm.md                           # /sm [search] - Memories
│   └── new-project.md                  # /new-project - Create integrated project
└── .beads/                             # Framework's OWN beads storage

~/projects/<project>/                   # Each project (ISOLATED)
├── CLAUDE.md                           # Project marker + instructions
├── .beads/                             # Project-local beads state
│   ├── issues/                         # Beads issues (if using local db)
│   └── agent_assignments.jsonl         # Project-isolated agent claims
├── .claude/                            # Project-local commands/settings
│   └── commands/                       # Project-specific slash commands
└── .serena/                            # Serena semantic analysis
    ├── memories/                       # Project knowledge
    └── config.yaml                     # Serena config
```

## Key Concepts

### Project Isolation
- **Beads database**: GLOBAL (`~/.claude/.beads/beads.db`) - all tasks visible everywhere
- **Agent assignments**: PER-PROJECT (`<project>/.beads/agent_assignments.jsonl`) - tracks which agent claimed which bead in which project context
- **Detection**: Walks up from $PWD looking for `.beads/` or `CLAUDE.md`

### Project Detection Order
1. `$CLAUDE_PROJECT_ROOT` env var (explicit override)
2. Walk up from $PWD for `.beads/` directory
3. Walk up from $PWD for `CLAUDE.md` file
4. Error if nothing found (no global fallback)

### Agent Lifecycle
1. **Claim**: Agent calls `bead_claim.py` → writes to project's `agent_assignments.jsonl`
2. **Heartbeat**: Periodic updates to `last_heartbeat` timestamp
3. **Release**: Agent calls `bead_release.py` → marks assignment complete
4. **Orphan Recovery**: Daemon detects stale assignments (>120min) → reverts bead to open

### Timeout Tiers
| Status | Threshold | Action |
|--------|-----------|--------|
| Stale | 30+ min | Warning logged |
| Stalled | 60+ min | Alert logged |
| Orphan | 120+ min | Auto-revert to open |

## Quick Reference

### Create New Project
```bash
/new-project my-app --description "Description"
# Creates: .beads/, .claude/, .serena/, CLAUDE.md, src/, .git/
```

### Serena Commands
```bash
/serena status              # Check availability
/si MyClass                 # Impact analysis for symbol
/sv src/main.ts             # Validate file
/sm                         # List memories
/sm auth                    # Search memories
```

### Context Aggregation
```bash
~/.claude/.venv/bin/python ~/.claude/ops/unified_context.py
# Shows: Serena, framework memories, claude-mem, beads, session state
```

### Installation Check
```bash
~/.claude/.venv/bin/python ~/.claude/ops/integration_install.py --check
# Verifies all 13 required files present
```

## Integration Points

### Beads → Claude-mem Bridge
- `bd_bridge.py` wraps `bd` CLI
- Fires observations to claude-mem API on create/close/update
- POST to `http://127.0.0.1:37777/api/sessions/observations`

### Serena → Framework
- `serena.py` outputs MCP workflow hints
- Slash commands (`/si`, `/sv`, `/sm`) trigger Serena MCP tools
- Memories in `.serena/memories/` for project knowledge

### Hooks → Beads
- `_beads.py` helper queries beads for hook decisions
- Parallel orchestration requires tracking open beads
- Grace period before bead enforcement kicks in

## Files Created

| File | Purpose |
|------|---------|
| `lib/project_context.py` | Project detection logic |
| `lib/agent_registry.py` | Agent assignment CRUD |
| `ops/bd_bridge.py` | Beads-memory bridge |
| `ops/bead_claim.py` | Agent claim wrapper |
| `ops/bead_release.py` | Agent release wrapper |
| `ops/bead_lifecycle_daemon.py` | Orphan recovery daemon |
| `ops/bead_orphan_check.py` | Manual diagnostic |
| `ops/serena.py` | Serena integration |
| `ops/unified_context.py` | Context aggregator |
| `ops/integration_install.py` | Installer |
| `ops/new_project.py` | Project scaffolding |
| `commands/serena.md` | /serena command |
| `commands/si.md` | /si command |
| `commands/sv.md` | /sv command |
| `commands/sm.md` | /sm command |
| `commands/new-project.md` | /new-project command |

## Constraints

- ❌ Cannot modify `~/.claude/hooks/*.py` runner files
- ❌ Cannot modify claude-mem plugin code
- ✅ Can modify `~/.claude/hooks/_beads.py` (helper module)
- ✅ Can create new ops scripts, commands, skills, lib modules
