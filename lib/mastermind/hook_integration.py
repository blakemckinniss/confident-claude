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
from .context_packer import pack_for_router, pack_for_planner
from .routing import parse_user_override, make_routing_decision
from .router_groq import call_groq_router, apply_risk_lexicon
from .redaction import redact_text
from .drift import evaluate_drift, should_escalate
from .executor_instructions import generate_executor_instructions, should_inject_instructions
from .telemetry import log_router_decision, log_planner_called, log_escalation
from .variance import generate_variance_report, format_variance_for_user


def get_session_id() -> str:
    """Get current session ID from environment or generate one."""
    return os.environ.get("CLAUDE_SESSION_ID", f"session_{int(time.time())}")


def process_user_prompt(
    prompt: str,
    turn_count: int,
    cwd: Path | None = None,
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
    session_id = get_session_id()
    result: dict[str, Any] = {
        "inject_context": None,
        "modified_prompt": prompt,
        "routing_info": {},
        "warnings": [],
    }

    # Load or create session state
    state = load_state(session_id)
    state.turn_count = turn_count

    # Parse user override
    clean_prompt, override = parse_user_override(prompt)
    result["modified_prompt"] = clean_prompt

    # Check if routing applies (turn 0-1 only)
    if turn_count <= 1 and config.router.enabled:
        result["routing_info"] = handle_session_start_routing(
            clean_prompt, override, state, cwd
        )

    # Check for drift on subsequent turns
    elif turn_count > 1 and config.drift.enabled and state.blueprint:
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
        # Would call planner here
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
