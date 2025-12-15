#!/usr/bin/env python3
"""
Dependency Checker v1.2: Validates all .claude dependencies at session start.

Checks:
1. Required API keys (for external services)
2. Python packages (from requirements.txt)
3. External binaries (git, ruff, bd, node, npm, etc.)
4. Critical directories and files
5. Node.js/npm for MCP servers and frontend workflows
6. MCP server dependencies
7. MCP config validity (settings.json plugin entries)
8. Stale MCP server processes

Features:
- Fast (<500ms total with caching)
- Non-blocking (warnings only, never fails session)
- Comprehensive (catches missing deps before cryptic failures)
- Auto-fix mode (--fix to install missing Python packages)
- Result caching (5 min TTL to avoid re-checking mid-session)
- Timeout protection on slow external commands
"""

import json
import os
import sys
import shutil
import subprocess
import importlib.util
import time
from pathlib import Path

# =============================================================================
# CONFIGURATION
# =============================================================================

# Cache settings
CACHE_FILE = Path.home() / ".claude" / "tmp" / "dep_check_cache.json"
CACHE_TTL_SECONDS = 300  # 5 minutes

# Timeout for external commands (seconds)
CMD_TIMEOUT_FAST = 2  # For quick commands like node --version
CMD_TIMEOUT_SLOW = 5  # For npm list (can be slow)

