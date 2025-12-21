#!/usr/bin/env python3
"""
Composite Stop Runner: Runs all Stop hooks in a single process.

PERFORMANCE: ~100ms for all hooks vs ~300ms for individual processes

HOOKS INDEX (by priority):
  CONTEXT MANAGEMENT (0-5):
    3 context_warning     - Warn at 75% context usage
    4 context_exhaustion  - Force resume prompt at 85%
    5 session_close_protocol - Enforce bd sync + next steps before exit

  PERSISTENCE (6-20):
    (auto_commit removed - commits are now explicit)

  VALIDATION (30-60):
    30 session_blocks     - Require reflection on blocks
    40 dismissal_check    - Catch false positive claims without fix
    50 stub_detector      - Files created with stubs

  WARNINGS (70-90):
    70 pending_greps      - Unverified function edits
    80 unresolved_errors  - Lingering errors

ARCHITECTURE:
  - Hooks register via @register_hook(name, priority)
  - Lower priority = runs first
  - First BLOCK wins for decision
  - stopReasons and contexts are aggregated
  - Special output schema for Stop hooks:
    {"decision": "block", "reason": "..."} - Forces Claude to continue
    {"stopReason": "..."} - Warning message
"""

import _lib_path  # noqa: F401
import sys
import json
import re
import time
import subprocess
import os
from pathlib import Path

from session_state import load_state, save_state, SessionState
from _patterns import STUB_BYTE_PATTERNS, CODE_EXTENSIONS
from _stop_registry import HOOKS, register_hook, StopHookResult

# Import language hooks module (triggers registration via decorators)
import _stop_language  # noqa: F401
from _stop_language import _read_tail_content


# =============================================================================
# CONFIGURATION
# =============================================================================

SCRIPT_DIR = Path(__file__).parent
CLAUDE_DIR = SCRIPT_DIR.parent
MEMORY_DIR = CLAUDE_DIR / "memory"

# Buffer sizes for transcript scanning
ACK_SCAN_BYTES = 20000
DISMISSAL_SCAN_BYTES = 20000

# Limits
MAX_CREATED_FILES_SCAN = 10

# Context exhaustion thresholds
# Token-based thresholds (absolute, not percentage)
CONTEXT_WARNING_TOKENS = 120000  # 120K tokens - soft warning
CONTEXT_EXHAUSTION_TOKENS = (
    150000  # 150K tokens - hard block (correlates with ~$50K remaining)
)
DEFAULT_CONTEXT_WINDOW = 200000  # Default if model info unavailable

# Dismissal patterns
DISMISSAL_PATTERNS = [
    (r"(this|that|it)('s| is) a false positive", "false_positive"),
    (r"the (warning|hook|gate) is (a )?false positive", "false_positive"),
    (r"hook (is )?(wrong|incorrect|mistaken)", "hook_dismissal"),
    (r"ignore (this|the) (warning|hook|gate)", "ignore_warning"),
    (r"(that|this) warning (is )?(incorrect|wrong)", "false_positive"),
]


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def run_git(args: list[str], cwd: str | None = None) -> tuple[int, str, str]:
    """Run git command, return (returncode, stdout, stderr)."""
    try:
        result = subprocess.run(
            ["git"] + args, cwd=cwd, capture_output=True, text=True, timeout=30
        )
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except subprocess.TimeoutExpired:
        return 1, "", "timeout"
    except Exception as e:
        return 1, "", str(e)


def is_git_repo(cwd: str) -> bool:
    """Check if cwd is inside a git repository."""
    code, _, _ = run_git(["rev-parse", "--git-dir"], cwd)
    return code == 0


def get_changes(cwd: str) -> dict:
    """Get summary of uncommitted changes."""
    changes = {"modified": [], "added": [], "deleted": [], "renamed": []}

    code, stdout, _ = run_git(["status", "--porcelain"], cwd)
    if code != 0 or not stdout:
        return changes

    for line in stdout.split("\n"):
        if len(line) < 3:
            continue
        status = line[:2]
        filepath = line[3:].split(" -> ")[-1]

        if status in ("??", "A ", " A", "AM"):
            changes["added"].append(filepath)
        elif status in (" D", "D ", "AD"):
            changes["deleted"].append(filepath)
        elif status in ("R ", " R", "RM"):
            changes["renamed"].append(filepath)
        else:
            changes["modified"].append(filepath)

    return changes


def _categorize_files(files: list[str]) -> dict[str, list[str]]:
    """Categorize files by directory type."""
    categories = {
        "hooks": [f for f in files if "hooks/" in f],
        "ops": [f for f in files if "ops/" in f],
        "commands": [f for f in files if "commands/" in f],
        "lib": [f for f in files if "lib/" in f],
        "config": [
            f
            for f in files
            if any(
                c in f for c in ["settings.json", "config/", ".json", ".yaml", ".yml"]
            )
        ],
        "memory": [f for f in files if "memory/" in f],
        "projects": [f for f in files if "projects/" in f],
    }
    categorized = set().union(*categories.values())
    categories["other"] = [f for f in files if f not in categorized]
    return categories


