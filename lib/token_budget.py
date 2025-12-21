#!/usr/bin/env python3
"""
Token Budget Manager - Dynamic token allocation with phase-based compression.

Implements progressive disclosure pattern:
- Phase 1 (<40%): Full verbosity
- Phase 2 (40-70%): Condensed format
- Phase 3 (70-85%): Signals only
- Phase 4 (>85%): Critical only, hooks auto-disable

v1.0: Initial implementation
"""

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Callable, Optional
import time

# Token budget constants
MAX_CONTEXT_TOKENS = 200_000
PHASE_VERBOSE_THRESHOLD = 0.0  # 0-40%
PHASE_CONDENSED_THRESHOLD = 0.40  # 40-70%
PHASE_SIGNALS_THRESHOLD = 0.70  # 70-85%
PHASE_CRITICAL_THRESHOLD = 0.85  # 85%+

# Default hook token allocations
CORE_SYSTEM_TOKENS = 15_000
SESSION_STATE_TOKENS = 2_000
CONFIDENCE_SYSTEM_TOKENS = 20_000
MASTERMIND_ROUTING_TOKENS = 15_000
RALPH_COMPLETION_TOKENS = 10_000
SUGGESTIONS_TOKENS = 12_000
CONTEXT_INJECTOR_TOKENS = 8_000
MEMORY_INJECTOR_TOKENS = 5_000
ANALYTICS_TOKENS = 5_000
DEBUG_TRACE_TOKENS = 3_000


class Phase(IntEnum):
    """Context usage phases with thresholds."""

    VERBOSE = 1  # <40% - Full verbosity
    CONDENSED = 2  # 40-70% - Compressed output
    SIGNALS = 3  # 70-85% - Minimal signals
    CRITICAL = 4  # >85% - Emergency mode


class HookPriority(IntEnum):
    """Hook priority levels - higher priority = more essential."""

    P0 = 0  # Core system - never disable
    P1 = 1  # Confidence, Mastermind - compress at Phase 3
    P2 = 2  # Ralph, Suggestions - disable at Phase 3
    P3 = 3  # Analytics, Debug - disable at Phase 2


@dataclass
class HookBudget:
    """Token budget allocation for a hook."""

    name: str
    priority: HookPriority
    base_tokens: int  # Tokens at Phase 1
    phase_multipliers: dict = field(
        default_factory=lambda: {
            Phase.VERBOSE: 1.0,
            Phase.CONDENSED: 0.5,
            Phase.SIGNALS: 0.2,
            Phase.CRITICAL: 0.0,
        }
    )

    def get_budget(self, phase: Phase) -> int:
        """Get token budget for current phase."""
        multiplier = self.phase_multipliers.get(phase, 0.0)
        return int(self.base_tokens * multiplier)

    def is_enabled(self, phase: Phase) -> bool:
        """Check if hook should run at current phase."""
        # P0 always runs
        if self.priority == HookPriority.P0:
            return True
        # P3 disabled at Phase 2+
        if self.priority == HookPriority.P3 and phase >= Phase.CONDENSED:
            return False
        # P2 disabled at Phase 3+
        if self.priority == HookPriority.P2 and phase >= Phase.SIGNALS:
            return False
        # P1 disabled at Phase 4
        if self.priority == HookPriority.P1 and phase >= Phase.CRITICAL:
            return False
        return True


# Default hook budgets (tokens at Phase 1 = 200K context)
DEFAULT_BUDGETS = {
    # P0 - Core (never disable)
    "core_system": HookBudget("core_system", HookPriority.P0, 15000),
    "session_state": HookBudget("session_state", HookPriority.P0, 2000),
    # P1 - Essential (compress at Phase 3, disable at Phase 4)
    "confidence_system": HookBudget("confidence_system", HookPriority.P1, 20000),
    "mastermind_routing": HookBudget(
        "mastermind_routing",
        HookPriority.P1,
        15000,
        {
            Phase.VERBOSE: 1.0,
            Phase.CONDENSED: 0.3,  # Lazy-load capabilities
            Phase.SIGNALS: 0.15,  # Cached routing table only
            Phase.CRITICAL: 0.0,
        },
    ),
    "ralph_completion": HookBudget("ralph_completion", HookPriority.P1, 10000),
    # P2 - Important (disable at Phase 3)
    "suggestions": HookBudget("suggestions", HookPriority.P2, 12000),
    "context_injector": HookBudget("context_injector", HookPriority.P2, 8000),
    "memory_injector": HookBudget("memory_injector", HookPriority.P2, 5000),
    # P3 - Optional (disable at Phase 2)
    "analytics": HookBudget("analytics", HookPriority.P3, 5000),
    "debug_trace": HookBudget("debug_trace", HookPriority.P3, 3000),
}


@dataclass
class PhaseState:
    """Current phase state with transition tracking."""

    phase: Phase = Phase.VERBOSE
    token_usage: int = 0
    max_tokens: int = 200000
    last_update: float = 0.0
    transition_count: int = 0

    @property
    def usage_percent(self) -> float:
        """Get usage as percentage."""
        return (self.token_usage / self.max_tokens) * 100 if self.max_tokens > 0 else 0


