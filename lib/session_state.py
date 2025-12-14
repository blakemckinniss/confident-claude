#!/usr/bin/env python3
"""
Session State Machine v3: The brain of the hook system.

This module maintains a comprehensive state of the current session:
- What files have been read/edited
- What libraries are being used vs researched
- What domain of work we're in (infra, dev, exploration)
- What errors have occurred
- What patterns are emerging

Other hooks import this module to:
- Update state (PostToolUse)
- Query state for gaps (PreToolUse)
- Inject relevant context (UserPromptSubmit)

Design Principles:
- Silent by default (only surface gaps)
- Domain-aware (infra ≠ development ≠ research)
- Accumulated (patterns over session, not single actions)
- Specific (reference actual files/tools, not generic advice)

This file is a thin re-export layer. Implementation is in _session_*.py modules.
"""

# =============================================================================
# CONSTANTS
# =============================================================================

from _session_constants import (
    LIB_DIR,
    CLAUDE_DIR,
    MEMORY_DIR,
    STATE_FILE,
    OPS_DIR,
    OPS_USAGE_FILE,
    STATE_LOCK_FILE,
    Domain,
    _DOMAIN_SIGNAL_PATTERNS,
    RESEARCH_REQUIRED_LIBS,
    STDLIB_PATTERNS,
)

# =============================================================================
# STATE CLASS
# =============================================================================

from _session_state_class import SessionState

# =============================================================================
# PERSISTENCE
# =============================================================================

from _session_persistence import (
    load_state,
    save_state,
    reset_state,
    update_state,
    _ensure_memory_dir,
    _acquire_state_lock,
    _release_state_lock,
    _save_state_unlocked,
)

# =============================================================================
# TRACKING
# =============================================================================

from _session_tracking import (
    detect_domain,
    add_domain_signal,
    track_file_read,
    track_file_edit,
    track_file_create,
    was_file_read,
    extract_libraries_from_code,
    track_library_used,
    track_library_researched,
    needs_research,
    track_command,
    track_ops_tool,
    get_ops_tool_stats,
    get_unused_ops_tools,
    mark_production_verified,
    is_production_verified,
    _is_stdlib,
    _persist_ops_tool_usage,
)

# =============================================================================
# ERRORS
# =============================================================================

from _session_errors import (
    track_error,
    resolve_error,
    has_unresolved_errors,
)

# =============================================================================
# CONTEXT
# =============================================================================

from _session_context import (
    _discover_ops_scripts,
    generate_context,
    get_session_summary,
)

# =============================================================================
# CONFIDENCE
# =============================================================================

from _session_confidence import (
    get_turns_since_op,
    add_evidence,
    update_confidence,
    set_confidence,
)

# =============================================================================
# GOALS
# =============================================================================

from _session_goals import (
    set_goal,
    check_goal_drift,
    track_failure,
    reset_failures,
    check_sunk_cost,
)

# =============================================================================
# BATCH
# =============================================================================

from _session_batch import (
    STRICT_BATCH_TOOLS,
    SOFT_BATCH_TOOLS,
    BATCHABLE_TOOLS,
    FUNCTION_PATTERNS,
    track_batch_tool,
    add_pending_file,
    add_pending_search,
    clear_pending_file,
    clear_pending_search,
    extract_function_def_lines,
    add_pending_integration_grep,
    clear_integration_grep,
    get_pending_integration_greps,
    check_integration_blindness,
)

# =============================================================================
# WORKFLOW
# =============================================================================

from _session_workflow import (
    NUDGE_COOLDOWNS,
    ESCALATION_THRESHOLD,
    should_nudge,
    record_nudge,
    start_feature,
    complete_feature,
    track_feature_file,
    add_work_item,
    get_next_work_item,
    create_checkpoint,
    prepare_handoff,
    extract_work_from_errors,
)

# =============================================================================
# THRESHOLDS
# =============================================================================

from _session_thresholds import (
    DEFAULT_THRESHOLDS,
    THRESHOLD_COOLDOWNS,
    CASCADE_THRESHOLD,
    CASCADE_WINDOW,
    get_adaptive_threshold,
    record_threshold_trigger,
    track_block,
    clear_blocks,
    check_cascade_failure,
    _apply_mean_reversion_on_load,
)

# =============================================================================
# EXPLICIT API
# =============================================================================

__all__ = [
    # Constants
    "LIB_DIR",
    "CLAUDE_DIR",
    "MEMORY_DIR",
    "STATE_FILE",
    "OPS_DIR",
    "OPS_USAGE_FILE",
    "STATE_LOCK_FILE",
    "Domain",
    "_DOMAIN_SIGNAL_PATTERNS",
    "RESEARCH_REQUIRED_LIBS",
    "STDLIB_PATTERNS",
    # State class
    "SessionState",
    # Persistence
    "load_state",
    "save_state",
    "reset_state",
    "update_state",
    "_ensure_memory_dir",
    "_acquire_state_lock",
    "_release_state_lock",
    "_save_state_unlocked",
    # Tracking
    "detect_domain",
    "add_domain_signal",
    "track_file_read",
    "track_file_edit",
    "track_file_create",
    "was_file_read",
    "extract_libraries_from_code",
    "track_library_used",
    "track_library_researched",
    "needs_research",
    "track_command",
    "track_ops_tool",
    "get_ops_tool_stats",
    "get_unused_ops_tools",
    "mark_production_verified",
    "is_production_verified",
    "_is_stdlib",
    "_persist_ops_tool_usage",
    # Errors
    "track_error",
    "resolve_error",
    "has_unresolved_errors",
    # Context
    "_discover_ops_scripts",
    "generate_context",
    "get_session_summary",
    # Confidence
    "get_turns_since_op",
    "add_evidence",
    "update_confidence",
    "set_confidence",
    # Goals
    "set_goal",
    "check_goal_drift",
    "track_failure",
    "reset_failures",
    "check_sunk_cost",
    # Batch
    "STRICT_BATCH_TOOLS",
    "SOFT_BATCH_TOOLS",
    "BATCHABLE_TOOLS",
    "FUNCTION_PATTERNS",
    "track_batch_tool",
    "add_pending_file",
    "add_pending_search",
    "clear_pending_file",
    "clear_pending_search",
    "extract_function_def_lines",
    "add_pending_integration_grep",
    "clear_integration_grep",
    "get_pending_integration_greps",
    "check_integration_blindness",
    # Workflow
    "NUDGE_COOLDOWNS",
    "ESCALATION_THRESHOLD",
    "should_nudge",
    "record_nudge",
    "start_feature",
    "complete_feature",
    "track_feature_file",
    "add_work_item",
    "get_next_work_item",
    "create_checkpoint",
    "prepare_handoff",
    "extract_work_from_errors",
    # Thresholds
    "DEFAULT_THRESHOLDS",
    "THRESHOLD_COOLDOWNS",
    "CASCADE_THRESHOLD",
    "CASCADE_WINDOW",
    "get_adaptive_threshold",
    "record_threshold_trigger",
    "track_block",
    "clear_blocks",
    "check_cascade_failure",
    "_apply_mean_reversion_on_load",
]
