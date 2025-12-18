"""
Mastermind Integration Hook - Multi-model orchestration for complex tasks.

Priority 6: Runs after confidence gating, before context extraction.

Phase 0 (dark_launch): Logs routing decisions without affecting execution
Phase 1 (explicit_override_only): Only ^ prefix triggers planning
Phase 2+: Auto-planning for complex tasks
"""

import os
import sys
from pathlib import Path

# Add lib to path for mastermind imports
lib_path = Path(__file__).parent.parent / "lib"
if str(lib_path) not in sys.path:
    sys.path.insert(0, str(lib_path))


def _get_current_session_id() -> str | None:
    """Get current Claude session ID from environment.

    This is the ACTUAL current session, not the potentially stale
    session_id from global SessionState which persists across sessions.
    """
    return os.environ.get("CLAUDE_SESSION_ID")


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

        # Get ACTUAL current session ID from env (not stale state)
        # This ensures mastermind detects new sessions correctly
        current_session_id = _get_current_session_id()

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
