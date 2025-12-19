"""
Mastermind Integration Hook - Multi-model orchestration for complex tasks.

Priority 6: Runs after confidence gating, before context extraction.

Phase 0 (dark_launch): Logs routing decisions without affecting execution
Phase 1 (explicit_override_only): Only ^ prefix triggers planning
Phase 2+: Auto-planning for complex tasks
"""

import json
import sys
from pathlib import Path

# Add lib to path for mastermind imports
lib_path = Path(__file__).parent.parent / "lib"
if str(lib_path) not in sys.path:
    sys.path.insert(0, str(lib_path))

# Priming packs cache
_PRIMING_PACKS: dict | None = None


def _load_priming_packs() -> dict:
    """Load task-type priming packs from config."""
    global _PRIMING_PACKS
    if _PRIMING_PACKS is not None:
        return _PRIMING_PACKS

    packs_path = Path(__file__).parent.parent / "config" / "task_priming_packs.json"
    try:
        if packs_path.exists():
            _PRIMING_PACKS = json.loads(packs_path.read_text())
        else:
            _PRIMING_PACKS = {}
    except Exception:
        _PRIMING_PACKS = {}
    return _PRIMING_PACKS


def _format_priming_pack(task_type: str) -> str | None:
    """Format priming pack for injection based on task type."""
    packs = _load_priming_packs()
    pack = packs.get(task_type, packs.get("general", {}))

    if not pack or not pack.get("constraints"):
        return None

    parts = []
    if pack.get("header"):
        parts.append(pack["header"])

    if pack.get("constraints"):
        parts.append("**Do:**")
        for constraint in pack["constraints"]:
            parts.append(f"- {constraint}")

    if pack.get("anti_patterns"):
        parts.append("**Don't:**")
        for anti in pack["anti_patterns"]:
            parts.append(f"- {anti}")

    return "\n".join(parts) if parts else None


# Hint catalog cache
_HINT_CATALOG: dict | None = None


def _load_hint_catalog() -> dict:
    """Load action hint catalog from config."""
    global _HINT_CATALOG
    if _HINT_CATALOG is not None:
        return _HINT_CATALOG

    catalog_path = Path(__file__).parent.parent / "config" / "hint_catalog.json"
    try:
        if catalog_path.exists():
            _HINT_CATALOG = json.loads(catalog_path.read_text())
        else:
            _HINT_CATALOG = {}
    except Exception:
        _HINT_CATALOG = {}
    return _HINT_CATALOG


def _format_action_hints(action_hints: list | None) -> str | None:
    """Expand and format action hints from IDs."""
    if not action_hints:
        return None

    catalog = _load_hint_catalog()
    hints_data = catalog.get("action_hints", {})

    parts = []
    for hint in action_hints:
        hint_id = hint.id if hasattr(hint, "id") else hint.get("id", "")
        priority = hint.priority if hasattr(hint, "priority") else hint.get("priority", "p1")

        if hint_id in hints_data:
            h = hints_data[hint_id]
            icon = h.get("icon", "💡")
            message = h.get("message", hint_id)
            kind = h.get("kind", "do")

            # Priority indicator
            pri_icon = "🔴" if priority == "p0" else "🟡" if priority == "p1" else "🔵"

            if kind == "caution":
                parts.append(f"{pri_icon} ⚠️ {message}")
            else:
                parts.append(f"{pri_icon} {icon} {message}")

    if not parts:
        return None

    return "**Action Hints:**\n" + "\n".join(parts)


def _format_recommended_capabilities(recommended) -> str | None:
    """Format capability recommendations by category."""
    if not recommended:
        return None

    parts = []

    # Skills
    skills = recommended.skills if hasattr(recommended, "skills") else recommended.get("skills")
    if skills:
        parts.append(f"🎯 **Skills:** {', '.join(skills)}")

    # Agents
    agents = recommended.agents if hasattr(recommended, "agents") else recommended.get("agents")
    if agents:
        parts.append(f"🤖 **Agents:** {', '.join(agents)}")

    # MCP Tools
    mcp = recommended.mcp_tools if hasattr(recommended, "mcp_tools") else recommended.get("mcp_tools")
    if mcp:
        parts.append(f"🔧 **MCP Tools:** {', '.join(mcp)}")

    # Ops Scripts
    ops = recommended.ops_scripts if hasattr(recommended, "ops_scripts") else recommended.get("ops_scripts")
    if ops:
        parts.append(f"📜 **Ops Scripts:** {', '.join(ops)}")

    if not parts:
        return None

    return "**Recommended Capabilities:**\n" + "\n".join(parts)


def _get_current_session_id(data: dict) -> str | None:
    """Get current Claude session ID from hook input data.

    Claude Code passes session_id in the JSON stdin data, not as an
    environment variable. This is the ACTUAL current session.
    """
    return data.get("session_id")


from _prompt_registry import register_hook, HookResult  # noqa: E402

try:
    from mastermind import process_user_prompt, load_config

    MASTERMIND_AVAILABLE = True
except ImportError as e:
    MASTERMIND_AVAILABLE = False
    MASTERMIND_ERROR = str(e)


