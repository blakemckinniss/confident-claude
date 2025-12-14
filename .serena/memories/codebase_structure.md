# Codebase Structure

## Directory Layout

```
~/.claude/
├── hooks/                 # Hook system (entry point for Claude Code lifecycle)
│   ├── py                 # Python wrapper script (auto-detects venv)
│   ├── post_tool_use_runner.py    # PostToolUse orchestrator (~60 hooks)
│   ├── pre_tool_use_runner.py     # PreToolUse orchestrator (gates/blocks)
│   ├── user_prompt_submit_runner.py # UserPromptSubmit (context injection)
│   ├── stop_runner.py             # Stop event handler (completion gate)
│   ├── session_init.py            # SessionStart handler
│   ├── session_cleanup.py         # SessionEnd handler
│   ├── subagent_stop.py           # SubagentStop handler
│   ├── pre_compact.py             # PreCompact handler
│   ├── statusline.py              # Status bar renderer
│   ├── _hook_result.py            # HookResult class (approve/deny/none)
│   ├── _cooldown.py               # Cooldown management
│   ├── _config.py                 # Centralized config
│   ├── _patterns.py               # Path patterns (scratch detection)
│   ├── _beads.py                  # Bead/task tracking helpers
│   ├── _logging.py                # Hook logging utilities
│   ├── _ast_utils.py              # AST analysis utilities
│   ├── _lib_path.py               # Library path management
│   ├── _pal_mandates.py           # PAL MCP mandate handling
│   ├── _quality_scanner.py        # Code quality scanning
│   ├── _cache.py                  # Hook result caching
│   └── _intent_classifier.py      # Intent classification
│
├── lib/                   # Shared library modules
│   ├── core.py            # Script setup utilities (setup_script, finalize)
│   ├── confidence.py      # Confidence system (reducers/increasers)
│   ├── session_state.py   # Session state management
│   ├── oracle.py          # External LLM integration
│   ├── council_engine.py  # Multi-persona consultation
│   ├── spark_core.py      # Memory/synapse system
│   ├── synapse_core.py    # Core synapse firing logic
│   ├── detour.py          # Blocking issue tracking
│   ├── context_builder.py # Context assembly
│   ├── session_rag.py     # Session history RAG
│   ├── epistemology.py    # Knowledge handling
│   ├── ast_analysis.py    # AST parsing
│   ├── hook_registry.py   # Hook discovery
│   ├── command_awareness.py # Command awareness
│   ├── project_state.py   # Project state
│   ├── project_detector.py # Project type detection
│   ├── persona_parser.py  # Persona parsing
│   ├── analysis/          # Code analysis submodule
│   │   ├── __init__.py
│   │   └── god_component_detector.py
│   └── cache/             # Caching submodule
│       ├── __init__.py
│       ├── grounding_analyzer.py
│       ├── embedding_client.py
│       ├── read_cache.py
│       └── exploration_cache.py
│
├── ops/                   # Operational tools (36 scripts)
│   ├── audit.py           # Code quality audit
│   ├── void.py            # Completeness checker
│   ├── oracle.py          # External LLM consultation
│   ├── council.py         # Multi-model consensus
│   ├── think.py           # Problem decomposition
│   ├── research.py        # Web search (Tavily)
│   ├── docs.py            # Documentation lookup
│   ├── groq.py            # Fast inference (Groq)
│   ├── swarm.py           # Parallel oracle reasoning
│   ├── fp.py              # False positive recording
│   ├── firecrawl.py       # Web scraping
│   ├── playwright.py      # Browser automation
│   └── ... (36 total)
│
├── commands/              # Slash command definitions (65 markdown files)
│   ├── audit.md, void.md, oracle.md, council.md, think.md
│   ├── research.md, docs.md, groq.md, swarm.md
│   ├── verify.md, scope.md, upkeep.md
│   ├── spark.md, remember.md, evidence.md
│   ├── bd.md, commit.md, gaps.md, drift.md
│   ├── sysinfo.md, inventory.md, housekeeping.md
│   └── ... (65 total)
│
├── rules/                 # Configuration rules (10 files)
│   ├── confidence.md      # Confidence system rules
│   ├── beads.md           # Task tracking rules
│   ├── hooks.md           # Hook development guide
│   ├── tools.md           # Tools reference
│   ├── python.md          # Python conventions
│   ├── typescript.md      # TypeScript conventions
│   ├── react.md           # React patterns
│   ├── nextjs.md          # Next.js patterns
│   ├── tailwind.md        # Tailwind CSS
│   └── shadcn.md          # shadcn/ui patterns
│
├── memory/                # Persistent memory
│   ├── __capabilities.md  # Framework capabilities index
│   ├── __lessons.md       # Learned lessons
│   ├── __decisions.md     # Architectural decisions
│   └── __*.md             # Other memory files
│
├── skills/                # Claude Agent skills
├── agents/                # Custom agent definitions
├── plugins/               # Plugin configurations
├── tests/                 # Test files
├── tmp/                   # Scratch/temporary files
├── cache/                 # Cached data
├── logs/                  # Log files
├── debug/                 # Debug output
├── downloads/             # Downloaded files
├── backups/               # Backup files
├── plans/                 # Plan files
├── todos/                 # Todo files (legacy)
├── reminders/             # Reminder files
├── projects/              # Project-specific configs
├── ide/                   # IDE integrations
├── file-history/          # File history tracking
├── shell-snapshots/       # Shell state snapshots
├── statsig/               # Feature flags
├── telemetry/             # Usage telemetry
├── session-env/           # Session environment
├── config/                # Additional configs
├── .beads/                # Beads task tracking data
├── .serena/               # Serena MCP memories
├── .venv/                 # Python virtual environment
├── settings.json          # Claude Code settings (hooks config)
├── settings.local.json    # Local settings overrides
├── requirements.txt       # Python dependencies
└── history.jsonl          # Session history
```

## Key Entry Points

1. **settings.json** - Configures all hooks and their triggers
2. **hooks/py** - Python wrapper that finds venv or system Python
3. **lib/core.py** - Common utilities for ops scripts
4. **lib/confidence.py** - The confidence regulation system
5. **lib/session_state.py** - Cross-hook state management

## Hook Flow

```
User Action → Hook Event → Runner → Individual Hooks → HookResult
                                                          ↓
                                              approve/deny/inject context
```

## Important Patterns

- **Runners** orchestrate multiple hooks for a single event
- **Hooks** are registered with `@register_hook` decorator
- **HookResult** controls whether actions proceed
- **SessionState** persists data across hooks within a session
- **Confidence** mechanically regulates behavior (not self-assessed)
