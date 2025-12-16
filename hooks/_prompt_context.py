"""
Context hooks for UserPromptSubmit (priority 15-70).

Hooks that inject contextual information:
  15 intention_tracker   - Extract mentioned files/searches, track as pending
  30 prompt_disclaimer   - System context and task checklist
  32 tech_version_risk   - Warn about outdated AI knowledge for fast-moving tech
  35 project_context     - Git state and project structure
  40 memory_injector     - Auto-surface relevant memories
  45 context_injector    - Session state summary and command suggestions
  50 reminder_injector   - Custom trigger-based reminders
"""

import re
from pathlib import Path
from typing import Optional

from _prompt_registry import register_hook
from _hook_result import HookResult
from _logging import log_debug
from session_state import (
    SessionState,
    add_pending_file,
    add_pending_search,
    add_domain_signal,
    generate_context,
    Domain,
)
from context_builder import extract_keywords

# Path constants
SCRIPT_DIR = Path(__file__).parent
CLAUDE_DIR = SCRIPT_DIR.parent
MEMORY_DIR = CLAUDE_DIR / "memory"
REMINDERS_DIR = CLAUDE_DIR / "reminders"

# Try to import command awareness
try:
    from _config import COMMAND_SUGGEST_ENABLED
except ImportError:
    COMMAND_SUGGEST_ENABLED = False

# Try to import caching utilities
try:
    from _cache import (
        cached_file_read,
        cached_json_read,
        cached_git_branch,
        cached_git_status,
    )
except ImportError:
    # Fallback implementations
    def cached_file_read(path: str) -> str:
        try:
            return Path(path).read_text(encoding="utf-8")
        except Exception:
            return ""

    def cached_json_read(path: str) -> dict | None:
        import json

        try:
            return json.loads(Path(path).read_text())
        except Exception:
            return None

    def cached_git_branch() -> str:
        import subprocess

        try:
            return subprocess.run(
                ["git", "branch", "--show-current"],
                capture_output=True,
                text=True,
                timeout=2,
            ).stdout.strip()
        except Exception:
            return ""

    def cached_git_status() -> str:
        import subprocess

        try:
            return subprocess.run(
                ["git", "status", "--porcelain"],
                capture_output=True,
                text=True,
                timeout=2,
            ).stdout
        except Exception:
            return ""


# =============================================================================
# FILE/SEARCH EXTRACTION PATTERNS
# =============================================================================

_FILE_PATTERNS = [
    re.compile(r'[`"\']([^`"\']+\.[a-zA-Z]{1,6})[`"\']'),
    re.compile(r"(?:^|\s)([~./][\w./\\-]+\.\w{1,6})(?:\s|$|[,;:])"),
    re.compile(
        r"(?:file|path|in|at|from|edit|read|open)\s+[`\"']?([^`\"'\s]+\.\w{1,6})"
    ),
]

_SEARCH_PATTERNS = [
    re.compile(
        r'(?:search|grep|find)\s+(?:for\s+)?[`"\']([^`"\']+)[`"\']',
        re.IGNORECASE,
    ),
    re.compile(
        r'(?:search|grep|find)\s+[`"\']?([^`"\']+)[`"\']?\s+(?:in|across)',
        re.IGNORECASE,
    ),
]


def _extract_files_from_prompt(prompt: str) -> list[str]:
    """Extract file paths from prompt text."""
    files = []
    for pattern in _FILE_PATTERNS:
        for match in pattern.findall(prompt):
            m = match[0] if isinstance(match, tuple) else match
            if m and not m.startswith("http") and ("/" in m or "." in m):
                clean = m.strip("`\"'")
                if 3 < len(clean) < 200:
                    files.append(clean)
    return list(set(files))


def _extract_searches_from_prompt(prompt: str) -> list[str]:
    """Extract search terms from prompt text."""
    searches = []
    for pattern in _SEARCH_PATTERNS:
        for match in pattern.findall(prompt):
            m = match[0] if isinstance(match, tuple) else match
            clean = m.strip()
            if 2 < len(clean) < 100:
                searches.append(clean)
    return list(set(searches))


