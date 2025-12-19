#!/usr/bin/env python3
"""
Session Constants - Paths, cache variables, Domain class, patterns.

This module exists to break circular import dependencies.
"""

import re
from pathlib import Path
from typing import Optional

# =============================================================================
# PATHS
# =============================================================================

LIB_DIR = Path(__file__).resolve().parent  # .claude/lib
CLAUDE_DIR = LIB_DIR.parent  # .claude
MEMORY_DIR = CLAUDE_DIR / "memory"
STATE_FILE = MEMORY_DIR / "session_state_v3.json"  # Legacy global (fallback only)
OPS_DIR = LIB_DIR.parent / "ops"  # .claude/ops
OPS_USAGE_FILE = MEMORY_DIR / "tool_usage.json"
STATE_LOCK_FILE = MEMORY_DIR / "session_state.lock"  # Legacy global lock

# =============================================================================
# PROJECT-AWARE STATE PATHS (v3.13)
# =============================================================================

# Cache for current project context (avoids repeated detection)
_CURRENT_PROJECT_ID: Optional[str] = None
_CURRENT_PROJECT_ROOT: Optional[str] = None


def _compute_cwd_hash() -> str:
    """Compute stable hash from current working directory.

    Used for isolation when no project markers are found.
    """
    import hashlib
    import os

    cwd = os.path.realpath(os.getcwd())
    return hashlib.sha256(cwd.encode()).hexdigest()[:12]


def get_project_state_file() -> Path:
    """Get project-specific state file path.

    Returns per-project state file - never uses global state.
    Ephemeral contexts get cwd-hash isolation to prevent cross-project leakage.

    Layout:
      ~/.claude/memory/projects/{project_id}/session_state.json  (per-project)
      ~/.claude/memory/projects/cwd_{hash}/session_state.json    (cwd-hash fallback)
    """
    global _CURRENT_PROJECT_ID, _CURRENT_PROJECT_ROOT

    try:
        # Ensure lib directory is on path for sibling module imports
        import sys

        lib_dir_str = str(LIB_DIR)
        if lib_dir_str not in sys.path:
            sys.path.insert(0, lib_dir_str)

        from project_detector import detect_project

        ctx = detect_project()

        # Cache for performance
        _CURRENT_PROJECT_ID = ctx.project_id
        _CURRENT_PROJECT_ROOT = ctx.root_path

        # Ephemeral contexts get cwd-hash isolation (no global state!)
        if ctx.project_type == "ephemeral":
            cwd_hash = _compute_cwd_hash()
            _CURRENT_PROJECT_ID = f"cwd_{cwd_hash}"
            project_dir = MEMORY_DIR / "projects" / _CURRENT_PROJECT_ID
            project_dir.mkdir(parents=True, exist_ok=True)
            return project_dir / "session_state.json"

        # Per-project state file
        project_dir = MEMORY_DIR / "projects" / ctx.project_id
        project_dir.mkdir(parents=True, exist_ok=True)
        return project_dir / "session_state.json"

    except Exception:
        # Fallback to cwd-hash on any detection failure (no global state!)
        cwd_hash = _compute_cwd_hash()
        _CURRENT_PROJECT_ID = f"cwd_{cwd_hash}"
        project_dir = MEMORY_DIR / "projects" / _CURRENT_PROJECT_ID
        project_dir.mkdir(parents=True, exist_ok=True)
        return project_dir / "session_state.json"


def get_project_lock_file() -> Path:
    """Get project-specific lock file path."""
    state_file = get_project_state_file()
    return state_file.parent / "session_state.lock"


def get_current_project_id() -> Optional[str]:
    """Get cached current project ID (call get_project_state_file first)."""
    return _CURRENT_PROJECT_ID


def get_current_project_root() -> Optional[str]:
    """Get cached current project root path."""
    return _CURRENT_PROJECT_ROOT


# =============================================================================
# SESSION-SCOPED STATE CACHE (Performance optimization)
# =============================================================================

