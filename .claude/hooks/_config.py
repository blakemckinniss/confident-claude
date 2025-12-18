"""
Centralized configuration for hook runners.

Loads settings from ~/.claude/config/hook_settings.json with sensible defaults.
Supports hot-reload on file change via mtime checking.
"""

import json
import time
from pathlib import Path
from typing import Any

# =============================================================================
# CONFIG PATHS
# =============================================================================

CONFIG_DIR = Path.home() / ".claude" / "config"
HOOK_SETTINGS_FILE = CONFIG_DIR / "hook_settings.json"

# =============================================================================
# DEFAULT VALUES (used when config file missing or key not found)
# =============================================================================

# =============================================================================
# TOOL NAMES (avoid magic strings scattered across codebase)
# =============================================================================

TOOL_NAMES = {
    "bash": "Bash",
    "edit": "Edit",
    "write": "Write",
    "read": "Read",
    "grep": "Grep",
    "glob": "Glob",
    "task": "Task",
    "web_fetch": "WebFetch",
    "web_search": "WebSearch",
    "notebook_edit": "NotebookEdit",
}

# =============================================================================
# MAGIC NUMBERS (centralized for easy tuning)
# =============================================================================

MAGIC_NUMBERS = {
    "default_context_window": 200000,
    "large_file_threshold": 500,
    "repetition_window_seconds": 300,
    "reads_before_warn": 5,
    "reads_before_crystallize": 8,
}

# =============================================================================
# DEFAULT VALUES (used when config file missing or key not found)
# =============================================================================

DEFAULTS = {
    "cooldowns": {
        "assumption": 120,
        "mutation": 120,
        "toolchain": 300,
        "tool_awareness": 300,
        "large_file": 600,
        "modularization": 10,
        "ops_nudge": 180,
        "ops_audit_reminder": 10800,  # 3 hours (v3.9)
    },
    "thresholds": {
        "stale_session_seconds": 3600,
        "max_method_lines": 60,
        "max_conditionals": 12,
        "large_file_lines": 500,
        "min_code_length": 50,
        "min_prompt_length": 10,
        "pipe_threshold": 3,
        "error_ttl_seconds": 300,
        "context_decay_warn_turns": 15,
        "context_decay_critical_turns": 30,
        "tech_risk_months_threshold": 6,
    },
    "limits": {
        "context_items": 8,
        "reads_before_warn": 5,
        "max_lessons_results": 3,
        "max_warnings": 3,
        "max_ops_suggestions": 3,
        "max_tool_suggestions": 5,
        "lru_cache_size": 50,
    },
    "ttl": {
        "git_cache_seconds": 5.0,
        "file_cache_seconds": 30.0,
    },
    "patterns": {
        "protected_paths": [".claude/ops/", ".claude/lib/"],
        "scratch_paths": [".claude/tmp/", ".claude/memory/"],
        "skip_extensions": [".md", ".txt", ".json", ".yaml", ".yml", ".sh", ".env"],
    },
}

# =============================================================================
# CONFIG LOADER WITH HOT-RELOAD
# =============================================================================


class HookConfig:
    """Configuration loader with mtime-based hot-reload."""

    def __init__(self):
        self._config: dict = {}
        self._mtime: float = 0
        self._last_check: float = 0
        self._check_interval: float = 5.0  # Check for changes every 5 seconds

    def _should_reload(self) -> bool:
        """Check if config file has changed since last load."""
        now = time.time()
        if now - self._last_check < self._check_interval:
            return False
        self._last_check = now

        if not HOOK_SETTINGS_FILE.exists():
            return False

        current_mtime = HOOK_SETTINGS_FILE.stat().st_mtime
        return current_mtime != self._mtime

    def _load(self) -> None:
        """Load config from file."""
        if HOOK_SETTINGS_FILE.exists():
            try:
                self._config = json.loads(HOOK_SETTINGS_FILE.read_text())
                self._mtime = HOOK_SETTINGS_FILE.stat().st_mtime
            except (json.JSONDecodeError, OSError):
                self._config = {}
        else:
            self._config = {}

    def get(self, section: str, key: str, default: Any = None) -> Any:
        """Get a config value with fallback to defaults."""
        if self._should_reload():
            self._load()

        # Try loaded config first
        if section in self._config and key in self._config[section]:
            return self._config[section][key]

        # Fall back to defaults
        if section in DEFAULTS and key in DEFAULTS[section]:
            return DEFAULTS[section][key]

        return default

    def get_section(self, section: str) -> dict:
        """Get an entire config section."""
        if self._should_reload():
            self._load()

        result = dict(DEFAULTS.get(section, {}))
        result.update(self._config.get(section, {}))
        return result

    def reload(self) -> None:
        """Force reload config from disk."""
        self._load()


# =============================================================================
# SINGLETON INSTANCE
# =============================================================================

config = HookConfig()


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================


def get_cooldown(name: str) -> int:
    """Get cooldown duration in seconds."""
    return config.get("cooldowns", name, 120)


def get_threshold(name: str) -> int:
    """Get threshold value."""
    return config.get("thresholds", name, 0)


def get_limit(name: str) -> int:
    """Get limit value."""
    return config.get("limits", name, 10)


def get_ttl(name: str) -> float:
    """Get TTL value in seconds."""
    return config.get("ttl", name, 5.0)


def get_patterns(name: str) -> list:
    """Get pattern list."""
    return config.get("patterns", name, [])


def is_protected_path(path: str) -> bool:
    """Check if path is in protected locations."""
    protected = get_patterns("protected_paths")
    return any(p in path for p in protected)


# NOTE: is_scratch_path moved to _patterns.py (single source of truth)
# Use: from _patterns import is_scratch_path


def get_tool_name(key: str) -> str:
    """Get canonical tool name (avoids magic strings)."""
    return TOOL_NAMES.get(key, key.title())


def get_magic_number(key: str, default: int = 0) -> int:
    """Get magic number constant."""
    return MAGIC_NUMBERS.get(key, default)
