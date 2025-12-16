#!/usr/bin/env python3
"""
Composite Stop Runner: Runs all Stop hooks in a single process.

PERFORMANCE: ~100ms for all hooks vs ~300ms for individual processes

HOOKS INDEX (by priority):
  CONTEXT MANAGEMENT (0-5):
    3 context_warning     - Warn at 75% context usage
    4 context_exhaustion  - Force resume prompt at 85%

  PERSISTENCE (6-20):
    10 auto_commit        - Commit all changes (semantic backup)

  VALIDATION (30-60):
    30 session_blocks     - Require reflection on blocks
    40 dismissal_check    - Catch false positive claims without fix
    45 completion_gate    - Block completion if confidence < 85%
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
from typing import Callable
from dataclasses import dataclass
from pathlib import Path

from session_state import load_state, save_state, SessionState
from _patterns import STUB_BYTE_PATTERNS, CODE_EXTENSIONS

# =============================================================================
# STOP HOOK RESULT TYPE (distinct from _hook_result.HookResult)
# =============================================================================


@dataclass
class StopHookResult:
    """Result from a Stop hook check.

    Note: This is intentionally different from _hook_result.StopHookResult.
    Stop hooks use "continue"/"block" semantics with stop_reason for warnings,
    while pre/post hooks use "approve"/"deny" with context injection.
    """

    decision: str = "continue"  # "continue" or "block"
    reason: str = ""  # Reason for block
    stop_reason: str = ""  # Warning message (non-blocking)

    @staticmethod
    def ok() -> "StopHookResult":
        return StopHookResult(decision="continue")

    @staticmethod
    def warn(message: str) -> "StopHookResult":
        return StopHookResult(decision="continue", stop_reason=message)

    @staticmethod
    def block(reason: str) -> "StopHookResult":
        return StopHookResult(decision="block", reason=reason)


# =============================================================================
# HOOK REGISTRY
# =============================================================================

# Format: (name, check_function, priority)
HOOKS: list[tuple[str, Callable, int]] = []


def register_hook(name: str, priority: int = 50):
    """Decorator to register a hook check function.

    Hooks can be disabled via environment variable:
        CLAUDE_HOOK_DISABLE_<NAME>=1

    Example:
        CLAUDE_HOOK_DISABLE_SESSION_CLEANUP=1 claude
    """

    def decorator(func: Callable[[dict, SessionState], StopHookResult]):
        # Check if hook is disabled via environment variable
        env_key = f"CLAUDE_HOOK_DISABLE_{name.upper()}"
        if os.environ.get(env_key, "0") == "1":
            return func  # Skip registration
        HOOKS.append((name, func, priority))
        return func

    return decorator


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
CONTEXT_WARNING_THRESHOLD = 0.75  # 75% - soft warning
CONTEXT_EXHAUSTION_THRESHOLD = 0.85  # 85% - hard block
DEFAULT_CONTEXT_WINDOW = 200000  # Default if model info unavailable

# Dismissal patterns
DISMISSAL_PATTERNS = [
    (r"(this|that|it)('s| is) a false positive", "false_positive"),
    (r"the (warning|hook|gate) is (a )?false positive", "false_positive"),
    (r"hook (is )?(wrong|incorrect|mistaken)", "hook_dismissal"),
    (r"ignore (this|the) (warning|hook|gate)", "ignore_warning"),
    (r"(that|this) warning (is )?(incorrect|wrong)", "false_positive"),
]

# Completion claim patterns - detect when Claude claims task is done
COMPLETION_PATTERNS = [
    r"\b(task|work|implementation|feature|fix|bug)\s+(is\s+)?(now\s+)?(complete|done|finished)\b",
    r"\b(that'?s?|this)\s+(should\s+)?(be\s+)?(all|everything|it)\b",
    r"\bsuccessfully\s+(implemented|completed|fixed|finished)\b",
    r"\b(all\s+)?(changes|work|tasks?)\s+(are\s+)?(complete|done)\b",
    r"\bnothing\s+(left|more|else)\s+to\s+do\b",
    r"^\*\*(?:session\s+)?summary\s+(?:of\s+)?(?:completed?\s+)?(?:work|changes|tasks?)",  # More specific
]

# Confidence threshold for completion claims
COMPLETION_CONFIDENCE_THRESHOLD = 70  # Lowered threshold
COMPLETION_TREND_THRESHOLD = 75  # Below this, must not be declining


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


def _format_resume_template(
    state: SessionState, pct: float, used: int, total: int
) -> str:
    """Format the comprehensive resume prompt template with session state."""
    # Gather files modified
    files_modified = list(set(state.files_edited + state.files_created))[:20]
    files_str = (
        "\n".join(f"- {f}" for f in files_modified)
        if files_modified
        else "- None tracked"
    )

    # Memory files consulted
    memory_files = [
        f for f in state.files_read if "/.claude/memory/" in f or "/memory/" in f
    ][:10]
    memory_str = (
        "\n".join(f"- {Path(f).name}" for f in memory_files)
        if memory_files
        else "- None"
    )

    # Evidence ledger
    evidence = state.evidence_ledger[-10:] if state.evidence_ledger else []
    evidence_str = (
        "\n".join(f"- {e.get('summary', str(e))[:100]}" for e in evidence)
        if evidence
        else "- None recorded"
    )

    # Approach history
    approaches = state.approach_history[-5:] if state.approach_history else []
    approach_str = (
        "\n".join(
            f"- {a.get('approach', 'unknown')}: {a.get('failures', 0)} failures"
            for a in approaches
        )
        if approaches
        else "- None tracked"
    )

    # Errors unresolved
    errors = state.errors_unresolved[-5:] if state.errors_unresolved else []
    errors_str = (
        "\n".join(
            f"- {e.get('type', 'error')}: {e.get('message', str(e))[:80]}"
            for e in errors
        )
        if errors
        else "- None"
    )

    # Blockers
    blockers = state.handoff_blockers[-5:] if state.handoff_blockers else []
    blockers_str = (
        "\n".join(f"- {b}" for b in blockers) if blockers else "- None identified"
    )

    # Next steps from state
    next_steps = state.handoff_next_steps[-5:] if state.handoff_next_steps else []
    next_str = (
        "\n".join(f"- {s}" for s in next_steps)
        if next_steps
        else "[Fill in priority next actions]"
    )

    # Work queue items
    work_items = [w for w in state.work_queue if w.get("status") != "done"][:5]
    work_str = (
        "\n".join(
            f"- [{w.get('type', 'task')}] {w.get('description', str(w))[:60]}"
            for w in work_items
        )
        if work_items
        else ""
    )

    # Progress log
    progress = state.progress_log[-5:] if state.progress_log else []
    progress_str = (
        "\n".join(f"- {p.get('description', str(p))[:80]}" for p in progress)
        if progress
        else "[Describe what was accomplished]"
    )

    return f"""## 🔄 CONTEXT EXHAUSTION ({pct:.0f}%) - Resume Prompt Required