@register_hook("intention_tracker", priority=15)
def check_intention_tracker(data: dict, state: SessionState) -> HookResult:
    """Extract mentioned files/searches and track as pending."""
    prompt = data.get("prompt", "")
    if not prompt:
        return HookResult.allow()

    files = _extract_files_from_prompt(prompt)
    searches = _extract_searches_from_prompt(prompt)

    if not files and not searches:
        return HookResult.allow()

    for f in files:
        add_pending_file(state, f)
    for s in searches:
        add_pending_search(state, s)

    total = len(files) + len(searches)
    if total >= 2:
        preview = (files + searches)[:4]
        return HookResult.allow(
            f"⚡ DETECTED {total} ITEMS: {preview}\n"
            f"RULE: Batch ALL Read/Grep calls in ONE message. Do NOT read sequentially."
        )

    return HookResult.allow()


# =============================================================================
# PROMPT DISCLAIMER (priority 30)
# =============================================================================

DISCLAIMER = """⚠️ SYSTEM ASSISTANT MODE: Full access to /home/blake & /mnt/c/. Ask if unsure. Read before edit. Verify before claiming. Use ~/projects/ for project work, ~/ai/ for AI projects/services, ~/.claude/tmp/ for scratch. For python scripts use /home/blake/.claude/.venv/bin/python as interpreter. Always confirm file paths exist before referencing. For task tracking use `bd` (beads) NOT TodoWrite. ⚠️"""

TASK_CHECKLIST = """
## Task Checklist - Order of Operations

**Before starting:**
- [ ] Clarify first? Should I ask user any clarifying questions before proceeding?
- [ ] Check context? Memories (`spark`), git commits, or prior decisions relevant?
- [ ] Research needed? WebSearch/WebFetch for current docs/patterns?
- [ ] Existing functionality? Check with Grep/Glob first
- [ ] Use an agent? Task(Explore), Task(Plan), or other subagent faster/better?
- [ ] Ops scripts? Any ~/.claude/ops/ tools applicable (audit, void, xray, etc.)?
- [ ] Slash commands? Check project .claude/commands/ for relevant commands
- [ ] Anti-patterns? Will this introduce complexity or violate patterns?
- [ ] Track with beads? Use `bd create` or `bd update` to track?
- [ ] Parallelize? Script or multiple agents to complete faster?
- [ ] Background? Can anything run in background while proceeding with other parts?
- [ ] Speed vs quality? Fastest path maintaining code quality?

**After completing:**
- [ ] Validate? Verify change works (build, lint, typecheck)?
- [ ] Tests needed? Create or update tests?
- [ ] Tech debt? Clean up related issues noticed?
- [ ] Next steps: MUST suggest potential follow-up actions to user
"""


@register_hook("prompt_disclaimer", priority=30)
def check_prompt_disclaimer(data: dict, state: SessionState) -> HookResult:
    """Inject system context and task checklist."""
    return HookResult.allow(f"{DISCLAIMER.strip()}\n{TASK_CHECKLIST.strip()}")


# =============================================================================
# INTEGRATION SYNERGY (priority 31)
# =============================================================================

# Try to import integration helpers
try:
    from _integration import (
        is_serena_available,
        get_serena_root,
        has_project_beads,
        get_project_name,
        is_claudemem_available,
    )

    _INTEGRATION_AVAILABLE = True
except ImportError:
    _INTEGRATION_AVAILABLE = False


@register_hook("integration_synergy", priority=31)
def check_integration_synergy(data: dict, state: SessionState) -> HookResult:
    """Inject Integration Synergy context (serena, beads, claude-mem)."""
    parts = []

    if _INTEGRATION_AVAILABLE:
        # Use integration helpers for comprehensive status
        if is_serena_available():
            serena_root = get_serena_root()
            project = serena_root.name if serena_root else "project"
            parts.append(
                f"🔮 **SERENA AVAILABLE**: `.serena/` detected — "
                f'activate with `mcp__serena__activate_project("{project}")`'
            )

        # Project beads isolation
        if has_project_beads():
            project_name = get_project_name() or "project"
            parts.append(
                f"📋 **BEADS ISOLATED**: Project `{project_name}` has local task tracking"
            )

        # Claude-mem warning (only when unavailable)
        if not is_claudemem_available():
            parts.append("⚠️ **CLAUDE-MEM**: API offline (observations not persisted)")
    else:
        # Fallback: basic serena check
        cwd = Path.cwd()
        serena_dir = cwd / ".serena"
        if serena_dir.is_dir():
            parts.append(
                "🔮 **SERENA AVAILABLE**: `.serena/` detected — "
                "activate with `mcp__serena__*` tools for semantic code analysis"
            )

    # Always recommend filesystem MCP for file operations
    parts.append(
        "📂 **FILESYSTEM MCP**: Prefer `mcp__filesystem__read_file`, "
        "`mcp__filesystem__write_file`, `mcp__filesystem__edit_file` "
        "for file operations (better error handling, atomic writes)"
    )

    return HookResult.allow("\n".join(parts))


