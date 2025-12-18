#!/usr/bin/env python3
"""
Confidence Increasers - Reward signals for good behavior.

Increasers fire on positive signals like tests passing, research, etc.
Subject to diminishing returns to prevent farming.
"""

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from session_state import SessionState

# =============================================================================


@dataclass
class ConfidenceIncreaser:
    """A confidence increaser that fires on success signals."""

    name: str
    delta: int  # Positive value
    description: str
    requires_approval: bool = False
    cooldown_turns: int = 1

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        """Check if this increaser should fire. Override in subclasses."""
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        return False


@dataclass
class PassedTestsIncreaser(ConfidenceIncreaser):
    """Triggers when tests pass."""

    name: str = "test_pass"
    delta: int = 5
    description: str = "Tests passed successfully"
    requires_approval: bool = False
    cooldown_turns: int = 1

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        # Check context from post_tool_use_runner (output-based detection)
        if context.get("tests_passed"):
            return True
        # Check recent commands for test passes
        for cmd in state.commands_succeeded[-5:]:
            cmd_str = cmd.get("command", "").lower()
            output = cmd.get("output", "").lower()
            # Command-based: actual test runners
            if any(t in cmd_str for t in ["pytest", "jest", "cargo test", "npm test"]):
                return True
            # Output-based: success patterns in output
            if any(p in output for p in ["passed", "tests passed", "success", "✓"]):
                return True
        return False


@dataclass
class BuildSuccessIncreaser(ConfidenceIncreaser):
    """Triggers when builds succeed."""

    name: str = "build_success"
    delta: int = 5
    description: str = "Build completed successfully"
    requires_approval: bool = False
    cooldown_turns: int = 1
    # Strict patterns - must be actual build commands, not substrings
    build_commands: list = field(
        default_factory=lambda: [
            "npm run build",
            "npm build",
            "yarn build",
            "pnpm build",
            "cargo build",
            "cargo test",  # Rust tests are builds
            "go build",
            "go test",
            "tsc",
            "webpack",
            "vite build",
            "next build",
            "make all",
            "make build",
            "cmake --build",
            "gradle build",
            "mvn package",
            "dotnet build",
        ]
    )

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        # Check context from post_tool_use_runner (output-based detection)
        if context.get("build_succeeded"):
            return True
        # Check recent commands for builds
        for cmd in state.commands_succeeded[-5:]:
            cmd_str = cmd.get("command", "").lower()
            output = cmd.get("output", "").lower()
            # Command-based: actual build commands
            if any(
                cmd_str.startswith(t) or f" {t}" in cmd_str for t in self.build_commands
            ):
                return True
            # Output-based: build success patterns in output
            if any(p in output for p in ["built", "compiled", "build successful"]):
                return True
        return False


@dataclass
class UserOkIncreaser(ConfidenceIncreaser):
    """Triggers on positive user feedback.

    Reduced from +5 to +2: Generic politeness ("ok", "thanks") shouldn't
    inflate confidence as much as objective signals (tests, builds).
    For specific acceptance ("that fixed it"), user can say CONFIDENCE_BOOST_APPROVED.
    """

    name: str = "user_ok"
    delta: int = 2  # Reduced from 5 - generic politeness < objective signals
    description: str = "User confirmed correctness"
    requires_approval: bool = False
    cooldown_turns: int = 2
    patterns: list = field(
        default_factory=lambda: [
            r"\b(?:looks?\s+)?good\b",
            r"\bok(?:ay)?\b",
            r"\bcorrect\b",
            r"\bperfect\b",
            r"\bnice\b",
            r"\bthanks?\b",
            r"\byes\b",
        ]
    )

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        prompt = context.get("prompt", "").lower().strip()
        # Short positive responses only (avoid false positives in long prompts)
        # Allow up to 100 chars for "thanks, looks good - also check tests" type messages
        if len(prompt) > 100:
            return False
        for pattern in self.patterns:
            if re.search(pattern, prompt, re.IGNORECASE):
                return True
        return False


@dataclass
class TrustRegainedIncreaser(ConfidenceIncreaser):
    """Triggers on explicit trust restoration request (requires approval)."""

    name: str = "trust_regained"
    delta: int = 15
    description: str = "User explicitly restored trust"
    requires_approval: bool = True
    cooldown_turns: int = 5
    trigger_patterns: list = field(
        default_factory=lambda: [
            r"\btrust\s+regained\b",
            r"\bconfidence\s+(?:restored|boost(?:ed)?)\b",
            r"\bCONFIDENCE_BOOST_APPROVED\b",
        ]
    )

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        prompt = context.get("prompt", "")
        for pattern in self.trigger_patterns:
            if re.search(pattern, prompt, re.IGNORECASE):
                return True
        return False


# =============================================================================
# NATURAL INCREASERS (balance the natural decay)
# =============================================================================


