#!/usr/bin/env python3
"""
The Janitor: Pre-commit health checks and project maintenance.
Run before commits to catch issues early.
"""
import sys
import os
import subprocess
import re
import ast
import stat
from datetime import datetime, timedelta

# Add .claude/lib to path
_script_path = os.path.abspath(__file__)
_script_dir = os.path.dirname(_script_path)
_current = _script_dir
while _current != "/":
    if os.path.exists(os.path.join(_current, ".claude", "lib", "core.py")):
        _project_root = _current
        break
    _current = os.path.dirname(_current)
else:
    raise RuntimeError("Could not find project root with .claude/lib/core.py")
sys.path.insert(0, os.path.join(_project_root, ".claude", "lib"))
from core import setup_script, finalize, logger, handle_debug  # noqa: E402


# Standard library modules for dependency checking
STDLIB_MODULES = {
    "abc", "argparse", "ast", "asyncio", "base64", "collections", "concurrent",
    "copy", "csv", "datetime", "decimal", "email", "enum", "functools", "glob",
    "hashlib", "hmac", "html", "http", "importlib", "inspect", "io", "itertools",
    "json", "logging", "math", "multiprocessing", "operator", "os", "pathlib",
    "pickle", "platform", "pprint", "re", "secrets", "shutil", "socket", "sqlite3",
    "stat", "statistics", "string", "subprocess", "sys", "tempfile", "textwrap",
    "threading", "time", "traceback", "typing", "unittest", "urllib", "uuid",
    "warnings", "xml", "contextlib", "dataclasses", "difflib", "fnmatch",
    "getpass", "grp", "pwd", "queue", "random", "select", "signal", "struct",
    "tarfile", "zipfile", "zlib", "types", "weakref", "array", "binascii",
    "fcntl", "termios", "tty", "pty", "resource", "syslog",  # Unix-specific
    "colorsys", "codeop", "code", "cgi", "cgitb", "chunk", "cmath", "cmd",
    "codecs", "crypt", "curses", "dbm", "dis", "doctest", "filecmp", "fileinput",
    "fractions", "ftplib", "gc", "getopt", "gettext", "graphlib", "gzip",
    "heapq", "idlelib", "imaplib", "ipaddress", "keyword", "lib2to3", "linecache",
    "locale", "lzma", "mailbox", "mimetypes", "mmap", "modulefinder", "netrc",
    "nis", "nntplib", "numbers", "optparse", "ossaudiodev", "parser", "pdb",
    "pkgutil", "poplib", "posix", "posixpath", "profile", "pstats", "rlcompleter",
    "runpy", "sched", "shelve", "shlex", "smtpd", "smtplib", "sndhdr", "spwd",
    "ssl", "stringprep", "sunau", "symbol", "symtable", "sysconfig", "tabnanny",
    "telnetlib", "test", "textwrap", "tkinter", "token", "tokenize", "trace",
    "tracemalloc", "turtledemo", "unicodedata", "venv", "wave", "webbrowser",
    "winreg", "winsound", "wsgiref", "xdrlib", "xmlrpc",
}

# Import name -> Package name mapping
IMPORT_TO_PACKAGE = {
    "dotenv": "python-dotenv",
    "cv2": "opencv-python",
    "PIL": "pillow",
    "yaml": "pyyaml",
    "bs4": "beautifulsoup4",
    "docx": "python-docx",
    "pptx": "python-pptx",
    "sklearn": "scikit-learn",
}


def section(title, icon="📋"):
    """Print a section header."""
    print(f"\n{icon} {title}")
    print("-" * 60)


def extract_imports_from_file(filepath):
    """Extract all imported module names from a Python file."""
    imports = set()
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=filepath)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.add(node.module.split(".")[0])
    except Exception as e:
        logger.debug(f"Could not parse {filepath}: {e}")
    return imports


