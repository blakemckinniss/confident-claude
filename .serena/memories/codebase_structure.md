# Codebase Structure

## Directory Layout

```
~/.claude/
├── hooks/                 # Hook system (31 files)
│   ├── py                 # Python wrapper script (auto-detects venv)
│   │
│   │ # Main Runners (5)
│   ├── post_tool_use_runner.py    # PostToolUse orchestrator (1 registered hook)
│   ├── pre_tool_use_runner.py     # PreToolUse orchestrator (38 registered hooks)
│   ├── user_prompt_submit_runner.py # UserPromptSubmit (1 hook, uses _prompt_* modules)
│   ├── stop_runner.py             # Stop event handler (12 registered hooks)
│   ├── session_init.py            # SessionStart handler
│   │
│   │ # Additional Runners (4)
│   ├── session_cleanup.py         # SessionEnd handler
│   ├── subagent_stop.py           # SubagentStop handler
│   ├── pre_compact.py             # PreCompact handler
│   ├── statusline.py              # Status bar renderer
│   │
│   │ # Standalone Hooks (1)
│   ├── dependency_check.py        # Dependency validation (API keys, packages)
│   │
│   │ # Helper Modules (21, prefixed with _)
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
│   ├── _intent_classifier.py      # Intent classification
│   ├── _hooks_state.py            # Hook state management
│   ├── _hooks_quality.py          # Quality check helpers
│   ├── _hooks_tracking.py         # Tracking utilities
│   ├── _hooks_cache.py            # Hook result caching
│   ├── _hook_registry.py          # Hook discovery/registration
│   ├── _prompt_registry.py        # Prompt injection registry
│   ├── _prompt_suggestions.py     # Contextual suggestions
│   ├── _prompt_gating.py          # Prompt-level gating
│   └── _prompt_context.py         # Context building for prompts
│
├── lib/                   # Shared library modules (36 files + subdirs)
│   │ # Core
│   ├── core.py            # Script setup utilities
│   ├── confidence.py      # Confidence system facade
│   ├── session_state.py   # Session state facade
│   │
│   │ # Confidence Modules (8 files)
│   ├── _confidence_constants.py
│   ├── _confidence_disputes.py
│   ├── _confidence_engine.py
│   ├── _confidence_increasers.py
│   ├── _confidence_realignment.py
│   ├── _confidence_reducers.py
│   ├── _confidence_streaks.py
│   ├── _confidence_tiers.py
│   │
│   │ # Session State Modules (11 files)
│   ├── _session_batch.py
│   ├── _session_confidence.py
│   ├── _session_constants.py
│   ├── _session_context.py
│   ├── _session_errors.py
│   ├── _session_goals.py
│   ├── _session_persistence.py
│   ├── _session_state_class.py
│   ├── _session_thresholds.py
│   ├── _session_tracking.py
│   ├── _session_workflow.py
│   │
│   │ # External LLM
│   ├── oracle.py          # OpenRouter integration
│   ├── council_engine.py  # Multi-model consensus
│   │
│   │ # Memory & Context
│   ├── spark_core.py      # Memory/synapse system
│   ├── synapse_core.py    # Core synapse logic
│   ├── session_rag.py     # Session history RAG
│   ├── context_builder.py # Context assembly
│   ├── epistemology.py    # Knowledge handling
│   │
│   │ # Code Analysis
│   ├── ast_analysis.py    # AST parsing
│   ├── analysis/          # Analysis submodule
│   │   ├── __init__.py
│   │   └── god_component_detector.py
│   │
│   │ # Caching
│   ├── cache/             # Cache submodule
│   │   ├── __init__.py
│   │   ├── grounding_analyzer.py
│   │   ├── embedding_client.py
│   │   ├── read_cache.py
│   │   └── exploration_cache.py
│   │
│   │ # Workflow & Utilities
│   ├── detour.py          # Blocking issue tracking
│   ├── project_state.py   # Project state
│   ├── project_detector.py # Project type detection
│   ├── hook_registry.py   # Hook discovery
│   ├── command_awareness.py # Command awareness
│   └── persona_parser.py  # Persona parsing
│
├── ops/                   # Operational tools (36 scripts)
│   ├── audit.py           # Code quality audit
│   ├── audit_hooks.py     # Hook spec auditing
│   ├── bdg.py             # Browser DevTools Protocol
│   ├── capabilities.py    # Capability index generator
│   ├── coderabbit.py      # AI code review
│   ├── compress_session.py # Session compression
│   ├── council.py         # Multi-persona consensus
│   ├── detour.py          # Blocking issue stack
│   ├── docs.py            # Documentation lookup
│   ├── drift.py           # Style drift detection
│   ├── evidence.py        # Evidence ledger
│   ├── firecrawl.py       # Web scraping
│   ├── fp.py              # False positive recording
│   ├── gaps.py            # Implementation gaps
│   ├── groq.py            # Fast inference (Groq)
│   ├── hooks.py           # Hook management
│   ├── housekeeping.py    # Disk cleanup
│   ├── inventory.py       # Binary scan
│   ├── oracle.py          # External LLM
│   ├── orchestrate.py     # Batch orchestration
│   ├── playwright.py      # Browser automation
│   ├── probe.py           # Runtime introspection
│   ├── recruiter.py       # Agent recruitment
│   ├── remember.py        # Persistent memory
│   ├── research.py        # Web search (Tavily)
│   ├── scope.py           # Definition of Done
│   ├── spark.py           # Associative recall
│   ├── swarm.py           # Parallel oracle reasoning
│   ├── sysinfo.py         # System health
│   ├── test_hooks.py      # Hook testing
│   ├── think.py           # Problem decomposition
│   ├── timekeeper.py      # Time tracking
│   ├── upkeep.py          # Pre-commit checks
│   ├── verify.py          # State verification
│   ├── void.py            # Completeness checker
│   └── xray.py            # AST structural search
│
├── commands/              # Slash command definitions (66 markdown files)
│   └── ... (see slash_commands memory for full list)
│
├── rules/                 # Configuration rules (6 files)
│   ├── confidence.md      # Confidence system rules
│   ├── beads.md           # Task tracking rules
│   ├── hooks.md           # Hook development guide
│   ├── tools.md           # Tools reference
│   ├── python.md          # Python conventions
│   └── typescript.md      # TypeScript conventions
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
4. **lib/confidence.py** - Confidence regulation facade
5. **lib/session_state.py** - Session state management facade

## Hook Flow

```
User Action → Hook Event → Runner → Individual Hooks → HookResult
                                                          ↓
                                              approve/deny/inject context
```

## Important Patterns

- **Runners** orchestrate multiple hooks for a single event
- **Hooks** registered with `@register_hook` decorator (52 total across runners)
- **HookResult** controls whether actions proceed
- **SessionState** persists data across hooks within a session
- **Confidence** mechanically regulates behavior (not self-assessed)
- **Facade pattern** used for confidence.py and session_state.py (import from modular `_*` files)
