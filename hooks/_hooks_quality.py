"""
Quality gate PostToolUse hooks.

Code quality checks, UI verification, toolchain suggestions.
Priority range: 22-50
"""

import _lib_path  # noqa: F401
import re
from pathlib import Path

from _hook_registry import register_hook
from _hook_result import HookResult
from _cooldown import (
    assumption_cooldown,
    mutation_cooldown,
    toolchain_keyed,
    large_file_keyed,
    tool_awareness_keyed,
    crawl4ai_promo_keyed,
)
from _patterns import is_scratch_path
from _config import get_magic_number

from session_state import SessionState, get_adaptive_threshold, record_threshold_trigger

# Quality scanner (ruff + radon)
try:
    from _quality_scanner import scan_file as quality_scan_file, format_report

    QUALITY_SCANNER_AVAILABLE = True
except ImportError:
    QUALITY_SCANNER_AVAILABLE = False
    quality_scan_file = None
    format_report = None


# Assumption detection patterns
_ASSUMPTION_PATTERNS = [
    (re.compile(r"\bNone\b"), "Assuming value is not None - verify nullability"),
    (re.compile(r"\[0\]|\[-1\]"), "Assuming collection is non-empty - check edge case"),
    (
        re.compile(r"\.get\([^,)]+\)"),
        "Using .get() - verify default behavior is correct",
    ),
    (re.compile(r"try:\s*\n\s*\w"), "Assuming exception handling covers all cases"),
    (re.compile(r"await\s+\w+"), "Assuming async operation succeeds - handle failures"),
    (re.compile(r"open\(|Path\(.*\)\.read"), "Assuming file exists and is readable"),
    (re.compile(r"json\.loads|JSON\.parse"), "Assuming valid JSON input"),
    (re.compile(r'\[\s*["\'][^"\']+["\']\s*\]'), "Assuming key exists in dict/object"),
]

# UI file detection patterns
_UI_FILE_PATTERNS = [
    re.compile(r"\.css$", re.IGNORECASE),
    re.compile(r"\.scss$", re.IGNORECASE),
    re.compile(r"\.less$", re.IGNORECASE),
    re.compile(r"\.sass$", re.IGNORECASE),
    re.compile(r"style", re.IGNORECASE),
    re.compile(r"theme", re.IGNORECASE),
    re.compile(r"\.tsx$", re.IGNORECASE),
    re.compile(r"\.vue$", re.IGNORECASE),
    re.compile(r"\.svelte$", re.IGNORECASE),
]

# Style content patterns
_STYLE_CONTENT_PATTERNS = [
    re.compile(r"className\s*="),
    re.compile(r"style\s*=\s*\{"),
    re.compile(r"styled\."),
    re.compile(r"css`"),
    re.compile(r"@apply\s+"),
    re.compile(r"sx\s*=\s*\{"),
    re.compile(r'class\s*=\s*["\'][\w\s-]+["\']'),
    re.compile(r"(background|color|margin|padding|display|flex|grid|width|height)\s*:"),
]

# React/JS mutation patterns
_JS_MUTATION_PATTERNS = [
    (
        re.compile(r"\.(push|pop|shift|unshift|splice)\s*\("),
        "Array mutation ({0}) - use spread: [...arr, item]",
    ),
    (re.compile(r"\.sort\s*\(\s*\)"), "In-place sort - use [...arr].sort()"),
    (re.compile(r"\.reverse\s*\(\s*\)"), "In-place reverse - use [...arr].reverse()"),
    (
        re.compile(r"set[A-Z]\w*\(\s*\w+\s*\.\s*\w+\s*="),
        "State mutation in setter - use spread: setState({{...prev, key: val}})",
    ),
]

# Python mutation patterns - now AST-based in _ast_utils.find_mutable_defaults()

# Spread operator check for JS mutation guard
_SPREAD_CHECK = re.compile(r"\[\.\.\.\w+\]\s*$")


# -----------------------------------------------------------------------------
# ASSUMPTION CHECK (priority 22) - Heuristic-based, no Groq call
# -----------------------------------------------------------------------------