# =============================================================================
# TECH VERSION RISK (priority 32)
# =============================================================================

# Format: (compiled_pattern, release_date, risk_level, version_info)
_TECH_RISK_DATABASE = [
    # Frontend frameworks - HIGH risk
    (
        re.compile(r"\btailwind(?:css)?\b", re.IGNORECASE),
        "2024-10",
        "HIGH",
        "v4.0 - major breaking changes from v3 config/utilities",
    ),
    (
        re.compile(r"\breact\b", re.IGNORECASE),
        "2024-12",
        "HIGH",
        "v19 - new compiler, hooks changes, deprecations",
    ),
    (
        re.compile(r"\bnext\.?js\b", re.IGNORECASE),
        "2024-10",
        "HIGH",
        "v15 - app router changes, turbopack default",
    ),
    (
        re.compile(r"\bsvelte\b", re.IGNORECASE),
        "2024-12",
        "HIGH",
        "v5 - runes, breaking changes from v4",
    ),
    (
        re.compile(r"\bvue\b", re.IGNORECASE),
        "2024-11",
        "MEDIUM",
        "v3.5+ - Vapor mode, new features",
    ),
    (
        re.compile(r"\bastro\b", re.IGNORECASE),
        "2024-12",
        "MEDIUM",
        "v5.0 - content layer changes",
    ),
    (
        re.compile(r"\bvite\b", re.IGNORECASE),
        "2024-11",
        "MEDIUM",
        "v6.0 - config changes, new defaults",
    ),
    # Build tools / runtimes
    (
        re.compile(r"\bbun\b", re.IGNORECASE),
        "2024-09",
        "HIGH",
        "v1.x - rapidly evolving, API changes",
    ),
    (
        re.compile(r"\bdeno\b", re.IGNORECASE),
        "2024-10",
        "HIGH",
        "v2.0 - major changes from v1",
    ),
    (
        re.compile(r"\bnode\.?js\b", re.IGNORECASE),
        "2024-10",
        "MEDIUM",
        "v22 LTS - new features",
    ),
    # Backend / API
    (
        re.compile(r"\bfastapi\b", re.IGNORECASE),
        "2024-09",
        "MEDIUM",
        "v0.115+ - new features, deprecations",
    ),
    (
        re.compile(r"\bpydantic\b", re.IGNORECASE),
        "2024-06",
        "HIGH",
        "v2.x - complete rewrite from v1",
    ),
    (
        re.compile(r"\blangchain\b", re.IGNORECASE),
        "2024-11",
        "HIGH",
        "v0.3 - major restructuring, new patterns",
    ),
    (
        re.compile(r"\bopenai\b.*\b(?:api|sdk|client)\b", re.IGNORECASE),
        "2024-10",
        "HIGH",
        "v1.x SDK - structured outputs, new models",
    ),
    (
        re.compile(r"\banthropic\b.*\b(?:api|sdk|client)\b", re.IGNORECASE),
        "2024-11",
        "HIGH",
        "new features, prompt caching, batches",
    ),
    # Databases / ORMs
    (
        re.compile(r"\bprisma\b", re.IGNORECASE),
        "2024-10",
        "MEDIUM",
        "v5.x - new features, some breaking",
    ),
    (
        re.compile(r"\bdrizzle\b", re.IGNORECASE),
        "2024-11",
        "MEDIUM",
        "rapidly evolving ORM",
    ),
    # Testing
    (
        re.compile(r"\bplaywright\b", re.IGNORECASE),
        "2024-10",
        "MEDIUM",
        "v1.48+ - new APIs, locators",
    ),
    (
        re.compile(r"\bvitest\b", re.IGNORECASE),
        "2024-10",
        "MEDIUM",
        "v2.x - new features",
    ),
    # CSS / UI
    (
        re.compile(r"\bshadcn\b", re.IGNORECASE),
        "2024-11",
        "MEDIUM",
        "new components, CLI changes",
    ),
    # Package managers
    (re.compile(r"\bpnpm\b", re.IGNORECASE), "2024-09", "LOW", "v9.x - minor changes"),
]

VERSION_SENSITIVE_KEYWORDS = re.compile(
    r"\b(install|add|upgrade|migrate|config|setup|init|create|new project|from scratch|latest)\b",
    re.IGNORECASE,
)