def _build_summary_parts(categories: dict[str, list[str]]) -> list[str]:
    """Build summary parts from file categories."""
    parts = []
    for name in ["hooks", "ops", "commands", "lib", "config", "memory"]:
        if categories[name]:
            parts.append(f"{name} ({len(categories[name])})")
    if categories["projects"]:
        parts.append("projects")
    if categories["other"]:
        other_dirs = {
            Path(f).parts[0] for f in categories["other"][:5] if len(Path(f).parts) > 1
        }
        parts.append(
            ", ".join(list(other_dirs)[:3])
            if other_dirs
            else f"{len(categories['other'])} files"
        )
    return parts


def _build_stats_line(changes: dict) -> str:
    """Build stats line from changes dict."""
    stats = []
    for key, label in [
        ("modified", "modified"),
        ("added", "added"),
        ("deleted", "deleted"),
        ("renamed", "renamed"),
    ]:
        if changes[key]:
            stats.append(f"{len(changes[key])} {label}")
    return ", ".join(stats) if stats else "no changes"


def generate_commit_message(changes: dict) -> str:
    """Generate semantic commit message from changes."""
    all_files = (
        changes["modified"] + changes["added"] + changes["deleted"] + changes["renamed"]
    )
    if not all_files:
        return ""
    categories = _categorize_files(all_files)
    summary = ", ".join(_build_summary_parts(categories))
    return f"[auto] {summary}\n\nFiles: {_build_stats_line(changes)}"


def check_acknowledgments_in_transcript(
    transcript_path: str,
) -> tuple[bool, bool, list[str]]:
    """Check for acknowledgments in transcript."""
    if not transcript_path or not Path(transcript_path).exists():
        return False, False, []

    try:
        with open(transcript_path, "r") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - ACK_SCAN_BYTES))
            content = f.read()

        substantive_matches = re.findall(
            r"[Bb]lock valid:\s*(.{10,200}?)(?:\n|$)", content
        )
        lessons = [m.strip() for m in substantive_matches if m.strip()]
        any_ack = re.search(r"[Bb]lock valid", content)

        return bool(lessons), bool(any_ack), lessons

    except (IOError, OSError):
        return False, False, []


def persist_lessons_to_memory(lessons: list[str], blocks: list[dict]) -> None:
    """Write block lessons to memory."""
    from datetime import datetime

    if not lessons:
        return

    hook_names = list(set(b.get("hook", "unknown") for b in blocks))
    hooks_str = ", ".join(hook_names[:3])

    lessons_file = MEMORY_DIR / "__lessons.md"
    if lessons_file.exists():
        try:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
            entries = []
            for lesson in lessons:
                lesson = lesson.strip().rstrip(".")
                entries.append(
                    f"\n### {timestamp}\n[block-reflection:{hooks_str}] {lesson}\n"
                )
            with open(lessons_file, "a") as f:
                f.writelines(entries)
        except (IOError, OSError):
            pass

    try:
        from project_state import add_global_lesson

        for lesson in lessons:
            lesson = lesson.strip().rstrip(".")
            add_global_lesson(lesson, category=f"block-reflection:{hooks_str}")
    except ImportError:
        pass


def check_dismissals_in_transcript(transcript_path: str) -> list[str]:
    """Check if Claude claimed any false positives without fixing them."""
    if not transcript_path or not Path(transcript_path).exists():
        return []

    warnings = []
    try:
        with open(transcript_path, "r") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - DISMISSAL_SCAN_BYTES))
            content = f.read()

        content_lower = content.lower()
        fix_evidence = re.search(r"\.claude/(hooks|lib)/\w+\.py", content)

        if fix_evidence:
            return []

        for pattern, dismissal_type in DISMISSAL_PATTERNS:
            if re.search(pattern, content_lower, re.IGNORECASE):
                warnings.append(
                    f"  • `{dismissal_type}`: Claude claimed hook feedback was wrong"
                )

    except (IOError, OSError):
        pass

    return warnings


# =============================================================================
# CONTEXT USAGE CALCULATION (ported from statusline.py)
# =============================================================================


def get_context_usage(transcript_path: str, context_window: int) -> tuple[int, int]:
    """Calculate context window usage from transcript.

    Parses the transcript JSONL to find the most recent assistant message
    with usage data, then sums all token types.

    Returns: (used_tokens, context_window)
    """
    if not transcript_path or not Path(transcript_path).exists():
        return 0, context_window

    try:
        with open(transcript_path, "r") as f:
            lines = f.readlines()

        # Search backwards for most recent assistant message with usage
        for line in reversed(lines):
            try:
                data = json.loads(line.strip())
                if data.get("message", {}).get("role") != "assistant":
                    continue
                # Skip synthetic messages
                model = str(data.get("message", {}).get("model", "")).lower()
                if "synthetic" in model:
                    continue
                usage = data.get("message", {}).get("usage")
                if usage:
                    used = (
                        usage.get("input_tokens", 0)
                        + usage.get("output_tokens", 0)
                        + usage.get("cache_read_input_tokens", 0)
                        + usage.get("cache_creation_input_tokens", 0)
                    )
                    return used, context_window
            except (json.JSONDecodeError, KeyError):
                continue
        return 0, context_window
    except (OSError, PermissionError):
        return 0, context_window


