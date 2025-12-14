# Library Modules

## Overview

The `lib/` directory contains shared Python modules used by hooks and ops scripts.

## Module Index

### Core Utilities

| Module | Purpose |
|--------|---------|
| `core.py` | Script setup utilities (`setup_script`, `finalize`, `safe_execute`) |
| `session_state.py` | Session state management (`SessionState` dataclass, persistence) |
| `confidence.py` | Confidence system (reducers, increasers, zones, gates) |

### External LLM Integration

| Module | Purpose |
|--------|---------|
| `oracle.py` | OpenRouter API calls, personas (judge, critic, skeptic) |
| `council_engine.py` | Multi-model consensus, parallel consultation |

### Memory & Context

| Module | Purpose |
|--------|---------|
| `spark_core.py` | Synapse/memory system (`fire_synapses`, `query_lessons`) |
| `session_rag.py` | Session history RAG (retrieval augmented generation) |
| `context_builder.py` | Context assembly for prompts |

### Code Analysis

| Module | Purpose |
|--------|---------|
| `ast_analysis.py` | AST parsing and analysis |
| `analysis/` | Analysis submodules (god_component_detector) |

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
| `epistemology.py` | Knowledge/evidence handling |

## Key Module Details

### `core.py`
```python
def get_project_root() -> Path:
    """Find .claude directory by walking up."""

def setup_script(description: str, add_args=None) -> Namespace:
    """Standard arg parsing with --debug, --dry-run."""

def finalize(success: bool, message: str):
    """Exit with proper code and message."""

def safe_execute(cmd: list[str]) -> tuple[int, str, str]:
    """Run subprocess safely, return (code, stdout, stderr)."""
```

### `oracle.py`
```python
def call_openrouter(prompt: str, model: str = None) -> str:
    """Call OpenRouter API with prompt."""

def oracle_judge(proposal: str) -> str:
    """ROI/value assessment persona."""

def oracle_critic(idea: str) -> str:
    """10th Man attack persona."""

def oracle_skeptic(proposal: str) -> str:
    """Hostile review persona."""

def oracle_consult(question: str) -> str:
    """General consultation."""
```

### `spark_core.py`
```python
def fire_synapses(topic: str) -> list[dict]:
    """Retrieve associative memories for topic."""

def query_lessons(keywords: list[str]) -> list[str]:
    """Query lessons file for matching entries."""

def query_session_history(query: str) -> list[dict]:
    """Search session history via RAG."""
```

### `detour.py`
```python
def detect_detour(text: str) -> Optional[DetourPattern]:
    """Detect blocking issue patterns in text."""

def push_detour(detour: Detour):
    """Push blocking issue onto stack."""

def pop_detour() -> Optional[Detour]:
    """Pop and resolve top detour."""

def get_active_detours() -> list[Detour]:
    """Get all unresolved detours."""

def get_resume_prompt(detour: Detour) -> str:
    """Generate prompt to resume after detour."""
```

## Import Pattern

```python
import sys
from pathlib import Path

# Add lib to path (for scripts outside lib/)
sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

# Now import
from core import setup_script, finalize
from session_state import load_state, save_state
from confidence import apply_reducers
```

## Analysis Submodule

```python
# lib/analysis/__init__.py
from .god_component_detector import detect_god_components
```

Detects components with too many responsibilities (> threshold methods/props).
