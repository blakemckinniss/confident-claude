"""Mastermind session state management.

Persists routing decisions, blueprints, and escalation state across turns.
Stored per-project in .claude/mastermind_state.json or per-session.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

# Default location for session state
DEFAULT_STATE_DIR = Path.home() / ".claude" / "tmp" / "mastermind"


def _get_project_id() -> str:
    """Get current project ID for state isolation.

    Never returns 'ephemeral' - uses cwd-hash for isolation when
    no project markers are found.
    """
    import hashlib
    import os

    try:
        from project_detector import detect_project

        ctx = detect_project()

        if ctx and ctx.project_type != "ephemeral":
            return ctx.project_id

        # Ephemeral or no context: use cwd-hash isolation
        cwd = os.path.realpath(os.getcwd())
        cwd_hash = hashlib.sha256(cwd.encode()).hexdigest()[:12]
        return f"cwd_{cwd_hash}"

    except (ImportError, Exception):
        # Fallback: cwd-hash (never use global "ephemeral")
        cwd = os.path.realpath(os.getcwd())
        cwd_hash = hashlib.sha256(cwd.encode()).hexdigest()[:12]
        return f"cwd_{cwd_hash}"


@dataclass
class Blueprint:
    """GPT-5.2 generated execution blueprint."""

    goal: str = ""
    invariants: list[str] = field(default_factory=list)
    touch_set: list[str] = field(default_factory=list)
    budget: dict[str, Any] = field(default_factory=dict)
    decision_points: list[str] = field(default_factory=list)
    acceptance_criteria: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    epoch_id: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Blueprint:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class RiskSignals:
    """Phase 1 metadata: Risk assessment from Groq router."""

    blast_radius: str = "local"  # local, module, service, multi_service, prod_wide
    reversibility: str = "easy"  # easy, moderate, hard, irreversible
    requires_review: bool = False
    confidence_override: float | None = None
    risk_factors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RiskSignals:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class SuccessCriteria:
    """Phase 1 metadata: Success conditions from Groq router."""

    what_done_looks_like: str = ""
    verification_steps: list[str] = field(default_factory=list)
    acceptance_signals: list[str] = field(default_factory=list)
    failure_signals: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SuccessCriteria:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class EscapeHatches:
    """Phase 1 metadata: Fallback strategies from Groq router."""

    abort_conditions: list[str] = field(default_factory=list)
    fallback_strategies: list[str] = field(default_factory=list)
    escalation_path: str | None = None
    max_attempts: int = 3

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EscapeHatches:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class RoutingDecision:
    """Record of router classification."""

    classification: str = "trivial"  # trivial, medium, complex
    confidence: float = 0.0
    reason_codes: list[str] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)
    user_override: str | None = None  # "!" for skip, "^" for force
    task_type: str = "general"  # debugging, planning, review, architecture, etc.
    suggested_tool: str = "chat"  # Groq's suggested PAL tool
    mandates: list[dict] = field(default_factory=list)  # Mandatory tool directives
    mandate_policy: str = "strict"  # strict = enforce, lenient = warn
    # v4.34: Phase 1 metadata
    risk_signals: RiskSignals | None = None
    success_criteria: SuccessCriteria | None = None
    escape_hatches: EscapeHatches | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        # Serialize nested dataclasses
        if self.risk_signals:
            d["risk_signals"] = self.risk_signals.to_dict()
        if self.success_criteria:
            d["success_criteria"] = self.success_criteria.to_dict()
        if self.escape_hatches:
            d["escape_hatches"] = self.escape_hatches.to_dict()
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RoutingDecision:
        # Extract nested dataclass data before passing to constructor
        risk_signals = None
        success_criteria = None
        escape_hatches = None

        if data.get("risk_signals"):
            risk_signals = RiskSignals.from_dict(data["risk_signals"])
        if data.get("success_criteria"):
            success_criteria = SuccessCriteria.from_dict(data["success_criteria"])
        if data.get("escape_hatches"):
            escape_hatches = EscapeHatches.from_dict(data["escape_hatches"])

        # Filter to valid fields, excluding nested ones we handle specially
        filtered = {
            k: v
            for k, v in data.items()
            if k in cls.__dataclass_fields__
            and k not in ("risk_signals", "success_criteria", "escape_hatches")
        }

        return cls(
            **filtered,
            risk_signals=risk_signals,
            success_criteria=success_criteria,
            escape_hatches=escape_hatches,
        )


@dataclass
class EscalationRecord:
    """Record of a drift escalation event."""

    turn: int
    trigger: str  # file_count, test_failures, approach_change
    evidence: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EscalationRecord:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class MastermindState:
    """Complete mastermind session state."""

    session_id: str = ""
    turn_count: int = 0
    routing_decision: RoutingDecision | None = None
    blueprint: Blueprint | None = None
    continuation_id: str | None = None  # Legacy single continuation
    pal_continuations: dict[str, str] = field(
        default_factory=dict
    )  # Per-tool: {debug: "abc", planner: "def"}
    epoch_id: int = 0
    escalation_count: int = 0
    escalations: list[EscalationRecord] = field(default_factory=list)
    last_escalation_turn: int = -100
    files_modified: list[str] = field(default_factory=list)
    test_failures: int = 0
    pal_bootstrapped: bool = False  # True once PAL planner has been called
    pal_consulted: bool = (
        False  # True once ANY PAL tool has been called (hybrid routing)
    )
    recent_prompts: list[str] = field(
        default_factory=list
    )  # Last N user prompts for conversation context (max 5)
    # v4.33.1: Mandate persistence across session turns/compactions
    pending_mandates: list[dict] = field(default_factory=list)
    mandate_policy: str = "strict"  # strict = enforce, lenient = warn
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def can_escalate(self, cooldown_turns: int, max_escalations: int) -> bool:
        """Check if escalation is allowed (respecting cooldown and limits)."""
        if self.escalation_count >= max_escalations:
            return False
        if self.turn_count - self.last_escalation_turn < cooldown_turns:
            return False
        return True

    def record_escalation(self, trigger: str, evidence: dict[str, Any]) -> None:
        """Record an escalation event."""
        self.escalations.append(
            EscalationRecord(
                turn=self.turn_count,
                trigger=trigger,
                evidence=evidence,
            )
        )
        self.escalation_count += 1
        self.last_escalation_turn = self.turn_count
        self.epoch_id += 1
        self.updated_at = time.time()

    def record_file_modified(self, path: str) -> None:
        """Track a file modification."""
        if path not in self.files_modified:
            self.files_modified.append(path)
        self.updated_at = time.time()

    def increment_turn(self) -> None:
        """Increment turn counter."""
        self.turn_count += 1
        self.updated_at = time.time()

    def increment_test_failures(self, count: int = 1) -> None:
        """Increment test failure counter."""
        self.test_failures += count
        self.updated_at = time.time()

    def reset_test_failures(self) -> None:
        """Reset test failure counter (e.g., after tests pass)."""
        self.test_failures = 0
        self.updated_at = time.time()

    def mark_bootstrapped(self) -> None:
        """Mark session as bootstrapped (PAL planner has been called)."""
        self.pal_bootstrapped = True
        self.updated_at = time.time()

    def capture_pal_continuation(self, tool_type: str, continuation_id: str) -> None:
        """Capture continuation_id from a PAL tool response.

        Args:
            tool_type: PAL tool type (e.g., "debug", "planner", "chat")
            continuation_id: The continuation_id from PAL response
        """
        self.pal_continuations[tool_type] = continuation_id
        self.pal_consulted = True
        self.updated_at = time.time()

    def get_pal_continuation(self, tool_type: str) -> str | None:
        """Get stored continuation_id for a PAL tool type."""
        return self.pal_continuations.get(tool_type)

    def record_prompt(self, prompt: str, max_prompts: int = 5) -> None:
        """Record a user prompt for conversation context.

        Args:
            prompt: The user's prompt text
            max_prompts: Maximum number of prompts to retain (default 5)
        """
        self.recent_prompts.append(prompt)
        # Keep only the most recent N prompts
        if len(self.recent_prompts) > max_prompts:
            self.recent_prompts = self.recent_prompts[-max_prompts:]
        self.updated_at = time.time()

    # v4.33.1: Mandate persistence methods
    def set_mandates(self, mandates: list[dict], policy: str = "strict") -> None:
        """Set pending mandates from router decision.

        Args:
            mandates: List of mandate dicts from Groq router
            policy: Enforcement policy (strict/lenient)
        """
        self.pending_mandates = mandates
        self.mandate_policy = policy
        self.updated_at = time.time()

    def mark_mandate_satisfied(self, mandate_type: str, tool_name: str) -> bool:
        """Mark a mandate as satisfied by tool use.

        Args:
            mandate_type: The mandate type (pal, research, agent, etc.)
            tool_name: The tool that satisfied the mandate

        Returns:
            True if a mandate was marked satisfied, False otherwise
        """
        for m in self.pending_mandates:
            if m.get("type") == mandate_type and not m.get("satisfied"):
                m["satisfied"] = True
                m["satisfied_by"] = tool_name
                m["satisfied_at"] = time.time()
                self.updated_at = time.time()
                return True
        return False

    def get_unsatisfied_mandates(self, blocking_only: bool = False) -> list[dict]:
        """Get mandates that haven't been satisfied yet.

        Args:
            blocking_only: If True, only return blocking mandates
        """
        result = []
        for m in self.pending_mandates:
            if m.get("satisfied"):
                continue
            if blocking_only and not m.get("blocking"):
                continue
            result.append(m)
        return result

    def clear_mandates(self) -> None:
        """Clear all pending mandates (e.g., on new task)."""
        self.pending_mandates = []
        self.updated_at = time.time()

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "session_id": self.session_id,
            "turn_count": self.turn_count,
            "routing_decision": self.routing_decision.to_dict()
            if self.routing_decision
            else None,
            "blueprint": self.blueprint.to_dict() if self.blueprint else None,
            "continuation_id": self.continuation_id,
            "pal_continuations": self.pal_continuations,
            "epoch_id": self.epoch_id,
            "escalation_count": self.escalation_count,
            "escalations": [e.to_dict() for e in self.escalations],
            "last_escalation_turn": self.last_escalation_turn,
            "files_modified": self.files_modified,
            "test_failures": self.test_failures,
            "pal_bootstrapped": self.pal_bootstrapped,
            "pal_consulted": self.pal_consulted,
            "recent_prompts": self.recent_prompts,
            # v4.33.1: Mandate persistence
            "pending_mandates": self.pending_mandates,
            "mandate_policy": self.mandate_policy,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MastermindState:
        """Deserialize from dictionary."""
        state = cls(
            session_id=data.get("session_id", ""),
            turn_count=data.get("turn_count", 0),
            continuation_id=data.get("continuation_id"),
            pal_continuations=data.get("pal_continuations", {}),
            epoch_id=data.get("epoch_id", 0),
            escalation_count=data.get("escalation_count", 0),
            last_escalation_turn=data.get("last_escalation_turn", -100),
            files_modified=data.get("files_modified", []),
            test_failures=data.get("test_failures", 0),
            pal_bootstrapped=data.get("pal_bootstrapped", False),
            pal_consulted=data.get("pal_consulted", False),
            recent_prompts=data.get("recent_prompts", []),
            # v4.33.1: Mandate persistence
            pending_mandates=data.get("pending_mandates", []),
            mandate_policy=data.get("mandate_policy", "strict"),
            created_at=data.get("created_at", time.time()),
            updated_at=data.get("updated_at", time.time()),
        )

        if data.get("routing_decision"):
            state.routing_decision = RoutingDecision.from_dict(data["routing_decision"])
        if data.get("blueprint"):
            state.blueprint = Blueprint.from_dict(data["blueprint"])
        if data.get("escalations"):
            state.escalations = [
                EscalationRecord.from_dict(e) for e in data["escalations"]
            ]

        return state


def get_state_path(
    session_id: str,
    project_id: str | None = None,
    state_dir: Path | None = None,
) -> Path:
    """Get path for session state file with project isolation.

    New path structure: {state_dir}/{project_id}/{session_id}/state.json
    """
    directory = state_dir or DEFAULT_STATE_DIR
    proj_id = project_id or _get_project_id()

    # New isolated path: {dir}/{project_id}/{session_id}/state.json
    state_path = directory / proj_id / session_id
    state_path.mkdir(parents=True, exist_ok=True)
    return state_path / "state.json"


def load_state(
    session_id: str,
    project_id: str | None = None,
    state_dir: Path | None = None,
) -> MastermindState:
    """Load session state from disk with migration fallback.

    Tries new isolated path first, falls back to legacy path for migration.
    """
    # Try new isolated path first
    path = get_state_path(session_id, project_id, state_dir)

    if path.exists():
        try:
            with open(path) as f:
                data = json.load(f)
            return MastermindState.from_dict(data)
        except (json.JSONDecodeError, OSError):
            pass

    # Fallback: try legacy path (~/.claude/tmp/mastermind_{session_id}.json)
    legacy_dir = state_dir or Path.home() / ".claude" / "tmp"
    legacy_path = legacy_dir / f"mastermind_{session_id}.json"

    if legacy_path.exists():
        try:
            with open(legacy_path) as f:
                data = json.load(f)
            return MastermindState.from_dict(data)
        except (json.JSONDecodeError, OSError):
            pass

    return MastermindState(session_id=session_id)


def save_state(
    state: MastermindState,
    project_id: str | None = None,
    state_dir: Path | None = None,
) -> Path:
    """Save session state to disk with project isolation.

    Always writes to new isolated path structure.
    Uses file locking for concurrent session safety.
    """
    import fcntl

    path = get_state_path(state.session_id, project_id, state_dir)
    lock_path = path.with_suffix(".lock")
    state.updated_at = time.time()

    # Use file locking to prevent concurrent write corruption
    with open(lock_path, "w") as lock_file:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            # Another process holds the lock - wait for it
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)

        try:
            # Atomic write: write to temp file then rename
            tmp_path = path.with_suffix(".tmp")
            with open(tmp_path, "w") as f:
                json.dump(state.to_dict(), f, indent=2)
            tmp_path.rename(path)
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    return path


def clear_state(
    session_id: str,
    project_id: str | None = None,
    state_dir: Path | None = None,
) -> None:
    """Remove session state file."""
    path = get_state_path(session_id, project_id, state_dir)
    if path.exists():
        path.unlink()