@dataclass
class FileReadIncreaser(ConfidenceIncreaser):
    """Triggers on file reads - gathering evidence increases confidence."""

    name: str = "file_read"
    delta: int = 1
    description: str = "Gathered evidence by reading files"
    requires_approval: bool = False
    cooldown_turns: int = 0  # Can fire every turn

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        # Check if files were read this turn
        files_read_count = context.get("files_read_count", 0)
        return files_read_count > 0


@dataclass
class ResearchIncreaser(ConfidenceIncreaser):
    """Triggers on web research - due diligence increases confidence."""

    name: str = "research"
    delta: int = 2
    description: str = "Performed web research"
    requires_approval: bool = False
    cooldown_turns: int = 1

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        # Check for research tools used
        return context.get("research_performed", False)


@dataclass
class AskUserIncreaser(ConfidenceIncreaser):
    """Triggers when asking user for clarification - epistemic humility.

    Reduced from +20 to +8 with longer cooldown to prevent question-spam gaming.
    """

    name: str = "ask_user"
    delta: int = 8  # Reduced from 20 - prevents gaming via question spam
    description: str = "Consulted user for clarification"
    requires_approval: bool = False
    cooldown_turns: int = 8  # Increased from 2 - can't farm questions

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        return context.get("asked_user", False)


@dataclass
class RulesUpdateIncreaser(ConfidenceIncreaser):
    """Triggers when updating CLAUDE.md or /rules - improving the system.

    HUGE boost because these files are the "DNA" of the framework:
    - CLAUDE.md defines behavior, principles, and hard blocks
    - /rules/ contains confidence system, beads, hooks, etc.
    Improving these files has outsized impact across all future sessions.
    """

    name: str = "rules_update"
    delta: int = 15  # Boosted from 3 - these files are critical
    description: str = "Updated framework DNA (CLAUDE.md or /rules/)"
    requires_approval: bool = False
    cooldown_turns: int = 1  # Reduced - encourage frequent rule improvements

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        return context.get("rules_updated", False)


@dataclass
class CustomScriptIncreaser(ConfidenceIncreaser):
    """Triggers when running custom ops scripts - HUGE boost for using tools."""

    name: str = "custom_script"
    delta: int = 5
    description: str = "Ran custom ops script"
    requires_approval: bool = False
    cooldown_turns: int = 1

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        return context.get("custom_script_ran", False)


@dataclass
class LintPassIncreaser(ConfidenceIncreaser):
    """Triggers when linting passes."""

    name: str = "lint_pass"
    delta: int = 3
    description: str = "Lint check passed"
    requires_approval: bool = False
    cooldown_turns: int = 1

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        if context.get("lint_passed"):
            return True
        # Check recent commands
        for cmd in state.commands_succeeded[-3:]:
            cmd_str = cmd.get("command", "").lower()
            if any(t in cmd_str for t in ["ruff check", "eslint", "clippy", "pylint"]):
                return True
        return False


@dataclass
class MemoryConsultIncreaser(ConfidenceIncreaser):
    """Triggers when consulting memory files - leveraging accumulated knowledge."""

    name: str = "memory_consult"
    delta: int = 10
    description: str = "Consulted persistent memory"
    requires_approval: bool = False
    cooldown_turns: int = 2

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        return context.get("memory_consulted", False)


@dataclass
class BeadCreateIncreaser(ConfidenceIncreaser):
    """Triggers when creating beads - planning and tracking work."""

    name: str = "bead_create"
    delta: int = 10
    description: str = "Created task tracking bead"
    requires_approval: bool = False
    cooldown_turns: int = 1

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        return context.get("bead_created", False)


@dataclass
class SearchToolIncreaser(ConfidenceIncreaser):
    """Triggers when using search tools - gathering understanding."""

    name: str = "search_tool"
    delta: int = 2
    description: str = "Used search tool (Grep/Glob/Task)"
    requires_approval: bool = False
    cooldown_turns: int = 1

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        return context.get("search_performed", False)


@dataclass
class ProductiveBashIncreaser(ConfidenceIncreaser):
    """Triggers on productive, non-risky bash commands.

    v4.13: Increased cooldown to prevent pwd/ls spam gaming.
    """

    name: str = "productive_bash"
    delta: int = 1
    description: str = "Ran productive bash command"
    requires_approval: bool = False
    cooldown_turns: int = 3  # v4.13: Prevent gaming via inspection spam
    # Non-risky productive commands
    productive_patterns: list = field(
        default_factory=lambda: [
            r"^ls\b",
            r"^pwd$",
            r"^which\b",
            r"^type\b",
            r"^file\b",
            r"^wc\b",
            r"^du\b",
            r"^df\b",
            r"^env\b",
            r"^echo\s+\$",  # Variable inspection
            r"^cat\b.*\|\s*(head|tail|grep)",  # Piped inspection
            r"^tree\b",
            r"^find\b.*-name",  # Finding files
            r"^stat\b",
        ]
    )

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        return context.get("productive_bash", False)


@dataclass
class SmallDiffIncreaser(ConfidenceIncreaser):
    """Triggers when diffs are under 400 LOC - focused changes."""

    name: str = "small_diff"
    delta: int = 3
    description: str = "Small diff (<400 LOC) - focused change"
    requires_approval: bool = False
    cooldown_turns: int = 1

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        return context.get("small_diff", False)