def _format_exhaustion_block(
    pct: float, used: int, total: int, next_steps: str | None = None
) -> str:
    """Format the context exhaustion block message.

    This is a BLOCK to prevent session end - not a resume template.
    State is auto-persisted; `/resume` in the next session will recover it.
    """
    next_steps_section = ""
    if next_steps:
        next_steps_section = f"""
### Documented Next Steps
{next_steps[:300]}
"""

    return f"""## 🛑 CONTEXT EXHAUSTION ({pct:.0%}) - Wrap Up Required

**Context usage: {used:,} / {total:,} tokens**

Session is approaching context limit. Complete these steps before stopping:

### 1. Sync Beads
```bash
bd sync
```

### 2. Commit (if needed)
If you have uncommitted changes, commit them now (commits are explicit, not automatic).

### 3. Verify State Saved
Session state is auto-persisted to `~/.claude/memory/session_state_v3.json`.
Check it includes your `original_goal` and `progress_log`.
{next_steps_section}
---

**Recovery:** In your NEXT session, run `/resume` to restore full context.

The `/resume` command will:
- Load session state (goals, progress, files modified)
- Check beads status
- Check git status
- Activate Serena if available

**You can now wrap up and stop.** Context will be recoverable."""


# =============================================================================
# HOOK IMPLEMENTATIONS
# =============================================================================


@register_hook("context_guard_activate", priority=1)
def activate_context_guard(data: dict, state: SessionState) -> StopHookResult:
    """Activate context guard after first Stop hook run.

    This hook runs early (priority 1) to:
    1. Increment stop_hook_runs counter
    2. Update last_context_tokens with current usage
    3. Activate context_guard_active after first run

    The guard enables proactive context checking in UserPromptSubmit hooks.
    """
    import os

    # Increment run counter
    state.stop_hook_runs = getattr(state, "stop_hook_runs", 0) + 1

    # Get current context usage
    transcript_path = data.get("transcript_path", "")
    context_window = data.get("model", {}).get("context_window", DEFAULT_CONTEXT_WINDOW)
    used, _ = get_context_usage(transcript_path, context_window)

    # Update last known tokens
    state.last_context_tokens = used

    # Activate guard after first stop if we have meaningful context
    # Only activate if session has accumulated 20k+ tokens
    if not getattr(state, "context_guard_active", False):
        if used >= 20000:  # ACTIVATION_BUFFER_TOKENS
            state.context_guard_active = True
            state.context_guard_project_id = os.getcwd()

    return StopHookResult.ok()


@register_hook("context_warning", priority=3)
def check_context_warning(data: dict, state: SessionState) -> StopHookResult:
    """Warn when context reaches 120K tokens - non-blocking heads up."""
    # Skip if already warned this session
    if state.nudge_history.get("context_warning_shown"):
        return StopHookResult.ok()

    transcript_path = data.get("transcript_path", "")
    context_window = data.get("model", {}).get("context_window", DEFAULT_CONTEXT_WINDOW)

    used, total = get_context_usage(transcript_path, context_window)
    if total == 0:
        return StopHookResult.ok()

    # Token-based thresholds (absolute, not percentage)
    if used < CONTEXT_WARNING_TOKENS:
        return StopHookResult.ok()

    # Don't warn if we're already at exhaustion threshold (let that hook handle it)
    if used >= CONTEXT_EXHAUSTION_TOKENS:
        return StopHookResult.ok()

    # Mark as warned
    state.nudge_history["context_warning_shown"] = True

    pct = used / total
    return StopHookResult.warn(
        f"⚠️ **CONTEXT WARNING** - {used:,} tokens used ({pct:.0%} of {total:,})\n\n"
        "Consider:\n"
        "- Wrapping up current task\n"
        "- Running `bd sync` to save bead state\n"
        "- Committing work in progress\n\n"
        f"**At {CONTEXT_EXHAUSTION_TOKENS:,} tokens, you'll be prompted to wrap up.** "
        "Session state auto-persists; `/resume` in next session recovers context."
    )


@register_hook("context_exhaustion", priority=4)
def check_context_exhaustion(data: dict, state: SessionState) -> StopHookResult:
    """Block session end at 150K tokens - prompt wrap-up actions.

    State is auto-persisted; `/resume` in the NEXT session recovers it.
    This hook just ensures Claude wraps up cleanly before context dies.
    """
    # Skip if already shown this session
    if state.nudge_history.get("context_exhaustion_shown"):
        return StopHookResult.ok()

    transcript_path = data.get("transcript_path", "")
    context_window = data.get("model", {}).get("context_window", DEFAULT_CONTEXT_WINDOW)

    used, total = get_context_usage(transcript_path, context_window)
    if total == 0:
        return StopHookResult.ok()

    # Token-based threshold (absolute, not percentage)
    if used < CONTEXT_EXHAUSTION_TOKENS:
        return StopHookResult.ok()

    # Mark as shown (only block once per session)
    state.nudge_history["context_exhaustion_shown"] = True

    # Extract next steps to include in wrap-up message
    next_steps = _extract_next_steps(transcript_path)

    pct = used / total
    return StopHookResult.block(_format_exhaustion_block(pct, used, total, next_steps))


