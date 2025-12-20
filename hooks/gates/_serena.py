#!/usr/bin/env python3
"""
Serena Integration Gates.

Gates that ensure Serena is activated before code navigation tools are used.
When .serena/ exists, these gates enforce semantic tooling over raw text search.

Hooks:
  - check_serena_activation_gate (priority 6): Block Serena MCP until activated
  - check_code_tools_require_serena (priority 6): Block Read/Grep/Glob on code

Architecture Note (v4.22):
  Hooks run from ~/.claude CWD, not the project directory. Project detection
  must use file paths from tool_input, not os.getcwd(). State loading must
  use project-specific paths derived from the file being accessed.
"""

from pathlib import Path
from typing import Optional

from ._common import register_hook, HookResult, SessionState


def _detect_serena_project(from_path: Optional[str] = None) -> tuple[Path | None, str]:
    """Detect .serena/ directory and extract project name.

    Args:
        from_path: Optional file path to detect from. If None, uses CWD.
                   IMPORTANT: Hooks should pass tool_input file paths here,
                   since hooks run from ~/.claude, not the project directory.

    Returns:
        (serena_dir, project_name) - serena_dir is None if not found,
        project_name defaults to parent folder name if not in project.yml
    """
    if from_path:
        start = Path(from_path).resolve()
        # If it's a file, start from its parent directory
        if start.is_file() or not start.exists():
            start = start.parent
    else:
        start = Path.cwd()

    for parent in [start, *start.parents]:
        serena_dir = parent / ".serena"
        if serena_dir.is_dir():
            project_name = ""
            project_yml = serena_dir / "project.yml"
            if project_yml.exists():
                try:
                    content = project_yml.read_text()
                    for line in content.splitlines():
                        if line.startswith("project_name:"):
                            project_name = line.split(":", 1)[1].strip().strip("\"'")
                            break
                except Exception:
                    pass
            # Fall back to folder name if no project_name found
            if not project_name:
                project_name = parent.name
            return serena_dir, project_name
        if parent == Path.home():
            break
    return None, ""


def _get_session_id() -> str:
    """Get current session ID for isolation.

    Multiple shells on same project need separate activation tracking.
    """
    import os

    # Priority: explicit session ID > SSE port > fallback
    session_id = os.environ.get("CLAUDE_SESSION_ID", "")[:16]
    if session_id:
        return session_id

    sse_port = os.environ.get("CLAUDE_CODE_SSE_PORT", "")
    if sse_port:
        return f"sse_{sse_port}"

    return "default"


def _is_serena_activated_for_project(serena_dir: Path) -> bool:
    """Check if Serena is activated for the project in THIS session.

    Uses a global activation registry keyed by project_root:session_id
    since per-project state files are loaded based on CWD (which is
    ~/.claude for hooks), not the target project.

    The registry is at ~/.claude/memory/.serena_activations.json
    """
    import json

    registry_path = Path.home() / ".claude" / "memory" / ".serena_activations.json"
    if not registry_path.exists():
        return False

    try:
        with open(registry_path) as f:
            activations = json.load(f)
        # Key is project_root:session_id for full isolation
        project_root = str(serena_dir.parent.resolve())
        session_id = _get_session_id()
        key = f"{project_root}:{session_id}"
        return activations.get(key, False)
    except (json.JSONDecodeError, OSError):
        return False


def _register_serena_activation(project_name: str, serena_dir: Path) -> None:
    """Register that Serena was activated for a project in THIS session.

    Called by post-tool-use hook after activate_project succeeds.
    """
    import json

    registry_path = Path.home() / ".claude" / "memory" / ".serena_activations.json"
    registry_path.parent.mkdir(parents=True, exist_ok=True)

    activations = {}
    if registry_path.exists():
        try:
            with open(registry_path) as f:
                activations = json.load(f)
        except (json.JSONDecodeError, OSError):
            pass

    # Key is project_root:session_id for full isolation
    project_root = str(serena_dir.parent.resolve())
    session_id = _get_session_id()
    key = f"{project_root}:{session_id}"
    activations[key] = True

    try:
        with open(registry_path, "w") as f:
            json.dump(activations, f, indent=2)
    except OSError:
        pass