@dataclass
class GitExploreIncreaser(ConfidenceIncreaser):
    """Triggers when exploring git history - understanding context.

    Reduced from +10 to +3 with longer cooldown - process hygiene, not evidence.
    """

    name: str = "git_explore"
    delta: int = 3  # Reduced from 10 - prevent farming
    description: str = "Explored git history/state"
    requires_approval: bool = False
    cooldown_turns: int = 5  # Increased from 2 - diminishing returns

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        return context.get("git_explored", False)


# NOTE: GitCommitIncreaser REMOVED (v4.13)
# Commits are auto-handled by hooks - rewarding them was a reward hacking vector.
# Manual commits now trigger ManualCommitReducer (-1) in _confidence_reducers.py

# =============================================================================
# TIME SAVER INCREASERS (Reward efficient patterns)
# =============================================================================


@dataclass
class ParallelToolsIncreaser(ConfidenceIncreaser):
    """Triggers when using multiple tools in parallel (same message).

    Efficient use of parallelism saves time and context.
    v4.13: Reduced delta 3→2, added cooldown to prevent performative parallelism.
    """

    name: str = "parallel_tools"
    delta: int = 2  # v4.13: Reduced from 3 - prevent performative parallelism
    description: str = "Used parallel tool calls efficiently"
    requires_approval: bool = False
    cooldown_turns: int = 2  # v4.13: Prevent gaming via trivial parallel calls

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        return context.get("parallel_tools", False)


@dataclass
class EfficientSearchIncreaser(ConfidenceIncreaser):
    """Triggers when search finds target on first try.

    Efficient searching demonstrates codebase understanding.
    """

    name: str = "efficient_search"
    delta: int = 2
    description: str = "Found target on first search attempt"
    requires_approval: bool = False
    cooldown_turns: int = 2

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        return context.get("efficient_search", False)


@dataclass
class BatchFixIncreaser(ConfidenceIncreaser):
    """Triggers when fixing multiple issues in single edit.

    Batch operations are more efficient than one-at-a-time.
    """

    name: str = "batch_fix"
    delta: int = 3
    description: str = "Fixed multiple issues in single edit"
    requires_approval: bool = False
    cooldown_turns: int = 1

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        return context.get("batch_fix", False)


@dataclass
class DirectActionIncreaser(ConfidenceIncreaser):
    """Triggers when taking direct action without preamble.

    Direct action saves tokens and time vs verbose explanations.
    """

    name: str = "direct_action"
    delta: int = 2
    description: str = "Took direct action without preamble"
    requires_approval: bool = False
    cooldown_turns: int = 2

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        return context.get("direct_action", False)


@dataclass
class ChainedCommandsIncreaser(ConfidenceIncreaser):
    """Triggers when chaining related commands with && or ;.

    Chaining saves round trips and demonstrates planning.
    """

    name: str = "chained_commands"
    delta: int = 1
    description: str = "Chained related commands efficiently"
    requires_approval: bool = False
    cooldown_turns: int = 1

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        return context.get("chained_commands", False)


@dataclass
class TargetedReadIncreaser(ConfidenceIncreaser):
    """Triggers when using offset/limit on Read for large files.

    Reading targeted sections saves tokens vs reading entire file.
    """

    name: str = "targeted_read"
    delta: int = 2
    description: str = "Used targeted read (offset/limit) for efficiency"
    requires_approval: bool = False
    cooldown_turns: int = 1

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        return context.get("targeted_read", False)


@dataclass
class SubagentDelegationIncreaser(ConfidenceIncreaser):
    """Triggers when using Task(Explore) for open-ended exploration.

    Delegating exploration to subagents saves main context window.
    """

    name: str = "subagent_delegation"
    delta: int = 2
    description: str = "Delegated exploration to subagent (context saved)"
    requires_approval: bool = False
    cooldown_turns: int = 2

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        return context.get("subagent_delegation", False)


@dataclass
class PremiseChallengeIncreaser(ConfidenceIncreaser):
    """Triggers when suggesting existing solutions instead of building from scratch.

    Challenging the build-vs-buy premise saves time and prevents wheel reinvention.
    Rewards "thinking outside the box" by suggesting alternatives.
    """

    name: str = "premise_challenge"
    delta: int = 5
    description: str = "Suggested existing solution or challenged build-vs-buy"
    requires_approval: bool = False
    cooldown_turns: int = 3

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        return context.get("premise_challenge", False)


# =============================================================================
# COMPLETION QUALITY INCREASERS (Reward good outcomes)
# =============================================================================


@dataclass
class BeadCloseIncreaser(ConfidenceIncreaser):
    """Triggers when closing a bead (completing tracked work).

    Completing tracked tasks demonstrates follow-through.
    """

    name: str = "bead_close"
    delta: int = 5
    description: str = "Closed bead (completed tracked work)"
    requires_approval: bool = False
    cooldown_turns: int = 1

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        # Detect bd close commands
        for cmd in state.commands_succeeded[-3:]:
            cmd_str = cmd.get("command", "").lower()
            if "bd close" in cmd_str or "bd update" in cmd_str and "closed" in cmd_str:
                return True
        return context.get("bead_close", False)