@register_hook("assumption_check", "Edit|Write", priority=22)
def check_assumptions(
    data: dict, state: SessionState, runner_state: dict
) -> HookResult:
    """Surface hidden assumptions in code changes (heuristic-based)."""
    tool_input = data.get("tool_input", {})
    file_path = tool_input.get("file_path", "")

    # Skip scratch/temp files
    if is_scratch_path(file_path):
        return HookResult.none()

    code = tool_input.get("new_string", "") or tool_input.get("content", "")
    if not code or len(code) < 100:
        return HookResult.none()

    # Check cooldown (don't spam)
    if assumption_cooldown.is_active():
        return HookResult.none()

    # Find assumptions (use pre-compiled patterns)
    found = []
    for pattern, assumption in _ASSUMPTION_PATTERNS:
        if pattern.search(code):
            found.append(assumption)
            if len(found) >= 2:
                break

    if found:
        assumption_cooldown.reset()
        return HookResult.with_context(
            "🤔 **ASSUMPTION CHECK**:\n" + "\n".join(f"  • {a}" for a in found[:2])
        )

    return HookResult.none()


# -----------------------------------------------------------------------------
# VERIFICATION REMINDER (priority 25)
# -----------------------------------------------------------------------------


@register_hook("verification_reminder", "Edit|Write|MultiEdit", priority=25)
def check_verification_reminder(
    data: dict, state: SessionState, runner_state: dict
) -> HookResult:
    """Remind to verify after fix iterations."""
    tool_input = data.get("tool_input", {})
    file_path = tool_input.get("file_path", "")

    fix_indicators = []

    # File edited multiple times
    edit_count = sum(1 for f in state.files_edited if f == file_path)
    if edit_count >= 2:
        fix_indicators.append(f"edited {edit_count}x")

    # Recent errors exist
    if state.errors_unresolved:
        fix_indicators.append("unresolved errors exist")

    # "fix" in filename
    if "fix" in file_path.lower():
        fix_indicators.append("'fix' in filename")

    verify_run = getattr(state, "verify_run", False)

    if fix_indicators and not verify_run:
        return HookResult.with_context(
            f"⚠️ VERIFY REMINDER: {', '.join(fix_indicators)} → run `verify` or tests before claiming fixed"
        )

    return HookResult.none()


# -----------------------------------------------------------------------------
# UI VERIFICATION GATE (priority 30)
# -----------------------------------------------------------------------------


@register_hook("ui_verification_gate", "Edit|Write|MultiEdit", priority=30)
def check_ui_verification(
    data: dict, state: SessionState, runner_state: dict
) -> HookResult:
    """Require browser screenshot after CSS/UI changes."""
    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})
    file_path = tool_input.get("file_path", "")

    content = ""
    if tool_name == "Write":
        content = tool_input.get("content", "")
    elif tool_name == "Edit":
        content = tool_input.get("new_string", "")

    # Use pre-compiled patterns from module level
    indicators = []
    for pattern in _UI_FILE_PATTERNS:
        if pattern.search(file_path):
            indicators.append(f"UI file: {pattern.pattern}")
            break

    for pattern in _STYLE_CONTENT_PATTERNS:
        if pattern.search(content):
            indicators.append("style pattern detected")
            break

    if not indicators:
        return HookResult.none()

    browser_used = getattr(state, "browser_screenshot_taken", False)
    if browser_used:
        return HookResult.none()

    return HookResult.with_context(
        f"📸 UI VERIFY: {', '.join(indicators[:2])} → `browser page screenshot -o .claude/tmp/ui_check.png`"
    )


# -----------------------------------------------------------------------------
# CODE QUALITY GATE (priority 35)
# Uses adaptive thresholds from session_state (v3.7) - self-tuning based on usage
# Fallback defaults if adaptive system unavailable:
# -----------------------------------------------------------------------------

# Fallback defaults (overridden by adaptive thresholds when available)
MAX_METHOD_LINES = 60
MAX_CONDITIONALS = 12
MAX_DEBUG_STATEMENTS = 5
MAX_NESTING_DEPTH = 5