def _get_git_branch() -> str:
    """Get current git branch name."""
    result = subprocess.run(
        ["git", "branch", "--show-current"],
        capture_output=True, text=True, cwd=_project_root
    )
    return result.stdout.strip() or "detached HEAD"


def _categorize_git_status(lines: list[str]) -> tuple[list[str], list[str], list[str]]:
    """Categorize git status lines into staged, unstaged, untracked."""
    staged = [ln for ln in lines if ln[0] != " " and ln[0] != "?"]
    unstaged = [ln for ln in lines if ln[0] == " " or ln[1] != " "]
    untracked = [ln for ln in lines if ln.startswith("??")]
    return staged, unstaged, untracked


def _print_git_summary(branch: str, staged: list, unstaged: list, untracked: list) -> None:
    """Print git status summary."""
    print(f"  Branch: {branch}")
    print(f"  Staged: {len(staged)} | Modified: {len(unstaged) - len(untracked)} | Untracked: {len(untracked)}")
    if staged:
        print("  📦 Ready to commit:")
        for line in staged[:5]:
            print(f"     {line}")
        if len(staged) > 5:
            print(f"     ... and {len(staged) - 5} more")


def check_git_status(dry_run):
    """Check git status for uncommitted changes."""
    section("Git Status", "📊")

    try:
        current_branch = _get_git_branch()
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True, text=True, cwd=_project_root
        )

        if result.returncode != 0:
            print("  ⚠️  Not a git repository or git error")
            return True

        lines = [ln for ln in result.stdout.strip().split("\n") if ln]
        if not lines:
            print(f"  ✅ Clean working tree on '{current_branch}'")
            return True

        staged, unstaged, untracked = _categorize_git_status(lines)
        _print_git_summary(current_branch, staged, unstaged, untracked)
        return True
    except FileNotFoundError:
        print("  ⚠️  git not found")
        return True


def _check_hook_executable(filepath: str, item: str, fix: bool, dry_run: bool) -> tuple[str | None, bool]:
    """Check if hook file is executable, optionally fix. Returns (issue, was_fixed)."""
    if not item.endswith((".py", ".sh", ".js")):
        return None, False
    mode = os.stat(filepath).st_mode
    is_exec = mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    if is_exec:
        return None, False
    if fix and not dry_run:
        os.chmod(filepath, mode | stat.S_IXUSR)
        print(f"  🔧 Fixed: {item} (made executable)")
        return None, True
    return f"{item} not executable", False


def _check_hook_syntax(filepath: str, item: str) -> str | None:
    """Check Python syntax of hook file. Returns issue string or None."""
    if not item.endswith(".py"):
        return None
    try:
        with open(filepath, "r") as f:
            ast.parse(f.read(), filename=item)
        return None
    except SyntaxError as e:
        return f"{item} syntax error: {e.msg} (line {e.lineno})"


def _get_hook_files(hooks_dir: str) -> list[tuple[str, str]]:
    """Get list of (filepath, filename) for hook files to check."""
    results = []
    for item in os.listdir(hooks_dir):
        if item.startswith((".", "_")) or item == "__pycache__":
            continue
        filepath = os.path.join(hooks_dir, item)
        if os.path.isfile(filepath):
            results.append((filepath, item))
    return results


def _check_all_hooks(hook_files: list[tuple[str, str]], fix: bool, dry_run: bool) -> tuple[list[str], int]:
    """Check all hook files. Returns (issues, fixed_count)."""
    issues = []
    fixed = 0
    for filepath, item in hook_files:
        issue, was_fixed = _check_hook_executable(filepath, item, fix, dry_run)
        if issue:
            issues.append(issue)
        if was_fixed:
            fixed += 1
        if syntax_issue := _check_hook_syntax(filepath, item):
            issues.append(syntax_issue)
    return issues, fixed


