"""
Shared hook registry for UserPromptSubmit hooks.

Hooks register via @register_hook(name, priority) decorator.
Lower priority = runs first.
"""

import _lib_path  # noqa: F401
import os
from typing import Callable

from session_state import SessionState
from _hook_result import HookResult

# Format: (name, check_function, priority)
HOOKS: list[tuple[str, Callable[[dict, SessionState], HookResult], int]] = []


def register_hook(name: str, priority: int = 50):
    """Decorator to register a hook check function.

    Hooks can be disabled via environment variable:
        CLAUDE_HOOK_DISABLE_<NAME>=1

    Example:
        CLAUDE_HOOK_DISABLE_GOAL_ANCHOR=1 claude
    """

    def decorator(func: Callable[[dict, SessionState], HookResult]):
        # Check if hook is disabled via environment variable
        env_key = f"CLAUDE_HOOK_DISABLE_{name.upper()}"
        if os.environ.get(env_key, "0") == "1":
            return func  # Skip registration
        HOOKS.append((name, func, priority))
        return func

    return decorator
