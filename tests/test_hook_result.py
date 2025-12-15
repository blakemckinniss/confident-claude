"""Tests for unified HookResult class."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "hooks"))

from _hook_result import HookResult


class TestHookResultApprove:
    """Tests for approve/allow methods."""

    def test_approve_returns_approve_decision(self):
        # Act
        result = HookResult.approve()

        # Assert
        assert result.decision == "approve"

    def test_approve_with_context_includes_context(self):
        # Arrange
        context = "Some helpful context"

        # Act
        result = HookResult.approve(context)

        # Assert
        assert result.context == context

    def test_allow_is_alias_for_approve(self):
        # Act
        result = HookResult.allow("test context")

        # Assert
        assert result.decision == "approve"
        assert result.context == "test context"


class TestHookResultDeny:
    """Tests for deny method."""

    def test_deny_returns_deny_decision(self):
        # Act
        result = HookResult.deny("blocked reason")

        # Assert
        assert result.decision == "deny"

    def test_deny_includes_reason(self):
        # Arrange
        reason = "Dangerous operation blocked"

        # Act
        result = HookResult.deny(reason)

        # Assert
        assert result.reason == reason


class TestHookResultAliases:
    """Tests for convenience aliases."""

    def test_none_returns_empty_result(self):
        # Act
        result = HookResult.none()

        # Assert
        assert result.decision == "approve"
        assert result.context == ""
        assert result.reason == ""

    def test_with_context_returns_approve_with_context(self):
        # Arrange
        context = "Injected context"

        # Act
        result = HookResult.with_context(context)

        # Assert
        assert result.decision == "approve"
        assert result.context == context
