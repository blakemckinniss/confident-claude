"""Mandate evaluation and tracking for Groq router directives.

Mandates are HARD requirements from Groq that Claude MUST follow.
Unlike suggestions, these are not advisory - they are authoritative.

Mandate Types:
- pal: Specific PAL tool (debug, thinkdeep, consensus, clink, etc.)
- research: Web research (crawl4ai, WebSearch, apilookup)
- agent: Task agent delegation (Explore, Plan, debugger, etc.)
- bead: Task tracking (create/claim bead)
- ask_user: User clarification (AskUserQuestion)
- plan_mode: Enter plan mode for approval
- project_research: Deep codebase research (serena, grep, glob)
- script: Orchestration script creation (tmp/*.py)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal
from enum import Enum


class MandateType(str, Enum):
    """Types of mandates Groq can issue."""

    PAL = "pal"
    RESEARCH = "research"
    AGENT = "agent"
    SCRIPT = "script"
    BEAD = "bead"
    ASK_USER = "ask_user"
    PLAN_MODE = "plan_mode"
    PROJECT_RESEARCH = "project_research"


@dataclass
class Mandate:
    """A single mandate from Groq router."""

    type: str  # MandateType value
    reason: str
    priority: Literal["p0", "p1", "p2"] = "p1"
    blocking: bool = True
    satisfied: bool = False
    satisfied_by: str | None = None  # Tool that satisfied it

    # Type-specific fields
    tool: str | None = None  # For pal, research (e.g., "mcp__pal__debug")
    query: str | None = None  # For research (search query)
    subagent: str | None = None  # For agent (e.g., "Explore", "debugger")
    scope: str | None = None  # For agent, project_research (what to look for)
    questions: list[str] = field(default_factory=list)  # For ask_user
    action: str | None = None  # For bead (create/claim)

    @classmethod
    def from_dict(cls, data: dict) -> Mandate:
        """Create Mandate from router response dict."""
        return cls(
            type=data.get("type", "pal"),
            reason=data.get("reason", "Required by router"),
            priority=data.get("priority", "p1"),
            blocking=data.get("blocking", True),
            satisfied=data.get("satisfied", False),
            satisfied_by=data.get("satisfied_by"),
            tool=data.get("tool"),
            query=data.get("query"),
            subagent=data.get("subagent"),
            scope=data.get("scope"),
            questions=data.get("questions", []),
            action=data.get("action"),
        )

    def to_dict(self) -> dict:
        """Serialize to dict for state persistence."""
        return {
            "type": self.type,
            "reason": self.reason,
            "priority": self.priority,
            "blocking": self.blocking,
            "satisfied": self.satisfied,
            "satisfied_by": self.satisfied_by,
            "tool": self.tool,
            "query": self.query,
            "subagent": self.subagent,
            "scope": self.scope,
            "questions": self.questions,
            "action": self.action,
        }


# Tool patterns that satisfy each mandate type
SATISFACTION_PATTERNS: dict[str, list[str]] = {
    "pal": ["mcp__pal__"],
    "research": [
        "mcp__crawl4ai__",
        "WebSearch",
        "WebFetch",
        "mcp__pal__apilookup",
    ],
    "agent": ["Task"],
    "script": ["Write"],  # Must also check path is tmp/*.py
    "bead": [
        "mcp__beads__create",
        "mcp__beads__update",
    ],
    "ask_user": ["AskUserQuestion"],
    "plan_mode": ["EnterPlanMode"],
    "project_research": [
        "mcp__serena__find",
        "mcp__serena__get",
        "mcp__serena__search",
        "mcp__serena__list",
        "Grep",
        "Glob",
        "Task",  # Explore agent
    ],
}


def check_mandate_satisfaction(
    mandate: Mandate | dict,
    tool_name: str,
    tool_input: dict,
) -> bool:
    """Check if a tool use satisfies a mandate.

    Args:
        mandate: Mandate object or dict from router
        tool_name: Name of tool being used
        tool_input: Tool input parameters

    Returns:
        True if the tool satisfies this mandate
    """
    if isinstance(mandate, dict):
        mandate = Mandate.from_dict(mandate)

    if mandate.satisfied:
        return False  # Already satisfied

    mtype = mandate.type
    patterns = SATISFACTION_PATTERNS.get(mtype, [])

    for pattern in patterns:
        if pattern in tool_name:
            # Type-specific validation
            if mtype == "pal" and mandate.tool:
                # Must match specific PAL tool
                if mandate.tool not in tool_name:
                    # Allow shorthand: "debug" matches "mcp__pal__debug"
                    if f"mcp__pal__{mandate.tool}" not in tool_name:
                        continue

            if mtype == "agent" and mandate.subagent:
                # Must match specific subagent
                subagent_type = tool_input.get("subagent_type", "")
                if subagent_type.lower() != mandate.subagent.lower():
                    continue

            if mtype == "script":
                # Must be writing to tmp/
                path = tool_input.get("file_path", "")
                if "/.claude/tmp/" not in path:
                    continue
                if not path.endswith(".py"):
                    continue

            if mtype == "project_research" and tool_name == "Task":
                # Must be exploration-type agent
                subagent = tool_input.get("subagent_type", "").lower()
                if subagent not in ("explore", "scout", "researcher"):
                    continue

            return True

    return False


def get_unsatisfied_blocking(mandates: list[Mandate | dict]) -> list[Mandate]:
    """Get mandates that block progress.

    Args:
        mandates: List of Mandate objects or dicts

    Returns:
        List of unsatisfied blocking mandates
    """
    result = []
    for m in mandates:
        if isinstance(m, dict):
            m = Mandate.from_dict(m)
        if m.blocking and not m.satisfied:
            result.append(m)
    return result


def get_unsatisfied_all(mandates: list[Mandate | dict]) -> list[Mandate]:
    """Get all unsatisfied mandates (blocking and non-blocking).

    Args:
        mandates: List of Mandate objects or dicts

    Returns:
        List of all unsatisfied mandates
    """
    result = []
    for m in mandates:
        if isinstance(m, dict):
            m = Mandate.from_dict(m)
        if not m.satisfied:
            result.append(m)
    return result


def format_mandate_checklist(mandates: list[Mandate | dict]) -> str:
    """Format mandates as injection checklist for prompt.

    Args:
        mandates: List of Mandate objects or dicts

    Returns:
        Formatted markdown checklist
    """
    if not mandates:
        return ""

    # Convert dicts to Mandate objects
    mandate_objs = [
        Mandate.from_dict(m) if isinstance(m, dict) else m for m in mandates
    ]

    lines = ["## 🚨 MANDATORY ACTIONS (Groq Router Directives)"]
    lines.append("**You MUST complete these before proceeding. Non-negotiable.**\n")

    blocking = [m for m in mandate_objs if m.blocking]
    optional = [m for m in mandate_objs if not m.blocking]

    if blocking:
        lines.append("### 🔴 BLOCKING (Must complete first)")
        for m in blocking:
            status = "✅" if m.satisfied else "⬜"
            icon = {"p0": "🔴", "p1": "🟡", "p2": "🔵"}.get(m.priority, "🟡")
            tool_hint = _format_tool_hint(m)
            lines.append(f"- {status} {icon} **{m.type.upper()}**: {m.reason}")
            if tool_hint:
                lines.append(f"  → Use: `{tool_hint}`")

    if optional:
        lines.append("\n### 🟡 RECOMMENDED (Complete when appropriate)")
        for m in optional:
            status = "✅" if m.satisfied else "⬜"
            tool_hint = _format_tool_hint(m)
            lines.append(f"- {status} **{m.type}**: {m.reason}")
            if tool_hint:
                lines.append(f"  → Use: `{tool_hint}`")

    return "\n".join(lines)


def _format_tool_hint(m: Mandate) -> str:
    """Format tool usage hint for a mandate."""
    if m.type == "pal":
        tool = m.tool or "mcp__pal__chat"
        if not tool.startswith("mcp__"):
            tool = f"mcp__pal__{tool}"
        return tool

    if m.type == "research":
        tool = m.tool or "mcp__crawl4ai__ddg_search"
        if m.query:
            return f'{tool}(query="{m.query}")'
        return tool

    if m.type == "agent":
        subagent = m.subagent or "Explore"
        if m.scope:
            return f'Task(subagent_type="{subagent}", prompt="{m.scope}...")'
        return f'Task(subagent_type="{subagent}")'

    if m.type == "bead":
        action = m.action or "create"
        if action == "create":
            return 'mcp__beads__create_bead(title="...")'
        return 'mcp__beads__update_bead(status="in_progress")'

    if m.type == "ask_user":
        if m.questions:
            return f'AskUserQuestion(questions=["{m.questions[0]}..."])'
        return "AskUserQuestion"

    if m.type == "plan_mode":
        return "EnterPlanMode"

    if m.type == "project_research":
        if m.scope:
            return f'Task(subagent_type="Explore", prompt="{m.scope}...")'
        return "mcp__serena__* or Task(Explore)"

    if m.type == "script":
        return 'Write(file_path="~/.claude/tmp/<task>.py")'

    return m.type


# System prompt addition for Groq router
MANDATE_SYSTEM_PROMPT = """
## MANDATORY TOOL DIRECTIVES

