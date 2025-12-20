"""Smart auto-commit system v2.

Fully automatic commits at natural break points. No prompts, no suggestions.

Triggers (all auto-commit):
- bd close: Commit with bead title as message
- test_pass: Commit after successful test run
- build_success: Commit after successful build
- session_end: Commit ALL repos before stopping (hard requirement)

Repo Handling:
- Framework (.claude/) and project repos commit separately
- Detects repo root by walking up from CWD
- Generates appropriate commit messages per repo type

Anti-triggers:
- Recent commit (< 2 turns): Cooldown to prevent spam
- No changes: Nothing to commit
- Only untracked scratch files: Not real work
"""

from __future__ import annotations

import os
import re
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lib._session_state_class import SessionState

# =============================================================================
# Configuration
# =============================================================================

# Minimum turns between commits to same repo
COMMIT_COOLDOWN_TURNS = 2

# Paths that don't count as "real work"
SCRATCH_PATTERNS = [
    r"/tmp/",
    r"\.pyc$",
    r"__pycache__",
    r"\.git/",
    r"node_modules/",
    r"\.venv/",
    r"\.cache/",
]

# Framework-specific scratch (don't commit these even in .claude/)
FRAMEWORK_SCRATCH = [
    r"\.claude/tmp/",
    r"\.claude/projects/",  # Per-project state, not framework code
    r"stats-cache\.json$",
    r"thinking_index\.jsonl$",
]

# =============================================================================
# Repo Detection
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
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except Exception as e:
        return 1, "", str(e)


def get_repo_root(path: str) -> str | None:
    """Find git repo root by walking up from path."""
    code, stdout, _ = _run_git(["rev-parse", "--show-toplevel"], path)
    if code == 0 and stdout:
        return stdout
    return None


def is_framework_repo(repo_root: str) -> bool:
    """Check if repo is the .claude framework repo."""
    return repo_root.rstrip("/").endswith(".claude")


def get_all_active_repos() -> list[str]:
    """Get all repos that might have uncommitted changes.

    Checks:
    1. Current working directory's repo
    2. ~/.claude (framework repo)
    """
    repos = set()

    # Current directory's repo
    cwd_repo = get_repo_root(os.getcwd())
    if cwd_repo:
        repos.add(cwd_repo)

    # Framework repo
    framework_path = os.path.expanduser("~/.claude")
    if os.path.isdir(framework_path):
        framework_repo = get_repo_root(framework_path)
        if framework_repo:
            repos.add(framework_repo)

    return list(repos)


# =============================================================================
# Change Detection
# =============================================================================


def get_uncommitted_changes(repo_root: str) -> dict:
    """Get summary of uncommitted changes in repo."""
    changes = {"modified": [], "added": [], "deleted": [], "renamed": [], "untracked": []}

    code, stdout, _ = _run_git(["status", "--porcelain"], repo_root)
    if code != 0 or not stdout:
        return changes

    for line in stdout.split("\n"):
        if len(line) < 3:
            continue
        status = line[:2]
        filepath = line[3:].split(" -> ")[-1]

        if status == "??":
            changes["untracked"].append(filepath)
        elif status in ("A ", " A", "AM"):
            changes["added"].append(filepath)
        elif status in (" D", "D ", "AD"):
            changes["deleted"].append(filepath)
        elif status in ("R ", " R", "RM"):
            changes["renamed"].append(filepath)
        else:
            changes["modified"].append(filepath)

    return changes


def _is_scratch_file(filepath: str, repo_root: str) -> bool:
    """Check if file is scratch that shouldn't be committed."""
    # General scratch patterns
    for pattern in SCRATCH_PATTERNS:
        if re.search(pattern, filepath):
            return True

    # Framework-specific scratch
    if is_framework_repo(repo_root):
        for pattern in FRAMEWORK_SCRATCH:
            if re.search(pattern, filepath):
                return True

    return False


def filter_real_changes(changes: dict, repo_root: str) -> dict:
    """Filter out scratch files from changes."""
    return {
        key: [f for f in files if not _is_scratch_file(f, repo_root)]
        for key, files in changes.items()
    }


def count_real_changes(changes: dict, repo_root: str) -> int:
    """Count number of real (non-scratch) changed files."""
    real = filter_real_changes(changes, repo_root)
    return sum(len(files) for files in real.values())


def has_uncommitted_changes(repo_root: str) -> bool:
    """Quick check if repo has any uncommitted changes."""
    changes = get_uncommitted_changes(repo_root)
    return count_real_changes(changes, repo_root) > 0


# =============================================================================
# Commit Message Generation
# =============================================================================