@register_hook("mastermind_orchestrator", priority=6)
def mastermind_orchestrator(data: dict, state) -> HookResult:
    """
    Orchestrate multi-model routing and planning.

    Returns context with routing info and optional blueprint instructions.
    Never denies - only augments context.
    """
    if not MASTERMIND_AVAILABLE:
        # Silently skip if mastermind module not available
        return HookResult(decision="allow", context=None)

    try:
        config = load_config()

        # Get ACTUAL current session ID from hook input data
        # This ensures mastermind detects new sessions correctly
        current_session_id = _get_current_session_id(data)

        # Check if system is enabled at all
        if config.rollout_phase == 0:
            # Dark launch - run but don't inject context
            # Still logs telemetry for validation
            prompt = data.get("prompt", "")
            if prompt:
                process_user_prompt(
                    prompt=prompt,
                    turn_count=getattr(state, "turn_count", 0),
                    session_id=current_session_id,
                )
                # Log but don't inject
                return HookResult(decision="allow", context=None)
            return HookResult(decision="allow", context=None)

        # Phase 1+: Active orchestration
        prompt = data.get("prompt", "")
        if not prompt:
            return HookResult(decision="allow", context=None)

        result = process_user_prompt(
            prompt=prompt,
            turn_count=getattr(state, "turn_count", 0),
            session_id=current_session_id,
            confidence=getattr(state, "confidence", 70),
        )

        # Build context from result
        context_parts = []

        # Get routing info
        routing = result.get("routing_info", {})

        # PRIORITY: Check for PAL mandate injection (^ override)
        # This MUST be injected for the pre_tool_use block to make sense
        inject_context = routing.get("inject_context") or result.get("inject_context")
        if inject_context:
            # PAL mandate or other injected context takes priority
            context_parts.append(inject_context)

        # Add routing classification info
        if routing and not inject_context:  # Skip if mandate already shown
            classification = routing.get("classification", "unknown")
            confidence = routing.get("confidence", 0)
            if classification != "unknown":
                context_parts.append(
                    f"🎯 **Mastermind**: Task classified as `{classification}` "
                    f"(confidence: {confidence:.0%})"
                )

        # Inject task-type priming pack (behavioral constraints)
        task_type = routing.get("task_type", "general") if routing else "general"
        priming_pack = _format_priming_pack(task_type)
        if priming_pack:
            context_parts.append(priming_pack)

        # Inject action hints (prescriptive recommendations)
        action_hints = routing.get("action_hints") if routing else None
        hints_formatted = _format_action_hints(action_hints)
        if hints_formatted:
            context_parts.append(hints_formatted)

        # Inject recommended capabilities (toolbox for this task)
        recommended = routing.get("recommended") if routing else None
        caps_formatted = _format_recommended_capabilities(recommended)
        if caps_formatted:
            context_parts.append(caps_formatted)

        # Add research recommendation if needed
        needs_research = routing.get("needs_research", False) if routing else False
        research_topics = routing.get("research_topics", []) if routing else []
        if needs_research and research_topics:
            # Build structured research directive with exact tool calls
            search_calls = "\n".join(
                f'- `mcp__crawl4ai__ddg_search` query="{topic}"'
                for topic in research_topics[:3]
            )
            context_parts.append(
                f"🔍 **Research First**: Current docs/APIs may be needed for accuracy.\n\n"
                f"**Run these searches before proceeding:**\n{search_calls}\n\n"
                f"**Then:** Summarize top 2-3 findings and include in your PAL tool prompt."
            )

        # Add blueprint if generated
        blueprint = result.get("blueprint")
        if blueprint:
            context_parts.append(
                f"📋 **Blueprint Available**: {blueprint.get('summary', 'See executor instructions')}"
            )

        # Add executor instructions if present
        instructions = result.get("executor_instructions")
        if instructions:
            context_parts.append(f"\n{instructions}")

        context = "\n".join(context_parts) if context_parts else None
        return HookResult(decision="allow", context=context)

    except Exception as e:
        # Never block on mastermind errors - fail silently
        print(f"[mastermind] Error: {e}", file=sys.stderr)
        return HookResult(decision="allow", context=None)


@register_hook("mastermind_drift_check", priority=65)
def mastermind_drift_check(data: dict, state) -> HookResult:
    """
    Check for drift from blueprint and warn if escalation needed.

    Priority 65: Runs after context injection, before suggestions.
    Only active when drift detection is enabled and blueprint exists.
    """
    if not MASTERMIND_AVAILABLE:
        return HookResult(decision="allow", context=None)

    try:
        config = load_config()
        if not config.drift.enabled:
            return HookResult(decision="allow", context=None)

        # Import drift check from hooks state module
        from _hooks_state import check_mastermind_drift

        drift_warning = check_mastermind_drift(state)
        if drift_warning:
            return HookResult(decision="allow", context=drift_warning)

        return HookResult(decision="allow", context=None)

    except Exception as e:
        print(f"[mastermind-drift] Error: {e}", file=sys.stderr)
        return HookResult(decision="allow", context=None)
