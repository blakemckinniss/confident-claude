#!/usr/bin/env python3
"""
Test Detection Utilities (v4.20) - Detect test files and test execution.

Provides utilities for:
- Detecting test files in a project (with caching)
- Identifying test frameworks in use
- Matching production files to their test files
- Detecting test execution in bash commands/output
"""

import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# =============================================================================
# PROJECT-LEVEL TEST FILE CACHE (v4.20.1)
# =============================================================================

# Cache TTL in seconds (5 minutes) - balances freshness vs scan cost
CACHE_TTL_SECONDS = 300.0


@dataclass
class TestFileCache:
    """Cache for test file detection results per project.

    Avoids repeated filesystem scans by caching results with TTL.
    Invalidates automatically when:
    - TTL expires (default 5 minutes)
    - Test files are added/removed via notify methods
    """

    # Cache storage: {project_root: {framework: [test_files]}}
    _cache: dict[str, dict[str, list[Path]]] = field(default_factory=dict)

    # Timestamps: {project_root: last_scan_time}
    _timestamps: dict[str, float] = field(default_factory=dict)

    # TTL in seconds
    ttl_seconds: float = CACHE_TTL_SECONDS

    # Quick lookup: {project_root: bool} for has_tests check
    _has_tests_cache: dict[str, bool] = field(default_factory=dict)

    def get(self, root: Path) -> Optional[dict[str, list[Path]]]:
        """Get cached test files for a project, or None if cache miss/expired."""
        root_str = str(root.resolve())

        if root_str not in self._cache:
            return None

        # Check TTL
        cached_time = self._timestamps.get(root_str, 0)
        if time.time() - cached_time > self.ttl_seconds:
            # Expired - remove from cache
            self._cache.pop(root_str, None)
            self._timestamps.pop(root_str, None)
            self._has_tests_cache.pop(root_str, None)
            return None

        return self._cache[root_str]

    def set(self, root: Path, test_files: dict[str, list[Path]]) -> None:
        """Cache test files for a project."""
        root_str = str(root.resolve())
        self._cache[root_str] = test_files
        self._timestamps[root_str] = time.time()
        self._has_tests_cache[root_str] = any(files for files in test_files.values())

    def has_tests(self, root: Path) -> Optional[bool]:
        """Quick check if project has tests (from cache). None if not cached."""
        root_str = str(root.resolve())

        if root_str not in self._has_tests_cache:
            return None

        # Check TTL
        cached_time = self._timestamps.get(root_str, 0)
        if time.time() - cached_time > self.ttl_seconds:
            return None

        return self._has_tests_cache[root_str]

    def invalidate(self, root: Path) -> None:
        """Invalidate cache for a project (e.g., when test files change)."""
        root_str = str(root.resolve())
        self._cache.pop(root_str, None)
        self._timestamps.pop(root_str, None)
        self._has_tests_cache.pop(root_str, None)

    def notify_test_file_added(self, file_path: Path) -> None:
        """Notify cache that a test file was added - invalidates relevant project."""
        # Find the project root by walking up
        for parent in file_path.parents:
            if (parent / ".git").exists() or (parent / "CLAUDE.md").exists():
                self.invalidate(parent)
                return
        # If no project root found, invalidate based on direct parent
        self.invalidate(file_path.parent)

    def notify_test_file_removed(self, file_path: Path) -> None:
        """Notify cache that a test file was removed - invalidates relevant project."""
        self.notify_test_file_added(file_path)  # Same logic

    def clear(self) -> None:
        """Clear entire cache."""
        self._cache.clear()
        self._timestamps.clear()
        self._has_tests_cache.clear()


# Global cache instance
_test_file_cache = TestFileCache()

# =============================================================================
# TEST FILE PATTERNS
# =============================================================================

# Patterns for detecting test files by language/framework
TEST_FILE_PATTERNS: dict[str, list[str]] = {
    "python": [
        "**/test_*.py",
        "**/*_test.py",
        "**/tests/*.py",
        "**/tests/**/*.py",
    ],
    "javascript": [
        "**/*.test.js",
        "**/*.spec.js",
        "**/test/*.js",
        "**/tests/*.js",
        "**/__tests__/*.js",
    ],
    "typescript": [
        "**/*.test.ts",
        "**/*.spec.ts",
        "**/*.test.tsx",
        "**/*.spec.tsx",
        "**/test/*.ts",
        "**/tests/*.ts",
        "**/__tests__/*.ts",
        "**/__tests__/*.tsx",
    ],
    "rust": [
        "**/tests/*.rs",
        "**/tests/**/*.rs",
    ],
    "go": [
        "**/*_test.go",
    ],
}