PATTERN_CONDITIONALS = re.compile(
    r"\b(if|elif|else|for|while|except|try|switch|case)\b"
)
PATTERN_TRY_BLOCK = re.compile(r"\b(try\s*:|try\s*\{)")
PATTERN_EXCEPT_BLOCK = re.compile(r"\b(except|catch)\b")
PATTERN_DEBUG_PY = re.compile(r"\bprint\s*\(", re.IGNORECASE)
PATTERN_DEBUG_JS = re.compile(r"\bconsole\.(log|debug|info|warn|error)\s*\(")
PATTERN_N_PLUS_ONE = re.compile(
    r"for\s+.*?\s+in\s+.*?:\s*\n?\s*.*?(query|fetch|load|select|find|get)\s*\(",
    re.MULTILINE | re.IGNORECASE,
)
# Nested loops: Match actual indented nesting (outer loop then indented inner loop)
PATTERN_NESTED_LOOPS = re.compile(
    r"^[ ]{0,8}(for|while)\s+[^\n]+:\s*\n"  # Outer loop
    r"(?:[ ]{4,}[^\n]*\n)*?"  # Skip lines until...
    r"[ ]{4,}(for|while)\s+[^\n]+:",  # Inner loop (more indented)
    re.MULTILINE,
)

# NEW: Additional performance anti-patterns from old system
PATTERN_STRING_CONCAT_LOOP = re.compile(
    r"for\s+.*?[:{]\s*\n?\s*.*?\+=\s*['\"]", re.MULTILINE
)
# Triple loop: Match actual indented nesting, not just 3 keywords anywhere
# Pattern: for/while at col 0-4, then indented for/while, then more indented for/while
PATTERN_TRIPLE_LOOP = re.compile(
    r"^[ ]{0,4}(for|while)\s+[^\n]+:\s*\n"  # Outer loop at indent 0-4
    r"(?:[ ]{4,}[^\n]*\n)*?"  # Skip lines until...
    r"[ ]{4,8}(for|while)\s+[^\n]+:\s*\n"  # Middle loop at indent 4-8
    r"(?:[ ]{8,}[^\n]*\n)*?"  # Skip lines until...
    r"[ ]{8,}(for|while)\s+[^\n]+:",  # Inner loop at indent 8+
    re.MULTILINE,
)
PATTERN_BLOCKING_IO_NODE = re.compile(
    r"\b(readFileSync|writeFileSync|existsSync|execSync)\s*\("
)
PATTERN_BLOCKING_IO_PY = re.compile(
    r"\bopen\s*\([^)]+\)\s*\.\s*read\s*\(\s*\)(?!\s*#.*async)"
)
PATTERN_MAGIC_NUMBERS = re.compile(
    r"(?<![.\w])(?:0x[a-fA-F0-9]+|\d{3,})(?![.\w])"
)  # Numbers >= 100 or hex
PATTERN_TODO_FIXME = re.compile(r"\b(TODO|FIXME|HACK|XXX)\b", re.IGNORECASE)


def _check_structure_patterns(
    code: str, file_path: str, state: SessionState
) -> tuple[list[str], list[tuple[str, int]]]:
    """Check structural code patterns (length, complexity, nesting)."""
    hints = []
    triggered = []

    threshold_lines = get_adaptive_threshold(state, "quality_long_method")
    threshold_complexity = get_adaptive_threshold(state, "quality_high_complexity")
    threshold_nesting = get_adaptive_threshold(state, "quality_deep_nesting")

    # Long method
    lines = code.count("\n") + 1
    if lines > threshold_lines:
        hints.append(f"📏 **Long Code Block**: {lines} lines (<{int(threshold_lines)})")
        triggered.append(("quality_long_method", lines))

    # High complexity
    conditionals = len(PATTERN_CONDITIONALS.findall(code))
    if conditionals > threshold_complexity:
        hints.append(f"🌀 **High Complexity**: {conditionals} conditionals")
        triggered.append(("quality_high_complexity", conditionals))

    # Deep nesting
    max_indent = max(
        (len(ln) - len(ln.lstrip()) for ln in code.split("\n") if ln.strip()), default=0
    )
    nesting_levels = max_indent // 4
    if nesting_levels > threshold_nesting:
        hints.append(f"🪆 **Deep Nesting**: {nesting_levels} levels")
        triggered.append(("quality_deep_nesting", nesting_levels))

    return hints, triggered


