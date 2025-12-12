#!/usr/bin/env python3
"""
God Component Detector - Prevents monolithic files.

Uses three layers:
1. Allowlist - Known-large file patterns, explicit markers
2. Complexity - AST-based function/import counting
3. Churn - Edit frequency tracking
"""

import ast
import re
from pathlib import Path
from typing import Optional
from dataclasses import dataclass

# =============================================================================
# CONFIGURATION
# =============================================================================

# Line thresholds
LINE_THRESHOLD_WARN = 500
LINE_THRESHOLD_BLOCK = 1000

# Complexity thresholds (used with AND logic)
FUNCTION_THRESHOLD = 20
IMPORT_THRESHOLD = 30
CLASS_THRESHOLD = 8

# Churn threshold (edits in session before escalating)
CHURN_THRESHOLD = 3

# Patterns that are allowed to be large (bypass all checks)
ALLOWLIST_PATTERNS = [
    # Data/config files
    "*.json",
    "*.yaml",
    "*.yml",
    "*.toml",
    "*.lock",
    "*.csv",
    # Style files
    "*.css",
    "*.scss",
    "*.less",
    # Generated/build output
    "*/dist/*",
    "*/build/*",
    "*/.next/*",
    "*/node_modules/*",
    "*/__pycache__/*",
    "*.min.js",
    "*.min.css",
    "*.bundle.*",
    "*.generated.*",
    # Test fixtures
    "*/fixtures/*",
    "*/testdata/*",
    "*/__fixtures__/*",
    # Type definitions (often large)
    "*.d.ts",
    # Migrations (each is independent)
    "*/migrations/*",
]

# Explicit marker to allow large files
# Usage: # LARGE_FILE_OK: This is a constants file with many entries
ALLOWLIST_MARKER = r"#\s*LARGE_FILE_OK:\s*(.+)"


@dataclass
class ComplexityMetrics:
    """Complexity analysis results."""

    lines: int
    functions: int
    classes: int
    imports: int
    max_depth: int  # Nesting depth
    has_allowlist_marker: bool
    marker_reason: str = ""


@dataclass
class DetectionResult:
    """Result of God component detection."""

    is_god_component: bool
    severity: str  # "ok", "warn", "block"
    reason: str
    metrics: Optional[ComplexityMetrics] = None
    suggestions: list = None

    def __post_init__(self):
        if self.suggestions is None:
            self.suggestions = []


def _matches_allowlist(file_path: str) -> bool:
    """Check if file matches allowlist patterns."""
    from fnmatch import fnmatch

    path = Path(file_path)
    path_str = str(path)
    name = path.name

    for pattern in ALLOWLIST_PATTERNS:
        if fnmatch(name, pattern) or fnmatch(path_str, pattern):
            return True

    return False


def _check_allowlist_marker(content: str) -> tuple[bool, str]:
    """Check for explicit allowlist marker in file."""
    for line in content.split("\n")[:20]:  # Check first 20 lines
        match = re.search(ALLOWLIST_MARKER, line)
        if match:
            return True, match.group(1).strip()
    return False, ""


def _count_lines(content: str) -> int:
    """Count total non-empty lines (including comments).

    Comments still contribute to file size and cognitive load,
    so we count them. Only blank lines are excluded.
    """
    return sum(1 for line in content.split("\n") if line.strip())


def analyze_python_complexity(content: str) -> ComplexityMetrics:
    """Analyze Python file complexity using AST."""
    lines = _count_lines(content)
    has_marker, marker_reason = _check_allowlist_marker(content)

    try:
        tree = ast.parse(content)
    except SyntaxError:
        # Can't parse - return line count only
        return ComplexityMetrics(
            lines=lines,
            functions=0,
            classes=0,
            imports=0,
            max_depth=0,
            has_allowlist_marker=has_marker,
            marker_reason=marker_reason,
        )

    functions = 0
    classes = 0
    imports = 0
    max_depth = 0

    def visit(node, depth=0):
        nonlocal functions, classes, imports, max_depth
        max_depth = max(max_depth, depth)

        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions += 1
        elif isinstance(node, ast.ClassDef):
            classes += 1
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            imports += 1

        for child in ast.iter_child_nodes(node):
            visit(child, depth + 1)

    visit(tree)

    return ComplexityMetrics(
        lines=lines,
        functions=functions,
        classes=classes,
        imports=imports,
        max_depth=max_depth,
        has_allowlist_marker=has_marker,
        marker_reason=marker_reason,
    )


def analyze_typescript_complexity(content: str) -> ComplexityMetrics:
    """Analyze TypeScript/JavaScript complexity (regex-based, less accurate)."""
    lines = _count_lines(content)
    has_marker, marker_reason = _check_allowlist_marker(content)

    # Count functions (various patterns)
    function_patterns = [
        r"\bfunction\s+\w+",  # function foo()
        r"\bconst\s+\w+\s*=\s*(?:async\s*)?\([^)]*\)\s*=>",  # const foo = () =>
        r"\b\w+\s*:\s*(?:async\s*)?\([^)]*\)\s*=>",  # foo: () =>
        r"\basync\s+function",  # async function
    ]
    functions = sum(len(re.findall(p, content)) for p in function_patterns)

    # Count classes
    classes = len(re.findall(r"\bclass\s+\w+", content))

    # Count imports
    imports = len(re.findall(r"^import\s+", content, re.MULTILINE))

    # Estimate nesting depth (count max consecutive indentation)
    max_depth = 0
    for line in content.split("\n"):
        if line.strip():
            indent = len(line) - len(line.lstrip())
            depth = indent // 2  # Assume 2-space indent
            max_depth = max(max_depth, depth)

    return ComplexityMetrics(
        lines=lines,
        functions=functions,
        classes=classes,
        imports=imports,
        max_depth=max_depth,
        has_allowlist_marker=has_marker,
        marker_reason=marker_reason,
    )