def _has_sudo_bypass(transcript_path: str) -> bool:
    """Check if SUDO bypass was used in recent transcript."""
    if not transcript_path or not Path(transcript_path).exists():
        return False
    try:
        with open(transcript_path, "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 5000))
            content = f.read().decode("utf-8", errors="ignore").upper()
        return "SUDO" in content
    except (OSError, PermissionError):
        return False


def _extract_next_steps(transcript_path: str) -> str | None:
    """Extract next steps section from transcript if present.

    Looks for markdown headings like "## Next Steps", "### ➡️ Next Steps",
    or similar variants and extracts the content that follows.
    """
    content = _read_tail_content(transcript_path, 20000)
    if not content:
        return None

    # Find next steps heading - allow emojis, bold markers, and other chars
    # Matches: "## Next Steps", "### ➡️ Next Steps", "## **Next Steps:**", etc.
    match = re.search(
        r"#{1,3}\s*[^\n]*?\*{0,2}next\s+steps:?\*{0,2}[:\s]*\n(.*?)(?=\n#{1,3}\s|\Z)",
        content,
        re.IGNORECASE | re.DOTALL,
    )
    if match:
        return match.group(1).strip()[:500]  # Limit to 500 chars
    return None


@register_hook("session_close_protocol", priority=5)
def check_session_close_protocol(data: dict, state: SessionState) -> StopHookResult:
    """Enforce session close protocol: bd sync + next steps before exit.

    Protocol:
    1. bd sync must have been run (persists task state)
    2. Next steps must be documented (in handoff or response)

    Git commits are explicit - handled by AI/user directive, not auto-hooks.
    """
    # SUDO bypass
    transcript_path = data.get("transcript_path", "")
    if _has_sudo_bypass(transcript_path):
        return StopHookResult.ok()

    # Skip Q&A sessions - no files edited, no files created, no beads touched
    # These are informational exchanges that don't need close protocol
    has_file_work = bool(state.files_edited or state.files_created)
    has_bead_work = any("bd " in cmd for cmd in list(state.commands_succeeded)[-50:])

    if not has_file_work and not has_bead_work:
        return StopHookResult.ok()

    # Also skip very short sessions with no meaningful work
    if state.turn_count < 3 and not state.files_edited:
        return StopHookResult.ok()

    violations = []

    # 1. Check bd sync ran (look for recent 'bd sync' in commands)
    recent_cmds = list(state.commands_succeeded)[-30:]
    has_bd_sync = any("bd sync" in cmd.lower() for cmd in recent_cmds)
    if not has_bd_sync:
        # Fallback: check transcript for bd sync
        content = _read_tail_content(transcript_path, 20000)
        if not content or "bd sync" not in content.lower():
            violations.append("bd sync not run")

    # 2. Check next steps documented
    has_next_steps = bool(getattr(state, "handoff_next_steps", None))
    has_goal = bool(getattr(state, "original_goal", None))

    # Try to populate handoff_next_steps from transcript if not set
    if not has_next_steps:
        extracted = _extract_next_steps(transcript_path)
        if extracted:
            state.handoff_next_steps = extracted
            has_next_steps = True

    if not has_next_steps and has_goal:
        violations.append("next steps not documented")

    if violations:
        return StopHookResult.block(
            f"🚨 **SESSION CLOSE PROTOCOL** - Missing: {', '.join(violations)}\n\n"
            "**Required before session end:**\n"
            "1. Run `bd sync` to persist task state\n"
            "2. Document next steps in your response\n\n"
            "**Bypass:** Say 'SUDO' to skip protocol"
        )

    return StopHookResult.ok()


# NOTE: auto_commit hook REMOVED
# Git commits are now explicit - triggered by AI or user directive only.
# This prevents unwanted automatic commits and gives full control to the user.


@register_hook("session_blocks", priority=30)
def check_session_blocks(data: dict, state: SessionState) -> StopHookResult:
    """Require reflection on session blocks."""
    from synapse_core import get_session_blocks, clear_session_blocks

    transcript_path = data.get("transcript_path", "")
    blocks = get_session_blocks()

    if not blocks:
        return StopHookResult.ok()

    # Check for acknowledgments
    substantive_ack, any_ack, lessons = check_acknowledgments_in_transcript(
        transcript_path
    )

    if substantive_ack:
        persist_lessons_to_memory(lessons, blocks)
        clear_session_blocks()
        return StopHookResult.ok()

    # Group by hook and function
    hook_details = {}
    for b in blocks:
        hook = b.get("hook", "unknown")
        func = b.get("function", "")
        key = f"{hook}" + (f" ({func})" if func else "")
        hook_details[key] = hook_details.get(key, 0) + 1

    if any_ack and not substantive_ack:
        # Mechanical ack - soft warning
        lines = ["⚠️ **BLOCKS ACKNOWLEDGED** - but no lesson captured:"]
        for detail, count in sorted(hook_details.items(), key=lambda x: -x[1])[:3]:
            lines.append(f"  • `{detail}`: {count}x")
        lines.append("\n**TIP:** 'Block valid: [lesson]' captures why it happened.")
        clear_session_blocks()
        return StopHookResult.warn("\n".join(lines))

    # No acknowledgment - require reflection
    lines = ["🚨 **SESSION BLOCKS DETECTED** - Reflection required:"]
    for detail, count in sorted(hook_details.items(), key=lambda x: -x[1])[:5]:
        lines.append(f"  • `{detail}`: {count}x")

    last_block = blocks[-1]
    reason_preview = last_block.get("reason", "")[:100]
    if reason_preview:
        lines.append(f"\n  Last block: {reason_preview}...")

    lines.append("\n**REFLECT:** Why did these blocks fire? How to avoid next time?")
    clear_session_blocks()

    return StopHookResult.block("\n".join(lines))


# =============================================================================
# RALPH-WIGGUM COMPLETION EVIDENCE GATE (v4.23)
# =============================================================================

BLOCKER_PATTERNS = [
    r"\bi(?:'m| am) (?:stuck|blocked)\b",
    r"\bcan(?:'t|not) (?:figure|proceed|continue)\b",
    r"\bneed (?:help|guidance|input)\b",
    r"\bescalat(?:e|ing)\b",
    r"\buncertain\b",
    r"\bi don(?:'t|'t) know\b",
]

DEFERRAL_PATTERNS = [
    r"\bgood enough\b",
    r"\bthat(?:'s|s) fine\b",
    r"\bship it\b",
    r"\bwe can stop\b",
    r"\blet(?:'s|s) stop\b",
    r"\b(?:done|complete) for now\b",
]


def _has_blocker_or_deferral(transcript_path: str) -> tuple[bool, str]:
    """Check if response contains blocker statement or user deferral."""
    import re

    try:
        content = _read_tail_content(transcript_path, 4000)
    except Exception:
        return False, ""

    # Check for blocker patterns
    for pattern in BLOCKER_PATTERNS:
        if re.search(pattern, content, re.IGNORECASE):
            return True, "blocker"

    # Check for deferral patterns
    for pattern in DEFERRAL_PATTERNS:
        if re.search(pattern, content, re.IGNORECASE):
            return True, "deferral"

    return False, ""


def _get_missing_evidence(state: SessionState) -> list[str]:
    """Determine what evidence is still needed for completion."""
    missing = []
    contract = state.task_contract

    if not contract:
        return ["No task contract defined"]

    evidence_types = {e.get("type") for e in state.completion_evidence}
    required = contract.get("evidence_required", ["test_pass"])

    for req in required:
        if req not in evidence_types:
            if req == "test_pass":
                missing.append("Run tests (pytest, npm test, etc.)")
            elif req == "build_success":
                missing.append("Run build (npm build, cargo build, etc.)")
            elif req == "lint_pass":
                missing.append("Run linter (ruff check, eslint, etc.)")
            else:
                missing.append(f"Evidence: {req}")

    return missing


# Research/audit task patterns - these don't need build evidence
RESEARCH_TASK_PATTERNS = [
    r"\b(audit|analyze|review|investigate|research|explore|understand)\b",
    r"\b(what|how|why|where|explain|describe|list|show)\b.*\?",
    r"\b(check|verify|inspect|examine|assess|evaluate)\b",
    r"\bfind\s+(all|the|any)\b",
]


def _is_research_task(goal: str) -> bool:
    """Detect if task is research/analysis (no build artifact expected)."""
    if not goal:
        return False
    goal_lower = goal.lower()
    for pattern in RESEARCH_TASK_PATTERNS:
        if re.search(pattern, goal_lower):
            return True
    return False


@register_hook("ralph_evidence", priority=35)
def check_ralph_evidence(data: dict, state: SessionState) -> StopHookResult:
    """
    Ralph-Wiggum completion evidence gate.

    Blocks session exit unless completion_confidence >= threshold
    OR explicit blocker/deferral statement detected.

    Philosophy: Tasks should complete fully, not be abandoned mid-work.

    FIX (2025-12-20): Skip build evidence requirement for research/audit tasks.
    """
    # Skip if ralph mode not active
    if not state.ralph_mode:
        return StopHookResult.ok()

    # Skip build evidence for research/audit tasks (FP fix)
    contract = state.task_contract
    goal = contract.get("goal", "") if contract else ""
    if _is_research_task(goal) or _is_research_task(state.original_goal):
        # Research tasks don't produce build artifacts - allow exit
        return StopHookResult.ok()

    # Check completion confidence threshold
    threshold = 80  # Default threshold
    if state.completion_confidence >= threshold:
        return StopHookResult.ok()

    # Check for explicit blocker or deferral
    transcript_path = data.get("transcript_path", "")
    has_escape, escape_type = _has_blocker_or_deferral(transcript_path)

    if has_escape:
        if escape_type == "deferral":
            # User said "good enough" - allow exit with note
            return StopHookResult.warn(
                f"Task deferred at {state.completion_confidence}% completion. "
                "Remaining work not verified."
            )
        else:
            # Blocker acknowledged - allow exit
            return StopHookResult.ok()

    # Strictness modes
    if state.ralph_strictness == "loose":
        # Advisory only - show what's incomplete but allow exit
        missing = _get_missing_evidence(state)
        return StopHookResult.warn(
            f"Task {state.completion_confidence}% complete. "
            f"Incomplete: {', '.join(missing[:2])}"
        )

    if state.ralph_strictness == "normal":
        # Nag budget - allow after N reminders
        if state.ralph_nag_budget <= 0:
            return StopHookResult.warn(
                f"Allowing exit after {2 - state.ralph_nag_budget} reminders. "
                f"Completion: {state.completion_confidence}%"
            )
        # Decrement budget (will be saved by hook runner)
        # Note: state mutation here - budget tracked in session state

    # STRICT MODE: Block until evidence threshold met
    missing = _get_missing_evidence(state)
    contract = state.task_contract
    goal = contract.get("goal", "Unknown goal")[:60]

    block_msg = f"""
🔄 **Task Incomplete** (completion: {state.completion_confidence}%)

**Goal:** {goal}

**Missing Evidence:**
{chr(10).join(f"  • {m}" for m in missing[:3])}

**To Complete:**
  • Run tests/build to accumulate evidence
  • Or state blocker: "I'm stuck on X"
  • Or confirm done: "This is good enough"
"""
    return StopHookResult.block(block_msg.strip())


# =============================================================================
# PERPETUAL MOMENTUM GATE (v4.24)
# =============================================================================
# Core philosophy: "What can we do to make this even better?"
# Things are never "done" - always enhancement, testing, meta-cognition available.
# Responses must contain actionable forward motion, not deadend satisfaction.
# =============================================================================

MOMENTUM_PATTERNS = [
    r"\bi\s+(?:can|will|could)\s+(?:also\s+)?(?:now\s+)?(?:\w+)",
    r"\blet\s+me\s+(?:now\s+)?(?:\w+)",
    r"\bnext\s+(?:i'?ll|step|steps?)[\s:]+",
    r"\b(?:shall|should)\s+i\s+(?:\w+)",
    r"\bwant\s+me\s+to\b",
    r"(?:^|\n)#+\s*(?:next\s+steps?|➡️|🛤️)",
    r"(?:^|\n)\*\*(?:next\s+steps?|➡️)\*\*",
]

DEADEND_PATTERNS = [
    r"\bthat'?s\s+(?:all|it)\s+(?:for now|i have)\b",
    r"\bwe'?re\s+(?:all\s+)?(?:done|finished|complete)\b",
    r"\blet\s+me\s+know\s+if\s+(?:you\s+)?(?:need|want|have)\b",
    r"\bhope\s+(?:this|that)\s+helps?\b",
    r"\banything\s+else\s+(?:you\s+)?(?:need|want)\b",
]


def _check_momentum(transcript_path: str) -> tuple[bool, bool]:
    """Check if response has momentum patterns vs deadend patterns.

    Returns: (has_momentum, has_deadend)
    """
    content = _read_tail_content(transcript_path, 5000)
    if not content:
        return False, False

    content_lower = content.lower()

    has_momentum = any(
        re.search(p, content_lower, re.IGNORECASE | re.MULTILINE)
        for p in MOMENTUM_PATTERNS
    )

    has_deadend = any(
        re.search(p, content_lower, re.IGNORECASE) for p in DEADEND_PATTERNS
    )

    return has_momentum, has_deadend


@register_hook("momentum_gate", priority=36)
def check_momentum_gate(data: dict, state: SessionState) -> StopHookResult:
    """Enforce perpetual momentum - responses must drive continuation.

    Philosophy: Things are never "done" - always enhancement, testing,
    meta-cognition available. Deadend responses are penalized.

    Bypassed by:
    - SUDO in transcript
    - Blocker acknowledgment ("I'm stuck")
    - User deferral ("good enough")
    """
    # Skip if SUDO bypass
    transcript_path = data.get("transcript_path", "")
    if _has_sudo_bypass(transcript_path):
        return StopHookResult.ok()

    # Skip if blocker or deferral acknowledged
    has_escape, _ = _has_blocker_or_deferral(transcript_path)
    if has_escape:
        return StopHookResult.ok()

    # Check momentum patterns
    has_momentum, has_deadend = _check_momentum(transcript_path)

    if has_momentum:
        return StopHookResult.ok()

    if has_deadend:
        return StopHookResult.warn(
            "🔄 **PERPETUAL MOMENTUM** - Response lacks forward motion.\n\n"
            "Before stopping, add actionable next steps:\n"
            '  • "I can now..." / "Let me..." / "Shall I..."\n'
            "  • Next Steps section with Claude-actionable items\n\n"
            'Philosophy: Things are never "done" - always enhancement available.'
        )

    # No strong signal either way - soft reminder
    return StopHookResult.ok()


@register_hook("dismissal_check", priority=40)
def check_dismissal(data: dict, state: SessionState) -> StopHookResult:
    """Catch false positive claims without fix."""
    transcript_path = data.get("transcript_path", "")
    dismissals = check_dismissals_in_transcript(transcript_path)

    if not dismissals:
        return StopHookResult.ok()

    lines = ["🔧 **FALSE POSITIVE CLAIMED** - Fix required:"]
    lines.extend(dismissals)
    lines.append(
        "\n**REQUIRED:** Fix the hook that fired incorrectly. This block repeats until fixed."
    )

    return StopHookResult.block("\n".join(lines))


@register_hook("stub_detector", priority=50)
def check_stubs(data: dict, state: SessionState) -> StopHookResult:
    """Check created files for stubs."""
    warnings = []

    for filepath in state.files_created[-MAX_CREATED_FILES_SCAN:]:
        path = Path(filepath)
        if not path.exists() or path.suffix not in CODE_EXTENSIONS:
            continue

        try:
            content = path.read_bytes()
            stubs = [p.decode() for p in STUB_BYTE_PATTERNS if p in content]
            if stubs:
                warnings.append(f"  • `{path.name}`: {', '.join(stubs[:2])}")
        except (OSError, PermissionError):
            pass

    if not warnings:
        return StopHookResult.ok()

    lines = ["⚠️ **ABANDONED WORK** - Files with stubs:"]
    lines.extend(warnings)
    return StopHookResult.warn("\n".join(lines))


@register_hook("pending_greps", priority=70)
def check_pending_greps(data: dict, state: SessionState) -> StopHookResult:
    """Check for unverified function edits."""
    pending = state.pending_integration_greps
    if not pending:
        return StopHookResult.ok()

    funcs = [p.get("function", "unknown") for p in pending[:3]]
    return StopHookResult.warn(
        f"⚠️ **UNVERIFIED EDITS** - Functions need grep: {', '.join(funcs)}"
    )


@register_hook("serena_memory_sync", priority=75)
def sync_serena_memory(data: dict, state: SessionState) -> StopHookResult:
    """Fire-and-forget Serena memory update on session end.

    Runs async - doesn't block stop, user doesn't see output.
    Writes session summary to Serena project memory.
    """
    cwd = data.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()

    # Check if project has Serena
    serena_dir = Path(cwd) / ".serena"
    if not serena_dir.exists():
        # Walk up to find project root with .serena
        check_dir = Path(cwd)
        serena_dir = None
        for _ in range(5):  # Max 5 levels up
            if (check_dir / ".serena").exists():
                serena_dir = check_dir / ".serena"
                cwd = str(check_dir)
                break
            if check_dir.parent == check_dir:
                break
            check_dir = check_dir.parent

        if not serena_dir:
            return StopHookResult.ok()

    # Build session summary for memory
    files_edited = list(set(state.files_edited[-20:]))
    files_created = list(set(state.files_created[-10:]))

    # Skip if nothing significant happened
    if not files_edited and not files_created:
        return StopHookResult.ok()

    # Build memory content
    from datetime import datetime

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")

    memory_lines = [
        f"# Session Summary - {timestamp}",
        "",
        f"## Files Modified ({len(files_edited)})",
    ]
    for f in files_edited[:10]:
        memory_lines.append(f"- {f}")

    if files_created:
        memory_lines.append(f"\n## Files Created ({len(files_created)})")
        for f in files_created[:5]:
            memory_lines.append(f"- {f}")

    if state.errors_unresolved:
        memory_lines.append(f"\n## Unresolved Issues ({len(state.errors_unresolved)})")
        for err in state.errors_unresolved[:3]:
            memory_lines.append(
                f"- {err.get('type', 'unknown')}: {err.get('message', '')[:100]}"
            )

    memory_content = "\n".join(memory_lines)

    # Write directly to Serena memories
    memory_file = (
        serena_dir
        / "memories"
        / f"session_{timestamp.replace(':', '-').replace(' ', '_')}.md"
    )

    # Direct write - fast enough to not block, avoids subprocess injection risks
    try:
        memory_file.parent.mkdir(parents=True, exist_ok=True)
        memory_file.write_text(memory_content)
    except (OSError, PermissionError):
        pass  # Fire and forget - ignore errors

    return StopHookResult.ok()


@register_hook("auto_close_beads", priority=77)
def auto_close_beads(data: dict, state: SessionState) -> StopHookResult:
    """Auto-close in_progress beads when session work appears complete.

    FULL AUTO-MANAGEMENT:
    - Detects session completion via file edits + command success
    - Auto-closes beads that were claimed this session
    - No manual bd commands needed

    SAFEGUARDS:
    - Only closes auto-created beads (tracked in state)
    - Only if session had successful work (files edited, no unresolved errors)
    - Graceful degradation on bd failure
    """
    from pathlib import Path

    # Skip if no file work done
    if not state.files_edited and not state.files_created:
        return StopHookResult.ok()

    # Skip if there are unresolved errors (work isn't complete)
    if state.errors_unresolved:
        return StopHookResult.ok()

    # Get auto-created beads from this session
    auto_beads = getattr(state, "auto_created_beads", [])
    if not auto_beads:
        return StopHookResult.ok()

    bd_path = Path.home() / ".local" / "bin" / "bd"
    if not bd_path.exists():
        return StopHookResult.ok()

    closed = []
    for bead_id in auto_beads:
        try:
            result = subprocess.run(
                [str(bd_path), "close", bead_id],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                closed.append(bead_id[:12])
        except (subprocess.TimeoutExpired, Exception):
            pass

    # Clear the auto-created beads list
    state.auto_created_beads = []

    if closed:
        return StopHookResult.ok(f"📋 **Auto-closed beads**: {', '.join(closed)}")

    return StopHookResult.ok()


@register_hook("unresolved_errors", priority=80)
def check_unresolved_errors(data: dict, state: SessionState) -> StopHookResult:
    """Check for lingering errors."""
    if not state.errors_unresolved:
        return StopHookResult.ok()

    error = state.errors_unresolved[-1]
    return StopHookResult.warn(
        f"⚠️ **UNRESOLVED ERROR**: {error.get('type', 'unknown')[:50]}"
    )


_TODO_PATTERNS = [b"TODO", b"FIXME", b"HACK", b"XXX"]


def _scan_file_for_debt(
    filepath: str, check_todos: bool = False
) -> tuple[list[str], int]:
    """Scan a file for stubs and optionally TODOs. Returns (items, score)."""
    path = Path(filepath)
    if not path.exists() or path.suffix not in CODE_EXTENSIONS:
        return [], 0
    try:
        content = path.read_bytes()
    except (OSError, PermissionError):
        return [], 0

    items, score = [], 0
    if any(p in content for p in STUB_BYTE_PATTERNS):
        items.append(f"stub in {path.name}")
        score += 5
    if check_todos:
        for pattern in _TODO_PATTERNS:
            if pattern in content:
                items.append(f"{pattern.decode()} in {path.name}")
                score += 2
                break
    return items, score


@register_hook("session_debt_penalty", priority=85)
def check_session_debt(data: dict, state: SessionState) -> StopHookResult:
    """Penalize ending session with technical/organizational debt."""
    from confidence import get_tier_info, set_confidence

    debt_items, debt_score = [], 0

    # Scan created files for stubs
    for fp in state.files_created[-20:]:
        items, score = _scan_file_for_debt(fp, check_todos=False)
        debt_items.extend(items)
        debt_score += score

    # Scan edited files for stubs and TODOs
    for fp in state.files_edited[-20:]:
        items, score = _scan_file_for_debt(fp, check_todos=True)
        debt_items.extend(items)
        debt_score += score

    # Unresolved errors and pending greps
    if state.errors_unresolved:
        debt_items.append(f"{len(state.errors_unresolved)} unresolved error(s)")
        debt_score += 10 * len(state.errors_unresolved)
    if state.pending_integration_greps:
        debt_items.append(f"{len(state.pending_integration_greps)} unverified edit(s)")
        debt_score += 5 * len(state.pending_integration_greps)

    if not debt_items or debt_score < 5:
        return StopHookResult.ok()

    penalty = min(debt_score, 20)
    new_confidence = max(0, state.confidence - penalty)
    set_confidence(state, new_confidence, "session debt penalty")
    _, emoji, _ = get_tier_info(new_confidence)
    debt_list = ", ".join(debt_items[:3])

    if debt_score >= 15 or new_confidence < 70:
        return StopHookResult.block(f"🚫 SESSION DEBT: {debt_list} | Fix or SUDO")
    return StopHookResult.warn(
        f"⚠️ SESSION DEBT: {emoji} {new_confidence}% | {debt_list}"
    )


@register_hook("session_auto_commit", priority=88)
def auto_commit_session_end(data: dict, state: SessionState) -> StopHookResult:
    """Auto-commit ALL repos at session end.

    This is a HARD requirement - nothing should be left uncommitted.
    Commits both framework (.claude/) and project repos.
    """
    # Try to import smart commit module
    try:
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "_smart_commit",
            CLAUDE_DIR / "lib" / "_smart_commit.py",
        )
        if not spec or not spec.loader:
            return StopHookResult.ok()
        sc = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(sc)
    except Exception:
        return StopHookResult.ok()

    # Commit all repos
    results = sc.commit_all_repos("session_end", state.turn_count)

    # No repos committed
    if not results:
        return StopHookResult.ok()

    # Format results
    successes = [
        r for r in results if r.success and "no changes" not in r.message.lower()
    ]
    failures = [r for r in results if not r.success]

    if not successes and not failures:
        return StopHookResult.ok()

    # Build feedback message
    lines = []
    if successes:
        lines.append("**Session commits:**")
        for r in successes:
            from pathlib import Path

            repo_name = Path(r.repo_root).name
            lines.append(f"  `{repo_name}`: {r.message}")

    if failures:
        lines.append("**Commit failed:**")
        for r in failures:
            from pathlib import Path

            repo_name = Path(r.repo_root).name
            lines.append(f"  `{repo_name}`: {r.message}")

    return StopHookResult.ok("\n".join(lines))


# =============================================================================
# MAIN RUNNER
# =============================================================================


def run_hooks(data: dict, state: SessionState) -> dict:
    """Run all hooks and return aggregated result."""
    # Hooks pre-sorted at module load

    stop_reasons = []
    block_reason = None

    for name, check_func, priority in HOOKS:
        try:
            result = check_func(data, state)

            # First block wins
            if result.decision == "block" and not block_reason:
                block_reason = result.reason

            # Collect stop reasons
            if result.stop_reason:
                stop_reasons.append(result.stop_reason)

        except Exception as e:
            print(f"[stop-runner] Hook {name} error: {e}", file=sys.stderr)

    # Build output
    if block_reason:
        return {"decision": "block", "reason": block_reason}
    elif stop_reasons:
        return {"stopReason": "\n\n".join(stop_reasons)}
    else:
        return {"status": "pass", "message": "No cleanup issues detected"}


# Pre-sort hooks by priority at module load (avoid re-sorting on every call)
HOOKS.sort(key=lambda x: x[2])


def main():
    """Main entry point."""
    start = time.time()

    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        data = {}

    # Single state load
    try:
        state = load_state()
    except Exception:
        from session_state import SessionState

        state = SessionState()

    # Run all hooks
    result = run_hooks(data, state)

    # Single state save
    save_state(state)

    # Output result
    print(json.dumps(result))

    # Debug timing
    elapsed = (time.time() - start) * 1000
    if elapsed > 200:
        print(f"[stop-runner] Slow: {elapsed:.1f}ms", file=sys.stderr)

    sys.exit(0)


if __name__ == "__main__":
    main()
