"""Hook integration for mastermind in UserPromptSubmit.

Wires mastermind components into the hook lifecycle:
1. Turn 0-1: Route and optionally plan
2. Turn 2+: Monitor for drift
3. Inject executor instructions when blueprint exists
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

from .config import get_config
from .state import MastermindState, load_state, save_state
from .context_packer import pack_for_router
from .routing import parse_user_override, make_routing_decision
from .router_groq import call_groq_router, apply_risk_lexicon
from .redaction import redact_text
from .drift import evaluate_drift, should_escalate
from .executor_instructions import (
    generate_executor_instructions,
    should_inject_instructions,
)
from .telemetry import log_router_decision, log_escalation
from .variance import generate_variance_report, format_variance_for_user


def get_session_id() -> str:
    """Get current session ID from environment or generate one."""
    return os.environ.get("CLAUDE_SESSION_ID", f"session_{int(time.time())}")


# =============================================================================
# PAL MCP PLANNER MANDATE
# =============================================================================
# This mandate is injected when user triggers ^ override.
# Claude MUST obey these instructions - they are non-negotiable.
# =============================================================================

PLANNER_MANDATE_TEMPLATE = """
# 🚨 MANDATORY: PAL MCP PLANNER REQUIRED 🚨

**THIS IS A HARD REQUIREMENT. YOU MUST COMPLY.**

The user has requested strategic planning via the `^` prefix. You are REQUIRED to use the PAL MCP planner tool BEFORE doing ANY other work.

## MANDATORY FIRST ACTION

You MUST call `mcp__pal__planner` with these EXACT parameters:

```
Tool: mcp__pal__planner
Parameters:
  - model: "openai/gpt-5.2" (MANDATORY - DO NOT SUBSTITUTE)
  - step: <planning content analyzing the user's request>
  - step_number: 1
  - total_steps: 2
  - next_step_required: true
  - use_assistant_model: true
```

## WHAT YOU MUST DO

1. **IMMEDIATELY** call `mcp__pal__planner` as your FIRST tool use
2. Use model "openai/gpt-5.2" - NO SUBSTITUTIONS ALLOWED
3. In your step content, analyze:
   - What is the user's goal?
   - What files will likely be touched?
   - What constraints/invariants must be preserved?
   - What are the acceptance criteria?
4. Wait for GPT-5.2's strategic analysis
5. Use the planner's output to guide your implementation

## FORBIDDEN ACTIONS

- ❌ DO NOT skip the planner call
- ❌ DO NOT substitute a different model
- ❌ DO NOT proceed with implementation before planning
- ❌ DO NOT use your own judgment instead of calling the planner

## WHY THIS MATTERS

The user explicitly requested multi-model orchestration. GPT-5.2 provides strategic planning that complements your execution capabilities. This is not optional.

## USER'S REQUEST

{user_prompt}

---

**NOW: Call `mcp__pal__planner` with model "openai/gpt-5.2" IMMEDIATELY.**
"""


def generate_planner_mandate(prompt: str, state: MastermindState) -> str:
    """Generate the mandatory PAL MCP planner directive.

    This creates an extremely strong instruction that Claude must
    use PAL MCP with GPT-5.2 before proceeding with any work.
    """
    return PLANNER_MANDATE_TEMPLATE.format(
        user_prompt=prompt,
        session_id=state.session_id,
        turn=state.turn_count,
    )


# =============================================================================
# PAL MANDATE LOCK FILE - Hard enforcement via pre_tool_use hook
# =============================================================================

PAL_MANDATE_LOCK_PATH = Path.home() / ".claude" / "tmp" / "pal_mandate.lock"


def create_pal_mandate_lock(
    session_id: str,
    project: str,
    prompt: str,
) -> Path:
    """Create lock file that blocks all tools until PAL planner is called.

    The pre_tool_use hook checks this lock and HARD BLOCKS everything
    except mcp__pal__planner with GPT-5.x model.
    """
    import json

    lock_data = {
        "session_id": session_id,
        "project": project,
        "prompt": prompt[:500],  # Truncate for readability
        "created_at": time.time(),
        "created_at_iso": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }

    PAL_MANDATE_LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    PAL_MANDATE_LOCK_PATH.write_text(json.dumps(lock_data, indent=2))

    return PAL_MANDATE_LOCK_PATH


def clear_pal_mandate_lock() -> bool:
    """Clear the PAL mandate lock file."""
    if PAL_MANDATE_LOCK_PATH.exists():
        PAL_MANDATE_LOCK_PATH.unlink()
        return True
    return False


def process_user_prompt(
    prompt: str,
    turn_count: int,
    cwd: Path | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Process user prompt through mastermind pipeline.

    Called from UserPromptSubmit hook.

    Args:
        prompt: User's raw prompt
        turn_count: Current turn number
        cwd: Working directory

    Returns:
        Dict with:
        - inject_context: Optional context to inject
        - modified_prompt: Prompt after override extraction
        - routing_info: Routing decision metadata
        - warnings: Any warnings for user
    """
    config = get_config()
    session_id = session_id or get_session_id()
    result: dict[str, Any] = {
        "inject_context": None,
        "modified_prompt": prompt,
        "routing_info": {},
        "warnings": [],
    }

    # Load or create session state keyed by CURRENT session_id
    # This ensures each Claude session gets fresh state
    state = load_state(session_id)

    # Parse user override
    clean_prompt, override = parse_user_override(prompt)
    result["modified_prompt"] = clean_prompt

    # Check if routing applies:
    # - ALWAYS route if ^ override (user explicitly requested planning)
    # - Otherwise, route on turn 0 of THIS session (using mastermind's own counter)
    # We use mastermind's internal turn counter (pre-increment) since it's keyed by
    # the actual CLAUDE_SESSION_ID, not the potentially stale global SessionState
    is_session_start = state.turn_count == 0  # Before increment = first turn
    should_route = (
        (override == "^")  # User explicitly requested planning
        or (is_session_start and config.router.enabled)  # First turn of this session
    )

    # NOW increment turn counter (after routing check)
    state.increment_turn()
    if should_route:
        result["routing_info"] = handle_session_start_routing(
            clean_prompt, override, state, cwd
        )

    # Check for drift on subsequent turns
    elif state.turn_count > 1 and config.drift.enabled and state.blueprint:
        drift_result = handle_drift_check(state)
        if drift_result.get("warnings"):
            result["warnings"].extend(drift_result["warnings"])

    # Inject executor instructions if blueprint exists
    if should_inject_instructions(state):
        result["inject_context"] = generate_executor_instructions(
            state.blueprint, state
        )

    # Save state
    save_state(state)

    return result


