#!/usr/bin/env python3
"""
PAL Mandate Formula Book

Defines conditions that trigger MANDATORY PAL tool usage.
VERY AGGRESSIVE by design - prefer external consultation over solo work.

v2.0: Significantly lowered thresholds to encourage proactive PAL usage.
      Added keyword triggers for common scenarios.
      Made mandates fire during normal operation, not just problems.

Usage:
    from _pal_mandates import get_mandate
    mandate = get_mandate(confidence, intent, state_flags)
    if mandate:
        inject mandate.directive into context
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional


@dataclass
class Mandate:
    """A mandatory PAL tool invocation."""

    tool: str  # MCP tool name
    directive: str  # Injected text
    priority: int  # Higher = more urgent (1-100)
    reason: str  # Why this mandate fired


# =============================================================================
# FORMULA BOOK: Condition → Mandate mappings
# =============================================================================

# Priority levels
P_CRITICAL = 100  # Must do immediately
P_HIGH = 80  # Should do before proceeding
P_MEDIUM = 60  # Recommended before major actions
P_LOW = 40  # Suggested but optional
P_PROACTIVE = 50  # Proactive consultation (new tier)


def _critical_mandates(
    confidence: int, cascade_failure: bool, sunk_cost: bool
) -> list[Mandate]:
    """Tier 1: Critical mandates (confidence < 50 OR cascade conditions)."""
    mandates = []
    # RAISED from <30 to <50 for more aggressive consultation
    if confidence < 50:
        mandates.append(
            Mandate(
                tool="mcp__pal__thinkdeep",
                directive=f"🚨 **MANDATORY**: Confidence below 50% ({confidence}%). "
                "You MUST use `mcp__pal__thinkdeep` to analyze the situation "
                "before ANY action. Do NOT proceed without external consultation.",
                priority=P_CRITICAL,
                reason=f"Low confidence: {confidence}%",
            )
        )
    if cascade_failure:
        mandates.append(
            Mandate(
                tool="mcp__pal__thinkdeep",
                directive="🚨 **MANDATORY**: Cascade failure detected - same block 3+ times. "
                "You MUST use `mcp__pal__thinkdeep` to break the deadlock. "
                "Current approach is failing repeatedly.",
                priority=P_CRITICAL,
                reason="Cascade failure deadlock",
            )
        )
    if sunk_cost:
        mandates.append(
            Mandate(
                tool="mcp__pal__thinkdeep",
                directive="🚨 **MANDATORY**: Sunk cost detected - 3+ failures on same approach. "
                "You MUST use `mcp__pal__thinkdeep` to reconsider strategy. "
                "Stop trying the same thing.",
                priority=P_CRITICAL,
                reason="Sunk cost fallacy",
            )
        )
    return mandates


def _high_mandates(
    confidence: int, edit_oscillation: bool, goal_drift: bool, consecutive_failures: int
) -> list[Mandate]:
    """Tier 2: High priority mandates (confidence 50-70 OR problematic patterns)."""
    mandates = []
    # RAISED from 30-50 to 50-70 range
    if 50 <= confidence < 70:
        mandates.append(
            Mandate(
                tool="mcp__pal__thinkdeep",
                directive=f"⚠️ **REQUIRED**: Confidence is moderate ({confidence}%). "
                "Use `mcp__pal__thinkdeep` before making significant changes. "
                "External validation improves outcomes.",
                priority=P_HIGH,
                reason=f"Moderate confidence: {confidence}%",
            )
        )
    if edit_oscillation:
        mandates.append(
            Mandate(
                tool="mcp__pal__codereview",
                directive="⚠️ **REQUIRED**: Edit oscillation detected - thrashing on same file. "
                "Use `mcp__pal__codereview` to get fresh perspective. "
                "Stop editing until you understand the problem.",
                priority=P_HIGH,
                reason="Edit oscillation",
            )
        )
    if goal_drift:
        mandates.append(
            Mandate(
                tool="mcp__pal__planner",
                directive="⚠️ **REQUIRED**: Goal drift detected - straying from original task. "
                "Use `mcp__pal__planner` to realign with the goal. "
                "Refocus before continuing.",
                priority=P_HIGH,
                reason="Goal drift",
            )
        )
    # LOWERED from 3 to 2 consecutive failures
    if consecutive_failures >= 2:
        mandates.append(
            Mandate(
                tool="mcp__pal__debug",
                directive=f"⚠️ **REQUIRED**: {consecutive_failures} consecutive failures detected. "
                "Use `mcp__pal__debug` to analyze what's going wrong. "
                "Stop and diagnose before retrying.",
                priority=P_HIGH,
                reason=f"{consecutive_failures} consecutive failures",
            )
        )
    return mandates


def _medium_mandates(intent: Optional[str], confidence: int) -> list[Mandate]:
    """Tier 3: Medium priority mandates (intent-based - fire at ANY confidence)."""
    mandates = []
    # REMOVED confidence gates - always recommend for these intents
    if intent == "debug":
        mandates.append(
            Mandate(
                tool="mcp__pal__debug",
                directive="🔧 **USE PAL**: Debug intent detected. "
                "Use `mcp__pal__debug` for systematic root cause analysis. "
                "External perspective catches blind spots in debugging.",
                priority=P_MEDIUM,
                reason="Debug intent",
            )
        )
    if intent == "code_review":
        mandates.append(
            Mandate(
                tool="mcp__pal__codereview",
                directive="🔍 **USE PAL**: Code review intent detected. "
                "Use `mcp__pal__codereview` for comprehensive analysis. "
                "External review is always more thorough.",
                priority=P_MEDIUM,
                reason="Code review intent",
            )
        )
    if intent == "refactor":
        mandates.append(
            Mandate(
                tool="mcp__pal__codereview",
                directive="♻️ **USE PAL**: Refactor intent detected. "
                "Use `mcp__pal__codereview` before restructuring. "
                "Validate approach with external perspective.",
                priority=P_MEDIUM,
                reason="Refactor intent",
            )
        )
    if intent == "implement":
        mandates.append(
            Mandate(
                tool="mcp__pal__planner",
                directive="🏗️ **USE PAL**: Implementation task detected. "
                "Use `mcp__pal__planner` to structure the approach. "
                "Planning with external input improves quality.",
                priority=P_PROACTIVE,
                reason="Implementation intent",
            )
        )
    if intent == "architecture":
        mandates.append(
            Mandate(
                tool="mcp__pal__consensus",
                directive="🏛️ **USE PAL**: Architecture decision detected. "
                "Use `mcp__pal__consensus` for multi-model perspective. "
                "Architecture decisions benefit from diverse viewpoints.",
                priority=P_HIGH,
                reason="Architecture intent",
            )
        )
    return mandates


def _proactive_mandates(confidence: int) -> list[Mandate]:
    """Tier 4: Proactive mandates - encourage PAL even when things are going well."""
    mandates = []
    # Proactive consultation even at moderate-high confidence
    if 70 <= confidence < 85:
        mandates.append(
            Mandate(
                tool="mcp__pal__chat",
                directive="💡 **CONSIDER PAL**: Confidence is good but not expert-level. "
                "Consider `mcp__pal__chat` for a quick sanity check. "
                "External perspective often reveals blind spots.",
                priority=P_LOW,
                reason=f"Proactive consultation at {confidence}%",
            )
        )
    return mandates


def get_mandate(
    confidence: int,
    intent: Optional[str] = None,
    cascade_failure: bool = False,
    edit_oscillation: bool = False,
    sunk_cost: bool = False,
    goal_drift: bool = False,
    consecutive_failures: int = 0,
) -> Optional[Mandate]:
    """Evaluate conditions and return the highest-priority mandate."""
    mandates = []
    mandates.extend(_critical_mandates(confidence, cascade_failure, sunk_cost))
    mandates.extend(
        _high_mandates(confidence, edit_oscillation, goal_drift, consecutive_failures)
    )
    mandates.extend(_medium_mandates(intent, confidence))
    mandates.extend(_proactive_mandates(confidence))

    return max(mandates, key=lambda m: m.priority) if mandates else None


# =============================================================================
# KEYWORD TRIGGERS (AGGRESSIVE - fire on common patterns)
# =============================================================================

# Regex patterns for more flexible matching
_RE_ARCHITECTURE = re.compile(
    r"(architect|redesign|migrat|rewrite|restructur|overhaul|"
    r"fundamental\s+change|breaking\s+change|major\s+refactor|"
    r"new\s+approach|different\s+strategy|rethink|reimagine)",
    re.IGNORECASE,
)

_RE_DECISION = re.compile(
    r"(should\s+[iwe]|which\s+(approach|way|method|option)|"
    r"better\s+(option|way|approach)|trade.?off|pros?\s+and\s+cons?|"
    r"compare|versus|\bvs\b|alternative|best\s+way|optimal|"
    r"recommend|advice|suggest|opinion)",
    re.IGNORECASE,
)

_RE_DEBUG = re.compile(
    r"(debug|fix|broken|not\s+working|error|bug|issue|problem|"
    r"fail|crash|exception|wrong|unexpected|strange|weird|"
    r"doesn.t\s+work|can.t\s+figure|stuck|confused)",
    re.IGNORECASE,
)

_RE_IMPLEMENTATION = re.compile(
    r"(implement|build|create|add|develop|write|make|"
    r"new\s+feature|add\s+feature|how\s+to\s+|how\s+do\s+i|"
    r"need\s+to\s+(add|create|build|implement))",
    re.IGNORECASE,
)

_RE_REVIEW = re.compile(
    r"(review|check|audit|examine|inspect|look\s+at|"
    r"code\s+quality|clean\s+up|improve|optimize|"
    r"is\s+this\s+(good|right|correct|ok)|feedback)",
    re.IGNORECASE,
)

_RE_COMPLEX = re.compile(
    r"(complex|complicated|tricky|difficult|hard|"
    r"challenging|advanced|sophisticated|intricate|"
    r"multi.?step|multi.?part|several\s+files)",
    re.IGNORECASE,
)

_RE_UNCERTAINTY = re.compile(
    r"(not\s+sure|uncertain|unsure|don.t\s+know|"
    r"maybe|perhaps|possibly|might|could\s+be|"
    r"i\s+think|i\s+guess|wondering|confused)",
    re.IGNORECASE,
)

_RE_API_DOCS = re.compile(
    r"(api|sdk|library|framework|package|module|"
    r"documentation|docs|how\s+does\s+.+\s+work|"
    r"latest|current\s+version|deprecat|breaking)",
    re.IGNORECASE,
)


def check_keyword_mandate(prompt: str, confidence: int) -> Optional[Mandate]:
    """
    Check for keyword-triggered mandates in user prompt.

    AGGRESSIVE: Triggers on many common patterns to encourage PAL usage.

    Args:
        prompt: User's prompt text
        confidence: Current confidence

    Returns:
        Mandate if keywords detected, None otherwise
    """
    # Skip very short prompts or slash commands
    if len(prompt) < 10 or prompt.startswith("/"):
        return None

    # Architecture keywords → consensus (ALWAYS HIGH PRIORITY)
    if _RE_ARCHITECTURE.search(prompt):
        return Mandate(
            tool="mcp__pal__consensus",
            directive=(
                "🏗️ **USE PAL**: Architecture/migration task detected. "
                "Use `mcp__pal__consensus` for multi-model perspective. "
                "Major changes REQUIRE external validation."
            ),
            priority=P_HIGH,
            reason="Architecture keywords",
        )

    # Decision keywords → consensus
    if _RE_DECISION.search(prompt):
        return Mandate(
            tool="mcp__pal__consensus",
            directive=(
                "⚖️ **USE PAL**: Decision-making detected. "
                "Use `mcp__pal__consensus` for balanced multi-model analysis. "
                "Decisions benefit from diverse perspectives."
            ),
            priority=P_MEDIUM,
            reason="Decision keywords",
        )

    # Debug keywords → debug tool
    if _RE_DEBUG.search(prompt):
        return Mandate(
            tool="mcp__pal__debug",
            directive=(
                "🔧 **USE PAL**: Debug/fix task detected. "
                "Use `mcp__pal__debug` for systematic root cause analysis. "
                "External debugging perspective catches blind spots."
            ),
            priority=P_MEDIUM,
            reason="Debug keywords",
        )

    # Uncertainty keywords → thinkdeep
    if _RE_UNCERTAINTY.search(prompt):
        return Mandate(
            tool="mcp__pal__thinkdeep",
            directive=(
                "🤔 **USE PAL**: Uncertainty detected in request. "
                "Use `mcp__pal__thinkdeep` to clarify the approach. "
                "When uncertain, external analysis helps."
            ),
            priority=P_MEDIUM,
            reason="Uncertainty keywords",
        )

    # Complex task keywords → planner
    if _RE_COMPLEX.search(prompt):
        return Mandate(
            tool="mcp__pal__planner",
            directive=(
                "🧩 **USE PAL**: Complex task detected. "
                "Use `mcp__pal__planner` to structure the approach. "
                "Complex tasks benefit from external planning."
            ),
            priority=P_PROACTIVE,
            reason="Complexity keywords",
        )

    # Review keywords → codereview
    if _RE_REVIEW.search(prompt):
        return Mandate(
            tool="mcp__pal__codereview",
            directive=(
                "🔍 **USE PAL**: Review/quality task detected. "
                "Use `mcp__pal__codereview` for thorough analysis. "
                "External review is always more comprehensive."
            ),
            priority=P_PROACTIVE,
            reason="Review keywords",
        )

    # API/docs keywords → apilookup
    if _RE_API_DOCS.search(prompt):
        return Mandate(
            tool="mcp__pal__apilookup",
            directive=(
                "📚 **USE PAL**: API/library question detected. "
                "Use `mcp__pal__apilookup` for current documentation. "
                "Get authoritative info before implementing."
            ),
            priority=P_LOW,
            reason="API/docs keywords",
        )

    # Implementation keywords → planner (catch-all for substantial work)
    if _RE_IMPLEMENTATION.search(prompt) and len(prompt) > 30:
        return Mandate(
            tool="mcp__pal__planner",
            directive=(
                "🏗️ **CONSIDER PAL**: Implementation task detected. "
                "Consider `mcp__pal__planner` to structure approach. "
                "Planning improves implementation quality."
            ),
            priority=P_LOW,
            reason="Implementation keywords",
        )

    return None


# =============================================================================
# REPOMIX MCP TRIGGERS (for codebase analysis)
# =============================================================================

_RE_CODEBASE_ANALYSIS = re.compile(
    r"(analyz|understand|explor|overview|structure|architectur)\s*.*(codebase|repo|project|code)",
    re.IGNORECASE,
)

_RE_GITHUB_REPO = re.compile(
    r"(github\.com/|analyze\s+.+repo|check\s+.+repo|look\s+at\s+.+repo|"
    r"review\s+.+repo|understand\s+.+repo|explore\s+.+repo)",
    re.IGNORECASE,
)

_RE_MULTI_FILE = re.compile(
    r"(all\s+files|entire\s+(codebase|project|repo)|"
    r"across\s+(the\s+)?(codebase|project|files)|"
    r"whole\s+(codebase|project)|every\s+file|"
    r"project.?wide|codebase.?wide|repo.?wide)",
    re.IGNORECASE,
)

_RE_CODE_REVIEW_BROAD = re.compile(
    r"(review|audit|check)\s+(the\s+)?(entire|whole|full|all)\s*(code|project|repo|codebase)",
    re.IGNORECASE,
)

_RE_DOCUMENTATION = re.compile(
    r"(document|generate\s+docs?|create\s+docs?|write\s+docs?)\s*.*(codebase|project|repo|code)",
    re.IGNORECASE,
)

_RE_BUG_HUNT = re.compile(
    r"(find|hunt|search|look\s+for)\s*.*(bug|issue|problem|error)\s*.*(across|in\s+the|throughout)",
    re.IGNORECASE,
)

_RE_SKILL_GENERATE = re.compile(
    r"(create|generate|make|build)\s*.*(skill|reference|knowledge)\s*.*(from|for|about)",
    re.IGNORECASE,
)


def check_repomix_mandate(prompt: str) -> Optional[Mandate]:
    """
    Check for Repomix MCP triggers in user prompt.

    Repomix is ideal for:
    - Codebase analysis and understanding
    - GitHub repository exploration
    - Multi-file operations
    - Documentation generation
    - Broad code reviews
    """
    if len(prompt) < 10 or prompt.startswith("/"):
        return None

    # GitHub URL or repo analysis → pack_remote_repository
    if _RE_GITHUB_REPO.search(prompt):
        return Mandate(
            tool="mcp__plugin_repomix-mcp_repomix__pack_remote_repository",
            directive=(
                "🔗 **USE REPOMIX**: GitHub repository detected. "
                "Use `mcp__plugin_repomix-mcp_repomix__pack_remote_repository` to analyze it. "
                "Repomix consolidates repos into AI-optimized format."
            ),
            priority=P_HIGH,
            reason="GitHub repo analysis",
        )

    # Codebase analysis/understanding → pack_codebase
    if _RE_CODEBASE_ANALYSIS.search(prompt):
        return Mandate(
            tool="mcp__plugin_repomix-mcp_repomix__pack_codebase",
            directive=(
                "📦 **USE REPOMIX**: Codebase analysis detected. "
                "Use `mcp__plugin_repomix-mcp_repomix__pack_codebase` for comprehensive view. "
                "Repomix provides structure, metrics, and consolidated code."
            ),
            priority=P_MEDIUM,
            reason="Codebase analysis",
        )

    # Multi-file operations → pack_codebase
    if _RE_MULTI_FILE.search(prompt):
        return Mandate(
            tool="mcp__plugin_repomix-mcp_repomix__pack_codebase",
            directive=(
                "📂 **USE REPOMIX**: Multi-file operation detected. "
                "Use `mcp__plugin_repomix-mcp_repomix__pack_codebase` to see all files. "
                "Repomix consolidates for efficient analysis."
            ),
            priority=P_MEDIUM,
            reason="Multi-file operation",
        )

    # Broad code review → pack_codebase
    if _RE_CODE_REVIEW_BROAD.search(prompt):
        return Mandate(
            tool="mcp__plugin_repomix-mcp_repomix__pack_codebase",
            directive=(
                "🔍 **USE REPOMIX**: Broad code review detected. "
                "Use `mcp__plugin_repomix-mcp_repomix__pack_codebase` first. "
                "Then use `mcp__pal__codereview` on the packed output."
            ),
            priority=P_HIGH,
            reason="Broad code review",
        )

    # Documentation generation → pack_codebase
    if _RE_DOCUMENTATION.search(prompt):
        return Mandate(
            tool="mcp__plugin_repomix-mcp_repomix__pack_codebase",
            directive=(
                "📚 **USE REPOMIX**: Documentation task detected. "
                "Use `mcp__plugin_repomix-mcp_repomix__pack_codebase` to gather all code. "
                "Repomix output is ideal for documentation generation."
            ),
            priority=P_MEDIUM,
            reason="Documentation generation",
        )

    # Bug hunting across codebase → pack_codebase
    if _RE_BUG_HUNT.search(prompt):
        return Mandate(
            tool="mcp__plugin_repomix-mcp_repomix__pack_codebase",
            directive=(
                "🐛 **USE REPOMIX**: Bug hunt across codebase detected. "
                "Use `mcp__plugin_repomix-mcp_repomix__pack_codebase` for full visibility. "
                "Then grep the packed output for patterns."
            ),
            priority=P_MEDIUM,
            reason="Codebase bug hunt",
        )

    # Skill generation → generate_skill
    if _RE_SKILL_GENERATE.search(prompt):
        return Mandate(
            tool="mcp__plugin_repomix-mcp_repomix__generate_skill",
            directive=(
                "🎯 **USE REPOMIX**: Skill generation detected. "
                "Use `mcp__plugin_repomix-mcp_repomix__generate_skill` to create reference. "
                "Creates SKILL.md with project knowledge."
            ),
            priority=P_MEDIUM,
            reason="Skill generation",
        )

    return None


# =============================================================================
# CRAWL4AI MCP TRIGGERS (for web scraping and search)
# =============================================================================

_RE_URL_FETCH = re.compile(
    r"(fetch|get|read|scrape|crawl|extract|pull)\s+(content\s+)?(from\s+)?"
    r"(the\s+)?(url|page|site|website|link|article|blog|post)|"
    r"https?://[^\s]+",
    re.IGNORECASE,
)

_RE_WEB_SEARCH = re.compile(
    r"(search|look\s+up|find)\s+(online|on\s+the\s+web|the\s+web|google|duckduckgo)|"
    r"(web|online|internet)\s+search|"
    r"search\s+(for|about)\s+.{10,}",
    re.IGNORECASE,
)

_RE_DOCUMENTATION_FETCH = re.compile(
    r"(get|fetch|read|check|look\s+at)\s+(the\s+)?(latest|official|current)?\s*"
    r"(docs?|documentation|readme|guide|tutorial|reference)",
    re.IGNORECASE,
)

_RE_CLOUDFLARE_BYPASS = re.compile(
    r"(cloudflare|bot\s+detect|captcha|blocked|403|access\s+denied|"
    r"javascript\s+render|dynamic\s+content|spa|single.?page)",
    re.IGNORECASE,
)

_RE_ARTICLE_READ = re.compile(
    r"(read|summarize|extract|get)\s+(the\s+)?(article|blog\s+post|post|news|content)\s+"
    r"(from|at|on)|"
    r"what\s+(does|is)\s+(this|that)\s+(article|page|site)\s+(say|about)",
    re.IGNORECASE,
)

_RE_RESEARCH_WEB = re.compile(
    r"(research|investigate|find\s+out|learn)\s+(about|how|what|why).{10,}(online|web)?|"
    r"(current|latest|recent|new)\s+(info|information|news|updates?)\s+(on|about)",
    re.IGNORECASE,
)


def check_crawl4ai_mandate(prompt: str) -> Optional[Mandate]:
    """
    Check for Crawl4AI MCP triggers in user prompt.

    Crawl4AI is ideal for:
    - Fetching web pages with JavaScript content
    - Bypassing bot detection/Cloudflare
    - Getting clean markdown from web pages
    - Web research and search
    - Reading documentation sites
    - Extracting article content
    """
    if len(prompt) < 10 or prompt.startswith("/"):
        return None

    # URL present or explicit fetch request → crawl
    if _RE_URL_FETCH.search(prompt):
        return Mandate(
            tool="mcp__crawl4ai__crawl",
            directive=(
                "🌐 **USE CRAWL4AI**: URL/fetch request detected. "
                "Use `mcp__crawl4ai__crawl` for JavaScript-rendered content. "
                "Crawl4AI bypasses bot detection and returns clean markdown."
            ),
            priority=P_HIGH,
            reason="URL fetch request",
        )

    # Cloudflare/bot detection mention → crawl
    if _RE_CLOUDFLARE_BYPASS.search(prompt):
        return Mandate(
            tool="mcp__crawl4ai__crawl",
            directive=(
                "🛡️ **USE CRAWL4AI**: Bot detection bypass needed. "
                "Use `mcp__crawl4ai__crawl` - it handles Cloudflare/captchas. "
                "More powerful than basic WebFetch."
            ),
            priority=P_HIGH,
            reason="Bot detection bypass",
        )

    # Documentation fetch → crawl
    if _RE_DOCUMENTATION_FETCH.search(prompt):
        return Mandate(
            tool="mcp__crawl4ai__crawl",
            directive=(
                "📚 **USE CRAWL4AI**: Documentation fetch detected. "
                "Use `mcp__crawl4ai__crawl` for clean markdown extraction. "
                "Better than WebFetch for docs sites with JS."
            ),
            priority=P_MEDIUM,
            reason="Documentation fetch",
        )

    # Article/blog reading → crawl
    if _RE_ARTICLE_READ.search(prompt):
        return Mandate(
            tool="mcp__crawl4ai__crawl",
            directive=(
                "📰 **USE CRAWL4AI**: Article extraction detected. "
                "Use `mcp__crawl4ai__crawl` for clean content extraction. "
                "Returns LLM-friendly markdown from articles."
            ),
            priority=P_MEDIUM,
            reason="Article extraction",
        )

    # Web search → ddg_search
    if _RE_WEB_SEARCH.search(prompt):
        return Mandate(
            tool="mcp__crawl4ai__ddg_search",
            directive=(
                "🔍 **USE CRAWL4AI**: Web search detected. "
                "Use `mcp__crawl4ai__ddg_search` for DuckDuckGo results. "
                "Then crawl individual URLs for full content."
            ),
            priority=P_MEDIUM,
            reason="Web search",
        )

    # Research request → ddg_search first
    if _RE_RESEARCH_WEB.search(prompt):
        return Mandate(
            tool="mcp__crawl4ai__ddg_search",
            directive=(
                "🔬 **USE CRAWL4AI**: Research request detected. "
                "Use `mcp__crawl4ai__ddg_search` to find sources first. "
                "Then crawl relevant URLs for detailed information."
            ),
            priority=P_LOW,
            reason="Web research",
        )

    return None


# =============================================================================
# CONTEXT7 MCP TRIGGERS (for library documentation)
# =============================================================================

# Import Context7 library detection if available
try:
    from _hooks_context7 import detect_library_context, LIBRARY_MENTION_PATTERNS

    CONTEXT7_DETECTION_AVAILABLE = True
except ImportError:
    CONTEXT7_DETECTION_AVAILABLE = False
    detect_library_context = None
    LIBRARY_MENTION_PATTERNS = []

_RE_LIBRARY_DOCS = re.compile(
    r"(how\s+(do\s+i|to|does)|what.?s\s+the|show\s+me|explain)\s+"
    r".{0,30}(api|hook|component|function|method|syntax|usage|example)",
    re.IGNORECASE,
)

_RE_LIBRARY_ERROR = re.compile(
    r"(error|issue|problem|bug|not\s+working)\s+.{0,30}"
    r"(with|in|using|from)\s+(react|vue|next|prisma|tailwind|zod|trpc|"
    r"express|fastapi|django|axios|tanstack|shadcn|radix)",
    re.IGNORECASE,
)

_RE_LIBRARY_SPECIFIC = re.compile(
    r"(react|vue|angular|svelte|next\.?js|nuxt|remix|astro|"
    r"prisma|drizzle|sequelize|typeorm|mongoose|"
    r"tailwind|styled-components|emotion|chakra|"
    r"redux|zustand|jotai|recoil|mobx|pinia|"
    r"zod|yup|joi|valibot|trpc|graphql|apollo|"
    r"tanstack|react-query|swr|framer-motion|"
    r"radix|headless-?ui|shadcn|mantine|"
    r"fastapi|flask|django|express|nest\.?js|"
    r"pytest|jest|vitest|playwright|cypress)\b"
    r".{0,50}(docs?|documentation|api|how|usage|example|hook|component)",
    re.IGNORECASE,
)


def check_context7_mandate(prompt: str) -> Optional[Mandate]:
    """
    Check for Context7 MCP triggers in user prompt.

    Context7 is ideal for:
    - Library/framework documentation lookup
    - API reference and code examples
    - Current/up-to-date library usage patterns
    - Specific library error troubleshooting

    Context7 is FASTER and more accurate than web search for library docs.
    """
    if len(prompt) < 10 or prompt.startswith("/"):
        return None

    # First, try smart library detection if available
    if CONTEXT7_DETECTION_AVAILABLE and detect_library_context:
        library_ctx = detect_library_context(prompt=prompt)
        if library_ctx and library_ctx.confidence >= 0.7:
            lib = library_ctx.library_name
            return Mandate(
                tool="mcp__plugin_context7_context7__resolve-library-id",
                directive=(
                    f"📚 **USE CONTEXT7**: Library `{lib}` detected. "
                    f"Use `mcp__plugin_context7_context7__resolve-library-id` with `{lib}` first, "
                    f"then `get-library-docs` for API reference and code examples. "
                    f"Context7 is FASTER than web search for library documentation."
                ),
                priority=P_HIGH,
                reason=f"Library detected: {lib}",
            )

    # Library-specific error → Context7 for troubleshooting
    if _RE_LIBRARY_ERROR.search(prompt):
        return Mandate(
            tool="mcp__plugin_context7_context7__resolve-library-id",
            directive=(
                "📚 **USE CONTEXT7**: Library error detected. "
                "Use Context7 to get current docs and code examples. "
                "Library docs often have troubleshooting sections."
            ),
            priority=P_HIGH,
            reason="Library error",
        )

    # Specific library + docs/api question → Context7
    if _RE_LIBRARY_SPECIFIC.search(prompt):
        return Mandate(
            tool="mcp__plugin_context7_context7__resolve-library-id",
            directive=(
                "📚 **USE CONTEXT7**: Library documentation request. "
                "Use `resolve-library-id` then `get-library-docs` for structured API reference. "
                "Context7 provides code snippets and current documentation."
            ),
            priority=P_MEDIUM,
            reason="Library docs request",
        )

    # General API/usage question → suggest Context7
    if _RE_LIBRARY_DOCS.search(prompt):
        return Mandate(
            tool="mcp__plugin_context7_context7__resolve-library-id",
            directive=(
                "📚 **CONSIDER CONTEXT7**: API/usage question detected. "
                "If this involves a library, use Context7 for authoritative docs. "
                "Context7 > web search for library documentation."
            ),
            priority=P_LOW,
            reason="API usage question",
        )

    return None


# =============================================================================
# SERENA MCP TRIGGERS (for semantic code analysis)
# =============================================================================

_RE_FIND_SYMBOL = re.compile(
    r"(find|where\s+is|locate|look\s+for)\s+(the\s+)?(class|function|method|def|symbol|"
    r"definition|implementation)\s+[`'\"]?(\w+)",
    re.IGNORECASE,
)

_RE_FIND_REFERENCES = re.compile(
    r"(who|what)\s+(calls?|uses?|references?|imports?)|"
    r"(find|show|list)\s+(all\s+)?(callers?|references?|usages?|uses)|"
    r"(where\s+is\s+.+\s+(called|used|referenced))|"
    r"(impact|affected)\s+(of|by)\s+(chang|modif)",
    re.IGNORECASE,
)

_RE_SYMBOL_OVERVIEW = re.compile(
    r"(what.?s\s+in|overview\s+of|structure\s+of|symbols?\s+in|"
    r"classes?\s+in|functions?\s+in|methods?\s+in)\s+.+\.(py|ts|js|java|go|rs)",
    re.IGNORECASE,
)

_RE_REFACTOR_SYMBOL = re.compile(
    r"(rename|refactor|change\s+name|update\s+name)\s+(the\s+)?"
    r"(class|function|method|variable|symbol|def)",
    re.IGNORECASE,
)

_RE_CODE_NAVIGATION = re.compile(
    r"(go\s+to|jump\s+to|navigate\s+to|show\s+me)\s+(the\s+)?"
    r"(definition|implementation|declaration|source)",
    re.IGNORECASE,
)

_RE_SEMANTIC_EDIT = re.compile(
    r"(add|insert|put)\s+(a\s+)?(method|function|class|import)\s+(to|in|into|before|after)",
    re.IGNORECASE,
)

_RE_IMPACT_ANALYSIS = re.compile(
    r"(impact|affect|break|change)\s+.*(if\s+I|when\s+I|by)\s+(chang|modif|renam|delet)|"
    r"(what\s+will\s+break|safe\s+to\s+(change|modify|rename|delete))",
    re.IGNORECASE,
)


def check_serena_mandate(prompt: str) -> Optional[Mandate]:
    """
    Check for Serena MCP triggers in user prompt.

    Serena is ideal for:
    - Symbol lookup (classes, functions, methods)
    - Finding references/callers
    - Understanding code structure
    - Semantic editing (symbol-level operations)
    - Impact analysis
    - Safe refactoring
    """
    if len(prompt) < 10 or prompt.startswith("/"):
        return None

    # Find references/callers → find_referencing_symbols
    if _RE_FIND_REFERENCES.search(prompt):
        return Mandate(
            tool="mcp__serena__find_referencing_symbols",
            directive=(
                "🔗 **USE SERENA**: Reference lookup detected. "
                "Use `mcp__serena__find_referencing_symbols` to find all callers/usages. "
                "Serena provides semantic reference tracking."
            ),
            priority=P_HIGH,
            reason="Reference lookup",
        )

    # Impact analysis → find_referencing_symbols
    if _RE_IMPACT_ANALYSIS.search(prompt):
        return Mandate(
            tool="mcp__serena__find_referencing_symbols",
            directive=(
                "⚡ **USE SERENA**: Impact analysis detected. "
                "Use `mcp__serena__find_referencing_symbols` to see what will be affected. "
                "Always check references before changing symbols."
            ),
            priority=P_HIGH,
            reason="Impact analysis",
        )

    # Find symbol/definition → find_symbol
    if _RE_FIND_SYMBOL.search(prompt):
        return Mandate(
            tool="mcp__serena__find_symbol",
            directive=(
                "🔍 **USE SERENA**: Symbol lookup detected. "
                "Use `mcp__serena__find_symbol` with name_path_pattern. "
                "Serena finds symbols semantically, not just text search."
            ),
            priority=P_MEDIUM,
            reason="Symbol lookup",
        )

    # Symbol overview → get_symbols_overview
    if _RE_SYMBOL_OVERVIEW.search(prompt):
        return Mandate(
            tool="mcp__serena__get_symbols_overview",
            directive=(
                "📋 **USE SERENA**: File structure request detected. "
                "Use `mcp__serena__get_symbols_overview` for symbol listing. "
                "Shows classes, functions, methods without reading entire file."
            ),
            priority=P_MEDIUM,
            reason="Symbol overview",
        )

    # Refactor/rename → rename_symbol
    if _RE_REFACTOR_SYMBOL.search(prompt):
        return Mandate(
            tool="mcp__serena__rename_symbol",
            directive=(
                "♻️ **USE SERENA**: Symbol rename detected. "
                "Use `mcp__serena__rename_symbol` for safe refactoring. "
                "Serena renames across entire codebase with reference updates."
            ),
            priority=P_HIGH,
            reason="Symbol rename",
        )

    # Code navigation → find_symbol with include_body
    if _RE_CODE_NAVIGATION.search(prompt):
        return Mandate(
            tool="mcp__serena__find_symbol",
            directive=(
                "🧭 **USE SERENA**: Code navigation detected. "
                "Use `mcp__serena__find_symbol` with `include_body=True`. "
                "Serena locates definitions precisely."
            ),
            priority=P_MEDIUM,
            reason="Code navigation",
        )

    # Semantic editing → insert_before/after_symbol
    if _RE_SEMANTIC_EDIT.search(prompt):
        return Mandate(
            tool="mcp__serena__insert_after_symbol",
            directive=(
                "✏️ **USE SERENA**: Semantic edit detected. "
                "Use `mcp__serena__insert_after_symbol` or `insert_before_symbol`. "
                "Serena inserts code at precise symbol boundaries."
            ),
            priority=P_MEDIUM,
            reason="Semantic edit",
        )

    return None


# =============================================================================
# PAL ANALYZE TRIGGERS (for code analysis and understanding)
# =============================================================================

_RE_CODE_ANALYSIS = re.compile(
    r"(analyz|understand|explain|how\s+does|what\s+does|break\s*down|"
    r"walk\s+through|trace|follow|diagram|map\s+out)\s+"
    r".{0,30}(code|function|class|method|logic|flow|implementation)",
    re.IGNORECASE,
)

_RE_PERFORMANCE_ANALYSIS = re.compile(
    r"(performance|slow|fast|optimi[sz]|bottleneck|profile|benchmark|"
    r"memory|cpu|latency|throughput|n\+1|query\s+count)",
    re.IGNORECASE,
)

_RE_QUALITY_ANALYSIS = re.compile(
    r"(quality|maintainab|readab|clean|smell|debt|pattern|anti.?pattern|"
    r"solid|dry|kiss|yagni|coupling|cohesion)",
    re.IGNORECASE,
)


def check_analyze_mandate(prompt: str) -> Optional[Mandate]:
    """
    Check for PAL Analyze MCP triggers in user prompt.

    PAL Analyze is ideal for:
    - Code understanding and explanation
    - Performance analysis
    - Quality/maintainability analysis
    - Architecture review
    """
    if len(prompt) < 10 or prompt.startswith("/"):
        return None

    # Performance analysis → analyze with performance focus
    if _RE_PERFORMANCE_ANALYSIS.search(prompt):
        return Mandate(
            tool="mcp__pal__analyze",
            directive=(
                "⚡ **USE PAL ANALYZE**: Performance analysis detected. "
                'Use `mcp__pal__analyze` with `analysis_type="performance"`. '
                "External analysis catches bottlenecks you might miss."
            ),
            priority=P_MEDIUM,
            reason="Performance analysis",
        )

    # Quality analysis → analyze with quality focus
    if _RE_QUALITY_ANALYSIS.search(prompt):
        return Mandate(
            tool="mcp__pal__analyze",
            directive=(
                "🔍 **USE PAL ANALYZE**: Quality analysis detected. "
                'Use `mcp__pal__analyze` with `analysis_type="quality"`. '
                "External perspective on code quality is valuable."
            ),
            priority=P_MEDIUM,
            reason="Quality analysis",
        )

    # General code analysis → analyze
    if _RE_CODE_ANALYSIS.search(prompt):
        return Mandate(
            tool="mcp__pal__analyze",
            directive=(
                "🧠 **USE PAL ANALYZE**: Code analysis request detected. "
                "Use `mcp__pal__analyze` for comprehensive understanding. "
                "External analysis provides structured insights."
            ),
            priority=P_LOW,
            reason="Code analysis",
        )

    return None


# =============================================================================
# PAL CHALLENGE TRIGGERS (for assumption testing)
# =============================================================================

_RE_ASSUMPTION = re.compile(
    r"(assum|believ|think\s+that|pretty\s+sure|probably|"
    r"should\s+be|must\s+be|likely|expect|suppos)",
    re.IGNORECASE,
)

_RE_CLAIM = re.compile(
    r"(this\s+will|this\s+should|this\s+is\s+the\s+best|"
    r"obviously|clearly|definitely|certainly|always|never|"
    r"the\s+only\s+way|no\s+other\s+way)",
    re.IGNORECASE,
)

_RE_PUSHBACK = re.compile(
    r"(are\s+you\s+sure|really\?|but\s+what\s+about|"
    r"have\s+you\s+considered|what\s+if|couldn.t\s+we|"
    r"why\s+not|disagree|don.t\s+think\s+so)",
    re.IGNORECASE,
)


def check_challenge_mandate(
    prompt: str, is_claude_output: bool = False
) -> Optional[Mandate]:
    """
    Check for PAL Challenge MCP triggers.

    PAL Challenge is ideal for:
    - Testing assumptions before acting on them
    - Validating claims and statements
    - Responding to user pushback thoughtfully
    - Preventing reflexive agreement
    """
    if len(prompt) < 10 or prompt.startswith("/"):
        return None

    # User pushback → challenge to avoid sycophancy
    if _RE_PUSHBACK.search(prompt):
        return Mandate(
            tool="mcp__pal__challenge",
            directive=(
                "🤔 **USE PAL CHALLENGE**: User pushback detected. "
                "Use `mcp__pal__challenge` to critically analyze your position. "
                "Avoid reflexive agreement - test your reasoning first."
            ),
            priority=P_HIGH,
            reason="User pushback",
        )

    # Strong claims in Claude output → challenge before proceeding
    if is_claude_output and _RE_CLAIM.search(prompt):
        return Mandate(
            tool="mcp__pal__challenge",
            directive=(
                "⚠️ **USE PAL CHALLENGE**: Strong claim detected. "
                "Use `mcp__pal__challenge` to validate before asserting. "
                "Challenge overconfident statements."
            ),
            priority=P_MEDIUM,
            reason="Strong claim",
        )

    # Assumptions → suggest challenge
    if _RE_ASSUMPTION.search(prompt) and len(prompt) > 50:
        return Mandate(
            tool="mcp__pal__challenge",
            directive=(
                "💡 **CONSIDER PAL CHALLENGE**: Assumption detected. "
                "Consider `mcp__pal__challenge` to test this assumption. "
                "Untested assumptions can lead to wasted effort."
            ),
            priority=P_LOW,
            reason="Assumption detected",
        )

    return None


# =============================================================================
# PAL PRECOMMIT TRIGGERS (for git commit validation)
# =============================================================================

_RE_GIT_COMMIT = re.compile(
    r"(git\s+commit|commit\s+(?:the\s+)?changes?|ready\s+to\s+commit|"
    r"let.?s\s+commit|make\s+a\s+commit|create\s+(?:a\s+)?commit)",
    re.IGNORECASE,
)

_RE_PR_CREATE = re.compile(
    r"(create\s+(?:a\s+)?(?:pull\s+request|pr)|open\s+(?:a\s+)?pr|"
    r"submit\s+(?:a\s+)?pr|gh\s+pr\s+create|ready\s+for\s+(?:review|pr))",
    re.IGNORECASE,
)


def check_precommit_mandate(
    prompt: str, has_staged_changes: bool = True
) -> Optional[Mandate]:
    """
    Check for PAL Precommit MCP triggers.

    PAL Precommit is ideal for:
    - Validating changes before commit
    - Security review of staged changes
    - Ensuring completeness (tests, docs)
    - Catching issues before they enter history
    """
    if len(prompt) < 10 or prompt.startswith("/"):
        return None

    # PR creation → precommit validation
    if _RE_PR_CREATE.search(prompt):
        return Mandate(
            tool="mcp__pal__precommit",
            directive=(
                "🔍 **USE PAL PRECOMMIT**: PR creation detected. "
                "Use `mcp__pal__precommit` to validate changes before PR. "
                "Catches issues before review - saves time."
            ),
            priority=P_HIGH,
            reason="PR creation",
        )

    # Git commit → precommit validation
    if _RE_GIT_COMMIT.search(prompt) and has_staged_changes:
        return Mandate(
            tool="mcp__pal__precommit",
            directive=(
                "✅ **USE PAL PRECOMMIT**: Commit intent detected. "
                "Use `mcp__pal__precommit` to validate changes. "
                "Verify security, completeness, and quality before commit."
            ),
            priority=P_MEDIUM,
            reason="Git commit",
        )

    return None


# =============================================================================
# CODE-MODE TRIGGERS (for multi-tool chaining)
# =============================================================================

_RE_MULTI_TOOL = re.compile(
    r"(then\s+(use|call|run|execute)|after\s+that|next\s+step|"
    r"first\s+.+\s+then|step\s*\d|chain|sequence|pipeline|"
    r"multiple\s+(tools?|steps?|calls?)|orchestrat|automat)",
    re.IGNORECASE,
)

_RE_BATCH_OPERATIONS = re.compile(
    r"(for\s+each|all\s+(?:the\s+)?files?|every\s+(?:file|item|entry)|"
    r"batch|bulk|mass|iterate|loop\s+through|process\s+all)",
    re.IGNORECASE,
)

_RE_CONDITIONAL_FLOW = re.compile(
    r"(if\s+.+\s+then|based\s+on\s+(?:the\s+)?result|depending\s+on|"
    r"when\s+.+\s+(?:do|run|execute)|conditionally|branching)",
    re.IGNORECASE,
)

_RE_DATA_TRANSFORM = re.compile(
    r"(extract\s+.+\s+(?:and|then)|parse\s+.+\s+(?:and|then)|"
    r"transform|convert\s+.+\s+to|map\s+.+\s+to|filter\s+.+\s+(?:and|then))",
    re.IGNORECASE,
)

_RE_TOOL_MENTIONS = re.compile(
    r"(mcp__|serena|repomix|crawl4ai|playwright|pal__|"
    r"grep\s+.+\s+then|read\s+.+\s+then|search\s+.+\s+then)",
    re.IGNORECASE,
)


def check_codemode_mandate(
    prompt: str,
    mastermind_classification: str | None = None,
    tool_count_estimate: int = 0,
) -> Optional[Mandate]:
    """
    Check for code-mode triggers in user prompt.

    Code-mode is ideal for:
    - Multi-tool orchestration (67-88% efficiency improvement)
    - Batch operations across files/items
    - Conditional workflows with branching
    - Data transformation pipelines
    - Complex automation sequences

    Code-mode lets Claude write code that chains tool calls instead of
    sequential API round-trips. The code has access to all MCP tools
    as namespaced functions.

    Args:
        prompt: User's prompt text
        mastermind_classification: Optional classification from Mastermind router
        tool_count_estimate: Estimated number of tools needed

    Returns:
        Mandate if code-mode should be suggested, None otherwise
    """
    if len(prompt) < 20 or prompt.startswith("/"):
        return None

    # Count signals for code-mode appropriateness
    signals = 0
    reasons = []

    # Strong signals
    if _RE_MULTI_TOOL.search(prompt):
        signals += 2
        reasons.append("multi-tool sequence")

    if _RE_BATCH_OPERATIONS.search(prompt):
        signals += 2
        reasons.append("batch operations")

    if _RE_CONDITIONAL_FLOW.search(prompt):
        signals += 2
        reasons.append("conditional flow")

    # Medium signals
    if _RE_DATA_TRANSFORM.search(prompt):
        signals += 1
        reasons.append("data transformation")

    if _RE_TOOL_MENTIONS.search(prompt):
        signals += 1
        reasons.append("explicit tool mentions")

    # Mastermind boost
    if mastermind_classification in ("medium", "complex"):
        signals += 1
        reasons.append(f"mastermind:{mastermind_classification}")

    # Tool count boost
    if tool_count_estimate >= 3:
        signals += 1
        reasons.append(f"{tool_count_estimate}+ tools estimated")

    # Decision thresholds
    if signals >= 3:
        # Strong recommendation
        return Mandate(
            tool="codemode_executor",
            directive=(
                "⚡ **USE CODE-MODE**: Multi-tool orchestration detected. "
                f"Signals: {', '.join(reasons)}. "
                "Write Python code that chains tool calls instead of sequential invocations. "
                "Code-mode provides 67-88% efficiency improvement for multi-tool tasks. "
                "Available tools: All MCP tools as `namespace.tool_name()` functions."
            ),
            priority=P_HIGH,
            reason=f"Code-mode signals: {', '.join(reasons)}",
        )

    if signals >= 2:
        # Moderate recommendation
        return Mandate(
            tool="codemode_executor",
            directive=(
                "💡 **CONSIDER CODE-MODE**: Multi-step task detected. "
                f"Signals: {', '.join(reasons)}. "
                "For complex tool chaining, consider writing code instead of sequential calls. "
                "Code-mode reduces API round-trips significantly."
            ),
            priority=P_PROACTIVE,
            reason=f"Code-mode signals: {', '.join(reasons)}",
        )

    return None


# =============================================================================
# SUMMARY: Mandate Thresholds (v2.0 - AGGRESSIVE)
# =============================================================================
#
# CONFIDENCE-BASED (always fire):
# | Condition              | Tool           | Priority | Confidence Range |
# |------------------------|----------------|----------|------------------|
# | confidence < 50        | thinkdeep      | CRITICAL | 0-49             |
# | cascade_failure        | thinkdeep      | CRITICAL | any              |
# | sunk_cost              | thinkdeep      | CRITICAL | any              |
# | confidence 50-70       | thinkdeep      | HIGH     | 50-69            |
# | edit_oscillation       | codereview     | HIGH     | any              |
# | goal_drift             | planner        | HIGH     | any              |
# | failures >= 2          | debug          | HIGH     | any              |
# | confidence 70-85       | chat           | LOW      | 70-84 (proactive)|
#
# INTENT-BASED (fire at ANY confidence):
# | Intent                 | Tool           | Priority |
# |------------------------|----------------|----------|
# | debug                  | debug          | MEDIUM   |
# | code_review            | codereview     | MEDIUM   |
# | refactor               | codereview     | MEDIUM   |
# | implement              | planner        | PROACTIVE|
# | architecture           | consensus      | HIGH     |
#
# KEYWORD-BASED (fire on pattern match):
# | Keywords               | Tool           | Priority |
# |------------------------|----------------|----------|
# | architect/migrate/etc  | consensus      | HIGH     |
# | should/which/compare   | consensus      | MEDIUM   |
# | debug/fix/broken/etc   | debug          | MEDIUM   |
# | uncertain/unsure/etc   | thinkdeep      | MEDIUM   |
# | complex/difficult/etc  | planner        | PROACTIVE|
# | review/audit/check     | codereview     | PROACTIVE|
# | api/docs/library       | apilookup      | LOW      |
# | implement/build/create | planner        | LOW      |
#