# Commands that run tests (for detection in bash commands)
TEST_COMMANDS: list[str] = [
    "pytest",
    "python -m pytest",
    "python3 -m pytest",
    "jest",
    "npx jest",
    "npm test",
    "npm run test",
    "yarn test",
    "pnpm test",
    "vitest",
    "npx vitest",
    "cargo test",
    "go test",
    "dotnet test",
    "mvn test",
    "gradle test",
    "rspec",
    "bundle exec rspec",
    "phpunit",
]

# Output patterns indicating test success
TEST_SUCCESS_PATTERNS: list[str] = [
    r"\d+ passed",
    r"tests? passed",
    r"PASSED",
    r"✓.*test",
    r"OK \(\d+ test",
    r"All tests passed",
    r"test result: ok",
    r"Tests:\s+\d+ passed",
]

# Output patterns indicating test failure
TEST_FAILURE_PATTERNS: list[str] = [
    r"\d+ failed",
    r"tests? failed",
    r"FAILED",
    r"✗.*test",
    r"FAIL:",
    r"test result: FAILED",
    r"Tests:\s+\d+ failed",
    r"AssertionError",
]


# =============================================================================
# TEST FILE DETECTION
# =============================================================================


def detect_test_files(
    root: Path, frameworks: Optional[list[str]] = None, use_cache: bool = True
) -> dict[str, list[Path]]:
    """
    Detect test files in a project.

    Args:
        root: Project root directory
        frameworks: Optional list of frameworks to check (e.g., ["python", "typescript"])
                   If None, checks all supported frameworks.
        use_cache: Whether to use cached results (default True)

    Returns:
        Dict mapping framework name to list of test file paths
    """
    if not root.exists() or not root.is_dir():
        return {}

    # Check cache first (only when checking all frameworks)
    if use_cache and frameworks is None:
        cached = _test_file_cache.get(root)
        if cached is not None:
            return cached

    result: dict[str, list[Path]] = {}
    patterns_to_check = (
        TEST_FILE_PATTERNS
        if frameworks is None
        else {k: v for k, v in TEST_FILE_PATTERNS.items() if k in frameworks}
    )

    for framework, patterns in patterns_to_check.items():
        test_files = []
        for pattern in patterns:
            # Use rglob for recursive matching
            try:
                for match in root.glob(pattern):
                    # Skip node_modules, .git, etc.
                    if any(
                        part in match.parts
                        for part in [
                            "node_modules",
                            ".git",
                            "__pycache__",
                            ".venv",
                            "venv",
                            "dist",
                            "build",
                        ]
                    ):
                        continue
                    if match.is_file():
                        test_files.append(match)
            except Exception:
                continue

        if test_files:
            result[framework] = sorted(set(test_files))

    # Update cache (only when checking all frameworks)
    if use_cache and frameworks is None:
        _test_file_cache.set(root, result)

    return result


def has_tests_in_project(root: Path, use_cache: bool = True) -> bool:
    """Quick check if project has any test files (uses cache)."""
    # Try quick cache lookup first
    if use_cache:
        cached_result = _test_file_cache.has_tests(root)
        if cached_result is not None:
            return cached_result

    result = detect_test_files(root, use_cache=use_cache)
    return any(files for files in result.values())


def count_test_files(root: Path) -> int:
    """Count total test files in project."""
    result = detect_test_files(root)
    return sum(len(files) for files in result.values())


# =============================================================================
# TEST FILE MATCHING
# =============================================================================


def is_test_file(path: str | Path) -> bool:
    """Check if a path is a test file."""
    path_str = str(path).lower()
    name = Path(path).name.lower()

    # Direct name patterns
    if name.startswith("test_") or name.endswith("_test.py"):
        return True
    if ".test." in name or ".spec." in name:
        return True
    if name.endswith("_test.go"):
        return True

    # Path patterns
    if "/tests/" in path_str or "/__tests__/" in path_str:
        return True

    return False


