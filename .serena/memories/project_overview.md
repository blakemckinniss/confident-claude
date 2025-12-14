# Project Overview

## Purpose
Claude Code hooks and ops infrastructure - a comprehensive workflow automation system for Claude Code CLI. This is a **global WSL2 system assistant framework** providing:

- **79 hooks** across 4 runners (PreToolUse, PostToolUse, UserPromptSubmit, Stop)
- **35 ops tools** for code quality, debugging, and workflow automation
- **65+ slash commands** for common development tasks
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
