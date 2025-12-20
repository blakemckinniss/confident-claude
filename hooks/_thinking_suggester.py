#!/usr/bin/env python3
"""
Thinking Suggester: Context injection based on Claude's thinking patterns.

Analyzes thinking blocks to surface relevant tools and capabilities that
Claude may not be aware of or remember to use.

PHILOSOPHY:
- Claude's thinking tokens contain rich signal about intent
- User prompts are minimal; thinking is where the context lives
- Proactive suggestion beats reactive correction

EXAMPLES:
- Thinking mentions "test in browser" → Playwright suggestion
- Thinking mentions "need docs for X" → Context7 suggestion
- Thinking shows uncertainty → PAL consultation suggestion
"""

import re
from dataclasses import dataclass
from typing import List, Tuple, Optional

# =============================================================================
# SUGGESTION PATTERNS
# =============================================================================


@dataclass
class Suggestion:
    """A contextual capability suggestion."""

    emoji: str
    title: str
    tools: List[str]
    hint: str


# Pattern → Suggestion mapping
# Each tuple: (compiled_regex, Suggestion)
_THINKING_SUGGESTIONS: List[Tuple[re.Pattern, Suggestion]] = [
    # Browser/UI testing
    (
        re.compile(
            r"(test|check|verify|see|view).{0,30}(browser|UI|interface|page|screen|visual)",
            re.I,
        ),
        Suggestion(
            emoji="🎭",
            title="Playwright Available",
            tools=[
                "mcp__playwright__browser_navigate",
                "mcp__playwright__browser_snapshot",
                "mcp__playwright__browser_click",
            ],
            hint="Navigate with browser_navigate, inspect with browser_snapshot",
        ),
    ),
    (
        re.compile(r"(open|launch|start).{0,20}(browser|chrome|firefox)", re.I),
        Suggestion(
            emoji="🎭",
            title="Playwright Browser Control",
            tools=[
                "mcp__playwright__browser_navigate",
                "mcp__playwright__browser_snapshot",
            ],
            hint="Use browser_navigate to open URLs, browser_snapshot to see page state",
        ),
    ),
    # API/Library documentation
    (
        re.compile(
            r"(need|want|get|find|look\s*up|check).{0,30}(API|library|package|docs|documentation)",
            re.I,
        ),
        Suggestion(
            emoji="📚",
            title="Context7 Documentation",
            tools=[
                "mcp__plugin_context7_context7__resolve-library-id",
                "mcp__plugin_context7_context7__get-library-docs",
            ],
            hint="First resolve-library-id, then get-library-docs with topic",
        ),
    ),
    (
        re.compile(
            r"(how does|how do I use|what's the API|documentation for)",
            re.I,
        ),
        Suggestion(
            emoji="📚",
            title="Context7 Available",
            tools=["mcp__plugin_context7_context7__get-library-docs"],
            hint="Use get-library-docs with the library ID and topic",
        ),
    ),
    # Uncertainty / need external perspective
    (
        re.compile(
            r"(not sure|uncertain|unsure|don't know).{0,40}(approach|how to|best|right|should)",
            re.I,
        ),
        Suggestion(
            emoji="🔮",
            title="PAL External Perspective",
            tools=["mcp__pal__chat", "mcp__pal__thinkdeep"],
            hint="Use chat for quick consult, thinkdeep for deep analysis",
        ),
    ),
    (
        re.compile(
            r"(multiple|several|different).{0,20}(approaches|options|ways).{0,20}(could|might|possible)",
            re.I,
        ),
        Suggestion(
            emoji="🗳️",
            title="PAL Consensus Available",
            tools=["mcp__pal__consensus"],
            hint="Get multi-model consensus on approach decisions",
        ),
    ),
    # Debugging
    (
        re.compile(
            r"(why is|why does|why isn't|why doesn't|why won't).{0,30}(work|fail|error|break|crash|function)",
            re.I,
        ),
        Suggestion(
            emoji="🐛",
            title="PAL Debug Available",
            tools=["mcp__pal__debug"],
            hint="Systematic debugging with hypothesis testing",
        ),
    ),
    (
        re.compile(
            r"(this|it).{0,20}(isn't|doesn't|won't|not).{0,20}(work|function|run)",
            re.I,
        ),
        Suggestion(
            emoji="🐛",
            title="PAL Debug Available",
            tools=["mcp__pal__debug"],
            hint="Systematic debugging with hypothesis testing",
        ),
    ),
    (
        re.compile(
            r"(can't figure out|stuck on|struggling with).{0,30}(bug|issue|error|problem)",
            re.I,
        ),
        Suggestion(
            emoji="🐛",
            title="PAL Debug for Stuck Issues",
            tools=["mcp__pal__debug", "mcp__pal__thinkdeep"],
            hint="Use debug for systematic root cause analysis",
        ),
    ),
    # Web search / research
    (
        re.compile(
            r"(search|look up|find|google|research).{0,20}(online|web|internet|latest|for)",
            re.I,
        ),
        Suggestion(
            emoji="🌐",
            title="Web Search Available",
            tools=["mcp__crawl4ai__ddg_search", "mcp__crawl4ai__crawl"],
            hint="ddg_search for queries, crawl for specific URLs",
        ),
    ),
    (
        re.compile(
            r"(need to|should|let me).{0,15}(search|google|look up|research)",
            re.I,
        ),
        Suggestion(
            emoji="🌐",
            title="Web Search Available",
            tools=["mcp__crawl4ai__ddg_search", "mcp__crawl4ai__crawl"],
            hint="ddg_search for queries, crawl for specific URLs",
        ),
    ),
    (
        re.compile(
            r"(current|latest|recent|2024|2025).{0,20}(version|release|docs|documentation)",
            re.I,
        ),
        Suggestion(
            emoji="🌐",
            title="Live Web Fetch",
            tools=["mcp__crawl4ai__crawl", "mcp__crawl4ai__ddg_search"],
            hint="Use crawl for up-to-date documentation, bypasses caches",
        ),
    ),
    # Code review / quality
    (
        re.compile(r"(review|check|audit).{0,20}(code|changes|diff|PR)", re.I),
        Suggestion(
            emoji="🔍",
            title="PAL Code Review",
            tools=["mcp__pal__codereview", "mcp__pal__precommit"],
            hint="codereview for deep analysis, precommit for pre-merge validation",
        ),
    ),
    (
        re.compile(r"(let me|should|need to).{0,15}review", re.I),
        Suggestion(
            emoji="🔍",
            title="PAL Code Review",
            tools=["mcp__pal__codereview", "mcp__pal__precommit"],
            hint="codereview for deep analysis, precommit for pre-merge validation",
        ),
    ),
    # Architecture / design
    (
        re.compile(
            r"(design|architect|structure|organize).{0,20}(system|application|codebase|project)",
            re.I,
        ),
        Suggestion(
            emoji="🏗️",
            title="PAL Architecture Planning",
            tools=["mcp__pal__planner", "mcp__pal__consensus"],
            hint="planner for implementation steps, consensus for design decisions",
        ),
    ),
    # Semantic code analysis
    (
        re.compile(
            r"(find|locate|where is|where's).{0,25}(symbol|function|class|method|defined|definition)",
            re.I,
        ),
        Suggestion(
            emoji="🔬",
            title="Serena Semantic Search",
            tools=["mcp__serena__find_symbol", "mcp__serena__find_referencing_symbols"],
            hint="find_symbol for definitions, find_referencing_symbols for usages",
        ),
    ),
    (
        re.compile(
            r"(this|that|the).{0,15}(symbol|function|class|method).{0,15}(is defined|defined)",
            re.I,
        ),
        Suggestion(
            emoji="🔬",
            title="Serena Semantic Search",
            tools=["mcp__serena__find_symbol", "mcp__serena__find_referencing_symbols"],
            hint="find_symbol for definitions, find_referencing_symbols for usages",
        ),
    ),
    (
        re.compile(
            r"(impact|affect|change).{0,20}(if I|when I|this|that).{0,20}(modify|change|rename)",
            re.I,
        ),
        Suggestion(
            emoji="🔬",
            title="Serena Impact Analysis",
            tools=[
                "mcp__serena__find_referencing_symbols",
                "mcp__serena__rename_symbol",
            ],
            hint="Find all references before making breaking changes",
        ),
    ),
    # Memory / past context
    (
        re.compile(
            r"(remember|recall|previous|earlier|before).{0,20}(session|conversation|decision|we)",
            re.I,
        ),
        Suggestion(
            emoji="🧠",
            title="Memory Search Available",
            tools=[
                "mcp__plugin_claude-mem_mem-search__search",
                "mcp__plugin_claude-mem_mem-search__get_recent_context",
            ],
            hint="search for specific topics, get_recent_context for chronological",
        ),
    ),
    (
        re.compile(
            r"(what did we|did we already|have we).{0,20}(decide|discuss|do|try)", re.I
        ),
        Suggestion(
            emoji="🧠",
            title="Claude-Mem History",
            tools=["mcp__plugin_claude-mem_mem-search__search"],
            hint="Search past sessions for context",
        ),
    ),
    # File operations at scale
    (
        re.compile(
            r"(many|multiple|all|every|batch).{0,20}(files|directories|folders)", re.I
        ),
        Suggestion(
            emoji="📦",
            title="Repomix Codebase Packing",
            tools=["mcp__plugin_repomix-mcp_repomix__pack_codebase"],
            hint="Pack entire codebase or directory for analysis",
        ),
    ),
    # Console errors / frontend debugging
    (
        re.compile(r"(console|browser).{0,20}(error|warning|log|message)", re.I),
        Suggestion(
            emoji="🖥️",
            title="Playwright Console Access",
            tools=[
                "mcp__playwright__browser_console_messages",
                "mcp__playwright__browser_evaluate",
            ],
            hint="browser_console_messages for logs, browser_evaluate for JS execution",
        ),
    ),
    # Form filling / interaction
    (
        re.compile(r"(fill|submit|enter|type).{0,20}(form|input|field|text)", re.I),
        Suggestion(
            emoji="⌨️",
            title="Playwright Form Interaction",
            tools=[
                "mcp__playwright__browser_fill_form",
                "mcp__playwright__browser_type",
                "mcp__playwright__browser_click",
            ],
            hint="browser_fill_form for multiple fields, browser_type for single input",
        ),
    ),
    # Screenshot / visual capture
    (
        re.compile(
            r"(screenshot|capture|picture|image).{0,20}(page|screen|UI|element)", re.I
        ),
        Suggestion(
            emoji="📸",
            title="Playwright Screenshot",
            tools=["mcp__playwright__browser_take_screenshot"],
            hint="Use fullPage=true for entire page, or specify element ref",
        ),
    ),
    # Network requests
    (
        re.compile(
            r"(API|network|HTTP|request|response|fetch).{0,20}(call|request|traffic)",
            re.I,
        ),
        Suggestion(
            emoji="📡",
            title="Playwright Network Monitor",
            tools=["mcp__playwright__browser_network_requests"],
            hint="See all network requests since page load",
        ),
    ),
    # === PATTERNS FROM REAL THINKING DATA ===
    # References/Impact (126 occurrences in real data)
    (
        re.compile(
            r"(search for|find|check).{0,15}references",
            re.I,
        ),
        Suggestion(
            emoji="🔬",
            title="Serena Reference Search",
            tools=["mcp__serena__find_referencing_symbols"],
            hint="Find all usages of a symbol across codebase",
        ),
    ),
    (
        re.compile(
            r"(files that|who|what).{0,10}(reference|call|use)",
            re.I,
        ),
        Suggestion(
            emoji="🔬",
            title="Serena Impact Analysis",
            tools=["mcp__serena__find_referencing_symbols"],
            hint="Find all callers/usages before making changes",
        ),
    ),
    # Investigation/Tracing (from DEBUG category)
    (
        re.compile(
            r"let me (investigate|trace|debug)",
            re.I,
        ),
        Suggestion(
            emoji="🐛",
            title="PAL Debug Available",
            tools=["mcp__pal__debug"],
            hint="Systematic debugging with hypothesis testing",
        ),
    ),
    # Read file first (37 occurrences - common pattern)
    (
        re.compile(
            r"(need to|should|let me).{0,10}read.{0,10}(file|code).{0,10}first",
            re.I,
        ),
        Suggestion(
            emoji="📖",
            title="Read Before Edit",
            tools=["Read", "mcp__serena__get_symbols_overview"],
            hint="Use Read tool or serena get_symbols_overview for structure",
        ),
    ),
    # Run tests/lint (81 occurrences - common workflow)
    (
        re.compile(
            r"let me run.{0,10}(test|lint|linter|build)",
            re.I,
        ),
        Suggestion(
            emoji="🧪",
            title="Test/Lint Execution",
            tools=["Bash"],
            hint="pytest, ruff check, npm test - run in background for long tasks",
        ),
    ),
    # Earlier/created earlier (memory from same session)
    (
        re.compile(
            r"(I |that I ).{0,10}(created|read|wrote|made).{0,10}earlier",
            re.I,
        ),
        Suggestion(
            emoji="🧠",
            title="Session Context",
            tools=["mcp__plugin_claude-mem_mem-search__get_recent_context"],
            hint="Check recent context for what was done earlier",
        ),
    ),
]

