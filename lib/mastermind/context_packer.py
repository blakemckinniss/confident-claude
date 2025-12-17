"""Structured context packer for mastermind routing and planning.

Packs context with strict token budgets:
- Router: 1200 tokens (fast classification)
- Planner: 4000 tokens (detailed blueprint)

Includes: repo structure, git diff, beads, test status, serena context.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import get_config


def estimate_tokens(text: str) -> int:
    """Rough token estimate (4 chars per token average)."""
    return len(text) // 4


def truncate_to_budget(text: str, budget: int) -> str:
    """Truncate text to fit within token budget."""
    estimated = estimate_tokens(text)
    if estimated <= budget:
        return text
    # Truncate with buffer for "..." indicator
    char_limit = (budget - 10) * 4
    return text[:char_limit] + "\n... [truncated]"


@dataclass
class PackedContext:
    """Packed context ready for router or planner."""
    prompt: str
    sections: dict[str, str]
    token_estimate: int
    budget: int
    truncated: bool


def get_repo_structure(cwd: Path, max_depth: int = 2) -> str:
    """Get repository structure via tree or ls."""
    try:
        result = subprocess.run(
            ["tree", "-L", str(max_depth), "--noreport", "-I", "node_modules|__pycache__|.git|.venv"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout[:2000]
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    # Fallback to ls
    try:
        result = subprocess.run(
            ["ls", "-la"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.stdout[:1000]
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return "[repo structure unavailable]"


def get_git_diff(cwd: Path, max_lines: int = 100) -> str:
    """Get current git diff (staged + unstaged)."""
    try:
        result = subprocess.run(
            ["git", "diff", "HEAD", "--stat"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            lines = result.stdout.strip().split("\n")
            if len(lines) > max_lines:
                return "\n".join(lines[:max_lines]) + f"\n... [{len(lines) - max_lines} more files]"
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return "[no changes]"


def get_beads_summary(max_items: int = 5) -> str:
    """Get summary of open beads."""
    try:
        result = subprocess.run(
            ["bd", "list", "--status=open"],
            capture_output=True,
            text=True,
            timeout=5,
            env={"BEADS_DIR": str(Path.home() / ".beads"), **subprocess.os.environ},
        )
        if result.returncode == 0 and result.stdout.strip():
            lines = result.stdout.strip().split("\n")
            if len(lines) > max_items + 2:  # header + items
                return "\n".join(lines[:max_items + 2]) + f"\n... [{len(lines) - max_items - 2} more]"
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return "[no beads]"


def get_test_status(cwd: Path) -> str:
    """Get recent test status if available."""
    # Check for common test result files
    for pattern in ["pytest.xml", "test-results.xml", ".pytest_cache"]:
        if (cwd / pattern).exists():
            return "[tests configured]"

    # Check package.json for test script
    pkg_json = cwd / "package.json"
    if pkg_json.exists():
        return "[npm tests available]"

    return "[no test info]"


def pack_for_router(user_prompt: str, cwd: Path | None = None) -> PackedContext:
    """Pack minimal context for router classification (1200 token budget).

    Focus on: user prompt, repo type, basic structure.
    """
    config = get_config()
    budget = config.context_packer.router_token_budget
    cwd = cwd or Path.cwd()

    sections: dict[str, str] = {}

    # User prompt is highest priority
    sections["prompt"] = user_prompt

    # Repo type detection
    repo_type = "unknown"
    if (cwd / "package.json").exists():
        repo_type = "node/javascript"
    elif (cwd / "pyproject.toml").exists() or (cwd / "setup.py").exists():
        repo_type = "python"
    elif (cwd / "Cargo.toml").exists():
        repo_type = "rust"
    elif (cwd / "go.mod").exists():
        repo_type = "go"
    sections["repo_type"] = repo_type

    # Compact structure (only if budget allows)
    if config.context_packer.include_repo_structure:
        sections["structure"] = get_repo_structure(cwd, max_depth=1)[:500]

    # Build packed prompt
    packed = f"""## User Request
{sections['prompt']}

## Repository
Type: {sections['repo_type']}
"""

    if "structure" in sections:
        packed += f"\n## Structure (top-level)\n{sections['structure']}\n"

    # Check budget and truncate if needed
    token_est = estimate_tokens(packed)
    truncated = token_est > budget
    if truncated:
        packed = truncate_to_budget(packed, budget)
        token_est = budget

    return PackedContext(
        prompt=packed,
        sections=sections,
        token_estimate=token_est,
        budget=budget,
        truncated=truncated,
    )


def pack_for_planner(
    user_prompt: str,
    routing_decision: dict[str, Any],
    cwd: Path | None = None,
) -> PackedContext:
    """Pack full context for planner blueprint generation (4000 token budget).

    Includes: user prompt, routing info, repo structure, git diff, beads, tests.
    """
    config = get_config()
    budget = config.context_packer.planner_token_budget
    cwd = cwd or Path.cwd()

    sections: dict[str, str] = {}

    # Core sections
    sections["prompt"] = user_prompt
    sections["routing"] = f"Classification: {routing_decision.get('classification', 'complex')}\nReason: {', '.join(routing_decision.get('reason_codes', []))}"

    # Repository context
    if config.context_packer.include_repo_structure:
        sections["structure"] = get_repo_structure(cwd, max_depth=2)

    if config.context_packer.include_git_diff:
        sections["diff"] = get_git_diff(cwd)

    if config.context_packer.include_beads:
        sections["beads"] = get_beads_summary()

    if config.context_packer.include_test_status:
        sections["tests"] = get_test_status(cwd)

    # Build packed prompt
    packed = f"""## User Request
{sections['prompt']}

## Router Classification
{sections['routing']}

## Repository Structure
{sections.get('structure', '[unavailable]')}

## Current Changes
{sections.get('diff', '[none]')}

## Open Tasks (Beads)
{sections.get('beads', '[none]')}

## Test Status
{sections.get('tests', '[unknown]')}
"""

    # Check budget and truncate if needed
    token_est = estimate_tokens(packed)
    truncated = token_est > budget
    if truncated:
        packed = truncate_to_budget(packed, budget)
        token_est = budget

    return PackedContext(
        prompt=packed,
        sections=sections,
        token_estimate=token_est,
        budget=budget,
        truncated=truncated,
    )
