"""
Unified logging framework for hook runners.

Features:
- Environment-controlled log levels via CLAUDE_HOOK_LOG_LEVEL
- Consistent error logging with context
- Optional file logging to .claude/tmp/hooks.log
- Per-hook timing instrumentation
"""

import os
import sys
import time
from pathlib import Path
from typing import Optional
from contextlib import contextmanager

# =============================================================================
# CONFIGURATION
# =============================================================================

LOG_LEVELS = {"DEBUG": 10, "INFO": 20, "WARN": 30, "ERROR": 40, "NONE": 100}

LOG_LEVEL = LOG_LEVELS.get(os.environ.get("CLAUDE_HOOK_LOG_LEVEL", "WARN").upper(), 30)

LOG_FILE = Path.home() / ".claude" / "tmp" / "hooks.log"
FILE_LOGGING = os.environ.get("CLAUDE_HOOK_FILE_LOG", "").lower() == "true"

# Profiling enabled via environment
PROFILING = os.environ.get("CLAUDE_HOOK_PROFILE", "").lower() == "true"


# =============================================================================
# LOGGING FUNCTIONS
# =============================================================================


def _should_log(level: str) -> bool:
    """Check if message should be logged at given level."""
    return LOG_LEVELS.get(level.upper(), 30) >= LOG_LEVEL


def _format_message(hook_name: str, level: str, message: str) -> str:
    """Format log message consistently."""
    timestamp = time.strftime("%H:%M:%S")
    return f"[{timestamp}] [{level}] [{hook_name}] {message}"


def _write_log(message: str) -> None:
    """Write log message to stderr and optionally to file."""
    print(message, file=sys.stderr)

    if FILE_LOGGING:
        try:
            LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(LOG_FILE, "a") as f:
                f.write(message + "\n")
        except OSError:
            pass


def log_debug(hook_name: str, message: str) -> None:
    """Log debug message."""
    if _should_log("DEBUG"):
        _write_log(_format_message(hook_name, "DEBUG", message))


def log_info(hook_name: str, message: str) -> None:
    """Log info message."""
    if _should_log("INFO"):
        _write_log(_format_message(hook_name, "INFO", message))


def log_warn(hook_name: str, message: str) -> None:
    """Log warning message."""
    if _should_log("WARN"):
        _write_log(_format_message(hook_name, "WARN", message))


def log_error(hook_name: str, message: str, error: Optional[Exception] = None) -> None:
    """Log error message with optional exception details."""
    if _should_log("ERROR"):
        if error:
            message = f"{message}: {type(error).__name__}: {error}"
        _write_log(_format_message(hook_name, "ERROR", message))


# =============================================================================
# PROFILING
# =============================================================================


class HookTimer:
    """Track execution time for hooks."""

    def __init__(self):
        self.timings: dict[str, list[float]] = {}

    def record(self, hook_name: str, duration_ms: float) -> None:
        """Record timing for a hook."""
        if hook_name not in self.timings:
            self.timings[hook_name] = []
        self.timings[hook_name].append(duration_ms)

    def get_stats(self, hook_name: str) -> dict:
        """Get timing stats for a hook."""
        times = self.timings.get(hook_name, [])
        if not times:
            return {"count": 0, "avg_ms": 0, "max_ms": 0, "total_ms": 0}
        return {
            "count": len(times),
            "avg_ms": sum(times) / len(times),
            "max_ms": max(times),
            "total_ms": sum(times),
        }

    def get_all_stats(self) -> dict[str, dict]:
        """Get timing stats for all hooks."""
        return {name: self.get_stats(name) for name in self.timings}

    def report(self) -> str:
        """Generate timing report."""
        if not self.timings:
            return "No timing data collected"

        lines = ["Hook Timing Report:", "-" * 50]
        stats = self.get_all_stats()

        # Sort by total time descending
        sorted_hooks = sorted(stats.items(), key=lambda x: -x[1]["total_ms"])

        for hook_name, s in sorted_hooks:
            lines.append(
                f"  {hook_name}: {s['count']} calls, "
                f"avg={s['avg_ms']:.1f}ms, max={s['max_ms']:.1f}ms, "
                f"total={s['total_ms']:.1f}ms"
            )

        return "\n".join(lines)


# Global timer instance
hook_timer = HookTimer()


@contextmanager
def timed_hook(hook_name: str):
    """Context manager to time hook execution."""
    if not PROFILING:
        yield
        return

    start = time.perf_counter()
    try:
        yield
    finally:
        duration_ms = (time.perf_counter() - start) * 1000
        hook_timer.record(hook_name, duration_ms)
        log_debug(hook_name, f"Completed in {duration_ms:.1f}ms")


def time_hook(func):
    """Decorator to time hook functions."""

    def wrapper(*args, **kwargs):
        if not PROFILING:
            return func(*args, **kwargs)

        hook_name = func.__name__
        start = time.perf_counter()
        try:
            return func(*args, **kwargs)
        finally:
            duration_ms = (time.perf_counter() - start) * 1000
            hook_timer.record(hook_name, duration_ms)

    return wrapper