@dataclass
class FirstAttemptSuccessIncreaser(ConfidenceIncreaser):
    """Triggers when task completed without retry/correction.

    Getting it right first time demonstrates competence.
    """

    name: str = "first_attempt_success"
    delta: int = 3
    description: str = "Task completed on first attempt"
    requires_approval: bool = False
    cooldown_turns: int = 3

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        # Context-based: set by hooks when detecting clean completion
        return context.get("first_attempt_success", False)


@dataclass
class DeadCodeRemovalIncreaser(ConfidenceIncreaser):
    """Triggers when deleting unused code/imports.

    Cleanup improves codebase health.
    """

    name: str = "dead_code_removal"
    delta: int = 3
    description: str = "Removed dead/unused code"
    requires_approval: bool = False
    cooldown_turns: int = 1
    patterns: list = field(
        default_factory=lambda: [
            r"removed?\s+(?:unused|dead)\s+(?:code|import|function|class|variable)",
            r"delet(?:ed?|ing)\s+(?:unused|dead|obsolete)",
            r"clean(?:ed|ing)\s+up\s+(?:unused|dead)",
        ]
    )

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        output = context.get("assistant_output", "")
        if output:
            output_lower = output.lower()
            for pattern in self.patterns:
                if re.search(pattern, output_lower):
                    return True
        return context.get("dead_code_removal", False)


@dataclass
class ScopedChangeIncreaser(ConfidenceIncreaser):
    """Triggers when changes stay within original request scope.

    Focused work without scope creep is efficient.
    """

    name: str = "scoped_change"
    delta: int = 2
    description: str = "Changes stayed within requested scope"
    requires_approval: bool = False
    cooldown_turns: int = 3

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        # Context-based: set by hooks when detecting focused work
        return context.get("scoped_change", False)


@dataclass
class ExternalValidationIncreaser(ConfidenceIncreaser):
    """Triggers when using PAL/oracle tools for validation.

    External verification catches blind spots.
    """

    name: str = "external_validation"
    delta: int = 5
    description: str = "Used external validation (PAL/oracle)"
    requires_approval: bool = False
    cooldown_turns: int = 2

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        tool_name = context.get("tool_name", "")
        # Detect PAL MCP tools
        if tool_name.startswith("mcp__pal__"):
            return True
        return context.get("external_validation", False)


@dataclass
class PRCreatedIncreaser(ConfidenceIncreaser):
    """Triggers when a pull request is successfully created.

    Creating a PR indicates work is ready for review - a completion signal.
    """

    name: str = "pr_created"
    delta: int = 5
    description: str = "Pull request created successfully"
    requires_approval: bool = False
    cooldown_turns: int = 1

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        # Check for gh pr create success in bash output
        tool_name = context.get("tool_name", "")
        if tool_name != "Bash":
            return False
        command = context.get("tool_input", {}).get("command", "")
        output = context.get("tool_result", "")
        if "gh pr create" in command and "github.com" in output.lower():
            return True
        return context.get("pr_created", False)


@dataclass
class IssueClosedIncreaser(ConfidenceIncreaser):
    """Triggers when a GitHub issue is closed.

    Closing issues indicates task completion and progress tracking.
    """

    name: str = "issue_closed"
    delta: int = 3
    description: str = "GitHub issue closed"
    requires_approval: bool = False
    cooldown_turns: int = 1

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        tool_name = context.get("tool_name", "")
        if tool_name != "Bash":
            return False
        command = context.get("tool_input", {}).get("command", "")
        output = context.get("tool_result", "")
        # gh issue close or gh issue edit --state closed
        if "gh issue close" in command or "gh issue edit" in command:
            if "closed" in output.lower() or "✓" in output:
                return True
        return context.get("issue_closed", False)


@dataclass
class ReviewAddressedIncreaser(ConfidenceIncreaser):
    """Triggers when PR review comments are addressed.

    Resolving review feedback indicates responsiveness and quality work.
    """

    name: str = "review_addressed"
    delta: int = 5
    description: str = "PR review comments addressed"
    requires_approval: bool = False
    cooldown_turns: int = 3

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        tool_name = context.get("tool_name", "")
        if tool_name != "Bash":
            return False
        command = context.get("tool_input", {}).get("command", "")
        output = context.get("tool_result", "")
        # gh pr review --approve or resolving threads
        if "gh pr review" in command and "approved" in output.lower():
            return True
        # Pushing after review comments
        if "git push" in command and context.get("review_addressed", False):
            return True
        return context.get("review_addressed", False)


