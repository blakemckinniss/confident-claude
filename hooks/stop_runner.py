#!/usr/bin/env python3
"""
Composite Stop Runner: Runs all Stop hooks in a single process.

PERFORMANCE: ~100ms for all hooks vs ~300ms for individual processes

HOOKS INDEX (by priority):
  PERSISTENCE (0-20):
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
# HOOK RESULT TYPE
# =============================================================================


@dataclass
class HookResult:
    """Result from a hook check."""

    decision: str = "continue"  # "continue" or "block"
    reason: str = ""  # Reason for block
    stop_reason: str = ""  # Warning message (non-blocking)

    @staticmethod
    def ok() -> "HookResult":
        return HookResult(decision="continue")

    @staticmethod
    def warn(message: str) -> "HookResult":
        return HookResult(decision="continue", stop_reason=message)

    @staticmethod
    def block(reason: str) -> "HookResult":
        return HookResult(decision="block", reason=reason)


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

    def decorator(func: Callable[[dict, SessionState], HookResult]):
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
COMPLETION_CONFIDENCE_THRESHOLD = 80  # Stasis floor - healthy operating range


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


def generate_commit_message(changes: dict) -> str:
    """Generate semantic commit message from changes."""
    all_files = (
        changes["modified"] + changes["added"] + changes["deleted"] + changes["renamed"]
    )

    if not all_files:
        return ""

    hooks = [f for f in all_files if "hooks/" in f]
    ops = [f for f in all_files if "ops/" in f]
    commands = [f for f in all_files if "commands/" in f]
    lib = [f for f in all_files if "lib/" in f]
    config = [
        f
        for f in all_files
        if any(c in f for c in ["settings.json", "config/", ".json", ".yaml", ".yml"])
    ]
    memory = [f for f in all_files if "memory/" in f]
    projects = [f for f in all_files if "projects/" in f]
    other = [
        f
        for f in all_files
        if f not in hooks + ops + commands + lib + config + memory + projects
    ]

    parts = []
    if hooks:
        parts.append(f"hooks ({len(hooks)})")
    if ops:
        parts.append(f"ops ({len(ops)})")
    if commands:
        parts.append(f"commands ({len(commands)})")
    if lib:
        parts.append(f"lib ({len(lib)})")
    if config:
        parts.append(f"config ({len(config)})")
    if memory:
        parts.append(f"memory ({len(memory)})")
    if projects:
        parts.append("projects")
    if other:
        other_dirs = set()
        for f in other[:5]:
            parts_path = Path(f).parts
            if len(parts_path) > 1:
                other_dirs.add(parts_path[0])
        if other_dirs:
            parts.append(", ".join(list(other_dirs)[:3]))
        else:
            parts.append(f"{len(other)} files")

    summary = ", ".join(parts)

    stats = []
    if changes["modified"]:
        stats.append(f"{len(changes['modified'])} modified")
    if changes["added"]:
        stats.append(f"{len(changes['added'])} added")
    if changes["deleted"]:
        stats.append(f"{len(changes['deleted'])} deleted")
    if changes["renamed"]:
        stats.append(f"{len(changes['renamed'])} renamed")

    stats_line = ", ".join(stats) if stats else "no changes"
    return f"[auto] {summary}\n\nFiles: {stats_line}"


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
# HOOK IMPLEMENTATIONS
# =============================================================================


@register_hook("auto_commit", priority=10)
def check_auto_commit(data: dict, state: SessionState) -> HookResult:
    """Commit all changes (semantic backup)."""
    cwd = data.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()

    if not is_git_repo(cwd):
        return HookResult.ok()

    changes = get_changes(cwd)
    total = sum(len(v) for v in changes.values())

    if total == 0:
        return HookResult.ok()

    message = generate_commit_message(changes)
    if not message:
        return HookResult.ok()

    # Stage all changes
    code, _, stderr = run_git(["add", "-A"], cwd)
    if code != 0:
        return HookResult.warn(f"⚠️ Auto-commit: git add failed: {stderr}")

    # Commit
    code, _, stderr = run_git(["commit", "-m", message], cwd)
    if code != 0:
        if "nothing to commit" not in stderr.lower():
            return HookResult.warn(f"⚠️ Auto-commit failed: {stderr}")
        return HookResult.ok()

    # Report success in state (not blocking)
    summary = message.split("\n")[0]
    return HookResult.warn(f"✅ Auto-committed: {summary} ({total} files)")


@register_hook("session_blocks", priority=30)
def check_session_blocks(data: dict, state: SessionState) -> HookResult:
    """Require reflection on session blocks."""
    from synapse_core import get_session_blocks, clear_session_blocks

    transcript_path = data.get("transcript_path", "")
    blocks = get_session_blocks()

    if not blocks:
        return HookResult.ok()

    # Check for acknowledgments
    substantive_ack, any_ack, lessons = check_acknowledgments_in_transcript(
        transcript_path
    )

    if substantive_ack:
        persist_lessons_to_memory(lessons, blocks)
        clear_session_blocks()
        return HookResult.ok()

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
        return HookResult.warn("\n".join(lines))

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

    return HookResult.block("\n".join(lines))


@register_hook("dismissal_check", priority=40)
def check_dismissal(data: dict, state: SessionState) -> HookResult:
    """Catch false positive claims without fix."""
    transcript_path = data.get("transcript_path", "")
    dismissals = check_dismissals_in_transcript(transcript_path)

    if not dismissals:
        return HookResult.ok()

    lines = ["🔧 **FALSE POSITIVE CLAIMED** - Fix required:"]
    lines.extend(dismissals)
    lines.append(
        "\n**REQUIRED:** Fix the hook that fired incorrectly. This block repeats until fixed."
    )

    return HookResult.block("\n".join(lines))


@register_hook("completion_gate", priority=45)
def check_completion_confidence(data: dict, state: SessionState) -> HookResult:
    """Block completion claims if confidence < 80% (stasis floor).

    This prevents lazy completion and reward hacking - Claude must earn
    confidence through actual verification (test pass, build success, user OK)
    before claiming a task is complete. 80% is the floor of the healthy
    operating range (80-90%).
    """
    # Import confidence utilities
    from confidence import get_tier_info, INCREASERS

    # Check current confidence
    confidence = getattr(state, "confidence", 70)
    if confidence >= COMPLETION_CONFIDENCE_THRESHOLD:
        return HookResult.ok()

    # Scan recent assistant output for completion claims
    transcript_path = data.get("transcript_path", "")
    if not transcript_path or not Path(transcript_path).exists():
        return HookResult.ok()

    try:
        with open(transcript_path, "rb") as f:
            f.seek(0, 2)  # End
            size = f.tell()
            f.seek(max(0, size - 15000))  # Last 15KB
            content = f.read().decode("utf-8", errors="ignore").lower()
    except (OSError, PermissionError):
        return HookResult.ok()

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

            return HookResult.block(
                f"🚫 **COMPLETION BLOCKED** - Confidence too low\n\n"
                f"Current: {emoji} {confidence}% ({tier_name})\n"
                f"Required: 🟢 {COMPLETION_CONFIDENCE_THRESHOLD}% (stasis floor)\n\n"
                f"**You cannot claim completion without earning confidence.**\n"
                f"This prevents lazy completion and reward hacking.\n\n"
                f"**How to raise confidence:**\n"
                + "\n".join(boost_options[:6])
                + "\n\n"
                "Or get explicit user approval: 'CONFIDENCE_BOOST_APPROVED'"
            )

    return HookResult.ok()


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
}


@register_hook("bad_language_detector", priority=46)
def check_bad_language(data: dict, state: SessionState) -> HookResult:
    """Detect and penalize bad language patterns in assistant output.

    Scans transcript for: overconfident completion claims, deferral,
    apologetic language, and sycophancy patterns.
    """
    from confidence import (
        apply_rate_limit,
        format_confidence_change,
        format_dispute_instructions,
        get_tier_info,
        set_confidence,
    )

    # Get recent transcript content
    transcript_path = data.get("transcript_path", "")
    if not transcript_path or not Path(transcript_path).exists():
        return HookResult.ok()

    try:
        with open(transcript_path, "rb") as f:
            f.seek(0, 2)  # End
            size = f.tell()
            f.seek(max(0, size - 20000))  # Last 20KB
            content = f.read().decode("utf-8", errors="ignore")
    except (OSError, PermissionError):
        return HookResult.ok()

    # Track which patterns triggered
    triggered = []

    for name, config in BAD_LANGUAGE_PATTERNS.items():
        # Check cooldown
        cooldown_key = f"bad_lang_{name}_turn"
        last_turn = state.nudge_history.get(cooldown_key, 0)
        if state.turn_count - last_turn < 3:  # 3 turn cooldown
            continue

        for pattern in config["patterns"]:
            if re.search(pattern, content, re.IGNORECASE):
                triggered.append((name, config["delta"]))
                state.nudge_history[cooldown_key] = state.turn_count
                break  # Only trigger once per category

    if not triggered:
        return HookResult.ok()

    # Apply penalties with rate limiting
    old_confidence = state.confidence
    total_delta = sum(delta for _, delta in triggered)
    total_delta = apply_rate_limit(total_delta, state)
    new_confidence = max(0, min(100, old_confidence + total_delta))

    set_confidence(state, new_confidence, "bad language detected")

    # Format feedback
    reasons = [f"{name}: {delta}" for name, delta in triggered]
    change_msg = format_confidence_change(
        old_confidence, new_confidence, ", ".join(reasons)
    )

    _, emoji, desc = get_tier_info(new_confidence)
    reducer_names = [name for name, _ in triggered]
    dispute_hint = format_dispute_instructions(reducer_names)

    return HookResult.warn(
        f"📉 **Bad Language Detected**\n{change_msg}\n\n"
        f"Current: {emoji} {new_confidence}% - {desc}"
        f"{dispute_hint}"
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
}


@register_hook("good_language_detector", priority=47)
def check_good_language(data: dict, state: SessionState) -> HookResult:
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
        return HookResult.ok()

    try:
        with open(transcript_path, "rb") as f:
            f.seek(0, 2)  # End
            size = f.tell()
            f.seek(max(0, size - 20000))  # Last 20KB
            content = f.read().decode("utf-8", errors="ignore")
    except (OSError, PermissionError):
        return HookResult.ok()

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
        return HookResult.ok()

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

    return HookResult.ok(
        f"📈 **Verification Language**\n{change_msg}\n\n"
        f"Current: {emoji} {new_confidence}% - {desc}"
    )


@register_hook("stub_detector", priority=50)
def check_stubs(data: dict, state: SessionState) -> HookResult:
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
        return HookResult.ok()

    lines = ["⚠️ **ABANDONED WORK** - Files with stubs:"]
    lines.extend(warnings)
    return HookResult.warn("\n".join(lines))


@register_hook("pending_greps", priority=70)
def check_pending_greps(data: dict, state: SessionState) -> HookResult:
    """Check for unverified function edits."""
    pending = state.pending_integration_greps
    if not pending:
        return HookResult.ok()

    funcs = [p.get("function", "unknown") for p in pending[:3]]
    return HookResult.warn(
        f"⚠️ **UNVERIFIED EDITS** - Functions need grep: {', '.join(funcs)}"
    )


@register_hook("unresolved_errors", priority=80)
def check_unresolved_errors(data: dict, state: SessionState) -> HookResult:
    """Check for lingering errors."""
    if not state.errors_unresolved:
        return HookResult.ok()

    error = state.errors_unresolved[-1]
    return HookResult.warn(
        f"⚠️ **UNRESOLVED ERROR**: {error.get('type', 'unknown')[:50]}"
    )


# =============================================================================
# MAIN RUNNER
# =============================================================================


def run_hooks(data: dict, state: SessionState) -> dict:
    """Run all hooks and return aggregated result."""
    sorted_hooks = sorted(HOOKS, key=lambda x: x[2])

    stop_reasons = []
    block_reason = None

    for name, check_func, priority in sorted_hooks:
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
