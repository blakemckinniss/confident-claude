"""
Caching utilities for hook runners.

Performance: Reduces repeated file I/O and subprocess calls.

Features:
- LRU cache with TTL for file reads
- Git command cache with configurable TTL
- JSON parse cache with mtime invalidation
"""

import json
import subprocess
import time
from pathlib import Path
from typing import Any, Optional


# =============================================================================
# TTL CACHE DECORATOR
# =============================================================================


class TTLCache:
    """Simple TTL cache for expensive operations."""

    def __init__(self, ttl_seconds: float = 5.0):
        self.ttl = ttl_seconds
        self._cache: dict[str, tuple[float, Any]] = {}

    def get(self, key: str) -> Optional[Any]:
        """Get cached value if not expired."""
        if key in self._cache:
            timestamp, value = self._cache[key]
            if time.time() - timestamp < self.ttl:
                return value
            del self._cache[key]
        return None

    def set(self, key: str, value: Any) -> None:
        """Set cached value with timestamp."""
        self._cache[key] = (time.time(), value)

    def invalidate(self, key: str) -> None:
        """Remove key from cache."""
        self._cache.pop(key, None)

    def clear(self) -> None:
        """Clear entire cache."""
        self._cache.clear()


# =============================================================================
# FILE CACHE WITH MTIME INVALIDATION
# =============================================================================


class FileCache:
    """Cache file contents with mtime-based invalidation."""

    def __init__(self, max_size: int = 50):
        self.max_size = max_size
        self._cache: dict[str, tuple[float, str]] = {}  # path -> (mtime, content)
        self._access_order: list[str] = []  # LRU tracking

    def read(self, path: str, encoding: str = "utf-8") -> Optional[str]:
        """Read file with caching, returns None if file doesn't exist."""
        try:
            p = Path(path)
            if not p.exists():
                return None

            current_mtime = p.stat().st_mtime

            # Check cache
            if path in self._cache:
                cached_mtime, content = self._cache[path]
                if cached_mtime == current_mtime:
                    # Update access order
                    if path in self._access_order:
                        self._access_order.remove(path)
                    self._access_order.append(path)
                    return content

            # Cache miss or stale - read file
            content = p.read_text(encoding=encoding)

            # Evict LRU if at capacity
            while len(self._cache) >= self.max_size:
                if self._access_order:
                    oldest = self._access_order.pop(0)
                    self._cache.pop(oldest, None)
                else:
                    break

            # Store in cache
            self._cache[path] = (current_mtime, content)
            self._access_order.append(path)

            return content
        except (OSError, IOError, UnicodeDecodeError):
            return None

    def read_json(self, path: str) -> Optional[dict]:
        """Read and parse JSON file with caching."""
        content = self.read(path)
        if content is None:
            return None
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            return None

    def invalidate(self, path: str) -> None:
        """Invalidate cache for a specific path."""
        self._cache.pop(path, None)
        if path in self._access_order:
            self._access_order.remove(path)

    def clear(self) -> None:
        """Clear entire cache."""
        self._cache.clear()
        self._access_order.clear()


# =============================================================================
# GIT CACHE
# =============================================================================


class GitCache:
    """Cache git command results with TTL."""

    def __init__(self, ttl_seconds: float = 5.0):
        self.ttl = ttl_seconds
        self._cache: dict[str, tuple[float, str]] = {}

    def _run_git(self, *args: str, cwd: Optional[str] = None) -> Optional[str]:
        """Run git command and return output or None on error."""
        try:
            result = subprocess.run(
                ["git", *args],
                capture_output=True,
                text=True,
                timeout=5,
                cwd=cwd,
            )
            if result.returncode == 0:
                return result.stdout.strip()
            return None
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            return None

    def current_branch(self, cwd: Optional[str] = None) -> Optional[str]:
        """Get current git branch (cached)."""
        cache_key = f"branch:{cwd or '.'}"

        # Check cache
        if cache_key in self._cache:
            timestamp, value = self._cache[cache_key]
            if time.time() - timestamp < self.ttl:
                return value

        # Cache miss - run command
        result = self._run_git("branch", "--show-current", cwd=cwd)
        if result is not None:
            self._cache[cache_key] = (time.time(), result)
        return result

    def status_porcelain(self, cwd: Optional[str] = None) -> Optional[str]:
        """Get git status in porcelain format (cached)."""
        cache_key = f"status:{cwd or '.'}"

        # Check cache
        if cache_key in self._cache:
            timestamp, value = self._cache[cache_key]
            if time.time() - timestamp < self.ttl:
                return value

        # Cache miss - run command
        result = self._run_git("status", "--porcelain", cwd=cwd)
        if result is not None:
            self._cache[cache_key] = (time.time(), result)
        return result

    def has_changes(self, cwd: Optional[str] = None) -> bool:
        """Check if repo has uncommitted changes (cached)."""
        status = self.status_porcelain(cwd)
        return bool(status)

    def invalidate(self) -> None:
        """Invalidate all git cache."""
        self._cache.clear()


# =============================================================================
# SINGLETON INSTANCES
# =============================================================================

# Global cache instances for use across hooks
file_cache = FileCache(max_size=50)
git_cache = GitCache(ttl_seconds=5.0)
ttl_cache = TTLCache(ttl_seconds=10.0)


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================


def cached_file_read(path: str) -> Optional[str]:
    """Read file with caching (convenience wrapper)."""
    return file_cache.read(path)


def cached_json_read(path: str) -> Optional[dict]:
    """Read JSON file with caching (convenience wrapper)."""
    return file_cache.read_json(path)


def cached_git_branch(cwd: Optional[str] = None) -> Optional[str]:
    """Get current git branch (convenience wrapper)."""
    return git_cache.current_branch(cwd)


def cached_git_status(cwd: Optional[str] = None) -> Optional[str]:
    """Get git status (convenience wrapper)."""
    return git_cache.status_porcelain(cwd)
