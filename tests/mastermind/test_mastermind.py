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
from lib.mastermind.router_groq import (
    RouterResponse,
    apply_risk_lexicon,
    RiskSignals,
    SuccessCriteria,
    EscapeHatches,
)
from lib.mastermind.state import (
    RiskSignals as StateRiskSignals,
    SuccessCriteria as StateSuccessCriteria,
    EscapeHatches as StateEscapeHatches,
    RoutingDecision,
)
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
        # Prime cache with defaults (non-existent path = use defaults)
        clear_cache()
        load_config(
            Path("/nonexistent/path.json")
        )  # Sets cache with router.enabled=False
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


class TestPhase1Metadata:
    """Test Phase 1 metadata parsing (RiskSignals, SuccessCriteria, EscapeHatches)."""

    def test_risk_signals_dataclass(self):
        """Test RiskSignals dataclass from router_groq."""
        rs = RiskSignals(
            blast_radius="service",
            reversibility="hard",
            requires_review=True,
            confidence_override=0.85,
            risk_factors=["database migration", "auth changes"],
        )
        assert rs.blast_radius == "service"
        assert rs.reversibility == "hard"
        assert rs.requires_review is True
        assert rs.confidence_override == 0.85
        assert len(rs.risk_factors) == 2

    def test_success_criteria_dataclass(self):
        """Test SuccessCriteria dataclass from router_groq."""
        sc = SuccessCriteria(
            what_done_looks_like="All tests pass and feature works",
            verification_steps=["Run pytest", "Manual test"],
            acceptance_signals=["Green CI"],
            failure_signals=["TypeError", "Import error"],
        )
        assert "tests pass" in sc.what_done_looks_like
        assert len(sc.verification_steps) == 2

    def test_escape_hatches_dataclass(self):
        """Test EscapeHatches dataclass from router_groq."""
        eh = EscapeHatches(
            abort_conditions=["3 consecutive failures", "User says stop"],
            fallback_strategies=["Revert to main", "Ask for help"],
            escalation_path="User review",
            max_attempts=5,
        )
        assert len(eh.abort_conditions) == 2
        assert eh.max_attempts == 5

    def test_router_response_with_metadata(self):
        """Test RouterResponse with Phase 1 metadata fields."""
        rs = RiskSignals(blast_radius="module", reversibility="moderate")
        sc = SuccessCriteria(what_done_looks_like="Feature complete")
        eh = EscapeHatches(abort_conditions=["timeout"])

        resp = RouterResponse(
            classification="complex",
            confidence=0.85,
            reason_codes=["multi_file"],
            task_type="planning",
            latency_ms=100,
            raw_response="{}",
            risk_signals=rs,
            success_criteria=sc,
            escape_hatches=eh,
        )
        assert resp.risk_signals.blast_radius == "module"
        assert resp.success_criteria.what_done_looks_like == "Feature complete"
        assert resp.escape_hatches.abort_conditions == ["timeout"]

    def test_risk_lexicon_preserves_metadata(self):
        """Test that apply_risk_lexicon preserves Phase 1 metadata."""
        rs = RiskSignals(blast_radius="local", reversibility="easy")
        sc = SuccessCriteria(what_done_looks_like="Done")
        eh = EscapeHatches(abort_conditions=["fail"])

        resp = RouterResponse(
            classification="trivial",
            confidence=0.9,
            reason_codes=["simple"],
            task_type="general",
            latency_ms=50,
            raw_response="{}",
            risk_signals=rs,
            success_criteria=sc,
            escape_hatches=eh,
        )

        # Risk lexicon should escalate but preserve metadata
        overridden = apply_risk_lexicon("Add authentication to login", resp)
        assert overridden.classification == "complex"
        assert overridden.risk_signals is not None
        assert overridden.risk_signals.blast_radius == "local"
        assert overridden.success_criteria is not None
        assert overridden.escape_hatches is not None

    def test_state_risk_signals_serialization(self):
        """Test RiskSignals serialization in state module."""
        rs = StateRiskSignals(
            blast_radius="prod_wide",
            reversibility="irreversible",
            requires_review=True,
            risk_factors=["production database"],
        )
        d = rs.to_dict()
        assert d["blast_radius"] == "prod_wide"
        assert d["reversibility"] == "irreversible"

        # Round-trip
        rs2 = StateRiskSignals.from_dict(d)
        assert rs2.blast_radius == rs.blast_radius
        assert rs2.reversibility == rs.reversibility

    def test_routing_decision_with_metadata(self):
        """Test RoutingDecision with Phase 1 metadata."""
        rs = StateRiskSignals(blast_radius="service")
        sc = StateSuccessCriteria(what_done_looks_like="Deployed")
        eh = StateEscapeHatches(abort_conditions=["rollback needed"])

        rd = RoutingDecision(
            classification="complex",
            confidence=0.8,
            task_type="architecture",
            risk_signals=rs,
            success_criteria=sc,
            escape_hatches=eh,
        )

        # Serialize
        d = rd.to_dict()
        assert d["risk_signals"]["blast_radius"] == "service"
        assert d["success_criteria"]["what_done_looks_like"] == "Deployed"

        # Deserialize
        rd2 = RoutingDecision.from_dict(d)
        assert rd2.risk_signals.blast_radius == "service"
        assert rd2.success_criteria.what_done_looks_like == "Deployed"
        assert rd2.escape_hatches.abort_conditions == ["rollback needed"]

    def test_routing_decision_without_metadata(self):
        """Test RoutingDecision handles missing metadata gracefully."""
        rd = RoutingDecision(
            classification="trivial",
            confidence=0.95,
        )
        d = rd.to_dict()

        # Deserialize with None metadata
        rd2 = RoutingDecision.from_dict(d)
        assert rd2.risk_signals is None
        assert rd2.success_criteria is None
        assert rd2.escape_hatches is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
