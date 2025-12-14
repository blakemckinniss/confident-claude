#!/usr/bin/env python3
"""
Session Persistence - Load, save, reset, and update state with file locking.
"""

import fcntl
import json
import os
import tempfile
import time
from dataclasses import asdict
from typing import TYPE_CHECKING

from _session_constants import (
    MEMORY_DIR,
    STATE_FILE,
    STATE_LOCK_FILE,
    _STATE_CACHE,
    _STATE_CACHE_MTIME,
)

if TYPE_CHECKING:
    from _session_state_class import SessionState


def _ensure_memory_dir():
    """Ensure memory directory exists."""
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)


def _acquire_state_lock(shared: bool = False):
    """Acquire lock for state file operations."""
    _ensure_memory_dir()
    lock_fd = os.open(str(STATE_LOCK_FILE), os.O_CREAT | os.O_RDWR)
    lock_type = fcntl.LOCK_SH if shared else fcntl.LOCK_EX
    fcntl.flock(lock_fd, lock_type)
    return lock_fd


def _release_state_lock(lock_fd: int):
    """Release state file lock."""
    fcntl.flock(lock_fd, fcntl.LOCK_UN)
    os.close(lock_fd)


def load_state() -> "SessionState":
    """Load session state from file with in-memory caching."""
    # Import here to avoid circular dependency
    from _session_state_class import SessionState
    from _session_context import _discover_ops_scripts
    from _session_thresholds import _apply_mean_reversion_on_load
    import _session_constants as const

    _ensure_memory_dir()

    # Check cache validity
    if const._STATE_CACHE is not None:
        try:
            current_mtime = STATE_FILE.stat().st_mtime if STATE_FILE.exists() else 0
            if current_mtime == const._STATE_CACHE_MTIME:
                return const._STATE_CACHE
        except OSError:
            pass

    # Cache miss or stale - load from disk
    lock_fd = _acquire_state_lock(shared=True)
    try:
        if STATE_FILE.exists():
            try:
                current_mtime = STATE_FILE.stat().st_mtime
                with open(STATE_FILE) as f:
                    data = json.load(f)
                    const._STATE_CACHE = _apply_mean_reversion_on_load(SessionState(**data))
                    const._STATE_CACHE_MTIME = current_mtime
                    return const._STATE_CACHE
            except (json.JSONDecodeError, TypeError, KeyError, OSError):
                pass
    finally:
        _release_state_lock(lock_fd)

    # No existing state - need exclusive lock to create
    lock_fd = _acquire_state_lock(shared=False)
    try:
        # Double-check after acquiring exclusive lock
        if STATE_FILE.exists():
            try:
                current_mtime = STATE_FILE.stat().st_mtime
                with open(STATE_FILE) as f:
                    data = json.load(f)
                    const._STATE_CACHE = _apply_mean_reversion_on_load(SessionState(**data))
                    const._STATE_CACHE_MTIME = current_mtime
                    return const._STATE_CACHE
            except (json.JSONDecodeError, TypeError, KeyError, OSError):
                pass

        # Initialize new state
        state = SessionState(
            session_id=os.environ.get("CLAUDE_SESSION_ID", "")[:16]
            or f"ses_{int(time.time())}",
            started_at=time.time(),
            ops_scripts=_discover_ops_scripts(),
        )
        _save_state_unlocked(state)
        const._STATE_CACHE = state
        const._STATE_CACHE_MTIME = STATE_FILE.stat().st_mtime if STATE_FILE.exists() else 0
        return state
    finally:
        _release_state_lock(lock_fd)


def _save_state_unlocked(state: "SessionState"):
    """Save state without acquiring lock (caller must hold lock)."""
    # Update activity timestamp
    state.last_activity_time = time.time()

    # Trim lists to prevent unbounded growth
    state.files_read = state.files_read[-50:]
    state.files_edited = state.files_edited[-50:]
    state.commands_succeeded = state.commands_succeeded[-20:]
    state.commands_failed = state.commands_failed[-20:]
    state.errors_recent = state.errors_recent[-10:]
    state.domain_signals = state.domain_signals[-20:]
    state.gaps_detected = state.gaps_detected[-10:]
    state.gaps_surfaced = state.gaps_surfaced[-10:]
    state.last_5_tools = state.last_5_tools[-5:]
    state.evidence_ledger = state.evidence_ledger[-20:]

    # Atomic write
    try:
        fd, tmp_path = tempfile.mkstemp(dir=MEMORY_DIR, suffix=".json")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(asdict(state), f, indent=2, default=str)
            os.replace(tmp_path, STATE_FILE)
        except Exception:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            raise
    except (IOError, OSError):
        with open(STATE_FILE, "w") as f:
            json.dump(asdict(state), f, indent=2, default=str)


def save_state(state: "SessionState"):
    """Save session state to file with locking."""
    import _session_constants as const

    _ensure_memory_dir()
    lock_fd = _acquire_state_lock()
    try:
        _save_state_unlocked(state)
        const._STATE_CACHE = state
        const._STATE_CACHE_MTIME = STATE_FILE.stat().st_mtime if STATE_FILE.exists() else 0
    finally:
        _release_state_lock(lock_fd)


def reset_state():
    """Reset state for new session."""
    import _session_constants as const

    const._STATE_CACHE = None
    const._STATE_CACHE_MTIME = 0.0

    if STATE_FILE.exists():
        STATE_FILE.unlink()
    return load_state()


def update_state(modifier_func):
    """Atomically load, modify, and save state."""
    from _session_state_class import SessionState
    from _session_context import _discover_ops_scripts
    import _session_constants as const

    _ensure_memory_dir()
    lock_fd = _acquire_state_lock()
    try:
        if STATE_FILE.exists():
            try:
                with open(STATE_FILE) as f:
                    data = json.load(f)
                    state = SessionState(**data)
            except (json.JSONDecodeError, TypeError, KeyError):
                state = SessionState(
                    session_id=os.environ.get("CLAUDE_SESSION_ID", "")[:16]
                    or f"ses_{int(time.time())}",
                    started_at=time.time(),
                    ops_scripts=_discover_ops_scripts(),
                )
        else:
            state = SessionState(
                session_id=os.environ.get("CLAUDE_SESSION_ID", "")[:16]
                or f"ses_{int(time.time())}",
                started_at=time.time(),
                ops_scripts=_discover_ops_scripts(),
            )

        modifier_func(state)
        _save_state_unlocked(state)

        const._STATE_CACHE = state
        const._STATE_CACHE_MTIME = STATE_FILE.stat().st_mtime if STATE_FILE.exists() else 0

        return state
    finally:
        _release_state_lock(lock_fd)
