# Library Modules

## Overview

The `lib/` directory contains 36 shared Python modules used by hooks and ops scripts. Major subsystems (confidence, session_state) have been split into modular components.

## Module Index (36 modules)

### Core Utilities
| Module | Purpose |
|--------|---------|
| `core.py` | Script setup utilities (`setup_script`, `finalize`, `safe_execute`) |
| `session_state.py` | Session state facade (imports from `_session_*` modules) |
| `confidence.py` | Confidence system facade (imports from `_confidence_*` modules) |

### Confidence System (Modular - 8 files)
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

### Session State (Modular - 11 files)
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

### External LLM Integration
| Module | Purpose |
|--------|---------|
| `oracle.py` | OpenRouter API calls, personas (judge, critic, skeptic) |
| `council_engine.py` | Multi-model consensus, parallel consultation |

### Memory & Context
| Module | Purpose |
|--------|---------|
| `spark_core.py` | Synapse/memory system (`fire_synapses`, `query_lessons`) |
| `synapse_core.py` | Core synapse firing logic |
| `session_rag.py` | Session history RAG (retrieval augmented generation) |
| `context_builder.py` | Context assembly for prompts |
| `epistemology.py` | Knowledge/evidence handling |

### Code Analysis
| Module | Purpose |
|--------|---------|
| `ast_analysis.py` | AST parsing and analysis |
| `analysis/__init__.py` | Submodule init |
| `analysis/god_component_detector.py` | Detects overloaded components |

### Caching Subsystem (`cache/`)
| Module | Purpose |
|--------|---------|
| `cache/__init__.py` | Cache submodule init |
| `cache/grounding_analyzer.py` | Grounding/hallucination analysis |
| `cache/embedding_client.py` | Embedding API client |
| `cache/read_cache.py` | File read caching |
| `cache/exploration_cache.py` | Codebase exploration caching |

### Workflow Management
| Module | Purpose |
|--------|---------|
| `detour.py` | Blocking issue stack management |
| `project_state.py` | Project-level state tracking |
| `project_detector.py` | Project type detection |

### Utilities
| Module | Purpose |
|--------|---------|
| `hook_registry.py` | Hook discovery and registration |
| `command_awareness.py` | Command/tool awareness |
| `persona_parser.py` | Persona prompt parsing |

## Key Facade Modules

### `confidence.py` (Facade)
Imports and re-exports from `_confidence_*` modules:
```python
from _confidence_engine import apply_reducers, apply_increasers, apply_rate_limit
from _confidence_tiers import get_tier_info, check_tool_permission
from _confidence_realignment import apply_mean_reversion, predict_trajectory
from _confidence_disputes import record_false_positive, get_adaptive_cooldown
from _confidence_streaks import update_streak, get_streak_multiplier
```

### `session_state.py` (Facade)
Imports and re-exports from `_session_*` modules:
```python
from _session_state_class import SessionState
from _session_persistence import load_state, save_state, reset_state, update_state
from _session_tracking import track_file_read, track_file_edit, track_file_create
from _session_goals import set_goal, check_goal_drift
from _session_errors import track_failure, check_sunk_cost
```

## Import Pattern

```python
import sys
from pathlib import Path

# Add lib to path (for scripts outside lib/)
sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

# Use facades for clean imports
from core import setup_script, finalize
from session_state import load_state, save_state, SessionState
from confidence import apply_reducers, get_tier_info
```