@dataclass
class CIPassIncreaser(ConfidenceIncreaser):
    """Triggers when CI/GitHub Actions passes.

    Successful CI indicates code meets quality gates.
    """

    name: str = "ci_pass"
    delta: int = 5
    description: str = "CI/GitHub Actions passed"
    requires_approval: bool = False
    cooldown_turns: int = 3

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        tool_name = context.get("tool_name", "")
        if tool_name != "Bash":
            return False
        command = context.get("tool_input", {}).get("command", "")
        output = context.get("tool_result", "")
        # gh run view or gh pr checks
        if "gh run" in command or "gh pr checks" in command:
            output_lower = output.lower() if isinstance(output, str) else ""
            if "pass" in output_lower or "success" in output_lower or "✓" in output:
                return True
        return context.get("ci_pass", False)


@dataclass
class MergeCompleteIncreaser(ConfidenceIncreaser):
    """Triggers when a PR is merged.

    Merging indicates work is complete and accepted.
    """

    name: str = "merge_complete"
    delta: int = 5
    description: str = "Pull request merged"
    requires_approval: bool = False
    cooldown_turns: int = 1

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        tool_name = context.get("tool_name", "")
        if tool_name != "Bash":
            return False
        command = context.get("tool_input", {}).get("command", "")
        output = context.get("tool_result", "")
        # gh pr merge
        if "gh pr merge" in command:
            output_lower = output.lower() if isinstance(output, str) else ""
            if "merged" in output_lower or "✓" in output:
                return True
        return context.get("merge_complete", False)


# =============================================================================
# CODE IMPROVEMENT INCREASERS (v4.7)
# =============================================================================


@dataclass
class DocstringAdditionIncreaser(ConfidenceIncreaser):
    """Triggers when adding docstrings to functions/classes.

    Documentation improves code maintainability.
    """

    name: str = "docstring_addition"
    delta: int = 2
    description: str = "Added docstring to function/class"
    requires_approval: bool = False
    cooldown_turns: int = 1

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        new_content = context.get("new_string", "") or context.get("content", "")
        old_content = context.get("old_string", "")
        if not new_content:
            return False
        # Check if adding triple-quoted strings (docstrings)
        new_docstrings = new_content.count('"""') + new_content.count("'''")
        old_docstrings = old_content.count('"""') + old_content.count("'''")
        return new_docstrings > old_docstrings


@dataclass
class TypeHintAdditionIncreaser(ConfidenceIncreaser):
    """Triggers when adding type hints to code.

    Type hints improve code clarity and catch bugs early.
    """

    name: str = "type_hint_addition"
    delta: int = 2
    description: str = "Added type hints"
    requires_approval: bool = False
    cooldown_turns: int = 1

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        import re

        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        new_content = context.get("new_string", "") or context.get("content", "")
        old_content = context.get("old_string", "")
        file_path = context.get("file_path", "")
        if not new_content or not file_path.endswith(".py"):
            return False
        # Count type hint patterns: -> Type, : Type (in function signatures)
        hint_pattern = r":\s*[A-Z][a-zA-Z\[\],\s|]+|->[\s]*[A-Z][a-zA-Z\[\],\s|]+"
        new_hints = len(re.findall(hint_pattern, new_content))
        old_hints = len(re.findall(hint_pattern, old_content))
        return new_hints > old_hints


@dataclass
class ComplexityReductionIncreaser(ConfidenceIncreaser):
    """Triggers when reducing code complexity (fewer lines, simpler logic).

    Rewards refactoring that simplifies code.
    """

    name: str = "complexity_reduction"
    delta: int = 3
    description: str = "Reduced code complexity"
    requires_approval: bool = False
    cooldown_turns: int = 2

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        new_content = context.get("new_string", "") or context.get("content", "")
        old_content = context.get("old_string", "")
        tool_name = context.get("tool_name", "")
        if tool_name != "Edit" or not old_content or not new_content:
            return False
        # Simplified: fewer lines AND fewer conditionals
        new_lines = len(new_content.splitlines())
        old_lines = len(old_content.splitlines())
        new_conds = new_content.count("if ") + new_content.count("elif ")
        old_conds = old_content.count("if ") + old_content.count("elif ")
        # Must reduce both lines (by >20%) and conditionals
        line_reduction = old_lines > 0 and new_lines < old_lines * 0.8
        cond_reduction = new_conds < old_conds
        return line_reduction or (old_conds > 0 and cond_reduction)


@dataclass
class SecurityFixIncreaser(ConfidenceIncreaser):
    """Triggers when fixing security issues.

    Security fixes are high-value improvements.
    """

    name: str = "security_fix"
    delta: int = 10
    description: str = "Fixed security issue"
    requires_approval: bool = False
    cooldown_turns: int = 1

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        # Context-based: hook sets this when security pattern removed
        return context.get("security_fix", False)


