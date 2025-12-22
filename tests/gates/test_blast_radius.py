#!/usr/bin/env python3
"""Unit tests for blast radius gate.

Tests the confidence escalation based on Groq's risk_signals.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pytest
from hooks.gates._blast_radius import (
    check_blast_radius_gate,
    _is_state_changing_bash,
    _BLAST_RADIUS_ESCALATION,
    _REVERSIBILITY_ESCALATION,
)


class MockSessionState:
    """Mock session state for testing."""

    def __init__(self, confidence: int = 85, data: dict | None = None):
        self._confidence = confidence
        self._data = data or {}

    @property
    def confidence(self) -> int:
        return self._confidence

    def get(self, key: str, default=None):
        return self._data.get(key, default)


class TestBlastRadiusEscalation:
    """Test blast radius confidence escalation values."""

    def test_escalation_values_defined(self):
        """Verify escalation values are defined for all levels."""
        assert _BLAST_RADIUS_ESCALATION["local"] == 0
        assert _BLAST_RADIUS_ESCALATION["module"] == 5
        assert _BLAST_RADIUS_ESCALATION["service"] == 10
        assert _BLAST_RADIUS_ESCALATION["multi_service"] == 15
        assert _BLAST_RADIUS_ESCALATION["prod_wide"] == 20

    def test_reversibility_values_defined(self):
        """Verify reversibility escalation values."""
        assert _REVERSIBILITY_ESCALATION["easy"] == 0
        assert _REVERSIBILITY_ESCALATION["moderate"] == 5
        assert _REVERSIBILITY_ESCALATION["hard"] == 10
        assert _REVERSIBILITY_ESCALATION["irreversible"] == 20


class TestStateChangingBash:
    """Test bash command classification."""

    def test_readonly_commands_not_state_changing(self):
        """Verify read-only commands are not flagged."""
        readonly = [
            "ls -la",
            "cat file.txt",
            "head -n 10 file.txt",
            "tail -f log.txt",
            "pwd",
            "which python",
            "tree .",
            "stat file.py",
            "echo hello",
            "grep pattern file.txt",
            "find . -name '*.py'",
            "git status",
            "git log --oneline",
            "git diff HEAD",
            "git show HEAD",
            "git branch -a",
            "ruff check src/",
            "pytest tests/",
            "python -m pytest tests/",
        ]
        for cmd in readonly:
            assert not _is_state_changing_bash(cmd), f"Expected {cmd} to be read-only"

    def test_state_changing_commands_flagged(self):
        """Verify state-changing commands are flagged."""
        state_changing = [
            "rm file.txt",
            "mv old.py new.py",
            "cp src.py dest.py",
            "mkdir new_dir",
            "touch file.txt",
            "git commit -m 'msg'",
            "git push origin main",
            "pip install package",
            "npm install",
            "docker run image",
        ]
        for cmd in state_changing:
            assert _is_state_changing_bash(cmd), f"Expected {cmd} to be state-changing"


class TestBlastRadiusGate:
    """Test the blast radius gate logic."""

    def test_no_risk_signals_approves(self):
        """Gate approves when no risk signals present."""
        state = MockSessionState(confidence=51)
        data = {"tool_name": "Edit", "tool_input": {"file_path": "test.py"}}

        result = check_blast_radius_gate(data, state)

        assert result.decision == "approve"

    def test_sudo_bypass(self):
        """SUDO bypass works."""
        state = MockSessionState(
            confidence=30,
            data={
                "mastermind_risk_signals": {
                    "blast_radius": "prod_wide",
                    "reversibility": "irreversible",
                }
            },
        )
        data = {"tool_name": "Edit", "_sudo_bypass": True}

        result = check_blast_radius_gate(data, state)

        assert result.decision == "approve"
        assert "SUDO" in (result.context or "")

    def test_readonly_bash_skipped(self):
        """Read-only bash commands skip the gate."""
        state = MockSessionState(
            confidence=30,
            data={
                "mastermind_risk_signals": {
                    "blast_radius": "prod_wide",
                }
            },
        )
        data = {"tool_name": "Bash", "tool_input": {"command": "git status"}}

        result = check_blast_radius_gate(data, state)

        assert result.decision == "approve"

    def test_local_blast_radius_no_escalation(self):
        """Local blast radius requires no additional confidence."""
        state = MockSessionState(
            confidence=51,
            data={
                "mastermind_risk_signals": {
                    "blast_radius": "local",
                    "reversibility": "easy",
                }
            },
        )
        data = {"tool_name": "Edit", "tool_input": {}}

        result = check_blast_radius_gate(data, state)

        assert result.decision == "approve"

    def test_service_blast_radius_escalation(self):
        """Service blast radius requires +10% confidence."""
        # 51 base + 10 = 61 required, 55 current = BLOCK
        state = MockSessionState(
            confidence=55,
            data={
                "mastermind_risk_signals": {
                    "blast_radius": "service",
                    "reversibility": "easy",
                }
            },
        )
        data = {"tool_name": "Edit", "tool_input": {}}

        result = check_blast_radius_gate(data, state)

        assert result.decision == "deny"
        assert "61%" in (result.reason or "")  # Required

    def test_service_blast_radius_sufficient_confidence(self):
        """Service blast radius passes with sufficient confidence."""
        # 51 base + 10 = 61 required, 65 current = APPROVE
        state = MockSessionState(
            confidence=65,
            data={
                "mastermind_risk_signals": {
                    "blast_radius": "service",
                    "reversibility": "easy",
                }
            },
        )
        data = {"tool_name": "Edit", "tool_input": {}}

        result = check_blast_radius_gate(data, state)

        assert result.decision == "approve"

    def test_irreversible_escalation(self):
        """Irreversible operations require +20% confidence."""
        # 51 base + 20 = 71 required, 60 current = BLOCK
        state = MockSessionState(
            confidence=60,
            data={
                "mastermind_risk_signals": {
                    "blast_radius": "local",
                    "reversibility": "irreversible",
                }
            },
        )
        data = {"tool_name": "Edit", "tool_input": {}}

        result = check_blast_radius_gate(data, state)

        assert result.decision == "deny"
        assert "71%" in (result.reason or "")

    def test_max_of_blast_and_reversibility(self):
        """Takes max of blast_radius and reversibility delta (no stacking)."""
        # blast_radius=service (+10), reversibility=hard (+10)
        # max(10, 10) = 10, not 20
        # 51 base + 10 = 61 required, 62 current = APPROVE
        state = MockSessionState(
            confidence=62,
            data={
                "mastermind_risk_signals": {
                    "blast_radius": "service",
                    "reversibility": "hard",
                }
            },
        )
        data = {"tool_name": "Edit", "tool_input": {}}

        result = check_blast_radius_gate(data, state)

        assert result.decision == "approve"

    def test_prod_wide_escalation(self):
        """Prod-wide blast radius requires +20% confidence."""
        # 51 base + 20 = 71 required, 65 current = BLOCK
        state = MockSessionState(
            confidence=65,
            data={
                "mastermind_risk_signals": {
                    "blast_radius": "prod_wide",
                    "reversibility": "easy",
                }
            },
        )
        data = {"tool_name": "Edit", "tool_input": {}}

        result = check_blast_radius_gate(data, state)

        assert result.decision == "deny"

    def test_confidence_override_respected(self):
        """Explicit confidence_override is used instead of calculation."""
        # confidence_override=0.90 = 90% required, 85 current = BLOCK
        state = MockSessionState(
            confidence=85,
            data={
                "mastermind_risk_signals": {
                    "blast_radius": "local",
                    "reversibility": "easy",
                    "confidence_override": 0.90,
                }
            },
        )
        data = {"tool_name": "Edit", "tool_input": {}}

        result = check_blast_radius_gate(data, state)

        assert result.decision == "deny"
        assert "90%" in (result.reason or "")

    def test_risk_factors_shown_in_denial(self):
        """Risk factors are displayed in denial message."""
        state = MockSessionState(
            confidence=50,
            data={
                "mastermind_risk_signals": {
                    "blast_radius": "service",
                    "reversibility": "hard",
                    "risk_factors": ["database migration", "auth changes"],
                }
            },
        )
        data = {"tool_name": "Edit", "tool_input": {}}

        result = check_blast_radius_gate(data, state)

        assert result.decision == "deny"
        assert "database migration" in (result.reason or "")

    def test_margin_warning_when_close(self):
        """Warns when confidence margin is small."""
        # 51 base + 10 = 61 required, 63 current = APPROVE with warning
        state = MockSessionState(
            confidence=63,
            data={
                "mastermind_risk_signals": {
                    "blast_radius": "service",
                    "reversibility": "easy",
                }
            },
        )
        data = {"tool_name": "Edit", "tool_input": {}}

        result = check_blast_radius_gate(data, state)

        assert result.decision == "approve"
        assert "Margin: 2%" in (result.context or "")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