# API keys and their purposes (for clear error messages)
API_KEYS = {
    "OPENROUTER_API_KEY": {
        "required": False,
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
PYTHON_PACKAGES = {
    "requests": None,
    "pydantic": None,
    "yaml": "pyyaml",
    "dotenv": "python-dotenv",
    "rapidfuzz": None,
    "websockets": None,
}

# Critical paths that must exist
CRITICAL_PATHS = {
    "~/.claude/hooks": "Hook scripts",
    "~/.claude/ops": "Ops scripts",
    "~/.claude/lib": "Library modules",
    "~/.claude/memory": "Memory storage",
    "~/.claude/.venv": "Python virtual environment",
}

# MCP servers that require npm packages
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

# Known MCP process patterns (for stale process detection)
MCP_PROCESS_PATTERNS = [
    "mcp-server",
    "repomix",
    "@anthropic/mcp",
    "claude-mem",
    "crawl4ai",
]


# =============================================================================
# CACHING
# =============================================================================


def load_cache() -> dict | None:
    """Load cached results if valid."""
    if not CACHE_FILE.exists():
        return None

    try:
        with open(CACHE_FILE) as f:
            cache = json.load(f)

        # Check TTL
        cached_at = cache.get("cached_at", 0)
        if time.time() - cached_at > CACHE_TTL_SECONDS:
            return None

        return cache.get("result")
    except (json.JSONDecodeError, KeyError, IOError):
        return None


def save_cache(result: dict) -> None:
    """Save results to cache."""
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(CACHE_FILE, "w") as f:
            json.dump({"cached_at": time.time(), "result": result}, f)
    except IOError:
        pass  # Non-critical


def clear_cache() -> None:
    """Clear the cache file."""
    if CACHE_FILE.exists():
        try:
            CACHE_FILE.unlink()
        except IOError:
            pass


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

    if not shutil.which("node") or not shutil.which("npm"):
        return issues

    try:
        result = subprocess.run(
            ["node", "--version"],
            capture_output=True,
            text=True,
            timeout=CMD_TIMEOUT_FAST,
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
    """Check MCP server dependencies with timeout protection."""
    issues = []

    if not shutil.which("npm"):
        return issues

    for server_name, info in MCP_SERVERS.items():
        package = info["package"]
        is_global = info.get("global", False)

        try:
            cmd = ["npm", "list", package]
            if is_global:
                cmd.insert(2, "-g")

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=CMD_TIMEOUT_SLOW,
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
            # Skip slow checks, don't report as issue
            pass

    return issues


def check_mcp_config() -> list[dict]:
    """Check MCP configuration in settings.json."""
    issues = []
    settings_path = Path.home() / ".claude" / "settings.json"

    if not settings_path.exists():
        return issues

    try:
        with open(settings_path) as f:
            settings = json.load(f)

        enabled_plugins = settings.get("enabledPlugins", {})

        for plugin_name, enabled in enabled_plugins.items():
            if not enabled:
                continue

            # Check for common plugin name patterns that suggest missing deps
            if "mcp" in plugin_name.lower():
                # Plugin enabled but we can't verify it's installed
                # This is informational, not blocking
                pass

        # Check hooks configuration
        hooks = settings.get("hooks", {})
        for hook_type, hook_configs in hooks.items():
            if not isinstance(hook_configs, list):
                continue

            for config in hook_configs:
                if not isinstance(config, dict):
                    continue

                hook_list = config.get("hooks", [])
                for hook in hook_list:
                    if not isinstance(hook, dict):
                        continue

                    command = hook.get("command", "")
                    if command:
                        # Check if hook script exists
                        # Expand $HOME
                        expanded = command.replace("$HOME", str(Path.home()))
                        parts = expanded.split()
                        if parts:
                            script_path = Path(parts[-1])  # Last part is usually the script
                            if script_path.suffix == ".py" and not script_path.exists():
                                issues.append({
                                    "type": "mcp_config",
                                    "name": f"Hook script missing: {script_path.name}",
                                    "description": f"Hook type {hook_type} references missing script",
                                    "required": False,
                                    "hint": f"Check {settings_path}",
                                })

    except (json.JSONDecodeError, KeyError, IOError):
        pass

    return issues


def check_stale_mcp_processes() -> list[dict]:
    """Check for stale MCP server processes."""
    issues = []

    try:
        # Get list of running processes
        result = subprocess.run(
            ["ps", "aux"],
            capture_output=True,
            text=True,
            timeout=CMD_TIMEOUT_FAST,
        )

        if result.returncode != 0:
            return issues

        lines = result.stdout.strip().split("\n")
        stale_processes = []

        for line in lines[1:]:  # Skip header
            parts = line.split(None, 10)
            if len(parts) < 11:
                continue

            pid = parts[1]
            cpu = parts[2]
            command = parts[10]

            # Check if this looks like an MCP process
            for pattern in MCP_PROCESS_PATTERNS:
                if pattern in command.lower():
                    # Check if it's consuming resources but possibly orphaned
                    try:
                        cpu_val = float(cpu)
                        # Flag processes using significant CPU or matching patterns
                        if cpu_val > 10 or "defunct" in command:
                            stale_processes.append({
                                "pid": pid,
                                "cpu": cpu,
                                "command": command[:60],
                            })
                    except ValueError:
                        pass
                    break

        if stale_processes:
            for proc in stale_processes[:3]:  # Limit to 3
                issues.append({
                    "type": "stale_process",
                    "name": f"PID {proc['pid']}",
                    "description": f"Possible stale MCP: {proc['command']}",
                    "required": False,
                    "hint": f"kill {proc['pid']} (if safe)",
                })

    except (subprocess.TimeoutExpired, IOError):
        pass

    return issues


# =============================================================================
# FIX FUNCTIONS
# =============================================================================


def fix_python_packages(issues: list[dict], verbose: bool = False) -> list[dict]:
    """Attempt to install missing Python packages."""
    remaining = []
    pip_path = Path.home() / ".claude" / ".venv" / "bin" / "pip"

    if not pip_path.exists():
        return issues

    python_issues = [i for i in issues if i["type"] == "python_package"]
    other_issues = [i for i in issues if i["type"] != "python_package"]

    if not python_issues:
        return issues

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


def run_dependency_check(
    auto_fix: bool = False,
    verbose: bool = False,
    use_cache: bool = True,
    force_refresh: bool = False,
) -> dict:
    """Run all dependency checks and return results.

    Args:
        auto_fix: If True, attempt to install missing Python packages.
        verbose: If True, print progress messages during fix.
        use_cache: If True, use cached results if available.
        force_refresh: If True, ignore cache and run fresh checks.

    Returns:
        dict with keys:
            - ok: bool (True if no required deps missing)
            - critical: list of critical issues (required deps missing)
            - warnings: list of warnings (optional deps missing)
            - summary: str (human-readable summary)
            - fixed: int (number of issues fixed, if auto_fix=True)
            - cached: bool (True if results came from cache)
    """
    # Check cache first (unless fixing or forcing refresh)
    if use_cache and not auto_fix and not force_refresh:
        cached = load_cache()
        if cached:
            cached["cached"] = True
            return cached

    all_issues = []

    # Run all checks
    all_issues.extend(check_critical_paths())
    all_issues.extend(check_venv_integrity())
    all_issues.extend(check_binaries())
    all_issues.extend(check_python_packages())
    all_issues.extend(check_node_ecosystem())
    all_issues.extend(check_mcp_servers())
    all_issues.extend(check_mcp_config())
    all_issues.extend(check_stale_mcp_processes())
    all_issues.extend(check_api_keys())

    fixed_count = 0

    if auto_fix:
        original_count = len(all_issues)
        all_issues = fix_python_packages(all_issues, verbose=verbose)
        fixed_count = original_count - len(all_issues)
        # Clear cache after fixing
        clear_cache()

    # Separate critical vs warnings
    critical = [i for i in all_issues if i.get("required", False)]
    warnings = [i for i in all_issues if not i.get("required", False)]

    # Build summary
    summary_parts = []

    if fixed_count > 0:
        summary_parts.append(f"🔧 Fixed {fixed_count} missing packages")

    if critical:
        summary_parts.append(f"🔴 {len(critical)} MISSING (required)")
        for issue in critical[:3]:
            name = issue.get("name", "unknown")
            hint = issue.get("hint", "")
            if hint:
                summary_parts.append(f"   • {name}: {hint}")
            else:
                summary_parts.append(f"   • {name}")
        if len(critical) > 3:
            summary_parts.append(f"   ... and {len(critical) - 3} more")

    if warnings:
        api_keys_missing = [w for w in warnings if w["type"] == "api_key"]
        stale_procs = [w for w in warnings if w["type"] == "stale_process"]
        other_warnings = [w for w in warnings if w["type"] not in ("api_key", "stale_process")]

        if api_keys_missing:
            key_names = [w["name"] for w in api_keys_missing]
            summary_parts.append(f"🟡 API keys not set: {', '.join(key_names[:4])}")
            if len(key_names) > 4:
                summary_parts.append(f"   ... and {len(key_names) - 4} more")

        if stale_procs:
            summary_parts.append(f"🟠 {len(stale_procs)} possible stale MCP process(es)")

        if other_warnings:
            for issue in other_warnings[:2]:
                summary_parts.append(f"🟡 Optional: {issue.get('name', 'unknown')}")

    if not critical and not warnings:
        summary_parts.append("✅ All dependencies satisfied")
    elif not critical and not summary_parts:
        summary_parts.insert(0, "✅ Core dependencies OK")

    result = {
        "ok": len(critical) == 0,
        "critical": critical,
        "warnings": warnings,
        "summary": "\n".join(summary_parts),
        "fixed": fixed_count,
        "cached": False,
    }

    # Save to cache (if not fixing)
    if use_cache and not auto_fix:
        save_cache(result)

    return result


def format_full_report(result: dict) -> str:
    """Format a full dependency report for verbose output."""
    lines = ["=" * 50, "DEPENDENCY CHECK REPORT", "=" * 50, ""]

    if result.get("cached"):
        lines.append("📋 (from cache)")
        lines.append("")

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
            if "description" in issue:
                lines.append(f"      Info: {issue['description']}")
            if "hint" in issue:
                lines.append(f"      Fix: {issue['hint']}")
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
    parser.add_argument("--no-cache", action="store_true", help="Skip cache, run fresh checks")
    parser.add_argument("--clear-cache", action="store_true", help="Clear cache and exit")
    args = parser.parse_args()

    if args.clear_cache:
        clear_cache()
        print("Cache cleared")
        sys.exit(0)

    result = run_dependency_check(
        auto_fix=args.fix,
        verbose=args.verbose or args.fix,
        use_cache=not args.no_cache,
        force_refresh=args.no_cache,
    )

    if args.json:
        print(json.dumps(result, indent=2))
    elif args.verbose:
        print(format_full_report(result))
    elif args.quiet:
        if not result["ok"] or result["warnings"]:
            print(result["summary"])
    else:
        print(result["summary"])

    sys.exit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