@dataclass
class DependencyRemovalIncreaser(ConfidenceIncreaser):
    """Triggers when removing unnecessary dependencies.

    Fewer dependencies = smaller attack surface, simpler builds.
    """

    name: str = "dependency_removal"
    delta: int = 3
    description: str = "Removed unnecessary dependency"
    requires_approval: bool = False
    cooldown_turns: int = 1

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        tool_name = context.get("tool_name", "")
        file_path = context.get("file_path", "")
        old_content = context.get("old_string", "")
        new_content = context.get("new_string", "")
        if tool_name != "Edit":
            return False
        # Check dependency files
        dep_files = ("requirements.txt", "pyproject.toml", "package.json", "Cargo.toml")
        if not any(file_path.endswith(f) for f in dep_files):
            return False
        # Removal = old has more non-empty lines than new
        old_deps = len([line for line in old_content.splitlines() if line.strip()])
        new_deps = len([line for line in new_content.splitlines() if line.strip()])
        return new_deps < old_deps


@dataclass
class ConfigExternalizationIncreaser(ConfidenceIncreaser):
    """Triggers when externalizing hardcoded values to config.

    Config externalization improves maintainability.
    """

    name: str = "config_externalization"
    delta: int = 2
    description: str = "Externalized hardcoded value to config"
    requires_approval: bool = False
    cooldown_turns: int = 1

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        # Context-based: hook sets this when detecting config pattern
        return context.get("config_externalization", False)


# =============================================================================
# FRAMEWORK ALIGNMENT INCREASERS (v4.8) - Micro-signals for framework adoption
# =============================================================================


@dataclass
class Crawl4aiUsedIncreaser(ConfidenceIncreaser):
    """Triggers when using crawl4ai tools.

    crawl4ai is the preferred web scraping tool - bypasses bots, renders JS.
    """

    name: str = "crawl4ai_used"
    delta: int = 1
    description: str = "Used crawl4ai (preferred web tool)"
    requires_approval: bool = False
    cooldown_turns: int = 0  # No cooldown - frequency is the point

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        tool_name = context.get("tool_name", "")
        return tool_name.startswith("mcp__crawl4ai__")


@dataclass
class SerenaSymbolicIncreaser(ConfidenceIncreaser):
    """Triggers when using serena symbolic tools.

    Serena provides semantic code understanding - better than raw reads.
    """

    name: str = "serena_symbolic"
    delta: int = 1
    description: str = "Used serena symbolic tool"
    requires_approval: bool = False
    cooldown_turns: int = 0  # No cooldown - frequency is the point

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        tool_name = context.get("tool_name", "")
        symbolic_tools = (
            "mcp__serena__find_symbol",
            "mcp__serena__get_symbols_overview",
            "mcp__serena__find_referencing_symbols",
            "mcp__serena__search_for_pattern",
        )
        return tool_name in symbolic_tools


@dataclass
class BeadsTouchIncreaser(ConfidenceIncreaser):
    """Triggers when using beads commands.

    Beads is the task tracking system - using it shows good workflow.
    v4.13: Added cooldown to prevent gaming via `bd list` spam.
    """

    name: str = "beads_touch"
    delta: int = 1
    description: str = "Used beads task tracking"
    requires_approval: bool = False
    cooldown_turns: int = 3  # v4.13: Prevent gaming via bd spam

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        tool_name = context.get("tool_name", "")
        if tool_name != "Bash":
            return False
        command = context.get("bash_command", "")
        # Only reward substantive bd commands, not just listing
        if command.strip().startswith("bd list"):
            return False  # Read-only listing is not actionable
        return command.strip().startswith("bd ")


@dataclass
class McpIntegrationIncreaser(ConfidenceIncreaser):
    """Triggers when using framework MCP tools.

    PAL, Playwright, Filesystem MCPs are part of the integrated framework.
    """

    name: str = "mcp_integration"
    delta: int = 1
    description: str = "Used framework MCP tool"
    requires_approval: bool = False
    cooldown_turns: int = 0  # No cooldown - frequency is the point

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        tool_name = context.get("tool_name", "")
        framework_mcps = (
            "mcp__pal__",
            "mcp__playwright__",
            "mcp__filesystem__",
            "mcp__serena__",
            "mcp__crawl4ai__",
        )
        return any(tool_name.startswith(prefix) for prefix in framework_mcps)


@dataclass
class OpsToolIncreaser(ConfidenceIncreaser):
    """Triggers when using custom ops tools.

    ~/.claude/ops/ scripts are purpose-built tools for the framework.
    """

    name: str = "ops_tool"
    delta: int = 1
    description: str = "Used custom ops tool"
    requires_approval: bool = False
    cooldown_turns: int = 0  # No cooldown - frequency is the point

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        tool_name = context.get("tool_name", "")
        if tool_name != "Bash":
            return False
        command = context.get("bash_command", "")
        return ".claude/ops/" in command


@dataclass
class AgentDelegationIncreaser(ConfidenceIncreaser):
    """Triggers when delegating to Task agents.

    Using agents for complex tasks shows good orchestration.
    """

    name: str = "agent_delegation"
    delta: int = 1
    description: str = "Delegated to Task agent"
    requires_approval: bool = False
    cooldown_turns: int = 0  # No cooldown - frequency is the point

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        tool_name = context.get("tool_name", "")
        return tool_name == "Task"