def _build_tech_warnings(prompt_lower: str, max_warnings: int = 2) -> list[str]:
    """Build tech risk warnings from prompt against risk database."""
    warnings = []
    for pattern, release_date, risk_level, version_info in _TECH_RISK_DATABASE:
        match = pattern.search(prompt_lower)
        if match and VERSION_SENSITIVE_KEYWORDS.search(prompt_lower):
            emoji = (
                "🚨" if risk_level == "HIGH" else "⚠️" if risk_level == "MEDIUM" else "ℹ️"
            )
            warnings.append(
                f"{emoji} **{match.group(0).upper()}** ({risk_level}): {version_info} (~{release_date})"
            )
            if len(warnings) >= max_warnings:
                break
    return warnings


def _check_version_mismatch(prompt_lower: str, deps: dict) -> str:
    """Check for version mismatch between package.json and prompt mentions."""
    checks = [
        (
            "tailwind",
            "tailwindcss",
            [("4", "v3|version\\s*3"), ("3", "v4|version\\s*4")],
        ),
        ("react", "react", [("19", "v18|version\\s*18")]),
    ]
    for keyword, pkg_name, version_checks in checks:
        if keyword in prompt_lower and pkg_name in deps:
            installed = deps[pkg_name].lstrip("^~")
            for prefix, pattern in version_checks:
                if installed.startswith(prefix) and re.search(pattern, prompt_lower):
                    return f"\n⚠️ **VERSION MISMATCH**: {pkg_name} v{installed} installed but prompt mentions different version"
    return ""


@register_hook("tech_version_risk", priority=32)
def check_tech_version_risk(data: dict, state: SessionState) -> HookResult:
    """Warn about potentially outdated AI knowledge for fast-moving technologies."""
    prompt = data.get("prompt", "")
    if not prompt or len(prompt) < 10:
        return HookResult.allow()

    prompt_lower = prompt.lower()
    if not VERSION_SENSITIVE_KEYWORDS.search(prompt_lower):
        return HookResult.allow()

    warnings = _build_tech_warnings(prompt_lower)
    if not warnings:
        return HookResult.allow()

    # Check package.json version mismatch
    version_mismatch = ""
    pkg_data = cached_json_read(str(Path.cwd() / "package.json"))
    if pkg_data:
        deps = {
            **pkg_data.get("dependencies", {}),
            **pkg_data.get("devDependencies", {}),
        }
        version_mismatch = _check_version_mismatch(prompt_lower, deps)

    return HookResult.allow(
        f"🔍 **OUTDATED KNOWLEDGE RISK**\n{chr(10).join(warnings)}{version_mismatch}\n"
        f"💡 Use `/research <tech>` to verify current docs"
    )


# =============================================================================
# PROJECT CONTEXT (priority 35)
# =============================================================================

KEY_FILES = {
    "package.json": "Node.js",
    "pyproject.toml": "Python (modern)",
    "Cargo.toml": "Rust",
    "go.mod": "Go",
    "Makefile": "Makefile",
    "Dockerfile": "Docker",
    "CLAUDE.md": "Claude instructions",
}
KEY_DIRS = ["src", "lib", ".claude", "tests", "docs", "projects"]


def _parse_git_changes(status: str) -> str:
    """Parse git status --porcelain output into summary string."""
    if not status:
        return ""
    lines = [ln for ln in status.split("\n") if ln.strip()]
    counts = {
        "modified": len([ln for ln in lines if len(ln) > 1 and ln[1] == "M"]),
        "untracked": len([ln for ln in lines if ln.startswith("??")]),
        "staged": len([ln for ln in lines if len(ln) > 0 and ln[0] in "MADRC"]),
    }
    parts = [f"{v} {k}" for k, v in counts.items() if v]
    return ", ".join(parts)


def _get_context_label(cwd: Path, home: Path) -> str:
    """Determine context label based on working directory."""
    cwd_str = str(cwd)
    if cwd_str.startswith(str(home / "projects")) and cwd != home / "projects":
        return "PROJECT"
    if cwd_str.startswith(str(home / "ai")) and cwd != home / "ai":
        return "AI"
    return "SYSTEM"