You MUST generate a `mandates` array specifying tools Claude MUST use. These are NOT suggestions - they are requirements that will be ENFORCED.

### Mandate Schema
{
  "mandates": [
    {
      "type": "pal|research|agent|bead|ask_user|plan_mode|project_research|script",
      "tool": "mcp__pal__debug",  // For pal, research - specific tool
      "query": "search query",  // For research - what to search
      "subagent": "Explore|debugger|researcher|code-reviewer|Plan|refactorer",  // For agent
      "scope": "what to look for",  // For agent, project_research
      "questions": ["q1", "q2"],  // For ask_user - questions to ask
      "action": "create|claim",  // For bead
      "reason": "why this is mandatory",
      "priority": "p0|p1|p2",  // p0 = critical, p1 = important, p2 = helpful
      "blocking": true  // true = blocks ALL other tools until satisfied
    }
  ],
  "mandate_policy": "strict"  // strict = enforce all, lenient = warn only
}

### When to Mandate Each Type

| Condition | Mandate | Blocking | Tool |
|-----------|---------|----------|------|
| Complex/uncertain task | pal | Yes | mcp__pal__thinkdeep |
| Debugging multi-file | pal | Yes | mcp__pal__debug |
| Architecture decision | pal | Yes | mcp__pal__consensus |
| External CLI needed | pal | Yes | mcp__pal__clink |
| Code review needed | pal | Yes | mcp__pal__codereview |
| Unknown library/API | research | Yes | mcp__crawl4ai__ddg_search or mcp__pal__apilookup |
| Codebase unfamiliar | agent | No | Explore |
| Multi-step feature | agent | No | Plan |
| Post-implementation | agent | No | code-reviewer |
| Non-trivial task | bead | Yes | create |
| Ambiguous requirements | ask_user | Yes | - |
| Multi-file impl | plan_mode | No | - |
| Deep codebase search | project_research | No | - |
| Complex orchestration | script | No | - |

