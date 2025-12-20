#!/usr/bin/env python3
"""
Content Quality Gates.

Gates that validate content being written to files - dangerous patterns,
code quality, documentation theater, security-sensitive code, etc.

Hooks (by priority):
  - content_gate (45): Block dangerous code patterns
  - crawl4ai_preference (47): Suggest crawl4ai over WebFetch
  - god_component_gate (48): Prevent monolithic files
  - gap_detector (50): Require read before edit
  - production_gate (55): Block stubs in production code
  - deferral_gate (60): Block deferral theater language
  - doc_theater_gate (65): Block standalone documentation files
  - root_pollution_gate (70): Block home directory clutter
  - recommendation_gate (75): Warn about duplicate functionality
  - security_claim_gate (80): Require audit for security code
  - epistemic_boundary (85): Catch claims not backed by evidence
  - research_gate (88): Block unverified external libraries
  - import_gate (92): Warn about third-party imports
  - modularization_nudge (95): Remind to modularize
  - curiosity_injection (96): Inject metacognitive prompts
"""

import os
import re
from pathlib import Path

from ._common import register_hook, HookResult, SessionState

# Import logging helper
try:
    from _hooks_state import log_debug
except ImportError:
    def log_debug(component: str, message: str) -> None:
        pass


# =============================================================================
# PATTERNS AND HELPERS
# =============================================================================

# Critical patterns that should ALWAYS be blocked
_CRITICAL_PATTERNS = [
    (re.compile(r"\beval\s*\("), "eval() is dangerous"),
    (re.compile(r"\bexec\s*\("), "exec() is dangerous"),
    (re.compile(r'f["\']SELECT\s+', re.I), "SQL injection risk"),
]

_BLOCK_PATTERNS = [
    (re.compile(r"subprocess\.[^(]+\([^)]*shell\s*=\s*True", re.M), "shell=True risk"),
    (re.compile(r"except\s*:\s*$", re.M), "Bare except"),
    (re.compile(r"from\s+\w+\s+import\s+\*", re.M), "Wildcard import"),
]


def _is_content_exempt_path(file_path: str) -> bool:
    """Check if path is exempt from content checks."""
    return any(
        p in file_path for p in (".claude/lib/", ".claude/hooks/", ".claude/tmp/")
    )


def _check_python_ast(content: str) -> HookResult | None:
    """Check Python content with AST analysis. Returns deny result or None."""
    try:
        from ast_analysis import has_critical_violations

        is_critical, violations = has_critical_violations(content)
        if is_critical:
            msgs = [f"- {v.message} (line {v.line})" for v in violations[:3]]
            return HookResult.deny(
                "**CONTENT BLOCKED** (AST analysis):\n"
                + "\n".join(msgs)
                + "\nFix the vulnerabilities."
            )
    except Exception as e:
        log_debug("content_gate", f"AST analysis failed: {e}")
    return None


def _get_projected_content(
    tool_name: str, tool_input: dict, file_path: str
) -> str | None:
    """Get content that will exist after edit. Returns None if can't determine."""
    path = Path(file_path)
    if tool_name == "Write":
        return tool_input.get("content", "")
    elif tool_name == "Edit":
        if not path.exists():
            return None
        existing = path.read_text()
        old_str = tool_input.get("old_string", "")
        if old_str not in existing:
            return None
        return existing.replace(old_str, tool_input.get("new_string", ""), 1)
    return None


# =============================================================================
# CONTENT GATE (Priority 45) - Block dangerous code patterns
# =============================================================================


@register_hook("content_gate", "Edit|Write", priority=45)
def check_content_gate(data: dict, state: SessionState) -> HookResult:
    """Block dangerous code patterns (eval, SQL injection, etc.)."""
    tool_input = data.get("tool_input", {})
    content = tool_input.get("content", "") or tool_input.get("new_string", "")
    file_path = tool_input.get("file_path", "")

    if not content or not file_path or _is_content_exempt_path(file_path):
        return HookResult.approve()

    if file_path.endswith(".py"):
        if result := _check_python_ast(content):
            return result

    for pattern, message in _CRITICAL_PATTERNS:
        if pattern.search(content):
            return HookResult.deny(
                f"**CONTENT BLOCKED**: {message}\nFix the vulnerability."
            )

    if not data.get("_sudo_bypass") and "__init__.py" not in file_path:
        for pattern, message in _BLOCK_PATTERNS:
            if pattern.search(content):
                return HookResult.deny(
                    f"**CONTENT BLOCKED**: {message}\nSay SUDO to bypass."
                )

    return HookResult.approve()


