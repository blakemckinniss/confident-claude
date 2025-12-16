# Project Overview

## Purpose
Claude Code hooks and ops infrastructure - a comprehensive workflow automation system for Claude Code CLI. This is a **global WSL2 system assistant framework** providing:

- **52 registered hooks** across 4 main runners (PreToolUse, PostToolUse, UserPromptSubmit, Stop)
- **31 hook files** (10 runners/standalone, 21 helper modules)
- **36 ops tools** for code quality, debugging, and workflow automation
- **66 slash commands** for common development tasks
- **Dynamic confidence system** that mechanically regulates Claude's behavior
- **Beads task tracking** (`bd` CLI) for persistent cross-session task management

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
- `OPENROUTER_API_KEY` - External LLM access (oracle.py, council.py)
- `TAVILY_API_KEY` - Web research (research.py)
- `FIRECRAWL_API_KEY` - Web scraping (firecrawl.py)
- `GROQ_API_KEY` - Fast inference (groq.py)

## Platform
- **OS**: Linux (WSL2 Ubuntu 24.04)
- **Host**: Windows 11
- **Location**: `/home/jinx/.claude/`

## Architecture Summary

### Hook System
4 main runners orchestrate hooks:
1. `pre_tool_use_runner.py` - Permission gates, blocking checks
2. `post_tool_use_runner.py` - Tool output processing (1 registered hook, inline logic)
3. `user_prompt_submit_runner.py` - Context injection, dispute detection
4. `stop_runner.py` - Completion gate, cleanup

Plus: `session_init.py`, `session_cleanup.py`, `subagent_stop.py`, `pre_compact.py`, `statusline.py`

### Library Modules
- `lib/core.py` - Script utilities
- `lib/confidence.py` - Confidence regulation
- `lib/session_state.py` - State management
- `lib/oracle.py` - External LLM
- `lib/spark_core.py` - Memory system
- `lib/cache/` - Caching subsystem

### Ops Tools Categories
- Code Quality: audit, void, drift, gaps, xray
- External LLM: oracle, council, think, research, docs, groq, swarm
- Workflow: upkeep, verify, scope, evidence, detour
- System: sysinfo, housekeeping, inventory, bdg, playwright
- Memory: remember, spark, compress_session
