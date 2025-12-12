---
paths: "**/.claude/hooks/**"
---

# Hook Development Guidelines

Rules for developing and maintaining the Whitebox hook system.

## Architecture

```
~/.claude/hooks/
├── pre_tool_use_runner.py    # PreToolUse orchestrator (gates)
├── post_tool_use_runner.py   # PostToolUse orchestrator (learning)
├── user_prompt_submit_runner.py  # UserPromptSubmit orchestrator (injection)
├── stop_runner.py            # Stop orchestrator (session cleanup)
├── synapse_core.py           # Shared utilities
├── analysis/                 # Analysis modules
└── py                        # Python wrapper script
```

## Hook Registration Pattern

```python
@register_hook("hook_name", "ToolName|OtherTool", priority=50)
def check_hook_name(data: dict, state: SessionState) -> HookResult:
    """Docstring becomes hook description."""
    # Implementation
    return HookResult.approve()  # or .deny(message) or .approve(message)
```

## Priority Ranges

| Range | Category | Examples |
|-------|----------|----------|
| 1-25 | Security | content_gate, security_claim_gate |
| 26-45 | Safety | production_gate, gap_detector |
| 46-54 | Complexity | god_component_gate |
| 55-95 | Quality | deferral_gate, doc_theater_gate |
| 96-100 | Cleanup | Final checks |

## HookResult Options

```python
HookResult.approve()           # Silent pass
HookResult.approve("message")  # Pass with injected message
HookResult.deny("message")     # Block with error message
```

## Bypass Mechanisms

1. **SUDO** - Check transcript for "SUDO" keyword
2. **File markers** - `# LARGE_FILE_OK: reason` as first line
3. **Path exclusions** - `.claude/tmp/`, `/.claude/` paths

```python
from synapse_core import check_sudo_in_transcript

if check_sudo_in_transcript(transcript_path):
    return HookResult.approve()
```

## State Management

```python
# Session state for cross-hook communication
state.get("key", default)
state.set("key", value)
state.get_file_edit_count(path)  # Track edit frequency
```

## Common Patterns

### Gate Pattern (block bad actions)
```python
if bad_condition:
    return HookResult.deny(f"**BLOCKED**: Reason.\nSay SUDO to bypass.")
return HookResult.approve()
```

### Injection Pattern (add context)
```python
parts = []
if condition_a:
    parts.append("Context A")
if condition_b:
    parts.append("Context B")
return HookResult.approve("\n".join(parts)) if parts else HookResult.approve()
```

### Cooldown Pattern (avoid spam)
```python
from _cooldown import should_run_check

if not should_run_check("check_name", cooldown_seconds=300):
    return HookResult.approve()
```

## Testing Hooks

```bash
# Lint
ruff check ~/.claude/hooks/pre_tool_use_runner.py

# Test specific hook behavior
# Trigger the condition and verify behavior
```

## Important Rules

1. **Never block `.claude/` paths** - Framework must be self-maintainable
2. **Always provide bypass** - SUDO or explicit marker
3. **Keep hooks fast** - They run on every tool call
4. **Avoid side effects** - Hooks should be pure functions
5. **Use cooldowns** - Prevent spam for periodic checks
6. **Document priority** - Add to runner docstring when adding hooks