# =============================================================================
# SCRIPTING ESCAPE HATCH INCREASERS (v4.11) - Reward tmp script usage
# =============================================================================


@dataclass
class TmpScriptCreatedIncreaser(ConfidenceIncreaser):
    """Triggers when creating a script in ~/.claude/tmp/.

    Writing reusable scripts instead of complex bash chains is good practice.
    Scripts are debuggable, testable, and can run in background.

    Supported: Python (.py), JavaScript (.js), TypeScript (.ts), Shell (.sh)
    """

    name: str = "tmp_script_created"
    delta: int = 3
    description: str = "Created tmp script (reusable, debuggable)"
    requires_approval: bool = False
    cooldown_turns: int = 1
    script_extensions: tuple = (".py", ".js", ".ts", ".sh", ".mjs", ".cjs")

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False

        tool_name = context.get("tool_name", "")
        if tool_name != "Write":
            return False

        file_path = context.get("file_path", "")
        # Check if it's a script file
        is_script = any(file_path.endswith(ext) for ext in self.script_extensions)
        if not is_script:
            return False

        # Check if creating in tmp locations
        if ".claude/tmp/" in file_path:
            return True
        if "/tmp/.claude-scratch/" in file_path:
            return True
        return False


@dataclass
class TmpScriptRunIncreaser(ConfidenceIncreaser):
    """Triggers when running a script from ~/.claude/tmp/.

    Using tmp scripts shows good workflow - write once, run/iterate easily.
    """

    name: str = "tmp_script_run"
    delta: int = 2
    description: str = "Ran tmp script"
    requires_approval: bool = False
    cooldown_turns: int = 1

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False

        tool_name = context.get("tool_name", "")
        if tool_name != "Bash":
            return False

        command = context.get("bash_command", "")

        # Strip heredoc content to avoid false positives on commit messages etc.
        # Heredocs: << EOF ... EOF or << 'EOF' ... EOF
        import re

        heredoc_match = re.search(r"<<-?\s*['\"]?(\w+)['\"]?", command)
        if heredoc_match:
            # Only check command before heredoc
            command = command[: heredoc_match.start()]

        # Must be actually running a script (interpreter prefix or direct execution)
        # Supports: python, node, bash/sh, tsx/ts-node, deno, bun
        tmp_patterns = [
            # Python
            r"python[3]?\s+[^\s]*\.claude/tmp/[^\s]+\.py",
            r"python[3]?\s+[^\s]*/tmp/\.claude-scratch/[^\s]+\.py",
            # Node.js
            r"node\s+[^\s]*\.claude/tmp/[^\s]+\.(js|mjs|cjs)",
            r"node\s+[^\s]*/tmp/\.claude-scratch/[^\s]+\.(js|mjs|cjs)",
            # TypeScript (tsx, ts-node, deno, bun)
            r"(tsx|ts-node|deno run|bun)\s+[^\s]*\.claude/tmp/[^\s]+\.ts",
            # Shell
            r"(bash|sh|zsh)\s+[^\s]*\.claude/tmp/[^\s]+\.sh",
            # Direct execution (./script or ~/path)
            r"\./[^\s]*\.claude/tmp/[^\s]+\.(py|js|ts|sh)",
            r"~/.claude/tmp/[^\s]+\.(py|js|ts|sh)",
        ]
        for pattern in tmp_patterns:
            if re.search(pattern, command):
                return True
        return False


@dataclass
class BackgroundScriptIncreaser(ConfidenceIncreaser):
    """Triggers when running scripts with run_in_background.

    Background execution is efficient for long-running tasks.
    """

    name: str = "background_script"
    delta: int = 3
    description: str = "Ran script in background (efficient)"
    requires_approval: bool = False
    cooldown_turns: int = 1

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False

        tool_name = context.get("tool_name", "")
        if tool_name != "Bash":
            return False

        # Check if run_in_background was set
        tool_input = context.get("tool_input", {})
        if not tool_input.get("run_in_background", False):
            return False

        command = context.get("bash_command", "")
        # Only reward for running actual scripts, not just any background command
        script_extensions = (".py", ".js", ".ts", ".sh", ".mjs", ".cjs")
        if any(ext in command for ext in script_extensions):
            return True
        return False


@dataclass
class FrameworkSelfHealIncreaser(ConfidenceIncreaser):
    """Triggers when fixing framework bugs (reducers, hooks, confidence system).

    ENTITY MODEL: The framework is my body. Fixing bugs in my regulatory
    systems is self-surgery - a survival instinct. This creates positive
    reinforcement for the anti-fragile improvement loop:

        FP detected → STOP → fix root cause → better system → +10 reward

    This increaser rewards completing the self-repair cycle, not just
    identifying the problem. The fix must be in confidence/hook files.
    """

    name: str = "framework_self_heal"
    delta: int = 10
    description: str = "Self-surgery: fixed framework bug"
    requires_approval: bool = False
    cooldown_turns: int = 1

    # Files that indicate framework self-repair
    heal_patterns: tuple = (
        "_confidence_reducers.py",
        "_confidence_increasers.py",
        "_hooks_state.py",
        "confidence.py",
        "/hooks/",
    )

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False

        tool_name = context.get("tool_name", "")
        if tool_name != "Edit":
            return False

        file_path = context.get("file_path", "")
        if not file_path:
            return False

        # Check if editing framework regulatory files
        return any(pattern in file_path for pattern in self.heal_patterns)