# =============================================================================
# CRAWL4AI PREFERENCE (Priority 47) - Suggest crawl4ai over WebFetch
# =============================================================================


@register_hook("crawl4ai_preference", "WebFetch", priority=47)
def suggest_crawl4ai(data: dict, state: SessionState) -> HookResult:
    """Proactively suggest crawl4ai MCP before WebFetch executes."""
    tool_input = data.get("tool_input", {})
    url = tool_input.get("url", "")

    if not url:
        return HookResult.approve()

    # Don't spam - use session tracking
    crawl4ai_suggestions = getattr(state, "crawl4ai_suggestions", 0)
    if crawl4ai_suggestions >= 2:
        return HookResult.approve()

    state.crawl4ai_suggestions = crawl4ai_suggestions + 1

    return HookResult.approve(
        "🌟 **Consider crawl4ai instead** - Superior for web content:\n"
        "  • `mcp__crawl4ai__crawl` - JS rendering + bot bypass\n"
        "  • `mcp__crawl4ai__ddg_search` - Discover related URLs\n"
        "  WebFetch proceeding, but crawl4ai handles protected sites better."
    )


# =============================================================================
# GOD COMPONENT GATE (Priority 48) - Prevent monolithic files
# =============================================================================


@register_hook("god_component_gate", "Edit|Write", priority=48)
def check_god_component_gate(data: dict, state: SessionState) -> HookResult:
    """Block edits that would create God components."""
    tool_input = data.get("tool_input", {})
    file_path = tool_input.get("file_path", "")

    if not file_path or ".claude/tmp/" in file_path or "/.claude/" in file_path:
        return HookResult.approve()
    if data.get("_sudo_bypass"):
        return HookResult.approve()

    try:
        content = _get_projected_content(
            data.get("tool_name", ""), tool_input, file_path
        )
        if not content:
            return HookResult.approve()
    except Exception:
        return HookResult.approve()

    edit_count = (
        state.get_file_edit_count(file_path)
        if hasattr(state, "get_file_edit_count")
        else 0
    )

    try:
        from analysis.god_component_detector import (
            detect_god_component,
            format_detection_message,
        )

        result = detect_god_component(file_path, content, edit_count)
        if result.severity == "block":
            msg = format_detection_message(result)
            return HookResult.deny(
                f"{msg}\nBypass: `# LARGE_FILE_OK: reason` as first line, SUDO, or use .claude/tmp/"
            )
        elif result.severity == "warn":
            return HookResult.approve_with_context(format_detection_message(result))
    except Exception as e:
        log_debug("god_component_gate", f"large file detection failed: {e}")
    return HookResult.approve()


# =============================================================================
# GAP DETECTOR (Priority 50) - Require read before edit
# =============================================================================


@register_hook("gap_detector", "Edit|Write", priority=50)
def check_gap_detector(data: dict, state: SessionState) -> HookResult:
    """Block editing file without reading first + verify old_string is current."""
    from session_state import was_file_read

    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})
    file_path = tool_input.get("file_path", "")

    if not file_path:
        return HookResult.approve()

    # Exceptions - scratch files skip all checks
    is_scratch = ".claude/tmp/" in file_path
    if is_scratch:
        return HookResult.approve()

    path_obj = Path(file_path)

    # === WRITE TOOL: Check "ls before create" ===
    if tool_name == "Write":
        file_exists = path_obj.exists()
        if file_exists:
            file_seen = (
                was_file_read(state, file_path) or file_path in state.files_edited
            )
            if not file_seen:
                filename = path_obj.name
                return HookResult.deny(
                    f"**GAP DETECTED**: Overwriting `{filename}` without reading first.\n"
                    f"Use Read tool first to understand what you're replacing."
                )
            return HookResult.approve()
        return HookResult.approve()

    # === EDIT TOOL: Check "read before edit" ===
    if tool_name != "Edit":
        return HookResult.approve()

    file_exists = path_obj.exists()
    if not file_exists:
        return HookResult.approve()

    old_string = tool_input.get("old_string", "")

    # ALWAYS verify old_string matches current file
    if old_string and len(old_string) > 10:
        try:
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                current_content = f.read()
            if old_string not in current_content:
                filename = path_obj.name
                snippet = old_string[:60].replace("\n", "\\n")
                return HookResult.deny(
                    f"**STALE EDIT BLOCKED**: `old_string` not found in current `{filename}`.\n"
                    f"Looking for: `{snippet}...`\n"
                    f"Re-read the file - content may have changed."
                )
            return HookResult.approve()
        except (OSError, IOError, UnicodeDecodeError):
            pass

    file_seen = was_file_read(state, file_path) or file_path in state.files_edited
    if file_seen:
        return HookResult.approve()

    filename = path_obj.name
    return HookResult.deny(
        f"**GAP DETECTED**: Editing `{filename}` without reading first.\n"
        f"Use Read tool first to understand the file structure."
    )


