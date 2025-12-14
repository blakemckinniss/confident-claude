# Ops Tools System

## Overview

Ops tools are standalone Python scripts in `~/.claude/ops/` that are invoked by slash commands. They provide code quality, debugging, external LLM integration, and workflow automation.

## Location
- **Scripts**: `~/.claude/ops/*.py` (36 tools)
- **Commands**: `~/.claude/commands/*.md` (65 commands)
- **Library**: `~/.claude/lib/core.py` (shared utilities)

## Script Pattern

```python
#!/usr/bin/env python3
"""Tool description for help text."""

import sys
from pathlib import Path

# Add lib to path
sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

from core import setup_script, finalize

def main():
    args = setup_script(
        description="Tool description",
        add_args=lambda p: p.add_argument("target", help="Target file")
    )
    
    # Implementation
    result = do_work(args.target)
    
    finalize(success=True, message=result)

if __name__ == "__main__":
    main()
```

## Complete Tool Index (36 tools)

### Code Quality & Analysis
| Tool | Purpose |
|------|---------|
| `audit.py` | Security + complexity analysis (ruff, bandit, radon) |
| `void.py` | Completeness check (stubs, missing CRUD, error handling) |
| `drift.py` | Style drift detection |
| `gaps.py` | Find implementation gaps |
| `xray.py` | AST structural code search |

### External LLM Integration
| Tool | Purpose |
|------|---------|
| `oracle.py` | External consultation (OpenRouter) |
| `council.py` | Multi-persona consensus |
| `think.py` | Problem decomposition |
| `research.py` | Web search (Tavily) |
| `docs.py` | Documentation lookup (Context7) |
| `groq.py` | Fast inference (Groq API) |
| `swarm.py` | Massive parallel oracle reasoning |

### Workflow & Task Management
| Tool | Purpose |
|------|---------|
| `upkeep.py` | Pre-commit checks |
| `verify.py` | State verification |
| `scope.py` | Definition of Done tracking |
| `evidence.py` | Evidence ledger |
| `detour.py` | Blocking issue stack |
| `timekeeper.py` | Time tracking utilities |

### Memory & Context
| Tool | Purpose |
|------|---------|
| `remember.py` | Persistent memory (lessons, decisions) |
| `spark.py` | Associative recall |
| `compress_session.py` | Convert session JSONL to token-efficient format |

### System & Browser
| Tool | Purpose |
|------|---------|
| `sysinfo.py` | System health check |
| `housekeeping.py` | Disk cleanup |
| `inventory.py` | Available binaries scan |
| `bdg.py` | Chrome DevTools Protocol CLI |
| `playwright.py` | Browser automation setup |
| `firecrawl.py` | Web scraping (Firecrawl API) |

### Hook Management
| Tool | Purpose |
|------|---------|
| `hooks.py` | Hook testing and management |
| `audit_hooks.py` | Audit hooks against Claude Code spec |
| `test_hooks.py` | Test hook configurations |

### Confidence System
| Tool | Purpose |
|------|---------|
| `fp.py` | Record false positives for reducers |

### Code Review & Automation
| Tool | Purpose |
|------|---------|
| `coderabbit.py` | AI code review integration |
| `orchestrate.py` | Claude API code_execution for batch tasks |
| `capabilities.py` | Regenerate hook/ops functionality index |
| `recruiter.py` | Agent recruitment utilities |
| `probe.py` | Runtime API introspection |

## Core Library (`lib/core.py`)

```python
def get_project_root() -> Path:
    """Find .claude directory by walking up."""

def setup_script(description: str, add_args: Callable = None) -> argparse.Namespace:
    """Standard argument parsing with --debug, --dry-run."""

def finalize(success: bool, message: str):
    """Exit with proper code and message."""

def safe_execute(cmd: list[str]) -> tuple[int, str, str]:
    """Run subprocess safely."""
```

## Production Requirements

Writing to `~/.claude/ops/` requires:
1. `audit.py` pass (ruff + bandit + radon)
2. `void.py` pass (completeness check)

This is enforced by the `production_gate` hook in `pre_tool_use_runner.py`.
