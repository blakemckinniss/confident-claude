# Ops Tools System

## Overview

Ops tools are standalone Python scripts in `~/.claude/ops/` invoked by slash commands. They provide code quality, debugging, external LLM integration, and workflow automation.

## Location
- **Scripts**: `~/.claude/ops/*.py` (51 tools)
- **Commands**: `~/.claude/commands/*.md` (75 commands)
- **Library**: `~/.claude/lib/core.py` (shared utilities)

## Script Pattern

```python
#!/usr/bin/env python3
"""Tool description for help text."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

from core import setup_script, finalize

def main():
    args = setup_script(
        description="Tool description",
        add_args=lambda p: p.add_argument("target", help="Target file")
    )
    result = do_work(args.target)
    finalize(success=True, message=result)

if __name__ == "__main__":
    main()
```

## Complete Tool Index (51 tools)

### Code Quality & Analysis (5)
| Tool | Purpose |
|------|---------|
| `audit.py` | Security + complexity analysis (ruff, bandit, radon) |
| `void.py` | Completeness check (stubs, missing CRUD, error handling) |
| `drift.py` | Style drift detection |
| `gaps.py` | Find implementation gaps |
| `xray.py` | AST structural code search |

### External LLM Integration (7)
| Tool | Purpose |
|------|---------|
| `oracle.py` | External consultation (OpenRouter) |
| `council.py` | Multi-persona consensus |
| `think.py` | Problem decomposition |
| `research.py` | Web search (Tavily) |
| `docs.py` | Documentation lookup (Context7) |
| `groq.py` | Fast inference (Groq API) |
| `swarm.py` | Massive parallel oracle reasoning |

### Workflow & Task Management (6)
| Tool | Purpose |
|------|---------|
| `upkeep.py` | Pre-commit checks |
| `verify.py` | State verification |
| `scope.py` | Definition of Done tracking |
| `evidence.py` | Evidence ledger |
| `detour.py` | Blocking issue stack |
| `timekeeper.py` | Time tracking utilities |

### Memory & Context (3)
| Tool | Purpose |
|------|---------|
| `remember.py` | Persistent memory (lessons, decisions) |
| `spark.py` | Associative recall |
| `compress_session.py` | Convert session JSONL to token-efficient format |

### System & Browser (6)
| Tool | Purpose |
|------|---------|
| `sysinfo.py` | System health check |
| `housekeeping.py` | Disk cleanup |
| `inventory.py` | Available binaries scan |
| `health.py` | Quick system health status |
| `firecrawl.py` | Web scraping (Firecrawl API) |
| `probe.py` | Runtime API introspection |

### Hook Management (3)
| Tool | Purpose |
|------|---------|
| `hooks.py` | Hook testing and management |
| `audit_hooks.py` | Audit hooks against Claude Code spec |
| `test_hooks.py` | Test hook configurations |

### Confidence System (2)
| Tool | Purpose |
|------|---------|
| `fp.py` | Record false positives for reducers |
| `fp_analyze.py` | Analyze false positive patterns |

### Integration Synergy (10)
| Tool | Purpose |
|------|---------|
| `bd_bridge.py` | Beads→claude-mem observation bridge |
| `bead_claim.py` | Agent claims bead with lifecycle tracking |
| `bead_release.py` | Agent releases bead with status |
| `bead_lifecycle_daemon.py` | Background orphan recovery (120min timeout) |
| `bead_orphan_check.py` | Manual multi-project orphan diagnostic |
| `serena.py` | Serena MCP workflow hints |
| `serena_memory_lifecycle.py` | Serena memory management |
| `unified_context.py` | Aggregates all context sources |
| `integration_install.py` | One-shot installer (--check/--install) |
| `new_project.py` | Project scaffolding with full integration |

### Mastermind (3)
| Tool | Purpose |
|------|---------|
| `mastermind_rollout.py` | Phase management CLI |
| `mastermind_cleanup.py` | State cleanup tool |
| `capability_inventory.py` | Regenerate capability index |

### Code Review & Automation (4)
| Tool | Purpose |
|------|---------|
| `coderabbit.py` | AI code review integration |
| `orchestrate.py` | Claude API code_execution for batch tasks |
| `capabilities.py` | Regenerate hook/ops functionality index |
| `recruiter.py` | Agent recruitment utilities |

### Utilities (2)
| Tool | Purpose |
|------|---------|
| `patch_claude_mem_banner.py` | Patch claude-mem banner |
| `state_migrate.py` | Migrate session state format |

## Production Requirements

Writing to `~/.claude/ops/` requires:
1. `audit.py` pass (ruff + bandit + radon)
2. `void.py` pass (completeness check)

Enforced by the `production_gate` hook in `pre_tool_use_runner.py`.

*Updated: 2025-12-17*
