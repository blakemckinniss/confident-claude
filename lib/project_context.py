"""
Project Context Detection

Detects which project we're in based on directory markers.
All beads/assignment operations use this to find project-local storage.

Detection order:
1. $CLAUDE_PROJECT_ROOT env var (explicit override)
2. Walk up from $PWD looking for .beads/ directory
3. Walk up from $PWD looking for CLAUDE.md file
4. Error if nothing found (no global fallback)

Project structure:
    <project_root>/
    ├── CLAUDE.md           # Project marker (optional if .beads/ exists)
    └── .beads/             # Project beads storage (auto-created)
        ├── issues/         # Beads issues
        ├── agent_assignments.jsonl
        └── lifecycle.log
"""

from __future__ import annotations

import os
from pathlib import Path


class ProjectNotFoundError(Exception):
    """Raised when no project context can be determined."""

    pass


def find_project_root(start_path: Path | str | None = None) -> Path:
    """
    Find the project root by walking up from start_path.

    Args:
        start_path: Starting directory (defaults to $PWD)

    Returns:
        Path to project root

    Raises:
        ProjectNotFoundError: If no project markers found
    """
    # Check explicit override first
    override = os.environ.get("CLAUDE_PROJECT_ROOT")
    if override:
        root = Path(override).resolve()
        if root.is_dir():
            return root

    # Start from provided path or cwd
    if start_path is None:
        start_path = Path.cwd()
    else:
        start_path = Path(start_path).resolve()

    current = start_path

    # Walk up looking for markers
    while current != current.parent:
        # Check for .beads/ directory (strongest signal)
        if (current / ".beads").is_dir():
            return current

        # Check for CLAUDE.md file
        if (current / "CLAUDE.md").is_file():
            return current

        # Don't go above home directory
        if current == Path.home():
            break

        current = current.parent

    # Special case: if we're in ~/.claude itself, that's a project
    home_claude = Path.home() / ".claude"
    if start_path == home_claude or home_claude in start_path.parents:
        return home_claude

    raise ProjectNotFoundError(
        f"No project found from {start_path}. "
        "Create CLAUDE.md or .beads/ directory in project root."
    )


def get_beads_dir(project_root: Path | None = None, create: bool = True) -> Path:
    """
    Get the .beads/ directory for a project.

    Args:
        project_root: Project root (auto-detected if None)
        create: Create directory if it doesn't exist

    Returns:
        Path to .beads/ directory
    """
    if project_root is None:
        project_root = find_project_root()

    beads_dir = project_root / ".beads"

    if create and not beads_dir.exists():
        beads_dir.mkdir(parents=True, exist_ok=True)
        # Create issues subdirectory for beads
        (beads_dir / "issues").mkdir(exist_ok=True)

    return beads_dir


def get_assignments_file(project_root: Path | None = None) -> Path:
    """Get path to agent_assignments.jsonl for a project."""
    beads_dir = get_beads_dir(project_root)
    return beads_dir / "agent_assignments.jsonl"


def get_lifecycle_log(project_root: Path | None = None) -> Path:
    """Get path to lifecycle.log for a project."""
    beads_dir = get_beads_dir(project_root)
    return beads_dir / "lifecycle.log"


def get_project_name(project_root: Path | None = None) -> str:
    """Get a human-readable project name."""
    if project_root is None:
        project_root = find_project_root()

    # Use directory name
    if project_root == Path.home() / ".claude":
        return "claude-framework"

    return project_root.name


def ensure_project_beads(project_root: Path | None = None) -> Path:
    """
    Ensure .beads/ directory exists for project.

    Returns:
        Path to .beads/ directory
    """
    if project_root is None:
        project_root = find_project_root()

    beads_dir = project_root / ".beads"
    beads_dir.mkdir(parents=True, exist_ok=True)
    (beads_dir / "issues").mkdir(exist_ok=True)

    return beads_dir


def is_in_project() -> bool:
    """Check if currently in a project context."""
    try:
        find_project_root()
        return True
    except ProjectNotFoundError:
        return False


def get_all_project_roots() -> list[Path]:
    """
    Discover all projects with .beads/ directories.

    Scans:
    - ~/projects/*/
    - ~/ai/*/
    - ~/.claude/

    Returns:
        List of project root paths
    """
    roots = []
    home = Path.home()

    # Check known project directories
    for base in [home / "projects", home / "ai"]:
        if base.is_dir():
            for child in base.iterdir():
                if child.is_dir() and (child / ".beads").is_dir():
                    roots.append(child)

    # Always include framework itself
    if (home / ".claude" / ".beads").is_dir():
        roots.append(home / ".claude")

    return sorted(roots)
