#!/usr/bin/env python3
"""
Project Detector v1.0: Auto-detect project context for multi-project isolation.

This module enables the hook system to work as a "swiss army knife" across
multiple projects without context pollution.

Detection Strategy (in order of precedence):
1. Git remote URL (most stable identifier)
2. Git repo root directory name
3. package.json/pyproject.toml project name
4. Working directory path hash

Project Types:
- "project": Has git repo, code files, structured work
- "ephemeral": No project markers, casual conversation, disposable context

Design Principles:
- Zero human declaration required
- Fast detection (<10ms)
- Stable IDs across sessions
- Graceful fallback chain
"""

import os
import re
import json
import hashlib
import subprocess
import time
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Optional

# =============================================================================
# SESSION-SCOPED CACHES (Performance optimization)
# Git operations are expensive (~50-100ms each). Cache for session lifetime.
# =============================================================================

_GIT_ROOT_CACHE: Optional[str] = None
_GIT_ROOT_CACHE_CWD: Optional[str] = None

_GIT_REMOTE_CACHE: Optional[str] = None
_GIT_REMOTE_CACHE_CWD: Optional[str] = None

_PROJECT_CACHE: Optional["ProjectContext"] = None
_PROJECT_CACHE_CWD: Optional[str] = None


@dataclass
class ProjectContext:
    """Detected project context."""

    project_id: str  # Stable identifier (hash or name)
    project_name: str  # Human-readable name
    project_type: str  # "project" | "ephemeral"
    root_path: str  # Absolute path to project root
    detection_method: str  # How we identified this project
    git_remote: str = ""  # Git remote URL if available
    language: str = ""  # Primary language (python, javascript, etc.)
    framework: str = ""  # Detected framework (react, fastapi, etc.)


# =============================================================================
# GIT DETECTION
# =============================================================================


# SUDO SECURITY: Adding caching to existing subprocess calls - no new security surface
def get_git_root() -> Optional[str]:
    """Get git repository root path.

    Cached per working directory - eliminates ~50ms subprocess overhead.
    """
    global _GIT_ROOT_CACHE, _GIT_ROOT_CACHE_CWD

    cwd = os.getcwd()
    if _GIT_ROOT_CACHE_CWD == cwd and _GIT_ROOT_CACHE is not None:
        return _GIT_ROOT_CACHE if _GIT_ROOT_CACHE else None

    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=2,
            cwd=cwd,
        )
        if result.returncode == 0:
            _GIT_ROOT_CACHE = result.stdout.strip()
            _GIT_ROOT_CACHE_CWD = cwd
            return _GIT_ROOT_CACHE
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass

    # Cache negative result too
    _GIT_ROOT_CACHE = ""
    _GIT_ROOT_CACHE_CWD = cwd
    return None


def get_git_remote() -> Optional[str]:
    """Get git remote origin URL.

    Cached per working directory - eliminates ~50ms subprocess overhead.
    """
    global _GIT_REMOTE_CACHE, _GIT_REMOTE_CACHE_CWD

    cwd = os.getcwd()
    if _GIT_REMOTE_CACHE_CWD == cwd and _GIT_REMOTE_CACHE is not None:
        return _GIT_REMOTE_CACHE if _GIT_REMOTE_CACHE else None

    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            timeout=2,
            cwd=cwd,
        )
        if result.returncode == 0:
            _GIT_REMOTE_CACHE = result.stdout.strip()
            _GIT_REMOTE_CACHE_CWD = cwd
            return _GIT_REMOTE_CACHE
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass

    # Cache negative result too
    _GIT_REMOTE_CACHE = ""
    _GIT_REMOTE_CACHE_CWD = cwd
    return None


def extract_repo_name(remote_url: str) -> str:
    """Extract repository name from git remote URL.

    Examples:
    - git@github.com:user/repo.git -> repo
    - https://github.com/user/repo.git -> repo
    - https://github.com/user/repo -> repo
    """
    if not remote_url:
        return ""

    # Remove .git suffix
    url = remote_url.rstrip("/").removesuffix(".git")

    # Extract last path component
    if "/" in url:
        return url.split("/")[-1]
    if ":" in url:
        return url.split(":")[-1].split("/")[-1]

    return url


# =============================================================================
# PROJECT FILE DETECTION
# =============================================================================

# Project file patterns: (filename, regex_pattern, is_json, name_transform)
_PROJECT_FILES = (
    ("package.json", None, True, None),
    ("pyproject.toml", r'name\s*=\s*["\']([^"\']+)["\']', False, None),
    ("Cargo.toml", r'name\s*=\s*["\']([^"\']+)["\']', False, None),
    ("go.mod", r"^module\s+(\S+)", False, lambda m: m.split("/")[-1]),
)


