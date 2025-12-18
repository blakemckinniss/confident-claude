# Library Modules

## Overview

The `lib/` directory contains 62 shared Python modules used by hooks and ops scripts. Major subsystems (confidence, session_state, mastermind) are split into modular components.

## Module Index (62 modules)

### Core Utilities (3)
| Module | Purpose |
|--------|---------|
| `core.py` | Script setup utilities (`setup_script`, `finalize`, `safe_execute`) |
| `session_state.py` | Session state facade (imports from `_session_*` modules) |
| `confidence.py` | Confidence system facade (imports from `_confidence_*` modules) |

### Confidence System (9 files)
| Module | Purpose |
|--------|---------|
| `_confidence_constants.py` | Constants, thresholds, zone definitions |
| `_confidence_disputes.py` | False positive handling, disputes |
| `_confidence_engine.py` | Core apply logic, rate limiting |
| `_confidence_increasers.py` | All increaser definitions |
| `_confidence_realignment.py` | Mean reversion, trajectory prediction |
| `_confidence_reducers.py` | All reducer definitions |
| `_confidence_streaks.py` | Streak/momentum system |
| `_confidence_tiers.py` | Zone/tier definitions, tool permissions |
| `_fatigue.py` | Session fatigue tracking |

### Session State (12 files)
| Module | Purpose |
|--------|---------|
| `_session_batch.py` | Batch operation tracking |
| `_session_confidence.py` | Confidence state integration |
| `_session_constants.py` | Constants, defaults |
| `_session_context.py` | Context building for prompts |
| `_session_errors.py` | Error tracking, framework errors |
| `_session_goals.py` | Goal tracking, drift detection |
| `_session_persistence.py` | State I/O, file locking |
| `_session_state_class.py` | Main SessionState dataclass |
| `_session_thresholds.py` | Adaptive thresholds |
| `_session_tracking.py` | File/edit tracking |
| `_session_workflow.py` | Workflow state (checkpoints, handoff) |
| `_step_workflow.py` | Step-based workflow tracking |

### Mastermind System (9 files in `mastermind/`)
| Module | Purpose |
|--------|---------|
| `__init__.py` | Module exports |
| `config.py` | Configuration loading |
| `router_groq.py` | Groq/Kimi K2 classification |
| `router_gpt.py` | GPT-5.2 toolchain routing |
| `state.py` | Blueprint/state management |
| `routing.py` | Routing decisions |
| `hook_integration.py` | Hook layer interface |
| `telemetry.py` | Logging/analytics |
| `context_packer.py` | Context assembly for routers |

### Advisory System (3 files)
| Module | Purpose |
|--------|---------|
| `_advisors.py` | Advisor framework |
| `_complexity.py` | Complexity analysis |
| `_question_triggers.py` | Question trigger detection |

### External LLM Integration (4)
| Module | Purpose |
|--------|---------|
| `oracle.py` | OpenRouter API calls, personas |
| `council_engine.py` | Multi-model consensus |
| `planner_pal.py` | PAL MCP planner integration |
| `variance.py` | Model variance handling |

### Memory & Context (6)
| Module | Purpose |
|--------|---------|
| `spark_core.py` | Synapse/memory system |
| `synapse_core.py` | Core synapse firing logic |
| `session_rag.py` | Session history RAG |
| `context_builder.py` | Context assembly for prompts |
| `epistemology.py` | Knowledge/evidence handling |
| `project_context.py` | Project-level context |

### Code Analysis (3)
| Module | Purpose |
|--------|---------|
| `ast_analysis.py` | AST parsing and analysis |
| `god_component_detector.py` | Detects overloaded components |
| `drift.py` | Style drift detection |

### Caching Subsystem (4 files in `cache/`)
| Module | Purpose |
|--------|---------|
| `grounding_analyzer.py` | Grounding/hallucination analysis |
| `embedding_client.py` | Embedding API client |
| `read_cache.py` | File read caching |
| `exploration_cache.py` | Codebase exploration caching |

### Workflow & Project (5)
| Module | Purpose |
|--------|---------|
| `detour.py` | Blocking issue stack management |
| `project_state.py` | Project-level state tracking |
| `project_detector.py` | Project type detection |
| `executor_instructions.py` | Executor instruction generation |
| `agent_registry.py` | Agent registration/discovery |

### Configuration & Registry (4)
| Module | Purpose |
|--------|---------|
| `config.py` | Configuration management |
| `hook_registry.py` | Hook discovery and registration |
| `command_awareness.py` | Command/tool awareness |
| `persona_parser.py` | Persona prompt parsing |

### Security (1)
| Module | Purpose |
|--------|---------|
| `redaction.py` | Secret/sensitive data redaction |

## Key Facade Modules

### `confidence.py` (Facade)
```python
from _confidence_engine import apply_reducers, apply_increasers, apply_rate_limit
from _confidence_tiers import get_tier_info, check_tool_permission
from _confidence_realignment import apply_mean_reversion, predict_trajectory
from _confidence_disputes import record_false_positive, get_adaptive_cooldown
from _confidence_streaks import update_streak, get_streak_multiplier
```

### `session_state.py` (Facade)
```python
from _session_state_class import SessionState
from _session_persistence import load_state, save_state, reset_state
from _session_tracking import track_file_read, track_file_edit
from _session_goals import set_goal, check_goal_drift
from _session_errors import track_failure, check_sunk_cost
```

## Import Pattern

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

from core import setup_script, finalize
from session_state import load_state, save_state, SessionState
from confidence import apply_reducers, get_tier_info
```

*Updated: 2025-12-17*
