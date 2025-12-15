#!/usr/bin/env python3
"""
Dynamic Confidence Regulation System

Core engine for mechanical confidence tracking with deterministic reducers
that bypass self-assessment bias.

Design Principles:
1. Reducers fire WITHOUT judgment - mechanical signals only
2. Escalation is MANDATORY at low confidence
3. Trust regain requires explicit user approval for large boosts
4. Visibility: user always sees confidence state and zone changes

Module Structure:
- _confidence_constants.py: All constants (thresholds, limits, etc.)
- _confidence_reducers.py: Reducer classes (penalties)
- _confidence_increasers.py: Increaser classes (rewards)
- _confidence_engine.py: Core apply functions, project weights
- _confidence_tiers.py: Tier system, tool permissions
- _confidence_disputes.py: False positive handling
- _confidence_realignment.py: Rock bottom recovery
- _confidence_streaks.py: Streaks, trajectory prediction
"""

# =============================================================================
# RE-EXPORTS: Constants
# =============================================================================

from _confidence_constants import (
    DEFAULT_CONFIDENCE,
    DIMINISHING_CAP,
    DIMINISHING_MULTIPLIERS,
    FARMABLE_INCREASERS,
    MAX_CONFIDENCE_DELTA_PER_TURN,
    MAX_CONFIDENCE_RECOVERY_DELTA,
    MEAN_REVERSION_RATE,
    MEAN_REVERSION_TARGET,
    ROCK_BOTTOM_RECOVERY_TARGET,
    STASIS_FLOOR,
    STREAK_DECAY_ON_FAILURE,
    STREAK_MULTIPLIERS,
    THRESHOLD_MANDATORY_EXTERNAL,
    THRESHOLD_PRODUCTION_ACCESS,
    THRESHOLD_REQUIRE_RESEARCH,
    THRESHOLD_ROCK_BOTTOM,
    TIER_EMOJI,
)

# =============================================================================
# RE-EXPORTS: Tier system from epistemology
# =============================================================================

from epistemology import (
    TIER_CERTAINTY,
    TIER_HYPOTHESIS,
    TIER_IGNORANCE,
    TIER_PRIVILEGES,
    TIER_TRUSTED,
    TIER_WORKING,
)

# =============================================================================
# RE-EXPORTS: Reducers and Increasers
# =============================================================================

from _confidence_reducers import ConfidenceReducer, REDUCERS, UserCorrectionReducer
from _confidence_increasers import ConfidenceIncreaser, INCREASERS

# =============================================================================
# RE-EXPORTS: Core engine
# =============================================================================

from _confidence_engine import (
    apply_rate_limit,
    apply_mean_reversion,
    apply_reducers,
    apply_increasers,
    get_project_weights,
    get_adjusted_delta,
)

# =============================================================================
# RE-EXPORTS: Tier system
# =============================================================================

from _confidence_tiers import (
    get_tier_info,
    format_confidence_change,
    should_require_research,
    should_mandate_external,
    check_tool_permission,
    suggest_alternatives,
    assess_prompt_complexity,
    get_confidence_recovery_options,
)

# =============================================================================
# RE-EXPORTS: Disputes
# =============================================================================

from _confidence_disputes import (
    DISPUTE_PATTERNS,
    get_adaptive_cooldown,
    record_false_positive,
    dispute_reducer,
    detect_dispute_in_prompt,
    get_recent_reductions,
    format_dispute_instructions,
    generate_approval_prompt,
)

# =============================================================================
# RE-EXPORTS: Realignment
# =============================================================================

from _confidence_realignment import (
    REALIGNMENT_QUESTIONS,
    is_rock_bottom,
    get_realignment_questions,
    check_realignment_complete,
    mark_realignment_complete,
    reset_realignment,
)

# =============================================================================
# RE-EXPORTS: Streaks and trajectory
# =============================================================================

from _confidence_streaks import (
    calculate_idle_reversion,
    get_streak_multiplier,
    get_diminishing_multiplier,
    update_streak,
    get_current_streak,
    predict_trajectory,
    format_trajectory_warning,
    log_confidence_change,
)

# =============================================================================
# CONTEXT FLAG REGISTRY (documentation only)
# =============================================================================