def _parse_project_file(
    path: Path, pattern: str, is_json: bool, transform
) -> Optional[dict]:
    """Parse a single project file and extract name."""
    try:
        if is_json:
            with open(path) as f:
                return json.load(f)
        content = path.read_text()
        match = re.search(pattern, content, re.MULTILINE)
        if match:
            name = match.group(1)
            return {"name": transform(name) if transform else name}
    except (json.JSONDecodeError, IOError):
        pass
    return None


def find_project_file(root: str) -> Optional[tuple[str, dict]]:
    """Find and parse project configuration file.

    Returns: (file_type, parsed_data) or None
    """
    root_path = Path(root)
    for filename, pattern, is_json, transform in _PROJECT_FILES:
        path = root_path / filename
        if path.exists():
            data = _parse_project_file(path, pattern, is_json, transform)
            if data:
                return (filename, data)
    return None


def detect_language(root: str) -> str:
    """Detect primary language from file extensions.

    Uses shallow search (max 2 levels) to avoid scanning large directories.
    """
    root_path = Path(root)

    # Skip expensive detection for home directories
    home = Path.home()
    if root_path == home or root_path == home.parent:
        return ""

    # Count files by extension (shallow search only)
    counts = {}
    lang_map = {
        ".py": "python",
        ".js": "javascript",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".rs": "rust",
        ".go": "go",
        ".java": "java",
        ".rb": "ruby",
        ".php": "php",
    }

    try:
        for ext, lang in lang_map.items():
            # Shallow glob: root + 2 levels deep only (fast)
            count = 0
            for pattern in [f"*{ext}", f"*/*{ext}", f"src/*{ext}", f"src/*/*{ext}"]:
                try:
                    count += len(list(root_path.glob(pattern))[:50])
                    if count >= 50:
                        break
                except OSError:
                    pass
            if count > 0:
                counts[lang] = min(count, 100)
    except OSError:
        pass

    if counts:
        return max(counts, key=counts.get)
    return ""


# Framework detection order (first match wins)
_JS_FRAMEWORKS = (
    ("next", "nextjs"),
    ("react", "react"),
    ("vue", "vue"),
    ("svelte", "svelte"),
    ("express", "express"),
)
_PY_FRAMEWORKS = (("fastapi", "fastapi"), ("django", "django"), ("flask", "flask"))


def detect_framework(root: str, language: str) -> str:
    """Detect framework from dependencies or file patterns."""
    root_path = Path(root)

    # Check package.json dependencies
    pkg_json = root_path / "package.json"
    if pkg_json.exists():
        try:
            data = json.loads(pkg_json.read_text())
            deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
            for dep, framework in _JS_FRAMEWORKS:
                if dep in deps:
                    return framework
        except (json.JSONDecodeError, IOError):
            pass

    # Check Python frameworks
    if language == "python":
        requirements = root_path / "requirements.txt"
        if requirements.exists():
            try:
                content = requirements.read_text().lower()
                for dep, framework in _PY_FRAMEWORKS:
                    if dep in content:
                        return framework
            except IOError:
                pass

    return ""


# =============================================================================
# PROJECT ID GENERATION
# =============================================================================


def generate_project_id(name: str, remote: str = "", root: str = "") -> str:
    """Generate stable project ID.

    Priority:
    1. Hash of git remote URL (most stable across machines)
    2. Hash of project name + root path (stable per machine)
    3. Hash of root path only (fallback)
    """
    if remote:
        # Normalize remote URL for consistent hashing
        normalized = remote.lower().rstrip("/").removesuffix(".git")
        return f"git_{hashlib.sha256(normalized.encode()).hexdigest()[:12]}"

    if name:
        # Use name + root for local uniqueness
        combo = f"{name}:{root}"
        return f"prj_{hashlib.sha256(combo.encode()).hexdigest()[:12]}"

    # Fallback to root path hash
    return f"dir_{hashlib.sha256(root.encode()).hexdigest()[:12]}"


# =============================================================================
# MAIN DETECTION
# =============================================================================

# Code file extensions for detection
_CODE_EXTENSIONS = ("py", "js", "ts", "rs", "go", "java")


def _detect_from_git(git_root: str, git_remote: str) -> ProjectContext:
    """Detect project from git repository."""
    detection_method = "git_remote" if git_remote else "git_root"
    name = extract_repo_name(git_remote) if git_remote else ""

    # Fallback to project file
    if not name:
        project_file = find_project_file(git_root)
        if project_file:
            _, data = project_file
            name = data.get("name", "")
            detection_method = f"git+{project_file[0]}"

    # Fallback to directory name
    if not name:
        name = Path(git_root).name
        detection_method = "git_dirname"

    return ProjectContext(
        project_id=generate_project_id(name, git_remote, git_root),
        project_name=name,
        project_type="project",
        root_path=git_root,
        detection_method=detection_method,
        git_remote=git_remote,
        language=detect_language(git_root),
        framework=detect_framework(git_root, detect_language(git_root)),
    )


