#!/usr/bin/env python3
"""
Session Cleanup Hook v3: SessionEnd hook for cleanup and persistence.

This hook fires when Claude Code session ends and:
- Persists learned patterns to long-term memory
- Updates lessons.md with session insights
- Cleans up .claude/tmp/ temporary files
- Generates session summary for telemetry
- Saves final state snapshot

Silent by default - performs cleanup in background.
"""

import _lib_path  # noqa: F401
from _logging import log_debug
import sys
import json
import time
import os
import fcntl
import tempfile
from pathlib import Path
from datetime import datetime

# Import the state machine
from session_state import (
    load_state,
    save_state,
    get_session_summary,
    MEMORY_DIR,
    prepare_handoff,
    complete_feature,
    extract_work_from_errors,
)

# Import project-aware state management
from _cooldown import _resolve_state_path

try:
    from project_detector import get_current_project
    from project_state import get_project_memory_dir

    PROJECT_AWARE = True
except ImportError:
    PROJECT_AWARE = False

# Import thinking memory for auto-indexing (v3.15)
try:
    from thinking_memory import (
        index_recent_sessions,
        prune_old_records,
        get_thinking_stats,
    )

    THINKING_MEMORY_AVAILABLE = True
except ImportError:
    THINKING_MEMORY_AVAILABLE = False

# =============================================================================
# CONFIGURATION
# =============================================================================

SCRATCH_DIR = (
    Path(__file__).resolve().parent.parent / "tmp"
)  # .claude/hooks -> .claude -> .claude/tmp
STATE_DIR = MEMORY_DIR / "state"  # Runtime state separated from semantic memory
LESSONS_FILE = MEMORY_DIR / "__lessons.md"


# Session log uses project-isolated state via _cooldown
def _get_session_log_file() -> Path:
    """Get project-isolated session log file."""
    return _resolve_state_path("session_log.jsonl")


# Legacy paths (used as fallback when not project-aware)
PROGRESS_FILE = MEMORY_DIR / "progress.json"  # Autonomous agent progress tracking
HANDOFF_FILE = MEMORY_DIR / "handoff.json"  # Session handoff data


def _get_project_progress_file() -> Path:
    """Get progress file path (project-scoped if available)."""
    if PROJECT_AWARE:
        try:
            context = get_current_project()
            return get_project_memory_dir(context.project_id) / "progress.json"
        except Exception as e:
            log_debug("session_cleanup", f"project progress path failed: {e}")
    return PROGRESS_FILE


def _get_project_handoff_file() -> Path:
    """Get handoff file path (project-scoped if available)."""
    if PROJECT_AWARE:
        try:
            context = get_current_project()
            return get_project_memory_dir(context.project_id) / "handoff.json"
        except Exception as e:
            log_debug("session_cleanup", f"project handoff path failed: {e}")
    return HANDOFF_FILE


# Files in .claude/tmp/ older than this get cleaned (in seconds)
SCRATCH_CLEANUP_AGE = 86400  # 24 hours

# Minimum edits to a file before generating a lesson
LESSON_EDIT_THRESHOLD = 3

# Serena memory grooming settings
SERENA_SESSION_MEMORY_KEEP = 30  # Keep last N session_* memories
SERENA_STRUCTURAL_MEMORIES = {
    # These are kept forever (not session ephemera)
    "beads_system.md",
    "codebase_structure.md",
    "confidence_increasers.md",
    "confidence_reducers.md",
    "confidence_system.md",
    "hook_registry.md",
    "integration_synergy.md",
    "lib_modules.md",
    "memory_index.md",
    "ops_tools.md",
    "post_tool_use_hooks.md",
    "pre_tool_use_hooks.md",
    "project_overview.md",
    "prompt_suggestions.md",
    "session_runners.md",
    "session_state.md",
    "slash_commands.md",
    "stop_hooks.md",
    "style_conventions.md",
    "suggested_commands.md",
    "task_completion.md",
}

# =============================================================================
# PATTERN EXTRACTION
# =============================================================================