# =============================================================================
# PRODUCTION GATE (Priority 55) - Block stubs in production code
# =============================================================================


@register_hook("production_gate", "Write|Edit", priority=55)
def check_production_gate(data: dict, state: SessionState) -> HookResult:
    """Block stubs in production code (.claude/ops/ or .claude/lib/)."""
    tool_input = data.get("tool_input", {})
    file_path = tool_input.get("file_path", "")

    if not file_path:
        return HookResult.approve()

    if data.get("_sudo_bypass"):
        return HookResult.approve()

    PROTECTED = [".claude/ops/", ".claude/lib/"]
    is_protected = any(p in file_path for p in PROTECTED)
    if not is_protected:
        return HookResult.approve()

    content = tool_input.get("content", "") or tool_input.get("new_string", "")
    if content:
        STUB_PATTERNS = ["# TODO", "# FIXME", "raise NotImplementedError", "pass  #"]
        for pattern in STUB_PATTERNS:
            if pattern in content:
                return HookResult.deny(
                    f"**STUB BLOCKED**: `{pattern}` detected in production code.\n"
                    f"Complete implementation before writing to .claude/ops/ or .claude/lib/"
                )

    if not Path(file_path).exists():
        return HookResult.approve("📝 New production file - lint after creation")

    return HookResult.approve()


# =============================================================================
# DEFERRAL GATE (Priority 60) - Block deferral theater language
# =============================================================================


@register_hook("deferral_gate", "Edit|Write|MultiEdit", priority=60)
def check_deferral_gate(data: dict, state: SessionState) -> HookResult:
    """Block deferral theater language."""
    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})

    content = ""
    if tool_name == "Write":
        content = tool_input.get("content", "")
    elif tool_name == "Edit":
        content = tool_input.get("new_string", "")

    if not content:
        return HookResult.approve()

    if "SUDO DEFER" in content.upper() or data.get("_sudo_bypass"):
        return HookResult.approve()

    DEFERRAL_PATTERNS = [
        (r"#\s*(TODO|FIXME):\s*(implement\s+)?later", "TODO later"),
        (r"#\s*low\s+priority", "low priority"),
        (r"#\s*nice\s+to\s+have", "nice to have"),
        (r"#\s*could\s+(do|add)\s+later", "could do later"),
        (r"#\s*worth\s+investigating", "worth investigating"),
        (r"#\s*consider\s+adding", "consider adding"),
    ]

    for pattern, name in DEFERRAL_PATTERNS:
        if re.search(pattern, content, re.IGNORECASE):
            return HookResult.deny(
                f"**DEFERRAL THEATER BLOCKED** (Principle #19)\n"
                f"Detected: {name}\n"
                f"Either do it NOW or delete the thought. Add 'SUDO DEFER' to bypass."
            )
    return HookResult.approve()


# =============================================================================
# DOC THEATER GATE (Priority 65) - Block standalone documentation files
# =============================================================================


