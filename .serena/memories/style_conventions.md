# Style and Conventions

## Python Style

### General
- **Python version**: 3.x (compatible with system Python and venv)
- **Linter**: `ruff` (primary)
- **Formatter**: `ruff format`
- **Line length**: Default ruff settings
- **Imports**: Standard library first, then third-party, then local

### Naming Conventions
- **Functions**: `snake_case` (e.g., `check_confidence_decay`, `run_hooks`)
- **Classes**: `PascalCase` (e.g., `HookResult`, `SessionState`, `ConfidenceReducer`)
- **Constants**: `UPPER_SNAKE_CASE` (e.g., `MAX_METHOD_LINES`, `HOOKS`)
- **Private functions**: `_leading_underscore` (e.g., `_detect_error_in_result`)
- **Module-private files**: `_filename.py` (e.g., `_hook_result.py`, `_cooldown.py`)

### Type Hints
- Type hints are used but not mandatory
- Common patterns: `def func(data: dict, state: SessionState) -> HookResult:`

### Docstrings
- Simple one-line docstrings for clear functions
- Hook docstrings become the hook description in registry

## Hook Development Pattern

```python
from _hook_result import HookResult

@register_hook("hook_name", "ToolPattern", priority=50)
def check_hook_name(data: dict, state: SessionState) -> HookResult:
    """Brief description of what this hook does."""
    if blocking_condition:
        return HookResult.deny("**BLOCKED**: Reason.\nSay SUDO to bypass.")
    if injection_condition:
        return HookResult.approve("Injected context message")
    return HookResult.approve()
```

## Ops Script Pattern

```python
#!/usr/bin/env python3
"""Script description."""

import sys
from pathlib import Path

# Add lib to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

from core import setup_script, finalize

def main():
    args = setup_script(description="Tool description")
    # Implementation
    finalize(success=True, message="Result")

if __name__ == "__main__":
    main()
```

## Slash Command Format

Commands are markdown files in `commands/` with YAML frontmatter:

```markdown
---
description: 🛡️ Brief description
argument-hint: [arg_name]
allowed-tools: Bash
---

!`python3 $CLAUDE_PROJECT_DIR/.claude/ops/script.py $ARGUMENTS`
```

## File Organization

- **Hooks**: `hooks/` - Python runners and helper modules
- **Ops tools**: `ops/` - Standalone Python scripts invoked by commands
- **Library**: `lib/` - Shared Python modules
- **Commands**: `commands/` - Slash command definitions (markdown)
- **Rules**: `rules/` - Configuration rules (markdown)
- **Memory**: `memory/` - Persistent memory files (markdown)
- **Skills**: `skills/` - Claude Agent skills

## Error Handling
- Prefer early returns over nested conditionals
- Use `assert` for invariants (crash early philosophy)
- Avoid broad `try/except` - let errors surface
