#!/usr/bin/env python3
"""
Phase-aware hook gating for token budget optimization.

Provides decorators and helpers to skip/compress hooks based on current phase.
Hooks declare their priority level and get automatically disabled when context is high.

v1.0: Initial implementation
"""

from enum import IntEnum
from functools import wraps
from typing import Callable, Any

# Import token budget manager
try:
    from token_budget import get_budget_manager, Phase

    BUDGET_AVAILABLE = True
except ImportError:
    BUDGET_AVAILABLE = False
    Phase = None


class HookTier(IntEnum):
    """Hook importance tiers - determines when hooks get disabled."""

    CRITICAL = 0  # Never disable (core system, security)
    ESSENTIAL = 1  # Disable at CRITICAL phase only
    IMPORTANT = 2  # Disable at SIGNALS phase
    OPTIONAL = 3  # Disable at CONDENSED phase
    VERBOSE = 4  # Disable at any non-VERBOSE phase


# Phase thresholds for each tier
TIER_PHASE_LIMITS = {
    HookTier.CRITICAL: None,  # Never disabled
    HookTier.ESSENTIAL: 4,  # Disabled at Phase.CRITICAL (4)
    HookTier.IMPORTANT: 3,  # Disabled at Phase.SIGNALS (3)
    HookTier.OPTIONAL: 2,  # Disabled at Phase.CONDENSED (2)
    HookTier.VERBOSE: 1,  # Only runs at Phase.VERBOSE (1)
}


def get_current_phase() -> int:
    """Get current phase (1-4), defaults to VERBOSE if unavailable."""
    if not BUDGET_AVAILABLE:
        return 1  # VERBOSE

    try:
        mgr = get_budget_manager()
        return mgr.get_phase().value
    except Exception:
        return 1  # VERBOSE


def should_run_hook(tier: HookTier) -> bool:
    """Check if a hook with given tier should run at current phase."""
    if tier == HookTier.CRITICAL:
        return True

    current_phase = get_current_phase()
    phase_limit = TIER_PHASE_LIMITS.get(tier)

    if phase_limit is None:
        return True

    # Hook runs if current phase is LESS than the limit
    return current_phase < phase_limit


def phase_gate(tier: HookTier, fallback: Any = None):
    """Decorator to gate hook execution based on phase.

    Usage:
        @phase_gate(HookTier.OPTIONAL)
        def my_optional_hook(data, state):
            # Only runs at VERBOSE phase
            ...

    Args:
        tier: The importance tier of this hook
        fallback: Value to return if hook is skipped (default: None)
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            if not should_run_hook(tier):
                return fallback
            return func(*args, **kwargs)

        # Store tier for introspection
        wrapper._phase_tier = tier
        return wrapper

    return decorator


def compress_output(output: str, max_chars: int = None) -> str:
    """Compress output based on current phase.

    VERBOSE: Full output
    CONDENSED: Truncate to 500 chars
    SIGNALS: Truncate to 200 chars
    CRITICAL: Truncate to 100 chars
    """
    if not output:
        return output

    phase = get_current_phase()

    if max_chars is None:
        max_chars = {
            1: len(output),  # VERBOSE - no limit
            2: 500,  # CONDENSED
            3: 200,  # SIGNALS
            4: 100,  # CRITICAL
        }.get(phase, len(output))

    if len(output) <= max_chars:
        return output

    return output[: max_chars - 3] + "..."


def get_phase_status() -> str:
    """Get human-readable phase status."""
    if not BUDGET_AVAILABLE:
        return "Phase: unknown (budget manager unavailable)"

    try:
        mgr = get_budget_manager()
        return mgr.format_status()
    except Exception as e:
        return f"Phase: error ({e})"


# Convenience exports for common patterns
def is_verbose() -> bool:
    """Check if we're in VERBOSE phase (full output allowed)."""
    return get_current_phase() == 1


def is_critical() -> bool:
    """Check if we're in CRITICAL phase (minimal output only)."""
    return get_current_phase() >= 4
