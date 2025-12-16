#!/usr/bin/env python3
"""
New Project Scaffolding

Creates a fully-integrated project with:
- .beads/ directory (task tracking)
- .claude/ directory (project commands/settings)
- .serena/ directory (semantic code analysis)
- CLAUDE.md (project instructions)

Validates Integration Synergy E2E by wiring up all components.

Usage:
    new_project.py <name> [--template minimal|full] [--description DESC]
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path

PROJECTS_DIR = Path.home() / "projects"


def create_beads_structure(project_root: Path) -> None:
    """Create .beads/ directory structure."""
    beads_dir = project_root / ".beads"
    beads_dir.mkdir(exist_ok=True)
    (beads_dir / "issues").mkdir(exist_ok=True)

    # Create empty agent assignments file
    (beads_dir / "agent_assignments.jsonl").touch()

    # Create .gitignore for beads
    gitignore = beads_dir / ".gitignore"
    gitignore.write_text(
        """# Beads local state
agent_assignments.jsonl
lifecycle.log
*.db
*.db-journal
"""
    )


def create_claude_structure(project_root: Path, name: str) -> None:
    """Create .claude/ directory for project-local settings."""
    claude_dir = project_root / ".claude"
    claude_dir.mkdir(exist_ok=True)

    # Commands directory
    commands_dir = claude_dir / "commands"
    commands_dir.mkdir(exist_ok=True)

    # Create a sample project command
    sample_cmd = commands_dir / "status.md"
    sample_cmd.write_text(
        f"""---
description: 📊 Project status - beads, git, and health check
allowed-tools: Bash, Read
---

# {name} Project Status

Show current project state:

```bash
echo "=== {name} Status ==="
echo ""
echo "Git:"
git -C {project_root} status --short 2>/dev/null || echo "  Not a git repo"
echo ""
echo "Beads:"
bd list --status=in_progress 2>/dev/null || echo "  No active beads"
echo ""
echo "Ready work:"
bd ready 2>/dev/null | head -5 || echo "  No ready beads"
```
"""
    )

    # Settings directory
    settings_dir = claude_dir / "settings"
    settings_dir.mkdir(exist_ok=True)

    # Create .gitignore
    gitignore = claude_dir / ".gitignore"
    gitignore.write_text(
        """# Local settings
settings/local.json
*.local.*
"""
    )


def create_serena_structure(project_root: Path, name: str, description: str) -> None:
    """Create .serena/ directory for semantic analysis."""
    serena_dir = project_root / ".serena"
    serena_dir.mkdir(exist_ok=True)

    # Memories directory
    memories_dir = serena_dir / "memories"
    memories_dir.mkdir(exist_ok=True)

    # Create initial memory
    initial_memory = memories_dir / "project_overview.md"
    initial_memory.write_text(
        f"""# {name} - Project Overview

## Description
{description or "A new project created with Integration Synergy scaffolding."}

## Created
{datetime.now().strftime("%Y-%m-%d")}

## Architecture
TODO: Document key architectural decisions here.

## Key Files
TODO: List important files and their purposes.

## Conventions
TODO: Document coding conventions and patterns.
"""
    )

    # Create config
    config = serena_dir / "config.yaml"
    config.write_text(
        f"""# Serena configuration for {name}
project_name: {name}
language_servers: []
"""
    )


def create_claude_md(project_root: Path, name: str, description: str) -> None:
    """Create project CLAUDE.md file."""
    claude_md = project_root / "CLAUDE.md"
    claude_md.write_text(
        f"""# {name} - Project Instructions

> **First Action:** Activate Serena MCP for this project:
> ```
> mcp__serena__activate_project("{name}")
> ```
> This enables symbolic code tools and project-specific memories.

{description or "A new project."}

## Tech Stack

| Layer | Technology |
|-------|------------|
| Language | TODO |
| Framework | TODO |
| Testing | TODO |

## Architecture

```
{name}/
├── CLAUDE.md           # This file
├── .beads/             # Task tracking (bd CLI)
├── .claude/            # Project-local commands
│   └── commands/       # Slash commands
├── .serena/            # Semantic analysis
│   └── memories/       # Project knowledge
└── src/                # Source code
```

## Quick Start

```bash
# Check project status
/status

# See available work
bd ready

# Create a task
bd create --title="Implement feature X" --type=task
```

## Conventions

- Use beads (`bd`) for task tracking
- Document decisions in `.serena/memories/`
- Keep CLAUDE.md updated with architecture changes

## Integration Features

