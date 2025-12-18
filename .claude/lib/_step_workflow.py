#!/usr/bin/env python3
"""
Step-Based Workflow System - BMAD-inspired multi-session continuity.

Enables complex operations to be paused and resumed across sessions by
tracking workflow state in a persistent format.

Key concepts (from BMAD-METHOD):
- Steps: Discrete units of work with clear completion criteria
- Frontmatter-style state: steps_completed array tracks progress
- Resume detection: Automatically detect and continue from last step
- Branching: Support alternative paths when decisions needed

Usage:
    workflow = StepWorkflow.create("migration", total_steps=5)
    workflow.start_step(1, "Analyze current schema")
    # ... do work ...
    workflow.complete_step(1, findings={"tables": 12})
    workflow.save()

Resume:
    workflow = StepWorkflow.load("migration")
    if workflow:
        next_step = workflow.get_resume_point()
        # Continue from next_step
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional, Any

# Storage location for workflow state
WORKFLOW_DIR = Path.home() / ".claude" / "tmp" / "workflows"


@dataclass
class StepState:
    """State of a single workflow step."""

    number: int
    title: str
    status: str = "pending"  # pending, in_progress, completed, skipped, blocked
    started_at: float = 0.0
    completed_at: float = 0.0
    findings: dict = field(default_factory=dict)
    blockers: list[str] = field(default_factory=list)
    branch_id: Optional[str] = None  # For alternative paths


@dataclass
class WorkflowState:
    """Persistent state for a multi-step workflow."""

    workflow_id: str
    name: str
    total_steps: int
    current_step: int = 0
    steps_completed: list[int] = field(default_factory=list)
    steps: dict[int, StepState] = field(default_factory=dict)

    # Metadata
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    session_id: str = ""

    # Context preservation
    goal: str = ""
    context: dict = field(default_factory=dict)
    decisions: list[dict] = field(default_factory=list)

    # Branching support
    active_branch: Optional[str] = None
    branches: dict[str, list[int]] = field(default_factory=dict)


class StepWorkflow:
    """
    Multi-step workflow with session continuity.

    Inspired by BMAD-METHOD's step-file architecture where:
    - step-01-init.md checks if workflow exists
    - step-01b-continue.md resumes from stepsCompleted
    - Each step has clear entry/exit criteria
    """

    def __init__(self, state: WorkflowState):
        self.state = state
        self._dirty = False

    @classmethod
    def create(
        cls,
        name: str,
        total_steps: int,
        goal: str = "",
        context: Optional[dict] = None,
    ) -> "StepWorkflow":
        """Create a new workflow."""
        workflow_id = f"wf_{name}_{int(time.time())}"

        state = WorkflowState(
            workflow_id=workflow_id,
            name=name,
            total_steps=total_steps,
            goal=goal,
            context=context or {},
        )

        # Initialize step states
        for i in range(1, total_steps + 1):
            state.steps[i] = StepState(number=i, title=f"Step {i}")

        workflow = cls(state)
        workflow._dirty = True
        return workflow

    @classmethod
    def load(cls, name: str) -> Optional["StepWorkflow"]:
        """Load an existing workflow by name (most recent)."""
        WORKFLOW_DIR.mkdir(parents=True, exist_ok=True)

        # Find most recent workflow with this name
        matches = sorted(
            WORKFLOW_DIR.glob(f"wf_{name}_*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )

        if not matches:
            return None

        try:
            data = json.loads(matches[0].read_text())

            # Reconstruct state
            state = WorkflowState(
                workflow_id=data["workflow_id"],
                name=data["name"],
                total_steps=data["total_steps"],
                current_step=data.get("current_step", 0),
                steps_completed=data.get("steps_completed", []),
                created_at=data.get("created_at", time.time()),
                updated_at=data.get("updated_at", time.time()),
                session_id=data.get("session_id", ""),
                goal=data.get("goal", ""),
                context=data.get("context", {}),
                decisions=data.get("decisions", []),
                active_branch=data.get("active_branch"),
                branches=data.get("branches", {}),
            )

            # Reconstruct steps
            for num_str, step_data in data.get("steps", {}).items():
                num = int(num_str)
                state.steps[num] = StepState(
                    number=num,
                    title=step_data.get("title", f"Step {num}"),
                    status=step_data.get("status", "pending"),
                    started_at=step_data.get("started_at", 0.0),
                    completed_at=step_data.get("completed_at", 0.0),
                    findings=step_data.get("findings", {}),
                    blockers=step_data.get("blockers", []),
                    branch_id=step_data.get("branch_id"),
                )

            return cls(state)
        except (json.JSONDecodeError, KeyError, OSError):
            return None

    @classmethod
    def load_by_id(cls, workflow_id: str) -> Optional["StepWorkflow"]:
        """Load workflow by exact ID."""
        path = WORKFLOW_DIR / f"{workflow_id}.json"
        if not path.exists():
            return None

        try:
            data = json.loads(path.read_text())
            # Same reconstruction as load()
            state = WorkflowState(
                workflow_id=data["workflow_id"],
                name=data["name"],
                total_steps=data["total_steps"],
                current_step=data.get("current_step", 0),
                steps_completed=data.get("steps_completed", []),
                created_at=data.get("created_at", time.time()),
                updated_at=data.get("updated_at", time.time()),
                session_id=data.get("session_id", ""),
                goal=data.get("goal", ""),
                context=data.get("context", {}),
                decisions=data.get("decisions", []),
                active_branch=data.get("active_branch"),
                branches=data.get("branches", {}),
            )

            for num_str, step_data in data.get("steps", {}).items():
                num = int(num_str)
                state.steps[num] = StepState(
                    number=num,
                    title=step_data.get("title", f"Step {num}"),
                    status=step_data.get("status", "pending"),
                    started_at=step_data.get("started_at", 0.0),
                    completed_at=step_data.get("completed_at", 0.0),
                    findings=step_data.get("findings", {}),
                    blockers=step_data.get("blockers", []),
                    branch_id=step_data.get("branch_id"),
                )

            return cls(state)
        except (json.JSONDecodeError, KeyError, OSError):
            return None

    def save(self) -> Path:
        """Persist workflow state to disk."""
        WORKFLOW_DIR.mkdir(parents=True, exist_ok=True)

        self.state.updated_at = time.time()

        # Convert to serializable format
        data = {
            "workflow_id": self.state.workflow_id,
            "name": self.state.name,
            "total_steps": self.state.total_steps,
            "current_step": self.state.current_step,
            "steps_completed": self.state.steps_completed,
            "created_at": self.state.created_at,
            "updated_at": self.state.updated_at,
            "session_id": self.state.session_id,
            "goal": self.state.goal,
            "context": self.state.context,
            "decisions": self.state.decisions,
            "active_branch": self.state.active_branch,
            "branches": self.state.branches,
            "steps": {str(num): asdict(step) for num, step in self.state.steps.items()},
        }

        path = WORKFLOW_DIR / f"{self.state.workflow_id}.json"
        path.write_text(json.dumps(data, indent=2))
        self._dirty = False
        return path

    def define_step(self, number: int, title: str) -> None:
        """Define or update a step's title."""
        if number not in self.state.steps:
            self.state.steps[number] = StepState(number=number, title=title)
        else:
            self.state.steps[number].title = title
        self._dirty = True

    def start_step(self, number: int, title: Optional[str] = None) -> StepState:
        """Mark a step as in progress."""
        if number not in self.state.steps:
            self.state.steps[number] = StepState(
                number=number,
                title=title or f"Step {number}",
            )

        step = self.state.steps[number]
        step.status = "in_progress"
        step.started_at = time.time()
        if title:
            step.title = title

        self.state.current_step = number
        self._dirty = True
        return step

    def complete_step(
        self,
        number: int,
        findings: Optional[dict] = None,
        decision: Optional[str] = None,
    ) -> None:
        """Mark a step as completed with optional findings."""
        if number not in self.state.steps:
            return

        step = self.state.steps[number]
        step.status = "completed"
        step.completed_at = time.time()
        if findings:
            step.findings.update(findings)

        if number not in self.state.steps_completed:
            self.state.steps_completed.append(number)
            self.state.steps_completed.sort()

        if decision:
            self.state.decisions.append(
                {
                    "step": number,
                    "decision": decision,
                    "timestamp": time.time(),
                }
            )

        self._dirty = True

    def block_step(self, number: int, reason: str) -> None:
        """Mark a step as blocked."""
        if number not in self.state.steps:
            return

        step = self.state.steps[number]
        step.status = "blocked"
        step.blockers.append(reason)
        self._dirty = True

    def skip_step(self, number: int, reason: str = "") -> None:
        """Skip a step (mark as not needed)."""
        if number not in self.state.steps:
            return

        step = self.state.steps[number]
        step.status = "skipped"
        if reason:
            step.findings["skip_reason"] = reason

        if number not in self.state.steps_completed:
            self.state.steps_completed.append(number)
            self.state.steps_completed.sort()

        self._dirty = True

    def get_resume_point(self) -> int:
        """
        Determine which step to resume from.

        BMAD pattern: Check stepsCompleted array, find first incomplete step.
        """
        for i in range(1, self.state.total_steps + 1):
            if i not in self.state.steps_completed:
                return i
        return self.state.total_steps  # All done

    def is_complete(self) -> bool:
        """Check if all steps are completed."""
        return len(self.state.steps_completed) >= self.state.total_steps

    def get_progress_summary(self) -> str:
        """Get human-readable progress summary."""
        completed = len(self.state.steps_completed)
        total = self.state.total_steps
        pct = (completed / total * 100) if total > 0 else 0

        lines = [
            f"**{self.state.name}** ({completed}/{total} steps, {pct:.0f}%)",
            f"Goal: {self.state.goal}" if self.state.goal else "",
        ]

        for i in range(1, total + 1):
            step = self.state.steps.get(i)
            if step:
                icon = {
                    "pending": "⬜",
                    "in_progress": "🔄",
                    "completed": "✅",
                    "skipped": "⏭️",
                    "blocked": "🚫",
                }.get(step.status, "⬜")
                lines.append(f"  {icon} Step {i}: {step.title}")

        return "\n".join(filter(None, lines))

    def create_branch(self, branch_id: str, from_step: int) -> None:
        """Create a branch point for alternative paths."""
        self.state.branches[branch_id] = [from_step]
        self._dirty = True

    def switch_branch(self, branch_id: str) -> None:
        """Switch to an alternative branch."""
        if branch_id in self.state.branches:
            self.state.active_branch = branch_id
            self._dirty = True

    def add_context(self, key: str, value: Any) -> None:
        """Store context for future sessions."""
        self.state.context[key] = value
        self._dirty = True

    def get_context(self, key: str, default: Any = None) -> Any:
        """Retrieve stored context."""
        return self.state.context.get(key, default)