@register_hook("doc_theater_gate", "Write", priority=65)
def check_doc_theater_gate(data: dict, state: SessionState) -> HookResult:
    """Block creation of standalone documentation files."""
    tool_input = data.get("tool_input", {})
    file_path = tool_input.get("file_path", "")

    if not file_path or not file_path.endswith(".md"):
        return HookResult.approve()

    if data.get("_sudo_bypass"):
        return HookResult.approve()

    ALLOWED = [
        r"/CLAUDE\.md$",
        r"\.claude/agents/.*\.md$",
        r"\.claude/commands/.*\.md$",
        r"\.claude/memory/.*\.md$",
        r"\.claude/reminders/.*\.md$",
        r"\.claude/plans/.*\.md$",
        r"\.claude/rules/.*\.md$",
        r"\.claude/skills/.*\.md$",
        r"\.claude/tmp/.*\.md$",
        r"/tmp/\.claude-scratch/.*\.md$",
        r"projects/.*/.*\.md$",
    ]
    for pattern in ALLOWED:
        if re.search(pattern, file_path):
            return HookResult.approve()

    DOC_PATTERNS = ["README.md", "GUIDE.md", "SCHEMA", "DOCS.md", "ARCHITECTURE.md"]
    filename = Path(file_path).name.upper()
    for pattern in DOC_PATTERNS:
        if pattern.upper() in filename:
            return HookResult.deny(
                f"**DOC THEATER BLOCKED**\n"
                f"File: {Path(file_path).name}\n"
                f"Put docs INLINE (docstrings, comments). Say SUDO to bypass."
            )

    return HookResult.deny(
        "**DOC THEATER BLOCKED**: Standalone .md outside allowed locations.\n"
        "Use .claude/memory/*.md or inline docs. Say SUDO to bypass."
    )


# =============================================================================
# ROOT POLLUTION GATE (Priority 70) - Block home directory clutter
# =============================================================================


@register_hook("root_pollution_gate", "Edit|Write", priority=70)
def check_root_pollution_gate(data: dict, state: SessionState) -> HookResult:
    """Block files that would clutter home directory."""
    tool_input = data.get("tool_input", {})
    file_path = tool_input.get("file_path", "")

    if not file_path:
        return HookResult.approve()

    HOME = Path.home()
    try:
        abs_path = Path(file_path).resolve()
        if not abs_path.is_relative_to(HOME):
            return HookResult.approve()
        rel_path = abs_path.relative_to(HOME)
    except (ValueError, OSError):
        return HookResult.approve()

    parts = rel_path.parts
    if not parts:
        return HookResult.approve()

    ALLOWED_DIRS = {"projects", ".claude", ".vscode", ".beads", ".git", "ai"}
    first = parts[0]

    if first in ALLOWED_DIRS or first.startswith("."):
        return HookResult.approve()

    if len(parts) == 1:
        ALLOWED_FILES = {"CLAUDE.md", ".gitignore", ".claudeignore"}
        if first in ALLOWED_FILES or first.startswith("."):
            return HookResult.approve()
        return HookResult.deny(
            f"**HOME CLEANLINESS**: '{first}' would clutter home.\n"
            f"Use ~/projects/<name>/, ~/ai/<name>/, or ~/.claude/tmp/"
        )
    return HookResult.approve()


# =============================================================================
# RECOMMENDATION GATE (Priority 75) - Warn about duplicate functionality
# =============================================================================


@register_hook("recommendation_gate", "Write", priority=75)
def check_recommendation_gate(data: dict, state: SessionState) -> HookResult:
    """Block duplicate functionality creation."""
    tool_input = data.get("tool_input", {})
    file_path = tool_input.get("file_path", "")

    if not file_path:
        return HookResult.approve()

    INFRA_PATTERNS = [
        r"setup[_-]?\w*\.sh$",
        r"bootstrap[_-]?\w*\.sh$",
        r"\.claude/hooks/\w+_gate\.py$",
        r"\.claude/ops/\w+\.py$",
    ]

    is_infra = any(re.search(p, file_path, re.IGNORECASE) for p in INFRA_PATTERNS)
    if not is_infra:
        return HookResult.approve()

    if Path(file_path).exists():
        return HookResult.approve()

    return HookResult.approve(
        f"⚠️ Creating new infrastructure: {Path(file_path).name}\n"
        f"Read `.claude/memory/__capabilities.md` first to avoid duplication."
    )


# =============================================================================
# SECURITY CLAIM GATE (Priority 80) - Require audit for security code
# =============================================================================