def _check_perf_patterns(code: str, file_path: str) -> list[str]:
    """Check performance-related anti-patterns."""
    hints = []
    is_python = file_path.endswith(".py")
    is_js = file_path.endswith((".js", ".ts", ".jsx", ".tsx"))

    # N+1 query
    if PATTERN_N_PLUS_ONE.search(code):
        hints.append("⚡ **Potential N+1**: DB/API call in loop")

    # Nested loops
    if PATTERN_TRIPLE_LOOP.search(code):
        hints.append("🔄 **Triple Nested Loops**: O(n³) complexity!")
    elif PATTERN_NESTED_LOOPS.search(code):
        hints.append("🔄 **Nested Loops**: O(n²) complexity")

    # String concat in loops
    if PATTERN_STRING_CONCAT_LOOP.search(code):
        hints.append("📝 **String Concat in Loop**: Use join() instead")

    # Blocking I/O
    if is_js and PATTERN_BLOCKING_IO_NODE.search(code):
        hints.append("🐌 **Blocking I/O**: Use async fs methods")
    elif is_python and PATTERN_BLOCKING_IO_PY.search(code):
        hints.append("🐌 **Blocking Read**: Use `with open()` pattern")

    return hints


def _check_quality_markers(
    code: str, file_path: str, state: SessionState
) -> tuple[list[str], list[tuple[str, int]]]:
    """Check code quality markers (debug, magic numbers, TODOs)."""
    hints = []
    triggered = []
    is_python = file_path.endswith(".py")
    is_js = file_path.endswith((".js", ".ts", ".jsx", ".tsx"))
    is_cli_tool = "/ops/" in file_path or "/.claude/hooks/" in file_path

    # Missing error handling
    if PATTERN_TRY_BLOCK.search(code) and not PATTERN_EXCEPT_BLOCK.search(code):
        hints.append("⚠️ **Missing Error Handler**: try without catch/except")

    # Debug statements (skip CLI tools)
    threshold_debug = get_adaptive_threshold(state, "quality_debug_statements")
    debug_count = (
        len(PATTERN_DEBUG_PY.findall(code))
        if is_python
        else (len(PATTERN_DEBUG_JS.findall(code)) if is_js else 0)
    )
    if debug_count > threshold_debug and not is_cli_tool:
        hints.append(f"🐛 **Debug Statements**: {debug_count} found")
        triggered.append(("quality_debug_statements", debug_count))

    # Magic numbers
    threshold_magic = get_adaptive_threshold(state, "quality_magic_numbers")
    magic_count = len(PATTERN_MAGIC_NUMBERS.findall(code))
    if magic_count > threshold_magic:
        hints.append(f"🔢 **Magic Numbers**: {magic_count} literals")
        triggered.append(("quality_magic_numbers", magic_count))

    # Tech debt markers
    threshold_debt = get_adaptive_threshold(state, "quality_tech_debt_markers")
    todo_count = len(PATTERN_TODO_FIXME.findall(code))
    if todo_count > threshold_debt:
        hints.append(f"📝 **Tech Debt**: {todo_count} TODO/FIXME markers")
        triggered.append(("quality_tech_debt_markers", todo_count))

    return hints, triggered