def list_workflows(name_filter: Optional[str] = None) -> list[dict]:
    """List all workflows, optionally filtered by name."""
    WORKFLOW_DIR.mkdir(parents=True, exist_ok=True)

    pattern = f"wf_{name_filter}_*.json" if name_filter else "wf_*.json"
    workflows = []

    for path in WORKFLOW_DIR.glob(pattern):
        try:
            data = json.loads(path.read_text())
            workflows.append(
                {
                    "id": data["workflow_id"],
                    "name": data["name"],
                    "progress": f"{len(data.get('steps_completed', []))}/{data['total_steps']}",
                    "updated": data.get("updated_at", 0),
                    "goal": data.get("goal", "")[:50],
                }
            )
        except (json.JSONDecodeError, KeyError):
            continue

    return sorted(workflows, key=lambda w: w["updated"], reverse=True)


def cleanup_old_workflows(max_age_days: int = 7) -> int:
    """Remove workflows older than max_age_days."""
    WORKFLOW_DIR.mkdir(parents=True, exist_ok=True)

    cutoff = time.time() - (max_age_days * 86400)
    removed = 0

    for path in WORKFLOW_DIR.glob("wf_*.json"):
        try:
            data = json.loads(path.read_text())
            if data.get("updated_at", 0) < cutoff:
                path.unlink()
                removed += 1
        except (json.JSONDecodeError, OSError):
            continue

    return removed
