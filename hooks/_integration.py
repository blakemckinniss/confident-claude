"""
Integration Synergy helpers for hooks.

Provides unified access to:
- Project context detection (project_context.py)
- Serena availability
- Claude-mem API status
- Beads project isolation
- Agent lifecycle tracking

Used by UserPromptSubmit hooks to inject integration context.
"""

import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from _logging import log_debug

if TYPE_CHECKING:
    from session_state import SessionState

# Add lib to path for imports
LIB_DIR = Path(__file__).parent.parent / "lib"
if str(LIB_DIR) not in sys.path:
    sys.path.insert(0, str(LIB_DIR))

# Cache for expensive checks (reset each hook invocation)
_INTEGRATION_CACHE: dict = {}


def get_project_root() -> Path | None:
    """Get project root using project_context detection."""
    if "project_root" in _INTEGRATION_CACHE:
        return _INTEGRATION_CACHE["project_root"]

    try:
        from project_context import find_project_root

        root = find_project_root()
        _INTEGRATION_CACHE["project_root"] = root
        return root
    except Exception as e:
        log_debug("_integration", f"Project detection failed: {e}")
        _INTEGRATION_CACHE["project_root"] = None
        return None


def get_project_name() -> str | None:
    """Get human-readable project name."""
    if "project_name" in _INTEGRATION_CACHE:
        return _INTEGRATION_CACHE["project_name"]

    try:
        from project_context import get_project_name as _get_name

        name = _get_name()
        _INTEGRATION_CACHE["project_name"] = name
        return name
    except Exception as e:
        log_debug("_integration", f"Project name failed: {e}")
        _INTEGRATION_CACHE["project_name"] = None
        return None


def is_serena_available() -> bool:
    """Check if .serena/ exists in project or ancestors."""
    if "serena_available" in _INTEGRATION_CACHE:
        return _INTEGRATION_CACHE["serena_available"]

    cwd = Path.cwd()
    for parent in [cwd, *cwd.parents]:
        if (parent / ".serena").is_dir():
            _INTEGRATION_CACHE["serena_available"] = True
            _INTEGRATION_CACHE["serena_root"] = parent
            return True
        if parent == Path.home():
            break

    _INTEGRATION_CACHE["serena_available"] = False
    return False


def get_serena_root() -> Path | None:
    """Get the root directory where .serena/ was found."""
    if not is_serena_available():
        return None
    return _INTEGRATION_CACHE.get("serena_root")


def is_serena_activated() -> bool:
    """Check if Serena has been activated this session (from session state)."""
    if "serena_activated" in _INTEGRATION_CACHE:
        return _INTEGRATION_CACHE["serena_activated"]

    try:
        from session_state import load_state

        state = load_state()
        activated = getattr(state, "serena_activated", False)
        _INTEGRATION_CACHE["serena_activated"] = activated
        return activated
    except Exception:
        return False


def mark_serena_activated(project: str) -> None:
    """Mark Serena as activated (called from post_tool_use)."""
    try:
        from session_state import load_state, save_state

        state = load_state()
        state.serena_activated = True
        state.serena_project = project
        save_state(state)
        _INTEGRATION_CACHE["serena_activated"] = True
    except Exception as e:
        log_debug("_integration", f"Failed to mark Serena activated: {e}")


def is_claudemem_available() -> bool:
    """Check if claude-mem API is reachable."""
    if "claudemem_available" in _INTEGRATION_CACHE:
        return _INTEGRATION_CACHE["claudemem_available"]

    try:
        import urllib.request

        req = urllib.request.Request(
            "http://127.0.0.1:37777/health",
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=1) as resp:
            _INTEGRATION_CACHE["claudemem_available"] = resp.status == 200
            return _INTEGRATION_CACHE["claudemem_available"]
    except Exception:
        _INTEGRATION_CACHE["claudemem_available"] = False
        return False


def has_project_beads() -> bool:
    """Check if project has .beads/ directory."""
    if "has_beads" in _INTEGRATION_CACHE:
        return _INTEGRATION_CACHE["has_beads"]

    root = get_project_root()
    if root:
        has = (root / ".beads").is_dir()
        _INTEGRATION_CACHE["has_beads"] = has
        return has

    _INTEGRATION_CACHE["has_beads"] = False
    return False


