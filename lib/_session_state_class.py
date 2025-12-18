#!/usr/bin/env python3
"""
Session State Class - The SessionState dataclass definition.
"""

from dataclasses import dataclass, field
from typing import Optional

from _session_constants import Domain


@dataclass
class SessionState:
    """Comprehensive session state."""

    # Identity
    session_id: str = ""
    started_at: float = 0
    last_activity_time: float = 0  # For mean reversion calculation

    # Domain detection
    domain: str = Domain.UNKNOWN
    domain_signals: list = field(default_factory=list)
    domain_confidence: float = 0.0

    # File tracking
    files_read: list = field(default_factory=list)
    files_edited: list = field(default_factory=list)
    files_created: list = field(default_factory=list)
    dirs_listed: list = field(default_factory=list)  # Directories explored via ls/Bash
    globs_run: list = field(default_factory=list)  # Glob patterns executed

    # Library tracking
    libraries_used: list = field(default_factory=list)
    libraries_researched: list = field(default_factory=list)

    # Command tracking
    commands_succeeded: list = field(default_factory=list)
    commands_failed: list = field(default_factory=list)

    # Error tracking
    errors_recent: list = field(default_factory=list)  # Last 10
    errors_unresolved: list = field(default_factory=list)

    # Pattern tracking
    edit_counts: dict = field(default_factory=dict)  # file -> count
    edit_history: dict = field(
        default_factory=dict
    )  # file -> [(old_hash, new_hash, ts), ...]
    tool_counts: dict = field(default_factory=dict)  # tool -> count
    tests_run: bool = False
    last_verify: Optional[float] = None
    last_deploy: Optional[dict] = None

    # Gap tracking
    gaps_detected: list = field(default_factory=list)
    gaps_surfaced: list = field(default_factory=list)  # Already shown to user

    # Ops scripts available
    ops_scripts: list = field(default_factory=list)

    # Ops tool usage tracking (v3.9) - per-session counts for analytics
    # Format: {tool_name: {count, last_turn, successes, failures}}
    ops_tool_usage: dict = field(default_factory=dict)

    # Production verification tracking (v3.9) - files that passed audit+void
    # Format: {filepath: {audit_turn, void_turn}}
    verified_production_files: dict = field(default_factory=dict)

    # Serena activation tracking (v3.12)
    serena_activated: bool = False
    serena_project: str = ""  # Project name passed to activate_project

    # Synapse tracking (v3)
    turn_count: int = 0
    last_5_tools: list = field(default_factory=list)  # For iteration detection
    ops_turns: dict = field(default_factory=dict)  # op_name -> last turn
    directives_fired: int = 0
    confidence: int = 70  # 0-100%, default to WORKING tier (floor)
    reputation_debt: int = (
        0  # Trust debt: accumulates when hitting floor, constrains max tier
    )
    evidence_ledger: list = field(default_factory=list)  # Evidence items
    _decay_accumulator: float = 0.0  # Fractional decay accumulator (persisted)

    # Meta-cognition: Goal Anchor (v3.1)
    original_goal: str = ""  # First substantive user prompt
    goal_set_turn: int = 0  # Turn when goal was set
    goal_keywords: list = field(default_factory=list)  # Key terms from goal
    goal_project_id: str = (
        ""  # Project ID when goal was set (for multi-project isolation)
    )
    last_user_prompt: str = ""  # Most recent user prompt (for contradiction detection)

    # Meta-cognition: Sunk Cost Detector (v3.1)
    approach_history: list = field(
        default_factory=list
    )  # [{approach, turns, failures}]
    consecutive_failures: int = 0  # Same approach failures
    last_failure_turn: int = 0

    # Batch Tracking (pattern detection only, no blocking)
    consecutive_single_reads: int = 0  # Sequential single Read/Grep/Glob messages
    pending_files: list = field(default_factory=list)  # Files mentioned but not read
    pending_searches: list = field(
        default_factory=list
    )  # Searches mentioned but not run
    last_message_tool_count: int = 0  # Tools in last message

    # Sequential Repetition Tracking (v4.1) - detect inefficient sequential same-tool usage
    # Format: {tool_name, turn, bash_cmd (for Bash only)}
    last_tool_info: dict = field(default_factory=dict)

    # Integration Blindness Prevention (v3.3)
    pending_integration_greps: list = field(
        default_factory=list
    )  # [{function, file, turn}]
    grepped_functions: dict = field(
        default_factory=dict
    )  # {function_name: turn_grepped} - prevents re-add after grep

    # Nudge Tracking (v3.4) - prevents repetitive warnings, enables escalation
    # Format: {nudge_type: {last_turn, times_shown, times_ignored, last_content_hash}}
    nudge_history: dict = field(default_factory=dict)

    # Intake Protocol (v3.5) - structured checklist tracking
    # SUDO SECURITY: Audit passed - adding state fields only, no security impact
    # Format: [{turn, complexity, prompt_preview, confidence_initial, confidence_final, boost_used}]
    intake_history: list = field(default_factory=list)
    last_intake_complexity: str = ""  # trivial/medium/complex
    last_intake_confidence: str = ""  # L/M/H
    intake_gates_triggered: int = 0  # Count of hard stops due to low confidence

    # Cascade Failure Tracking (v3.8) - detect deadlocked sessions
    # Format: {hook_name: {count, first_turn, last_turn}}
    consecutive_blocks: dict = field(default_factory=dict)
    last_block_turn: int = 0

    # Hook-specific counters
    crawl4ai_suggestions: int = 0  # Track crawl4ai preference suggestions

    # ==========================================================================
    # AUTONOMOUS AGENT PATTERNS (v3.6) - Inspired by Anthropic's agent harness
    # https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents
    # ==========================================================================

    # Progress Tracking - automatic capture of what was done
    # Format: [{feature_id, description, status, files, commits, errors, started, completed}]
    progress_log: list = field(default_factory=list)
    current_feature: str = ""  # Active feature/task being worked on
    current_feature_started: float = 0.0  # When current feature started (timestamp)
    current_feature_start_turn: int = (
        0  # Turn count when feature started (for turn counting)
    )
    current_feature_files: list = field(
        default_factory=list
    )  # Files touched for current feature

    # Auto-discovered work items (from errors, TODOs, failing tests, gaps)
    # Format: [{id, type, source, description, priority, discovered_at, status}]
    work_queue: list = field(default_factory=list)

    # Checkpoint tracking for recovery
    # Format: [{checkpoint_id, commit_hash, feature, timestamp, files_state}]
    checkpoints: list = field(default_factory=list)
    last_checkpoint_turn: int = 0

    # Session handoff data (for context bridging across sessions)
    handoff_summary: str = ""  # Auto-generated summary for next session
    handoff_next_steps: list = field(default_factory=list)  # Prioritized next actions
    handoff_blockers: list = field(default_factory=list)  # Known blockers/issues

    # ==========================================================================
    # PARALLEL AGENT ORCHESTRATION (v3.9) - Nudge sequential → parallel Task spawns
    # ==========================================================================

    # Task spawn tracking per turn (reset each turn)
    task_spawns_this_turn: int = 0  # Count of Task tools in current turn
    last_task_turn: int = 0  # Turn when last Task was spawned

    # Sequential pattern detection
    consecutive_single_tasks: int = 0  # Sequential turns with single Task spawn
    task_prompts_recent: list = field(
        default_factory=list
    )  # Last 5 Task prompts (for similarity)
    parallel_nudge_count: int = 0  # Times we've nudged for parallelization

    # Background task tracking (for check-in reminders)
    background_tasks: list = field(default_factory=list)  # [{type, prompt, turn}]

    # Beads command batching
    recent_beads_commands: list = field(default_factory=list)  # [{cmd, turn}]

    # Bead enforcement tracking
    bead_enforcement_blocks: int = 0  # Cascade detection for bd failures

    # ==========================================================================
    # SELF-HEALING ENFORCEMENT (v3.10) - Framework must fix itself
    # ==========================================================================

    # Framework error tracking (errors in .claude/ paths)
    framework_errors: list = field(default_factory=list)  # [{path, error, turn}]
    framework_error_turn: int = 0  # Turn when last framework error occurred

    # Self-heal state machine
    self_heal_required: bool = False  # Blocks other work until fix attempted
    self_heal_target: str = ""  # Path/component that needs fixing
    self_heal_error: str = ""  # Error message that triggered self-heal
    self_heal_attempts: int = 0  # Fix attempts for current error
    self_heal_max_attempts: int = 3  # After this, escalate to user

    # ==========================================================================
    # TOOL DEBT TRACKING (v4.14) - Pressure-to-remember mechanism
    # ==========================================================================

    # Tracks turns since each tool family was used
    # Format: {family: {turns_without: int, last_used_turn: int}}
    tool_debt: dict = field(default_factory=lambda: {
        "pal": {"turns_without": 0, "last_used_turn": 0},
        "serena": {"turns_without": 0, "last_used_turn": 0},
        "beads": {"turns_without": 0, "last_used_turn": 0},
    })