@register_hook("code_quality_gate", "Edit|Write", priority=35)
def check_code_quality(
    data: dict, state: SessionState, runner_state: dict
) -> HookResult:
    """Detect code quality anti-patterns with adaptive thresholds."""
    tool_input = data.get("tool_input", {})
    file_path = tool_input.get("file_path", "")

    code_extensions = (
        ".py",
        ".js",
        ".ts",
        ".jsx",
        ".tsx",
        ".go",
        ".rs",
        ".java",
        ".rb",
        ".sh",
    )
    if not file_path.endswith(code_extensions):
        return HookResult.none()

    code = tool_input.get("content", "") or tool_input.get("new_string", "")
    if not code or len(code) < 50:
        return HookResult.none()

    # Collect hints from specialized checkers
    hints = []
    triggered_patterns = []

    struct_hints, struct_triggered = _check_structure_patterns(code, file_path, state)
    hints.extend(struct_hints)
    triggered_patterns.extend(struct_triggered)

    hints.extend(_check_perf_patterns(code, file_path))

    marker_hints, marker_triggered = _check_quality_markers(code, file_path, state)
    hints.extend(marker_hints)
    triggered_patterns.extend(marker_triggered)

    if hints:
        for pattern_name, value in triggered_patterns:
            record_threshold_trigger(state, pattern_name, value)
        return HookResult.with_context(
            "🔍 **Code Quality Check**:\n" + "\n".join(hints[:4])
        )

    return HookResult.none()


# -----------------------------------------------------------------------------
# QUALITY SCANNER (priority 36) - ruff + radon code quality
# -----------------------------------------------------------------------------


@register_hook("quality_scanner", "Edit|Write", priority=36)
def check_quality_scan(
    data: dict, state: SessionState, runner_state: dict
) -> HookResult:
    """Scan code for quality issues using ruff (lint) and radon (complexity).

    Fast rule-based analysis - no ML model required.
    Advisory only - warns but doesn't block.
    """
    if not QUALITY_SCANNER_AVAILABLE or quality_scan_file is None:
        return HookResult.none()

    tool_input = data.get("tool_input", {})
    file_path = tool_input.get("file_path", "")

    # Only scan Python files (ruff/radon are Python-focused)
    if not file_path.endswith(".py"):
        return HookResult.none()

    # Skip scratch/tmp files
    if is_scratch_path(file_path):
        return HookResult.none()

    # Scan file for quality issues
    result = quality_scan_file(file_path, complexity_threshold="C")

    if result is None:
        return HookResult.none()

    # Quality issues found - advisory warning
    report = format_report(result)
    if report:
        return HookResult.with_context(report)

    return HookResult.none()


# -----------------------------------------------------------------------------
# STATE MUTATION GUARD (priority 37) - React/JS + Python anti-patterns
# -----------------------------------------------------------------------------


def _check_js_mutations(code: str) -> list[str]:
    """Check JS/TS code for state mutation anti-patterns."""
    warnings = []
    for pattern, msg in _JS_MUTATION_PATTERNS:
        match = pattern.search(code)
        if not match:
            continue
        # Skip if clearly on spread [...arr].sort()
        if match.group(0) in (".sort()", ".reverse()"):
            context = code[max(0, match.start() - 10) : match.start()]
            if _SPREAD_CHECK.search(context):
                continue
        try:
            warnings.append(
                msg.format(match.group(1) if match.lastindex else match.group(0))
            )
        except (IndexError, AttributeError):
            warnings.append(msg.format("method"))
    return warnings


def _check_py_mutations(code: str) -> list[str]:
    """Check Python code for mutable default anti-patterns."""
    from _ast_utils import find_mutable_defaults

    warnings = []
    for func_name, line, mtype in find_mutable_defaults(code)[:2]:
        warnings.append(
            f"Mutable default {mtype} in {func_name}() - use None and set in body"
        )
    return warnings


@register_hook("state_mutation_guard", "Edit|Write", priority=37)
def check_state_mutations(
    data: dict, state: SessionState, runner_state: dict
) -> HookResult:
    """Detect state mutation anti-patterns in React/JS and Python."""
    tool_input = data.get("tool_input", {})
    file_path = tool_input.get("file_path", "")

    if is_scratch_path(file_path) or mutation_cooldown.is_active():
        return HookResult.none()

    code = tool_input.get("new_string", "") or tool_input.get("content", "")
    if not code or len(code) < 50:
        return HookResult.none()

    # Dispatch to language-specific checker
    if file_path.endswith((".js", ".ts", ".jsx", ".tsx")):
        warnings = _check_js_mutations(code)
    elif file_path.endswith(".py"):
        warnings = _check_py_mutations(code)
    else:
        return HookResult.none()

    if warnings:
        mutation_cooldown.reset()
        return HookResult.with_context(
            "⚠️ **State Mutation Warning**:\n"
            + "\n".join(f"  • {w}" for w in warnings[:2])
        )

    return HookResult.none()


