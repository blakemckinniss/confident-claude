# Codebase Structure

## Directory Layout

```
~/.claude/
├── hooks/                 # Hook system (entry point for Claude Code lifecycle)
│   ├── py                 # Python wrapper script (auto-detects venv)
│   ├── post_tool_use_runner.py    # PostToolUse orchestrator (~60 hooks)
│   ├── pre_tool_use_runner.py     # PreToolUse orchestrator (gates/blocks)
│   ├── user_prompt_submit_runner.py # UserPromptSubmit (context injection)
│   ├── stop_runner.py             # Stop event handler (cleanup)
│   ├── session_init.py            # SessionStart handler
│   ├── session_cleanup.py         # SessionEnd handler
│   ├── statusline.py              # Status bar renderer
│   ├── _hook_result.py            # HookResult class (approve/deny/none)
│   ├── _cooldown.py               # Cooldown management
│   ├── _config.py                 # Centralized config
│   ├── _patterns.py               # Path patterns (scratch detection)
│   ├── _beads.py                  # Bead/task tracking helpers
│   └── _*.py                      # Other private helper modules
│
├── lib/                   # Shared library modules
│   ├── core.py            # Script setup utilities (setup_script, finalize)
│   ├── confidence.py      # Confidence system (reducers/increasers)
│   ├── session_state.py   # Session state management
│   ├── oracle.py          # External LLM integration
│   ├── council_engine.py  # Multi-persona consultation
│   ├── spark_core.py      # Memory/synapse system
│   ├── detour.py          # Blocking issue tracking
│   └── analysis/          # Code analysis modules
│
├── ops/                   # Operational tools (invoked by slash commands)
│   ├── audit.py           # Code quality audit (ruff, bandit, radon)
│   ├── void.py            # Completeness checker
│   ├── oracle.py          # External LLM consultation
│   ├── council.py         # Multi-model consensus
│   ├── think.py           # Problem decomposition
│   ├── research.py        # Web search (Tavily)
│   ├── docs.py            # Documentation lookup
│   ├── verify.py          # State verification
│   └── *.py               # ~35 other tools
│
├── commands/              # Slash command definitions (markdown)
│   ├── audit.md           # /audit command
│   ├── void.md            # /void command
│   └── *.md               # ~65 other commands
│
├── rules/                 # Configuration rules
│   ├── confidence.md      # Confidence system rules
│   ├── beads.md           # Task tracking rules
│   ├── hooks.md           # Hook development guide
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
│   └── */SKILL.md         # Skill definitions
│
├── agents/                # Custom agent definitions
├── tests/                 # Test files
├── tmp/                   # Scratch/temporary files
├── cache/                 # Cached data
├── logs/                  # Log files
├── .venv/                 # Python virtual environment
├── settings.json          # Claude Code settings (hooks config)
└── requirements.txt       # Python dependencies
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
