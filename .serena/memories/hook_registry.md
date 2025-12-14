# Hook Registry System

## Overview

Hooks are registered via decorator and stored in the `HOOKS` list. The runner executes them in priority order, checking matchers against the tool name.

## Registration Pattern

```python
# In hooks/*_runner.py
HOOKS: list[tuple[str, Optional[str], Callable, int]] = []

def register_hook(name: str, matcher: Optional[str], priority: int = 50):
    """Decorator to register a hook check function.

    Hooks can be disabled via environment variable:
        CLAUDE_HOOK_DISABLE_<NAME>=1

    Example:
        CLAUDE_HOOK_DISABLE_ASSUMPTION_CHECK=1 claude
    """
    def decorator(func: Callable[[dict, SessionState, dict], HookResult]):
        env_key = f"CLAUDE_HOOK_DISABLE_{name.upper()}"
        if os.environ.get(env_key, "0") == "1":
            return func  # Skip registration
        HOOKS.append((name, matcher, func, priority))
        return func
    return decorator
```

## Hook Function Signature

```python
@register_hook("hook_name", "ToolPattern|OtherTool", priority=50)
def check_hook_name(data: dict, state: SessionState, config: dict) -> HookResult:
    """Docstring becomes hook description."""
    # data: Tool input/output from Claude Code
    # state: SessionState instance
    # config: Loaded from _config.py
    return HookResult.approve()
```

## Priority Ranges

| Range | Category | Purpose |
|-------|----------|---------|
| 1-25 | Security | Content gates, security claims |
| 26-45 | Safety | Production gates, gap detection |
| 46-54 | Complexity | God component detection |
| 55-95 | Quality | Deferral, doc theater, code quality |
| 96-100 | Cleanup | Final checks, state updates |

## Matcher Patterns

- `None` or empty: Matches all tools
- `"Bash"`: Exact match
- `"Bash|Edit|Write"`: OR pattern (pipe-separated)
- Uses `re.match()` internally

## Runner Execution Flow

```python
def run_hooks(data: dict, state: SessionState, config: dict) -> HookResult:
    # 1. Pre-compute SUDO bypass (once per call)
    data["_sudo_bypass"] = check_sudo_in_response(data)
    
    # 2. Sort hooks by priority
    sorted_hooks = sorted(HOOKS, key=lambda h: h[3])
    
    # 3. Execute matching hooks
    messages = []
    for name, matcher, func, priority in sorted_hooks:
        if matcher and not re.match(matcher, tool_name):
            continue
        result = func(data, state, config)
        if result.decision == "deny":
            return result  # Early exit on block
        if result.message:
            messages.append(result.message)
    
    # 4. Aggregate approved messages
    return HookResult.approve("\n".join(messages)) if messages else HookResult.approve()
```

## HookResult API

```python
# hooks/_hook_result.py
class HookResult:
    @classmethod
    def approve(cls, message: str = "") -> HookResult:
        """Pass, optionally inject context."""
    
    @classmethod
    def deny(cls, message: str) -> HookResult:
        """Block with error message."""
    
    @classmethod
    def none(cls) -> HookResult:
        """No-op, skip this hook."""
    
    def with_context(self, **kwargs) -> HookResult:
        """Add metadata to result."""
```

## Disabling Hooks

```bash
# Environment variable (per-hook)
CLAUDE_HOOK_DISABLE_CODE_QUALITY=1 claude

# SUDO bypass (in prompt)
"SUDO" in user message → data["_sudo_bypass"] = True
```

## Adding a New Hook

1. Choose appropriate runner file (`pre_tool_use_runner.py`, `post_tool_use_runner.py`, etc.)
2. Add function with `@register_hook` decorator
3. Assign priority in correct range
4. Return `HookResult.approve()`, `.deny()`, or `.none()`
5. Update runner docstring with hook documentation