@register_hook("project_context", priority=35)
def check_project_context(data: dict, state: SessionState) -> HookResult:
    """Inject git state and project structure."""
    cwd, home = Path.cwd(), Path.home()
    parts = []

    branch = cached_git_branch()
    if branch:
        git_info = f"branch: {branch}"
        changes = _parse_git_changes(cached_git_status())
        if changes:
            git_info += f" | changes: {changes}"
        parts.append(f"Git: {git_info}")

    found_dirs = [d for d in KEY_DIRS if (cwd / d).is_dir()]
    if found_dirs:
        parts.append(f"Dirs: {', '.join(found_dirs)}")

    if not parts:
        return HookResult.allow()

    return HookResult.allow(f"📁 {_get_context_label(cwd, home)}: {' | '.join(parts)}")


# =============================================================================
# MEMORY INJECTOR (priority 40)
# =============================================================================

LESSONS_FILE = MEMORY_DIR / "__lessons.md"
DECISIONS_FILE = MEMORY_DIR / "__decisions.md"
PUNCH_LIST_FILE = MEMORY_DIR / "punch_list.json"


def find_relevant_lessons(keywords: list[str], max_results: int = 3) -> list[str]:
    """Find lessons matching keywords (uses cached file read)."""
    content = cached_file_read(str(LESSONS_FILE))
    if not content:
        return []
    matches = []
    try:
        for line in content.split("\n"):
            if not line.strip() or line.startswith("#"):
                continue
            line_lower = line.lower()
            score = sum(1 for k in keywords if k in line_lower)
            if score > 0:
                if "[block-reflection:" in line:
                    score += 2
                matches.append((score, line.strip()))
        matches.sort(key=lambda x: -x[0])
        return [m[1][:100] for m in matches[:max_results]]
    except Exception:
        return []


def get_active_scope() -> Optional[dict]:
    """Get active DoD/scope if exists (uses cached JSON read)."""
    data = cached_json_read(str(PUNCH_LIST_FILE))
    if not data:
        return None
    try:
        task = data.get("task", "")
        items = data.get("items", [])
        if not task or not items:
            return None
        completed = sum(1 for i in items if i.get("status") == "done")
        next_item = None
        for item in items:
            if item.get("status") != "done":
                next_item = item.get("description", "")[:60]
                break
        return {
            "task": task[:50],
            "progress": f"{completed}/{len(items)}",
            "next": next_item,
        }
    except Exception:
        return None


# Trivial prompts that don't need memory injection
_TRIVIAL_PROMPT_PATTERN = re.compile(
    r"^(yes|no|ok|hi|hello|thanks|y|n|status|commit|push|/\w+|SUDO)\b", re.IGNORECASE
)


def _get_spark_associations(prompt: str) -> list[str]:
    """Get spark associations with timeout protection."""
    # Skip trivial prompts (saves 100ms+)
    if len(prompt) < 15 or _TRIVIAL_PROMPT_PATTERN.match(prompt):
        return []

    try:
        from synapse_core import run_spark, MAX_ASSOCIATIONS, MAX_MEMORIES

        # run_spark has its own cache - call directly with shorter timeout
        result = run_spark(prompt, timeout=0.5)
        if not result:
            return []
        assocs = result.get("associations", []) + result.get("memories", [])
        return assocs[: MAX_ASSOCIATIONS + MAX_MEMORIES]
    except Exception:
        return []


def _build_memory_parts(
    spark_assocs: list, lessons: list, scope: dict | None
) -> list[str]:
    """Build memory injection output parts."""
    parts = []
    if spark_assocs:
        lines = "\n".join(f"   * {a[:100]}" for a in spark_assocs[:3])
        parts.append(f"SUBCONSCIOUS RECALL:\n{lines}")
    if lessons:
        lines = "\n".join(f"   * {lesson}" for lesson in lessons)
        parts.append(f"RELEVANT LESSONS:\n{lines}")
    if scope:
        line = f"ACTIVE TASK: {scope['task']} [{scope['progress']}]"
        if scope.get("next"):
            line += f"\n   Next: {scope['next']}"
        parts.append(line)
    return parts


@register_hook("memory_injector", priority=40)
def check_memory_injector(data: dict, state: SessionState) -> HookResult:
    """Auto-surface relevant memories."""
    prompt = data.get("prompt", "")
    if not prompt or len(prompt) < 10:
        return HookResult.allow()

    spark_assocs = _get_spark_associations(prompt)
    keywords = extract_keywords(prompt)
    lessons = find_relevant_lessons(keywords) if keywords else []
    scope = get_active_scope()

    parts = _build_memory_parts(spark_assocs, lessons, scope)
    return HookResult.allow("\n\n".join(parts)) if parts else HookResult.allow()


# =============================================================================
# CONTEXT INJECTOR (priority 45)
# =============================================================================


