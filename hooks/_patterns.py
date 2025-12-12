"""
Centralized pattern definitions for hook runners.

Consolidates duplicate patterns used across multiple hooks.
All patterns are pre-compiled at module load for performance.
"""

import re

# =============================================================================
# STUB/INCOMPLETE CODE PATTERNS
# =============================================================================

STUB_PATTERNS = [
    re.compile(r"#\s*TODO\b", re.IGNORECASE),
    re.compile(r"#\s*FIXME\b", re.IGNORECASE),
    re.compile(r"raise\s+NotImplementedError"),
    re.compile(r"pass\s*#"),
    re.compile(r"\.\.\.\s*#"),
    re.compile(r"#\s*stub\b", re.IGNORECASE),
    re.compile(r"#\s*placeholder\b", re.IGNORECASE),
]

STUB_STRINGS = ["# TODO", "# FIXME", "raise NotImplementedError", "pass  #"]

# Byte patterns for binary file scanning (used by stop hooks)
STUB_BYTE_PATTERNS = [
    b"# TODO",
    b"# FIXME",
    b"TODO",
    b"FIXME",
    b"NotImplementedError",
    b"raise NotImplementedError",
    b"pass  #",
    b"...  #",
    b"...",  # Python ellipsis stub
    b"stub",
    b"STUB",
]


def has_stub_pattern(content: str) -> bool:
    """Check if content contains stub/incomplete code patterns."""
    return any(p.search(content) for p in STUB_PATTERNS)


def find_stub_patterns(content: str) -> list[str]:
    """Find all stub patterns in content, return list of matched patterns."""
    found = []
    for pattern in STUB_PATTERNS:
        if pattern.search(content):
            found.append(pattern.pattern)
    return found


# =============================================================================
# FILE EXTENSION PATTERNS
# =============================================================================

CODE_EXTENSIONS = frozenset(
    {
        ".py",
        ".ts",
        ".tsx",
        ".js",
        ".jsx",
        ".rs",
        ".go",
        ".java",
        ".kt",
        ".c",
        ".cpp",
        ".h",
        ".hpp",
        ".cs",
        ".rb",
        ".php",
        ".swift",
        ".scala",
    }
)

CONFIG_EXTENSIONS = frozenset(
    {
        ".json",
        ".yaml",
        ".yml",
        ".toml",
        ".ini",
        ".cfg",
        ".conf",
        ".env",
    }
)

DOC_EXTENSIONS = frozenset({".md", ".txt", ".rst", ".adoc"})

SKIP_EXTENSIONS = frozenset(
    {
        ".md",
        ".txt",
        ".json",
        ".yaml",
        ".yml",
        ".sh",
        ".env",
    }
)

WEB_EXTENSIONS = frozenset({".html", ".css", ".scss", ".less", ".sass"})


def is_code_file(path: str) -> bool:
    """Check if path is a code file."""
    from pathlib import Path

    return Path(path).suffix.lower() in CODE_EXTENSIONS


def is_config_file(path: str) -> bool:
    """Check if path is a config file."""
    from pathlib import Path

    return Path(path).suffix.lower() in CONFIG_EXTENSIONS


def should_skip_file(path: str) -> bool:
    """Check if file should be skipped for certain checks."""
    from pathlib import Path

    return Path(path).suffix.lower() in SKIP_EXTENSIONS


# =============================================================================
# SECURITY PATTERNS
# =============================================================================

SECURITY_FILE_PATTERNS = [
    re.compile(r"auth", re.IGNORECASE),
    re.compile(r"login", re.IGNORECASE),
    re.compile(r"password", re.IGNORECASE),
    re.compile(r"credential", re.IGNORECASE),
    re.compile(r"token", re.IGNORECASE),
    re.compile(r"secret", re.IGNORECASE),
    re.compile(r"jwt", re.IGNORECASE),
    re.compile(r"oauth", re.IGNORECASE),
]

SECURITY_CONTENT_PATTERNS = [
    re.compile(r"password\s*=", re.IGNORECASE),
    re.compile(r"secret\s*=", re.IGNORECASE),
    re.compile(r"\.encrypt\(", re.IGNORECASE),
    re.compile(r"\.decrypt\(", re.IGNORECASE),
    re.compile(r"api[_-]?key\s*=", re.IGNORECASE),
]


def is_security_sensitive_file(path: str) -> bool:
    """Check if file path suggests security-sensitive content."""
    path_lower = path.lower()
    return any(p.search(path_lower) for p in SECURITY_FILE_PATTERNS)


def has_security_content(content: str) -> bool:
    """Check if content contains security-sensitive patterns."""
    return any(p.search(content) for p in SECURITY_CONTENT_PATTERNS)


# =============================================================================
# SCRATCH/TEMP PATH PATTERNS
# =============================================================================

SCRATCH_PATHS = [".claude/tmp/", ".claude/memory/", "/tmp/", ".cache/"]

PROTECTED_PATHS = [".claude/ops/", ".claude/lib/"]


def is_scratch_path(path: str) -> bool:
    """Check if path is in scratch/temp locations."""
    return any(p in path for p in SCRATCH_PATHS)


def is_protected_path(path: str) -> bool:
    """Check if path is in protected locations."""
    return any(p in path for p in PROTECTED_PATHS)


# =============================================================================
# DEFERRAL PATTERNS (anti-patterns for "TODO later")
# =============================================================================

DEFERRAL_PATTERNS = [
    (
        re.compile(r"#\s*(TODO|FIXME):\s*(implement\s+)?later", re.IGNORECASE),
        "TODO later",
    ),
    (re.compile(r"#\s*low\s+priority", re.IGNORECASE), "low priority"),
    (re.compile(r"#\s*nice\s+to\s+have", re.IGNORECASE), "nice to have"),
    (re.compile(r"#\s*could\s+(do|add)\s+later", re.IGNORECASE), "could do later"),
    (re.compile(r"#\s*worth\s+investigating", re.IGNORECASE), "worth investigating"),
    (re.compile(r"#\s*consider\s+adding", re.IGNORECASE), "consider adding"),
]


def find_deferral_pattern(content: str) -> tuple[bool, str]:
    """Check for deferral patterns, return (found, pattern_name)."""
    for pattern, name in DEFERRAL_PATTERNS:
        if pattern.search(content):
            return True, name
    return False, ""


# =============================================================================
# RECURSIVE PATH PATTERNS (anti-patterns for nested duplicates)
# =============================================================================

RECURSIVE_PATTERNS = [
    re.compile(r"\.claude/.*\.claude/"),
    re.compile(r"projects/[^/]+/projects/"),
    re.compile(r"\.claude/tmp/.*\.claude/tmp/"),
]


def is_recursive_path(path: str) -> bool:
    """Check if path has recursive/nested duplicates."""
    return any(p.search(path) for p in RECURSIVE_PATTERNS)