# =============================================================================
# COOLDOWN TRACKING
# =============================================================================

# Track which suggestions were recently shown (by title)
# to avoid spamming the same suggestion
_recent_suggestions: dict[str, int] = {}  # title -> turn_count
_SUGGESTION_COOLDOWN = 10  # turns before same suggestion can appear again


def _should_suggest(title: str, turn_count: int) -> bool:
    """Check if suggestion is off cooldown."""
    if title not in _recent_suggestions:
        return True
    last_shown = _recent_suggestions[title]
    return (turn_count - last_shown) >= _SUGGESTION_COOLDOWN


def _record_suggestion(title: str, turn_count: int) -> None:
    """Record that a suggestion was shown."""
    _recent_suggestions[title] = turn_count


# =============================================================================
# MAIN FUNCTION
# =============================================================================


def get_thinking_suggestions(
    thinking_content: str, turn_count: int = 0, max_suggestions: int = 2
) -> Optional[str]:
    """
    Analyze thinking content and return contextual capability suggestions.

    Args:
        thinking_content: Combined text from recent thinking blocks
        turn_count: Current turn number for cooldown tracking
        max_suggestions: Maximum suggestions to return

    Returns:
        Formatted suggestion string or None if no matches
    """
    if not thinking_content or len(thinking_content) < 30:
        return None

    matched_suggestions: List[Suggestion] = []

    for pattern, suggestion in _THINKING_SUGGESTIONS:
        if len(matched_suggestions) >= max_suggestions:
            break

        if pattern.search(thinking_content):
            # Check cooldown
            if _should_suggest(suggestion.title, turn_count):
                matched_suggestions.append(suggestion)
                _record_suggestion(suggestion.title, turn_count)

    if not matched_suggestions:
        return None

    # Format output
    lines = ["💡 **Thinking-Based Suggestions**:"]
    for s in matched_suggestions:
        tools_str = ", ".join(f"`{t}`" for t in s.tools[:2])
        lines.append(f"{s.emoji} **{s.title}**: {tools_str}")
        lines.append(f"   ↳ {s.hint}")

    return "\n".join(lines)


# =============================================================================
# HOOK INTEGRATION
# =============================================================================


def check_thinking_suggestions(data: dict, state, runner_state: dict):
    """
    Hook function for PreToolUse runner integration.

    Returns HookResult with contextual suggestions based on thinking patterns.
    """
    from _hook_result import HookResult
    from synapse_core import extract_thinking_blocks

    transcript_path = data.get("transcript_path", "")
    if not transcript_path:
        return HookResult.none()

    # Skip for read-only tools (don't interrupt exploration)
    tool_name = data.get("tool_name", "")
    if tool_name in {"Read", "Glob", "Grep", "TodoRead", "BashOutput"}:
        return HookResult.none()

    # Extract thinking blocks
    thinking_blocks = extract_thinking_blocks(transcript_path)
    if not thinking_blocks:
        return HookResult.none()

    # Combine recent thinking (last 2 blocks, up to 2000 chars)
    combined = " ".join(thinking_blocks[-2:])[-2000:]

    # Get turn count from state for cooldown
    turn_count = getattr(state, "turn_count", 0)

    # Get suggestions
    suggestion_text = get_thinking_suggestions(combined, turn_count)

    if suggestion_text:
        return HookResult.with_context(suggestion_text)

    return HookResult.none()