**Context usage: {used:,} / {total:,} tokens**

You MUST generate a comprehensive resume prompt before this session ends.
Fill in the bracketed sections with specific details from this session.

---

# Resume Prompt for New Session

## Original Goal
{state.original_goal or "[Describe what the user originally asked for]"}

## Progress Summary
{progress_str}

## Files Modified
{files_str}

## Key Decisions Made
[Document important architectural/implementation choices and their rationale]

## Current Blockers
{errors_str}
{blockers_str}

## Beads Status
Run these commands to see current task state:
```bash
bd list --status=open
bd list --status=in_progress
```

## Git State
Run to capture uncommitted work:
```bash
git status --short
git diff --stat
```

## Memory Files Consulted
{memory_str}

## Evidence Gathered
{evidence_str}

## Approaches Tried
{approach_str}

## Work Queue
{work_str if work_str else "[Any discovered work items]"}

## Next Steps (Priority Order)
{next_str}

## Critical Context
[Information the next session MUST know:
- Environment variables or config needed
- Ports/services that should be running
- API keys location or auth setup
- Any workarounds or gotchas discovered]

## Session Continuity Resources

**Full Transcript:**
- Location: `~/.claude/projects/` (by project/session ID)
- Session ID: `{state.session_id or "[check session_state.json]"}`

**Memory Systems:**
- Framework: `~/.claude/memory/` (lessons, decisions, capabilities)
- Serena: `~/.claude/.serena/memories/` (project-specific if Serena active)

**Serena Activation:**
If `.serena/` exists in working directory, activate with:
```
mcp__serena__activate_project
```

---

