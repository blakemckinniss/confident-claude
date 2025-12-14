"""
Cache-related PostToolUse hooks.

Handles caching of exploration results and read file contents.
Priority range: 5-6
"""

import _lib_path  # noqa: F401
from pathlib import Path

from _hook_registry import register_hook
from _hook_result import HookResult
from session_state import SessionState


@register_hook("exploration_cacher", "Task", priority=5)
def check_exploration_cacher(
    data: dict, state: SessionState, runner_state: dict
) -> HookResult:
    """Cache exploration results after Task(Explore) completes."""
    tool_input = data.get("tool_input", {})
    subagent_type = tool_input.get("subagent_type", "")

    if subagent_type.lower() != "explore":
        return HookResult.allow()

    prompt = tool_input.get("prompt", "")
    result = data.get("tool_result", {})

    # Get the agent's response
    agent_output = ""
    if isinstance(result, dict):
        agent_output = (
            result.get("content", "") or result.get("output", "") or str(result)
        )
    elif isinstance(result, str):
        agent_output = result

    # Don't cache empty or error results
    if not agent_output or len(agent_output) < 50:
        return HookResult.allow()
    if "error" in agent_output.lower()[:100]:
        return HookResult.allow()

    # Detect project path
    try:
        from project_detector import detect_project

        project_info = detect_project()
        if not project_info or not project_info.get("path"):
            return HookResult.allow()
        project_path = project_info["path"]
    except Exception:
        return HookResult.allow()

    # Cache the result
    try:
        from cache.exploration_cache import cache_exploration

        cache_exploration(
            project_path=Path(project_path),
            query=prompt,
            result=agent_output[:5000],
            directory_path="",
            touched_files=[],
        )
    except Exception:
        pass

    return HookResult.allow()


@register_hook("read_cacher", "Read", priority=6)
def check_read_cacher(
    data: dict, state: SessionState, runner_state: dict
) -> HookResult:
    """Cache successful Read results for memoization."""
    tool_input = data.get("tool_input", {})
    file_path = tool_input.get("file_path", "")

    if not file_path:
        return HookResult.allow()

    # Don't cache partial reads
    if tool_input.get("offset") or tool_input.get("limit"):
        return HookResult.allow()

    result = data.get("tool_result", {})

    # Get the file content from result
    content = ""
    if isinstance(result, dict):
        content = result.get("content", "") or result.get("output", "") or ""
    elif isinstance(result, str):
        content = result

    # Don't cache errors or empty results
    if not content or "error" in content.lower()[:50]:
        return HookResult.allow()

    try:
        from cache.read_cache import cache_read_result

        cache_read_result(file_path, content)
    except Exception:
        pass

    return HookResult.allow()


@register_hook("read_cache_invalidator", "Write|Edit", priority=6)
def check_read_cache_invalidator(
    data: dict, state: SessionState, runner_state: dict
) -> HookResult:
    """Invalidate read cache when files are written or edited."""
    tool_input = data.get("tool_input", {})
    file_path = tool_input.get("file_path", "")

    if not file_path:
        return HookResult.allow()

    try:
        from cache.read_cache import invalidate_read_cache

        invalidate_read_cache(file_path)
    except Exception:
        pass

    return HookResult.allow()