def get_integration_status() -> dict:
    """Get full integration status for context injection."""
    return {
        "project_root": get_project_root(),
        "project_name": get_project_name(),
        "serena_available": is_serena_available(),
        "serena_root": get_serena_root(),
        "serena_activated": is_serena_activated(),
        "claudemem_available": is_claudemem_available(),
        "has_beads": has_project_beads(),
    }


def format_integration_hints(state: "SessionState") -> str:
    """Format integration hints for prompt injection."""
    parts = []
    status = get_integration_status()

    # Serena hint - different message based on activation status
    if status["serena_available"]:
        serena_root = status["serena_root"]
        project = serena_root.name if serena_root else "project"
        if status["serena_activated"]:
            parts.append(f"🔮 **SERENA ACTIVE**: Project `{project}` ready")
        else:
            parts.append(
                f"🔮 **SERENA AVAILABLE**: `.serena/` detected — "
                f'activate with `mcp__serena__activate_project("{project}")`'
            )

    # Project beads hint
    if status["has_beads"]:
        project_name = status["project_name"] or "project"
        parts.append(
            f"📋 **BEADS**: Project `{project_name}` has isolated task tracking"
        )
    elif status["project_root"]:
        # Project exists but no beads - suggest setup
        parts.append("💡 **TIP**: Run `/new-project` to set up full integration")

    # Claude-mem status (only if unavailable - don't spam when working)
    if not status["claudemem_available"]:
        parts.append("⚠️ **CLAUDE-MEM**: API not reachable (observations not persisted)")

    return "\n".join(parts) if parts else ""


def get_active_agent_assignments() -> list:
    """Get active agent assignments for current project."""
    try:
        from agent_registry import get_active_assignments

        root = get_project_root()
        return get_active_assignments(root)
    except Exception as e:
        log_debug("_integration", f"Agent assignments failed: {e}")
        return []


def get_stale_assignments(timeout_minutes: int = 30) -> list:
    """Get stale agent assignments (potential orphans)."""
    try:
        from agent_registry import get_stale_assignments

        root = get_project_root()
        return get_stale_assignments(timeout_minutes, root)
    except Exception as e:
        log_debug("_integration", f"Stale check failed: {e}")
        return []


def fire_observation(tool_name: str, tool_input: dict, tool_response: str) -> bool:
    """Fire observation to claude-mem API (non-blocking)."""
    if not is_claudemem_available():
        return False

    try:
        import json
        import urllib.request

        session_id = os.environ.get("CLAUDE_SESSION_ID")
        if not session_id:
            # Try to get from state file
            state_file = Path.home() / ".claude" / "tmp" / "session_state_v3.json"
            if state_file.exists():
                try:
                    data = json.loads(state_file.read_text())
                    session_id = data.get("session_id")
                except Exception:
                    pass

        if not session_id:
            return False

        payload = {
            "claudeSessionId": session_id,
            "tool_name": tool_name,
            "tool_input": tool_input,
            "tool_response": tool_response[:5000],  # Truncate large responses
            "cwd": str(Path.cwd()),
        }

        req = urllib.request.Request(
            "http://127.0.0.1:37777/api/sessions/observations",
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
        )
        req.add_header("Content-Type", "application/json")

        with urllib.request.urlopen(req, timeout=2) as resp:
            return resp.status == 200
    except Exception as e:
        log_debug("_integration", f"Observation failed: {e}")
        return False


def suggest_integration_setup() -> str | None:
    """Suggest integration setup if not configured."""
    status = get_integration_status()

    # If in a project without full integration, suggest setup
    if status["project_root"] and not status["has_beads"]:
        return (
            "💡 **INTEGRATION**: This project lacks `.beads/`. "
            "Run `/new-project` or manually create `.beads/` for task tracking."
        )

    return None


def clear_cache() -> None:
    """Clear integration cache (call at start of new hook invocation)."""
    global _INTEGRATION_CACHE
    _INTEGRATION_CACHE = {}
