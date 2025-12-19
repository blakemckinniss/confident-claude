"""
Cooldown management utilities for hook runners.

Replaces 8+ duplicate cooldown implementations with a single, file-locked manager.

v2.0: Project-aware cooldown isolation
- Each project gets isolated cooldown state via cwd-hash
- Prevents cross-project cooldown pollution when running multiple shells
- Falls back to legacy global paths during migration
"""

import fcntl
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Optional

from _config import get_cooldown

# =============================================================================
# COOLDOWN MANAGER
# =============================================================================

MEMORY_DIR = Path.home() / ".claude" / "memory"
STATE_DIR = MEMORY_DIR / "state"  # Legacy global (for migration fallback)


def _get_project_id() -> str:
    """Get current project ID for state isolation.

    Uses same isolation strategy as session_state and mastermind:
    - Project ID from project_detector if available
    - cwd-hash fallback for ephemeral contexts (never global)
    """
    try:
        # Add lib to path for project_detector import
        import sys

        lib_dir = Path(__file__).parent.parent / "lib"
        if str(lib_dir) not in sys.path:
            sys.path.insert(0, str(lib_dir))

        from project_detector import detect_project

        ctx = detect_project()

        if ctx and ctx.project_type != "ephemeral":
            return ctx.project_id

        # Ephemeral: use cwd-hash (never global "ephemeral")
        cwd = os.path.realpath(os.getcwd())
        return f"cwd_{hashlib.sha256(cwd.encode()).hexdigest()[:12]}"

    except Exception:
        # Fallback: always cwd-hash, never global
        cwd = os.path.realpath(os.getcwd())
        return f"cwd_{hashlib.sha256(cwd.encode()).hexdigest()[:12]}"


def _get_project_state_dir() -> Path:
    """Get project-specific state directory.

    Returns: ~/.claude/memory/state/projects/{project_id}/
    """
    project_id = _get_project_id()
    project_dir = STATE_DIR / "projects" / project_id
    project_dir.mkdir(parents=True, exist_ok=True)
    return project_dir


def _resolve_state_path(filename: str, project_isolated: bool = True) -> Path:
    """Resolve state file path with project isolation and backward compatibility.

    Args:
        filename: State file name (e.g., "assumption_cooldown.json")
        project_isolated: If True, use project-specific path. If False, use global.

    Resolution order:
    1. New project-isolated path: state/projects/{project_id}/{filename}
    2. Legacy global path: state/{filename} (migration fallback)
    3. Very old path: memory/{filename} (ancient migration)
    """
    if project_isolated:
        # New isolated path
        project_dir = _get_project_state_dir()
        new_path = project_dir / filename
        if new_path.exists():
            return new_path

        # Check legacy global - if exists, migrate on next write
        legacy_path = STATE_DIR / filename
        if legacy_path.exists():
            # Return new path for writes (migration happens naturally)
            return new_path

    # Global path (for intentionally shared state)
    global_path = STATE_DIR / filename
    if global_path.exists():
        return global_path

    # Very old legacy path
    legacy_path = MEMORY_DIR / filename
    if legacy_path.exists():
        return legacy_path

    # Default: new project-isolated or global based on flag
    if project_isolated:
        return _get_project_state_dir() / filename
    return STATE_DIR / filename


class CooldownManager:
    """Manage cooldowns with file-based persistence and locking."""

    def __init__(self, name: str, ttl: Optional[int] = None):
        """
        Initialize cooldown manager.

        Args:
            name: Cooldown identifier (e.g., "assumption", "mutation")
            ttl: Time-to-live in seconds. If None, uses centralized config.
        """
        self.name = name
        self.ttl = ttl if ttl is not None else get_cooldown(name)
        self.file = _resolve_state_path(f"{name}_cooldown.json")

    def is_active(self) -> bool:
        """Check if cooldown is currently active (should skip)."""
        try:
            if not self.file.exists():
                return False
            data = json.loads(self.file.read_text())
            last = data.get("last", 0)
            return time.time() - last < self.ttl
        except (json.JSONDecodeError, OSError, IOError):
            return False

    def reset(self) -> None:
        """Reset cooldown (mark as triggered now) with file locking."""
        try:
            self.file.parent.mkdir(parents=True, exist_ok=True)

            # Use file locking to prevent race conditions
            with open(self.file, "w") as f:
                try:
                    fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    json.dump({"last": time.time()}, f)
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
                except BlockingIOError:
                    # Another process has the lock, write anyway
                    json.dump({"last": time.time()}, f)
        except (OSError, IOError):
            pass

    def clear(self) -> None:
        """Clear cooldown (allow immediate trigger)."""
        try:
            if self.file.exists():
                self.file.unlink()
        except OSError:
            pass

    def time_remaining(self) -> float:
        """Get seconds remaining in cooldown, or 0 if not active."""
        try:
            if not self.file.exists():
                return 0
            data = json.loads(self.file.read_text())
            last = data.get("last", 0)
            remaining = self.ttl - (time.time() - last)
            return max(0, remaining)
        except (json.JSONDecodeError, OSError, IOError):
            return 0

    def check_and_reset(self) -> bool:
        """
        Check if cooldown allows action and reset if so.

        Returns:
            True if action is allowed (cooldown was inactive), False otherwise.
        """
        if self.is_active():
            return False
        self.reset()
        return True