def analyze_complexity(file_path: str, content: str) -> ComplexityMetrics:
    """Analyze file complexity based on extension."""
    ext = Path(file_path).suffix.lower()

    if ext == ".py":
        return analyze_python_complexity(content)
    elif ext in (".ts", ".tsx", ".js", ".jsx"):
        return analyze_typescript_complexity(content)
    else:
        # Generic analysis
        lines = _count_lines(content)
        has_marker, marker_reason = _check_allowlist_marker(content)
        return ComplexityMetrics(
            lines=lines,
            functions=0,
            classes=0,
            imports=0,
            max_depth=0,
            has_allowlist_marker=has_marker,
            marker_reason=marker_reason,
        )


def detect_god_component(
    file_path: str,
    content: str,
    edit_count: int = 0,
) -> DetectionResult:
    """
    Detect if a file is becoming a God component.

    Args:
        file_path: Path to the file
        content: File content (after proposed edit)
        edit_count: Number of times this file has been edited this session

    Returns:
        DetectionResult with severity and suggestions
    """
    # Layer 1: Allowlist check
    if _matches_allowlist(file_path):
        return DetectionResult(
            is_god_component=False,
            severity="ok",
            reason="File matches allowlist pattern",
        )

    # Analyze complexity
    metrics = analyze_complexity(file_path, content)

    # Check for explicit marker
    if metrics.has_allowlist_marker:
        return DetectionResult(
            is_god_component=False,
            severity="ok",
            reason=f"Explicitly allowed: {metrics.marker_reason}",
            metrics=metrics,
        )

    # Layer 2: Complexity analysis
    is_complex = (
        metrics.functions > FUNCTION_THRESHOLD
        or metrics.imports > IMPORT_THRESHOLD
        or metrics.classes > CLASS_THRESHOLD
    )

    # Determine severity
    if metrics.lines > LINE_THRESHOLD_BLOCK and is_complex:
        # Layer 3: Churn escalation
        if edit_count >= CHURN_THRESHOLD:
            return DetectionResult(
                is_god_component=True,
                severity="block",
                reason=(
                    f"God component detected: {metrics.lines} lines, "
                    f"{metrics.functions} functions, {metrics.imports} imports. "
                    f"Edited {edit_count}x this session - time to refactor!"
                ),
                metrics=metrics,
                suggestions=_generate_suggestions(file_path, metrics),
            )
        else:
            return DetectionResult(
                is_god_component=True,
                severity="block",
                reason=(
                    f"File exceeds complexity threshold: {metrics.lines} lines, "
                    f"{metrics.functions} functions, {metrics.imports} imports"
                ),
                metrics=metrics,
                suggestions=_generate_suggestions(file_path, metrics),
            )

    elif metrics.lines > LINE_THRESHOLD_WARN and is_complex:
        return DetectionResult(
            is_god_component=False,
            severity="warn",
            reason=(
                f"File approaching God component: {metrics.lines} lines, "
                f"{metrics.functions} functions"
            ),
            metrics=metrics,
            suggestions=_generate_suggestions(file_path, metrics),
        )

    elif metrics.lines > LINE_THRESHOLD_BLOCK:
        # Large but not complex - just warn
        return DetectionResult(
            is_god_component=False,
            severity="warn",
            reason=f"Large file ({metrics.lines} lines) but low complexity - consider splitting",
            metrics=metrics,
        )

    return DetectionResult(
        is_god_component=False,
        severity="ok",
        reason="File within acceptable limits",
        metrics=metrics,
    )


def _generate_suggestions(file_path: str, metrics: ComplexityMetrics) -> list[str]:
    """Generate refactoring suggestions based on metrics."""
    suggestions = []

    if metrics.functions > FUNCTION_THRESHOLD:
        suggestions.append(
            f"Extract related functions into separate modules "
            f"({metrics.functions} functions is too many)"
        )

    if metrics.imports > IMPORT_THRESHOLD:
        suggestions.append(
            f"High import count ({metrics.imports}) suggests mixed concerns - "
            f"split by responsibility"
        )

    if metrics.classes > CLASS_THRESHOLD:
        suggestions.append(
            f"Multiple classes ({metrics.classes}) should each have their own file"
        )

    if metrics.max_depth > 6:
        suggestions.append(
            f"Deep nesting ({metrics.max_depth} levels) - extract nested logic"
        )

    # File-specific suggestions
    name = Path(file_path).stem.lower()
    if "util" in name or "helper" in name:
        suggestions.append(
            "Utils/helpers tend to grow unbounded - group by domain instead"
        )
    if "index" in name:
        suggestions.append("Index files should just re-export, not contain logic")

    if not suggestions:
        suggestions.append(
            "Add `# LARGE_FILE_OK: <reason>` at top if this file must be large"
        )

    return suggestions


def format_detection_message(result: DetectionResult) -> str:
    """Format detection result for hook output."""
    if result.severity == "ok":
        return ""

    icon = "⚠️" if result.severity == "warn" else "🚫"

    lines = [
        f"{icon} **GOD COMPONENT {'WARNING' if result.severity == 'warn' else 'BLOCKED'}**"
    ]
    lines.append("")
    lines.append(result.reason)

    if result.metrics:
        m = result.metrics
        lines.append("")
        lines.append(
            f"📊 Metrics: {m.lines} lines, {m.functions} functions, {m.imports} imports, {m.classes} classes"
        )

    if result.suggestions:
        lines.append("")
        lines.append("💡 **Suggestions:**")
        for s in result.suggestions:
            lines.append(f"  • {s}")

    return "\n".join(lines)
