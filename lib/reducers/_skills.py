#!/usr/bin/env python3
"""Confidence reducers: skill usage enforcement (v4.27).

These reducers penalize patterns where Skills should have been used
instead of manual tool sequences - maximizing framework leverage.

Skill Economy Philosophy:
- Skills encapsulate best practices and multi-step workflows
- Using Skill tool = documented, tested, optimal approach
- Manual sequences = reinventing the wheel, error-prone
- Skills often spawn agents internally = double context savings
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ._base import ConfidenceReducer, IMPACT_BEHAVIORAL

if TYPE_CHECKING:
    from session_state import SessionState


@dataclass
class ResearchWithoutDocsSkillReducer(ConfidenceReducer):
    """Triggers when doing library research without /docs skill.

    Pattern: Multiple WebSearch/WebFetch for library documentation
    Solution: /docs <library> uses Context7 for authoritative docs

    The /docs skill:
    - Uses Context7 MCP for curated, up-to-date documentation
    - Returns code examples, not just text
    - Avoids hallucinated API patterns from web search
    """

    name: str = "research_without_docs_skill"
    delta: int = -4
    description: str = "Library research without /docs - use Context7"
    remedy: str = "Skill(skill='docs', args='<library>')"
    cooldown_turns: int = 6
    impact_category: str = IMPACT_BEHAVIORAL

    # Patterns suggesting library documentation lookup
    LIBRARY_PATTERNS = {
        "react",
        "nextjs",
        "tailwind",
        "typescript",
        "python",
        "fastapi",
        "django",
        "express",
        "prisma",
        "supabase",
        "vercel",
        "vite",
        "playwright",
        "jest",
        "pytest",
        "ruff",
    }

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.get_effective_cooldown(state):
            return False

        # Check for library documentation searches without /docs
        research_for_docs = getattr(state, "research_for_library_docs", False)
        recent_docs_skill = getattr(state, "recent_docs_skill_turn", -100)

        if state.turn_count - recent_docs_skill < 10:
            return False  # Recently used /docs, exempt

        return research_for_docs


@dataclass
class DebuggingWithoutThinkSkillReducer(ConfidenceReducer):
    """Triggers when stuck debugging without /think skill.

    Pattern: 3+ debug attempts without problem decomposition
    Solution: /think "<problem>" for structured reasoning

    The /think skill:
    - Forces structured problem decomposition
    - Surfaces assumptions and blind spots
    - Often reveals the actual issue before more attempts
    """

    name: str = "debugging_without_think_skill"
    delta: int = -5
    description: str = "Stuck debugging without /think - decompose first"
    remedy: str = "Skill(skill='think', args='Debug: <problem description>')"
    cooldown_turns: int = 8
    impact_category: str = IMPACT_BEHAVIORAL

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.get_effective_cooldown(state):
            return False

        # Check for extended debugging without /think
        debug_attempts = getattr(state, "consecutive_debug_attempts", 0)
        recent_think_skill = getattr(state, "recent_think_skill_turn", -100)

        if state.turn_count - recent_think_skill < 15:
            return False

        return debug_attempts >= 3


@dataclass
class CommitWithoutSkillReducer(ConfidenceReducer):
    """Triggers when committing manually without /commit skill.

    Pattern: Raw `git commit` without /commit workflow
    Solution: /commit handles staging, message generation, verification

    The /commit skill:
    - Auto-generates meaningful commit messages
    - Runs pre-commit checks
    - Handles staging intelligently
    - Follows project commit conventions
    """

    name: str = "commit_without_skill"
    delta: int = -3
    description: str = "Manual git commit - use /commit skill"
    remedy: str = "Skill(skill='commit')"
    cooldown_turns: int = 5
    impact_category: str = IMPACT_BEHAVIORAL

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.get_effective_cooldown(state):
            return False

        # Detect manual git commit (tracked in state)
        manual_commit_detected = context.get("manual_git_commit", False)
        recent_commit_skill = getattr(state, "recent_commit_skill_turn", -100)

        if state.turn_count - recent_commit_skill < 5:
            return False

        return manual_commit_detected


@dataclass
class FrameworkEditWithoutAuditReducer(ConfidenceReducer):
    """Triggers when editing framework files without /audit + /void.

    Pattern: Editing .claude/ops/, .claude/hooks/, .claude/lib/ without verification
    Solution: Run /audit and /void before committing framework changes

    These skills:
    - /audit: Security and quality scan
    - /void: Completeness check (stubs, gaps, missing error handling)
    - Together ensure framework integrity
    """

    name: str = "framework_edit_without_audit"
    delta: int = -6
    description: str = "Framework edit without /audit + /void verification"
    remedy: str = "Run audit.py and void.py before committing"
    cooldown_turns: int = 10
    impact_category: str = IMPACT_BEHAVIORAL

    FRAMEWORK_PATHS = {
        ".claude/ops/",
        ".claude/hooks/",
        ".claude/lib/",
        ".claude/rules/",
    }

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.get_effective_cooldown(state):
            return False

        # Check for framework file edits without audit/void
        framework_edited = getattr(state, "framework_files_edited", [])
        recent_audit = getattr(state, "recent_audit_turn", -100)
        recent_void = getattr(state, "recent_void_turn", -100)

        if not framework_edited:
            return False

        # If audit OR void run recently, exempt
        if state.turn_count - recent_audit < 15 or state.turn_count - recent_void < 15:
            return False

        return len(framework_edited) >= 1


@dataclass
class VerificationWithoutSkillReducer(ConfidenceReducer):
    """Triggers when claiming fixes without /verify skill.

    Pattern: Saying "fixed" without running verification
    Solution: /verify file_exists|grep_text|command_success

    The /verify skill:
    - Provides mechanical verification of claims
    - Prevents reward hacking ("it's fixed" without proof)
    - Builds evidence for completion
    """

    name: str = "verification_without_skill"
    delta: int = -4
    description: str = "Claiming 'fixed' without /verify - prove it"
    remedy: str = "Skill(skill='verify', args='command_success \"<test command>\"')"
    cooldown_turns: int = 5
    impact_category: str = IMPACT_BEHAVIORAL

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.get_effective_cooldown(state):
            return False

        # Check for fix claims without verification
        fix_claimed = context.get("fix_claimed_without_verification", False)
        recent_verify_skill = getattr(state, "recent_verify_skill_turn", -100)

        if state.turn_count - recent_verify_skill < 8:
            return False

        return fix_claimed


@dataclass
class CodeExplorationWithoutSerenaReducer(ConfidenceReducer):
    """Triggers when exploring code without Serena activation.

    Pattern: Multiple Read/Grep on code files without semantic tools
    Solution: Activate Serena for semantic code understanding

    Serena provides:
    - Symbol-level navigation (find_symbol, find_referencing_symbols)
    - Impact analysis before changes
    - Project memories for context
    - More accurate than text-based search
    """

    name: str = "code_exploration_without_serena"
    delta: int = -3
    description: str = (
        "Code exploration without Serena - activate for semantic analysis"
    )
    remedy: str = "mcp__serena__activate_project('.') then use symbolic tools"
    cooldown_turns: int = 10
    impact_category: str = IMPACT_BEHAVIORAL

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.get_effective_cooldown(state):
            return False

        # Check for code exploration without Serena
        code_reads = getattr(state, "consecutive_code_file_reads", 0)
        serena_active = getattr(state, "serena_active", False)

        if serena_active:
            return False  # Serena is active, exempt

        return code_reads >= 4


__all__ = [
    "ResearchWithoutDocsSkillReducer",
    "DebuggingWithoutThinkSkillReducer",
    "CommitWithoutSkillReducer",
    "FrameworkEditWithoutAuditReducer",
    "VerificationWithoutSkillReducer",
    "CodeExplorationWithoutSerenaReducer",
]