# =============================================================================
# SINGLETON INSTANCES FOR COMMON COOLDOWNS
# =============================================================================

assumption_cooldown = CooldownManager("assumption")
mutation_cooldown = CooldownManager("mutation")
toolchain_cooldown = CooldownManager("toolchain")
tool_awareness_cooldown = CooldownManager("tool_awareness")
large_file_cooldown = CooldownManager("large_file")
intuition_cooldown = CooldownManager("intuition")


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================


def is_on_cooldown(name: str) -> bool:
    """Check if a named cooldown is active."""
    return CooldownManager(name).is_active()


def reset_cooldown(name: str) -> None:
    """Reset a named cooldown."""
    CooldownManager(name).reset()


def check_and_reset_cooldown(name: str, cooldown_seconds: int | None = None) -> bool:
    """Check if cooldown allows action and reset if so."""
    return CooldownManager(name, ttl=cooldown_seconds).check_and_reset()


# =============================================================================
# KEYED COOLDOWN MANAGER (for per-file, per-extension cooldowns)
# =============================================================================


class KeyedCooldownManager:
    """Manage cooldowns with multiple keys (e.g., per-file, per-extension).

    Stores all keys in a single JSON file with automatic LRU eviction.
    """

    def __init__(self, name: str, ttl: Optional[int] = None, max_keys: int = 50):
        """
        Initialize keyed cooldown manager.

        Args:
            name: Cooldown identifier (e.g., "toolchain", "large_file")
            ttl: Time-to-live in seconds. If None, uses centralized config.
            max_keys: Maximum keys to track (LRU eviction when exceeded).
        """
        self.name = name
        self.ttl = ttl if ttl is not None else get_cooldown(name)
        self.max_keys = max_keys
        self.file = _resolve_state_path(f"{name}_keyed_cooldown.json")
        self._cache: Optional[dict] = None
        self._cache_mtime: float = 0

    def _load(self) -> dict:
        """Load cooldowns from file with caching."""
        try:
            if not self.file.exists():
                return {}
            mtime = self.file.stat().st_mtime
            if self._cache is not None and mtime == self._cache_mtime:
                return self._cache
            self._cache = json.loads(self.file.read_text())
            self._cache_mtime = mtime
            return self._cache
        except (json.JSONDecodeError, OSError, IOError):
            return {}

    def _save(self, data: dict) -> None:
        """Save cooldowns to file with locking and LRU eviction."""
        try:
            # LRU eviction if over capacity
            if len(data) > self.max_keys:
                sorted_items = sorted(data.items(), key=lambda x: x[1], reverse=True)
                data = dict(sorted_items[: self.max_keys])

            self.file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.file, "w") as f:
                try:
                    fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    json.dump(data, f)
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
                except BlockingIOError:
                    json.dump(data, f)
            self._cache = data
            self._cache_mtime = self.file.stat().st_mtime
        except (OSError, IOError):
            pass

    def is_active(self, key: str) -> bool:
        """Check if cooldown is active for a specific key."""
        data = self._load()
        last = data.get(key, 0)
        return time.time() - last < self.ttl

    def reset(self, key: str) -> None:
        """Reset cooldown for a specific key."""
        data = self._load()
        data[key] = time.time()
        self._save(data)

    def check_and_reset(self, key: str) -> bool:
        """Check if cooldown allows action and reset if so.

        Returns:
            True if action is allowed (cooldown was inactive), False otherwise.
        """
        if self.is_active(key):
            return False
        self.reset(key)
        return True

    def clear(self, key: Optional[str] = None) -> None:
        """Clear cooldown for a key, or all keys if key is None."""
        if key is None:
            try:
                if self.file.exists():
                    self.file.unlink()
                self._cache = None
            except OSError:
                pass
        else:
            data = self._load()
            data.pop(key, None)
            self._save(data)


# =============================================================================
# SINGLETON INSTANCES FOR KEYED COOLDOWNS
# =============================================================================

toolchain_keyed = KeyedCooldownManager("toolchain", ttl=300, max_keys=20)
large_file_keyed = KeyedCooldownManager("large_file", ttl=600, max_keys=20)
tool_awareness_keyed = KeyedCooldownManager("tool_awareness", ttl=300, max_keys=10)
crawl4ai_promo_keyed = KeyedCooldownManager("crawl4ai_promo", ttl=600, max_keys=20)
beads_sync_cooldown = CooldownManager("beads_sync", ttl=300)
