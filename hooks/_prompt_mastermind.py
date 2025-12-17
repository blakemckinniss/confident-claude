"""
Mastermind Integration Hook - Multi-model orchestration for complex tasks.

Priority 6: Runs after confidence gating, before context extraction.

Phase 0 (dark_launch): Logs routing decisions without affecting execution
Phase 1 (explicit_override_only): Only ^ prefix triggers planning
Phase 2+: Auto-planning for complex tasks
"""

import sys
from pathlib import Path

# Add lib to path for mastermind imports
lib_path = Path(__file__).parent.parent / "lib"
if str(lib_path) not in sys.path:
    sys.path.insert(0, str(lib_path))

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

        # Check if system is enabled at all
        if config.rollout_phase == 0:
            # Dark launch - run but don't inject context
            # Still logs telemetry for validation
            prompt = data.get("prompt", "")
            if prompt:
                process_user_prompt(
                    prompt=prompt,
                    turn_count=getattr(state, "turn_count", 0),
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
        )

        # Build context from result
        context_parts = []

        # Add routing info
        routing = result.get("routing_info", {})
        if routing:
            classification = routing.get("classification", "unknown")
            confidence = routing.get("confidence", 0)
            if classification != "unknown":
                context_parts.append(
                    f"🎯 **Mastermind**: Task classified as `{classification}` "
                    f"(confidence: {confidence:.0%})"
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