def check_hooks_health(dry_run, fix=False):
    """Verify hooks are executable and have valid syntax."""
    section("Hooks Health", "🪝")

    hooks_dir = os.path.join(_project_root, ".claude", "hooks")
    if not os.path.exists(hooks_dir):
        print("  ℹ️  No hooks directory")
        return True

    hook_files = _get_hook_files(hooks_dir)
    issues, fixed = _check_all_hooks(hook_files, fix, dry_run)

    if issues:
        print(f"  ⚠️  {len(issues)} issue(s):")
        for issue in issues:
            print(f"     - {issue}")
        if not fix:
            print("  💡 Run with --fix to auto-repair")
        return False

    print(f"  ✅ {len(hook_files)} hooks healthy" + (f" ({fixed} fixed)" if fixed else ""))
    return True


def check_ops_syntax(dry_run):
    """Validate Python syntax in all ops/ scripts."""
    section("Ops Syntax Check", "🔍")

    ops_dir = os.path.join(_project_root, ".claude", "ops")
    if not os.path.exists(ops_dir):
        print("  ℹ️  No ops directory")
        return True

    errors = []
    checked = 0

    for item in os.listdir(ops_dir):
        if not item.endswith(".py"):
            continue
        filepath = os.path.join(ops_dir, item)
        checked += 1

        try:
            with open(filepath, "r") as f:
                ast.parse(f.read(), filename=item)
        except SyntaxError as e:
            errors.append(f"{item}:{e.lineno}: {e.msg}")

    if errors:
        print(f"  ❌ {len(errors)} syntax error(s):")
        for err in errors:
            print(f"     {err}")
        return False

    print(f"  ✅ {checked} scripts valid")
    return True


def _get_local_modules() -> set[str]:
    """Auto-detect local modules from .claude subdirs."""
    import glob as glob_module
    local_modules = {"core", "parallel", "lib", "confidence", "session_state", "context_builder"}
    # Find all .py files in .claude (excluding venv/cache)
    pattern = os.path.join(_project_root, ".claude", "**", "*.py")
    for path in glob_module.glob(pattern, recursive=True):
        if any(x in path for x in [".venv", "__pycache__", ".ruff_cache"]):
            continue
        name = os.path.basename(path)[:-3]  # Remove .py
        local_modules.add(name)
        if name.startswith("_"):
            local_modules.add(name[1:])  # Also add without underscore
    return local_modules


def _collect_all_imports(scripts_dir: str) -> set[str]:
    """Collect all imports from Python files in directory."""
    all_imports = set()
    for root, dirs, files in os.walk(scripts_dir):
        dirs[:] = [d for d in dirs if d not in {".venv", "__pycache__", ".ruff_cache"}]
        for file in files:
            if file.endswith(".py"):
                imports = extract_imports_from_file(os.path.join(root, file))
                all_imports.update(imports)
    return all_imports