### PAL Tool Selection Guide (Pick the BEST one)

| Task Signal | Best PAL Tool | When to Use |
|-------------|---------------|-------------|
| "why", "how does", understanding | mcp__pal__thinkdeep | Deep reasoning needed |
| bug, error, failure, fix | mcp__pal__debug | Any debugging |
| review, quality, refactor | mcp__pal__codereview | Code quality assessment |
| architecture, design, tradeoff | mcp__pal__consensus | Multi-perspective needed |
| API, library, docs, version | mcp__pal__apilookup | External documentation |
| plan, implement, steps | mcp__pal__planner | Multi-step implementation |
| validate, pre-commit, changes | mcp__pal__precommit | Before committing |
| brainstorm, discuss, general | mcp__pal__chat | General consultation |
| external CLI (gemini, codex) | mcp__pal__clink | Leverage other CLIs |

### Examples

Task: "Fix the authentication bug"
"mandates": [
  {"type": "bead", "action": "create", "reason": "Bug fix needs tracking", "blocking": true, "priority": "p1"},
  {"type": "pal", "tool": "mcp__pal__debug", "reason": "Multi-step debugging requires external analysis", "blocking": true, "priority": "p0"},
  {"type": "agent", "subagent": "Explore", "scope": "auth-related files and error patterns", "reason": "Map affected code surface", "blocking": false, "priority": "p1"}
]

Task: "Implement dark mode"
"mandates": [
  {"type": "bead", "action": "create", "reason": "Feature implementation needs tracking", "blocking": true, "priority": "p1"},
  {"type": "research", "tool": "mcp__crawl4ai__ddg_search", "query": "CSS dark mode best practices 2025", "reason": "Current patterns needed", "blocking": true, "priority": "p0"},
  {"type": "plan_mode", "reason": "Multi-file feature needs user approval", "blocking": false, "priority": "p2"}
]

Task: "What does the auth module do?"
"mandates": [
  {"type": "agent", "subagent": "Explore", "scope": "auth module structure and flow", "reason": "Codebase exploration", "blocking": false, "priority": "p1"}
]
// Note: Trivial explanation doesn't need bead or PAL

Task: "How should we architect the notification system?"
"mandates": [
  {"type": "bead", "action": "create", "reason": "Architecture decision needs tracking", "blocking": true, "priority": "p1"},
  {"type": "pal", "tool": "mcp__pal__consensus", "reason": "Architecture decisions need multi-perspective analysis", "blocking": true, "priority": "p0"},
  {"type": "ask_user", "questions": ["Real-time or batch?", "In-app, email, or push?"], "reason": "Requirements ambiguous", "blocking": true, "priority": "p0"}
]

IMPORTANT: For any non-trivial task (medium or complex classification), you MUST include at least:
1. A bead mandate (blocking) for task tracking
2. A PAL mandate (blocking) with the SPECIFIC best tool
3. Any relevant research/agent mandates based on the task
"""


__all__ = [
    "MandateType",
    "Mandate",
    "SATISFACTION_PATTERNS",
    "check_mandate_satisfaction",
    "get_unsatisfied_blocking",
    "get_unsatisfied_all",
    "format_mandate_checklist",
    "MANDATE_SYSTEM_PROMPT",
]
