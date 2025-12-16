# Integration Synergy

Deep integration between claude-mem + serena + beads + hooks with project isolation.

## Architecture

```
~/.claude/                              # Framework (shared runtime)
├── lib/
│   ├── project_context.py              # Project detection
│   └── agent_registry.py               # Agent assignment tracking
├── ops/
│   ├── bd_bridge.py                    # Beads→claude-mem bridge
│   ├── bead_claim.py                   # Agent claims bead
│   ├── bead_release.py                 # Agent releases bead
│   ├── bead_lifecycle_daemon.py        # Orphan recovery daemon
│   ├── bead_orphan_check.py            # Manual orphan check
│   ├── serena.py                       # Serena MCP workflow hints
│   ├── unified_context.py              # Context aggregator
│   ├── integration_install.py          # One-shot installer
│   └── new_project.py                  # Project scaffolding
└── commands/
    ├── serena.md                       # /serena command
    ├── si.md                           # /si <symbol> impact
    ├── sv.md                           # /sv <file> validate
    ├── sm.md                           # /sm memories
    └── new-project.md                  # /new-project scaffolding
```

## Key Concepts

### Project Isolation
- **Beads database**: GLOBAL (`~/.claude/.beads/beads.db`)
- **Agent assignments**: PER-PROJECT (`<project>/.beads/agent_assignments.jsonl`)
- **Detection**: Walks up from $PWD for `.beads/` or `CLAUDE.md`

### Agent Lifecycle
1. Claim: `bead_claim.py <id>` → writes to project assignments
2. Work on task
3. Release: `bead_release.py <id>` → marks complete
4. Orphan recovery: 120+ min stale → auto-revert

### Serena Commands
| Command | Purpose |
|---------|---------|
| `/serena status` | Check availability |
| `/si <symbol>` | Impact analysis |
| `/sv <file>` | Validate file |
| `/sm [search]` | Project memories |

### New Project Scaffolding
```bash
/new-project my-app --description "Description"
# Creates: .beads/, .claude/, .serena/, CLAUDE.md, src/, .git/
```

## Files Reference

| File | Purpose |
|------|---------|
| `lib/project_context.py` | Project detection logic |
| `lib/agent_registry.py` | Assignment CRUD operations |
| `ops/bd_bridge.py` | Fires observations to claude-mem |
| `ops/bead_claim.py` | Agent claim wrapper |
| `ops/bead_release.py` | Agent release wrapper |
| `ops/bead_lifecycle_daemon.py` | Background orphan recovery |
| `ops/unified_context.py` | Aggregates all context sources |
| `ops/new_project.py` | Project scaffolding script |
