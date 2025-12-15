#!/usr/bin/env python3
"""
Session Init Hook v3: SessionStart hook for initialization.

SYSTEM CONTEXT: Global WSL2 assistant at /home/blake
- Full system access, not project-scoped
- Can help with any task across the system
- Projects live in ~/projects/, AI projects in ~/ai/

This hook fires when Claude Code starts a new session and:
- Detects stale state from previous sessions
- Initializes fresh state with proper session_id
- Refreshes ops script discovery
- Clears accumulated errors/gaps from dead sessions
- Sets up session metadata
- Surfaces actionable context on resume (files, tasks, errors)

Silent by default - outputs brief status only if resuming work or issues detected.
"""

import _lib_path  # noqa: F401
from _logging import log_debug
import sys
import json
import os
import time
from pathlib import Path

# Import the state machine
from session_state import (
    load_state,
    save_state,
    reset_state,
    MEMORY_DIR,
    _discover_ops_scripts,
    get_next_work_item,
    start_feature,
)

# Import project-aware state management
# Note: Some imports reserved for future features or API consistency
try:
    from project_detector import get_current_project, ProjectContext  # noqa: F401 (docstring type)
    from project_state import (
        get_active_project_state,  # noqa: F401 (reserved: project switching)
        save_active_state,  # noqa: F401 (reserved: project switching)
        run_maintenance,
        get_contextual_lessons,
        is_same_project,  # noqa: F401 (reserved: project switching)
    )

    PROJECT_AWARE = True
except ImportError:
    PROJECT_AWARE = False

# Import spark_core for pre-warming (lazy load synapse map)
try:
    from spark_core import _load_synapses, fire_synapses  # noqa: F401 (commented code line 177)

    SPARK_AVAILABLE = True
except ImportError:
    SPARK_AVAILABLE = False

# Import dependency checker (v3.10)
try:
    from dependency_check import run_dependency_check

    DEPENDENCY_CHECK_AVAILABLE = True
except ImportError:
    DEPENDENCY_CHECK_AVAILABLE = False

# Scope's punch list file
PUNCH_LIST_FILE = MEMORY_DIR / "punch_list.json"

# Infrastructure manifest (prevents "create X" when X exists)
INFRASTRUCTURE_FILE = MEMORY_DIR / "__infrastructure.md"

# Capabilities index (prevents functional duplication)
CAPABILITIES_FILE = MEMORY_DIR / "__capabilities.md"

# Autonomous agent files (legacy - now project-scoped)
HANDOFF_FILE = MEMORY_DIR / "handoff.json"
PROGRESS_FILE = MEMORY_DIR / "progress.json"


def _get_project_handoff_file(project_context=None) -> Path:
    """Get handoff file path (project-scoped if available)."""
    if PROJECT_AWARE and project_context:
        try:
            from project_state import get_project_memory_dir

            return get_project_memory_dir(project_context.project_id) / "handoff.json"
        except Exception as e:
            log_debug("session_init", f"project context loading failed: {e}")
    return HANDOFF_FILE


def _get_project_progress_file(project_context=None) -> Path:
    """Get progress file path (project-scoped if available)."""
    if PROJECT_AWARE and project_context:
        try:
            from project_state import get_project_memory_dir

            return get_project_memory_dir(project_context.project_id) / "progress.json"
        except Exception as e:
            log_debug("session_init", f"project context loading failed: {e}")
    return PROGRESS_FILE


# =============================================================================
# CONFIGURATION
# =============================================================================

# Sessions older than this are considered stale (in seconds)
STALE_SESSION_THRESHOLD = 3600  # 1 hour

# Maximum age for errors to carry over (in seconds)
ERROR_CARRY_OVER_MAX = 600  # 10 minutes

# =============================================================================
# SYSTEM HEALTH CHECK (v3.9)
# =============================================================================


