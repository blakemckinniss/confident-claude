#!/usr/bin/env python3
"""
Session Persistence - Load, save, reset, and update state with file locking.

v3.13: Project-aware state isolation
- Each project gets its own session_state.json
- Prevents hook noise from leaking across projects
- Falls back to global state for ephemeral contexts
"""

import fcntl
import json
import os
import tempfile
import time
from dataclasses import asdict
from typing import TYPE_CHECKING

from _session_constants import (
    get_project_state_file,
    get_project_lock_file,
)

if TYPE_CHECKING:
    from _session_state_class import SessionState


def _ensure_memory_dir():
    """Ensure memory directory exists for current project."""
    state_file = get_project_state_file()
    state_file.parent.mkdir(parents=True, exist_ok=True)


def _acquire_state_lock(shared: bool = False):
    """Acquire lock for state file operations (project-aware)."""
    _ensure_memory_dir()
    lock_file = get_project_lock_file()
    lock_fd = os.open(str(lock_file), os.O_CREAT | os.O_RDWR)
    lock_type = fcntl.LOCK_SH if shared else fcntl.LOCK_EX
    fcntl.flock(lock_fd, lock_type)
    return lock_fd


def _release_state_lock(lock_fd: int):
    """Release state file lock."""
    fcntl.flock(lock_fd, fcntl.LOCK_UN)
    os.close(lock_fd)


def load_state() -> "SessionState":
    """Load session state from file with in-memory caching (project-aware)."""
    # Import here to avoid circular dependency
    from _session_state_class import SessionState
    from _session_context import _discover_ops_scripts
    from _session_thresholds import _apply_mean_reversion_on_load
    import _session_constants as const

    _ensure_memory_dir()

    # Get project-specific state file
    state_file = get_project_state_file()

    # Check cache validity (must match both file AND project)
    if const._STATE_CACHE is not None:
        try:
            current_mtime = state_file.stat().st_mtime if state_file.exists() else 0
            if current_mtime == const._STATE_CACHE_MTIME:
                return const._STATE_CACHE
        except OSError:
            pass

    # Cache miss or stale - load from disk
    lock_fd = _acquire_state_lock(shared=True)
    try:
        if state_file.exists():
            try:
                current_mtime = state_file.stat().st_mtime
                with open(state_file) as f:
                    data = json.load(f)
                    const._STATE_CACHE = _apply_mean_reversion_on_load(
                        SessionState(**data)
                    )
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
        if state_file.exists():
            try:
                current_mtime = state_file.stat().st_mtime
                with open(state_file) as f:
                    data = json.load(f)
                    const._STATE_CACHE = _apply_mean_reversion_on_load(
                        SessionState(**data)
                    )
                    const._STATE_CACHE_MTIME = current_mtime
                    return const._STATE_CACHE
            except (json.JSONDecodeError, TypeError, KeyError, OSError):
                pass

        # Initialize new state for this project
        state = SessionState(
            session_id=os.environ.get("CLAUDE_SESSION_ID", "")[:16]
            or f"ses_{int(time.time())}",
            started_at=time.time(),
            ops_scripts=_discover_ops_scripts(),
        )
        _save_state_unlocked(state)
        const._STATE_CACHE = state
        const._STATE_CACHE_MTIME = (
            state_file.stat().st_mtime if state_file.exists() else 0
        )
        return state
    finally:
        _release_state_lock(lock_fd)


def _save_state_unlocked(state: "SessionState"):
    """Save state without acquiring lock (caller must hold lock). Project-aware."""
    # Get project-specific state file
    state_file = get_project_state_file()

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

    # Atomic write to project-specific location
    try:
        fd, tmp_path = tempfile.mkstemp(dir=state_file.parent, suffix=".json")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(asdict(state), f, indent=2, default=str)
            os.replace(tmp_path, state_file)
        except Exception:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            raise
    except (IOError, OSError):
        with open(state_file, "w") as f:
            json.dump(asdict(state), f, indent=2, default=str)


def save_state(state: "SessionState"):
    """Save session state to file with locking (project-aware)."""
    import _session_constants as const

    _ensure_memory_dir()
    state_file = get_project_state_file()
    lock_fd = _acquire_state_lock()
    try:
        _save_state_unlocked(state)
        const._STATE_CACHE = state
        const._STATE_CACHE_MTIME = (
            state_file.stat().st_mtime if state_file.exists() else 0
        )
    finally:
        _release_state_lock(lock_fd)


def reset_state():
    """Reset state for new session (project-aware)."""
    import _session_constants as const

    const._STATE_CACHE = None
    const._STATE_CACHE_MTIME = 0.0

    state_file = get_project_state_file()
    if state_file.exists():
        state_file.unlink()
    return load_state()


def update_state(modifier_func):
    """Atomically load, modify, and save state (project-aware)."""
    from _session_state_class import SessionState
    from _session_context import _discover_ops_scripts
    import _session_constants as const

    _ensure_memory_dir()
    state_file = get_project_state_file()
    lock_fd = _acquire_state_lock()
    try:
        if state_file.exists():
            try:
                with open(state_file) as f:
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
        const._STATE_CACHE_MTIME = (
            state_file.stat().st_mtime if state_file.exists() else 0
        )

        return state
    finally:
        _release_state_lock(lock_fd)
