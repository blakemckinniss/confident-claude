# Hook Registry System

## Overview

Hooks are registered via decorator and stored in the `HOOKS` list. The runner executes them in priority order, checking matchers against the tool name.

## Current Hook Counts

| Runner | Registered Hooks | Purpose |
|--------|------------------|---------|
| `pre_tool_use_runner.py` | 47 | Permission gates, blocking checks |
| `post_tool_use_runner.py` | 1 | Confidence tracking (bulk logic inline) |
| `user_prompt_submit_runner.py` | 1 | Context injection via _prompt_* modules |
| `stop_runner.py` | 16 | Completion gate, cleanup |
| **Total** | **42 files** | (see runners for registered hook counts) |

## File Structure

### Runners (4 main entry points)
| File | Event | Hooks |
|------|-------|-------|
| `pre_tool_use_runner.py` | PreToolUse | 47 gates |
| `post_tool_use_runner.py` | PostToolUse | 1 + inline logic |
| `user_prompt_submit_runner.py` | UserPromptSubmit | 1 + _prompt_* modules |
| `stop_runner.py` | Stop | 16 checks |

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
| `_prompt_mastermind.py` | Mastermind integration (priority 6) |
| `py` | Python wrapper script (auto-detects venv) |

## Registration Pattern

```python
# In hooks/*_runner.py
HOOKS: list[tuple[str, Optional[str], Callable, int]] = []

def register_hook(name: str, matcher: Optional[str], priority: int = 50):
    """Decorator to register a hook check function.

    Hooks can be disabled via environment variable:
        CLAUDE_HOOK_DISABLE_<NAME>=1
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

*Updated: 2025-12-17*
