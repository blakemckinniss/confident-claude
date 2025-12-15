#!/usr/bin/env python3
"""
Dependency Checker v1.1: Validates all .claude dependencies at session start.

Checks:
1. Required API keys (for external services)
2. Python packages (from requirements.txt)
3. External binaries (git, ruff, bd, node, npm, etc.)
4. Critical directories and files
5. Node.js/npm for MCP servers and frontend workflows
6. MCP server dependencies

Features:
- Fast (<500ms total)
- Non-blocking (warnings only, never fails session)
- Comprehensive (catches missing deps before cryptic failures)
- Auto-fix mode (--fix to install missing Python packages)
"""

import os
import sys
import shutil
import subprocess
import importlib.util
from pathlib import Path

# =============================================================================
# CONFIGURATION
# =============================================================================

# API keys and their purposes (for clear error messages)
API_KEYS = {
    "OPENROUTER_API_KEY": {
        "required": False,  # Not required for basic operation
        "used_by": ["think.py", "oracle.py", "council.py", "gaps.py", "void.py", "drift.py", "scope.py"],
        "purpose": "External LLM consultation (OpenRouter)",
    },
    "TAVILY_API_KEY": {
        "required": False,
        "used_by": ["research.py"],
        "purpose": "Web search via Tavily",
    },
    "ANTHROPIC_API_KEY": {
        "required": False,
        "used_by": ["orchestrate.py"],
        "purpose": "Claude API code execution",
    },
    "GROQ_API_KEY": {
        "required": False,
        "used_by": ["groq.py"],
        "purpose": "Fast inference via Groq",
    },
    "FIRECRAWL_API_KEY": {
        "required": False,
        "used_by": ["firecrawl.py"],
        "purpose": "Web scraping via Firecrawl",
    },
    "CONTEXT7_API_KEY": {
        "required": False,
        "used_by": ["docs.py"],
        "purpose": "Documentation lookup via Context7",
    },
}

# External binaries (name -> info)
BINARIES = {
    "git": {
        "required": True,
        "used_by": ["version control", "scope.py", "coderabbit.py"],
    },
    "ruff": {
        "required": True,
        "used_by": ["code linting", "audit.py"],
        "install_hint": "pip install ruff",
    },
    "bd": {
        "required": False,
        "used_by": ["beads task tracking"],
        "install_hint": "pip install beads-cli or check ~/.local/bin",
    },
    "python3": {
        "required": True,
        "used_by": ["hook execution"],
    },
    "node": {
        "required": False,
        "used_by": ["MCP servers", "frontend workflows"],
        "install_hint": "Install Node.js from https://nodejs.org or via nvm",
    },
    "npm": {
        "required": False,
        "used_by": ["MCP servers", "package management"],
        "install_hint": "Comes with Node.js installation",
    },
}

# Python packages to check (module_name -> package_name if different)
# Only checking critical ones - full list in requirements.txt
PYTHON_PACKAGES = {
    "requests": None,
    "pydantic": None,
    "yaml": "pyyaml",
    "dotenv": "python-dotenv",
    "rapidfuzz": None,
    "websockets": None,  # For bdg.py CDP
}

# Critical paths that must exist
CRITICAL_PATHS = {
    "~/.claude/hooks": "Hook scripts",
    "~/.claude/ops": "Ops scripts",
    "~/.claude/lib": "Library modules",
    "~/.claude/memory": "Memory storage",
    "~/.claude/.venv": "Python virtual environment",
}

# MCP servers that require npm packages (server_name -> npm_package)
MCP_SERVERS = {
    "repomix-mcp": {
        "package": "repomix",
        "global": True,
        "required": False,
    },
    "filesystem": {
        "package": "@anthropic/mcp-server-filesystem",
        "global": True,
        "required": False,
    },
}


# =============================================================================
# CHECK FUNCTIONS
# =============================================================================


def check_api_keys() -> list[dict]:
    """Check for missing API keys."""
    issues = []
    for key, info in API_KEYS.items():
        value = os.environ.get(key, "").strip()
        if not value:
            issues.append({
                "type": "api_key",
                "name": key,
                "required": info["required"],
                "purpose": info["purpose"],
                "used_by": info["used_by"],
            })
    return issues


def check_binaries() -> list[dict]:
    """Check for missing external binaries."""
    issues = []
    for name, info in BINARIES.items():
        path = shutil.which(name)
        if not path:
            issue = {
                "type": "binary",
                "name": name,
                "required": info["required"],
                "used_by": info["used_by"],
            }
            if "install_hint" in info:
                issue["hint"] = info["install_hint"]
            issues.append(issue)
    return issues


def check_python_packages() -> list[dict]:
    """Check for missing Python packages."""
    issues = []
    for module_name, package_name in PYTHON_PACKAGES.items():
        spec = importlib.util.find_spec(module_name)
        if spec is None:
            issues.append({
                "type": "python_package",
                "name": module_name,
                "package": package_name or module_name,
                "required": True,
            })
    return issues


