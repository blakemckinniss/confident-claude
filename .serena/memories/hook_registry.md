# Hook Registry System

## Overview

Hooks are registered via decorator and stored in the `HOOKS` list. The runner executes them in priority order, checking matchers against the tool name.

## File Structure

### Runners (4 main entry points)
| File | Event | Purpose |
|------|-------|---------|
| `post_tool_use_runner.py` | PostToolUse | ~60 hooks for tool output processing |
| `pre_tool_use_runner.py` | PreToolUse | Permission gates, blocking checks |
| `user_prompt_submit_runner.py` | UserPromptSubmit | Context injection, dispute detection |
| `stop_runner.py` | Stop | Completion gate, cleanup |

### Additional Runners
| File | Event | Purpose |
|------|-------|---------|
| `session_init.py` | SessionStart | Session initialization |
| `session_cleanup.py` | SessionEnd | Session cleanup |
| `subagent_stop.py` | SubagentStop | Subagent completion handling |
| `pre_compact.py` | PreCompact | Pre-compaction processing |
| `statusline.py` | Statusline | Status bar rendering |

### Helper Modules (Private)
| File | Purpose |
|------|---------|
| `_hook_result.py` | HookResult class (approve/deny/none) |
| `_cooldown.py` | Cooldown management |
| `_config.py` | Centralized configuration |
| `_patterns.py` | Path patterns (scratch detection) |
| `_beads.py` | Bead/task tracking helpers |
| `_logging.py` | Hook logging utilities |
| `_ast_utils.py` | AST analysis utilities |
| `_lib_path.py` | Library path management |
| `_pal_mandates.py` | PAL MCP mandate handling |
| `_quality_scanner.py` | Code quality scanning |
| `_cache.py` | Hook result caching |
| `_intent_classifier.py` | Intent classification |
| `_hooks_state.py` | Hook state management |
| `_hooks_quality.py` | Quality check helpers |
| `_hooks_tracking.py` | Tracking utilities |
| `_hooks_cache.py` | Hook result caching |
| `_hook_registry.py` | Hook discovery/registration |
| `_prompt_registry.py` | Prompt injection registry |
| `_prompt_suggestions.py` | Contextual suggestions |
| `_prompt_gating.py` | Prompt-level gating |
| `_prompt_context.py` | Context building for prompts |
| `py` | Python wrapper script (auto-detects venv) |

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

1. Choose appropriate runner file
2. Add function with `@register_hook` decorator
3. Assign priority in correct range
4. Return `HookResult.approve()`, `.deny()`, or `.none()`
5. Update runner docstring with hook documentation