def extract_lessons(state) -> list[dict]:
    """Extract lessons from session patterns.

    NOTE: Only extract HIGH-VALUE lessons worth persisting to lessons.md.
    Telemetry/stats go to session_log.jsonl, not lessons.md.

    Removed (low value, polluted lessons.md):
    - file_complexity: "Edited X 5x" - noise, not actionable
    - unresearched_libs: Lists stdlib modules - garbage
    - domain_focus: "Session focused on X" - trivia
    - recurring_error: Rarely actionable without context
    - abandoned_stubs: Became noise - files with stubs pile up across projects
      without being actionable. Better tracked via beads or linting.

    Currently: Returns empty. Lessons should be manually added via remember.py
    or auto-remember hooks that extract from assistant output, not auto-generated
    from session telemetry patterns.
    """
    # No auto-generated lessons - they all became noise over time
    return []


def _extract_recent_insights(existing: str) -> set[str]:
    """Extract recent insight texts for deduplication."""
    recent_insights = set()
    for line in existing.split("\n")[-50:]:
        if line.startswith("- ["):
            parts = line.split("] ", 1)
            if len(parts) > 1:
                recent_insights.add(parts[1].strip().lower())
    return recent_insights


def _deduplicate_lessons(lessons: list[dict], recent_insights: set[str]) -> list[dict]:
    """Filter out lessons that already exist in recent insights."""
    new_lessons = []
    for lesson in lessons:
        insight_lower = lesson["insight"].lower()
        if insight_lower not in recent_insights:
            new_lessons.append(lesson)
            recent_insights.add(insight_lower)
    return new_lessons


def persist_lessons(lessons: list[dict]):
    """Append lessons to lessons.md file with deduplication.

    Uses atomic read-modify-write with file locking to avoid TOCTOU race.
    """
    if not lessons:
        return

    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    lock_file = MEMORY_DIR / ".lessons.lock"
    lock_fd = os.open(str(lock_file), os.O_CREAT | os.O_RDWR)

    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)

        existing = ""
        try:
            existing = LESSONS_FILE.read_text()
        except FileNotFoundError:
            pass

        new_lessons = _deduplicate_lessons(lessons, _extract_recent_insights(existing))
        if not new_lessons:
            return

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        new_content = f"\n### {timestamp}\n"
        new_content += "".join(
            f"- [{lesson['type']}] {lesson['insight']}\n" for lesson in new_lessons
        )

        with open(LESSONS_FILE, "a") as f:
            if "## Session Lessons" not in existing:
                f.write("\n\n## Session Lessons\n")
            f.write(new_content)
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)


# =============================================================================
# SCRATCH CLEANUP
# =============================================================================

SESSION_ENV_DIR = Path(__file__).resolve().parent.parent / "session-env"
SESSION_ENV_KEEP = 20  # Keep this many most recent session-env dirs


def groom_serena_memories() -> dict[str, int]:
    """Groom Serena memories: keep structural + last N session memories.

    Returns dict with counts: {"kept": N, "pruned": M, "structural": K}
    """
    result = {"kept": 0, "pruned": 0, "structural": 0}

    # Find .serena/memories in current project or walk up
    cwd = Path.cwd()
    serena_dir = None
    for parent in [cwd, *cwd.parents]:
        candidate = parent / ".serena" / "memories"
        if candidate.is_dir():
            serena_dir = candidate
            break
        if parent == Path.home():
            break

    if not serena_dir:
        return result

    # Separate structural from session memories
    structural = []
    sessions = []

    for mem_file in serena_dir.glob("*.md"):
        if mem_file.name in SERENA_STRUCTURAL_MEMORIES:
            structural.append(mem_file)
        elif mem_file.name.startswith("session_"):
            sessions.append(mem_file)
        else:
            # Unknown memory - keep it (might be important)
            structural.append(mem_file)

    result["structural"] = len(structural)

    # Sort sessions by mtime (newest first), prune excess
    sessions.sort(key=lambda f: f.stat().st_mtime, reverse=True)

    kept = sessions[:SERENA_SESSION_MEMORY_KEEP]
    to_prune = sessions[SERENA_SESSION_MEMORY_KEEP:]

    result["kept"] = len(kept)
    result["pruned"] = 0

    for mem_file in to_prune:
        try:
            mem_file.unlink()
            result["pruned"] += 1
        except (OSError, PermissionError):
            pass

    return result


