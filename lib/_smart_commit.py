"""Smart auto-commit system.

Commits at natural completion points without spamming.

Triggers:
- bd close: Natural completion point → auto-commit with bead title
- Session ending: Suggest commit if uncommitted changes
- Significant work: 5+ files edited AND tests pass → suggest
- Time threshold: 15+ turns since commit → suggest

Anti-triggers:
- Recent commit (< 3 turns): Cooldown
- Tests failing: Don't commit broken state
- Only scratch/tmp files: Not real work
- No file changes: Nothing to commit
"""

from __future__ import annotations

import re
import subprocess
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lib._session_state_class import SessionState

# =============================================================================
# Configuration
# =============================================================================

# Minimum turns between commits to avoid spam
COMMIT_COOLDOWN_TURNS = 3

# Minimum files edited to trigger suggestion (not auto-commit)
MIN_FILES_FOR_SUGGESTION = 5

# Maximum turns without commit before suggesting
MAX_TURNS_WITHOUT_COMMIT = 15

# Paths that don't count as "real work"
SCRATCH_PATTERNS = [
    r"\.claude/tmp/",
    r"\.claude/projects/",
    r"/tmp/",
    r"\.pyc$",
    r"__pycache__",
    r"\.git/",
]

# Paths that indicate test files
TEST_PATTERNS = [
    r"test[s]?/",
    r"_test\.py$",
    r"\.test\.[jt]sx?$",
    r"\.spec\.[jt]sx?$",
]


# =============================================================================
# State tracking
# =============================================================================


@dataclass
class CommitState:
    """Tracks commit-related state within a session."""

    last_commit_turn: int = 0
    last_commit_time: float = 0.0
    last_commit_hash: str = ""
    files_since_commit: list = field(default_factory=list)
    tests_passed_since_commit: bool = False
    last_bead_closed: str = ""  # Title of last closed bead


_commit_state = CommitState()


def get_commit_state() -> CommitState:
    """Get current commit state."""
    return _commit_state


def reset_commit_state() -> None:
    """Reset commit state (e.g., after a commit)."""
    global _commit_state
    _commit_state = CommitState(
        last_commit_turn=_commit_state.last_commit_turn,
        last_commit_time=_commit_state.last_commit_time,
        last_commit_hash=_commit_state.last_commit_hash,
    )


# =============================================================================
# Git utilities
# =============================================================================