def check_critical_paths() -> list[dict]:
    """Check for missing critical directories/files."""
    issues = []
    for path_str, description in CRITICAL_PATHS.items():
        path = Path(path_str).expanduser()
        if not path.exists():
            issues.append({
                "type": "path",
                "name": str(path),
                "description": description,
                "required": True,
            })
    return issues


def check_venv_integrity() -> list[dict]:
    """Check if venv is properly set up."""
    issues = []
    venv_path = Path.home() / ".claude" / ".venv"

    if venv_path.exists():
        python_path = venv_path / "bin" / "python"
        if not python_path.exists():
            issues.append({
                "type": "venv",
                "name": "venv python",
                "description": "Virtual environment exists but python binary missing",
                "required": True,
                "hint": "Run: python3 -m venv ~/.claude/.venv",
            })

        # Check if pip is available
        pip_path = venv_path / "bin" / "pip"
        if not pip_path.exists():
            issues.append({
                "type": "venv",
                "name": "venv pip",
                "description": "Virtual environment missing pip",
                "required": True,
                "hint": "Run: ~/.claude/.venv/bin/python -m ensurepip",
            })

    return issues


def check_node_ecosystem() -> list[dict]:
    """Check Node.js ecosystem health."""
    issues = []

    # Skip if node/npm not installed (already caught by check_binaries)
    if not shutil.which("node") or not shutil.which("npm"):
        return issues

    # Check node version (need 18+ for modern MCP servers)
    try:
        result = subprocess.run(
            ["node", "--version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            version = result.stdout.strip().lstrip("v")
            major = int(version.split(".")[0])
            if major < 18:
                issues.append({
                    "type": "node_version",
                    "name": f"Node.js {version}",
                    "description": f"Node.js {major}.x is outdated, MCP servers need 18+",
                    "required": False,
                    "hint": "Update Node.js to v18 or newer",
                })
    except (subprocess.TimeoutExpired, ValueError, IndexError):
        pass

    return issues


def check_mcp_servers() -> list[dict]:
    """Check MCP server dependencies."""
    issues = []

    # Skip if npm not available
    if not shutil.which("npm"):
        return issues

    for server_name, info in MCP_SERVERS.items():
        package = info["package"]
        is_global = info.get("global", False)

        try:
            # Check if package is installed
            cmd = ["npm", "list", package]
            if is_global:
                cmd.insert(2, "-g")

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=10,
            )

            if result.returncode != 0 and "(empty)" not in result.stdout:
                issues.append({
                    "type": "mcp_server",
                    "name": server_name,
                    "package": package,
                    "required": info.get("required", False),
                    "hint": f"npm install {'-g ' if is_global else ''}{package}",
                })
        except subprocess.TimeoutExpired:
            pass  # Skip slow checks

    return issues


# =============================================================================
# FIX FUNCTIONS
# =============================================================================


def fix_python_packages(issues: list[dict], verbose: bool = False) -> list[dict]:
    """Attempt to install missing Python packages.

    Returns list of issues that couldn't be fixed.
    """
    remaining = []
    pip_path = Path.home() / ".claude" / ".venv" / "bin" / "pip"

    if not pip_path.exists():
        return issues  # Can't fix without pip

    python_issues = [i for i in issues if i["type"] == "python_package"]
    other_issues = [i for i in issues if i["type"] != "python_package"]

    if not python_issues:
        return issues

    # Collect packages to install
    packages = [i["package"] for i in python_issues]

    if verbose:
        print(f"📦 Installing: {', '.join(packages)}")

    try:
        result = subprocess.run(
            [str(pip_path), "install", "-q"] + packages,
            capture_output=True,
            text=True,
            timeout=120,
        )

        if result.returncode == 0:
            if verbose:
                print(f"✅ Installed {len(packages)} packages")
            # Verify installation
            for issue in python_issues:
                spec = importlib.util.find_spec(issue["name"])
                if spec is None:
                    remaining.append(issue)
        else:
            if verbose:
                print(f"❌ pip install failed: {result.stderr[:200]}")
            remaining.extend(python_issues)

    except subprocess.TimeoutExpired:
        if verbose:
            print("⏱️ pip install timed out")
        remaining.extend(python_issues)

    return other_issues + remaining


# =============================================================================
# MAIN CHECK FUNCTION
# =============================================================================


def run_dependency_check(auto_fix: bool = False, verbose: bool = False) -> dict:
    """Run all dependency checks and return results.

    Args:
        auto_fix: If True, attempt to install missing Python packages.
        verbose: If True, print progress messages during fix.

    Returns:
        dict with keys:
            - ok: bool (True if no required deps missing)
            - critical: list of critical issues (required deps missing)
            - warnings: list of warnings (optional deps missing)
            - summary: str (human-readable summary)
            - fixed: int (number of issues fixed, if auto_fix=True)
    """
    all_issues = []

    # Run all checks
    all_issues.extend(check_critical_paths())
    all_issues.extend(check_venv_integrity())
    all_issues.extend(check_binaries())
    all_issues.extend(check_python_packages())
    all_issues.extend(check_node_ecosystem())
    all_issues.extend(check_mcp_servers())
    all_issues.extend(check_api_keys())

    fixed_count = 0

    # Attempt auto-fix if requested
    if auto_fix:
        original_count = len(all_issues)
        all_issues = fix_python_packages(all_issues, verbose=verbose)
        fixed_count = original_count - len(all_issues)

    # Separate critical vs warnings
    critical = [i for i in all_issues if i.get("required", False)]
    warnings = [i for i in all_issues if not i.get("required", False)]

    # Build summary
    summary_parts = []

    if fixed_count > 0:
        summary_parts.append(f"🔧 Fixed {fixed_count} missing packages")

    if critical:
        summary_parts.append(f"🔴 {len(critical)} MISSING (required)")
        for issue in critical[:3]:  # Show first 3
            name = issue.get("name", "unknown")
            hint = issue.get("hint", "")
            if hint:
                summary_parts.append(f"   • {name}: {hint}")
            else:
                summary_parts.append(f"   • {name}")
        if len(critical) > 3:
            summary_parts.append(f"   ... and {len(critical) - 3} more")

    if warnings:
        # Group by type for cleaner output
        api_keys_missing = [w for w in warnings if w["type"] == "api_key"]
        other_warnings = [w for w in warnings if w["type"] != "api_key"]

        if api_keys_missing:
            key_names = [w["name"] for w in api_keys_missing]
            summary_parts.append(f"🟡 API keys not set: {', '.join(key_names[:4])}")
            if len(key_names) > 4:
                summary_parts.append(f"   ... and {len(key_names) - 4} more")

        if other_warnings:
            for issue in other_warnings[:2]:
                summary_parts.append(f"🟡 Optional: {issue.get('name', 'unknown')}")

    if not critical and not warnings:
        summary_parts.append("✅ All dependencies satisfied")
    elif not critical and not summary_parts:
        summary_parts.insert(0, "✅ Core dependencies OK")

    return {
        "ok": len(critical) == 0,
        "critical": critical,
        "warnings": warnings,
        "summary": "\n".join(summary_parts),
        "fixed": fixed_count,
    }


def format_full_report(result: dict) -> str:
    """Format a full dependency report for verbose output."""
    lines = ["=" * 50, "DEPENDENCY CHECK REPORT", "=" * 50, ""]

    if result.get("fixed", 0) > 0:
        lines.append(f"🔧 Auto-fixed {result['fixed']} packages")
        lines.append("")

    if result["critical"]:
        lines.append("🔴 CRITICAL (Required - will cause failures):")
        lines.append("-" * 40)
        for issue in result["critical"]:
            lines.append(f"  [{issue['type']}] {issue['name']}")
            if "description" in issue:
                lines.append(f"      Description: {issue['description']}")
            if "hint" in issue:
                lines.append(f"      Fix: {issue['hint']}")
            if "used_by" in issue:
                used = issue["used_by"]
                if isinstance(used, list):
                    lines.append(f"      Used by: {', '.join(used[:3])}")
        lines.append("")

    if result["warnings"]:
        lines.append("🟡 WARNINGS (Optional - some features disabled):")
        lines.append("-" * 40)
        for issue in result["warnings"]:
            lines.append(f"  [{issue['type']}] {issue['name']}")
            if "purpose" in issue:
                lines.append(f"      Purpose: {issue['purpose']}")
            if "hint" in issue:
                lines.append(f"      Install: {issue['hint']}")
        lines.append("")

    if result["ok"] and not result["warnings"]:
        lines.append("✅ All dependencies satisfied!")
    elif result["ok"]:
        lines.append("✅ Core dependencies OK (some optional features unavailable)")
    else:
        lines.append("❌ Some required dependencies missing!")
        lines.append("   Run: ~/.claude/hooks/dependency_check.py --fix")
        lines.append("   Or:  pip install -r ~/.claude/requirements.txt")

    lines.append("")
    lines.append("=" * 50)
    return "\n".join(lines)


# =============================================================================
# CLI INTERFACE
# =============================================================================


def main():
    """Run dependency check and output results."""
    import argparse

    parser = argparse.ArgumentParser(description="Check .claude dependencies")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show full report")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--quiet", "-q", action="store_true", help="Only show if issues exist")
    parser.add_argument("--fix", action="store_true", help="Auto-install missing Python packages")
    args = parser.parse_args()

    result = run_dependency_check(auto_fix=args.fix, verbose=args.verbose or args.fix)

    if args.json:
        import json
        print(json.dumps(result, indent=2))
    elif args.verbose:
        print(format_full_report(result))
    elif args.quiet:
        if not result["ok"] or result["warnings"]:
            print(result["summary"])
    else:
        print(result["summary"])

    # Exit code: 0 if ok, 1 if critical issues
    sys.exit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
