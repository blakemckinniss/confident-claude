"""End-to-end tests for mastermind architecture.

Tests scenarios:
1. Trivial prompt executes directly (no planner)
2. Complex prompt triggers blueprint
3. Mid-session drift fires escalation
4. Loop guards prevent pathological re-escalation
"""

import sys
from pathlib import Path

# Add lib to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pytest
from lib.mastermind.config import load_config, MastermindConfig, clear_cache
from lib.mastermind.state import MastermindState
from lib.mastermind.routing import parse_user_override, make_routing_decision
from lib.mastermind.router_groq import RouterResponse, apply_risk_lexicon
from lib.mastermind.context_packer import pack_for_router, pack_for_planner
from lib.mastermind.drift import evaluate_drift
from lib.mastermind.redaction import redact_text, is_safe_to_send


class TestConfig:
    """Test configuration loading."""

    def test_load_defaults(self):
        clear_cache()
        config = load_config(Path("/nonexistent/path.json"))
        assert config.rollout_phase == 0
        assert config.router.enabled is False
        assert config.planner.model == "auto"  # PAL auto-selects model

    def test_phase_name(self):
        config = MastermindConfig(rollout_phase=0)
        assert config.phase_name == "dark_launch"


class TestRouting:
    """Test routing decision logic."""

    def test_user_skip_override(self):
        prompt, override = parse_user_override("! just do it")
        assert prompt == "just do it"
        assert override == "!"

    def test_user_force_override(self):
        prompt, override = parse_user_override("^ complex task")
        assert prompt == "complex task"
        assert override == "^"

    def test_no_override(self):
        prompt, override = parse_user_override("normal prompt")
        assert prompt == "normal prompt"
        assert override is None

    def test_routing_disabled_by_default(self):
        policy = make_routing_decision("test", turn_count=0)
        assert policy.should_route is False
        assert policy.reason == "routing_disabled"


class TestRiskLexicon:
    """Test risk lexicon overrides."""

    def test_security_keyword_escalates(self):
        resp = RouterResponse("trivial", 0.9, ["single_file"], "", 100)
        overridden = apply_risk_lexicon("Add authentication to login", resp)
        assert overridden.classification == "complex"
        assert "risk_lexicon_override" in overridden.reason_codes

    def test_safe_prompt_unchanged(self):
        resp = RouterResponse("trivial", 0.9, ["single_file"], "", 100)
        result = apply_risk_lexicon("Fix typo in README", resp)
        assert result.classification == "trivial"


class TestContextPacker:
    """Test context packing."""

    def test_router_budget(self):
        ctx = pack_for_router("Simple question")
        assert ctx.token_estimate <= ctx.budget
        assert ctx.budget == 1200

    def test_planner_budget(self):
        ctx = pack_for_planner(
            "Complex task",
            {"classification": "complex", "reason_codes": ["multi_file"]},
        )
        assert ctx.token_estimate <= ctx.budget
        assert ctx.budget == 4000


class TestDrift:
    """Test drift detection."""

    def test_no_drift_when_disabled(self):
        state = MastermindState(session_id="test")
        state.files_modified = ["a.py", "b.py", "c.py", "d.py", "e.py", "f.py"]
        signals = evaluate_drift(state)
        assert len(signals) == 0  # Disabled by default

    def test_escalation_respects_cooldown(self):
        state = MastermindState(session_id="test", turn_count=5)
        state.last_escalation_turn = 3
        assert state.can_escalate(cooldown_turns=8, max_escalations=3) is False

    def test_escalation_respects_max(self):
        state = MastermindState(session_id="test", escalation_count=3)
        assert state.can_escalate(cooldown_turns=1, max_escalations=3) is False


class TestRedaction:
    """Test secret redaction."""

    def test_api_key_redacted(self):
        text = "API_KEY=sk-abc123456789012345678901234567890"
        redacted, types = redact_text(text)
        assert "sk-" not in redacted
        assert "REDACTED" in redacted

    def test_safe_text_passes(self):
        safe, _ = is_safe_to_send("This is normal text")
        assert safe is True

    def test_github_token_detected(self):
        # ghp_ tokens require 36 alphanumeric chars after prefix
        safe, detected = is_safe_to_send(
            "Token: ghp_abcdefghijklmnopqrstuvwxyz1234567890"
        )
        assert safe is False
        assert "github_token" in detected


class TestState:
    """Test state management."""

    def test_turn_increment(self):
        state = MastermindState(session_id="test")
        assert state.turn_count == 0
        state.increment_turn()
        assert state.turn_count == 1

    def test_file_tracking(self):
        state = MastermindState(session_id="test")
        state.record_file_modified("a.py")
        state.record_file_modified("b.py")
        state.record_file_modified("a.py")  # Duplicate
        assert len(state.files_modified) == 2

    def test_escalation_recording(self):
        state = MastermindState(session_id="test", turn_count=5)
        state.record_escalation("file_count", {"files": 10})
        assert state.escalation_count == 1
        assert state.last_escalation_turn == 5
        assert state.epoch_id == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