def _detect_from_project_file(cwd: str) -> Optional[ProjectContext]:
    """Detect project from project file (package.json, pyproject.toml, etc.)."""
    project_file = find_project_file(cwd)
    if not project_file:
        return None

    file_type, data = project_file
    name = data.get("name", Path(cwd).name)
    language = detect_language(cwd)

    return ProjectContext(
        project_id=generate_project_id(name, "", cwd),
        project_name=name,
        project_type="project",
        root_path=cwd,
        detection_method=file_type,
        language=language,
        framework=detect_framework(cwd, language),
    )


def _detect_from_code_files(cwd: str) -> Optional[ProjectContext]:
    """Detect project from presence of code files."""
    has_code = any(Path(cwd).glob(f"*.{ext}") for ext in _CODE_EXTENSIONS)
    if not has_code:
        return None

    dir_name = Path(cwd).name
    return ProjectContext(
        project_id=generate_project_id(dir_name, "", cwd),
        project_name=dir_name,
        project_type="project",
        root_path=cwd,
        detection_method="code_files",
        language=detect_language(cwd),
    )


def _make_ephemeral_context(cwd: str) -> ProjectContext:
    """Create ephemeral context for non-project directories."""
    return ProjectContext(
        project_id="ephemeral",
        project_name="ephemeral",
        project_type="ephemeral",
        root_path=cwd,
        detection_method="none",
    )


def _cache_and_return(result: ProjectContext, cwd: str) -> ProjectContext:
    """Cache result and return it."""
    global _PROJECT_CACHE, _PROJECT_CACHE_CWD
    _PROJECT_CACHE = result
    _PROJECT_CACHE_CWD = cwd
    return result


def detect_project() -> ProjectContext:
    """Detect current project context.

    Returns ProjectContext with detected information.
    Detection takes <10ms in typical cases (cached after first call).
    """
    cwd = os.getcwd()

    # Return cached result if cwd hasn't changed
    if _PROJECT_CACHE_CWD == cwd and _PROJECT_CACHE is not None:
        return _PROJECT_CACHE

    # Try git detection first (most reliable)
    git_root = get_git_root()
    if git_root:
        git_remote = get_git_remote() or ""
        return _cache_and_return(_detect_from_git(git_root, git_remote), cwd)

    # Try project file detection
    result = _detect_from_project_file(cwd)
    if result:
        return _cache_and_return(result, cwd)

    # Try code file detection
    result = _detect_from_code_files(cwd)
    if result:
        return _cache_and_return(result, cwd)

    # Fallback to ephemeral
    return _cache_and_return(_make_ephemeral_context(cwd), cwd)


def get_project_memory_dir(project_id: str) -> Path:
    """Get the memory directory for a specific project."""
    # Find .claude directory relative to this file
    lib_dir = Path(__file__).resolve().parent
    claude_dir = lib_dir.parent
    memory_dir = claude_dir / "memory"

    if project_id == "ephemeral":
        return memory_dir / "ephemeral"

    return memory_dir / "projects" / project_id


def get_global_memory_dir() -> Path:
    """Get the global (cross-project) memory directory."""
    lib_dir = Path(__file__).resolve().parent
    claude_dir = lib_dir.parent
    return claude_dir / "memory" / "global"


# =============================================================================
# PROJECT REGISTRY
# =============================================================================


def get_project_index_path() -> Path:
    """Get path to project index file."""
    lib_dir = Path(__file__).resolve().parent
    claude_dir = lib_dir.parent
    return claude_dir / "memory" / "projects" / "_index.json"


def load_project_index() -> dict:
    """Load project index with last-active timestamps."""
    index_path = get_project_index_path()
    if index_path.exists():
        try:
            with open(index_path) as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {"projects": {}}


def save_project_index(index: dict):
    """Save project index."""
    index_path = get_project_index_path()
    index_path.parent.mkdir(parents=True, exist_ok=True)
    with open(index_path, "w") as f:
        json.dump(index, f, indent=2)


def register_project_activity(context: ProjectContext):
    """Register activity for a project (updates last-active timestamp)."""

    if context.project_type == "ephemeral":
        return

    index = load_project_index()
    index["projects"][context.project_id] = {
        "name": context.project_name,
        "root_path": context.root_path,
        "language": context.language,
        "framework": context.framework,
        "last_active": time.time(),
        "detection_method": context.detection_method,
    }
    save_project_index(index)


def get_stale_projects(max_age_days: int = 7) -> list[str]:
    """Get list of project IDs that haven't been active recently."""

    index = load_project_index()
    cutoff = time.time() - (max_age_days * 86400)

    stale = []
    for project_id, info in index.get("projects", {}).items():
        if info.get("last_active", 0) < cutoff:
            stale.append(project_id)

    return stale


# =============================================================================
# CONVENIENCE
# =============================================================================


def get_current_project() -> ProjectContext:
    """Get current project context and register activity.

    This is the main entry point for hooks to get project context.
    """
    context = detect_project()
    register_project_activity(context)
    return context


if __name__ == "__main__":
    # Test detection
    ctx = detect_project()
    print(json.dumps(asdict(ctx), indent=2))