CONTEXT_FLAGS = {
    # Format: "flag": ("set_by", "used_by")
    # === TOOL METADATA ===
    "tool_name": ("always", "Multiple"),
    "tool_input": ("always", "PRCreatedIncreaser"),
    "tool_result": ("always", "PRCreatedIncreaser"),
    "file_path": ("Edit/Write", "BackupFileReducer"),
    "new_string": ("Edit", "PlaceholderImplReducer"),
    "content": ("Write", "PlaceholderImplReducer"),
    "bash_command": ("Bash", "DebtBashReducer"),
    "prompt": ("user_prompt_submit_runner", "UserCorrectionReducer"),
    "assistant_output": ("stop_runner", "OverconfidentCompletionReducer"),
    "current_activity": ("session_tracking", "GoalDriftReducer"),
    # === REDUCER FLAGS ===
    "large_diff": ("git_diff>400", "LargeDiffReducer"),
    "hook_blocked": ("pre_tool_use", "HookBlockReducer"),
    "sequential_repetition_3plus": ("tool_tracking", "SequentialRepetitionReducer"),
    "unbacked_verification": ("output_analysis", "UnbackedVerificationClaimReducer"),
    "fixed_without_chain": ("output_analysis", "FixedWithoutChainReducer"),
    "git_spam": ("command_tracking", "GitSpamReducer"),
    "incomplete_refactor": ("grep_after_edit", "IncompleteRefactorReducer"),
    "reread_unchanged": ("file_hash_tracking", "RereadUnchangedReducer"),
    "huge_output_dump": ("output_size_check", "HugeOutputDumpReducer"),
    "trivial_question": ("question_analysis", "TrivialQuestionReducer"),
    "test_ignored": ("test_file_tracking", "TestIgnoredReducer"),
    "change_without_test": ("coverage_tracking", "ChangeWithoutTestReducer"),
    "contradiction_detected": ("claim_tracking", "ContradictionReducer"),
    # === INCREASER FLAGS ===
    "files_read_count": ("Read_tool", "FileReadIncreaser"),
    "memory_consulted": ("Read_path_check", "MemoryConsultIncreaser"),
    "targeted_read": ("Read_params", "TargetedReadIncreaser"),
    "research_performed": ("WebSearch/WebFetch", "ResearchIncreaser"),
    "search_performed": ("Grep/Glob/Task", "SearchToolIncreaser"),
    "subagent_delegation": ("Task_subagent_type", "SubagentDelegationIncreaser"),
    "asked_user": ("AskUserQuestion", "AskUserIncreaser"),
    "rules_updated": ("Edit_path_check", "RulesUpdateIncreaser"),
    "custom_script_ran": ("Bash_path_check", "CustomScriptIncreaser"),
    "bead_created": ("Bash_output", "BeadCreateIncreaser"),
    "git_explored": ("Bash_command", "GitExploreIncreaser"),
    "git_committed": ("Bash_command", "GitCommitIncreaser"),
    "productive_bash": ("Bash_command", "ProductiveBashIncreaser"),
    "small_diff": ("git_diff<400", "SmallDiffIncreaser"),
    "tests_passed": ("Bash_output", "PassedTestsIncreaser"),
    "build_succeeded": ("Bash_output", "BuildSuccessIncreaser"),
    "lint_passed": ("Bash_output", "LintPassIncreaser"),
    "chained_commands": ("Bash_command", "ChainedCommandsIncreaser"),
    "batch_fix": ("Edit_analysis", "BatchFixIncreaser"),
    "parallel_tools": ("tool_count", "ParallelToolsIncreaser"),
    "efficient_search": ("search_result", "EfficientSearchIncreaser"),
    "first_attempt_success": ("task_tracking", "FirstAttemptSuccessIncreaser"),
    "scoped_change": ("goal_tracking", "ScopedChangeIncreaser"),
    "dead_code_removal": ("output_analysis", "DeadCodeRemovalIncreaser"),
    "external_validation": ("tool_name", "ExternalValidationIncreaser"),
    "pr_created": ("Bash_output", "PRCreatedIncreaser"),
    "issue_closed": ("Bash_output", "IssueClosedIncreaser"),
    "review_addressed": ("Bash_output", "ReviewAddressedIncreaser"),
    "ci_pass": ("Bash_output", "CIPassIncreaser"),
    "merge_complete": ("Bash_output", "MergeCompleteIncreaser"),
    "bead_close": ("Bash_output", "BeadCloseIncreaser"),
    "premise_challenge": ("output_analysis", "PremiseChallengeIncreaser"),
    "direct_action": ("output_analysis", "DirectActionIncreaser"),
}

# =============================================================================
# Public API - Everything is re-exported, no local implementation
# =============================================================================

__all__ = [
    # Constants
    "DEFAULT_CONFIDENCE",
    "THRESHOLD_ROCK_BOTTOM",
    "THRESHOLD_MANDATORY_EXTERNAL",
    "THRESHOLD_REQUIRE_RESEARCH",
    "THRESHOLD_PRODUCTION_ACCESS",
    "ROCK_BOTTOM_RECOVERY_TARGET",
    "TIER_EMOJI",
    "MAX_CONFIDENCE_DELTA_PER_TURN",
    "MAX_CONFIDENCE_RECOVERY_DELTA",
    "STASIS_FLOOR",
    "STREAK_MULTIPLIERS",
    "STREAK_DECAY_ON_FAILURE",
    "FARMABLE_INCREASERS",
    "DIMINISHING_MULTIPLIERS",
    "DIMINISHING_CAP",
    "MEAN_REVERSION_TARGET",
    "MEAN_REVERSION_RATE",
    "CONTEXT_FLAGS",
    # Tiers from epistemology
    "TIER_IGNORANCE",
    "TIER_HYPOTHESIS",
    "TIER_WORKING",
    "TIER_CERTAINTY",
    "TIER_TRUSTED",
    "TIER_PRIVILEGES",
    # Classes
    "ConfidenceReducer",
    "ConfidenceIncreaser",
    "UserCorrectionReducer",
    # Registries
    "REDUCERS",
    "INCREASERS",
    # Core engine
    "apply_rate_limit",
    "apply_mean_reversion",
    "apply_reducers",
    "apply_increasers",
    "get_project_weights",
    "get_adjusted_delta",
    # Tier system
    "get_tier_info",
    "format_confidence_change",
    "should_require_research",
    "should_mandate_external",
    "check_tool_permission",
    "suggest_alternatives",
    "assess_prompt_complexity",
    "get_confidence_recovery_options",
    # Disputes
    "DISPUTE_PATTERNS",
    "get_adaptive_cooldown",
    "record_false_positive",
    "dispute_reducer",
    "detect_dispute_in_prompt",
    "get_recent_reductions",
    "format_dispute_instructions",
    "generate_approval_prompt",
    # Realignment
    "REALIGNMENT_QUESTIONS",
    "is_rock_bottom",
    "get_realignment_questions",
    "check_realignment_complete",
    "mark_realignment_complete",
    "reset_realignment",
    # Streaks
    "calculate_idle_reversion",
    "get_streak_multiplier",
    "get_diminishing_multiplier",
    "update_streak",
    "get_current_streak",
    "predict_trajectory",
    "format_trajectory_warning",
    "log_confidence_change",
]