def _load_requirements(requirements_file: str) -> set[str]:
    """Load package names from requirements.txt."""
    required = set()
    if not os.path.exists(requirements_file):
        return required
    with open(requirements_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                pkg_name = re.split(r"[=<>!\[]", line)[0].strip()
                required.add(pkg_name.lower())
    return required


def check_dependencies(dry_run):
    """Scan scripts for imports and verify against requirements.txt."""
    section("Dependencies", "📦")

    local_modules = _get_local_modules()
    all_imports = _collect_all_imports(os.path.join(_project_root, ".claude"))

    external_imports = {
        imp for imp in all_imports
        if imp not in STDLIB_MODULES and imp not in local_modules and not imp.startswith("_")
    }

    required_packages = _load_requirements(os.path.join(_project_root, ".claude", "requirements.txt"))

    missing = [imp for imp in external_imports if IMPORT_TO_PACKAGE.get(imp, imp).lower() not in required_packages]

    if missing:
        print(f"  ⚠️  {len(missing)} potentially undocumented:")
        for pkg in sorted(missing):
            print(f"     - {pkg}")
        return False

    print(f"  ✅ {len(external_imports)} external deps documented")
    return True


def _find_stale_files(tmp_dir: str, files: list[str], cutoff_hours: int = 24) -> list[tuple[str, float]]:
    """Find files older than cutoff. Returns list of (filename, age_hours)."""
    cutoff = datetime.now() - timedelta(hours=cutoff_hours)
    stale = []
    for fname in files:
        fpath = os.path.join(tmp_dir, fname)
        mtime = datetime.fromtimestamp(os.path.getmtime(fpath))
        if mtime < cutoff:
            age_h = (datetime.now() - mtime).total_seconds() / 3600
            stale.append((fname, age_h))
    return stale


def _clean_stale_files(tmp_dir: str, old_files: list[tuple[str, float]]) -> None:
    """Delete stale files from tmp directory."""
    for fname, _ in old_files:
        os.remove(os.path.join(tmp_dir, fname))
    print(f"  🧹 Cleaned {len(old_files)} stale files")


def check_tmp_dir(dry_run, fix=False):
    """Check .claude/tmp/ for stale files."""
    section("Temp Directory", "🧹")

    tmp_dir = os.path.join(_project_root, ".claude", "tmp")
    if not os.path.exists(tmp_dir):
        print("  ℹ️  .claude/tmp/ does not exist")
        return True

    files = [f for f in os.listdir(tmp_dir) if os.path.isfile(os.path.join(tmp_dir, f))]
    if not files:
        print("  ✅ Clean (empty)")
        return True

    old_files = _find_stale_files(tmp_dir, files)
    print(f"  📊 {len(files)} file(s), {len(old_files)} stale (>24h)")

    if not old_files:
        return True

    if fix and not dry_run:
        _clean_stale_files(tmp_dir, old_files)
        return True

    for fname, age in old_files[:3]:
        print(f"     - {fname} ({age:.0f}h old)")
    if len(old_files) > 3:
        print(f"     ... and {len(old_files) - 3} more")
    print("  💡 Run with --fix to clean, or promote to ops/")
    return False


def _get_staged_filepaths(lines: list[str]) -> list[str]:
    """Extract staged file paths from git porcelain output."""
    paths = []
    for line in lines:
        if not line or line.startswith("??"):
            continue
        if len(line) < 3 or line[0] == " ":
            continue  # Not staged in index
        filepath = line[3:].strip()
        if " -> " in filepath:  # rename
            filepath = filepath.split(" -> ")[1]
        paths.append(filepath)
    return paths


def _find_large_staged_files(filepaths: list[str], size_limit: int) -> list[tuple[str, float]]:
    """Find files exceeding size limit. Returns list of (path, size_mb)."""
    large = []
    for filepath in filepaths:
        full_path = os.path.join(_project_root, filepath)
        if os.path.isfile(full_path):
            size = os.path.getsize(full_path)
            if size > size_limit:
                large.append((filepath, size / 1024 / 1024))
    return large


def check_large_files(dry_run):
    """Check for large uncommitted files."""
    section("Large Files Check", "📏")

    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True, text=True, cwd=_project_root
        )
        if result.returncode != 0:
            return True

        lines = result.stdout.strip().split("\n")
        staged_paths = _get_staged_filepaths(lines)
        large_files = _find_large_staged_files(staged_paths, 1024 * 1024)

        if large_files:
            print(f"  ⚠️  {len(large_files)} large file(s) staged:")
            for fpath, size_mb in large_files:
                print(f"     - {fpath} ({size_mb:.1f}MB)")
            return False

        print("  ✅ No large files staged")
        return True
    except Exception:
        return True