def _run_git(args: list[str], cwd: str) -> tuple[int, str, str]:
    """Run a git command and return (code, stdout, stderr)."""
    try:
        result = subprocess.run(
            ["git"] + args,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result.returncode, result.stdout, result.stderr
    except Exception as e:
        return 1, "", str(e)


def is_git_repo(cwd: str) -> bool:
    """Check if directory is in a git repo."""
    code, _, _ = _run_git(["rev-parse", "--git-dir"], cwd)
    return code == 0


def get_uncommitted_changes(cwd: str) -> dict:
    """Get summary of uncommitted changes."""
    changes = {"modified": [], "added": [], "deleted": [], "renamed": []}

    code, stdout, _ = _run_git(["status", "--porcelain"], cwd)
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


def get_last_commit_info(cwd: str) -> tuple[str, str, float]:
    """Get hash, message, and timestamp of last commit."""
    code, stdout, _ = _run_git(
        ["log", "-1", "--format=%H|%s|%ct"],
        cwd,
    )
    if code != 0 or not stdout:
        return "", "", 0.0

    parts = stdout.strip().split("|")
    if len(parts) >= 3:
        return parts[0], parts[1], float(parts[2])
    return "", "", 0.0


def has_tests_passing(cwd: str) -> bool | None:
    """Check if tests are currently passing.

    Returns:
        True: Tests pass
        False: Tests fail
        None: Can't determine (no test command found or not run)
    """
    # Check for common test result markers in recent output
    # This is heuristic - we track test_pass/test_fail signals in session state
    return None  # Defer to session state


# =============================================================================
# Heuristics
# =============================================================================


def _is_scratch_file(filepath: str) -> bool:
    """Check if file is a scratch/temp file that doesn't need committing."""
    for pattern in SCRATCH_PATTERNS:
        if re.search(pattern, filepath):
            return True
    return False


def _filter_real_changes(changes: dict) -> dict:
    """Filter out scratch files from changes."""
    return {
        key: [f for f in files if not _is_scratch_file(f)]
        for key, files in changes.items()
    }


def _count_real_changes(changes: dict) -> int:
    """Count number of real (non-scratch) changed files."""
    real = _filter_real_changes(changes)
    return sum(len(files) for files in real.values())


def _categorize_changes(files: list[str]) -> dict[str, list[str]]:
    """Categorize files by type for commit message generation."""
    categories = {
        "hooks": [],
        "lib": [],
        "ops": [],
        "commands": [],
        "rules": [],
        "config": [],
        "tests": [],
        "other": [],
    }

    for f in files:
        if "/hooks/" in f or f.startswith("hooks/"):
            categories["hooks"].append(f)
        elif "/lib/" in f or f.startswith("lib/"):
            categories["lib"].append(f)
        elif "/ops/" in f or f.startswith("ops/"):
            categories["ops"].append(f)
        elif "/commands/" in f or f.startswith("commands/"):
            categories["commands"].append(f)
        elif "/rules/" in f or f.startswith("rules/"):
            categories["rules"].append(f)
        elif any(re.search(p, f) for p in TEST_PATTERNS):
            categories["tests"].append(f)
        elif "config" in f.lower() or f.endswith(".json") or f.endswith(".yaml"):
            categories["config"].append(f)
        else:
            categories["other"].append(f)

    return {k: v for k, v in categories.items() if v}


def generate_commit_message(changes: dict, bead_title: str | None = None) -> str:
    """Generate a semantic commit message from changes.

    Args:
        changes: Dict with modified/added/deleted/renamed lists
        bead_title: Optional bead title to use as basis for message
    """
    all_files = (
        changes["modified"] + changes["added"] + changes["deleted"] + changes["renamed"]
    )
    real_files = [f for f in all_files if not _is_scratch_file(f)]

    if not real_files:
        return ""

    # If we have a bead title, use it as the basis
    if bead_title:
        # Clean up bead title for commit message
        msg = bead_title.strip()
        # Ensure it has a prefix
        if not re.match(r"^(feat|fix|refactor|chore|docs|test|style)(\(.+\))?:", msg, re.I):
            # Infer prefix from bead title
            lower = msg.lower()
            if any(w in lower for w in ["fix", "bug", "error", "issue"]):
                prefix = "fix"
            elif any(w in lower for w in ["add", "new", "implement", "feature"]):
                prefix = "feat"
            elif any(w in lower for w in ["refactor", "clean", "improve"]):
                prefix = "refactor"
            elif any(w in lower for w in ["doc", "readme", "comment"]):
                prefix = "docs"
            elif any(w in lower for w in ["test"]):
                prefix = "test"
            else:
                prefix = "chore"
            msg = f"{prefix}: {msg}"
        return msg

    # Generate from file categories
    categories = _categorize_changes(real_files)

    # Build summary parts
    parts = []
    if "hooks" in categories:
        parts.append(f"hooks ({len(categories['hooks'])} files)")
    if "lib" in categories:
        parts.append(f"lib ({len(categories['lib'])} files)")
    if "ops" in categories:
        parts.append(f"ops ({len(categories['ops'])} files)")
    if "commands" in categories:
        parts.append(f"commands ({len(categories['commands'])} files)")
    if "rules" in categories:
        parts.append(f"rules ({len(categories['rules'])} files)")
    if "config" in categories:
        parts.append(f"config ({len(categories['config'])} files)")
    if "tests" in categories:
        parts.append(f"tests ({len(categories['tests'])} files)")
    if "other" in categories:
        parts.append(f"other ({len(categories['other'])} files)")

    summary = ", ".join(parts)

    # Determine prefix
    if categories.get("tests") and len(categories) == 1:
        prefix = "test"
    elif categories.get("config") and len(categories) == 1:
        prefix = "chore"
    else:
        prefix = "chore"

    # Stats line
    stats = []
    if changes["modified"]:
        stats.append(f"{len(changes['modified'])} modified")
    if changes["added"]:
        stats.append(f"{len(changes['added'])} added")
    if changes["deleted"]:
        stats.append(f"{len(changes['deleted'])} deleted")

    stats_line = ", ".join(stats) if stats else ""

    return f"{prefix}: Update {summary}\n\nFiles: {stats_line}"


# =============================================================================
# Core decision logic
# =============================================================================


@dataclass
class CommitDecision:
    """Result of should_commit evaluation."""

    should_commit: bool
    auto: bool  # True = auto-commit, False = suggest only
    reason: str
    message: str  # Suggested commit message


def should_commit(
    state: SessionState,
    cwd: str,
    trigger: str = "periodic",
) -> CommitDecision:
    """Evaluate whether a commit should happen.

    Args:
        state: Current session state
        cwd: Working directory
        trigger: What triggered this check:
            - "bead_close": A bead was closed
            - "session_end": Session is ending
            - "periodic": Regular periodic check

    Returns:
        CommitDecision with recommendation
    """
    commit_state = get_commit_state()

    # Not a git repo - can't commit
    if not is_git_repo(cwd):
        return CommitDecision(
            should_commit=False,
            auto=False,
            reason="not a git repo",
            message="",
        )

    # Get current changes
    changes = get_uncommitted_changes(cwd)
    real_count = _count_real_changes(changes)

    # No changes - nothing to commit
    if real_count == 0:
        return CommitDecision(
            should_commit=False,
            auto=False,
            reason="no uncommitted changes",
            message="",
        )

    # Cooldown check (unless session_end which bypasses)
    turns_since_commit = state.turn_count - commit_state.last_commit_turn
    if trigger != "session_end" and turns_since_commit < COMMIT_COOLDOWN_TURNS:
        return CommitDecision(
            should_commit=False,
            auto=False,
            reason=f"cooldown ({turns_since_commit}/{COMMIT_COOLDOWN_TURNS} turns)",
            message="",
        )

    # Check test status from session state
    tests_failing = bool(state.errors_unresolved) and any(
        "test" in str(e).lower() for e in state.errors_unresolved
    )
    if tests_failing and trigger != "session_end":
        return CommitDecision(
            should_commit=False,
            auto=False,
            reason="tests failing - don't commit broken state",
            message="",
        )

    # Generate commit message
    bead_title = commit_state.last_bead_closed if trigger == "bead_close" else None
    message = generate_commit_message(changes, bead_title)

    # === TRIGGER EVALUATION ===

    # Bead close = auto-commit
    if trigger == "bead_close" and commit_state.last_bead_closed:
        return CommitDecision(
            should_commit=True,
            auto=True,
            reason=f"bead closed: {commit_state.last_bead_closed}",
            message=message,
        )

    # Session end = suggest (not auto)
    if trigger == "session_end":
        return CommitDecision(
            should_commit=True,
            auto=False,
            reason="session ending with uncommitted changes",
            message=message,
        )

    # Significant work threshold
    if real_count >= MIN_FILES_FOR_SUGGESTION:
        # Prefer to have tests passed
        if state.tests_run:
            return CommitDecision(
                should_commit=True,
                auto=False,
                reason=f"{real_count} files changed + tests run",
                message=message,
            )

    # Time threshold
    if turns_since_commit >= MAX_TURNS_WITHOUT_COMMIT:
        return CommitDecision(
            should_commit=True,
            auto=False,
            reason=f"{turns_since_commit} turns since last commit",
            message=message,
        )

    # Default: no commit needed
    return CommitDecision(
        should_commit=False,
        auto=False,
        reason="no trigger conditions met",
        message="",
    )


def do_commit(cwd: str, message: str, state: SessionState) -> tuple[bool, str]:
    """Execute the commit.

    Args:
        cwd: Working directory
        message: Commit message
        state: Session state to update

    Returns:
        (success, result_message)
    """
    commit_state = get_commit_state()

    # Stage all changes
    code, _, stderr = _run_git(["add", "-A"], cwd)
    if code != 0:
        return False, f"git add failed: {stderr}"

    # Commit
    code, stdout, stderr = _run_git(["commit", "-m", message], cwd)
    if code != 0:
        return False, f"git commit failed: {stderr}"

    # Extract commit hash from output
    hash_match = re.search(r"\[[\w-]+\s+([a-f0-9]{7,})\]", stdout)
    commit_hash = hash_match.group(1) if hash_match else ""

    # Update state
    commit_state.last_commit_turn = state.turn_count
    commit_state.last_commit_time = time.time()
    commit_state.last_commit_hash = commit_hash
    reset_commit_state()

    return True, f"Committed: {commit_hash[:7]} {message.split(chr(10))[0]}"


# =============================================================================
# Hook integration helpers
# =============================================================================


def track_bead_close(bead_title: str) -> None:
    """Track that a bead was closed (called from post_tool_use hook)."""
    commit_state = get_commit_state()
    commit_state.last_bead_closed = bead_title


def track_file_change(filepath: str) -> None:
    """Track that a file was changed (called from post_tool_use hook)."""
    commit_state = get_commit_state()
    if filepath not in commit_state.files_since_commit:
        commit_state.files_since_commit.append(filepath)


def track_test_pass() -> None:
    """Track that tests passed (called from post_tool_use hook)."""
    commit_state = get_commit_state()
    commit_state.tests_passed_since_commit = True


def track_commit(turn: int, commit_hash: str = "") -> None:
    """Track that a commit happened (called from post_tool_use hook)."""
    commit_state = get_commit_state()
    commit_state.last_commit_turn = turn
    commit_state.last_commit_time = time.time()
    commit_state.last_commit_hash = commit_hash
    reset_commit_state()