@register_hook("security_claim_gate", "Edit|Write", priority=80)
def check_security_claim_gate(data: dict, state: SessionState) -> HookResult:
    """Require audit for security-sensitive code."""
    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})
    file_path = tool_input.get("file_path", "")

    content = ""
    if tool_name == "Write":
        content = tool_input.get("content", "")
    elif tool_name == "Edit":
        content = tool_input.get("new_string", "")

    if "SUDO SECURITY" in content.upper() or data.get("_sudo_bypass"):
        return HookResult.approve()

    EXCLUDED = [".claude/hooks/", ".claude/tmp/", ".claude/ops/"]
    if any(ex in file_path for ex in EXCLUDED):
        return HookResult.approve()

    SECURITY_PATTERNS = [
        "auth", "login", "password", "credential",
        "token", "secret", "jwt", "oauth",
    ]
    path_lower = file_path.lower()
    is_security_file = any(p in path_lower for p in SECURITY_PATTERNS)

    CONTENT_PATTERNS = [r"password\s*=", r"secret\s*=", r"\.encrypt\(", r"\.decrypt\("]
    has_security_content = any(
        re.search(p, content, re.IGNORECASE) for p in CONTENT_PATTERNS
    )

    if is_security_file or has_security_content:
        audited = getattr(state, "audited_files", [])
        if file_path not in audited:
            return HookResult.approve(
                f"⚠️ SECURITY-SENSITIVE: Consider `audit {Path(file_path).name}` before editing."
            )
    return HookResult.approve()


# =============================================================================
# EPISTEMIC BOUNDARY (Priority 85) - Catch claims not backed by evidence
# =============================================================================


@register_hook("epistemic_boundary", "Edit|Write", priority=85)
def check_epistemic_boundary(data: dict, state: SessionState) -> HookResult:
    """Catch claims not backed by session evidence (AST-based)."""
    tool_input = data.get("tool_input", {})
    file_path = tool_input.get("file_path", "")

    if ".claude/tmp/" in file_path or ".claude/memory" in file_path:
        return HookResult.approve()

    if not file_path.endswith(".py"):
        return HookResult.approve()

    code = tool_input.get("new_string", "") or tool_input.get("content", "")
    if not code or len(code) < 50:
        return HookResult.approve()

    files_read = state.files_read or []

    from _ast_utils import extract_non_builtin_calls

    calls = extract_non_builtin_calls(code)

    if not calls:
        return HookResult.approve()

    unverified = []
    for call in list(calls)[:5]:
        found = any(call.lower() in f.lower() for f in files_read if f)
        if not found and not any(call.lower() in file_path.lower() for _ in [1]):
            unverified.append(call)

    if unverified and len(unverified) >= 2:
        return HookResult.approve(
            f"🔬 EPISTEMIC: Using {', '.join(unverified[:3])} - source files not read this session."
        )
    return HookResult.approve()


# =============================================================================
# RESEARCH GATE (Priority 88) - Block unverified external libraries
# =============================================================================


@register_hook("research_gate", "Edit|Write", priority=88)
def check_research_gate(data: dict, state: SessionState) -> HookResult:
    """Block writes using unverified external libraries."""
    if data.get("_sudo_bypass"):
        return HookResult.approve()

    from session_state import RESEARCH_REQUIRED_LIBS, extract_libraries_from_code

    tool_input = data.get("tool_input", {})
    file_path = tool_input.get("file_path", "")

    if not file_path.endswith(".py") or ".claude/tmp/" in file_path:
        return HookResult.approve()

    code = tool_input.get("new_string", "") or tool_input.get("content", "")
    if not code or len(code) < 30:
        return HookResult.approve()

    libs = extract_libraries_from_code(code)
    researched = state.libraries_researched or []

    STABLE = {
        "os", "sys", "json", "re", "pathlib", "typing",
        "requests", "pytest", "pydantic",
    }

    unresearched = []
    for lib in libs:
        lib_lower = lib.lower()
        if lib_lower in STABLE:
            continue
        if lib_lower in [r.lower() for r in researched]:
            continue
        if any(req.lower() in lib_lower for req in RESEARCH_REQUIRED_LIBS):
            unresearched.append(lib)

    if unresearched:
        state.set("research_gate_blocked_libs", unresearched[:3])
        return HookResult.deny(
            f"**RESEARCH GATE BLOCKED**\n"
            f"Unverified: {', '.join(unresearched[:3])}\n"
            f'Run `research "{unresearched[0]} API"` or say VERIFIED.'
        )
    return HookResult.approve()