class TokenBudgetManager:
    """
    Manages token budgets across all hooks with phase-based allocation.

    Usage:
        manager = TokenBudgetManager()
        manager.update_usage(150000)  # Update token count

        budget = manager.get_budget("confidence_system")
        if manager.is_hook_enabled("analytics"):
            # Run analytics hook
    """

    # Phase thresholds (percentage of max tokens)
    PHASE_THRESHOLDS = {
        Phase.VERBOSE: 0.0,  # 0-40%
        Phase.CONDENSED: 0.40,  # 40-70%
        Phase.SIGNALS: 0.70,  # 70-85%
        Phase.CRITICAL: 0.85,  # 85%+
    }

    def __init__(
        self,
        max_tokens: int = 200000,
        budgets: Optional[dict[str, HookBudget]] = None,
        on_phase_change: Optional[Callable[[Phase, Phase], None]] = None,
    ):
        self.max_tokens = max_tokens
        self.budgets = budgets or DEFAULT_BUDGETS.copy()
        self.on_phase_change = on_phase_change
        self.state = PhaseState(max_tokens=max_tokens)
        self._phase_listeners: list[Callable[[Phase], None]] = []

    def add_phase_listener(self, listener: Callable[[Phase], None]) -> None:
        """Register a listener for phase changes."""
        self._phase_listeners.append(listener)

    def update_usage(self, token_count: int) -> Phase:
        """
        Update token usage and recalculate phase.

        Returns the current phase (may have changed).
        """
        old_phase = self.state.phase
        self.state.token_usage = token_count
        self.state.last_update = time.time()

        # Calculate new phase
        usage_pct = token_count / self.max_tokens
        new_phase = Phase.VERBOSE

        for phase, threshold in sorted(
            self.PHASE_THRESHOLDS.items(), key=lambda x: x[1], reverse=True
        ):
            if usage_pct >= threshold:
                new_phase = phase
                break

        # Handle phase transition
        if new_phase != old_phase:
            self.state.phase = new_phase
            self.state.transition_count += 1

            # Notify listeners
            if self.on_phase_change:
                self.on_phase_change(old_phase, new_phase)
            for listener in self._phase_listeners:
                listener(new_phase)

        return self.state.phase

    def get_phase(self) -> Phase:
        """Get current phase."""
        return self.state.phase

    def get_budget(self, hook_name: str) -> int:
        """Get token budget for a hook at current phase."""
        budget = self.budgets.get(hook_name)
        if not budget:
            return 0
        return budget.get_budget(self.state.phase)

    def is_hook_enabled(self, hook_name: str) -> bool:
        """Check if a hook should run at current phase."""
        budget = self.budgets.get(hook_name)
        if not budget:
            return True  # Unknown hooks default to enabled
        return budget.is_enabled(self.state.phase)

    def get_total_budget(self) -> int:
        """Get total allocated budget across all enabled hooks."""
        total = 0
        for name, budget in self.budgets.items():
            if budget.is_enabled(self.state.phase):
                total += budget.get_budget(self.state.phase)
        return total

    def get_remaining_budget(self) -> int:
        """Get tokens remaining after hook allocations."""
        return self.max_tokens - self.state.token_usage - self.get_total_budget()

    def format_status(self) -> str:
        """Format current status for display."""
        phase_names = {
            Phase.VERBOSE: "VERBOSE",
            Phase.CONDENSED: "CONDENSED",
            Phase.SIGNALS: "SIGNALS",
            Phase.CRITICAL: "CRITICAL",
        }
        phase_emoji = {
            Phase.VERBOSE: "💚",
            Phase.CONDENSED: "🟡",
            Phase.SIGNALS: "🟠",
            Phase.CRITICAL: "🔴",
        }

        p = self.state.phase
        return (
            f"{phase_emoji[p]} Phase {p.value}: {phase_names[p]} | "
            f"{self.state.usage_percent:.1f}% used | "
            f"{self.get_remaining_budget():,} tokens remaining"
        )

    def get_compression_hints(self) -> dict[str, str]:
        """Get compression hints for each hook based on current phase."""
        hints = {}
        for name, budget in self.budgets.items():
            if not budget.is_enabled(self.state.phase):
                hints[name] = "DISABLED"
            elif self.state.phase == Phase.VERBOSE:
                hints[name] = "FULL"
            elif self.state.phase == Phase.CONDENSED:
                hints[name] = "COMPRESS"
            elif self.state.phase == Phase.SIGNALS:
                hints[name] = "SIGNAL_ONLY"
            else:
                hints[name] = "MINIMAL"
        return hints


# Singleton instance for global access
_manager: Optional[TokenBudgetManager] = None


def get_budget_manager() -> TokenBudgetManager:
    """Get the global TokenBudgetManager instance."""
    global _manager
    if _manager is None:
        _manager = TokenBudgetManager()
    return _manager


def reset_budget_manager() -> None:
    """Reset the global manager (for testing)."""
    global _manager
    _manager = None
