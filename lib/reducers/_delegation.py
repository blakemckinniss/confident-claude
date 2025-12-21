#!/usr/bin/env python3
"""Confidence reducers: agent delegation enforcement (v4.26).

These reducers penalize patterns where Task agents should have been used
instead of direct tool calls - preserving master thread context.

Token Economy Philosophy:
- Master thread has 200k context limit
- Each Task agent gets its own 200k context (free)
- Offloading "dumb" subroutines to agents = context preservation
- Agents can run in background = async progress
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ._base import ConfidenceReducer, IMPACT_BEHAVIORAL

if TYPE_CHECKING:
    from session_state import SessionState


@dataclass
class ExplorationWithoutAgentReducer(ConfidenceReducer):
    """Triggers when doing 3+ exploration calls without using Explore agent.

    Pattern: Sequential Grep/Glob/Read calls for codebase understanding
    Solution: Task(subagent_type='Explore') consumes its own 200k context

    AGGRESSIVE (v4.26.1): Lowered from 5 to 3, penalty increased.
    Every Read/Grep/Glob burns YOUR 200k context. Agents are FREE.
    """

    name: str = "exploration_without_agent"
    delta: int = -8  # INCREASED from -5
    description: str = "3+ exploration calls - MUST use Task(Explore) agent"
    remedy: str = "Task(subagent_type='Explore', prompt='Find X in codebase')"
    cooldown_turns: int = 5  # DECREASED from 8 - fire more often
    impact_category: str = IMPACT_BEHAVIORAL

    # Exploration tools that should trigger counting
    EXPLORATION_TOOLS = {
        "Grep",
        "Glob",
        "Read",
        "mcp__serena__find_symbol",
        "mcp__serena__search_for_pattern",
        "mcp__serena__get_symbols_overview",
    }

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.get_effective_cooldown(state):
            return False

        # Count consecutive exploration calls without Task(Explore)
        consecutive_explore = getattr(state, "consecutive_exploration_calls", 0)

        # Check if Task(Explore) was used recently (last 5 turns) - TIGHTENED
        recent_explore_agent = getattr(state, "recent_explore_agent_turn", -100)
        if state.turn_count - recent_explore_agent < 5:
            return False  # Recently used Explore agent, exempt

        return consecutive_explore >= 3  # LOWERED from 5


@dataclass
class DebuggingWithoutAgentReducer(ConfidenceReducer):
    """Triggers when debugging 2+ attempts without using debugger agent.

    Pattern: Repeated edit attempts on same file to fix issue
    Solution: Task(subagent_type='debugger') gets fresh perspective

    AGGRESSIVE (v4.26.1): After 2 failed attempts, you're burning context.
    A debugger agent with fresh 200k context WILL find it faster.
    """

    name: str = "debugging_without_agent"
    delta: int = -12  # INCREASED from -8 - debugging loops are expensive
    description: str = "2+ debug attempts - SPAWN Task(debugger) NOW"
    remedy: str = "Task(subagent_type='debugger', prompt='Debug issue: ...')"
    cooldown_turns: int = 5  # DECREASED from 10
    impact_category: str = IMPACT_BEHAVIORAL

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.get_effective_cooldown(state):
            return False

        # Check for debugging loop (same file edited 3+ times)
        file_edit_counts = getattr(state, "file_edit_counts", {})
        max_edits = max(file_edit_counts.values()) if file_edit_counts else 0

        # Check if in debug mode and stuck
        in_debug_mode = getattr(state, "debug_mode_active", False)
        consecutive_failures = getattr(state, "consecutive_tool_failures", 0)

        # Check if debugger agent was used recently
        recent_debugger = getattr(state, "recent_debugger_agent_turn", -100)
        if state.turn_count - recent_debugger < 10:
            return False

        # AGGRESSIVE: 2+ edits to same file OR (debug mode + 1 failure)
        return max_edits >= 2 or (in_debug_mode and consecutive_failures >= 1)


@dataclass
class ResearchWithoutAgentReducer(ConfidenceReducer):
    """Triggers when doing 2+ web lookups without using researcher agent.

    Pattern: Multiple WebSearch/WebFetch/crawl4ai calls for same topic
    Solution: Task(subagent_type='researcher') does comprehensive research

    AGGRESSIVE (v4.26.1): 2 searches = pattern. Researcher agent does it
    better with dedicated context. Stop polluting master thread.
    """

    name: str = "research_without_agent"
    delta: int = -6  # INCREASED from -3
    description: str = "2+ research calls - DELEGATE to Task(researcher)"
    remedy: str = "Task(subagent_type='researcher', prompt='Research X')"
    cooldown_turns: int = 4  # DECREASED from 8
    impact_category: str = IMPACT_BEHAVIORAL

    RESEARCH_TOOLS = {
        "WebSearch",
        "WebFetch",
        "mcp__crawl4ai__crawl",
        "mcp__crawl4ai__ddg_search",
        "mcp__pal__apilookup",
    }

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.get_effective_cooldown(state):
            return False

        consecutive_research = getattr(state, "consecutive_research_calls", 0)

        # Check if researcher agent was used recently (TIGHTENED to 5 turns)
        recent_researcher = getattr(state, "recent_researcher_agent_turn", -100)
        if state.turn_count - recent_researcher < 5:
            return False

        return consecutive_research >= 2  # LOWERED from 3


@dataclass
class ReviewWithoutAgentReducer(ConfidenceReducer):
    """Triggers after ANY significant implementation without code-reviewer.

    Pattern: 3+ file edits without spawning code-reviewer
    Solution: Task(subagent_type='code-reviewer') catches issues early

    AGGRESSIVE (v4.26.1): 3 files edited = significant work. Code review
    in a separate 200k context catches YOUR blind spots. DO IT.
    """

    name: str = "review_without_agent"
    delta: int = -6  # INCREASED from -3
    description: str = "3+ edits - SPAWN Task(code-reviewer) for review"
    remedy: str = "Task(subagent_type='code-reviewer', prompt='Review changes')"
    cooldown_turns: int = 8  # DECREASED from 15
    impact_category: str = IMPACT_BEHAVIORAL

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.get_effective_cooldown(state):
            return False

        # Count files edited this session
        files_edited = getattr(state, "files_edited", [])

        # Check if code-reviewer was used (TIGHTENED to 10 turns)
        recent_reviewer = getattr(state, "recent_reviewer_agent_turn", -100)
        if state.turn_count - recent_reviewer < 10:
            return False

        return len(files_edited) >= 3  # LOWERED from 5


@dataclass
class PlanningWithoutAgentReducer(ConfidenceReducer):
    """Triggers on ANY multi-file task without using Plan agent.

    Pattern: Multi-step implementation started without planning
    Solution: Task(subagent_type='Plan') creates implementation roadmap

    AGGRESSIVE (v4.26.1): Planning in master thread = context waste.
    Plan agent produces BETTER architecture with dedicated context.
    """

    name: str = "planning_without_agent"
    delta: int = -8  # INCREASED from -4
    description: str = "Multi-file task without Plan agent - SPAWN NOW"
    remedy: str = "Task(subagent_type='Plan', prompt='Plan implementation of X')"
    cooldown_turns: int = 10  # DECREASED from 20
    impact_category: str = IMPACT_BEHAVIORAL

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.get_effective_cooldown(state):
            return False

        # Check if task was marked as complex by mastermind
        task_complexity = getattr(state, "mastermind_classification", "")
        is_complex = task_complexity == "complex"

        # Check if Plan agent was used
        recent_planner = getattr(state, "recent_plan_agent_turn", -100)
        if state.turn_count - recent_planner < 30:
            return False

        # Only trigger if complex AND significant work started
        files_edited = len(getattr(state, "files_edited", []))

        return is_complex and files_edited >= 2


@dataclass
class RefactorWithoutAgentReducer(ConfidenceReducer):
    """Triggers when refactoring without using refactorer agent.

    Pattern: Renaming/moving symbols across multiple files manually
    Solution: Task(subagent_type='refactorer') ensures all callers updated

    AGGRESSIVE (v4.26.1): Manual refactoring ALWAYS misses callers.
    Refactorer agent greps ALL usages with fresh 200k context.
    """

    name: str = "refactor_without_agent"
    delta: int = -10  # INCREASED from -5 - broken refactors are expensive
    description: str = "Refactoring detected - MUST use Task(refactorer)"
    remedy: str = "Task(subagent_type='refactorer', prompt='Rename X to Y')"
    cooldown_turns: int = 5  # DECREASED from 10
    impact_category: str = IMPACT_BEHAVIORAL

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.get_effective_cooldown(state):
            return False

        # Detect refactoring pattern: same symbol/pattern edited in multiple files
        refactor_detected = context.get("refactor_pattern_detected", False)

        # Check if refactorer agent was used
        recent_refactorer = getattr(state, "recent_refactorer_agent_turn", -100)
        if state.turn_count - recent_refactorer < 15:
            return False

        return refactor_detected


__all__ = [
    "ExplorationWithoutAgentReducer",
    "DebuggingWithoutAgentReducer",
    "ResearchWithoutAgentReducer",
    "ReviewWithoutAgentReducer",
    "PlanningWithoutAgentReducer",
    "RefactorWithoutAgentReducer",
]
