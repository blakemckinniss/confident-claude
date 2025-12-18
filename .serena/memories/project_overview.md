# Project Overview

## Purpose
Claude Code hooks and ops infrastructure - a comprehensive workflow automation system for Claude Code CLI. This is a **global WSL2 system assistant framework** providing:

- **65 registered hooks** across 4 main runners (PreToolUse, PostToolUse, UserPromptSubmit, Stop)
- **35 hook files** (runners, standalone, and helper modules)
- **51 ops tools** for code quality, debugging, and workflow automation
- **75 slash commands** for common development tasks
- **Dynamic confidence system** that mechanically regulates Claude's behavior
- **Beads task tracking** (`bd` CLI) for persistent cross-session task management
- **Mastermind multi-model orchestration** for intelligent task routing

## Tech Stack
- **Primary Language**: Python 3.x
- **Secondary**: Bash/Shell scripts
- **Virtual Environment**: `.venv/` in project root
- **Package Manager**: pip with `requirements.txt`

## Key Dependencies
```
requests>=2.31.0       # HTTP requests (oracle, research, firecrawl, groq)
websockets>=12.0       # Browser automation (Chrome DevTools Protocol)
playwright>=1.40.0     # Browser automation (optional)
ruff>=0.1.0            # Linting
bandit>=1.7.0          # Security scanning
radon>=6.0.0           # Complexity analysis
```

## Environment Variables (API Keys)
- `OPENROUTER_API_KEY` - External LLM access (oracle.py, council.py, PAL MCP)
- `TAVILY_API_KEY` - Web research (research.py)
- `FIRECRAWL_API_KEY` - Web scraping (firecrawl.py)
- `GROQ_API_KEY` - Fast inference (groq.py, mastermind router)

## Platform
- **OS**: Linux (WSL2 Ubuntu 24.04)
- **Host**: Windows 11
- **Location**: `/home/blake/.claude/`

## Architecture Summary

### Hook System
4 main runners orchestrate hooks:
1. `pre_tool_use_runner.py` - 47 permission gates, blocking checks
2. `post_tool_use_runner.py` - 1 hook (confidence tracking), inline logic
3. `user_prompt_submit_runner.py` - 1 hook, context injection via _prompt_* modules
4. `stop_runner.py` - 16 completion checks (completion_gate)

Plus: `session_init.py`, `session_cleanup.py`, `subagent_stop.py`, `pre_compact.py`, `statusline.py`

### Mastermind System
Multi-model task routing:
- `router_groq.py` - Kimi K2 fast classification (~100ms)
- `router_gpt.py` - GPT-5.2 toolchain routing for complex tasks
- `hook_integration.py` - Hook layer interface
- `config.py` - Configuration management
- Capability registry in `~/.claude/capabilities/`

### Library Modules (62 files)
- `lib/core.py` - Script utilities
- `lib/confidence.py` - Confidence regulation (facade)
- `lib/session_state.py` - State management (facade)
- `lib/oracle.py` - External LLM
- `lib/spark_core.py` - Memory system
- `lib/mastermind/` - Multi-model orchestration
- `lib/cache/` - Caching subsystem

### Ops Tools Categories (51 tools)
- Code Quality: audit, void, drift, gaps, xray
- External LLM: oracle, council, think, research, docs, groq, swarm
- Workflow: upkeep, verify, scope, evidence, detour
- System: sysinfo, housekeeping, inventory, health
- Memory: remember, spark, compress_session
- Integration: bd_bridge, bead_claim, bead_release, unified_context
- Mastermind: mastermind_rollout, mastermind_cleanup, capability_inventory

*Updated: 2025-12-17*
