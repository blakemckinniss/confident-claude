"""
Shared hook registry for Stop hooks.

Hooks register via @register_hook(name, priority) decorator.
Lower priority = runs first.
"""

import _lib_path  # noqa: F401
import os
from dataclasses import dataclass
from typing import Callable

from session_state import SessionState


# =============================================================================
# STOP HOOK RESULT TYPE
# =============================================================================


@dataclass
class StopHookResult:
    """Result from a Stop hook check.

    Stop hooks use "continue"/"block" semantics with stop_reason for warnings,
    while pre/post hooks use "approve"/"deny" with context injection.
    """

    decision: str = "continue"  # "continue" or "block"
    reason: str = ""  # Reason for block
    stop_reason: str = ""  # Warning message (non-blocking)

    @staticmethod
    def ok(stop_reason: str = "") -> "StopHookResult":
        """Return continue result, optionally with a non-blocking message."""
        return StopHookResult(decision="continue", stop_reason=stop_reason)

    @staticmethod
    def warn(message: str) -> "StopHookResult":
        return StopHookResult(decision="continue", stop_reason=message)

    @staticmethod
    def block(reason: str) -> "StopHookResult":
        return StopHookResult(decision="block", reason=reason)


# =============================================================================
# HOOK REGISTRY
# =============================================================================

# Format: (name, check_function, priority)
HOOKS: list[tuple[str, Callable[[dict, SessionState], StopHookResult], int]] = []


def register_hook(name: str, priority: int = 50):
    """Decorator to register a hook check function.

    Hooks can be disabled via environment variable:
        CLAUDE_HOOK_DISABLE_<NAME>=1

    Example:
        CLAUDE_HOOK_DISABLE_SESSION_CLEANUP=1 claude
    """

    def decorator(func: Callable[[dict, SessionState], StopHookResult]):
        # Check if hook is disabled via environment variable
        env_name = f"CLAUDE_HOOK_DISABLE_{name.upper()}"
        if os.environ.get(env_name) == "1":
            return func  # Return func but don't register

        HOOKS.append((name, func, priority))
        return func

    return decorator