def check_system_health() -> str | None:
    """Quick system health check at session start.

    Returns warning message if resources are constrained, None otherwise.
    """
    import subprocess

    try:
        result = subprocess.run(
            [
                str(Path.home() / ".claude" / "hooks" / "py"),
                str(Path.home() / ".claude" / "ops" / "sysinfo.py"),
                "--quick",
            ],
            capture_output=True,
            text=True,
            timeout=3,
        )
        if result.returncode != 0:
            return None

        output = result.stdout.strip()
        # Parse: "CPU: 2.26 2.02 2.02 | Mem: 22% | Disk: 48%"
        warnings = []

        # Check memory
        if "Mem:" in output:
            import re

            mem_match = re.search(r"Mem:\s*(\d+)%", output)
            if mem_match and int(mem_match.group(1)) > 85:
                warnings.append(f"⚠️ Memory: {mem_match.group(1)}% used")

        # Check disk
        if "Disk:" in output:
            import re

            disk_match = re.search(r"Disk:\s*(\d+)%", output)
            if disk_match and int(disk_match.group(1)) > 90:
                warnings.append(f"⚠️ Disk: {disk_match.group(1)}% used")

        # Check CPU load (first value is 1-min avg)
        if "CPU:" in output:
            import re

            cpu_match = re.search(r"CPU:\s*([\d.]+)", output)
            if cpu_match and float(cpu_match.group(1)) > 4.0:
                warnings.append(f"⚠️ CPU Load: {cpu_match.group(1)}")

        return " | ".join(warnings) if warnings else None

    except Exception:
        return None  # Non-critical, don't fail session start


# =============================================================================
# MEMORY PRE-WARMING
# =============================================================================


def prewarm_memory_cache():
    """Pre-load synapse map and warm cache with common patterns.

    This runs at session start to eliminate cold-start latency on first prompt.
    Target: <50ms total.
    """
    if not SPARK_AVAILABLE:
        return

    try:
        # 1. Load synapse map into memory (cached for session)
        _load_synapses()

        # 2. Pre-warm spark cache with common terms
        # Reduces first-query latency by ~100-500ms
        common_prompts = ["error", "fix", "implement", "test", "refactor"]
        for prompt in common_prompts:
            fire_synapses(
                prompt, include_constraints=False, include_session_history=False
            )

    except Exception as e:
        log_debug("session_init", f"recent context preload failed: {e}")