# -----------------------------------------------------------------------------
# DEV TOOLCHAIN SUGGESTIONS (priority 40) - Language-specific lint/format/check
# -----------------------------------------------------------------------------

# Language -> (formatter, linter, typechecker)
DEV_TOOLCHAIN = {
    ".py": ("ruff format {file}", "ruff check --fix {file}", "mypy {file}"),
    ".ts": (
        "npx prettier --write {file}",
        "npx eslint --fix {file}",
        "npx tsc --noEmit",
    ),
    ".tsx": (
        "npx prettier --write {file}",
        "npx eslint --fix {file}",
        "npx tsc --noEmit",
    ),
    ".js": ("npx prettier --write {file}", "npx eslint --fix {file}", None),
    ".jsx": ("npx prettier --write {file}", "npx eslint --fix {file}", None),
    ".json": ("npx prettier --write {file}", None, None),
    ".css": ("npx prettier --write {file}", None, None),
    ".scss": ("npx prettier --write {file}", None, None),
    ".html": ("npx prettier --write {file}", None, None),
    ".md": ("npx prettier --write {file}", None, None),
    ".yaml": ("npx prettier --write {file}", None, None),
    ".yml": ("npx prettier --write {file}", None, None),
}


@register_hook("dev_toolchain_suggest", "Edit|Write", priority=40)
def check_dev_toolchain(
    data: dict, state: SessionState, runner_state: dict
) -> HookResult:
    """Suggest language-appropriate dev tools after edits."""
    tool_input = data.get("tool_input", {})
    file_path = tool_input.get("file_path", "")

    if is_scratch_path(file_path):
        return HookResult.none()

    # Find matching extension
    ext = None
    for e in DEV_TOOLCHAIN:
        if file_path.endswith(e):
            ext = e
            break

    if not ext:
        return HookResult.none()

    # Check cooldown per extension (5 min per language)
    if toolchain_keyed.is_active(ext):
        return HookResult.none()

    formatter, linter, typechecker = DEV_TOOLCHAIN[ext]
    suggestions = []

    if formatter:
        suggestions.append(f"Format: `{formatter.format(file=Path(file_path).name)}`")
    if linter:
        suggestions.append(f"Lint: `{linter.format(file=Path(file_path).name)}`")
    if typechecker:
        suggestions.append(f"Typecheck: `{typechecker}`")

    if suggestions:
        toolchain_keyed.reset(ext)
        return HookResult.with_context(
            f"🛠️ **Dev Tools** ({ext}):\n  " + "\n  ".join(suggestions[:2])
        )

    return HookResult.none()


# -----------------------------------------------------------------------------
# LARGE FILE HELPER (priority 45) - Line range guidance for big files
# -----------------------------------------------------------------------------

LARGE_FILE_THRESHOLD = get_magic_number("large_file_threshold", 500)


@register_hook("large_file_helper", "Read", priority=45)
def check_large_file(data: dict, state: SessionState, runner_state: dict) -> HookResult:
    """Provide line range guidance for large files."""
    tool_input = data.get("tool_input", {})
    tool_result = data.get("tool_result", {})
    file_path = tool_input.get("file_path", "")

    if not file_path:
        return HookResult.none()

    # Guard against non-dict results
    if not isinstance(tool_result, dict):
        return HookResult.none()

    # Check if file is large (estimate from output)
    output = tool_result.get("output", "")
    line_count = output.count("\n")

    if line_count < LARGE_FILE_THRESHOLD:
        return HookResult.none()

    # Check cooldown per file (10 min)
    if large_file_keyed.is_active(file_path):
        return HookResult.none()

    large_file_keyed.reset(file_path)
    filename = Path(file_path).name
    return HookResult.with_context(
        f"📄 **Large File** ({line_count}+ lines): `{filename}`\n"
        f"  For edits, use line-range reads: `Read {filename} lines X-Y`\n"
        f"  Look for section markers: `// === SECTION ===` or `# --- SECTION ---`"
    )