def cleanup_scratch():
    """Clean up old files in .claude/tmp/ directory."""
    if not SCRATCH_DIR.exists():
        return []

    cleaned = []
    cutoff = time.time() - SCRATCH_CLEANUP_AGE

    for filepath in SCRATCH_DIR.iterdir():
        # Skip .gitkeep and directories
        if filepath.name == ".gitkeep" or filepath.is_dir():
            continue

        try:
            mtime = filepath.stat().st_mtime
            if mtime < cutoff:
                filepath.unlink()
                cleaned.append(filepath.name)
        except (OSError, PermissionError):
            pass

    return cleaned


def cleanup_session_env() -> int:
    """Clean up old session-env directories, keeping most recent N.

    Returns count of directories removed.
    """
    if not SESSION_ENV_DIR.exists():
        return 0

    import shutil

    # Get all session dirs with their mtime
    session_dirs = []
    for d in SESSION_ENV_DIR.iterdir():
        if d.is_dir():
            try:
                mtime = d.stat().st_mtime
                session_dirs.append((mtime, d))
            except OSError:
                pass

    # Sort by mtime descending (newest first)
    session_dirs.sort(key=lambda x: x[0], reverse=True)

    # Remove old ones beyond the keep threshold
    removed = 0
    for mtime, dirpath in session_dirs[SESSION_ENV_KEEP:]:
        try:
            shutil.rmtree(dirpath)
            removed += 1
        except (OSError, PermissionError):
            pass

    return removed


# =============================================================================
# THINKING MEMORY GROOMING (v3.15)
# =============================================================================

THINKING_MEMORY_MAX_RECORDS = 500  # Auto-prune when exceeding this
THINKING_INDEX_SESSIONS = 5  # Index last N sessions per cleanup


def groom_thinking_memory() -> dict[str, int]:
    """Auto-index recent sessions and prune old thinking records.

    Runs on every session end to keep thinking memory fresh and bounded.
    Returns dict with counts: {"indexed": N, "pruned": M, "total": K}
    """
    result = {"indexed": 0, "pruned": 0, "total": 0}

    if not THINKING_MEMORY_AVAILABLE:
        return result

    try:
        # Index recent sessions (incremental - skips already indexed)
        index_result = index_recent_sessions(max_sessions=THINKING_INDEX_SESSIONS)
        result["indexed"] = index_result.get("indexed", 0)

        # Get current stats
        stats = get_thinking_stats()
        result["total"] = stats.get("total", 0)

        # Auto-prune if exceeding threshold
        if result["total"] > THINKING_MEMORY_MAX_RECORDS:
            result["pruned"] = prune_old_records(keep_count=THINKING_MEMORY_MAX_RECORDS)

    except Exception as e:
        log_debug("session_cleanup", f"thinking memory groom failed: {e}")

    return result


# =============================================================================
# SESSION LOG
# =============================================================================


def log_session(state, lessons: list[dict]):
    """Append session summary to log file."""
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)

    summary = get_session_summary(state)
    summary["ended_at"] = time.time()
    summary["lessons_count"] = len(lessons)
    summary["timestamp"] = datetime.now().isoformat()

    log_file = _get_session_log_file()
    log_file.parent.mkdir(parents=True, exist_ok=True)
    with open(log_file, "a") as f:
        f.write(json.dumps(summary) + "\n")


# =============================================================================
# AUTONOMOUS AGENT: PROGRESS & HANDOFF PERSISTENCE
# =============================================================================


def _atomic_json_write(filepath: Path, data: dict):
    """Write JSON atomically with file locking to prevent corruption.

    Uses fcntl.flock for exclusive access and temp file + rename for atomicity.
    """
    filepath.parent.mkdir(parents=True, exist_ok=True)
    lock_file = filepath.parent / f".{filepath.name}.lock"

    # Acquire exclusive lock
    lock_fd = os.open(str(lock_file), os.O_CREAT | os.O_RDWR)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)

        # Write to temp file first
        fd, tmp_path = tempfile.mkstemp(dir=filepath.parent, suffix=".json")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(data, f, indent=2, default=str)
            os.replace(tmp_path, filepath)  # Atomic on POSIX
        except Exception:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            raise
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)