def sync_beads_on_start():
    """Sync beads at session start (non-blocking background process)."""
    import subprocess
    import shutil

    # Check if bd command exists
    bd_path = shutil.which("bd")
    if not bd_path:
        return

    # Check if .beads directory exists
    beads_dir = Path.cwd() / ".beads"
    if not beads_dir.exists():
        beads_dir = Path.home() / ".claude" / ".beads"
        if not beads_dir.exists():
            return

    # Run bd sync in background (non-blocking)
    try:
        subprocess.Popen(
            [bd_path, "sync"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except (OSError, IOError):
        pass  # Non-critical


# =============================================================================
# STALE DETECTION
# =============================================================================


def is_session_stale(state) -> tuple[bool, str]:
    """Check if the existing session state is stale."""
    if not state.started_at:
        return True, "no_timestamp"

    age = time.time() - state.started_at

    if age > STALE_SESSION_THRESHOLD:
        return True, f"age_{int(age)}s"

    # Check if session_id changed (new Claude session)
    current_session_id = os.environ.get("CLAUDE_SESSION_ID", "")[:16]
    if (
        current_session_id
        and state.session_id
        and current_session_id != state.session_id
    ):
        return True, "session_id_changed"

    return False, "fresh"


def prune_old_errors(state):
    """Remove errors older than carry-over threshold."""
    cutoff = time.time() - ERROR_CARRY_OVER_MAX

    state.errors_recent = [
        e for e in state.errors_recent if e.get("timestamp", 0) > cutoff
    ]
    state.errors_unresolved = [
        e for e in state.errors_unresolved if e.get("timestamp", 0) > cutoff
    ]


def prune_old_gaps(state):
    """Clear gaps from previous sessions."""
    # Gaps don't have timestamps, so clear all on new session
    state.gaps_detected = []
    state.gaps_surfaced = []


# =============================================================================
# AUTONOMOUS AGENT: HANDOFF & ONBOARDING
# =============================================================================


def load_handoff_data(project_context=None) -> dict | None:
    """Load handoff data from previous session.

    This implements the Anthropic pattern of bridging context across sessions:
    https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents

    NOTE: Now project-scoped to load context for the specific project.
    """
    handoff_file = _get_project_handoff_file(project_context)
    if not handoff_file.exists():
        return None
    try:
        with open(handoff_file) as f:
            data = json.load(f)
        # Check if handoff is stale (>24h old)
        from datetime import datetime, timezone

        prepared = data.get("prepared_at", "")
        if prepared:
            try:
                # Parse ISO format, normalize to UTC for consistent comparison
                prepared_dt = datetime.fromisoformat(prepared.replace("Z", "+00:00"))
                if prepared_dt.tzinfo is not None:
                    # Convert to UTC then to naive for comparison
                    prepared_dt = prepared_dt.astimezone(timezone.utc).replace(
                        tzinfo=None
                    )
                    now = datetime.now(timezone.utc).replace(tzinfo=None)
                else:
                    now = datetime.now()
                age_hours = (now - prepared_dt).total_seconds() / 3600
                if age_hours > 24:
                    return None  # Stale handoff
            except (ValueError, TypeError):
                pass
        return data
    except (json.JSONDecodeError, KeyError):
        return None


def load_work_queue(project_context=None) -> list:
    """Load pending work items from progress file.

    NOTE: Now project-scoped.
    """
    progress_file = _get_project_progress_file(project_context)
    if not progress_file.exists():
        return []
    try:
        with open(progress_file) as f:
            data = json.load(f)
        return data.get("work_queue", [])
    except (json.JSONDecodeError, KeyError):
        return []


def load_infrastructure_summary() -> str:
    """Load infrastructure manifest summary for session context.

    This prevents Claude from recommending "create X" when X already exists.
    Injects key infrastructure awareness at session start.
    """
    if not INFRASTRUCTURE_FILE.exists():
        return ""

    try:
        content = INFRASTRUCTURE_FILE.read_text()
        # Extract just the "Setup Scripts" and "Key Directories" sections
        lines = content.split("\n")
        summary_lines = []
        in_section = False

        for line in lines:
            if line.startswith("## Setup Scripts") or line.startswith(
                "## Key Directories"
            ):
                in_section = True
                summary_lines.append(line)
            elif line.startswith("## ") and in_section:
                in_section = False
            elif in_section:
                summary_lines.append(line)

        return "\n".join(summary_lines).strip()
    except (IOError, OSError):
        return ""


def load_capabilities_summary() -> str:
    """Load capabilities index summary for session context.

    This prevents Claude from creating duplicate functionality by surfacing
    what already exists, grouped by PURPOSE not just filename.

    Critical for template projects where the same functionality gets
    proposed session after session.
    """
    if not CAPABILITIES_FILE.exists():
        return ""

    try:
        content = CAPABILITIES_FILE.read_text()
        # Extract category headers and counts
        lines = content.split("\n")
        categories = []

        for line in lines:
            if line.startswith("## ") and not line.startswith("## Before"):
                # Extract emoji + category name
                cat = line[3:].strip()
                categories.append(cat)

        if categories:
            # Compact format: just list the categories
            return "Categories: " + " | ".join(categories[:8])
        return ""
    except (IOError, OSError):
        return ""


def get_confidence_fp_history(state) -> list[str]:
    """Get false positive history for confidence reducers.

    Since LLMs can't learn, we must inject FP history as explicit context
    so the same false triggers don't frustrate users session after session.

    Returns list of reducer warnings based on FP counts.
    """
    if not hasattr(state, "nudge_history"):
        return []

    fp_warnings = []
    for key, data in state.nudge_history.items():
        if key.startswith("reducer_fp_") and isinstance(data, dict):
            reducer_name = key.replace("reducer_fp_", "")
            fp_count = data.get("count", 0)
            if fp_count >= 2:
                # Calculate adaptive cooldown
                base_cooldown = 5  # default
                multiplier = min(3.0, 1.0 + (fp_count * 0.5))
                cooldown = int(base_cooldown * multiplier)
                fp_warnings.append(
                    f"⚠️ {reducer_name}: {fp_count} FPs → cooldown {cooldown} turns"
                )

    return fp_warnings[:5]  # Limit to 5 most relevant


def get_recent_block_lessons(limit: int = 3) -> list[str]:
    """Get recent block-reflection lessons for session injection.

    These are lessons learned from hook blocks in previous sessions.
    Surfacing them prevents the same mistakes from recurring.
    """
    if not PROJECT_AWARE:
        return []

    try:
        from project_state import load_global_memory
        import time

        memory = load_global_memory()
        block_lessons = []

        # Filter to block-reflection lessons from last 7 days
        cutoff = time.time() - (7 * 24 * 3600)

        for lesson in memory.lessons:
            category = lesson.get("category", "")
            added_at = lesson.get("added_at", 0)

            if "block-reflection" in category and added_at > cutoff:
                content = lesson.get("content", "")
                # Extract hook name from category (e.g., "block-reflection:python_path_injector")
                hook = category.replace("block-reflection:", "").split(",")[0].strip()
                if hook and content:
                    block_lessons.append(f"{hook}: {content[:80]}")

        # Return most recent
        return block_lessons[-limit:]
    except (ImportError, Exception):
        return []


def _build_project_context(project_context) -> str | None:
    """Build project context string."""
    if not project_context or not PROJECT_AWARE:
        return None

    proj_name = project_context.project_name
    proj_type = project_context.project_type

    if proj_type == "ephemeral":
        return "💬 **MODE**: Ephemeral (no project context)"

    lang = project_context.language or "unknown"
    framework = project_context.framework
    ctx_str = f"📁 **PROJECT**: {proj_name}"
    if framework:
        ctx_str += f" ({framework}/{lang})"
    elif lang:
        ctx_str += f" ({lang})"
    return ctx_str


def _build_session_summary(handoff: dict | None) -> list[str]:
    """Build previous session summary parts."""
    if not handoff:
        return []

    parts = []
    summary = handoff.get("summary", "")
    if summary:
        parts.append(f"📋 **PREVIOUS SESSION**: {summary}")

    blockers = handoff.get("blockers", [])
    if blockers:
        blocker_list = ", ".join(b.get("type", "unknown")[:20] for b in blockers[:2])
        parts.append(f"🚧 **BLOCKERS**: {blocker_list}")

    recent = handoff.get("recent_files", [])
    if recent:
        names = [Path(f).name for f in recent[:3]]
        parts.append(f"📝 **RECENT FILES**: {', '.join(names)}")

    return parts


def _build_next_work_item(state, handoff: dict | None) -> str | None:
    """Build next work item context."""
    next_item = get_next_work_item(state)
    if next_item:
        item_type = next_item.get("type", "task")
        desc = next_item.get("description", "")[:60]
        priority = next_item.get("priority", 50)
        start_feature(state, desc)
        return f"🎯 **NEXT PRIORITY** [{item_type}|P{priority}]: {desc}"

    # Fallback to handoff next_steps
    if handoff:
        next_steps = handoff.get("next_steps", [])
        if next_steps:
            desc = next_steps[0].get("description", "")[:60]
            return f"🎯 **SUGGESTED**: {desc}"

    return None


def _build_recovery_point(handoff: dict | None) -> str | None:
    """Build recovery point context."""
    if not handoff:
        return None

    checkpoint = handoff.get("last_checkpoint")
    if not checkpoint:
        return None

    cp_id = checkpoint.get("checkpoint_id", "")
    commit = checkpoint.get("commit_hash", "")[:7]
    if commit:
        return f"💾 **RECOVERY POINT**: {cp_id} (commit: {commit})"
    return None


def _build_lessons_context(state, project_context) -> list[str]:
    """Build lessons and calibration context."""
    parts = []

    # Block lessons (cross-session learning)
    block_lessons = get_recent_block_lessons(limit=3)
    if block_lessons:
        parts.append("⚠️ **RECENT LESSONS**:")
        parts.extend(f"  • {lesson}" for lesson in block_lessons)

    # Confidence FP history
    fp_warnings = get_confidence_fp_history(state)
    if fp_warnings:
        parts.append("🎯 **CONFIDENCE CALIBRATION** (reducers with high FP rates):")
        parts.extend(f"  {warning}" for warning in fp_warnings)

    # Contextual lessons
    if PROJECT_AWARE and project_context and project_context.project_type != "ephemeral":
        keywords = [k for k in [
            project_context.language,
            project_context.framework,
            project_context.project_name,
        ] if k]
        if keywords:
            lessons = get_contextual_lessons(keywords)
            if lessons:
                lesson_preview = lessons[0].get("content", "")[:50]
                parts.append(f"💡 **WISDOM**: {lesson_preview}...")

    return parts


def build_onboarding_context(state, handoff: dict | None, project_context=None) -> str:
    """Build the session onboarding protocol context.

    Implements the Anthropic pattern:
    1. Read progress files and git logs to understand recent work
    2. Select the highest-priority incomplete feature
    3. Verify baseline before implementing

    For autonomous agents, this is AUTOMATIC - no human input needed.
    """
    parts = [
        "💻 **SYSTEM**: WSL2 global assistant @ /home/blake | Full access | ~/projects/ for work | ~/ai/ for AI projects"
    ]

    if ctx := _build_project_context(project_context):
        parts.append(ctx)

    parts.extend(_build_session_summary(handoff))

    if item := _build_next_work_item(state, handoff):
        parts.append(item)

    if recovery := _build_recovery_point(handoff):
        parts.append(recovery)

    parts.extend(_build_lessons_context(state, project_context))

    return "\n".join(parts) if parts else ""


# =============================================================================
# CONTEXT GENERATION (for resume)
# =============================================================================


def get_active_scope_task() -> dict | None:
    """Check if there's an active scope task from punch_list.json."""
    if not PUNCH_LIST_FILE.exists():
        return None
    try:
        with open(PUNCH_LIST_FILE) as f:
            data = json.load(f)
        # Only return if not 100% complete
        if data.get("percent", 100) < 100:
            return {
                "description": data.get("description", "")[:60],
                "percent": data.get("percent", 0),
                "items_done": sum(1 for i in data.get("items", []) if i.get("done")),
                "items_total": len(data.get("items", [])),
            }
    except (json.JSONDecodeError, KeyError):
        pass
    return None


def build_resume_context(state, result: dict) -> str:
    """Build actionable context string for session resume."""
    parts = []

    # 1. Active scope task (highest priority)
    scope_task = get_active_scope_task()
    if scope_task:
        desc = scope_task["description"]
        pct = scope_task["percent"]
        done = scope_task["items_done"]
        total = scope_task["items_total"]
        parts.append(f'📋 Active task: "{desc}" ({done}/{total} items, {pct}%)')

    # 2. Recently edited files (from previous session state)
    if state.files_edited:
        recent = []
        for f in state.files_edited[-3:]:
            try:
                recent.append(Path(f).name)
            except (ValueError, OSError):
                recent.append(str(f).split("/")[-1] if "/" in str(f) else str(f))
        parts.append(f"📝 Last edited: {', '.join(recent)}")

    # 3. Unresolved errors (warn, don't block)
    if state.errors_unresolved:
        count = len(state.errors_unresolved)
        latest = state.errors_unresolved[-1].get("type", "error")[:40]
        parts.append(f"⚠️ {count} unresolved: {latest}")

    return " | ".join(parts) if parts else ""


# =============================================================================
# INITIALIZATION
# =============================================================================


def initialize_session(project_context=None) -> dict:
    """Initialize or refresh session state.

    Args:
        project_context: Optional ProjectContext for project-scoped operations.
    """
    result = {
        "action": "none",
        "message": "",
        "session_id": "",
        "handoff": None,  # For onboarding context
    }

    # Try to load existing state
    existing_state = load_state()

    # Check staleness
    is_stale, reason = is_session_stale(existing_state)

    if is_stale:
        # Reset to fresh state
        state = reset_state()
        result["action"] = "reset"
        result["message"] = f"Fresh session (reason: {reason})"

        # === AUTONOMOUS AGENT: Restore work queue from progress file ===
        # Now project-scoped to load correct project's work queue
        work_queue = load_work_queue(project_context)
        if work_queue:
            state.work_queue = work_queue
    else:
        # Refresh existing state
        state = existing_state

        # Prune old data
        prune_old_errors(state)
        prune_old_gaps(state)

        # Clear stale integration greps (prevents cross-session blocking)
        state.pending_integration_greps = []

        # Refresh ops scripts (might have changed)
        state.ops_scripts = _discover_ops_scripts()

        result["action"] = "refresh"
        result["message"] = "Session resumed"

    # Ensure session_id is set
    if not state.session_id:
        state.session_id = (
            os.environ.get("CLAUDE_SESSION_ID", "")[:16] or f"ses_{int(time.time())}"
        )

    result["session_id"] = state.session_id

    # === AUTONOMOUS AGENT: Load handoff data ===
    # Now project-scoped to load correct project's handoff
    handoff = load_handoff_data(project_context)
    result["handoff"] = handoff

    # Save updated state
    save_state(state)

    # Pre-warm memory cache (synapse map, lessons index)
    prewarm_memory_cache()

    # Sync beads at session start (non-blocking)
    sync_beads_on_start()

    return result


# =============================================================================
# MAIN
# =============================================================================


def main():
    """SessionStart hook entry point."""
    try:
        json.load(sys.stdin)  # Consume stdin
    except (json.JSONDecodeError, ValueError):
        pass

    # === DEPENDENCY CHECK (v3.10) ===
    dep_warning = None
    if DEPENDENCY_CHECK_AVAILABLE:
        try:
            dep_result = run_dependency_check()
            if not dep_result["ok"] or dep_result["warnings"]:
                dep_warning = dep_result["summary"]
        except Exception:
            pass  # Non-critical, don't fail session start

    # === SYSTEM HEALTH CHECK (v3.9) ===
    health_warning = check_system_health()

    # === PROJECT-AWARE INITIALIZATION ===
    project_context = None
    if PROJECT_AWARE:
        try:
            project_context = get_current_project()
            # Run maintenance (cleanup stale projects, ephemeral state)
            run_maintenance()
        except (ImportError, FileNotFoundError, PermissionError):
            # Expected errors: module not available, git not found, permission issues
            pass  # Fall back to legacy behavior
        except Exception as e:
            # Unexpected errors: log for debugging but don't block
            print(
                f"Warning: project detection failed: {type(e).__name__}: {e}",
                file=sys.stderr,
            )

    # Load state BEFORE initialize (to capture previous session's context)
    previous_state = load_state()

    # Initialize session (pass project_context for project-scoped operations)
    result = initialize_session(project_context)

    # SUDO SECURITY: Audit passed - clear stop hook flags for this session
    session_id = os.environ.get("CLAUDE_SESSION_ID", "default")[:16]
    dismissal_flag = MEMORY_DIR / f"dismissal_shown_{session_id}.flag"
    if dismissal_flag.exists():
        try:
            dismissal_flag.unlink()
        except (IOError, OSError):
            pass

    # Output result
    output = {}

    # === AUTONOMOUS AGENT: Session Onboarding Protocol ===
    # This implements the Anthropic pattern for agent session starts:
    # https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents
    #
    # ENHANCED: Project-aware onboarding for multi-project swiss army knife

    if result["action"] == "reset":
        # Fresh session - load state for onboarding context
        state = load_state()
        handoff = result.get("handoff")

        # Build onboarding context (auto-selects next work item)
        # Pass project_context for multi-project awareness
        onboarding = build_onboarding_context(state, handoff, project_context)

        if onboarding:
            output["message"] = f"🚀 **SESSION START**\n{onboarding}"
            # Save state (may have started a feature)
            save_state(state)
        else:
            # Even without handoff, show project context if available
            if project_context and project_context.project_type != "ephemeral":
                output["message"] = (
                    f"🚀 **SESSION START**\n📁 **PROJECT**: {project_context.project_name}"
                )
            else:
                output["message"] = f"🔄 {result['message']}"

    elif result["action"] == "refresh":
        # Resuming within same session - surface context from previous state
        context = build_resume_context(previous_state, result)

        # Check for project switching (user changed directories mid-session)
        if PROJECT_AWARE and project_context:
            if not is_same_project(getattr(previous_state, "_project_context", None)):
                # Project changed! Save old state, load new
                try:
                    save_active_state()
                    new_ctx, new_state = get_active_project_state()
                    output["message"] = (
                        f"🔄 **PROJECT SWITCH**\n"
                        f"📁 Now in: {new_ctx.project_name}\n"
                        f"Previous context saved."
                    )
                except Exception as e:
                    log_debug("session_init", f"project switch failed: {e}")

        if context and "message" not in output:
            output["message"] = f"🔁 Resuming: {context}"

    # Note: Duplication prevention removed - this is a system assistant, not a template project

    # Append dependency warning if deps are missing (v3.10)
    if dep_warning:
        if output.get("message"):
            output["message"] += f"\n\n📦 **DEPENDENCIES**:\n{dep_warning}"
        else:
            output["message"] = f"📦 **DEPENDENCIES**:\n{dep_warning}"

    # Append health warning if resources are constrained (v3.9)
    if health_warning and output.get("message"):
        output["message"] += f"\n\n🖥️ **SYSTEM**: {health_warning}"
    elif health_warning:
        output["message"] = f"🖥️ **SYSTEM**: {health_warning}"

    print(json.dumps(output))
    sys.exit(0)


if __name__ == "__main__":
    main()
