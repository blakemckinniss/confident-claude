"""
Unified HookResult class for all hook runners.

Provides consistent API across pre_tool_use, post_tool_use, and user_prompt_submit runners.
"""

from dataclasses import dataclass


@dataclass
class HookResult:
    """Result from a hook check.

    Attributes:
        decision: "approve" or "deny" - whether the tool call should proceed
        reason: Explanation for deny decisions
        context: Additional context to inject into the conversation
    """

    decision: str = "approve"
    reason: str = ""
    context: str = ""

    @staticmethod
    def approve(context: str = "") -> "HookResult":
        """Approve the action, optionally with context to inject."""
        return HookResult(decision="approve", context=context)

    @staticmethod
    def deny(reason: str) -> "HookResult":
        """Deny the action with an explanation."""
        return HookResult(decision="deny", reason=reason)

    # Aliases for backward compatibility and convenience
    @staticmethod
    def allow(context: str = "") -> "HookResult":
        """Alias for approve() - for consistency with user_prompt_submit patterns."""
        return HookResult(decision="approve", context=context)

    @staticmethod
    def none() -> "HookResult":
        """Return empty result (no context, no denial) - alias for approve()."""
        return HookResult()

    @staticmethod
    def with_context(context: str) -> "HookResult":
        """Approve with context to inject - alias for approve(context)."""
        return HookResult(decision="approve", context=context)