This project is set up with Integration Synergy:
- **Beads**: Task tracking with `bd` CLI
- **Serena**: Semantic code analysis via MCP
- **Project isolation**: Local .beads/agent_assignments.jsonl
- **Slash commands**: Project-specific commands in .claude/commands/
"""
    )


def create_src_structure(project_root: Path, template: str) -> None:
    """Create basic source structure."""
    src_dir = project_root / "src"
    src_dir.mkdir(exist_ok=True)

    if template == "full":
        # Create more directories
        (src_dir / "lib").mkdir(exist_ok=True)
        (src_dir / "tests").mkdir(exist_ok=True)

        # Create placeholder files
        (src_dir / "__init__.py").touch()
        (src_dir / "lib" / "__init__.py").touch()
        (src_dir / "tests" / "__init__.py").touch()


def init_git(project_root: Path) -> bool:
    """Initialize git repository."""
    try:
        subprocess.run(
            ["git", "init"],
            cwd=project_root,
            capture_output=True,
            check=True,
        )

        # Create .gitignore
        gitignore = project_root / ".gitignore"
        gitignore.write_text(
            """# Python
__pycache__/
*.py[cod]
*.egg-info/
.eggs/
dist/
build/
.venv/
venv/

# IDE
.idea/
.vscode/
*.swp
*.swo

# OS
.DS_Store
Thumbs.db

# Project
*.log
*.local.*
"""
        )

        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def create_initial_bead(project_root: Path, name: str) -> bool:
    """Create initial setup bead."""
    try:
        result = subprocess.run(
            [
                "bd",
                "create",
                f"--title=Initial setup for {name}",
                "--type=task",
            ],
            cwd=project_root,
            capture_output=True,
            text=True,
        )
        return result.returncode == 0
    except FileNotFoundError:
        return False


def verify_project(project_root: Path) -> dict:
    """Verify project structure is complete."""
    checks = {
        ".beads/": (project_root / ".beads").is_dir(),
        ".beads/issues/": (project_root / ".beads" / "issues").is_dir(),
        ".beads/agent_assignments.jsonl": (
            project_root / ".beads" / "agent_assignments.jsonl"
        ).exists(),
        ".claude/": (project_root / ".claude").is_dir(),
        ".claude/commands/": (project_root / ".claude" / "commands").is_dir(),
        ".serena/": (project_root / ".serena").is_dir(),
        ".serena/memories/": (project_root / ".serena" / "memories").is_dir(),
        "CLAUDE.md": (project_root / "CLAUDE.md").exists(),
        "src/": (project_root / "src").is_dir(),
        ".git/": (project_root / ".git").is_dir(),
    }
    return checks


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a new integrated project")
    parser.add_argument("name", help="Project name (will be created in ~/projects/)")
    parser.add_argument(
        "--template",
        "-t",
        choices=["minimal", "full"],
        default="minimal",
        help="Project template",
    )
    parser.add_argument("--description", "-d", help="Project description")

    args = parser.parse_args()

    name = args.name.lower().replace(" ", "-")
    project_root = PROJECTS_DIR / name

    # Check if already exists
    if project_root.exists():
        print(f"❌ Project already exists: {project_root}")
        return 1

    print(f"Creating project: {name}")
    print(f"Location: {project_root}")
    print(f"Template: {args.template}")
    print()

    # Create project root
    project_root.mkdir(parents=True)

    # Create all structures
    print("Creating .beads/ structure...")
    create_beads_structure(project_root)

    print("Creating .claude/ structure...")
    create_claude_structure(project_root, name)

    print("Creating .serena/ structure...")
    create_serena_structure(project_root, name, args.description or "")

    print("Creating CLAUDE.md...")
    create_claude_md(project_root, name, args.description or "")

    print("Creating src/ structure...")
    create_src_structure(project_root, args.template)

    print("Initializing git...")
    if init_git(project_root):
        print("  ✅ Git initialized")
    else:
        print("  ⚠️  Git init failed (optional)")

    print("Creating initial bead...")
    if create_initial_bead(project_root, name):
        print("  ✅ Initial bead created")
    else:
        print("  ⚠️  Bead creation failed (bd CLI issue)")

    print()

    # Verify
    print("Verifying project structure...")
    checks = verify_project(project_root)
    all_ok = True
    for item, ok in checks.items():
        status = "✅" if ok else "❌"
        print(f"  {status} {item}")
        if not ok:
            all_ok = False

    print()
    print("=" * 50)

    if all_ok:
        print(f"✅ Project '{name}' created successfully!")
        print()
        print("Next steps:")
        print(f"  cd {project_root}")
        print(f'  mcp__serena__activate_project("{name}")')
        print("  bd ready")
        return 0
    else:
        print(f"⚠️  Project '{name}' created with warnings")
        return 1


if __name__ == "__main__":
    sys.exit(main())