def handle_session_start_routing(
    prompt: str,
    override: str | None,
    state: MastermindState,
    cwd: Path | None,
) -> dict[str, Any]:
    """Handle routing at session start (turn 0-1).

    Returns routing metadata.
    """
    config = get_config()
    result: dict[str, Any] = {"routed": False}

    # Handle explicit overrides
    if override == "!":
        result["skipped"] = True
        result["reason"] = "user_skip"
        return result

    if override == "^":
        result["forced"] = True
        result["classification"] = "complex"
        result["routed"] = True
        result["planner_mandate"] = True

        # Get project from cwd
        project = cwd.name if cwd else "unknown"

        # CREATE HARD LOCK - blocks ALL tools until PAL planner is called
        create_pal_mandate_lock(
            session_id=state.session_id,
            project=project,
            prompt=prompt,
        )

        # Inject MANDATORY PAL MCP planner directive
        result["inject_context"] = generate_planner_mandate(prompt, state)
        return result

    # Pack context for router
    router_ctx = pack_for_router(prompt, cwd)

    # Redact before sending
    redacted_prompt, _ = redact_text(router_ctx.prompt)

    # Call router (if not in dark launch)
    if config.rollout_phase > 0:
        router_response = call_groq_router(redacted_prompt)
        router_response = apply_risk_lexicon(prompt, router_response)

        # Log telemetry
        log_router_decision(
            state.session_id,
            state.turn_count,
            router_response.classification,
            router_response.confidence,
            router_response.reason_codes,
            router_response.latency_ms,
            override,
        )

        result["routed"] = True
        result["classification"] = router_response.classification
        result["confidence"] = router_response.confidence
        result["reason_codes"] = router_response.reason_codes

        # Apply routing decision
        policy = make_routing_decision(prompt, state.turn_count, router_response)
        result["should_plan"] = policy.should_plan

    else:
        # Dark launch - just log what would happen
        result["dark_launch"] = True
        result["would_route"] = True

    return result


def handle_drift_check(state: MastermindState) -> dict[str, Any]:
    """Check for drift and generate warnings if needed."""
    result: dict[str, Any] = {"warnings": []}

    signals = evaluate_drift(state)

    if signals and should_escalate(signals, state):
        # Generate variance report
        report = generate_variance_report(state, signals)
        warning = format_variance_for_user(report)
        result["warnings"].append(warning)

        # Log escalation
        for signal in signals:
            log_escalation(
                state.session_id,
                state.turn_count,
                signal.trigger,
                state.epoch_id,
                signal.evidence,
            )

        # Record escalation in state
        state.record_escalation(
            signals[0].trigger,
            signals[0].evidence,
        )

    return result


def record_file_modification(file_path: str) -> None:
    """Record a file modification in session state.

    Called from Edit/Write tool hooks.
    """
    session_id = get_session_id()
    state = load_state(session_id)
    state.record_file_modified(file_path)
    save_state(state)


def record_test_failure() -> None:
    """Increment test failure count in session state.

    Called when test commands fail.
    """
    session_id = get_session_id()
    state = load_state(session_id)
    state.test_failures += 1
    save_state(state)
