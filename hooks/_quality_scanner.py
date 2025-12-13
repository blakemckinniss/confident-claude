#!/usr/bin/env python3
"""
Code Quality Scanner using rule-based tools (ruff, radon).

Fast, reliable, and actionable - no ML model loading required.
Detects:
- Lint issues (ruff): style, imports, potential bugs
- Complexity issues (radon): functions too complex, low maintainability
"""

from __future__ import annotations

import subprocess
import json
from pathlib import Path
from typing import Optional


def scan_file(file_path: str, complexity_threshold: str = "C") -> Optional[dict]:
    """
    Scan a Python file for quality issues.

    Args:
        file_path: Path to Python file
        complexity_threshold: Min complexity grade to report (A-F, default C)

    Returns:
        Dict with 'issues', 'complexity', 'recommendations' or None if clean
    """
    path = Path(file_path)
    if not path.exists() or path.suffix != ".py":
        return None

    issues = []
    recommendations = []

    # Run ruff for lint issues
    ruff_issues = _run_ruff(file_path)
    if ruff_issues:
        issues.extend(ruff_issues)
        recommendations.append("🔧 Run `ruff check --fix` to auto-fix style issues")

    # Run radon for complexity
    complexity = _run_radon_cc(file_path, complexity_threshold)
    if complexity:
        issues.extend(complexity)
        recommendations.append(
            "🧩 Consider breaking complex functions into smaller pieces"
        )

    # Run radon for maintainability index
    mi_issues = _run_radon_mi(file_path)
    if mi_issues:
        issues.extend(mi_issues)

    if not issues:
        return None

    return {
        "file": file_path,
        "issue_count": len(issues),
        "issues": issues[:5],  # Limit to top 5
        "recommendations": recommendations,
    }


def scan_code(code: str, complexity_threshold: str = "C") -> Optional[dict]:
    """
    Scan code string for quality issues (writes to temp file).

    Args:
        code: Python source code
        complexity_threshold: Min complexity grade to report

    Returns:
        Dict with issues or None if clean
    """
    if not code or len(code.strip()) < 20:
        return None

    # Write to temp file for analysis
    import tempfile

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(code)
        temp_path = f.name

    try:
        result = scan_file(temp_path, complexity_threshold)
        if result:
            result["file"] = "<code>"
        return result
    finally:
        Path(temp_path).unlink(missing_ok=True)


def _run_ruff(file_path: str) -> list[dict]:
    """Run ruff check and return issues."""
    try:
        result = subprocess.run(
            ["ruff", "check", "--output-format=json", file_path],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.stdout:
            data = json.loads(result.stdout)
            return [
                {
                    "type": "lint",
                    "code": item.get("code", ""),
                    "message": item.get("message", ""),
                    "line": item.get("location", {}).get("row", 0),
                    "severity": _ruff_severity(item.get("code", "")),
                }
                for item in data[:10]  # Limit
            ]
    except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError):
        pass
    return []


def _run_radon_cc(file_path: str, min_grade: str = "C") -> list[dict]:
    """Run radon cyclomatic complexity check."""
    try:
        result = subprocess.run(
            ["radon", "cc", "-j", "-n", min_grade, file_path],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.stdout:
            data = json.loads(result.stdout)
            issues = []
            for path, blocks in data.items():
                for block in blocks:
                    issues.append(
                        {
                            "type": "complexity",
                            "name": block.get("name", ""),
                            "complexity": block.get("complexity", 0),
                            "rank": block.get("rank", ""),
                            "line": block.get("lineno", 0),
                            "message": f"{block.get('name')} has complexity {block.get('complexity')} (rank {block.get('rank')})",
                            "severity": _complexity_severity(block.get("rank", "A")),
                        }
                    )
            return issues
    except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError):
        pass
    return []


def _run_radon_mi(file_path: str, threshold: float = 50.0) -> list[dict]:
    """Run radon maintainability index check."""
    try:
        result = subprocess.run(
            ["radon", "mi", "-j", file_path],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.stdout:
            data = json.loads(result.stdout)
            issues = []
            for path, info in data.items():
                mi = info.get("mi", 100)
                rank = info.get("rank", "A")
                if mi < threshold or rank in ("C", "D", "E", "F"):
                    issues.append(
                        {
                            "type": "maintainability",
                            "mi_score": round(mi, 1),
                            "rank": rank,
                            "message": f"Maintainability index {round(mi, 1)} (rank {rank}) - consider refactoring",
                            "severity": _mi_severity(rank),
                        }
                    )
            return issues
    except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError):
        pass
    return []


def _ruff_severity(code: str) -> str:
    """Map ruff code to severity."""
    if code.startswith(("E9", "F")):  # Syntax errors, critical
        return "high"
    if code.startswith(("E", "W")):  # Style
        return "low"
    if code.startswith(("C", "B")):  # Complexity, bugbear
        return "medium"
    return "low"


def _complexity_severity(rank: str) -> str:
    """Map complexity rank to severity."""
    return {
        "A": "low",
        "B": "low",
        "C": "medium",
        "D": "high",
        "E": "high",
        "F": "critical",
    }.get(rank, "medium")


def _mi_severity(rank: str) -> str:
    """Map maintainability rank to severity."""
    return {"A": "low", "B": "medium", "C": "high"}.get(rank, "high")


def format_report(result: dict) -> str:
    """Format scan result as readable report."""
    if not result:
        return ""

    lines = [f"📊 **Code Quality**: {result['issue_count']} issues in {result['file']}"]

    for issue in result.get("issues", []):
        severity_icon = {
            "low": "🔵",
            "medium": "🟡",
            "high": "🟠",
            "critical": "🔴",
        }.get(issue.get("severity", ""), "⚪")
        if issue["type"] == "lint":
            lines.append(
                f"  {severity_icon} L{issue['line']}: [{issue['code']}] {issue['message']}"
            )
        elif issue["type"] == "complexity":
            lines.append(f"  {severity_icon} L{issue['line']}: {issue['message']}")
        elif issue["type"] == "maintainability":
            lines.append(f"  {severity_icon} {issue['message']}")

    for rec in result.get("recommendations", []):
        lines.append(f"  {rec}")

    return "\n".join(lines)