@register_hook("context_injector", priority=45)
def check_context_injector(data: dict, state: SessionState) -> HookResult:
    """Inject session state summary and command suggestions."""
    prompt = data.get("prompt", "")
    if not prompt or len(prompt) < 5:
        return HookResult.allow()

    add_domain_signal(state, prompt[:200])

    # Check if we should inject
    should_check = (
        state.errors_unresolved
        or (state.domain != Domain.UNKNOWN and state.domain_confidence > 0.5)
        or len(state.files_edited) >= 2
        or COMMAND_SUGGEST_ENABLED
    )
    if not should_check:
        return HookResult.allow()

    parts = []

    # State context
    state_context = generate_context(state)
    if state_context:
        parts.append(f"📊 {state_context}")

    # Command suggestions
    if COMMAND_SUGGEST_ENABLED and len(prompt) >= 15:
        try:
            from command_awareness import suggest_commands

            suggestions = suggest_commands(prompt, max_suggestions=2)
            for s in suggestions:
                parts.append(f"💡 {s}")
        except Exception as e:
            log_debug("_prompt_context", f"command suggestion loading failed: {e}")

    return HookResult.allow("\n".join(parts)) if parts else HookResult.allow()


# =============================================================================
# REMINDER INJECTOR (priority 50)
# =============================================================================


def _find_frontmatter_end(lines: list[str]) -> int:
    """Find the closing --- index for YAML frontmatter."""
    for i, line in enumerate(lines[1:], 1):
        if line.strip() == "---":
            return i
    return -1


def _parse_frontmatter_lines(lines: list[str]) -> dict:
    """Parse simple YAML key-value pairs from frontmatter lines."""
    meta = {}
    current_key = None
    current_list = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if ":" in stripped and not stripped.startswith("-"):
            if current_key and current_list:
                meta[current_key] = current_list
            key_part = stripped.split(":")[0].strip()
            val_part = stripped[len(key_part) + 1 :].strip()
            current_key = key_part
            if val_part:
                meta[current_key] = val_part
                current_key = None
                current_list = []
            else:
                current_list = []
        elif stripped.startswith("-") and current_key:
            current_list.append(stripped[1:].strip())
    if current_key and current_list:
        meta[current_key] = current_list
    return meta


def parse_reminder_frontmatter(content: str) -> tuple[dict, str]:
    """Parse YAML frontmatter from reminder file."""
    if not content.startswith("---"):
        return {}, content
    lines = content.split("\n")
    end_idx = _find_frontmatter_end(lines)
    if end_idx == -1:
        return {}, content
    meta = _parse_frontmatter_lines(lines[1:end_idx])
    body = "\n".join(lines[end_idx + 1 :]).strip()
    return meta, body


def matches_reminder_trigger(prompt: str, trigger: str) -> bool:
    """Check if prompt matches a reminder trigger."""
    prompt_lower = prompt.lower()
    if trigger.startswith("phrase:"):
        return trigger[7:].lower() in prompt_lower
    elif trigger.startswith("word:"):
        return bool(re.search(rf"\b{re.escape(trigger[5:])}\b", prompt, re.IGNORECASE))
    elif trigger.startswith("regex:"):
        try:
            return bool(re.search(trigger[6:], prompt, re.IGNORECASE))
        except re.error:
            return False
    else:
        return trigger.lower() in prompt_lower


@register_hook("reminder_injector", priority=50)
def check_reminder_injector(data: dict, state: SessionState) -> HookResult:
    """Inject custom trigger-based reminders."""
    prompt = data.get("prompt", "")
    if not prompt or not REMINDERS_DIR.exists():
        return HookResult.allow()

    matches = []
    for md_file in REMINDERS_DIR.glob("*.md"):
        try:
            content = md_file.read_text(encoding="utf-8")
            meta, body = parse_reminder_frontmatter(content)
            triggers = meta.get("trigger", [])
            if isinstance(triggers, str):
                triggers = [triggers]
            if not triggers:
                matches.append((body, md_file.stem))
                continue
            for trigger in triggers:
                if matches_reminder_trigger(prompt, trigger):
                    matches.append((body, md_file.stem))
                    break
        except Exception:
            continue

    if not matches:
        return HookResult.allow()

    parts = [f"[{fname}]\n{content}" for content, fname in matches]
    context = "\n\n---\n\n".join(parts)
    return HookResult.allow(
        f"<additional-user-instruction>\n{context}\n</additional-user-instruction>"
    )