# =============================================================================
# IMPORT GATE (Priority 92) - Warn about third-party imports
# =============================================================================


@register_hook("import_gate", "Write", priority=92)
def check_import_gate(data: dict, state: SessionState) -> HookResult:
    """Warn about potentially missing imports (AST-based)."""
    tool_input = data.get("tool_input", {})
    file_path = tool_input.get("file_path", "")
    content = tool_input.get("content", "")

    if not file_path.endswith(".py") or not content:
        return HookResult.approve()

    from _ast_utils import extract_non_stdlib_imports

    third_party = extract_non_stdlib_imports(content)
    if third_party:
        return HookResult.approve(
            f"📦 Third-party imports: {', '.join(sorted(third_party)[:5])} - ensure installed."
        )
    return HookResult.approve()


# =============================================================================
# MODULARIZATION NUDGE (Priority 95) - Remind to modularize
# =============================================================================


@register_hook("modularization_nudge", "Edit|Write", priority=95)
def check_modularization(data: dict, state: SessionState) -> HookResult:
    """Remind to modularize before creating code."""
    tool_input = data.get("tool_input", {})
    file_path = tool_input.get("file_path", "")

    if not file_path:
        return HookResult.approve()

    SKIP_EXT = {".md", ".txt", ".json", ".yaml", ".yml", ".sh", ".env"}
    ext = os.path.splitext(file_path)[1].lower()
    if ext in SKIP_EXT:
        return HookResult.approve()

    if ".claude/tmp/" in file_path:
        return HookResult.approve()

    if state.turn_count % 10 != 0:
        return HookResult.approve()

    return HookResult.approve(
        "📦 MODULARIZATION: Search first, separate concerns, use descriptive filenames."
    )


# =============================================================================
# CURIOSITY INJECTION (Priority 96) - Inject metacognitive prompts
# =============================================================================


@register_hook("curiosity_injection", "Edit|Write", priority=96)
def inject_curiosity_prompt(data: dict, state: SessionState) -> HookResult:
    """Inject metacognitive prompts to expand associative thinking."""
    tool_input = data.get("tool_input", {})
    file_path = tool_input.get("file_path", "")

    if not file_path:
        return HookResult.approve()

    if ".claude/tmp/" in file_path:
        return HookResult.approve()

    CODE_EXT = {".py", ".ts", ".tsx", ".js", ".jsx", ".rs", ".go", ".java"}
    ext = os.path.splitext(file_path)[1].lower()
    if ext not in CODE_EXT:
        return HookResult.approve()

    key = "_curiosity_injection_count"
    count = state.nudge_history.get(key, 0) + 1
    state.nudge_history[key] = count

    if count % 8 != 0:
        return HookResult.approve()

    prompts = []

    if ".claude/" in file_path and ("hooks" in file_path or "lib" in file_path):
        prompts.append("🧬 Framework DNA edit - what side effects might this have?")
        prompts.append("🔗 What other hooks/reducers might interact with this change?")
    elif "test" in file_path.lower():
        prompts.append("🧪 What edge cases am I NOT testing?")
        prompts.append("🎯 Does this test the behavior or the implementation?")
    else:
        prompts.append("🤔 What assumption am I making that might be wrong?")
        prompts.append(
            "🔄 Is there an existing pattern in this codebase I should follow?"
        )

    prompt = prompts[count % len(prompts)]

    return HookResult.approve(f"💡 CURIOSITY: {prompt}")


__all__ = [
    "check_content_gate",
    "suggest_crawl4ai",
    "check_god_component_gate",
    "check_gap_detector",
    "check_production_gate",
    "check_deferral_gate",
    "check_doc_theater_gate",
    "check_root_pollution_gate",
    "check_recommendation_gate",
    "check_security_claim_gate",
    "check_epistemic_boundary",
    "check_research_gate",
    "check_import_gate",
    "check_modularization",
    "inject_curiosity_prompt",
]
