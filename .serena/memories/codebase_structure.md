# Codebase Structure

Project root: `~/.claude/`

## Directory Layout

| Directory | Purpose | Key Contents |
|-----------|---------|--------------|
| `.beads/` | Beads task database | `beads.db`, sockets |
| `.serena/` | Serena MCP config | memories, project config |
| `agents/` | Agent definitions | Task agent configs |
| `backups/` | File backups | Auto-generated |
| `cache/` | Runtime caches | Exploration, embedding |
| `capabilities/` | Mastermind capability registry | `registry.yaml`, index |
| `commands/` | Slash commands (75) | `*.md` files |
| `config/` | Configuration files | `mastermind.json`, etc. |
| `debug/` | Debug logs | Session traces |
| `file-history/` | File version history | Auto-generated |
| `hooks/` | Hook system (35 files) | Runners, helpers |
| `ide/` | IDE integration | VS Code config |
| `lib/` | Library modules (62) | Core, confidence, state |
| `logs/` | Application logs | Runtime logs |
| `memory/` | Persistent memory | `__*.md` files |
| `ops/` | Ops tools (51) | `*.py` scripts |
| `plans/` | Plan mode files | Generated plans |
| `plugins/` | Claude Code plugins | MCP servers, extensions |
| `projects/` | Project configs | Per-project settings |
| `reminders/` | Reminder system | Scheduled reminders |
| `rules/` | Rule files | `*.md` rule definitions |
| `scripts/` | Shell scripts | Utilities |
| `session-env/` | Session environment | Runtime state |
| `skills/` | Agent skills | Skill definitions |
| `statsig/` | Feature flags | Statsig config |
| `shell-snapshots/` | Shell state snapshots | Auto-generated |
| `telemetry/` | Telemetry data | Analytics |
| `tests/` | Test files | `test_*.py` |
| `tmp/` | Temporary files | Scratch space |
| `todos/` | Legacy todos | Deprecated |

## Key Files (Root)

| File | Purpose |
|------|---------|
| `requirements.txt` | Python dependencies |
| `settings.json` | Claude Code settings |
| `settings.local.json` | Local overrides |
| `history.jsonl` | Session history |
| `statusline-command.sh` | Status line script |
| `privacy-restore.yaml` | Privacy settings |

## Subsystem Locations

### Hook System (`hooks/`)
```
hooks/
├── pre_tool_use_runner.py    # 47 gates
├── post_tool_use_runner.py   # 1 hook + inline
├── user_prompt_submit_runner.py  # 1 hook
├── stop_runner.py            # 16 hooks
├── session_init.py           # SessionStart
├── session_cleanup.py        # SessionEnd
├── subagent_stop.py          # SubagentStop
├── pre_compact.py            # PreCompact
├── statusline.py             # Statusline
├── dependency_check.py       # Standalone
├── _*.py                     # Helper modules
└── py                        # Python wrapper
```

### Library (`lib/`)
```
lib/
├── core.py                   # Script utilities
├── confidence.py             # Confidence facade
├── session_state.py          # State facade
├── _confidence_*.py          # Confidence modules (9)
├── _session_*.py             # State modules (12)
├── mastermind/               # Multi-model routing (9)
├── cache/                    # Caching (4)
├── oracle.py                 # External LLM
└── ...                       # 62 total modules
```

### Mastermind (`lib/mastermind/`)
```
mastermind/
├── __init__.py
├── config.py                 # Configuration
├── router_groq.py            # Kimi K2 classifier
├── router_gpt.py             # GPT-5.2 planner
├── hook_integration.py       # Hook interface
├── state.py                  # Blueprint state
├── routing.py                # Routing logic
├── context_packer.py         # Context assembly
└── telemetry.py              # Logging
```

### Capabilities (`capabilities/`)
```
capabilities/
├── registry.yaml             # Master catalog
├── capabilities_index.json   # Auto-generated index
└── tag_vocab.json            # Controlled vocabulary
```

## File Counts Summary

| Category | Count |
|----------|-------|
| Hook files | 35 |
| Registered hooks | 65 |
| Ops tools | 51 |
| Slash commands | 75 |
| Lib modules | 62 |

*Updated: 2025-12-17*
