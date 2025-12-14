#!/usr/bin/env python3
"""
Session Context - Ops discovery, context generation, and session summary.
"""

import time
from pathlib import Path
from typing import TYPE_CHECKING

from _session_constants import Domain, OPS_DIR, _OPS_SCRIPTS_CACHE, _OPS_SCRIPTS_MTIME

if TYPE_CHECKING:
    from _session_state_class import SessionState

# Module-level cache
_ops_scripts_cache: list | None = None
_ops_scripts_mtime: float = 0.0


def _discover_ops_scripts() -> list:
    """Discover available ops scripts (cached)."""
    global _ops_scripts_cache, _ops_scripts_mtime

    if not OPS_DIR.exists():
        return []

    try:
        current_mtime = OPS_DIR.stat().st_mtime
        if _ops_scripts_cache is not None and current_mtime == _ops_scripts_mtime:
            return _ops_scripts_cache
    except OSError:
        pass

    scripts = [f.stem for f in OPS_DIR.glob("*.py")]
    _ops_scripts_cache = scripts
    _ops_scripts_mtime = current_mtime if "current_mtime" in dir() else 0.0
    return scripts


def generate_context(state: "SessionState") -> str:
    """Generate context string for injection."""
    parts = []

    if state.domain != Domain.UNKNOWN and state.domain_confidence > 0.3:
        domain_emoji = {
            Domain.INFRASTRUCTURE: "☁️",
            Domain.DEVELOPMENT: "💻",
            Domain.EXPLORATION: "🔍",
            Domain.DATA: "📊",
        }.get(state.domain, "📁")
        parts.append(f"{domain_emoji} Domain: {state.domain} ({state.domain_confidence:.0%})")

    if state.files_edited:
        recent_edits = state.files_edited[-3:]
        names = [Path(f).name for f in recent_edits]
        parts.append(f"📝 Edited: {', '.join(names)}")

    if state.errors_unresolved:
        error = state.errors_unresolved[-1]
        parts.append(f"⚠️ Unresolved: {error.get('type', 'error')[:40]}")

    if state.last_deploy:
        age = time.time() - state.last_deploy.get("timestamp", 0)
        if age < 600:
            status = "✅" if state.last_deploy.get("success") else "❌"
            parts.append(f"{status} Deploy: {int(age)}s ago")

    if state.tests_run:
        parts.append("✅ Tests: run")
    elif any(c >= 2 for c in state.edit_counts.values()):
        parts.append("⚠️ Tests: not run")

    return " | ".join(parts) if parts else ""


def get_session_summary(state: "SessionState") -> dict:
    """Get a summary of the session for debugging."""
    return {
        "session_id": state.session_id,
        "domain": state.domain,
        "domain_confidence": state.domain_confidence,
        "files_read": len(state.files_read),
        "files_edited": len(state.files_edited),
        "libraries_used": state.libraries_used,
        "libraries_researched": state.libraries_researched,
        "tests_run": state.tests_run,
        "errors_unresolved": len(state.errors_unresolved),
        "edit_counts": state.edit_counts,
    }