def find_corresponding_test(prod_file: Path, root: Path) -> Optional[Path]:
    """
    Find the corresponding test file for a production file.

    Tries common patterns:
    - src/foo.py -> tests/test_foo.py
    - src/foo.ts -> src/foo.test.ts
    - src/foo.js -> src/__tests__/foo.test.js
    """
    stem = prod_file.stem
    suffix = prod_file.suffix
    parent = prod_file.parent

    candidates = []

    if suffix == ".py":
        # Python patterns
        candidates = [
            root / "tests" / f"test_{stem}.py",
            root / "tests" / prod_file.parent.name / f"test_{stem}.py",
            parent / f"test_{stem}.py",
            parent / "tests" / f"test_{stem}.py",
        ]
    elif suffix in (".ts", ".tsx", ".js", ".jsx"):
        # JS/TS patterns
        candidates = [
            parent / f"{stem}.test{suffix}",
            parent / f"{stem}.spec{suffix}",
            parent / "__tests__" / f"{stem}.test{suffix}",
            root / "tests" / f"{stem}.test{suffix}",
        ]
    elif suffix == ".go":
        # Go pattern
        candidates = [
            parent / f"{stem}_test.go",
        ]

    for candidate in candidates:
        if candidate.exists():
            return candidate

    return None


def find_corresponding_impl(test_file: Path, root: Path) -> Optional[Path]:
    """
    Find the corresponding implementation file for a test file.

    Reverse of find_corresponding_test.
    """
    name = test_file.name
    suffix = test_file.suffix
    parent = test_file.parent

    # Extract the base name
    stem = None
    if name.startswith("test_"):
        stem = name[5:].replace(suffix, "")
    elif ".test." in name:
        stem = name.split(".test.")[0]
    elif ".spec." in name:
        stem = name.split(".spec.")[0]
    elif name.endswith("_test.go"):
        stem = name[:-8]

    if not stem:
        return None

    # Try to find the implementation
    candidates = []

    if suffix == ".py":
        candidates = [
            root / "src" / f"{stem}.py",
            root / f"{stem}.py",
            parent.parent / f"{stem}.py",  # tests/test_x.py -> x.py
        ]
    elif suffix in (".ts", ".tsx", ".js", ".jsx"):
        candidates = [
            parent / f"{stem}{suffix}",
            parent.parent / f"{stem}{suffix}",  # __tests__/x.test.ts -> x.ts
            root / "src" / f"{stem}{suffix}",
        ]
    elif suffix == ".go":
        candidates = [
            parent / f"{stem}.go",
        ]

    for candidate in candidates:
        if candidate.exists() and not is_test_file(candidate):
            return candidate

    return None


# =============================================================================
# TEST EXECUTION DETECTION
# =============================================================================


def is_test_command(command: str) -> bool:
    """Check if a bash command is running tests."""
    cmd_lower = command.lower().strip()

    for test_cmd in TEST_COMMANDS:
        if test_cmd in cmd_lower:
            return True

    return False


def detect_test_result(output: str) -> Optional[str]:
    """
    Detect test result from command output.

    Returns:
        "passed" if tests passed
        "failed" if tests failed
        None if can't determine
    """
    # Check for failure first (more specific)
    for pattern in TEST_FAILURE_PATTERNS:
        if re.search(pattern, output, re.IGNORECASE):
            return "failed"

    # Check for success
    for pattern in TEST_SUCCESS_PATTERNS:
        if re.search(pattern, output, re.IGNORECASE):
            return "passed"

    return None


def get_test_framework_from_command(command: str) -> Optional[str]:
    """Extract the test framework name from a command."""
    cmd_lower = command.lower()

    if "pytest" in cmd_lower:
        return "pytest"
    if "jest" in cmd_lower:
        return "jest"
    if "vitest" in cmd_lower:
        return "vitest"
    if "cargo test" in cmd_lower:
        return "cargo"
    if "go test" in cmd_lower:
        return "go"
    if "npm test" in cmd_lower or "yarn test" in cmd_lower:
        return "npm"
    if "rspec" in cmd_lower:
        return "rspec"

    return None


# =============================================================================
# COVERAGE HELPERS
# =============================================================================


def production_file_has_test(prod_file: Path, root: Path) -> bool:
    """Check if a production file has a corresponding test file."""
    return find_corresponding_test(prod_file, root) is not None


def get_untested_production_files(modified_files: list[Path], root: Path) -> list[Path]:
    """
    Get list of modified production files without corresponding tests.

    Args:
        modified_files: List of files modified this session
        root: Project root

    Returns:
        List of production files without tests
    """
    untested = []
    for f in modified_files:
        if is_test_file(f):
            continue
        if not production_file_has_test(f, root):
            untested.append(f)
    return untested