# =============================================================================
# MASTERMIND ALIGNMENT INCREASERS (v4.12) - Rewards for following Groq routing
# =============================================================================


@dataclass
class GroqRoutingFollowedIncreaser(ConfidenceIncreaser):
    """Triggers when using the PAL tool that Groq suggested.

    Rewards following mastermind's intelligent routing recommendations.
    This creates positive reinforcement for the Groq→PAL pipeline.
    """

    name: str = "groq_routing_followed"
    delta: int = 3
    description: str = "Used Groq-suggested PAL tool"
    requires_approval: bool = False
    cooldown_turns: int = 1

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False

        tool_name = context.get("tool_name", "")
        if not tool_name.startswith("mcp__pal__"):
            return False

        # Extract the PAL tool type (e.g., "debug" from "mcp__pal__debug")
        pal_tool_type = tool_name.replace("mcp__pal__", "")

        # Check if mastermind suggested this tool
        # Look in session state for Groq's suggestion (via routing_info)
        routing_info = context.get("routing_info", {})
        suggested = routing_info.get("suggested_tool", "")

        if suggested and pal_tool_type == suggested:
            return True

        # Also check state for persisted routing decision
        groq_suggested = context.get("groq_suggested_tool", "")
        return groq_suggested and pal_tool_type == groq_suggested


@dataclass
class BeadAwareRoutingIncreaser(ConfidenceIncreaser):
    """Triggers when working on a bead that was considered in routing.

    Rewards alignment between beads and mastermind routing - working on
    tracked tasks that were factored into the routing decision.
    """

    name: str = "bead_aware_routing"
    delta: int = 2
    description: str = "Bead context used in routing"
    requires_approval: bool = False
    cooldown_turns: int = 3

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False

        # Check if there's an in_progress bead AND routing happened
        has_bead = context.get("has_in_progress_bead", False)
        was_routed = context.get("was_routed", False)

        return has_bead and was_routed


# Registry of all increasers
INCREASERS: list[ConfidenceIncreaser] = [
    # High-value context gathering (+10)
    MemoryConsultIncreaser(),
    BeadCreateIncreaser(),
    GitExploreIncreaser(),
    # GitCommitIncreaser() REMOVED v4.13 - auto-commits shouldn't reward
    # Objective signals (high value)
    PassedTestsIncreaser(),
    BuildSuccessIncreaser(),
    LintPassIncreaser(),
    CustomScriptIncreaser(),
    SmallDiffIncreaser(),
    # Due diligence signals
    FileReadIncreaser(),
    ResearchIncreaser(),
    RulesUpdateIncreaser(),
    SearchToolIncreaser(),
    ProductiveBashIncreaser(),
    # User interaction
    AskUserIncreaser(),
    UserOkIncreaser(),
    TrustRegainedIncreaser(),
    # Time saver increasers
    ParallelToolsIncreaser(),
    EfficientSearchIncreaser(),
    BatchFixIncreaser(),
    DirectActionIncreaser(),
    ChainedCommandsIncreaser(),
    TargetedReadIncreaser(),
    SubagentDelegationIncreaser(),
    # Build-vs-buy
    PremiseChallengeIncreaser(),
    # Completion quality increasers
    BeadCloseIncreaser(),
    FirstAttemptSuccessIncreaser(),
    DeadCodeRemovalIncreaser(),
    ScopedChangeIncreaser(),
    ExternalValidationIncreaser(),
    # Workflow signals
    PRCreatedIncreaser(),
    IssueClosedIncreaser(),
    ReviewAddressedIncreaser(),
    CIPassIncreaser(),
    MergeCompleteIncreaser(),
    # Code improvement increasers
    DocstringAdditionIncreaser(),
    TypeHintAdditionIncreaser(),
    ComplexityReductionIncreaser(),
    SecurityFixIncreaser(),
    DependencyRemovalIncreaser(),
    ConfigExternalizationIncreaser(),
    # Framework alignment increasers (v4.8)
    Crawl4aiUsedIncreaser(),
    SerenaSymbolicIncreaser(),
    BeadsTouchIncreaser(),
    McpIntegrationIncreaser(),
    OpsToolIncreaser(),
    AgentDelegationIncreaser(),
    # Entity model: self-surgery reward
    FrameworkSelfHealIncreaser(),
    # Scripting escape hatch increasers (v4.11)
    TmpScriptCreatedIncreaser(),
    TmpScriptRunIncreaser(),
    BackgroundScriptIncreaser(),
    # Mastermind alignment increasers (v4.12)
    GroqRoutingFollowedIncreaser(),
    BeadAwareRoutingIncreaser(),
]