@register_hook("serena_activation_gate", "mcp__serena__.*", priority=6)
def check_serena_activation_gate(data: dict, state: SessionState) -> HookResult:
    """Block Serena tools until project is activated.

    Allows activate_project through, blocks all other Serena MCP tools
    until activation has occurred.
    """
    tool_name = data.get("tool_name", "")

    # Always allow activation
    if "activate_project" in tool_name:
        return HookResult.approve()

    # Check global activation registry (handles CWD != project dir issue)
    serena_dir, serena_project = _detect_serena_project()
    if serena_dir and _is_serena_activated_for_project(serena_dir):
        return HookResult.approve()

    # Fallback: also check per-project state (backward compat)
    if getattr(state, "serena_activated", False):
        return HookResult.approve()

    return HookResult.deny(
        f"🔮 **SERENA NOT ACTIVATED**: Call `mcp__serena__activate_project"
        f'("{serena_project or "project"}")` first.\n'
        f"Tool `{tool_name}` requires an active Serena session."
    )


@register_hook("code_tools_require_serena", "Read|Grep|Glob", priority=6)
def check_code_tools_require_serena(data: dict, state: SessionState) -> HookResult:
    """Block Read/Grep/Glob on code files when .serena/ exists but not activated.

    Forces Serena activation before any code navigation, ensuring semantic
    tools are used instead of raw text search.

    IMPORTANT: Detects project from file path in tool_input, not CWD.
    This is critical because hooks run from ~/.claude, not the project dir.
    """
    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})

    # Get target path from tool input (critical for correct project detection)
    target_path = ""
    if tool_name == "Read":
        target_path = tool_input.get("file_path", "")
    elif tool_name == "Grep":
        target_path = tool_input.get("path", "")
    elif tool_name == "Glob":
        target_path = tool_input.get("path", "")

    # Detect project from the file path, not CWD
    serena_dir, serena_project = _detect_serena_project(from_path=target_path)

    # No .serena/ found for this file's project - allow
    if not serena_dir:
        return HookResult.approve()

    # Check global activation registry (keyed by project_root:session_id)
    if _is_serena_activated_for_project(serena_dir):
        return HookResult.approve()

    # Fallback: also check per-project state (backward compat)
    if getattr(state, "serena_activated", False):
        return HookResult.approve()

    # For Glob, check if pattern targets code files
    if tool_name == "Glob":
        pattern = tool_input.get("pattern", "")
        code_patterns = (".py", ".ts", ".tsx", ".js", ".jsx", ".rs", ".go", ".java")
        if any(ext in pattern for ext in code_patterns):
            return HookResult.deny(
                f"🔮 **SERENA REQUIRED**: `.serena/` detected. Activate before code search.\n"
                f'Call `mcp__serena__activate_project("{serena_project}")` first.\n'
                f"Serena provides semantic search superior to Glob patterns."
            )

    # Check if target is a code file
    code_extensions = (".py", ".ts", ".tsx", ".js", ".jsx", ".rs", ".go", ".java")
    if target_path and target_path.endswith(code_extensions):
        return HookResult.deny(
            f"🔮 **SERENA REQUIRED**: `.serena/` detected. Activate before reading code.\n"
            f'Call `mcp__serena__activate_project("{serena_project}")` first.\n'
            f"Use `mcp__serena__get_symbols_overview` or `mcp__serena__find_symbol` instead of raw reads."
        )

    # Check if searching in code directories
    # Match: absolute (/lib/), relative (lib/), and end-of-path (/lib, lib)
    code_dirs = (
        "/src/",
        "/src",
        "src/",
        "/lib/",
        "/lib",
        "lib/",
        "/hooks/",
        "/hooks",
        "hooks/",
        "/ops/",
        "/ops",
        "ops/",
        "/components/",
        "/components",
        "components/",
        "/utils/",
        "/utils",
        "utils/",
    )
    if target_path and any(d in target_path for d in code_dirs):
        return HookResult.deny(
            f"🔮 **SERENA REQUIRED**: `.serena/` detected. Activate before code search.\n"
            f'Call `mcp__serena__activate_project("{serena_project}")` first.\n'
            f"Use `mcp__serena__search_for_pattern` for semantic code search."
        )

    return HookResult.approve()


__all__ = [
    "_detect_serena_project",
    "check_serena_activation_gate",
    "check_code_tools_require_serena",
]