def check_claude_md(dry_run):
    """Verify CLAUDE.md exists and is readable."""
    section("CLAUDE.md", "📄")

    claude_md = os.path.join(_project_root, "CLAUDE.md")

    if not os.path.exists(claude_md):
        print("  ⚠️  CLAUDE.md not found in project root")
        return False

    try:
        with open(claude_md, "r") as f:
            content = f.read()

        lines = len(content.split("\n"))
        size_kb = len(content) / 1024

        # Basic sanity checks
        issues = []
        if size_kb > 50:
            issues.append(f"Large ({size_kb:.1f}KB) - consider trimming")
        if "## " not in content:
            issues.append("No section headers found")

        if issues:
            print(f"  ⚠️  CLAUDE.md ({lines} lines):")
            for issue in issues:
                print(f"     - {issue}")
            return False

        print(f"  ✅ CLAUDE.md valid ({lines} lines, {size_kb:.1f}KB)")
        return True
    except Exception as e:
        print(f"  ❌ Could not read CLAUDE.md: {e}")
        return False


def log_maintenance(dry_run):
    """Log maintenance timestamp and update session state."""
    log_file = os.path.join(_project_root, ".claude", "memory", "upkeep_log.md")

    if dry_run:
        return True

    try:
        os.makedirs(os.path.dirname(log_file), exist_ok=True)

        if not os.path.exists(log_file):
            with open(log_file, "w") as f:
                f.write("# Upkeep Log\n\n")

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        with open(log_file, "a") as f:
            f.write(f"- {timestamp}\n")

        # Update session state so gap_detector knows upkeep ran
        # (Bash-invoked upkeep doesn't trigger hooks, so we update directly)
        try:
            from session_state import update_state
            def mark_upkeep(state):
                state.ops_turns["upkeep"] = state.turn_count
            update_state(mark_upkeep)
        except Exception:
            pass  # Don't fail upkeep if state update fails

        return True
    except Exception:
        return True


def _run_checks(dry_run: bool, fix: bool, quick: bool) -> list[str]:
    """Run all health checks. Returns list of issue names."""
    issues = []
    checks = [
        (check_git_status, [dry_run], "git status"),
        (check_hooks_health, [dry_run, fix], "hooks health"),
        (check_ops_syntax, [dry_run], "ops syntax"),
        (check_dependencies, [dry_run], "dependencies"),
        (check_tmp_dir, [dry_run, fix], "stale tmp files"),
        (check_claude_md, [dry_run], "CLAUDE.md"),
    ]
    for check_fn, check_args, name in checks:
        if not check_fn(*check_args):
            issues.append(name)
    if not quick and not check_large_files(dry_run):
        issues.append("large files")
    return issues


def _print_summary(issues: list[str], fix: bool) -> None:
    """Print final summary of check results."""
    print("\n" + "=" * 60)
    print("📊 SUMMARY")
    print("=" * 60)
    if issues:
        print(f"  ⚠️  {len(issues)} area(s) need attention:")
        for issue in issues:
            print(f"     • {issue}")
        if not fix:
            print("\n  💡 Run with --fix to auto-repair fixable issues")
    else:
        print("  ✅ All checks passed!")


def main():
    parser = setup_script(
        "The Janitor: Pre-commit health checks and project maintenance."
    )
    parser.add_argument(
        "--quick", action="store_true",
        help="Skip slow checks (large files, full syntax scan)"
    )
    parser.add_argument(
        "--fix", action="store_true",
        help="Auto-fix issues where possible (chmod hooks, clean tmp)"
    )

    args = parser.parse_args()
    handle_debug(args)

    print("\n" + "=" * 60)
    print("🧹 UPKEEP: Project Health Check")
    print("=" * 60)

    if args.dry_run:
        print("⚠️  DRY RUN MODE")
    if args.fix:
        print("🔧 FIX MODE: Will auto-repair issues")

    issues = _run_checks(args.dry_run, args.fix, args.quick)
    log_maintenance(args.dry_run)
    _print_summary(issues, args.fix)

    if issues:
        finalize(success=False, message=f"Upkeep found {len(issues)} issue(s)")
    else:
        finalize(success=True, message="Upkeep complete - project healthy")


if __name__ == "__main__":
    main()