def _categorize_files(files: list[str], repo_root: str) -> dict[str, list[str]]:
    """Categorize files by type for commit message generation."""
    is_framework = is_framework_repo(repo_root)

    if is_framework:
        categories = {
            "hooks": [],
            "lib": [],
            "ops": [],
            "commands": [],
            "rules": [],
            "config": [],
            "memory": [],
            "serena": [],
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
            elif ".serena/" in f:
                categories["serena"].append(f)
            elif "/memory/" in f or f.startswith("memory/"):
                categories["memory"].append(f)
            elif "config" in f.lower() or f.endswith(".json") or f.endswith(".yaml"):
                categories["config"].append(f)
            else:
                categories["other"].append(f)
    else:
        # Project repo - simpler categorization
        categories = {
            "src": [],
            "tests": [],
            "config": [],
            "docs": [],
            "other": [],
        }

        for f in files:
            if re.search(r"test[s]?/|_test\.|\.test\.|\.spec\.", f):
                categories["tests"].append(f)
            elif f.startswith("src/") or "/src/" in f:
                categories["src"].append(f)
            elif re.search(r"\.md$|docs?/|README", f, re.I):
                categories["docs"].append(f)
            elif re.search(r"config|\.json$|\.yaml$|\.yml$|\.toml$", f):
                categories["config"].append(f)
            else:
                categories["other"].append(f)

    return {k: v for k, v in categories.items() if v}


def generate_commit_message(
    changes: dict,
    repo_root: str,
    trigger: str,
    bead_title: str | None = None,
) -> str:
    """Generate a semantic commit message.

    Args:
        changes: Dict with modified/added/deleted/renamed/untracked lists
        repo_root: Path to repo root
        trigger: What triggered the commit (bead_close, test_pass, build_success, session_end)
        bead_title: Optional bead title for bead_close commits
    """
    all_files = (
        changes["modified"] + changes["added"] + changes["deleted"] +
        changes["renamed"] + changes.get("untracked", [])
    )
    real_files = [f for f in all_files if not _is_scratch_file(f, repo_root)]

    if not real_files:
        return ""

    # Bead close - use bead title as basis
    if trigger == "bead_close" and bead_title:
        msg = bead_title.strip()
        # Ensure it has a prefix
        if not re.match(r"^(feat|fix|refactor|chore|docs|test|style)(\(.+\))?:", msg, re.I):
            lower = msg.lower()
            if any(w in lower for w in ["fix", "bug", "error", "issue"]):
                prefix = "fix"
            elif any(w in lower for w in ["add", "new", "implement", "feature", "create"]):
                prefix = "feat"
            elif any(w in lower for w in ["refactor", "clean", "improve", "update"]):
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
    categories = _categorize_files(real_files, repo_root)
    is_framework = is_framework_repo(repo_root)

    # Build summary
    parts = []
    for name, files in categories.items():
        if files and name != "other":
            parts.append(f"{name} ({len(files)})")
    if categories.get("other"):
        parts.append(f"{len(categories['other'])} other")

    summary = ", ".join(parts) if parts else f"{len(real_files)} files"

    # Determine prefix based on trigger and changes
    if trigger == "test_pass":
        prefix = "test" if categories.get("tests") else "chore"
        trigger_note = "after tests pass"
    elif trigger == "build_success":
        prefix = "chore"
        trigger_note = "after build"
    elif trigger == "session_end":
        prefix = "chore"
        trigger_note = "session checkpoint"
    else:
        prefix = "chore"
        trigger_note = "auto"

    # Stats
    stats = []
    if changes["modified"]:
        stats.append(f"{len(changes['modified'])}M")
    if changes["added"] or changes.get("untracked"):
        added_count = len(changes["added"]) + len(changes.get("untracked", []))
        stats.append(f"{added_count}A")
    if changes["deleted"]:
        stats.append(f"{len(changes['deleted'])}D")

    stats_str = " ".join(stats) if stats else ""

    # Framework vs project message style
    if is_framework:
        return f"{prefix}: Update {summary} [{trigger_note}]\n\n{stats_str}"
    else:
        return f"{prefix}: {summary} [{trigger_note}]\n\n{stats_str}"


# =============================================================================
# Commit State Tracking
# =============================================================================


@dataclass
class CommitState:
    """Tracks commit-related state within a session."""

    # Per-repo tracking: repo_root -> last_commit_turn
    repo_last_commit: dict = field(default_factory=dict)

    # Last bead closed (for message generation)
    last_bead_closed: str = ""
    last_bead_closed_turn: int = 0


_commit_state = CommitState()


def get_commit_state() -> CommitState:
    """Get current commit state."""
    return _commit_state


def reset_commit_state() -> None:
    """Reset commit state for new session."""
    global _commit_state
    _commit_state = CommitState()


def track_bead_close(bead_title: str, turn: int) -> None:
    """Track that a bead was closed."""
    state = get_commit_state()
    state.last_bead_closed = bead_title
    state.last_bead_closed_turn = turn


def track_commit(repo_root: str, turn: int) -> None:
    """Track that a commit happened."""
    state = get_commit_state()
    state.repo_last_commit[repo_root] = turn


def is_in_cooldown(repo_root: str, current_turn: int) -> bool:
    """Check if repo is in commit cooldown."""
    state = get_commit_state()
    last_turn = state.repo_last_commit.get(repo_root, 0)
    return (current_turn - last_turn) < COMMIT_COOLDOWN_TURNS


# =============================================================================
# Core Commit Logic
# =============================================================================


@dataclass
class CommitResult:
    """Result of a commit attempt."""

    success: bool
    message: str  # Success: "hash: message" / Failure: error message
    repo_root: str
    files_committed: int = 0


def do_commit(
    repo_root: str,
    trigger: str,
    turn: int,
    bead_title: str | None = None,
) -> CommitResult:
    """Execute a commit on the specified repo.

    Args:
        repo_root: Path to repo root
        trigger: What triggered the commit
        turn: Current turn count
        bead_title: Optional bead title for message generation

    Returns:
        CommitResult with success status and message
    """
    # Get changes
    changes = get_uncommitted_changes(repo_root)
    real_count = count_real_changes(changes, repo_root)

    if real_count == 0:
        return CommitResult(
            success=True,
            message="no changes to commit",
            repo_root=repo_root,
        )

    # Generate message
    message = generate_commit_message(changes, repo_root, trigger, bead_title)
    if not message:
        return CommitResult(
            success=False,
            message="failed to generate commit message",
            repo_root=repo_root,
        )

    # Stage all changes (including untracked)
    code, _, stderr = _run_git(["add", "-A"], repo_root)
    if code != 0:
        return CommitResult(
            success=False,
            message=f"git add failed: {stderr}",
            repo_root=repo_root,
        )

    # Commit
    code, stdout, stderr = _run_git(["commit", "-m", message], repo_root)
    if code != 0:
        # Check if it's just "nothing to commit"
        if "nothing to commit" in stderr or "nothing to commit" in stdout:
            return CommitResult(
                success=True,
                message="nothing to commit",
                repo_root=repo_root,
            )
        return CommitResult(
            success=False,
            message=f"git commit failed: {stderr}",
            repo_root=repo_root,
        )

    # Extract commit hash
    hash_match = re.search(r"\[[\w-]+\s+([a-f0-9]{7,})\]", stdout)
    commit_hash = hash_match.group(1) if hash_match else "unknown"

    # Track the commit
    track_commit(repo_root, turn)

    # First line of message for display
    msg_first_line = message.split("\n")[0][:50]

    return CommitResult(
        success=True,
        message=f"{commit_hash}: {msg_first_line}",
        repo_root=repo_root,
        files_committed=real_count,
    )


def commit_all_repos(trigger: str, turn: int) -> list[CommitResult]:
    """Commit all repos with uncommitted changes.

    Used at session end to ensure nothing is left uncommitted.
    """
    results = []

    for repo_root in get_all_active_repos():
        if has_uncommitted_changes(repo_root):
            # Skip cooldown for session_end - must commit everything
            if trigger != "session_end" and is_in_cooldown(repo_root, turn):
                continue

            result = do_commit(repo_root, trigger, turn)
            results.append(result)

    return results


def should_auto_commit(
    repo_root: str,
    trigger: str,
    turn: int,
) -> tuple[bool, str]:
    """Decide if auto-commit should happen.

    Returns:
        (should_commit, reason)
    """
    # No changes = no commit
    if not has_uncommitted_changes(repo_root):
        return False, "no changes"

    # Cooldown check (except session_end which must commit)
    if trigger != "session_end" and is_in_cooldown(repo_root, turn):
        return False, "cooldown"

    return True, f"trigger: {trigger}"


# =============================================================================
# Helper for displaying results
# =============================================================================


def format_commit_result(result: CommitResult) -> str:
    """Format a commit result for display."""
    repo_name = Path(result.repo_root).name

    if not result.success:
        return f"  {repo_name}: {result.message}"

    if "no changes" in result.message or "nothing to commit" in result.message:
        return f"  {repo_name}: (no changes)"

    return f"  {repo_name}: {result.message} ({result.files_committed} files)"


def format_commit_results(results: list[CommitResult]) -> str:
    """Format multiple commit results for display."""
    if not results:
        return "No repos with uncommitted changes"

    lines = []
    successes = [r for r in results if r.success and "no changes" not in r.message]
    failures = [r for r in results if not r.success]

    if successes:
        lines.append("Committed:")
        for r in successes:
            lines.append(format_commit_result(r))

    if failures:
        lines.append("Failed:")
        for r in failures:
            lines.append(format_commit_result(r))

    return "\n".join(lines)