# -----------------------------------------------------------------------------
# CRAWL4AI PROMOTION (priority 48) - Suggest crawl4ai over WebFetch
# -----------------------------------------------------------------------------


@register_hook("crawl4ai_promo", "WebFetch", priority=48)
def promote_crawl4ai(data: dict, state: SessionState, runner_state: dict) -> HookResult:
    """Promote crawl4ai MCP when WebFetch is used - crawl4ai is superior for web content."""
    tool_input = data.get("tool_input", {})
    url = tool_input.get("url", "")

    if not url:
        return HookResult.none()

    # Extract domain for keyed cooldown
    domain_match = re.search(r"https?://([^/]+)", url)
    domain = domain_match.group(1) if domain_match else "unknown"

    # Skip if recently promoted for this domain
    if crawl4ai_promo_keyed.is_active(domain):
        return HookResult.none()

    crawl4ai_promo_keyed.reset(domain)

    return HookResult.with_context(
        "🌟 **Crawl4AI Available** - Superior to WebFetch:\n"
        "  • Full JavaScript rendering (SPAs, dynamic content)\n"
        "  • Bypasses Cloudflare, bot detection, CAPTCHAs\n"
        "  • Returns clean LLM-friendly markdown\n"
        "  → `mcp__crawl4ai__crawl` for this URL\n"
        "  → `mcp__crawl4ai__search` to discover related URLs"
    )


# -----------------------------------------------------------------------------
# TOOL AWARENESS (priority 50) - Remind about available tools
# -----------------------------------------------------------------------------

TOOL_AWARENESS_PATTERNS = {
    "playwright": {
        "pattern": re.compile(
            r"\b(manual.*test|test.*manual|browser.*test|click|navigate|form|button|webpage|e2e|integration test|screenshot)\b",
            re.IGNORECASE,
        ),
        "reminder": "🎭 **Playwright Available**: Use `mcp__playwright__*` tools for browser automation instead of manual testing.",
        "threshold": 2,
    },
    "pal_mcp": {
        "pattern": re.compile(
            r"\b(uncertain|not sure|complex|difficult|stuck|investigate|how to|unsure|maybe)\b",
            re.IGNORECASE,
        ),
        "reminder": "🤝 **PAL MCP Available**: `mcp__pal__chat/thinkdeep/debug` for deep analysis when uncertain.",
        "threshold": 3,
    },
    "websearch": {
        "pattern": re.compile(
            r"\b(latest|recent|current|new version|updated|documentation|best practice|2024|2025)\b",
            re.IGNORECASE,
        ),
        "reminder": "🔍 **WebSearch Available**: Search for latest docs/patterns instead of relying on training data.",
        "threshold": 2,
    },
    "task_agent": {
        "pattern": re.compile(
            r"\b(then|and then|after that|next|also|first.*then)\b", re.IGNORECASE
        ),
        "reminder": "🤖 **Task Agent**: For 3+ sequential tasks, use parallel Task agents for speed.",
        "threshold": 4,
    },
}


@register_hook("tool_awareness", "Read|Bash|Task", priority=50)
def check_tool_awareness(
    data: dict, state: SessionState, runner_state: dict
) -> HookResult:
    """Remind about available tools when relevant patterns detected."""
    tool_result = data.get("tool_result", {})
    output = (
        tool_result.get("output", "")
        if isinstance(tool_result, dict)
        else str(tool_result)
    )

    if not output or len(output) < 50:
        return HookResult.none()

    for tool_name, config in TOOL_AWARENESS_PATTERNS.items():
        # Skip if recently reminded (keyed cooldown)
        if tool_awareness_keyed.is_active(tool_name):
            continue

        matches = len(config["pattern"].findall(output))
        if matches >= config["threshold"]:
            tool_awareness_keyed.reset(tool_name)
            return HookResult.with_context(config["reminder"])

    return HookResult.none()
