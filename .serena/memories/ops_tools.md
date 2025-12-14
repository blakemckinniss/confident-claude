# Ops Tools System

## Overview

Ops tools are standalone Python scripts in `~/.claude/ops/` that are invoked by slash commands. They provide code quality, debugging, external LLM integration, and workflow automation.

## Location
- **Scripts**: `~/.claude/ops/*.py` (~35 tools)
- **Commands**: `~/.claude/commands/*.md` (~65 commands)
- **Library**: `~/.claude/lib/core.py` (shared utilities)

## Script Pattern

```python
#!/usr/bin/env python3
"""Tool description for help text."""

import sys
from pathlib import Path

# Add lib to path
sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

from core import setup_script, finalize, handle_debug

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

## Core Library (`lib/core.py`)

```python
def get_project_root() -> Path:
    """Find .claude directory by walking up."""

def setup_script(description: str, add_args: Callable = None) -> argparse.Namespace:
    """Standard argument parsing with --debug, --dry-run."""

def handle_debug(args):
    """Enable debug logging if --debug."""

def check_dry_run(args) -> bool:
    """Check if --dry-run mode."""

def finalize(success: bool, message: str):
    """Exit with proper code and message."""

def safe_execute(cmd: list[str]) -> tuple[int, str, str]:
    """Run subprocess safely."""
```

## Tool Categories

### Code Quality
| Tool | Purpose |
|------|---------|
| `audit.py` | Security + complexity analysis (ruff, bandit, radon) |
| `void.py` | Completeness check (stubs, missing CRUD, error handling) |
| `drift.py` | Style drift detection |
| `gaps.py` | Find implementation gaps |

### External LLM
| Tool | Purpose |
|------|---------|
| `oracle.py` | External consultation (OpenRouter) |
| `council.py` | Multi-persona consensus |
| `think.py` | Problem decomposition |
| `research.py` | Web search (Tavily) |
| `docs.py` | Documentation lookup |
| `groq.py` | Fast inference (Groq) |

### Workflow
| Tool | Purpose |
|------|---------|
| `upkeep.py` | Pre-commit checks |
| `verify.py` | State verification |
| `scope.py` | Definition of Done tracking |
| `evidence.py` | Evidence ledger |
| `detour.py` | Blocking issue stack |

### System
| Tool | Purpose |
|------|---------|
| `sysinfo.py` | System health check |
| `housekeeping.py` | Disk cleanup |
| `inventory.py` | Available binaries |
| `bdg.py` | Chrome DevTools Protocol |

### Memory
| Tool | Purpose |
|------|---------|
| `remember.py` | Persistent memory |
| `spark.py` | Associative recall |

## Slash Command Format

Commands in `~/.claude/commands/*.md`:

```markdown
---
description: 🛡️ Brief description
argument-hint: [arg_name]
allowed-tools: Bash
---

!`python3 $CLAUDE_PROJECT_DIR/.claude/ops/script.py $ARGUMENTS`
```

**Variables available:**
- `$ARGUMENTS` - User arguments after command
- `$CLAUDE_PROJECT_DIR` - Project root

## Adding a New Tool

1. Create `~/.claude/ops/newtool.py` following the script pattern
2. Create `~/.claude/commands/newtool.md` with YAML frontmatter
3. Use `lib/core.py` utilities for consistency
4. Run `audit` and `void` before committing to ops/

## Tracking Usage

```python
# lib/session_state.py
track_ops_tool(tool_name: str)
get_ops_tool_stats() -> dict
get_unused_ops_tools() -> list
```

## Production Requirements

Writing to `~/.claude/ops/` requires:
1. `audit.py` pass (ruff + bandit + radon)
2. `void.py` pass (completeness check)

This is enforced by the `production_gate` hook in `pre_tool_use_runner.py`.
