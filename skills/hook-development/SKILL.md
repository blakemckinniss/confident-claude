---
name: hook-development
description: |
  Create hook, modify hook, add gate, hook development, pre-tool hook, post-tool hook,
  user prompt hook, stop hook, hook patterns, hook testing, hook debugging,
  Claude Code hooks, event handlers, interceptors, middleware, guards.

  Trigger phrases: create a hook, add a gate, new hook, modify the hook,
  update gate, hook system, hook patterns, pre-tool use, post-tool use,
  user prompt submit, stop hook, block action, inject context,
  hook registration, hook priority, HookResult, approve, deny,
  bypass mechanism, SUDO bypass, cooldown, rate limit, throttle,
  hook testing, audit hooks, hook debugging, hook not firing,
  hook blocking incorrectly, false positive, hook error, hook exception,
  Claude Code extension, customize Claude, extend Claude, guard rail,
  safety check, quality gate, content filter, action blocker.
---

# Hook Development

Guide for the Whitebox hook system.

## Architecture
```
~/.claude/hooks/
├── pre_tool_use_runner.py     # Gates
├── post_tool_use_runner.py    # Learning
├── user_prompt_submit_runner.py # Injection
├── stop_runner.py             # Cleanup
├── synapse_core.py            # Utilities
```

## Registration
```python
@register_hook("name", "Tool|Other", priority=50)
def check_name(data: dict, state: SessionState) -> HookResult:
    """Description."""
    return HookResult.approve()
```

## Priority Ranges
| Range | Category |
|-------|----------|
| 1-25 | Security |
| 26-45 | Safety |
| 46-54 | Complexity |
| 55-95 | Quality |

## HookResult
```python
HookResult.approve()           # Pass
HookResult.approve("msg")      # Pass + inject
HookResult.deny("msg")         # Block
```

## Bypass
```python
from synapse_core import check_sudo_in_transcript
if check_sudo_in_transcript(transcript_path):
    return HookResult.approve()
```

## Testing
```bash
/audit-hooks
```

## Rules Reference
See `~/.claude/rules/hooks.md`
