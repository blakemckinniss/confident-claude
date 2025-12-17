"""Routing decision engine - policy layer for mastermind.

Handles:
- User overrides (! to skip, ^ to force)
- Session-start-only enforcement
- Bias-toward-complex logic for uncertainty
- Observability payload generation
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .config import get_config
from .router_groq import RouterResponse


@dataclass
class RoutingPolicy:
    """Policy decision for a routing request."""
    should_route: bool
    should_plan: bool
    reason: str
    user_override: str | None = None
    classification: str = "trivial"
    confidence: float = 0.0
    reason_codes: list[str] | None = None


def parse_user_override(prompt: str) -> tuple[str, str | None]:
    """Extract user override prefix from prompt.

    Overrides:
    - "!" prefix: Skip routing entirely (execute directly)
    - "^" prefix: Force complex classification (always plan)

    Returns:
        (clean_prompt, override_type) where override_type is "!", "^", or None
    """
    prompt = prompt.strip()

    if prompt.startswith("!"):
        return prompt[1:].strip(), "!"
    if prompt.startswith("^"):
        return prompt[1:].strip(), "^"

    return prompt, None


def check_session_start(turn_count: int) -> bool:
    """Check if we're at session start (turn 0 or 1).

    Routing only happens at session start per architecture decision.
    """
    return turn_count <= 1


def apply_uncertainty_bias(response: RouterResponse) -> RouterResponse:
    """Apply bias-toward-complex for uncertain classifications.

    When confidence is below threshold, escalate to complex.
    This implements "when in doubt, consult the planner" policy.
    """
    config = get_config()

    if not config.router.force_complex_when_uncertain:
        return response

    if response.is_uncertain and response.classification != "complex":
        return RouterResponse(
            classification="complex",
            confidence=response.confidence,
            reason_codes=(response.reason_codes or []) + ["uncertainty_escalation"],
            raw_response=response.raw_response,
            latency_ms=response.latency_ms,
            error=response.error,
        )

    return response


def make_routing_decision(
    prompt: str,
    turn_count: int,
    router_response: RouterResponse | None = None,
) -> RoutingPolicy:
    """Make routing decision based on prompt, turn, and router response.

    Args:
        prompt: User's original prompt (may contain override prefix)
        turn_count: Current turn in session
        router_response: Optional pre-computed router response

    Returns:
        RoutingPolicy with decision and reasoning
    """
    config = get_config()

    # Check if routing is enabled
    if not config.router.enabled:
        return RoutingPolicy(
            should_route=False,
            should_plan=False,
            reason="routing_disabled",
        )

    # Parse user override
    clean_prompt, override = parse_user_override(prompt)

    # Handle explicit skip override
    if override == "!":
        return RoutingPolicy(
            should_route=False,
            should_plan=False,
            reason="user_skip_override",
            user_override="!",
        )

    # Handle explicit force override
    if override == "^":
        return RoutingPolicy(
            should_route=True,
            should_plan=True,
            reason="user_force_override",
            user_override="^",
            classification="complex",
            confidence=1.0,
            reason_codes=["user_forced"],
        )

    # Check session start constraint
    if not check_session_start(turn_count):
        return RoutingPolicy(
            should_route=False,
            should_plan=False,
            reason="not_session_start",
        )

    # No router response means we need to call router
    if router_response is None:
        return RoutingPolicy(
            should_route=True,
            should_plan=False,  # Will be determined after router call
            reason="needs_classification",
        )

    # Apply uncertainty bias
    response = apply_uncertainty_bias(router_response)

    # Determine if planning is needed
    should_plan = response.classification in ("medium", "complex")
    if not config.planner.enabled:
        should_plan = False

    return RoutingPolicy(
        should_route=True,
        should_plan=should_plan,
        reason=f"classified_{response.classification}",
        classification=response.classification,
        confidence=response.confidence,
        reason_codes=response.reason_codes,
    )


def generate_observability_payload(
    policy: RoutingPolicy,
    router_response: RouterResponse | None,
    prompt_tokens: int,
) -> dict[str, Any]:
    """Generate structured payload for telemetry.

    Returns dict suitable for JSONL logging.
    """
    return {
        "event": "routing_decision",
        "should_route": policy.should_route,
        "should_plan": policy.should_plan,
        "reason": policy.reason,
        "user_override": policy.user_override,
        "classification": policy.classification,
        "confidence": policy.confidence,
        "reason_codes": policy.reason_codes or [],
        "router_latency_ms": router_response.latency_ms if router_response else None,
        "router_error": router_response.error if router_response else None,
        "prompt_tokens": prompt_tokens,
    }
