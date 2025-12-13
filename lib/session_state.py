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
"""

# SUDO SECURITY: Audit passed 2025-11-28 - adding fcntl for race condition fix
import json
import time
from confidence import calculate_idle_reversion
import re
import os
import tempfile
import fcntl
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field, asdict

# =============================================================================
# PATHS
# =============================================================================

LIB_DIR = Path(__file__).resolve().parent  # .claude/lib
CLAUDE_DIR = LIB_DIR.parent  # .claude
MEMORY_DIR = CLAUDE_DIR / "memory"
STATE_FILE = MEMORY_DIR / "session_state_v3.json"
OPS_DIR = (
    Path(__file__).resolve().parent.parent / "ops"
)  # .claude/lib -> .claude -> .claude/ops

# =============================================================================
# SESSION-SCOPED STATE CACHE (Performance optimization)
# Eliminates repeated file I/O - saves 50-100ms per hook invocation
# =============================================================================

_STATE_CACHE: Optional["SessionState"] = None
_STATE_CACHE_DIRTY: bool = False
_STATE_CACHE_MTIME: float = 0.0

# =============================================================================
# DOMAIN DETECTION
# =============================================================================


class Domain:
    UNKNOWN = "unknown"
    INFRASTRUCTURE = "infrastructure"  # gcloud, aws, docker, k8s
    DEVELOPMENT = "development"  # editing code, debugging
    EXPLORATION = "exploration"  # reading, understanding codebase
    DATA = "data"  # jupyter, pandas, SQL


# Pre-compiled domain signal patterns (avoids 40+ regex compilations per call)
_DOMAIN_SIGNAL_PATTERNS = {
    Domain.INFRASTRUCTURE: [
        re.compile(r"gcloud\s+", re.IGNORECASE),
        re.compile(r"aws\s+", re.IGNORECASE),
        re.compile(r"docker\s+", re.IGNORECASE),
        re.compile(r"kubectl\s+", re.IGNORECASE),
        re.compile(r"terraform\s+", re.IGNORECASE),
        re.compile(r"--region", re.IGNORECASE),
        re.compile(r"--project", re.IGNORECASE),
        re.compile(r"deploy", re.IGNORECASE),
        re.compile(r"service", re.IGNORECASE),
        re.compile(r"secrets?", re.IGNORECASE),
    ],
    Domain.DEVELOPMENT: [
        re.compile(r"\.py$", re.IGNORECASE),
        re.compile(r"\.js$", re.IGNORECASE),
        re.compile(r"\.ts$", re.IGNORECASE),
        re.compile(r"\.rs$", re.IGNORECASE),
        re.compile(r"npm\s+(run|test|build)", re.IGNORECASE),
        re.compile(r"pytest", re.IGNORECASE),
        re.compile(r"cargo\s+(build|test|run)", re.IGNORECASE),
        re.compile(r"function\s+\w+", re.IGNORECASE),
        re.compile(r"class\s+\w+", re.IGNORECASE),
        re.compile(r"def\s+\w+", re.IGNORECASE),
    ],
    Domain.EXPLORATION: [
        re.compile(r"what\s+(is|does|are)", re.IGNORECASE),
        re.compile(r"how\s+(does|do|to)", re.IGNORECASE),
        re.compile(r"explain", re.IGNORECASE),
        re.compile(r"understand", re.IGNORECASE),
        re.compile(r"find.*file", re.IGNORECASE),
        re.compile(r"where\s+is", re.IGNORECASE),
        re.compile(r"show\s+me", re.IGNORECASE),
    ],
    Domain.DATA: [
        re.compile(r"\.ipynb", re.IGNORECASE),
        re.compile(r"pandas", re.IGNORECASE),
        re.compile(r"dataframe", re.IGNORECASE),
        re.compile(r"sql", re.IGNORECASE),
        re.compile(r"query", re.IGNORECASE),
        re.compile(r"\.csv", re.IGNORECASE),
        re.compile(r"\.parquet", re.IGNORECASE),
    ],
}

# =============================================================================
# LIBRARY DETECTION
# =============================================================================

# Libraries that should be researched before use (fast-moving, complex APIs)
RESEARCH_REQUIRED_LIBS = {
    # Python
    "fastapi",
    "pydantic",
    "langchain",
    "llamaindex",
    "anthropic",
    "openai",
    "polars",
    "duckdb",
    "streamlit",
    "gradio",
    "transformers",
    "torch",
    "boto3",
    "playwright",
    "httpx",
    "aiohttp",
    # JavaScript
    "next",
    "nuxt",
    "remix",
    "astro",
    "svelte",
    # Cloud SDKs
    "@google-cloud",
    "@aws-sdk",
    "@azure",
}

# Standard libraries that don't need research
STDLIB_PATTERNS = [
    r"^(os|sys|json|re|time|datetime|pathlib|subprocess|typing|collections|itertools)$",
    r"^(math|random|string|io|functools|operator|contextlib|abc|dataclasses)$",
]

# =============================================================================
# STATE SCHEMA
# =============================================================================


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

    # Synapse tracking (v3)
    turn_count: int = 0
    last_5_tools: list = field(default_factory=list)  # For iteration detection
    ops_turns: dict = field(default_factory=dict)  # op_name -> last turn
    directives_fired: int = 0
    confidence: int = 0  # 0-100%
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


# =============================================================================
# STATE MANAGEMENT
# =============================================================================


def _ensure_memory_dir():
    """Ensure memory directory exists."""
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)


# Lock file for state operations (prevents race conditions across terminals)
STATE_LOCK_FILE = MEMORY_DIR / "session_state.lock"


def _acquire_state_lock(shared: bool = False):
    """Acquire lock for state file operations.

    Args:
        shared: If True, acquire shared lock (multiple readers OK).
                If False, acquire exclusive lock (single writer).
    """
    _ensure_memory_dir()
    lock_fd = os.open(str(STATE_LOCK_FILE), os.O_CREAT | os.O_RDWR)
    lock_type = fcntl.LOCK_SH if shared else fcntl.LOCK_EX
    fcntl.flock(lock_fd, lock_type)
    return lock_fd


def _release_state_lock(lock_fd: int):
    """Release state file lock."""
    fcntl.flock(lock_fd, fcntl.LOCK_UN)
    os.close(lock_fd)


def load_state() -> SessionState:
    """Load session state from file with in-memory caching.

    Uses session-scoped cache to eliminate repeated file I/O.
    Cache is invalidated if file mtime changes (external modification).
    """
    global _STATE_CACHE, _STATE_CACHE_MTIME

    _ensure_memory_dir()

    # Check cache validity
    if _STATE_CACHE is not None:
        try:
            current_mtime = STATE_FILE.stat().st_mtime if STATE_FILE.exists() else 0
            if current_mtime == _STATE_CACHE_MTIME:
                return _STATE_CACHE
        except OSError:
            pass

    # Cache miss or stale - load from disk
    lock_fd = _acquire_state_lock(shared=True)
    try:
        if STATE_FILE.exists():
            try:
                current_mtime = STATE_FILE.stat().st_mtime
                with open(STATE_FILE) as f:
                    data = json.load(f)
                    _STATE_CACHE = _apply_mean_reversion_on_load(SessionState(**data))
                    _STATE_CACHE_MTIME = current_mtime
                    return _STATE_CACHE
            except (json.JSONDecodeError, TypeError, KeyError, OSError):
                pass
    finally:
        _release_state_lock(lock_fd)

    # No existing state - need exclusive lock to create
    lock_fd = _acquire_state_lock(shared=False)
    try:
        # Double-check after acquiring exclusive lock (another process may have created it)
        if STATE_FILE.exists():
            try:
                current_mtime = STATE_FILE.stat().st_mtime
                with open(STATE_FILE) as f:
                    data = json.load(f)
                    _STATE_CACHE = _apply_mean_reversion_on_load(SessionState(**data))
                    _STATE_CACHE_MTIME = current_mtime
                    return _STATE_CACHE
            except (json.JSONDecodeError, TypeError, KeyError, OSError):
                pass

        # Initialize new state
        state = SessionState(
            session_id=os.environ.get("CLAUDE_SESSION_ID", "")[:16]
            or f"ses_{int(time.time())}",
            started_at=time.time(),
            ops_scripts=_discover_ops_scripts(),
        )
        _save_state_unlocked(state)
        _STATE_CACHE = state
        _STATE_CACHE_MTIME = STATE_FILE.stat().st_mtime if STATE_FILE.exists() else 0
        return state
    finally:
        _release_state_lock(lock_fd)


def _save_state_unlocked(state: SessionState):
    # Update activity timestamp for mean reversion
    state.last_activity_time = time.time()

    # Trim lists to prevent unbounded growth
    state.files_read = state.files_read[-50:]
    state.files_edited = state.files_edited[-50:]
    state.commands_succeeded = state.commands_succeeded[-20:]
    state.commands_failed = state.commands_failed[-20:]
    state.errors_recent = state.errors_recent[-10:]
    state.domain_signals = state.domain_signals[-20:]
    state.gaps_detected = state.gaps_detected[-10:]
    state.gaps_surfaced = state.gaps_surfaced[-10:]
    state.last_5_tools = state.last_5_tools[-5:]
    state.evidence_ledger = state.evidence_ledger[-20:]

    # Atomic write: write to temp file, then rename
    try:
        fd, tmp_path = tempfile.mkstemp(dir=MEMORY_DIR, suffix=".json")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(asdict(state), f, indent=2, default=str)
            os.replace(tmp_path, STATE_FILE)  # Atomic on POSIX
        except Exception:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            raise
    except (IOError, OSError):
        with open(STATE_FILE, "w") as f:
            json.dump(asdict(state), f, indent=2, default=str)


def save_state(state: SessionState):
    """Save session state to file (with file locking for concurrency safety).

    Also updates the in-memory cache.
    """
    global _STATE_CACHE, _STATE_CACHE_MTIME

    _ensure_memory_dir()
    lock_fd = _acquire_state_lock()
    try:
        _save_state_unlocked(state)
        # Update cache after successful write
        _STATE_CACHE = state
        _STATE_CACHE_MTIME = STATE_FILE.stat().st_mtime if STATE_FILE.exists() else 0
    finally:
        _release_state_lock(lock_fd)


def reset_state():
    """Reset state for new session."""
    global _STATE_CACHE, _STATE_CACHE_MTIME

    _STATE_CACHE = None
    _STATE_CACHE_MTIME = 0.0

    if STATE_FILE.exists():
        STATE_FILE.unlink()
    return load_state()


def update_state(modifier_func):
    """
    Atomically load, modify, and save state (race-condition safe).

    Holds lock across entire read-modify-write operation, preventing
    lost updates when multiple Claude instances modify state concurrently.
    Updates the in-memory cache after successful write.

    Usage:
        def add_file(state):
            state.files_read.append("foo.py")
        update_state(add_file)

    Args:
        modifier_func: Function that takes SessionState and modifies it in-place

    Returns:
        The modified SessionState
    """
    global _STATE_CACHE, _STATE_CACHE_MTIME

    _ensure_memory_dir()
    lock_fd = _acquire_state_lock()
    try:
        if STATE_FILE.exists():
            try:
                with open(STATE_FILE) as f:
                    data = json.load(f)
                    state = SessionState(**data)
            except (json.JSONDecodeError, TypeError, KeyError):
                state = SessionState(
                    session_id=os.environ.get("CLAUDE_SESSION_ID", "")[:16]
                    or f"ses_{int(time.time())}",
                    started_at=time.time(),
                    ops_scripts=_discover_ops_scripts(),
                )
        else:
            state = SessionState(
                session_id=os.environ.get("CLAUDE_SESSION_ID", "")[:16]
                or f"ses_{int(time.time())}",
                started_at=time.time(),
                ops_scripts=_discover_ops_scripts(),
            )

        modifier_func(state)
        _save_state_unlocked(state)

        # Update cache after successful write
        _STATE_CACHE = state
        _STATE_CACHE_MTIME = STATE_FILE.stat().st_mtime if STATE_FILE.exists() else 0

        return state
    finally:
        _release_state_lock(lock_fd)


# =============================================================================
# DOMAIN DETECTION
# =============================================================================


def detect_domain(state: SessionState) -> tuple[str, float]:
    """Detect domain from accumulated signals."""
    if not state.domain_signals:
        return Domain.UNKNOWN, 0.0

    # Count matches per domain
    scores = {
        d: 0
        for d in [
            Domain.INFRASTRUCTURE,
            Domain.DEVELOPMENT,
            Domain.EXPLORATION,
            Domain.DATA,
        ]
    }

    combined_signals = " ".join(state.domain_signals[-20:]).lower()

    for domain, compiled_patterns in _DOMAIN_SIGNAL_PATTERNS.items():
        for pattern in compiled_patterns:
            matches = len(pattern.findall(combined_signals))
            scores[domain] += matches

    # Find winner
    if max(scores.values()) == 0:
        return Domain.UNKNOWN, 0.0

    winner = max(scores, key=scores.get)
    total = sum(scores.values())
    confidence = scores[winner] / total if total > 0 else 0

    return winner, confidence


def add_domain_signal(state: SessionState, signal: str):
    """Add a signal for domain detection."""
    state.domain_signals.append(signal)
    state.domain, state.domain_confidence = detect_domain(state)


# =============================================================================
# FILE TRACKING
# =============================================================================


def track_file_read(state: SessionState, filepath: str):
    """Track that a file was read."""
    if filepath and filepath not in state.files_read:
        state.files_read.append(filepath)
    add_domain_signal(state, filepath)


def track_file_edit(
    state: SessionState,
    filepath: str,
    old_string: str = "",
    new_string: str = "",
):
    """Track that a file was edited, with optional content hashes for oscillation detection."""
    if filepath:
        if filepath not in state.files_edited:
            state.files_edited.append(filepath)
        state.edit_counts[filepath] = state.edit_counts.get(filepath, 0) + 1

        # Track edit history for oscillation detection
        # Store hashes to detect when edits revert previous changes
        if old_string or new_string:
            import hashlib
            import time

            old_hash = (
                hashlib.md5(old_string.encode()).hexdigest()[:8] if old_string else ""
            )
            new_hash = (
                hashlib.md5(new_string.encode()).hexdigest()[:8] if new_string else ""
            )
            if filepath not in state.edit_history:
                state.edit_history[filepath] = []
            state.edit_history[filepath].append((old_hash, new_hash, time.time()))
            # Keep only last 10 edits per file
            state.edit_history[filepath] = state.edit_history[filepath][-10:]

    add_domain_signal(state, filepath)


def track_file_create(state: SessionState, filepath: str):
    """Track that a file was created."""
    if filepath and filepath not in state.files_created:
        state.files_created.append(filepath)
    add_domain_signal(state, filepath)


def was_file_read(state: SessionState, filepath: str) -> bool:
    """Check if a file was read this session."""
    return filepath in state.files_read


# =============================================================================
# LIBRARY TRACKING
# =============================================================================


def extract_libraries_from_code(code: str) -> list:
    """Extract library imports from code."""
    libs = []

    # Python imports
    py_imports = re.findall(r"(?:from|import)\s+([\w.]+)", code)
    libs.extend(py_imports)

    # JavaScript requires/imports
    js_imports = re.findall(r"(?:require|from)\s*['\"]([^'\"]+)['\"]", code)
    libs.extend(js_imports)

    # Clean up
    cleaned = []
    for lib in libs:
        # Get top-level package
        top_level = lib.split(".")[0].split("/")[0]
        if top_level and not _is_stdlib(top_level):
            cleaned.append(top_level)

    return list(set(cleaned))


def _is_stdlib(lib: str) -> bool:
    """Check if library is standard library."""
    for pattern in STDLIB_PATTERNS:
        if re.match(pattern, lib):
            return True
    return False


def track_library_used(state: SessionState, lib: str):
    """Track that a library is being used."""
    if lib and lib not in state.libraries_used:
        state.libraries_used.append(lib)


def track_library_researched(state: SessionState, lib: str):
    """Track that a library was researched."""
    if lib and lib not in state.libraries_researched:
        state.libraries_researched.append(lib)


def needs_research(state: SessionState, lib: str) -> bool:
    """Check if a library needs research before use."""
    if lib in state.libraries_researched:
        return False
    if _is_stdlib(lib):
        return False
    # Check if it's a fast-moving library
    lib_lower = lib.lower()
    for research_lib in RESEARCH_REQUIRED_LIBS:
        if research_lib in lib_lower or lib_lower in research_lib:
            return True
    return False


# =============================================================================
# COMMAND TRACKING
# =============================================================================


def track_command(state: SessionState, command: str, success: bool, output: str = ""):
    """Track a command execution."""
    cmd_record = {
        "command": command[:200],
        "success": success,
        "timestamp": time.time(),
    }

    if success:
        state.commands_succeeded.append(cmd_record)
    else:
        state.commands_failed.append(cmd_record)
        track_error(state, f"Command failed: {command[:100]}", output[:500])

    add_domain_signal(state, command)

    # Check for specific patterns
    if "pytest" in command or "npm test" in command or "cargo test" in command:
        state.tests_run = True

    if "verify.py" in command:
        state.last_verify = time.time()

    if "deploy" in command.lower():
        state.last_deploy = {
            "command": command[:200],
            "timestamp": time.time(),
            "success": success,
        }

    # Check for research commands
    if "research.py" in command or "probe.py" in command:
        # Try to extract what was researched
        parts = command.split()
        for i, part in enumerate(parts):
            if part in ["research.py", "probe.py"] and i + 1 < len(parts):
                topic = parts[i + 1].strip("'\"")
                track_library_researched(state, topic)


# =============================================================================
# OPS TOOL TRACKING (v3.9)
# =============================================================================

OPS_USAGE_FILE = Path.home() / ".claude" / "memory" / "tool_usage.json"


def track_ops_tool(state: SessionState, tool_name: str, success: bool = True):
    """Track ops tool usage for analytics and self-maintenance.

    Updates both session state and persistent cross-session file.
    """
    # Update session state
    if tool_name not in state.ops_tool_usage:
        state.ops_tool_usage[tool_name] = {
            "count": 0,
            "last_turn": 0,
            "successes": 0,
            "failures": 0,
        }
    state.ops_tool_usage[tool_name]["count"] += 1
    state.ops_tool_usage[tool_name]["last_turn"] = state.turn_count
    if success:
        state.ops_tool_usage[tool_name]["successes"] += 1
    else:
        state.ops_tool_usage[tool_name]["failures"] += 1

    # Persist to cross-session file (async-safe with atomic write)
    _persist_ops_tool_usage(tool_name, success)


def _persist_ops_tool_usage(tool_name: str, success: bool):
    """Persist ops tool usage to cross-session file."""
    try:
        # Load existing data
        data = {}
        if OPS_USAGE_FILE.exists():
            data = json.loads(OPS_USAGE_FILE.read_text())

        # Update tool entry
        if tool_name not in data:
            data[tool_name] = {
                "total_uses": 0,
                "successes": 0,
                "failures": 0,
                "first_used": time.strftime("%Y-%m-%d"),
                "last_used": "",
                "sessions": 0,
            }
        data[tool_name]["total_uses"] += 1
        data[tool_name]["last_used"] = time.strftime("%Y-%m-%d %H:%M")
        if success:
            data[tool_name]["successes"] += 1
        else:
            data[tool_name]["failures"] += 1

        # Atomic write
        tmp = OPS_USAGE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2))
        tmp.rename(OPS_USAGE_FILE)
    except Exception:
        pass  # Non-critical, don't break hooks


def get_ops_tool_stats() -> dict:
    """Get cross-session ops tool usage statistics."""
    if OPS_USAGE_FILE.exists():
        try:
            return json.loads(OPS_USAGE_FILE.read_text())
        except Exception:
            pass
    return {}


def get_unused_ops_tools(days_threshold: int = 30) -> list:
    """Get ops tools not used in the last N days."""
    from datetime import datetime, timedelta

    stats = get_ops_tool_stats()
    cutoff = datetime.now() - timedelta(days=days_threshold)
    unused = []

    # Get all ops tools
    ops_dir = Path.home() / ".claude" / "ops"
    if ops_dir.exists():
        all_tools = {f.stem for f in ops_dir.glob("*.py")}
        for tool in all_tools:
            if tool not in stats:
                unused.append(tool)
            else:
                last_used = stats[tool].get("last_used", "")
                if last_used:
                    try:
                        last_dt = datetime.strptime(last_used[:10], "%Y-%m-%d")
                        if last_dt < cutoff:
                            unused.append(tool)
                    except Exception:
                        pass
    return unused


def mark_production_verified(state: SessionState, filepath: str, tool: str):
    """Mark a file as having passed audit or void this session."""
    if filepath not in state.verified_production_files:
        state.verified_production_files[filepath] = {}
    state.verified_production_files[filepath][f"{tool}_turn"] = state.turn_count


def is_production_verified(state: SessionState, filepath: str) -> tuple[bool, str]:
    """Check if a file has passed both audit and void this session.

    Returns (is_verified, missing_tool) where missing_tool is 'audit', 'void', or 'both'.
    """
    verified = state.verified_production_files.get(filepath, {})
    has_audit = "audit_turn" in verified
    has_void = "void_turn" in verified

    if has_audit and has_void:
        return True, ""
    elif has_audit:
        return False, "void"
    elif has_void:
        return False, "audit"
    else:
        return False, "both"


# =============================================================================
# ERROR TRACKING
# =============================================================================


def track_error(state: SessionState, error_type: str, details: str = ""):
    """Track an error."""
    error = {
        "type": error_type,
        "details": details[:500],
        "timestamp": time.time(),
        "resolved": False,
    }
    state.errors_recent.append(error)
    state.errors_unresolved.append(error)


def resolve_error(state: SessionState, error_pattern: str):
    """Mark errors matching pattern as resolved."""
    state.errors_unresolved = [
        e
        for e in state.errors_unresolved
        if error_pattern.lower() not in e.get("type", "").lower()
        and error_pattern.lower() not in e.get("details", "").lower()
    ]


def has_unresolved_errors(state: SessionState) -> bool:
    """Check if there are unresolved errors."""
    # Only consider errors from last 10 minutes
    cutoff = time.time() - 600
    recent_unresolved = [
        e for e in state.errors_unresolved if e.get("timestamp", 0) > cutoff
    ]
    return len(recent_unresolved) > 0


# =============================================================================
# OPS SCRIPT DISCOVERY (cached for performance)
# =============================================================================

_OPS_SCRIPTS_CACHE: list | None = None
_OPS_SCRIPTS_MTIME: float = 0.0


def _discover_ops_scripts() -> list:
    """Discover available ops scripts (cached, refreshes if directory modified)."""
    global _OPS_SCRIPTS_CACHE, _OPS_SCRIPTS_MTIME

    if not OPS_DIR.exists():
        return []

    # Check if cache is valid (directory mtime unchanged)
    try:
        current_mtime = OPS_DIR.stat().st_mtime
        if _OPS_SCRIPTS_CACHE is not None and current_mtime == _OPS_SCRIPTS_MTIME:
            return _OPS_SCRIPTS_CACHE
    except OSError:
        pass

    # Refresh cache
    scripts = [f.stem for f in OPS_DIR.glob("*.py")]
    _OPS_SCRIPTS_CACHE = scripts
    _OPS_SCRIPTS_MTIME = current_mtime if "current_mtime" in dir() else 0.0
    return scripts


def generate_context(state: SessionState) -> str:
    """Generate context string for injection."""
    parts = []

    # Domain
    if state.domain != Domain.UNKNOWN and state.domain_confidence > 0.3:
        domain_emoji = {
            Domain.INFRASTRUCTURE: "☁️",
            Domain.DEVELOPMENT: "💻",
            Domain.EXPLORATION: "🔍",
            Domain.DATA: "📊",
        }.get(state.domain, "📁")
        parts.append(
            f"{domain_emoji} Domain: {state.domain} ({state.domain_confidence:.0%})"
        )

    # Files
    if state.files_edited:
        recent_edits = state.files_edited[-3:]
        names = [Path(f).name for f in recent_edits]
        parts.append(f"📝 Edited: {', '.join(names)}")

    # Errors
    if state.errors_unresolved:
        error = state.errors_unresolved[-1]
        parts.append(f"⚠️ Unresolved: {error.get('type', 'error')[:40]}")

    # Deploy status
    if state.last_deploy:
        age = time.time() - state.last_deploy.get("timestamp", 0)
        if age < 600:  # Last 10 minutes
            status = "✅" if state.last_deploy.get("success") else "❌"
            parts.append(f"{status} Deploy: {int(age)}s ago")

    # Tests
    if state.tests_run:
        parts.append("✅ Tests: run")
    elif any(c >= 2 for c in state.edit_counts.values()):
        parts.append("⚠️ Tests: not run")

    return " | ".join(parts) if parts else ""


# =============================================================================
# UTILITY
# =============================================================================


def get_session_summary(state: SessionState) -> dict:
    """Get a summary of the session for debugging."""
    return {
        "session_id": state.session_id,
        "domain": state.domain,
        "domain_confidence": state.domain_confidence,
        "files_read": len(state.files_read),
        "files_edited": len(state.files_edited),
        "libraries_used": state.libraries_used,
        "libraries_researched": state.libraries_researched,
        "tests_run": state.tests_run,
        "errors_unresolved": len(state.errors_unresolved),
        "edit_counts": state.edit_counts,
    }


# =============================================================================
# SYNAPSE TRACKING (v3)
# =============================================================================


def get_turns_since_op(state: SessionState, op_name: str) -> int:
    """Get turns since an ops command was run."""
    last_turn = state.ops_turns.get(op_name, -1)
    if last_turn < 0:
        return 999  # Never run
    return state.turn_count - last_turn


def add_evidence(state: SessionState, evidence_type: str, content: str):
    """Add evidence to the ledger."""
    state.evidence_ledger.append(
        {
            "type": evidence_type,
            "content": content[:200],
            "turn": state.turn_count,
            "timestamp": time.time(),
        }
    )


def update_confidence(state: SessionState, delta: int, reason: str = ""):
    """Update confidence level with bounds checking."""
    old = state.confidence
    state.confidence = max(0, min(100, state.confidence + delta))
    if reason:
        add_evidence(
            state, "confidence_change", f"{old} -> {state.confidence}: {reason}"
        )


def set_confidence(state: SessionState, value: int, reason: str = ""):
    """Set confidence to absolute value with audit trail.

    Use this instead of direct state.confidence = X assignments
    to ensure all confidence changes are tracked.
    """
    old = state.confidence
    state.confidence = max(0, min(100, value))
    if old != state.confidence:
        add_evidence(
            state,
            "confidence_set",
            f"{old} -> {state.confidence}: {reason or 'direct set'}",
        )


# =============================================================================
# GOAL ANCHOR (v3.1)
# =============================================================================


def set_goal(state: SessionState, prompt: str):
    """Set the original goal if not already set."""
    if state.original_goal:
        return  # Goal already set

    # Skip meta/administrative prompts
    skip_patterns = [
        r"^(hi|hello|hey|thanks|ok|yes|no|sure)\b",
        r"^(commit|push|pr|status|help)\b",
        r"^/",  # Slash commands
    ]
    prompt_lower = prompt.lower().strip()
    for pattern in skip_patterns:
        if re.match(pattern, prompt_lower):
            return

    # Extract substantive goal
    state.original_goal = prompt[:200]
    state.goal_set_turn = state.turn_count

    # Extract keywords (nouns/verbs, skip common words)
    stop_words = {
        "the",
        "a",
        "an",
        "is",
        "are",
        "to",
        "for",
        "in",
        "on",
        "with",
        "and",
        "or",
        "but",
        "can",
        "you",
        "i",
        "me",
        "my",
        "this",
        "that",
        "it",
        "be",
        "do",
        "have",
        "will",
        "would",
        "could",
        "should",
    }
    words = re.findall(r"\b[a-z]{3,}\b", prompt_lower)
    state.goal_keywords = [w for w in words if w not in stop_words][:10]


def check_goal_drift(state: SessionState, current_activity: str) -> tuple[bool, str]:
    """Check if current activity has drifted from original goal.

    Returns: (is_drifting, drift_message)
    """
    if not state.original_goal or not state.goal_keywords:
        return False, ""

    # Only check after some turns
    if state.turn_count - state.goal_set_turn < 5:
        return False, ""

    # Check keyword overlap
    activity_lower = current_activity.lower()
    matches = sum(1 for kw in state.goal_keywords if kw in activity_lower)
    overlap_ratio = matches / len(state.goal_keywords) if state.goal_keywords else 0

    # Drift if <20% keyword overlap after 5+ turns
    if overlap_ratio < 0.2:
        return (
            True,
            f'📍 GOAL ANCHOR: "{state.original_goal[:80]}..."\n🔀 CURRENT: {current_activity[:60]}\n⚠️ Low overlap ({overlap_ratio:.0%}) - verify alignment',
        )

    return False, ""


# =============================================================================
# SUNK COST DETECTOR (v3.1)
# =============================================================================


def track_failure(state: SessionState, approach_signature: str):
    """Track a failure for the current approach."""
    state.consecutive_failures += 1
    state.last_failure_turn = state.turn_count

    for entry in state.approach_history:
        if entry.get("signature") == approach_signature:
            entry["failures"] = entry.get("failures", 0) + 1


def reset_failures(state: SessionState):
    """Reset failure count (on success)."""
    state.consecutive_failures = 0


def check_sunk_cost(state: SessionState) -> tuple[bool, str]:
    """Check if stuck in sunk cost trap.

    Returns: (is_trapped, nudge_message)
    """
    # Check consecutive failures
    if state.consecutive_failures >= 3:
        return (
            True,
            f"🔄 SUNK COST: {state.consecutive_failures} consecutive failures.\n💡 If starting fresh, would you still pick this approach?",
        )

    # Check approach with high turns + failures
    for entry in state.approach_history:
        turns = entry.get("turns", 0)
        failures = entry.get("failures", 0)
        if turns >= 5 and failures >= 2:
            sig = entry.get("signature", "unknown")[:40]
            return (
                True,
                f"🔄 SUNK COST: {turns} turns on `{sig}` with {failures} failures.\n💡 Consider: pivot vs persist?",
            )

    return False, ""


# =============================================================================
# BATCH ENFORCEMENT (v3.2)
# =============================================================================

# Strict batching (local files - you CAN know what you need upfront via ls/find)
STRICT_BATCH_TOOLS = frozenset({"Read", "Grep", "Glob"})
# Soft batching (external URLs - discovery is inherently sequential)
SOFT_BATCH_TOOLS = frozenset({"WebFetch", "WebSearch"})
# Combined for type checking
BATCHABLE_TOOLS = STRICT_BATCH_TOOLS | SOFT_BATCH_TOOLS


def track_batch_tool(state: SessionState, tool_name: str, tools_in_message: int):
    """Track batch/sequential tool usage patterns.

    Args:
        tool_name: Current tool being used
        tools_in_message: Total tool calls in this message (from hook context)
    """
    if tool_name not in BATCHABLE_TOOLS:
        return

    state.last_message_tool_count = tools_in_message

    if tools_in_message == 1:
        state.consecutive_single_reads += 1
    else:
        state.consecutive_single_reads = 0  # Reset on batch


def add_pending_file(state: SessionState, filepath: str):
    """Add a file to pending reads (extracted from prompt/response)."""
    if filepath and filepath not in state.pending_files:
        state.pending_files.append(filepath)
        state.pending_files = state.pending_files[-20:]  # Limit


def add_pending_search(state: SessionState, pattern: str):
    """Add a search pattern to pending searches."""
    if pattern and pattern not in state.pending_searches:
        state.pending_searches.append(pattern)
        state.pending_searches = state.pending_searches[-10:]  # Limit


def clear_pending_file(state: SessionState, filepath: str):
    """Clear a file from pending (after it's been read)."""
    if filepath in state.pending_files:
        state.pending_files.remove(filepath)


def clear_pending_search(state: SessionState, pattern: str):
    """Clear a search from pending (after it's been run)."""
    if pattern in state.pending_searches:
        state.pending_searches.remove(pattern)


FUNCTION_PATTERNS = [
    # Python: def function_name(
    (re.compile(r"\bdef\s+(\w+)\s*\("), "python"),
    # Python: async def function_name(
    (re.compile(r"\basync\s+def\s+(\w+)\s*\("), "python"),
    # JavaScript/TypeScript: function name(
    (re.compile(r"\bfunction\s+(\w+)\s*\("), "js"),
    # JavaScript/TypeScript: const/let/var name = (args) => (arrow function, not IIFE)
    # Excludes IIFEs like `const x = (() => ...)()` by requiring => after params
    (
        re.compile(r"\b(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?\([^)]*\)\s*=>"),
        "js",
    ),
    # JavaScript/TypeScript: export const name =
    (re.compile(r"\bexport\s+(?:const|let|var)\s+(\w+)\s*="), "js"),
    # Class methods: name(args) {
    (re.compile(r"^\s+(\w+)\s*\([^)]*\)\s*\{", re.MULTILINE), "js"),
    # Rust: fn name(
    (re.compile(r"\bfn\s+(\w+)\s*[<(]"), "rust"),
    # Go: func name(
    (re.compile(r"\bfunc\s+(\w+)\s*\("), "go"),
]


# Pre-compiled patterns for function definition line extraction
_FUNC_DEF_PATTERNS = [
    (re.compile(r"^(\s*def\s+(\w+)\s*\([^)]*\)\s*(?:->.*?)?:)"), 2),
    (re.compile(r"^(\s*(?:async\s+)?function\s+(\w+)\s*\([^)]*\))"), 2),
    (re.compile(r"^(\s*(?:pub\s+)?fn\s+(\w+)\s*[<(][^{]*)"), 2),
    (re.compile(r"^(\s*func\s+(\w+)\s*\([^)]*\))"), 2),
]


def extract_function_def_lines(code: str) -> dict[str, str]:
    """Extract function definition LINES for signature change detection."""
    result = {}
    for line in code.split("\n"):
        for pattern, name_group in _FUNC_DEF_PATTERNS:
            match = pattern.match(line)
            if match:
                result[match.group(name_group)] = " ".join(
                    match.group(1).strip().split()
                )
                break
    return result


# Pre-compiled comment stripping patterns
_RE_PYTHON_COMMENT = re.compile(r"#.*$", re.MULTILINE)
_RE_JS_COMMENT = re.compile(r"//.*$", re.MULTILINE)


def add_pending_integration_grep(
    state: SessionState, function_name: str, file_path: str
):
    """Add a function that needs grep verification after edit."""
    # Skip if recently grepped (within 3 turns) - prevents false positive loops
    GREP_COOLDOWN = 3
    grepped_turn = state.grepped_functions.get(function_name, -999)
    if state.turn_count - grepped_turn <= GREP_COOLDOWN:
        return  # Already verified recently, don't re-add

    entry = {
        "function": function_name,
        "file": file_path,
        "turn": state.turn_count,
    }
    # Avoid duplicates
    existing = [p["function"] for p in state.pending_integration_greps]
    if function_name not in existing:
        state.pending_integration_greps.append(entry)
    # Limit to prevent unbounded growth
    state.pending_integration_greps = state.pending_integration_greps[-5:]


def clear_integration_grep(state: SessionState, pattern: str):
    """Clear pending integration grep if pattern matches function name."""
    # Record which functions were cleared (for cooldown tracking)
    for p in state.pending_integration_greps:
        func_name = p["function"]
        if func_name in pattern or pattern in func_name:
            state.grepped_functions[func_name] = state.turn_count

    # Also record the pattern itself as grepped (handles direct function name greps)
    if len(pattern) > 3:  # Skip short patterns
        state.grepped_functions[pattern] = state.turn_count

    # Clean up old entries (keep last 20)
    if len(state.grepped_functions) > 20:
        sorted_funcs = sorted(
            state.grepped_functions.items(), key=lambda x: x[1], reverse=True
        )
        state.grepped_functions = dict(sorted_funcs[:20])

    state.pending_integration_greps = [
        p
        for p in state.pending_integration_greps
        if p["function"] not in pattern and pattern not in p["function"]
    ]


def get_pending_integration_greps(state: SessionState) -> list[dict]:
    """Get pending integration greps (max age: 10 turns)."""
    return [
        p
        for p in state.pending_integration_greps
        if state.turn_count - p.get("turn", 0) <= 10
    ]


def check_integration_blindness(
    state: SessionState, tool_name: str, tool_input: dict
) -> tuple[bool, str]:
    """Check if there are pending integration greps that should block.

    Returns: (should_block, message)

    NOTE: Clearing of pending greps happens in state_updater.py (PostToolUse)
    to avoid race conditions with other PreToolUse hooks.
    """
    pending = get_pending_integration_greps(state)
    if not pending:
        return False, ""

    # Diagnostic tools are always allowed (needed to investigate/clear)
    diagnostic_tools = {"Read", "Grep", "Glob", "Bash", "BashOutput", "TodoWrite"}
    if tool_name in diagnostic_tools:
        return False, ""

    # Read-only Task agents are allowed - they don't edit, just analyze
    # These preserve context window without risking integration blindness
    if tool_name == "Task":
        subagent_type = tool_input.get("subagent_type", "").lower()
        read_only_agents = {
            "scout",
            "digest",
            "parallel",
            "explore",
            "chore",
            "plan",
            "claude-code-guide",
        }
        if subagent_type in read_only_agents:
            return False, ""

    # Non-code files are allowed - integration blindness only matters for code
    # Editing .md, .json, .txt, .yaml etc. doesn't affect function callers
    if tool_name in {"Edit", "Write"}:
        file_path = tool_input.get("file_path", "")
        non_code_extensions = {
            ".md",
            ".json",
            ".txt",
            ".yaml",
            ".yml",
            ".toml",
            ".ini",
            ".cfg",
            ".csv",
            ".css",
            ".scss",
            ".sass",
            ".less",
        }
        from pathlib import Path

        if Path(file_path).suffix.lower() in non_code_extensions:
            return False, ""

        # Allow edits to files that don't contain any pending functions
        # Integration blindness only matters when editing code that might call the changed function
        pending_files = {p["file"] for p in pending}
        if file_path not in pending_files:
            # Editing a different file is allowed - the grep is to find callers,
            # not to block all work. The pending grep remains until satisfied.
            return False, ""

    # Block with message about pending greps
    func_list = ", ".join(f"`{p['function']}`" for p in pending[:3])

    # Add hint about read-only agents if blocking Task
    agent_hint = ""
    if tool_name == "Task":
        agent_hint = "\nNote: Read-only agents (scout, digest, parallel, Explore, chore) are allowed."

    return True, (
        f"**INTEGRATION BLINDNESS BLOCKED** (Hard Block #6)\n"
        f"Edited functions: {func_list}\n"
        f'REQUIRED: Run `grep -r "function_name"` to find callers before continuing.\n'
        f"Pattern: After function edit, grep is MANDATORY.{agent_hint}"
    )


# =============================================================================
# NUDGE TRACKING (v3.4) - Anti-Amnesia System
# =============================================================================

# Nudge categories with default cooldowns (turns before re-showing)
NUDGE_COOLDOWNS = {
    "goal_drift": 8,  # Goal anchor warnings
    "library_research": 5,  # Unresearched library warnings
    "multiple_edits": 10,  # "Edited X times without tests"
    "unresolved_error": 3,  # Pending errors
    "sunk_cost": 5,  # "3 failures on same approach"
    "batch_opportunity": 4,  # "Could batch these reads"
    "iteration_loop": 3,  # "4+ same tool calls"
    "stub_warning": 10,  # New file has stubs
    "default": 5,  # Fallback cooldown
}

# Escalation thresholds
ESCALATION_THRESHOLD = 3  # After 3 ignored nudges, escalate severity


def _content_hash(content: str) -> int:
    """Simple hash of content for dedup (first 100 chars)."""
    return hash(content[:100])


def should_nudge(
    state: SessionState, nudge_type: str, content: str = ""
) -> tuple[bool, str]:
    """Check if a nudge should be shown based on history.

    Returns: (should_show, severity)
        severity: "normal", "escalate", or "suppress"
    """
    history = state.nudge_history.get(nudge_type, {})
    cooldown = NUDGE_COOLDOWNS.get(nudge_type, NUDGE_COOLDOWNS["default"])

    last_turn = history.get("last_turn", -999)
    turns_since = state.turn_count - last_turn

    # Check cooldown
    if turns_since < cooldown:
        # Same content within cooldown? Suppress
        if content and history.get("last_content_hash") == _content_hash(content):
            return False, "suppress"
        # Different content? Allow (new situation)
        if content and history.get("last_content_hash") != _content_hash(content):
            return True, "normal"
        return False, "suppress"

    # Check for escalation (ignored multiple times)
    times_ignored = history.get("times_ignored", 0)
    if times_ignored >= ESCALATION_THRESHOLD:
        return True, "escalate"

    return True, "normal"


def record_nudge(state: SessionState, nudge_type: str, content: str = ""):
    """Record that a nudge was shown."""
    if nudge_type not in state.nudge_history:
        state.nudge_history[nudge_type] = {}

    history = state.nudge_history[nudge_type]
    history["last_turn"] = state.turn_count
    history["times_shown"] = history.get("times_shown", 0) + 1
    if content:
        history["last_content_hash"] = _content_hash(content)


def start_feature(state: SessionState, description: str) -> str:
    """Start tracking a new feature/task.

    Returns: feature_id for reference
    """
    feature_id = f"F{int(time.time())}"

    # Close any current feature first
    if state.current_feature:
        complete_feature(state, "interrupted")

    state.current_feature = description[:200]
    state.current_feature_started = time.time()
    state.current_feature_start_turn = state.turn_count
    state.current_feature_files = []

    return feature_id


def complete_feature(state: SessionState, status: str = "completed"):
    """Complete the current feature and log it.

    Args:
        status: "completed", "interrupted", "blocked", "abandoned"
    """
    if not state.current_feature:
        return

    entry = {
        "feature_id": f"F{int(state.current_feature_started)}",
        "description": state.current_feature,
        "status": status,
        "files": list(set(state.current_feature_files))[-10:],  # Dedupe, limit
        "errors": len(
            [
                e
                for e in state.errors_recent
                if e.get("timestamp", 0) > state.current_feature_started
            ]
        ),
        "started": state.current_feature_started,
        "completed": time.time(),
        # Use feature start turn for accurate turn count (not goal_set_turn)
        "turns": state.turn_count - state.current_feature_start_turn,
    }
    state.progress_log.append(entry)
    state.progress_log = state.progress_log[-20:]  # Keep last 20

    # Reset current feature
    state.current_feature = ""
    state.current_feature_started = 0.0
    state.current_feature_start_turn = 0
    state.current_feature_files = []


def track_feature_file(state: SessionState, filepath: str):
    """Track a file as part of current feature work."""
    if filepath and filepath not in state.current_feature_files:
        state.current_feature_files.append(filepath)
        state.current_feature_files = state.current_feature_files[-20:]


def add_work_item(
    state: SessionState,
    item_type: str,
    source: str,
    description: str,
    priority: int = 50,
) -> str:
    """Add an auto-discovered work item to the queue.

    Args:
        item_type: "error", "todo", "test_failure", "gap", "stub"
        source: File or command that surfaced this
        description: What needs to be done
        priority: 0-100 (higher = more urgent)

    Returns: work_item_id
    """
    item_id = f"W{int(time.time() * 1000) % 100000}"

    # Check for duplicates (same type + similar description)
    for existing in state.work_queue:
        if existing.get("type") == item_type:
            # Simple similarity: first 50 chars match
            if existing.get("description", "")[:50] == description[:50]:
                return existing.get("id", item_id)  # Return existing

    item = {
        "id": item_id,
        "type": item_type,
        "source": source[:100],
        "description": description[:200],
        "priority": priority,
        "discovered_at": time.time(),
        "status": "pending",
    }
    state.work_queue.append(item)
    state.work_queue = state.work_queue[-30:]  # Limit queue size

    return item_id


def get_next_work_item(state: SessionState) -> Optional[dict]:
    """Get the highest priority pending work item.

    Priority factors:
    1. Explicit priority score
    2. Errors > test_failures > gaps > todos > stubs
    3. Recency (newer items slightly higher)
    """
    pending = [w for w in state.work_queue if w.get("status") == "pending"]
    if not pending:
        return None

    # Type priority multipliers
    type_weights = {
        "error": 1.5,
        "test_failure": 1.3,
        "gap": 1.1,
        "todo": 1.0,
        "stub": 0.8,
    }

    def score(item):
        base = item.get("priority", 50)
        type_mult = type_weights.get(item.get("type", ""), 1.0)
        # Slight recency boost (newer = higher)
        age = time.time() - item.get("discovered_at", 0)
        recency = max(0, 1 - age / 86400)  # Decays over 24h
        return base * type_mult + recency * 10

    return max(pending, key=score)


def create_checkpoint(state: SessionState, commit_hash: str = "", notes: str = ""):
    """Record a checkpoint for recovery.

    Call this after significant progress (successful tests, feature complete, etc.)
    """
    checkpoint = {
        "checkpoint_id": f"CP{int(time.time())}",
        "commit_hash": commit_hash,
        "feature": state.current_feature,
        "timestamp": time.time(),
        "turn": state.turn_count,
        "files_edited": list(state.files_edited[-10:]),
        "notes": notes[:100],
    }
    state.checkpoints.append(checkpoint)
    state.checkpoints = state.checkpoints[-10:]  # Keep last 10
    state.last_checkpoint_turn = state.turn_count


def prepare_handoff(state: SessionState) -> dict:
    """Prepare session handoff data for context bridging.

    Call this at session end to preserve context for next session.
    """
    # Auto-generate summary
    summary_parts = []

    # What was accomplished
    completed = [p for p in state.progress_log if p.get("status") == "completed"]
    if completed:
        recent = completed[-3:]
        summary_parts.append(
            f"Completed: {', '.join(p['description'][:30] for p in recent)}"
        )

    # Current work
    if state.current_feature:
        summary_parts.append(f"In progress: {state.current_feature[:50]}")

    # Errors encountered
    if state.errors_unresolved:
        summary_parts.append(f"Unresolved errors: {len(state.errors_unresolved)}")

    state.handoff_summary = (
        " | ".join(summary_parts) if summary_parts else "No significant progress"
    )

    # Next steps (from work queue)
    next_items = sorted(
        [w for w in state.work_queue if w.get("status") == "pending"],
        key=lambda x: x.get("priority", 0),
        reverse=True,
    )[:5]
    state.handoff_next_steps = [
        {"type": w["type"], "description": w["description"][:80]} for w in next_items
    ]

    # Blockers
    state.handoff_blockers = [
        {"type": e.get("type", "error")[:30], "details": e.get("details", "")[:50]}
        for e in state.errors_unresolved[:3]
    ]

    return {
        "summary": state.handoff_summary,
        "next_steps": state.handoff_next_steps,
        "blockers": state.handoff_blockers,
    }


def extract_work_from_errors(state: SessionState):
    """Auto-extract work items from recent errors.

    Call periodically to populate work queue from error patterns.
    """
    for error in state.errors_unresolved:
        error_type = error.get("type", "unknown")
        details = error.get("details", "")

        # Skip already-processed
        existing_ids = {w.get("source") for w in state.work_queue}
        error_key = f"error:{error_type[:20]}"
        if error_key in existing_ids:
            continue

        # Determine priority based on error type
        priority = 70  # Default high
        if "syntax" in error_type.lower():
            priority = 90
        elif "import" in error_type.lower():
            priority = 85
        elif "test" in error_type.lower():
            priority = 80

        add_work_item(
            state,
            item_type="error",
            source=error_key,
            description=f"Fix: {error_type} - {details[:100]}",
            priority=priority,
        )


# =============================================================================
# ADAPTIVE THRESHOLD LEARNING (v3.7)
# Prevents hook fatigue by auto-adjusting thresholds based on trigger patterns.
# Inspired by claude-starter's posttooluse-metacognition.py learning system.
# =============================================================================

# Default thresholds for various patterns (can be adjusted per-session)
DEFAULT_THRESHOLDS = {
    # Code quality patterns
    "quality_long_method": 50,  # Lines before warning
    "quality_high_complexity": 10,  # Conditionals before warning
    "quality_deep_nesting": 4,  # Nesting levels before warning
    "quality_debug_statements": 3,  # console.log/print count
    "quality_tech_debt_markers": 5,  # TODO/FIXME count
    "quality_magic_numbers": 5,  # Numeric literals count
    # Performance patterns
    "perf_blocking_io": 1,  # Sync file ops
    "perf_repeated_calculation": 3,  # Same expensive op calls
    "perf_repeated_calculation_ops": 2,
    # Batch/iteration patterns
    "batch_sequential_reads": 3,  # Sequential single reads before warning
    "iteration_same_tool": 4,  # Same tool in 5 turns
    # Other
    "velocity_oscillation": 3,  # Back-forth edits
}

# Cooldown durations (seconds) - suppress pattern after recent trigger
THRESHOLD_COOLDOWNS = {
    "quality_long_method": 3600,  # 1 hour
    "quality_high_complexity": 3600,
    "quality_deep_nesting": 3600,
    "quality_debug_statements": 1800,  # 30 min
    "quality_tech_debt_markers": 3600,
    "quality_magic_numbers": 1800,
    "perf_blocking_io": 1800,
    "perf_repeated_calculation": 1800,
    "batch_sequential_reads": 600,  # 10 min
    "iteration_same_tool": 600,
    "velocity_oscillation": 600,
    "default": 1800,
}


def get_adaptive_threshold(state: SessionState, pattern_name: str) -> float:
    """Get adaptive threshold for a pattern, adjusted based on usage history.

    Returns float('inf') if pattern is in cooldown (should be suppressed).

    Adaptation rules:
    - Trigger < 5 min after last: +50% threshold, enter 1hr cooldown (likely false positive)
    - Trigger > 24 hrs after last: -10% threshold (valuable insight, lower bar)
    - Floor: 50% of default (never go below this)
    - Ceiling: 300% of default (don't make it impossible to trigger)
    """
    # Get learning state for this pattern
    learning = state.nudge_history.get(f"threshold_{pattern_name}", {})
    default = DEFAULT_THRESHOLDS.get(pattern_name, 10)
    current_threshold = learning.get("threshold", default)

    # Check cooldown
    cooldown_until = learning.get("cooldown_until", 0)
    if cooldown_until and time.time() < cooldown_until:
        return float("inf")  # Suppress during cooldown

    # Time-based adjustment
    last_trigger = learning.get("last_trigger", 0)
    if last_trigger:
        time_since = time.time() - last_trigger

        if time_since < 300:  # < 5 minutes - likely false positive
            # Increase threshold 50%, enter cooldown
            current_threshold = min(current_threshold * 1.5, default * 3.0)
            cooldown_duration = THRESHOLD_COOLDOWNS.get(
                pattern_name, THRESHOLD_COOLDOWNS["default"]
            )
            learning["cooldown_until"] = time.time() + cooldown_duration
            learning["threshold"] = current_threshold
            state.nudge_history[f"threshold_{pattern_name}"] = learning

        elif time_since > 86400:  # > 24 hours - valuable insight
            # Decrease threshold 10%, floor at 50% of default
            current_threshold = max(current_threshold * 0.9, default * 0.5)
            learning["threshold"] = current_threshold
            state.nudge_history[f"threshold_{pattern_name}"] = learning

    return current_threshold


def record_threshold_trigger(state: SessionState, pattern_name: str, value: int = 1):
    """Record that a pattern was triggered (for adaptive learning).

    Call this AFTER the threshold check passes and the warning is shown.
    """
    key = f"threshold_{pattern_name}"
    if key not in state.nudge_history:
        state.nudge_history[key] = {
            "threshold": DEFAULT_THRESHOLDS.get(pattern_name, 10),
            "trigger_count": 0,
            "last_trigger": 0,
            "cooldown_until": 0,
        }

    state.nudge_history[key]["trigger_count"] = (
        state.nudge_history[key].get("trigger_count", 0) + 1
    )
    state.nudge_history[key]["last_trigger"] = time.time()
    state.nudge_history[key]["last_value"] = value


CASCADE_THRESHOLD = 3  # Blocks before escalation
CASCADE_WINDOW = 5  # Turns within which blocks must occur


def track_block(state: SessionState, hook_name: str):
    """Track a block from a hook for cascade detection."""
    if hook_name not in state.consecutive_blocks:
        state.consecutive_blocks[hook_name] = {
            "count": 0,
            "first_turn": state.turn_count,
            "last_turn": 0,
        }

    entry = state.consecutive_blocks[hook_name]

    # Reset if too many turns passed (not a cascade)
    if state.turn_count - entry.get("last_turn", 0) > CASCADE_WINDOW:
        entry["count"] = 0
        entry["first_turn"] = state.turn_count

    entry["count"] = entry.get("count", 0) + 1
    entry["last_turn"] = state.turn_count
    state.last_block_turn = state.turn_count


def clear_blocks(state: SessionState, hook_name: str = None):
    """Clear block tracking (on success or user bypass)."""
    if hook_name:
        if hook_name in state.consecutive_blocks:
            del state.consecutive_blocks[hook_name]
    else:
        state.consecutive_blocks = {}


def check_cascade_failure(state: SessionState, hook_name: str) -> tuple[bool, str]:
    """Check if we're in a cascade failure state for a hook.

    Returns: (is_cascade, escalation_message)
    """
    entry = state.consecutive_blocks.get(hook_name, {})
    count = entry.get("count", 0)

    if count < CASCADE_THRESHOLD:
        return False, ""

    # Check if blocks are recent (within window)
    turns_since_first = state.turn_count - entry.get("first_turn", 0)
    if turns_since_first > CASCADE_WINDOW * 2:
        # Old blocks, not a cascade
        return False, ""

    return True, (
        f"⚠️ **CASCADE FAILURE**: `{hook_name}` blocked {count}x in {turns_since_first} turns.\n"
        f"💡 Try: `/think` to decompose, `/oracle` for advice, or say 'BYPASS {hook_name}' to override once."
    )


def _apply_mean_reversion_on_load(state: SessionState) -> SessionState:
    """Apply mean reversion based on idle time when loading state.

    Called during load_state to pull confidence toward baseline after idle periods.
    """
    if state.last_activity_time <= 0:
        return state

    import time as _time

    current_time = _time.time()
    new_confidence, reason = calculate_idle_reversion(
        state.confidence, state.last_activity_time, current_time
    )

    if new_confidence != state.confidence:
        # Log the reversion (will be shown in next hook output)
        state.nudge_history["_mean_reversion_applied"] = {
            "old": state.confidence,
            "new": new_confidence,
            "reason": reason,
        }
        set_confidence(state, new_confidence, f"mean_reversion: {reason}")

    return state