def save_progress(state):
    """Save progress log to JSON file for cross-session persistence.

    This implements the Anthropic "progress tracking" pattern:
    https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents

    Using JSON instead of Markdown because "the model is less likely to
    inappropriately change or overwrite JSON files compared to Markdown files."

    NOTE: Progress is now project-scoped to avoid cross-project pollution.
    """
    progress_file = _get_project_progress_file()
    progress_file.parent.mkdir(parents=True, exist_ok=True)

    # Load existing progress
    existing = []
    if progress_file.exists():
        try:
            with open(progress_file) as f:
                data = json.load(f)
                existing = data.get("entries", [])
        except (json.JSONDecodeError, KeyError):
            pass

    # Merge new progress (dedupe by feature_id)
    existing_ids = {e.get("feature_id") for e in existing}
    for entry in state.progress_log:
        if entry.get("feature_id") not in existing_ids:
            existing.append(entry)

    # Trim to last 50 entries
    existing = existing[-50:]

    # Save atomically with locking
    progress_data = {
        "last_updated": datetime.now().isoformat(),
        "session_id": state.session_id,
        "entries": existing,
        "work_queue": [w for w in state.work_queue if w.get("status") == "pending"][
            :20
        ],
    }

    _atomic_json_write(progress_file, progress_data)


def save_handoff(state):
    """Save session handoff data for next session.

    This is the key insight from Anthropic's agent harness:
    "agents need a way to bridge the gap between coding sessions"
    through structured artifacts.

    NOTE: Handoff is now project-scoped to avoid cross-project pollution.
    """
    handoff_file = _get_project_handoff_file()
    handoff_file.parent.mkdir(parents=True, exist_ok=True)

    # Prepare handoff data
    handoff = prepare_handoff(state)

    # Add session metadata and save atomically with locking
    handoff_data = {
        "prepared_at": datetime.now().isoformat(),
        "session_id": state.session_id,
        "summary": handoff["summary"],
        "next_steps": handoff["next_steps"],
        "blockers": handoff["blockers"],
        # Include recent file context for onboarding
        "recent_files": state.files_edited[-5:],
        "recent_commits": [],  # Could be populated from git log
        # Include checkpoint for recovery
        "last_checkpoint": state.checkpoints[-1] if state.checkpoints else None,
    }

    _atomic_json_write(handoff_file, handoff_data)


# =============================================================================
# MAIN
# =============================================================================


def main():
    """SessionEnd hook entry point."""
    try:
        json.load(sys.stdin)  # Consume stdin
    except (json.JSONDecodeError, ValueError):
        pass

    # Load current state
    state = load_state()

    # === AUTONOMOUS AGENT: Finalize current work ===

    # Complete any in-progress feature (mark as interrupted if session ending)
    if state.current_feature:
        complete_feature(state, "interrupted")

    # Auto-extract work items from unresolved errors
    extract_work_from_errors(state)

    # Extract lessons from session patterns
    lessons = extract_lessons(state)

    # Persist lessons to long-term memory
    persist_lessons(lessons)

    # === AUTONOMOUS AGENT: Save progress & handoff ===

    # Save progress log (JSON, survives sessions)
    save_progress(state)

    # Save handoff data for next session onboarding
    save_handoff(state)

    # Clean up old scratch files
    cleaned_files = cleanup_scratch()

    # Clean up old session-env directories (keep last 20)
    removed_sessions = cleanup_session_env()

    # Groom Serena memories (keep structural + last N session memories)
    serena_groom = groom_serena_memories()

    # Groom thinking memory (auto-index + prune)
    thinking_groom = groom_thinking_memory()

    # Log session summary
    log_session(state, lessons)

    # Save final state
    save_state(state)

    # Output result (silent unless debugging)
    output = {}

    # Optionally surface cleanup info
    cleanup_parts = []
    if cleaned_files:
        cleanup_parts.append(f"{len(cleaned_files)} scratch files")
    if removed_sessions:
        cleanup_parts.append(f"{removed_sessions} old sessions")
    if serena_groom.get("pruned", 0) > 0:
        cleanup_parts.append(f"{serena_groom['pruned']} stale Serena memories")
    if thinking_groom.get("indexed", 0) > 0:
        cleanup_parts.append(f"{thinking_groom['indexed']} thinking memories indexed")
    if thinking_groom.get("pruned", 0) > 0:
        cleanup_parts.append(f"{thinking_groom['pruned']} old thinking records pruned")
    if cleanup_parts:
        output["message"] = f"🧹 Cleaned {', '.join(cleanup_parts)}"

    print(json.dumps(output))
    sys.exit(0)


if __name__ == "__main__":
    main()
