#!/usr/bin/env python3
"""
Common infrastructure for gate modules.

Provides shared HOOKS list and register_hook decorator that gate modules use.
"""

import sys
from pathlib import Path

# Ensure parent directories are in path for imports
_hooks_dir = Path(__file__).resolve().parent.parent
_lib_dir = _hooks_dir.parent / "lib"
for p in [str(_hooks_dir), str(_lib_dir)]:
    if p not in sys.path:
        sys.path.insert(0, p)

import os  # noqa: E402
from typing import Callable, Optional  # noqa: E402

from _hook_result import HookResult  # noqa: E402
from session_state import SessionState  # noqa: E402

# Shared hooks registry - all gate modules register into this list
HOOKS: list[tuple[str, Optional[str], Callable, int]] = []


def register_hook(name: str, matcher: Optional[str], priority: int = 50):
    """Decorator to register a hook check function.

    Hooks can be disabled via environment variable:
        CLAUDE_HOOK_DISABLE_<NAME>=1

    Example:
        CLAUDE_HOOK_DISABLE_CONTENT_GATE=1 claude
    """

    def decorator(func: Callable[[dict, SessionState], HookResult]):
        # Check if hook is disabled via environment variable
        env_key = f"CLAUDE_HOOK_DISABLE_{name.upper()}"
        if os.environ.get(env_key, "0") == "1":
            return func  # Skip registration
        HOOKS.append((name, matcher, func, priority))
        return func

    return decorator


__all__ = ["HOOKS", "register_hook", "HookResult", "SessionState"]