**Copy everything between the --- markers to start a new session.**
"""


# =============================================================================
# HOOK IMPLEMENTATIONS
# =============================================================================


@register_hook("context_warning", priority=3)
def check_context_warning(data: dict, state: SessionState) -> StopHookResult:
    """Warn when context reaches 75% - non-blocking heads up."""
    # Skip if already warned this session
    if state.nudge_history.get("context_warning_shown"):
        return StopHookResult.ok()

    transcript_path = data.get("transcript_path", "")
    context_window = data.get("model", {}).get("context_window", DEFAULT_CONTEXT_WINDOW)

    used, total = get_context_usage(transcript_path, context_window)
    if total == 0:
        return StopHookResult.ok()

    pct = used / total
    if pct < CONTEXT_WARNING_THRESHOLD:
        return StopHookResult.ok()

    # Don't warn if we're already at exhaustion threshold (let that hook handle it)
    if pct >= CONTEXT_EXHAUSTION_THRESHOLD:
        return StopHookResult.ok()

    # Mark as warned
    state.nudge_history["context_warning_shown"] = True

    return StopHookResult.warn(
        f"⚠️ **CONTEXT WARNING** - {pct:.0%} used ({used:,} / {total:,} tokens)\n\n"
        "Consider:\n"
        "- Wrapping up current task\n"
        "- Running `bd sync` to save bead state\n"
        "- Committing work in progress\n\n"
        f"**Hard cutoff at {CONTEXT_EXHAUSTION_THRESHOLD:.0%} will require resume prompt generation.**"
    )


@register_hook("context_exhaustion", priority=4)
def check_context_exhaustion(data: dict, state: SessionState) -> StopHookResult:
    """Force resume prompt generation at 85% context usage."""
    # Skip if resume already generated
    if state.nudge_history.get("context_resume_generated"):
        return StopHookResult.ok()

    transcript_path = data.get("transcript_path", "")
    context_window = data.get("model", {}).get("context_window", DEFAULT_CONTEXT_WINDOW)

    used, total = get_context_usage(transcript_path, context_window)
    if total == 0:
        return StopHookResult.ok()

    pct = used / total
    if pct < CONTEXT_EXHAUSTION_THRESHOLD:
        return StopHookResult.ok()

    # Mark as triggered (will be set after user sees the block)
    state.nudge_history["context_resume_generated"] = True

    # Provide both: the template AND mention the command
    template = _format_resume_template(state, pct * 100, used, total)
    return StopHookResult.block(
        template
        + "\n\n💡 **TIP:** Run `/resume` to auto-generate this from session state."
    )


@register_hook("auto_commit", priority=10)
def check_auto_commit(data: dict, state: SessionState) -> StopHookResult:
    """Commit all changes (semantic backup)."""
    cwd = data.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()

    if not is_git_repo(cwd):
        return StopHookResult.ok()

    changes = get_changes(cwd)
    total = sum(len(v) for v in changes.values())

    if total == 0:
        return StopHookResult.ok()

    message = generate_commit_message(changes)
    if not message:
        return StopHookResult.ok()

    # Stage all changes
    code, _, stderr = run_git(["add", "-A"], cwd)
    if code != 0:
        return StopHookResult.warn(f"⚠️ Auto-commit: git add failed: {stderr}")

    # Commit
    code, _, stderr = run_git(["commit", "-m", message], cwd)
    if code != 0:
        if "nothing to commit" not in stderr.lower():
            return StopHookResult.warn(f"⚠️ Auto-commit failed: {stderr}")
        return StopHookResult.ok()

    # Report success in state (not blocking)
    summary = message.split("\n")[0]
    return StopHookResult.warn(f"✅ Auto-committed: {summary} ({total} files)")


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


@register_hook("completion_gate", priority=45)
def check_completion_confidence(data: dict, state: SessionState) -> StopHookResult:
    """Block completion claims if confidence < 70%, or < 75% with negative trend.

    This prevents lazy completion and reward hacking - Claude must earn
    confidence through actual verification (test pass, build success, user OK)
    before claiming a task is complete.
    """
    # Import confidence utilities
    from confidence import get_tier_info, INCREASERS

    # Check current confidence and trend
    confidence = getattr(state, "confidence", 70)
    prev_confidence = getattr(state, "completion_gate_prev_confidence", confidence)
    state.completion_gate_prev_confidence = confidence  # Track for next check

    is_declining = confidence < prev_confidence

    # Pass if above threshold
    if confidence >= COMPLETION_CONFIDENCE_THRESHOLD:
        # But block if in danger zone (< 75%) AND declining
        if confidence < COMPLETION_TREND_THRESHOLD and is_declining:
            pass  # Fall through to block
        else:
            return StopHookResult.ok()

    # Scan recent assistant output for completion claims
    transcript_path = data.get("transcript_path", "")
    if not transcript_path or not Path(transcript_path).exists():
        return StopHookResult.ok()

    try:
        with open(transcript_path, "rb") as f:
            f.seek(0, 2)  # End
            size = f.tell()
            f.seek(max(0, size - 15000))  # Last 15KB
            content = f.read().decode("utf-8", errors="ignore").lower()
    except (OSError, PermissionError):
        return StopHookResult.ok()

    # Check for completion patterns
    for pattern in COMPLETION_PATTERNS:
        if re.search(pattern, content, re.IGNORECASE | re.MULTILINE):
            tier_name, emoji, _ = get_tier_info(confidence)

            # Build guidance on how to raise confidence
            boost_options = []
            for inc in INCREASERS:
                if not inc.requires_approval:
                    boost_options.append(
                        f"  • {inc.name}: {inc.description} (+{inc.delta})"
                    )

            # Determine block reason
            if confidence < COMPLETION_CONFIDENCE_THRESHOLD:
                reason = f"below {COMPLETION_CONFIDENCE_THRESHOLD}%"
            else:
                reason = f"declining in danger zone (<{COMPLETION_TREND_THRESHOLD}%)"

            return StopHookResult.block(
                f"🚫 **COMPLETION BLOCKED** - Confidence {reason}\n\n"
                f"Current: {emoji} {confidence}% ({tier_name})"
                + (f" ↓ (was {prev_confidence}%)" if is_declining else "")
                + "\n\n**How to raise confidence:**\n"
                + "\n".join(boost_options[:5])
                + "\n\nOr: 'CONFIDENCE_BOOST_APPROVED'"
            )

    return StopHookResult.ok()


# Language patterns for bad behavior detection
BAD_LANGUAGE_PATTERNS = {
    "overconfident_completion": {
        "delta": -15,
        "patterns": [
            r"\b100%\s*(done|complete|finished|ready)\b",
            r"\bcompletely\s+(done|finished|ready)\b",
            r"\bperfectly\s+(done|finished|working)\b",
            r"\bfully\s+complete[d]?\b",
        ],
    },
    "deferral": {
        "delta": -12,
        "patterns": [
            r"\bskip\s+(this\s+)?(for\s+)?now\b",
            r"\bcome\s+back\s+(to\s+(this|it)\s+)?later\b",
            r"\bdo\s+(this|it)\s+later\b",
            r"\bleave\s+(this|it)\s+for\s+(now|later)\b",
            r"\bwe\s+can\s+(do|address|handle)\s+(this|it)\s+later\b",
            r"\bpostpone\b",
            r"\bdefer\s+(this|it)\b",
            # "investigate later" variants - absolute cancer
            r"\b(bug|issue|problem|this)\s+to\s+investigate\s+later\b",
            r"\binvestigate\s+(this\s+)?(later|another\s+time)\b",
            r"\blook\s+into\s+(this\s+)?(later|another\s+time)\b",
            r"\bfix\s+(this\s+)?(later|another\s+time)\b",
            r"\baddress\s+(this\s+)?(later|another\s+time)\b",
            r"\btable\s+(this|it)\s+for\s+(now|later)\b",
            r"\bpunt\s+(on\s+)?(this|it)\b",
            r"\bshelve\s+(this|it)\b",
            r"\bbacklog\s+(this|it)\b",
        ],
    },
    "apologetic": {
        "delta": -5,
        "patterns": [
            r"\b(i'?m\s+)?sorry\b",
            r"\bmy\s+(mistake|bad|apologies|fault)\b",
            r"\bi\s+apologize\b",
            r"\bapologies\s+for\b",
        ],
    },
    "sycophancy": {
        "delta": -8,
        "patterns": [
            r"\byou'?re\s+(absolutely|totally|completely|entirely)\s+right\b",
            r"\babsolutely\s+right\b",
            r"\byou'?re\s+right,?\s+(i|my)\b",
            r"\bthat'?s\s+(absolutely|totally|completely)\s+(correct|true|right)\b",
            r"\bgreat\s+(point|observation|catch)\b",
            r"\bexcellent\s+(point|observation|catch)\b",
        ],
    },
    # Theater patterns - look busy without substance
    "filler_preamble": {
        "delta": -5,
        "patterns": [
            r"\bgreat\s+question\b",
            r"\bgood\s+question\b",
            r"\bi\s+understand\s+(your|the|what)\b",
            r"\bi'?d\s+be\s+happy\s+to\b",
            r"\bi'?ll\s+be\s+happy\s+to\b",
            r"^certainly[!.,]",
            r"^absolutely[!.,]",
            r"^of\s+course[!.,]",
            r"\blet\s+me\s+help\s+you\s+with\b",
        ],
    },
    "confirmation_theater": {
        "delta": -5,
        "patterns": [
            r"\bwould\s+you\s+like\s+me\s+to\b",
            r"\bshould\s+i\s+proceed\b",
            r"\bdo\s+you\s+want\s+me\s+to\b",
            r"\bshall\s+i\s+(start|begin|proceed|continue)\b",
            r"\bwant\s+me\s+to\s+(go\s+ahead|proceed)\b",
        ],
    },
    "announcement_theater": {
        "delta": -3,
        "patterns": [
            r"\bnow\s+i\s+will\b",
            r"\bnow\s+i'?m\s+going\s+to\b",
            r"\bi'?m\s+now\s+going\s+to\b",
            r"\blet\s+me\s+now\b",
            r"\bi'?ll\s+now\b",
            r"\bnext,?\s+i\s+will\b",
            r"\bnext,?\s+i'?ll\b",
        ],
    },
    "excessive_affirmation": {
        "delta": -3,
        "patterns": [
            r"^sure[!.,]\s",
            r"^yes[!.,]\s+i\s+(can|will)\b",
            r"\bhappy\s+to\s+help\b",
            r"\bglad\s+to\s+help\b",
            r"\bno\s+problem[!.,]",
        ],
    },
    "bikeshedding": {
        "delta": -8,
        "patterns": [
            # Naming deliberation
            r"\bwe\s+could\s+(call|name)\s+it\s+\w+\s+or\s+\w+\b",
            r"\b(name|call)\s+it\s+(either\s+)?\w+\s+or\s+\w+\b",
            r"\boption\s+(a|1)[:\s].*\boption\s+(b|2)\b",
            # Excessive deliberation on trivial matters
            r"\bon\s+(the\s+)?one\s+hand\b.*\bon\s+the\s+other\s+hand\b",
            r"\bpros\s+and\s+cons\b.{0,50}\b(naming|style|format)",
            r"\b(tabs?\s+vs\.?\s+spaces?|spaces?\s+vs\.?\s+tabs?)\b",
            r"\b(single|double)\s+quotes?\s+vs\.?\s+(single|double)\b",
        ],
    },
    "greenfield_impulse": {
        "delta": -10,
        "patterns": [
            # "Start fresh" when modification is likely better
            r"\bstart\s+(from\s+)?scratch\b",
            r"\bbuild\s+(it\s+)?fresh\b",
            r"\brewrite\s+(it\s+)?from\s+(the\s+)?ground\s+up\b",
            r"\bscrap\s+(it|this|the)\s+and\s+(start|build)\b",
            r"\bthrow\s+(it|this)\s+away\s+and\b",
            # Creating new when existing should be modified
            r"\bcreate\s+a\s+new\s+\w+\s+(instead|rather)\b",
            r"\bwrite\s+a\s+new\s+\w+\s+(instead|rather)\b",
            r"\bbuild\s+a\s+new\s+\w+\s+(instead|rather)\b",
        ],
    },
    "passive_deflection": {
        "delta": -8,
        "patterns": [
            # Deflecting to user
            r"\b(up\s+to\s+you|your\s+(choice|call|decision))\b",
            r"\blet\s+me\s+know\s+(what\s+you\s+prefer|your\s+preference)\b",
            r"\bwhatever\s+you\s+(think|prefer|want)\b",
            r"\bi'?ll\s+leave\s+(it|that)\s+(up\s+)?to\s+you\b",
            # Apathetic hedging
            r"\bit\s+depends\b(?!\s+on\s+(the|whether))",  # allow "it depends on X"
            r"\bthere\s+are\s+many\s+(ways|approaches|options)\b(?!\.\s+i\s+recommend)",
            r"\bi'?m\s+not\s+(sure|certain)\b(?!\s*(,\s*)?(but|so)\s+let\s+me)",  # allow "not sure, let me check"
            r"\bi\s+don'?t\s+know\b(?!\s*(,\s*)?(but|so)\s+(let\s+me|i'?ll))",  # allow "don't know, let me investigate"
            # Open-ended non-answers
            r"\byou\s+could\s+(try|do|use)\s+\w+\s+or\s+\w+\b(?!\.\s*(i\s+)?(recommend|suggest))",
            r"\beither\s+(way|option)\s+(works|is\s+fine)\b",
            r"\bboth\s+(approaches|options)\s+(are|have)\s+(valid|merit)\b",
            # Lazy deflection
            r"\bthat'?s\s+beyond\s+(my|the)\s+scope\b",
            r"\bi\s+can'?t\s+(help|assist)\s+with\s+that\b(?!\s+because)",
        ],
    },
    "obvious_next_steps": {
        "delta": -5,
        "patterns": [
            # Obvious testing suggestions
            r"\btest\s+(?:in\s+)?(?:real\s+)?usage\b",
            r"\btest\s+the\s+(?:new\s+)?(?:patterns?|changes?|implementation)\b",
            r"\bverify\s+(?:it\s+)?works\b",
            r"\bplay\s*test\b",
            r"\btry\s+it\s+out\b",
            r"\bsee\s+how\s+it\s+(?:works|performs)\b",
            # Obvious iteration suggestions
            r"\btune\s+(?:the\s+)?(?:values?|deltas?|parameters?)\b",
            r"\badjust\s+(?:as\s+)?needed\b",
            r"\bmonitor\s+(?:for\s+)?(?:issues?|problems?)\b",
            r"\bwatch\s+(?:for\s+)?(?:issues?|problems?|errors?)\b",
            # Generic obvious actions
            r"\b(?:run|do)\s+(?:the\s+)?(?:tests?|builds?)\s+(?:to\s+)?(?:verify|check|confirm)\b",
        ],
    },
    "surrender_pivot": {
        "delta": -20,  # Severe penalty - this is CANCER behavior
        "patterns": [
            # Invented time constraints (LLMs have no time limits)
            r"\b(given|due\s+to)\s+(the\s+)?time\s+constraints?\b",
            r"\btime\s+(is\s+)?limited\b",
            r"\bfor\s+(the\s+)?sake\s+of\s+time\b",
            r"\bto\s+save\s+time\b",
            r"\bquickly\s+switch\s+to\b",
            # Unilateral pivots without asking
            r"\blet\s+me\s+(switch|use|try)\s+\w+\s+instead\b",
            r"\bi'?ll\s+(switch|use)\s+\w+\s+instead\b",
            r"\bswitching\s+to\s+\w+\s+(instead|which)\b",
            # Abandoning because "incomplete" without fixing
            r"\b(is\s+)?incomplete[.,]?\s+(so\s+)?(let\s+me|i'?ll)\s+(switch|use)\b",
            r"\bdoesn'?t\s+work[.,]?\s+(so\s+)?(let\s+me|i'?ll)\s+(switch|use)\b",
            # "Proven/out-of-the-box" as excuse
            r"\bproven\s+(model|solution|approach)\s+that\s+works\b",
            r"\bout[- ]of[- ]the[- ]box\s+(solution|alternative)\b",
            r"\bworks\s+out[- ]of[- ]the[- ]box\b",
            # Goal abandonment language
            r"\bgiven\s+(the\s+)?(issues?|problems?|difficulties?)[.,]\s+(let\s+me|i'?ll)\s+(switch|use|try)\b",
            r"\beasier\s+(to\s+)?(just\s+)?use\s+\w+\s+instead\b",
        ],
    },
}


def _collect_bad_language_triggers(
    content: str, state: SessionState
) -> list[tuple[str, int]]:
    """Scan content for bad language patterns, respecting cooldowns."""
    triggered = []
    for name, config in BAD_LANGUAGE_PATTERNS.items():
        cooldown_key = f"bad_lang_{name}_turn"
        if state.turn_count - state.nudge_history.get(cooldown_key, 0) < 3:
            continue
        for pattern in config["patterns"]:
            if re.search(pattern, content, re.IGNORECASE):
                triggered.append((name, config["delta"]))
                state.nudge_history[cooldown_key] = state.turn_count
                break
    return triggered


def _get_violation_multiplier(num_violations: int) -> float:
    """Get compounding multiplier for multiple violations."""
    if num_violations >= 4:
        return 3.0
    if num_violations >= 3:
        return 2.0
    if num_violations >= 2:
        return 1.5
    return 1.0


@register_hook("bad_language_detector", priority=46)
def check_bad_language(data: dict, state: SessionState) -> StopHookResult:
    """Detect and penalize bad language patterns in assistant output."""
    from confidence import (
        apply_rate_limit,
        format_confidence_change,
        format_dispute_instructions,
        get_tier_info,
        set_confidence,
    )

    transcript_path = data.get("transcript_path", "")
    if not transcript_path or not Path(transcript_path).exists():
        return StopHookResult.ok()

    try:
        with open(transcript_path, "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 20000))
            content = f.read().decode("utf-8", errors="ignore")
    except (OSError, PermissionError):
        return StopHookResult.ok()

    triggered = _collect_bad_language_triggers(content, state)
    if not triggered:
        return StopHookResult.ok()

    old_confidence = state.confidence
    total_delta = int(
        sum(d for _, d in triggered) * _get_violation_multiplier(len(triggered))
    )

    has_surrender = any(name == "surrender_pivot" for name, _ in triggered)
    if not has_surrender:
        total_delta = apply_rate_limit(total_delta, state)

    new_confidence = max(0, min(100, old_confidence + total_delta))
    set_confidence(state, new_confidence, "bad language detected")

    reasons = [f"{name}: {delta}" for name, delta in triggered]
    change_msg = format_confidence_change(
        old_confidence, new_confidence, ", ".join(reasons)
    )
    _, emoji, desc = get_tier_info(new_confidence)
    dispute_hint = format_dispute_instructions([n for n, _ in triggered])

    return StopHookResult.warn(
        f"📉 **Bad Language Detected**\n{change_msg}\n\n"
        f"Current: {emoji} {new_confidence}% - {desc}{dispute_hint}"
    )


# Positive language patterns for verification behavior
GOOD_LANGUAGE_PATTERNS = {
    "verification_intent": {
        "delta": 3,
        "patterns": [
            r"\blet\s+me\s+(just\s+)?(check|verify|confirm|validate|inspect)\b",
            r"\bi'?ll\s+(just\s+)?(check|verify|confirm|validate|inspect)\b",
            r"\blet\s+me\s+(first\s+)?(read|look\s+at|examine|review)\b",
            r"\bbefore\s+(i|we)\s+(proceed|continue|start)\b.*\b(check|verify|confirm)\b",
            r"\bfirst,?\s+(let\s+me\s+)?(check|verify|read|confirm)\b",
        ],
    },
    "evidence_gathering": {
        "delta": 2,
        "patterns": [
            r"\bto\s+understand\s+(this|the|how)\b",
            r"\bto\s+see\s+(what|how|if|whether)\b",
            r"\bto\s+confirm\s+(that|this|the|whether)\b",
            r"\bto\s+verify\s+(that|this|the|whether)\b",
        ],
    },
    "proactive_contribution": {
        "delta": 5,
        "patterns": [
            # "I also" patterns (extra work done)
            r"\bi\s+also\s+(fixed|addressed|cleaned|updated|improved|noticed\s+and\s+fixed)\b",
            r"\bwhile\s+(i\s+was\s+)?(there|at\s+it|doing\s+this),?\s+i\s+(also\s+)?(fixed|cleaned|updated)\b",
            r"\badditionally,?\s+i\s+(went\s+ahead\s+and\s+)?(fixed|addressed|cleaned|improved)\b",
            r"\bi\s+went\s+ahead\s+and\s+(also\s+)?(fixed|cleaned|ran|added)\b",
            # Bonus/extra patterns
            r"\b(bonus|as\s+a\s+bonus)[:\s]+\s*i\b",
            r"\bextra[:\s]+i\s+(also\s+)?\b",
            # Proactive quality signals
            r"\bi\s+ran\s+(the\s+)?(tests?|lints?|checks?)\s+(to\s+make\s+sure|to\s+verify|proactively)\b",
            r"\bcaught\s+(and\s+fixed|this\s+while)\b",
        ],
    },
    "debt_removal": {
        "delta": 10,
        "patterns": [
            # Removing dead/unused code
            r"\b(removed|deleted|cleaned\s+up)\s+(dead|unused|obsolete|stale)\s+(code|imports?|files?|functions?)\b",
            r"\b(removed|deleted)\s+\d+\s+(unused|dead)\b",
            r"\bpaid\s+(down|off)\s+(tech(nical)?|org(anizational)?)\s+debt\b",
            # Resolving TODOs/FIXMEs
            r"\b(resolved|completed|addressed|fixed)\s+(the\s+)?(TODO|FIXME|HACK)\b",
            r"\b(removed|cleared)\s+(a\s+)?(TODO|FIXME)\b",
            # Cleanup actions
            r"\bcleaned\s+up\s+(the\s+)?(codebase|code|file|module)\b",
            r"\brefactored\s+(away|out)\s+(the\s+)?(tech(nical)?\s+)?debt\b",
            r"\beliminated\s+(the\s+)?(tech(nical)?\s+)?debt\b",
            # File/code removal
            r"\bdeleted\s+(the\s+)?(deprecated|legacy|old)\s+(code|file|module)\b",
            r"\bremoved\s+(commented|commented-out)\s+code\b",
        ],
    },
    "assertive_stance": {
        "delta": 5,
        "patterns": [
            # Direct recommendations
            r"\bi\s+recommend\b",
            r"\byou\s+should\b",
            r"\bthe\s+(best|right|correct)\s+(approach|way|solution)\s+is\b",
            r"\buse\s+this\b",
            r"\bdo\s+this\b",
            r"\bhere'?s\s+(the|my)\s+(fix|solution|recommendation)\b",
            # Taking ownership
            r"\bi'?ll\s+(do|handle|fix|implement)\s+(this|it|that)\b",
            r"\bdoing\s+(this|it)\s+now\b",
            r"\bfixing\s+(this|it)\s+now\b",
            # Direct assertions
            r"\bthis\s+is\s+(the|a)\s+(bug|issue|problem|cause)\b",
            r"\bthe\s+(issue|problem|bug)\s+is\b",
            r"\bi\s+disagree\b",
            r"\bthat'?s\s+(incorrect|wrong|not\s+right)\b",
        ],
    },
}


@register_hook("good_language_detector", priority=47)
def check_good_language(data: dict, state: SessionState) -> StopHookResult:
    """Detect and reward verification language patterns in assistant output.

    Rewards: "let me check", "let me verify", evidence-gathering statements.
    """
    from confidence import (
        apply_rate_limit,
        format_confidence_change,
        get_tier_info,
        set_confidence,
    )

    # Get recent transcript content
    transcript_path = data.get("transcript_path", "")
    if not transcript_path or not Path(transcript_path).exists():
        return StopHookResult.ok()

    try:
        with open(transcript_path, "rb") as f:
            f.seek(0, 2)  # End
            size = f.tell()
            f.seek(max(0, size - 20000))  # Last 20KB
            content = f.read().decode("utf-8", errors="ignore")
    except (OSError, PermissionError):
        return StopHookResult.ok()

    # Track which patterns triggered
    triggered = []

    for name, config in GOOD_LANGUAGE_PATTERNS.items():
        # Check cooldown (longer cooldown to prevent gaming)
        cooldown_key = f"good_lang_{name}_turn"
        last_turn = state.nudge_history.get(cooldown_key, 0)
        if state.turn_count - last_turn < 5:  # 5 turn cooldown
            continue

        for pattern in config["patterns"]:
            if re.search(pattern, content, re.IGNORECASE):
                triggered.append((name, config["delta"]))
                state.nudge_history[cooldown_key] = state.turn_count
                break  # Only trigger once per category

    if not triggered:
        return StopHookResult.ok()

    # Apply rewards with rate limiting
    old_confidence = state.confidence
    total_delta = sum(delta for _, delta in triggered)
    total_delta = apply_rate_limit(total_delta, state)
    new_confidence = max(0, min(100, old_confidence + total_delta))

    set_confidence(state, new_confidence, "verification language detected")

    # Format feedback
    reasons = [f"{name}: +{delta}" for name, delta in triggered]
    change_msg = format_confidence_change(
        old_confidence, new_confidence, ", ".join(reasons)
    )

    _, emoji, desc = get_tier_info(new_confidence)

    return StopHookResult.ok(
        f"📈 **Verification Language**\n{change_msg}\n\n"
        f"Current: {emoji} {new_confidence}% - {desc}"
    )


# Verification theater patterns - claims that need tool evidence
VERIFICATION_CLAIMS = {
    "test_claim": {
        "patterns": [
            r"\btests?\s+(are\s+)?(pass(ing|ed)?|green|succeed(ed|ing)?)\b",
            r"\ball\s+tests?\s+(pass|green)\b",
            r"\bpytest\s+(pass|succeed)\b",
            r"\bi\s+ran\s+(the\s+)?tests?\b",
        ],
        "evidence_key": "tests_run",  # Check state.tests_run or recent test commands
    },
    "lint_claim": {
        "patterns": [
            r"\blint\s+(is\s+)?(clean|pass(ing|ed)?|green)\b",
            r"\bruff\s+(check\s+)?(pass|clean|green)\b",
            r"\bno\s+(lint(ing)?|ruff)\s+(errors?|issues?|warnings?)\b",
        ],
        "evidence_key": "lint_run",
    },
    "fixed_claim": {
        "patterns": [
            r"\b(fixed|resolved|solved)\s+(it|this|the\s+(bug|issue|problem))\b",
            r"\bthat\s+(should\s+)?(fix|resolve|solve)\s+(it|this|the)\b",
            r"\b(bug|issue|problem)\s+(is\s+)?(now\s+)?(fixed|resolved|solved)\b",
        ],
        "evidence_key": "recent_write",  # Need a recent file write
    },
}


def _read_tail_content(path: str, tail_bytes: int = 10000) -> str | None:
    """Read last N bytes of file as string, or None on error."""
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - tail_bytes))
            return f.read().decode("utf-8", errors="ignore").lower()
    except (OSError, PermissionError):
        return None


def _has_evidence(state: SessionState, evidence_key: str) -> bool:
    """Check if evidence exists for a verification claim."""
    if evidence_key == "tests_run":
        recent = state.commands_succeeded[-5:] + state.commands_failed[-5:]
        return any(
            t in cmd
            for cmd in recent
            for t in ["pytest", "npm test", "jest", "cargo test", "go test"]
        )
    elif evidence_key == "lint_run":
        return any(
            lc in cmd
            for cmd in state.commands_succeeded[-5:]
            for lc in ["ruff check", "eslint", "clippy", "pylint"]
        )
    elif evidence_key == "recent_write":
        return len(state.files_edited) > 0
    return False


@register_hook("verification_theater_detector", priority=48)
def check_verification_theater(data: dict, state: SessionState) -> StopHookResult:
    """Detect verification claims without tool evidence."""
    from confidence import apply_rate_limit, get_tier_info, set_confidence

    content = _read_tail_content(data.get("transcript_path", ""))
    if not content:
        return StopHookResult.ok()

    triggered = []
    for claim_type, config in VERIFICATION_CLAIMS.items():
        cooldown_key = f"verify_theater_{claim_type}_turn"
        if state.turn_count - state.nudge_history.get(cooldown_key, 0) < 3:
            continue
        if not any(re.search(p, content) for p in config["patterns"]):
            continue
        if not _has_evidence(state, config["evidence_key"]):
            delta = -8 if claim_type == "fixed_claim" else -15
            triggered.append((claim_type, delta))
            state.nudge_history[cooldown_key] = state.turn_count

    if not triggered:
        return StopHookResult.ok()

    total_delta = apply_rate_limit(sum(d for _, d in triggered), state)
    new_conf = max(0, min(100, state.confidence + total_delta))
    set_confidence(state, new_conf, "verification theater")
    _, emoji, desc = get_tier_info(new_conf)
    return StopHookResult.warn(
        f"📉 VERIFICATION THEATER: {emoji} {new_conf}% | Claims without evidence"
    )


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
