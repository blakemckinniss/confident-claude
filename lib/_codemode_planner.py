#!/usr/bin/env python3
"""
Code-Mode Plan Protocol (v1.0)

Generates structured tool execution plans for Claude to execute.
Since hooks cannot invoke MCP tools directly, code-mode generates plans
that Claude interprets and executes via actual tool calls.

Philosophy: https://ghuntley.com/ralph/
- Code-mode = plan generator, not executor
- Claude = plan executor with real MCP access
- Results flow back for next plan iteration

Protocol:
1. Hook generates plan JSON with tool calls
2. Claude executes tools in order
3. Results returned as structured JSON
4. Next hook cycle continues with results
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

# State persistence location
STATE_DIR = Path.home() / ".claude" / "tmp" / "codemode"
RUN_STATE_FILE = STATE_DIR / "run_state.json"


class PlanPhase(str, Enum):
    """Execution phases for the plan protocol."""

    NEED_SCHEMAS = "need_schemas"  # First run: need tool discovery
    NEED_TOOLS = "need_tools"  # Have schemas, generated tool plan
    HAVE_RESULTS = "have_results"  # Results received, can continue
    DONE = "done"  # Execution complete


@dataclass
class ToolCallSpec:
    """Specification for a single tool call in a plan."""

    id: str  # Unique ID for result correlation
    tool: str  # Full MCP tool name (e.g., mcp__serena__find_symbol)
    args: dict[str, Any]  # Tool arguments
    depends_on: list[str] = field(default_factory=list)  # IDs of calls this depends on
    description: str = ""  # Human-readable description

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "tool": self.tool,
            "args": self.args,
            "depends_on": self.depends_on,
            "description": self.description,
        }


@dataclass
class ExecutionPlan:
    """A structured plan for Claude to execute."""

    protocol_version: str = "mcp_tool_plan/v1"
    run_id: str = ""
    phase: PlanPhase = PlanPhase.NEED_TOOLS
    calls: list[ToolCallSpec] = field(default_factory=list)
    result_format: dict = field(default_factory=lambda: {"type": "json", "keyed_by": "id"})
    instructions: str = ""
    context: dict = field(default_factory=dict)  # For passing data between phases

    def to_dict(self) -> dict:
        return {
            "codemode_protocol": self.protocol_version,
            "run_id": self.run_id,
            "phase": self.phase.value,
            "calls": [c.to_dict() for c in self.calls],
            "result_format": self.result_format,
            "instructions": self.instructions,
            "context": self.context,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    def to_instruction_block(self) -> str:
        """Generate Claude-readable instruction block."""
        lines = [
            "## Code-Mode Execution Plan",
            "",
            f"**Run ID:** `{self.run_id}`",
            f"**Phase:** {self.phase.value}",
            "",
        ]

        if self.instructions:
            lines.extend(["### Instructions", self.instructions, ""])

        if self.calls:
            lines.extend(["### Tool Calls to Execute", ""])
            for i, call in enumerate(self.calls, 1):
                deps = f" (after: {', '.join(call.depends_on)})" if call.depends_on else ""
                lines.append(f"{i}. **{call.tool}**{deps}")
                if call.description:
                    lines.append(f"   - {call.description}")
                lines.append(f"   - Args: `{json.dumps(call.args)}`")
                lines.append(f"   - Result ID: `{call.id}`")
                lines.append("")

            lines.extend([
                "### Expected Response Format",
                "After executing all tools, respond with:",
                "```json",
                "{",
                '  "codemode_results": {',
                '    "<call_id>": { "success": true, "result": <tool_output> },',
                "    ...",
                "  }",
                "}",
                "```",
            ])

        return "\n".join(lines)


@dataclass
class RunState:
    """Persistent state for multi-turn execution."""

    run_id: str
    phase: PlanPhase
    pending_calls: list[str] = field(default_factory=list)  # IDs not yet executed
    completed_calls: dict[str, dict] = field(default_factory=dict)  # ID -> result
    context: dict = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "phase": self.phase.value,
            "pending_calls": self.pending_calls,
            "completed_calls": self.completed_calls,
            "context": self.context,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "RunState":
        return cls(
            run_id=data["run_id"],
            phase=PlanPhase(data["phase"]),
            pending_calls=data.get("pending_calls", []),
            completed_calls=data.get("completed_calls", {}),
            context=data.get("context", {}),
            created_at=data.get("created_at", time.time()),
            updated_at=data.get("updated_at", time.time()),
        )

    def save(self) -> None:
        """Persist state to disk."""
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        self.updated_at = time.time()
        # Atomic write
        tmp_file = RUN_STATE_FILE.with_suffix(".tmp")
        tmp_file.write_text(json.dumps(self.to_dict(), indent=2))
        tmp_file.rename(RUN_STATE_FILE)

    @classmethod
    def load(cls) -> "RunState | None":
        """Load state from disk if exists."""
        if not RUN_STATE_FILE.exists():
            return None
        try:
            data = json.loads(RUN_STATE_FILE.read_text())
            return cls.from_dict(data)
        except (json.JSONDecodeError, KeyError, OSError):
            return None

    @classmethod
    def clear(cls) -> None:
        """Clear persisted state."""
        if RUN_STATE_FILE.exists():
            RUN_STATE_FILE.unlink()


def generate_run_id() -> str:
    """Generate unique run ID based on timestamp."""
    return f"cm-{int(time.time() * 1000) % 1000000:06d}"


def generate_call_id(tool: str, index: int) -> str:
    """Generate unique call ID."""
    tool_short = tool.split("__")[-1][:10]
    return f"{tool_short}-{index:02d}"


class CodeModePlanner:
    """
    Generates execution plans for code-mode.

    Instead of executing tools directly, generates structured plans
    that Claude interprets and executes via MCP.
    """

    def __init__(self, tool_schemas: dict[str, dict] | None = None):
        """
        Initialize planner with optional tool schemas.

        Args:
            tool_schemas: Dict mapping tool names to their schemas.
                         If None, will request schema discovery on first plan.
        """
        self.tool_schemas = tool_schemas or {}
        self.run_state: RunState | None = None

    def needs_schema_discovery(self) -> bool:
        """Check if we need to discover tool schemas first."""
        return len(self.tool_schemas) == 0

    def create_schema_discovery_plan(self) -> ExecutionPlan:
        """Generate a plan to discover available MCP tools."""
        run_id = generate_run_id()

        self.run_state = RunState(
            run_id=run_id,
            phase=PlanPhase.NEED_SCHEMAS,
            pending_calls=["discover-01"],
        )
        self.run_state.save()

        return ExecutionPlan(
            run_id=run_id,
            phase=PlanPhase.NEED_SCHEMAS,
            calls=[],  # No specific calls - Claude lists available tools
            instructions=(
                "List all available MCP tools with their schemas.\n"
                "Use the tool listing capability to discover what tools are available.\n"
                "Return the tool names and their parameter schemas."
            ),
        )

    def create_tool_plan(
        self,
        tool_calls: list[tuple[str, dict]],
        context: dict | None = None,
    ) -> ExecutionPlan:
        """
        Generate an execution plan from a list of tool calls.

        Args:
            tool_calls: List of (tool_name, args) tuples
            context: Optional context to pass between phases

        Returns:
            ExecutionPlan for Claude to execute
        """
        run_id = generate_run_id()
        calls = []

        for i, (tool, args) in enumerate(tool_calls):
            call_id = generate_call_id(tool, i)
            # Get description from schema if available
            desc = ""
            if tool in self.tool_schemas:
                desc = self.tool_schemas[tool].get("description", "")[:100]

            calls.append(
                ToolCallSpec(
                    id=call_id,
                    tool=tool,
                    args=args,
                    description=desc,
                )
            )

        self.run_state = RunState(
            run_id=run_id,
            phase=PlanPhase.NEED_TOOLS,
            pending_calls=[c.id for c in calls],
            context=context or {},
        )
        self.run_state.save()

        return ExecutionPlan(
            run_id=run_id,
            phase=PlanPhase.NEED_TOOLS,
            calls=calls,
            context=context or {},
            instructions="Execute the following tool calls in order and return results.",
        )

    def process_results(self, results: dict[str, dict]) -> RunState:
        """
        Process results from Claude's tool execution.

        Args:
            results: Dict mapping call IDs to their results

        Returns:
            Updated run state
        """
        if self.run_state is None:
            self.run_state = RunState.load()

        if self.run_state is None:
            raise ValueError("No active run state found")

        # Update completed calls
        for call_id, result in results.items():
            if call_id in self.run_state.pending_calls:
                self.run_state.pending_calls.remove(call_id)
            self.run_state.completed_calls[call_id] = result

        # Update phase
        if not self.run_state.pending_calls:
            self.run_state.phase = PlanPhase.HAVE_RESULTS

        self.run_state.save()
        return self.run_state

    def is_complete(self) -> bool:
        """Check if execution is complete."""
        if self.run_state is None:
            return False
        return self.run_state.phase == PlanPhase.DONE

    def mark_complete(self) -> None:
        """Mark execution as complete and clean up state."""
        if self.run_state:
            self.run_state.phase = PlanPhase.DONE
            self.run_state.save()
        RunState.clear()


def parse_codemode_results(response: str) -> dict[str, dict] | None:
    """
    Parse codemode results from Claude's response.

    Looks for JSON block with codemode_results key.
    """
    import re

    # Try to find JSON block
    json_match = re.search(r"```json\s*(\{.*?\})\s*```", response, re.DOTALL)
    if json_match:
        try:
            data = json.loads(json_match.group(1))
            if "codemode_results" in data:
                return data["codemode_results"]
        except json.JSONDecodeError:
            pass

    # Try direct JSON parse
    try:
        data = json.loads(response)
        if "codemode_results" in data:
            return data["codemode_results"]
    except json.JSONDecodeError:
        pass

    return None


# Convenience function for hook integration
def generate_plan_from_code(
    code: str,
    tool_schemas: dict[str, dict],
) -> ExecutionPlan | None:
    """
    Analyze Python code and generate an execution plan.

    This is a static analysis approach - parses the code to find
    tool calls without executing it.

    Args:
        code: Python code with tool calls like serena.find_symbol(...)
        tool_schemas: Available tool schemas

    Returns:
        ExecutionPlan if tool calls found, None otherwise
    """
    import ast

    try:
        tree = ast.parse(code)
    except SyntaxError:
        return None

    # Find all tool call expressions
    tool_calls: list[tuple[str, dict]] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute):
                if isinstance(node.func.value, ast.Name):
                    namespace = node.func.value.id
                    method = node.func.attr

                    # Convert to full tool name
                    full_name = f"mcp__{namespace}__{method}"

                    # Try to extract literal arguments
                    args = {}
                    for kw in node.keywords:
                        if kw.arg and isinstance(kw.value, ast.Constant):
                            args[kw.arg] = kw.value.value

                    # Check if this is a known tool
                    if full_name in tool_schemas:
                        tool_calls.append((full_name, args))

    if not tool_calls:
        return None

    planner = CodeModePlanner(tool_schemas)
    return planner.create_tool_plan(tool_calls)


# For direct testing
if __name__ == "__main__":
    # Create a sample plan
    planner = CodeModePlanner({
        "mcp__serena__find_symbol": {
            "description": "Find symbols matching pattern",
        },
        "mcp__serena__get_symbols_overview": {
            "description": "Get overview of symbols in file",
        },
    })

    plan = planner.create_tool_plan([
        ("mcp__serena__find_symbol", {"name_path_pattern": "CodeModePlanner"}),
        ("mcp__serena__get_symbols_overview", {"relative_path": "lib/test.py"}),
    ])

    print("=== Plan JSON ===")
    print(plan.to_json())
    print()
    print("=== Instruction Block ===")
    print(plan.to_instruction_block())