_STATE_CACHE = None  # Type: Optional[SessionState] - set after import
_STATE_CACHE_DIRTY: bool = False
_STATE_CACHE_MTIME: float = 0.0

# Cache for ops scripts discovery
_OPS_SCRIPTS_CACHE: list | None = None
_OPS_SCRIPTS_MTIME: float = 0.0

# =============================================================================
# DOMAIN DETECTION
# =============================================================================


class Domain:
    UNKNOWN = "unknown"
    INFRASTRUCTURE = "infrastructure"
    DEVELOPMENT = "development"
    EXPLORATION = "exploration"
    DATA = "data"


# Pre-compiled domain signal patterns
_DOMAIN_SIGNAL_PATTERNS = {
    Domain.INFRASTRUCTURE: [
        re.compile(r"gcloud\s+", re.IGNORECASE),
        re.compile(r"aws\s+", re.IGNORECASE),
        re.compile(r"docker\s+", re.IGNORECASE),
        re.compile(r"kubectl\s+", re.IGNORECASE),
        re.compile(r"terraform\s+", re.IGNORECASE),
        re.compile(r"--region", re.IGNORECASE),
        re.compile(r"--project", re.IGNORECASE),
        re.compile(r"deploy", re.IGNORECASE),
        re.compile(r"service", re.IGNORECASE),
        re.compile(r"secrets?", re.IGNORECASE),
    ],
    Domain.DEVELOPMENT: [
        re.compile(r"\.py$", re.IGNORECASE),
        re.compile(r"\.js$", re.IGNORECASE),
        re.compile(r"\.ts$", re.IGNORECASE),
        re.compile(r"\.rs$", re.IGNORECASE),
        re.compile(r"npm\s+(run|test|build)", re.IGNORECASE),
        re.compile(r"pytest", re.IGNORECASE),
        re.compile(r"cargo\s+(build|test|run)", re.IGNORECASE),
        re.compile(r"function\s+\w+", re.IGNORECASE),
        re.compile(r"class\s+\w+", re.IGNORECASE),
        re.compile(r"def\s+\w+", re.IGNORECASE),
    ],
    Domain.EXPLORATION: [
        re.compile(r"what\s+(is|does|are)", re.IGNORECASE),
        re.compile(r"how\s+(does|do|to)", re.IGNORECASE),
        re.compile(r"explain", re.IGNORECASE),
        re.compile(r"understand", re.IGNORECASE),
        re.compile(r"find.*file", re.IGNORECASE),
        re.compile(r"where\s+is", re.IGNORECASE),
        re.compile(r"show\s+me", re.IGNORECASE),
    ],
    Domain.DATA: [
        re.compile(r"\.ipynb", re.IGNORECASE),
        re.compile(r"pandas", re.IGNORECASE),
        re.compile(r"dataframe", re.IGNORECASE),
        re.compile(r"sql", re.IGNORECASE),
        re.compile(r"query", re.IGNORECASE),
        re.compile(r"\.csv", re.IGNORECASE),
        re.compile(r"\.parquet", re.IGNORECASE),
    ],
}

# =============================================================================
# LIBRARY DETECTION
# =============================================================================

RESEARCH_REQUIRED_LIBS = {
    "fastapi",
    "pydantic",
    "langchain",
    "llamaindex",
    "anthropic",
    "openai",
    "polars",
    "duckdb",
    "streamlit",
    "gradio",
    "transformers",
    "torch",
    "boto3",
    "playwright",
    "httpx",
    "aiohttp",
    "next",
    "nuxt",
    "remix",
    "astro",
    "svelte",
    "@google-cloud",
    "@aws-sdk",
    "@azure",
}

STDLIB_PATTERNS = [
    r"^(os|sys|json|re|time|datetime|pathlib|subprocess|typing|collections|itertools)$",
    r"^(math|random|string|io|functools|operator|contextlib|abc|dataclasses)$",
]
