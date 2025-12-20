#!/usr/bin/env python3
"""
Serena Integration Gates.

Gates that ensure Serena is activated before code navigation tools are used.
When .serena/ exists, these gates enforce semantic tooling over raw text search.

Hooks:
  - check_serena_activation_gate (priority 6): Block Serena MCP until activated
  - check_code_tools_require_serena (priority 6): Block Read/Grep/Glob on code
"""

from pathlib import Path

from ._common import register_hook, HookResult, SessionState


def _detect_serena_project() -> tuple[Path | None, str]:
    """Detect .serena/ directory and extract project name.

    Returns:
        (serena_dir, project_name) - serena_dir is None if not found,
        project_name defaults to parent folder name if not in project.yml
    """
    cwd = Path.cwd()
    for parent in [cwd, *cwd.parents]:
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

    # Check if Serena was activated this session
    if getattr(state, "serena_activated", False):
        return HookResult.approve()

    # Block with helpful message
    _, serena_project = _detect_serena_project()

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
    """
    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})

    # Check if .serena/ exists
    serena_dir, serena_project = _detect_serena_project()

    # No .serena/ found - allow
    if not serena_dir:
        return HookResult.approve()

    # Serena already activated - allow
    if getattr(state, "serena_activated", False):
        return HookResult.approve()

    # Get the target path
    target_path = ""
    if tool_name == "Read":
        target_path = tool_input.get("file_path", "")
    elif tool_name == "Grep":
        target_path = tool_input.get("path", "")
    elif tool_name == "Glob":
        target_path = tool_input.get("path", "")
        pattern = tool_input.get("pattern", "")
        # Check if pattern targets code files
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
