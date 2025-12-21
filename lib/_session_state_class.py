#!/usr/bin/env python3
"""
Session State Class - The SessionState dataclass definition.

Session Lifecycle Tiers (see memory/__session_lifecycle.md):
- Tier 1 (Critical): ALWAYS persist - cannot be reconstructed, essential for recovery
- Tier 2 (Extended): Persist if <1hr - high-value cache, reconstructible
- Tier 3 (Ephemeral): Discard at CONDENSED+ - noise that harms revival

Fields are annotated with [T1], [T2], [T3] to indicate their tier.
"""

from dataclasses import dataclass, field
from typing import Optional

from _session_constants import Domain


@dataclass
class SessionState:
    """Comprehensive session state with lifecycle tier annotations."""

    # ==========================================================================
    # TIER 1: CRITICAL - ALWAYS persist across sessions (see session_checkpoint.py)
    # These fields CANNOT be reconstructed and are essential for recovery.
    # ==========================================================================

    # [T1] Identity
    session_id: str = ""
    started_at: float = 0
    last_activity_time: float = 0  # For mean reversion calculation

    # [T2] Domain detection - reconstructible from context
    domain: str = Domain.UNKNOWN
    domain_signals: list = field(default_factory=list)
    domain_confidence: float = 0.0

    # ==========================================================================
    # TIER 2: EXTENDED - Persist if <1hr, reconstructible from git/context
    # ==========================================================================

    # [T2] File tracking - can be reconstructed from git status/log
    files_read: list = field(default_factory=list)
    files_edited: list = field(default_factory=list)
    files_created: list = field(default_factory=list)
    dirs_listed: list = field(default_factory=list)  # Directories explored via ls/Bash
    globs_run: list = field(default_factory=list)  # Glob patterns executed

    # [T2] Library tracking
    libraries_used: list = field(default_factory=list)
    libraries_researched: list = field(default_factory=list)

    # [T2] Command tracking
    commands_succeeded: list = field(default_factory=list)
    commands_failed: list = field(default_factory=list)

    # [T2] Error tracking - errors_unresolved is borderline T1 (blocking issues)
    errors_recent: list = field(default_factory=list)  # Last 10
    errors_unresolved: list = field(default_factory=list)  # [T1-adjacent: blockers]

    # ==========================================================================
    # TIER 3: EPHEMERAL - Discard at CONDENSED+, causes context pollution
    # ==========================================================================

    # [T3] Pattern tracking - verbose, reconstruct from git if needed
    edit_counts: dict = field(default_factory=dict)  # file -> count
    edit_history: dict = field(
        default_factory=dict
    )  # file -> [(old_hash, new_hash, ts), ...]
    tool_counts: dict = field(default_factory=dict)  # [T2] tool -> count
    tests_run: bool = False  # [T2]
    last_verify: Optional[float] = None  # [T2]
    last_deploy: Optional[dict] = None  # [T2]

    # [T3] Gap tracking - session-specific, re-detect on revival
    gaps_detected: list = field(default_factory=list)
    gaps_surfaced: list = field(default_factory=list)  # Already shown to user

    # [T2] Ops scripts available - cached, rebuild from filesystem
    ops_scripts: list = field(default_factory=list)

    # [T3] Ops tool usage tracking (v3.9) - per-session analytics
    # Format: {tool_name: {count, last_turn, successes, failures}}
    ops_tool_usage: dict = field(default_factory=dict)

    # [T2] Production verification tracking (v3.9) - files that passed audit+void
    # Format: {filepath: {audit_turn, void_turn}}
    verified_production_files: dict = field(default_factory=dict)

    # ==========================================================================
    # [T1] Serena activation - CRITICAL for semantic search state
    # ==========================================================================
    serena_activated: bool = False
    serena_project: str = ""  # Project name passed to activate_project

    # ==========================================================================
    # [T1] Confidence & Gating - CRITICAL for permission decisions
    # ==========================================================================
    turn_count: int = 0  # [T2] - reconstructible from history
    last_5_tools: list = field(default_factory=list)  # [T1] For iteration detection
    ops_turns: dict = field(default_factory=dict)  # [T2] op_name -> last turn
    directives_fired: int = 0  # [T2]
    confidence: int = 70  # [T1] 0-100%, default to WORKING tier (floor)
    reputation_debt: int = (
        0  # [T2] Trust debt: accumulates when hitting floor, constrains max tier
    )
    evidence_ledger: list = field(default_factory=list)  # [T3] Evidence items
    _decay_accumulator: float = 0.0  # [T2] Fractional decay accumulator (persisted)

    # ==========================================================================
    # [T1] Meta-cognition: Goal Anchor (v3.1) - CRITICAL for drift prevention
    # ==========================================================================
    original_goal: str = ""  # First substantive user prompt
    goal_set_turn: int = 0  # Turn when goal was set
    goal_keywords: list = field(default_factory=list)  # Key terms from goal
    goal_project_id: str = (
        ""  # Project ID when goal was set (for multi-project isolation)
    )
    last_user_prompt: str = ""  # Most recent user prompt (for contradiction detection)

    # [T1] PAL continuation pointer - second brain state (v3.16)
    # [T1] PAL continuation tracking (v4.28) - per-tool persistent context
    # Format: {"debug": "abc123", "analyze": "def456", ...}
    pal_continuations: dict = field(default_factory=dict)
    pal_continuation_id: str = ""  # Legacy - single ID for backwards compat
    last_pal_tool: str = ""  # Most recent PAL tool used (for waste detection)

    # [T3] Meta-cognition: Sunk Cost Detector (v3.1) - debug state, discard on revival
    approach_history: list = field(
        default_factory=list
    )  # [{approach, turns, failures}]
    consecutive_failures: int = 0  # Same approach failures
    last_failure_turn: int = 0

    # [T3] Batch Tracking (pattern detection only, no blocking)
    consecutive_single_reads: int = 0  # Sequential single Read/Grep/Glob messages
    pending_files: list = field(default_factory=list)  # Files mentioned but not read
    pending_searches: list = field(
        default_factory=list
    )  # Searches mentioned but not run
    last_message_tool_count: int = 0  # Tools in last message

    # [T3] Sequential Repetition Tracking (v4.1) - session-specific
    # Format: {tool_name, turn, bash_cmd (for Bash only)}
    last_tool_info: dict = field(default_factory=dict)

    # [T3] Integration Blindness Prevention (v3.3) - cleared on session end
    pending_integration_greps: list = field(
        default_factory=list
    )  # [{function, file, turn}]
    grepped_functions: dict = field(
        default_factory=dict
    )  # {function_name: turn_grepped} - prevents re-add after grep

    # [T2] Nudge Tracking (v3.4) - prevents repetitive warnings, enables escalation
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

    # ==========================================================================
    # AGENT DELEGATION TRACKING (v4.26) - Token economy enforcement
    # Tracks when to suggest agents instead of direct tool calls
    # ==========================================================================

    # Exploration pattern tracking (5+ calls → suggest Explore agent)
    consecutive_exploration_calls: int = 0  # Sequential Grep/Glob/Read without Task
    recent_explore_agent_turn: int = -100  # Last turn Explore agent was spawned

    # Debugging pattern tracking (3+ edits → suggest debugger agent)
    debug_mode_active: bool = False  # Currently in debugging loop
    consecutive_tool_failures: int = 0  # Sequential tool failures
    recent_debugger_agent_turn: int = -100  # Last turn debugger agent was spawned

    # Research pattern tracking (3+ web calls → suggest researcher agent)
    consecutive_research_calls: int = 0  # Sequential WebSearch/crawl4ai calls
    recent_researcher_agent_turn: int = -100  # Last turn researcher agent was spawned

    # Review pattern tracking (5+ edits → suggest code-reviewer agent)
    recent_reviewer_agent_turn: int = -100  # Last turn code-reviewer agent was spawned

    # Planning pattern tracking (complex task → suggest Plan agent)
    recent_plan_agent_turn: int = -100  # Last turn Plan agent was spawned
    mastermind_classification: str = ""  # trivial/medium/complex from mastermind

    # Refactoring pattern tracking (multi-file symbol changes → suggest refactorer)
    recent_refactorer_agent_turn: int = -100  # Last turn refactorer agent was spawned

    # SKILL USAGE TRACKING (v4.27)
    recent_docs_skill_turn: int = -100  # Last turn /docs skill was used
    recent_think_skill_turn: int = -100  # Last turn /think skill was used
    recent_commit_skill_turn: int = -100  # Last turn /commit skill was used
    recent_verify_skill_turn: int = -100  # Last turn /verify skill was used
    recent_audit_turn: int = -100  # Last turn audit.py was run
    recent_void_turn: int = -100  # Last turn void.py was run
    research_for_library_docs: bool = False  # Detected library doc research pattern
    consecutive_debug_attempts: int = 0  # Debug attempts without /think
    consecutive_code_file_reads: int = 0  # Code reads without Serena
    framework_files_edited: list = None  # Framework files edited this session
    serena_active: bool = False  # Whether Serena is activated

    # File edit counts for oscillation detection (reuse existing edit_counts)
    # edit_counts: dict already exists above - tracks file -> count

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

    # Tracks turns since each tool family was used (v4.14, extended v4.15)
    # Format: {family: {turns_without: int, last_used_turn: int}}
    # Families: pal, serena, beads, agent_delegation, skills, clarification, tech_debt_cleanup
    tool_debt: dict = field(
        default_factory=lambda: {
            "pal": {"turns_without": 0, "last_used_turn": 0},
            "serena": {"turns_without": 0, "last_used_turn": 0},
            "beads": {"turns_without": 0, "last_used_turn": 0},
            "agent_delegation": {"turns_without": 0, "last_used_turn": 0},
            "skills": {"turns_without": 0, "last_used_turn": 0},
            "clarification": {"turns_without": 0, "last_used_turn": 0},
            "tech_debt_cleanup": {"turns_without": 0, "last_used_turn": 0},
        }
    )

    # ==========================================================================
    # REPAIR DEBT TRACKING (v4.16) - Redemption recovery for process penalties
    # ==========================================================================

    # Tracks recoverable penalty debt from PROCESS-class reducers
    # Format: {reducer_name: {amount: int, turn: int, evidence_tier: int, recovered: int}}
    # Evidence tiers: 0=claim, 1=user_accepts, 2=lint_pass, 3=test_pass, 4=user_confirms+test
    repair_debt: dict = field(default_factory=dict)

    # ==========================================================================
    # TEST ENFORCEMENT TRACKING (v4.20) - Ensure tests are always run
    # ==========================================================================

    # Session-level test tracking
    # Which test frameworks have been run this session (pytest, jest, vitest, etc.)
    test_frameworks_run: set = field(default_factory=set)

    # Turn when tests were last run (for staleness detection)
    last_test_run_turn: int = 0

    # Files modified since last test run (cleared when tests pass)
    files_modified_since_test: set = field(default_factory=set)

    # Cached test file detection (None = not scanned yet)
    # Format: {framework: [list of test file paths]}
    project_test_files: Optional[dict] = None

    # Test files created this session (for orphan detection)
    # Format: {path: {created_turn, executed: bool}}
    test_files_created: dict = field(default_factory=dict)

    # Production files changed without corresponding test coverage
    # Format: {path: {changed_turn, has_test: bool}}
    untested_production_changes: dict = field(default_factory=dict)

    # Test creation tracking (for test_first detection)
    # If a test file is created before its corresponding impl file, that's test-first
    test_creation_order: list = field(default_factory=list)  # [(path, is_test, turn)]

    # ==========================================================================
    # CONFIDENCE ENHANCEMENTS (v4.21)
    # ==========================================================================

    # Category-level pattern detection
    # Tracks reducer categories that fired recently for meta-pattern detection
    # Format: [(category, reducer_name, turn)]
    reducer_category_history: list = field(default_factory=list)

    # Volatility dampening
    # Tracks recent confidence values for oscillation detection
    # Format: [confidence_value, ...]  (last 10 values)
    confidence_history: list = field(default_factory=list)

    # Recovery intent tracking
    # When a big penalty fires, the first recovery action gets a boost
    # Format: {reducer_name: {amount: int, turn: int, recovered: bool}}
    recovery_intent_debt: dict = field(default_factory=dict)

    # ==========================================================================
    # CONTEXT GUARD (v4.22) - Proactive context exhaustion safeguard
    # ==========================================================================

    # Activates after first Stop hook run - enables proactive context checking
    context_guard_active: bool = False

    # Number of Stop hook runs this session (triggers activation after first)
    stop_hook_runs: int = 0

    # Last known token usage (updated by Stop hook)
    last_context_tokens: int = 0

    # Project ID when context guard activated (for isolation)
    context_guard_project_id: str = ""

    # Whether context warning was shown this session (one-shot soft warning)
    context_guard_warned: bool = False

    # ==========================================================================
    # [T1] RALPH-WIGGUM INTEGRATION (v4.23) - Task completion enforcement
    # https://ghuntley.com/ralph/ - Persistent iteration until genuine completion
    # CRITICAL: These fields gate session exit - MUST persist
    # ==========================================================================

    # [T1] Separate completion confidence from general confidence
    # Accumulates from test_pass, build_success, bead_close
    # Must reach threshold (default 80%) to allow session exit
    completion_confidence: int = 0  # 0-100%

    # [T1] Task contract extracted from user prompt
    # Format: {goal: str, criteria: list, evidence_required: list, created_turn: int}
    task_contract: dict = field(default_factory=dict)

    # [T3] Evidence accumulated during session - verbose, summarize on revival
    # Format: [{type: str, turn: int, details: str}]
    completion_evidence: list = field(default_factory=list)

    # [T1] Ralph activation mode
    # "": not active (trivial tasks)
    # "auto": auto-detected non-trivial task
    # "explicit": user ran /ralph-loop
    ralph_mode: str = ""

    # [T2] Strictness level for stop-blocking
    # "strict": block unless evidence >= threshold OR explicit blocker
    # "normal": soft reminder with nag budget, then allow
    # "loose": show what's incomplete but always allow exit
    ralph_strictness: str = "strict"

    # [T2] Nag budget for non-strict modes (decrements on each reminder)
    ralph_nag_budget: int = 2
