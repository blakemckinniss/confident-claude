"""
Shared hook registry for PostToolUse hooks.

Allows hooks to be split across multiple modules while sharing a single registry.
Hook modules import `register_hook` and `HOOKS` from here.
"""

import os
import re
from typing import Optional, Callable

# Format: (name, matcher_pattern, check_function, priority)
# Lower priority = runs first
# matcher_pattern: None = all tools, str = regex pattern
HOOKS: list[tuple[str, Optional[str], Callable, int]] = []


def register_hook(name: str, matcher: Optional[str], priority: int = 50):
    """Decorator to register a PostToolUse hook check function.

    Args:
        name: Hook identifier (used for disable env var)
        matcher: Regex pattern for tool names, None = all tools
        priority: Lower = runs first (0-100)

    Hooks can be disabled via environment variable:
        CLAUDE_HOOK_DISABLE_<NAME>=1

    Example:
        @register_hook("my_hook", "Bash|Edit", priority=50)
        def check_my_hook(data: dict, state: SessionState, runner_state: dict) -> HookResult:
            ...
    """

    def decorator(func: Callable):
        # Check if hook is disabled via environment variable
        env_key = f"CLAUDE_HOOK_DISABLE_{name.upper()}"
        if os.environ.get(env_key, "0") == "1":
            return func  # Skip registration
        HOOKS.append((name, matcher, func, priority))
        return func

    return decorator


def matches_tool(matcher: Optional[str], tool_name: str) -> bool:
    """Check if tool matches the hook's matcher pattern."""
    if matcher is None:
        return True
    return bool(re.match(f"^({matcher})$", tool_name))


def sort_hooks() -> None:
    """Sort hooks by priority. Call after all hook modules are imported."""
    HOOKS.sort(key=lambda x: x[3])
