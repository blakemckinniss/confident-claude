"""
Suggestion hooks for UserPromptSubmit (priority 72-95).

Hooks that provide suggestions and guidance:
   2 beads_periodic_sync   - Periodic background beads sync
  70 complexity_assessment - BMAD-style complexity detection (Path B)
  71 advisor_context       - Persona-flavored advisory (Path C)
  72 self_heal_diagnostic  - Diagnostic guidance for self-heal mode
  75 proactive_nudge       - Actionable suggestions from state
  80 ops_nudge             - Suggest ops tools based on patterns
  81 agent_suggestion      - Suggest Task agents based on prompt patterns
  82 skill_suggestion      - Suggest Skills based on prompt patterns
  85 ops_awareness         - Fallback ops script reminders
  86 ops_audit_reminder    - Periodic ops tool usage audit
  88 intent_classifier     - ML-based intent classification
  89 expert_probe          - Force probing questions
  89 pal_mandate           - PAL tool mandates based on state
  90 resource_pointer      - Surface relevant resources
  91 work_patterns         - Inject work behavior patterns
  93 quality_signals       - Pattern smells and context decay
  95 response_format       - Structured response requirements
"""

import json
import re
import time
from pathlib import Path

from _prompt_registry import register_hook
from _hook_result import HookResult
from session_state import SessionState
from context_builder import extract_keywords
from _hooks_memory import get_memory_prompt_hint

# Path constants
SCRIPT_DIR = Path(__file__).parent
CLAUDE_DIR = SCRIPT_DIR.parent
MEMORY_DIR = CLAUDE_DIR / "memory"

# Try to import intent classifier
try:
    from _intent_classifier import classify_intent

    INTENT_CLASSIFIER_AVAILABLE = True
except ImportError:
    INTENT_CLASSIFIER_AVAILABLE = False
    classify_intent = None

# Try to import complexity detector (Path B - BMAD-inspired)
try:
    import _lib_path  # noqa: F401 - Sets up sys.path for lib imports

    from _complexity import assess_complexity, get_complexity_context_injection

    COMPLEXITY_AVAILABLE = True
except ImportError:
    COMPLEXITY_AVAILABLE = False
    assess_complexity = None
    get_complexity_context_injection = None

# Try to import advisory personas (Path C - BMAD-inspired)
try:
    from _advisors import (
        detect_advisor_context,
        get_advisory_context_injection,
        format_advisory,
        ADVISORS,
    )

    ADVISORS_AVAILABLE = True
except ImportError:
    ADVISORS_AVAILABLE = False
    detect_advisor_context = None
    get_advisory_context_injection = None
    format_advisory = None
    ADVISORS = {}

# Try to import PAL/tool mandates
try:
    from _pal_mandates import (
        get_mandate,
        check_keyword_mandate,
        check_repomix_mandate,
        check_serena_mandate,
        check_crawl4ai_mandate,
        check_analyze_mandate,
        check_challenge_mandate,
        check_precommit_mandate,
        check_codemode_mandate,
        check_ralph_mandate,
    )

    PAL_MANDATES_AVAILABLE = True
except ImportError:
    PAL_MANDATES_AVAILABLE = False
    get_mandate = None
    check_keyword_mandate = None
    check_repomix_mandate = None
    check_serena_mandate = None
    check_crawl4ai_mandate = None
    check_analyze_mandate = None
    check_challenge_mandate = None
    check_precommit_mandate = None
    check_codemode_mandate = None
    check_ralph_mandate = None

# Try to import Serena activation mandate
try:
    from _integration import get_serena_activation_mandate
except ImportError:
    get_serena_activation_mandate = None

# Try to import ops tool stats
try:
    from _ops_stats import get_unused_ops_tools, get_ops_tool_stats
except ImportError:

    def get_unused_ops_tools(days_threshold: int = 7) -> list[str]:
        return []

    def get_ops_tool_stats() -> dict:
        return {}


# =============================================================================
# BEADS PERIODIC SYNC (priority 2)
# =============================================================================

BEADS_PERIODIC_SYNC_FILE = MEMORY_DIR / "beads_periodic_sync.json"
BEADS_PERIODIC_SYNC_SECONDS = 600  # 10 minutes


@register_hook("beads_periodic_sync", priority=2)
def check_beads_periodic_sync(data: dict, state: SessionState) -> HookResult:
    """Periodically sync beads in background (every 10 minutes)."""
    import subprocess
    import shutil

    # Check cooldown - don't sync too frequently
    try:
        if BEADS_PERIODIC_SYNC_FILE.exists():
            sync_data = json.loads(BEADS_PERIODIC_SYNC_FILE.read_text())
            if time.time() - sync_data.get("last", 0) < BEADS_PERIODIC_SYNC_SECONDS:
                return HookResult.allow()
    except (json.JSONDecodeError, IOError):
        pass

    # Check if bd command exists
    bd_path = shutil.which("bd")
    if not bd_path:
        return HookResult.allow()

    # Check if .beads directory exists
    beads_dir = Path.cwd() / ".beads"
    if not beads_dir.exists():
        beads_dir = Path.home() / ".claude" / ".beads"
        if not beads_dir.exists():
            return HookResult.allow()

    # Run bd sync in background (non-blocking)
    try:
        subprocess.Popen(
            [bd_path, "sync"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )

        # Update sync timestamp
        BEADS_PERIODIC_SYNC_FILE.parent.mkdir(parents=True, exist_ok=True)
        BEADS_PERIODIC_SYNC_FILE.write_text(json.dumps({"last": time.time()}))
    except (OSError, IOError):
        pass

    return HookResult.allow()


# =============================================================================
# AUTO-CREATE BEAD FROM PROMPT (priority 3) - Full auto-management
# =============================================================================

# Task-like keywords that suggest work needing tracking
_TASK_KEYWORDS = [
    r"\b(implement|add|create|build|fix|refactor|update|change|modify|remove|delete)\b",
    r"\b(bug|issue|error|problem|feature|enhancement)\b",
    r"\b(test|write|review|audit|check|verify|validate)\b",
]


@register_hook("auto_create_bead_from_prompt", priority=3)
def auto_create_bead_from_prompt(data: dict, state: SessionState) -> HookResult:
    """Auto-create a bead from substantive user prompts.

    FULL AUTO-MANAGEMENT:
    - Detects task-like prompts (implement, fix, add, etc.)
    - Auto-creates bead with title from prompt
    - Auto-claims it immediately
    - No manual bd commands needed

    SAFEGUARDS:
    - Skip short prompts (< 10 chars)
    - Skip question-only prompts
    - Skip if already have in_progress bead
    - Graceful degradation on bd failure
    - Cooldown to prevent spam
    """
    import subprocess
    import shutil

    prompt = data.get("user_prompt", "")
    if not prompt or len(prompt) < 10:
        return HookResult.allow()

    # Skip pure questions (ends with ? and no action words)
    if prompt.strip().endswith("?") and not any(
        re.search(p, prompt, re.IGNORECASE) for p in _TASK_KEYWORDS
    ):
        return HookResult.allow()

    # Check if any task keywords present
    has_task_keyword = any(re.search(p, prompt, re.IGNORECASE) for p in _TASK_KEYWORDS)
    if not has_task_keyword:
        return HookResult.allow()

    # Check cooldown - don't create beads too frequently
    cooldown_key = "auto_bead_create_turn"
    if state.turn_count - state.nudge_history.get(cooldown_key, 0) < 5:
        return HookResult.allow()

    # Check if we already have an in_progress bead
    try:
        from _beads import get_in_progress_beads

        if get_in_progress_beads(state):
            return HookResult.allow()
    except ImportError:
        pass

    # Check if bd exists
    bd_path = shutil.which("bd") or str(Path.home() / ".local" / "bin" / "bd")
    if not Path(bd_path).exists():
        return HookResult.allow()

    # Generate title from prompt (first 50 chars, cleaned)
    title = prompt[:50].strip()
    title = re.sub(r"[^\w\s-]", "", title)  # Remove special chars
    title = " ".join(title.split())  # Normalize whitespace
    if len(title) < 5:
        return HookResult.allow()

    try:
        # Create bead
        result = subprocess.run(
            [bd_path, "create", f"--title={title}", "--type=task"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return HookResult.allow()

        # Extract bead ID
        match = re.search(r"(claude-\w+)", result.stdout)
        if not match:
            return HookResult.allow()

        bead_id = match.group(1)

        # Claim it
        subprocess.run(
            [bd_path, "update", bead_id, "--status=in_progress"],
            capture_output=True,
            text=True,
            timeout=5,
        )

        # Track for auto-close
        if not hasattr(state, "auto_created_beads"):
            state.auto_created_beads = []
        state.auto_created_beads.append(bead_id)

        # Update cooldown
        state.nudge_history[cooldown_key] = state.turn_count

        return HookResult.allow(
            f"📋 **Auto-created bead**: `{bead_id[:12]}` - {title[:30]}"
        )

    except (subprocess.TimeoutExpired, Exception):
        return HookResult.allow()


# =============================================================================
# COMPLEXITY ASSESSMENT (priority 70) - Path B: BMAD-inspired
# =============================================================================


@register_hook("complexity_assessment", priority=70)
def check_complexity_assessment(data: dict, state: SessionState) -> HookResult:
    """Assess task complexity to tune hook verbosity (BMAD-inspired)."""
    if not COMPLEXITY_AVAILABLE or assess_complexity is None:
        return HookResult.allow()

    prompt = data.get("prompt", "")
    if not prompt or len(prompt) < 30:
        return HookResult.allow()

    # Skip trivial prompts
    if re.match(r"^(yes|no|ok|hi|hello|thanks|commit|push|/\w+)\b", prompt.lower()):
        return HookResult.allow()

    # Gather context
    context = {
        "consecutive_failures": getattr(state, "consecutive_failures", 0),
        "turn_count": getattr(state, "turn_count", 0),
    }

    # Assess complexity
    complexity = assess_complexity(prompt, context=context)

    # Store in state for other hooks to use
    state.set("task_complexity", complexity.level)
    state.set("task_complexity_score", complexity.score)

    # Only inject context for complex tasks (avoid noise for simple tasks)
    injection = get_complexity_context_injection(complexity)
    if injection:
        return HookResult.allow(injection)

    return HookResult.allow()


# =============================================================================
# ADVISOR CONTEXT (priority 71) - Path C: BMAD-inspired
# =============================================================================


@register_hook("advisor_context", priority=71)
def check_advisor_context(data: dict, state: SessionState) -> HookResult:
    """Inject persona-flavored advisory context (BMAD-inspired)."""
    if not ADVISORS_AVAILABLE or detect_advisor_context is None:
        return HookResult.allow()

    prompt = data.get("prompt", "")
    if not prompt or len(prompt) < 30:
        return HookResult.allow()

    # Skip trivial prompts
    if re.match(r"^(yes|no|ok|hi|hello|thanks|commit|push|/\w+)\b", prompt.lower()):
        return HookResult.allow()

    # Only show advisors for complex tasks (use complexity from previous hook)
    complexity_level = state.get("task_complexity", "standard")
    if complexity_level == "trivial":
        return HookResult.allow()

    # Detect relevant advisors
    advisors = detect_advisor_context(prompt)
    if not advisors:
        return HookResult.allow()

    # Store for other hooks
    state.set("active_advisors", advisors)

    # Generate injection (only for complex tasks)
    if complexity_level == "complex":
        injection = get_advisory_context_injection(advisors, prompt)
        if injection:
            return HookResult.allow(injection)

    return HookResult.allow()


# =============================================================================
# QUESTION TRIGGER (priority 73) - Proactive question suggestions
# =============================================================================

# Try to import question trigger library
try:
    from _question_triggers import (
        detect_question_opportunities,
        format_question_suggestion,
        should_force_question,
    )

    QUESTION_TRIGGERS_AVAILABLE = True
except ImportError:
    QUESTION_TRIGGERS_AVAILABLE = False


@register_hook("question_trigger", priority=73)
def check_question_trigger(data: dict, state: SessionState) -> HookResult:
    """
    Detect situations where proactive questioning adds value.

    Triggers for:
    - Vague/ambiguous prompts
    - Multiple valid implementation paths
    - Build vs buy decisions
    - Low confidence + non-trivial task

    Philosophy: Questions are a feature, not overhead. They demonstrate
    epistemic humility and ensure alignment with user's underlying interests.
    """
    if not QUESTION_TRIGGERS_AVAILABLE:
        return HookResult.allow()

    prompt = data.get("prompt", "")
    if not prompt or len(prompt) < 25:
        return HookResult.allow()

    # Skip trivial/command prompts
    if re.match(r"^(yes|no|ok|hi|hello|thanks|commit|push|/\w+)\b", prompt.lower()):
        return HookResult.allow()

    # Get confidence from state
    confidence = getattr(state, "confidence", 70)
    turn_count = getattr(state, "turn_count", 0)

    # Check for question opportunities
    opportunities = detect_question_opportunities(
        prompt,
        confidence_level=confidence,
        turn_count=turn_count,
    )

    if not opportunities:
        return HookResult.allow()

    # Check if we should force a question (blocking)
    should_force, force_reason = should_force_question(
        prompt,
        confidence,
        consecutive_actions=getattr(state, "consecutive_actions", 0),
    )

    # Format the suggestion
    suggestion = format_question_suggestion(opportunities)

    if should_force and suggestion:
        # At very low confidence, make it more prominent
        msg = f"⚠️ **CLARIFICATION RECOMMENDED** ({force_reason})\n\n{suggestion}"
        return HookResult.allow(msg)

    if suggestion:
        return HookResult.allow(suggestion)

    return HookResult.allow()


# =============================================================================
# SELF-HEAL DIAGNOSTIC (priority 72)
# =============================================================================


@register_hook("self_heal_diagnostic", priority=72)
def check_self_heal_diagnostic(data: dict, state: SessionState) -> HookResult:
    """Inject diagnostic guidance when self-heal mode is active."""
    if not getattr(state, "self_heal_required", False):
        return HookResult.allow()

    target = getattr(state, "self_heal_target", "unknown")
    error = getattr(state, "self_heal_error", "unknown error")
    attempts = getattr(state, "self_heal_attempts", 0)
    max_attempts = getattr(state, "self_heal_max_attempts", 3)

    # Build diagnostic commands based on error type
    diagnostics = []
    diagnostics.append("ruff check ~/.claude/hooks/  # Lint all hooks")

    # Path-specific diagnostics
    if "hook" in target.lower() or "runner" in target.lower():
        diagnostics.append(
            "cd ~/.claude/hooks && ~/.claude/.venv/bin/python -c "
            '"import pre_tool_use_runner"  # Test import'
        )
    if "session_state" in target.lower() or "lib" in target.lower():
        diagnostics.append(
            '~/.claude/.venv/bin/python -c "from session_state import load_state; print(load_state())"  # Test state'
        )

    # Error-specific diagnostics
    if "syntax" in error.lower():
        diagnostics.append(
            f"~/.claude/.venv/bin/python -m py_compile {target}  # Check syntax"
        )
    if "import" in error.lower() or "module" in error.lower():
        diagnostics.append("ls -la ~/.claude/hooks/*.py | head -10  # List hook files")
        diagnostics.append(
            "grep -l 'import.*Error' ~/.claude/hooks/*.py  # Find import issues"
        )

    lines = [
        f"🚨 **SELF-HEAL MODE ACTIVE** (attempt {attempts}/{max_attempts})",
        f"**Target:** `{target}`",
        f"**Error:** {error[:100]}",
        "",
        "**Diagnostic commands:**",
    ]
    lines.extend(f"```bash\n{cmd}\n```" for cmd in diagnostics[:3])
    lines.append("")
    lines.append(
        "Fix the framework error before continuing other work. Say **SUDO** to bypass."
    )

    return HookResult.allow("\n".join(lines))


# =============================================================================
# PROACTIVE NUDGE (priority 75)
# =============================================================================


def _collect_proactive_suggestions(state: SessionState) -> list[str]:
    """Collect all proactive suggestions from state."""
    suggestions = []

    if state.pending_files:
        names = [Path(f).name for f in state.pending_files[:3]]
        suggestions.append(f"📂 Mentioned but unread: {names}")

    if state.files_edited and not state.last_verify and len(state.files_edited) >= 2:
        suggestions.append(f"✅ {len(state.files_edited)} files edited, no /verify run")

    if any(c >= 3 for c in state.edit_counts.values()) and not state.tests_run:
        suggestions.append("🧪 Multiple edits without test run")

    if state.consecutive_failures >= 2:
        suggestions.append(
            f"⚠️ {state.consecutive_failures} failures - consider different approach"
        )

    if state.pending_integration_greps:
        funcs = [p["function"] for p in state.pending_integration_greps[:2]]
        suggestions.append(f"🔗 Grep callers for: {funcs}")

    bg_tasks = getattr(state, "background_tasks", [])
    if bg_tasks:
        recent = [t for t in bg_tasks if state.turn_count - t.get("turn", 0) <= 10]
        if recent:
            types = [t.get("type", "agent")[:15] for t in recent[:2]]
            suggestions.append(
                f"⏳ Background agents running: {types} - check with `TaskOutput`"
            )

    return suggestions


# =============================================================================
# MEMORY PROMPT HINT (priority 73)
# =============================================================================


@register_hook("memory_prompt_hint", priority=73)
def check_memory_prompt_hint(data: dict, state: SessionState) -> HookResult:
    """Suggest memory search for debugging prompts."""
    prompt = data.get("prompt", "")
    hint = get_memory_prompt_hint(prompt)
    if hint:
        return HookResult.allow(hint)
    return HookResult.allow()


@register_hook("proactive_nudge", priority=75)
def check_proactive_nudge(data: dict, state: SessionState) -> HookResult:
    """Surface actionable suggestions based on state."""
    prompt = data.get("prompt", "")
    if not prompt or len(prompt) < 10 or prompt.startswith("/") or state.turn_count < 5:
        return HookResult.allow()

    suggestions = _collect_proactive_suggestions(state)
    if not suggestions:
        return HookResult.allow()

    lines = ["💡 **PROACTIVE CHECKLIST:**"]
    lines.extend(f"  • {s}" for s in suggestions[:3])
    lines.append("  → Act on these or consciously skip them.")
    return HookResult.allow("\n".join(lines))


# =============================================================================
# OPS AWARENESS (priority 85)
# =============================================================================

_OPS_SCRIPTS = {
    "research": (
        [
            re.compile(r"look up", re.I),
            re.compile(r"find docs", re.I),
            re.compile(r"documentation", re.I),
        ],
        "Web search via Tavily API",
    ),
    "probe": (
        [
            re.compile(r"inspect.*object", re.I),
            re.compile(r"what methods", re.I),
            re.compile(r"api.*signature", re.I),
        ],
        "Runtime introspection",
    ),
    "xray": (
        [
            re.compile(r"find.*class", re.I),
            re.compile(r"find.*function", re.I),
            re.compile(r"code structure", re.I),
        ],
        "AST-based code search",
    ),
    "audit": (
        [re.compile(r"security.*check", re.I), re.compile(r"vulnerability", re.I)],
        "Security audit",
    ),
    "void": (
        [
            re.compile(r"find.*stubs", re.I),
            re.compile(r"todo.*code", re.I),
            re.compile(r"incomplete", re.I),
        ],
        "Find stubs and TODOs",
    ),
    "think": (
        [
            re.compile(r"break.*down", re.I),
            re.compile(r"decompose", re.I),
            re.compile(r"complex.*problem", re.I),
        ],
        "Problem decomposition",
    ),
    "verify": (
        [
            re.compile(r"check.*exists", re.I),
            re.compile(r"verify.*file", re.I),
            re.compile(r"confirm.*works", re.I),
        ],
        "Reality checks",
    ),
    "remember": (
        [re.compile(r"save.*lesson", re.I), re.compile(r"remember.*this", re.I)],
        "Persistent memory",
    ),
    "spark": (
        [re.compile(r"recall.*about", re.I), re.compile(r"what.*learned", re.I)],
        "Retrieve memories",
    ),
}


@register_hook("ops_awareness", priority=85)
def check_ops_awareness(data: dict, state: SessionState) -> HookResult:
    """Remind about existing ops scripts (fallback)."""
    prompt = data.get("prompt", "")
    if not prompt or len(prompt) < 10:
        return HookResult.allow()

    prompt_lower = prompt.lower()
    matches = []
    for script, (triggers, desc) in _OPS_SCRIPTS.items():
        for pattern in triggers:
            if pattern.search(prompt_lower):
                matches.append((script, desc))
                break
        if len(matches) >= 3:
            break

    if not matches:
        return HookResult.allow()

    suggestions = "\n".join([f"   - `{s}`: {d}" for s, d in matches])
    return HookResult.allow(f"🔧 OPS SCRIPTS AVAILABLE:\n{suggestions}")


# =============================================================================
# OPS AUDIT REMINDER (priority 86)
# =============================================================================


@register_hook("ops_audit_reminder", priority=86)
def check_ops_audit_reminder(data: dict, state: SessionState) -> HookResult:
    """Periodic reminder about ops tool usage and unused tools.

    DISABLED (2025-12-20): Identified as periodic noise.
    3-hour reminders about unused tools don't drive adoption - they annoy.
    See ~/.claude/memory/__hook_health.md for audit details.
    """
    return HookResult.allow()  # DISABLED

    from _cooldown import check_and_reset_cooldown

    # Only run every 3 hours
    if not check_and_reset_cooldown("ops_audit_reminder"):
        return HookResult.allow()

    parts = []

    # Check for unused tools (7 day threshold)
    unused = get_unused_ops_tools(days_threshold=7)
    if unused and len(unused) >= 5:
        sample = unused[:5]
        parts.append(
            f"📊 **OPS TOOLS**: {len(unused)} tools unused in 7+ days: "
            f"`{', '.join(sample)}`{'...' if len(unused) > 5 else ''}"
        )

    # Check tool stats for suggestions
    stats = get_ops_tool_stats()
    if stats:
        by_usage = sorted(
            stats.items(), key=lambda x: x[1].get("total_uses", 0), reverse=True
        )
        if by_usage:
            top_tool = by_usage[0][0]
            top_uses = by_usage[0][1].get("total_uses", 0)
            if top_uses >= 10:
                parts.append(f"💡 Most-used tool: `{top_tool}` ({top_uses} uses)")

        for tool, data in stats.items():
            total = data.get("total_uses", 0)
            failures = data.get("failures", 0)
            if total >= 5 and failures / total > 0.5:
                parts.append(
                    f"⚠️ `{tool}` has {failures}/{total} failures - may need fixing"
                )
                break

    if not parts:
        return HookResult.allow()

    return HookResult.allow("\n".join(parts))


# =============================================================================
# INTENT CLASSIFIER (priority 88)
# =============================================================================


@register_hook("intent_classifier", priority=88)
def check_intent_classifier(data: dict, state: SessionState) -> HookResult:
    """Classify user intent via HuggingFace model and inject mode-specific context."""
    if not INTENT_CLASSIFIER_AVAILABLE or classify_intent is None:
        return HookResult.allow()

    prompt = data.get("prompt", "")
    if not prompt or len(prompt) < 20:
        return HookResult.allow()

    # Skip slash commands and trivial prompts
    if prompt.startswith("/") or re.match(
        r"^(yes|no|ok|hi|hello|thanks)\b", prompt.lower()
    ):
        return HookResult.allow()

    # Cooldown: only classify every 3rd prompt
    if state.turn_count % 3 != 1:
        return HookResult.allow()

    try:
        result = classify_intent(prompt, threshold=0.35)
        if result is None:
            return HookResult.allow()

        intent = result["intent"]
        confidence = result["confidence"]
        message = result.get("message")

        # Store intent in state
        state.set("detected_intent", intent)
        state.set("intent_confidence", confidence)

        if message and confidence >= 0.45:
            return HookResult.allow(
                f"🎯 **INTENT [{intent.upper()}]** ({confidence:.0%}): {message}"
            )

        return HookResult.allow()
    except Exception:
        return HookResult.allow()


# =============================================================================
# EXPERT PROBE (priority 89)
# =============================================================================

_EXPERT_PROBES = [
    (
        re.compile(r"\b(fix|improve|better|faster|clean|help|make it)\b"),
        re.compile(r"\b(because|since|error|exception|line \d|specific)\b"),
        '❓ **VAGUENESS**: Ask "What specific behavior/output is wrong?"',
    ),
    (
        re.compile(r"\b(broken|doesn't work|not working|wrong|bug|issue|problem)\b"),
        re.compile(r"\b(error|traceback|expected|actual|instead|got)\b"),
        '🔍 **CLAIM CHECK**: Ask "Expected vs actual? Any error message?"',
    ),
    (
        re.compile(r"\b(update|change|modify|refactor|rewrite)\b"),
        re.compile(r"\b(file|function|class|line|method|in \w+\.)\b"),
        '📍 **SCOPE**: Ask "Which specific files/functions?"',
    ),
]

_RE_TRIVIAL_PROMPT = re.compile(r"^(yes|no|ok|hi|thanks|commit|push|/\w+)\b")
_RE_UNCERTAIN = re.compile(r"\b(i think|probably|maybe|might be|could be|seems like)\b")
_RE_NEW_FEATURE = re.compile(r"\b(add|create|implement|build|new feature)\b")


def _collect_expert_probes(prompt_lower: str, turn_count: int) -> list[str]:
    """Collect applicable expert probes for prompt."""
    probes = []
    for trigger, exclude, message in _EXPERT_PROBES:
        if trigger.search(prompt_lower) and not exclude.search(prompt_lower):
            probes.append(message)
    if _RE_NEW_FEATURE.search(prompt_lower) and turn_count <= 3:
        probes.append(
            "🚧 **CONSTRAINTS**: Ask about edge cases, error handling, existing patterns"
        )
    if _RE_UNCERTAIN.search(prompt_lower):
        probes.append(
            "🎓 **EXPERT MODE**: User uncertain - investigate first, don't assume they're right"
        )
    return probes


@register_hook("expert_probe", priority=89)
def check_expert_probe(data: dict, state: SessionState) -> HookResult:
    """Force AI to ask probing questions - assume user needs guidance."""
    prompt = data.get("prompt", "")
    if not prompt or len(prompt) < 15 or "?" in prompt or len(prompt) > 300:
        return HookResult.allow()

    prompt_lower = prompt.lower()
    if _RE_TRIVIAL_PROMPT.match(prompt_lower):
        return HookResult.allow()

    probes = _collect_expert_probes(prompt_lower, state.turn_count)
    if not probes:
        return HookResult.allow()

    return HookResult.allow(
        "🧠 **PROBE BEFORE ACTING** (assume user needs guidance):\n" + "\n".join(probes)
    )


# =============================================================================
# PAL MANDATE (priority 89)
# =============================================================================


@register_hook("pal_mandate", priority=89)
def check_pal_mandate(data: dict, state: SessionState) -> HookResult:
    """Inject MANDATORY PAL tool directives based on confidence/intent/state.

    Integrates with ralph-wiggum task tracking to enhance mandates:
    - When ralph_mode is active, PAL mandates are more assertive
    - Task contract criteria inform tool selection
    - Completion evidence requirements boost mandate priority
    """
    if not PAL_MANDATES_AVAILABLE or get_mandate is None:
        return HookResult.allow()

    prompt = data.get("prompt", "")
    if not prompt or len(prompt) < 15:
        return HookResult.allow()

    if prompt.startswith("/"):
        return HookResult.allow()

    # PRIORITY: Serena activation mandate (fires before PAL mandates)
    # Auto-activates Serena when project has memories but isn't activated
    if get_serena_activation_mandate is not None:
        serena_mandate = get_serena_activation_mandate()
        if serena_mandate:
            state.set("active_pal_mandate", serena_mandate["tool"])
            state.set("mandate_reason", serena_mandate["reason"])
            return HookResult.allow(serena_mandate["directive"])

    confidence = state.get("confidence", 70)
    intent = state.get("detected_intent")
    cascade_failure = state.get("cascade_failure_active", False)
    edit_oscillation = state.get("edit_oscillation_active", False)
    sunk_cost = state.get("sunk_cost_active", False)
    goal_drift = state.get("goal_drift_active", False)
    consecutive_failures = state.get("consecutive_failures", 0)

    # ==========================================================================
    # RALPH-WIGGUM INTEGRATION
    # When ralph tracks a non-trivial task, enhance PAL mandate behavior
    # ==========================================================================
    ralph_mode = state.get("ralph_mode", "")
    task_contract = state.get("task_contract", {})
    completion_confidence = state.get("completion_confidence", 0)
    completion_evidence = state.get("completion_evidence", [])

    # Ralph-aware intent inference: If ralph detected implementation task,
    # use that to inform intent if not already set
    if ralph_mode and not intent:
        # Infer intent from task contract goal
        goal = task_contract.get("goal", "").lower()
        if any(kw in goal for kw in ["fix", "bug", "debug", "error"]):
            intent = "debug"
        elif any(kw in goal for kw in ["refactor", "clean", "improve"]):
            intent = "refactor"
        elif any(kw in goal for kw in ["implement", "build", "create", "add"]):
            intent = "implement"

    # Ralph boost: If ralph is tracking and completion_confidence is low,
    # lower the effective confidence to trigger stronger mandates
    effective_confidence = confidence
    if ralph_mode and task_contract:
        # Evidence required but not yet gathered = more aggressive PAL
        evidence_required = task_contract.get("evidence_required", [])
        evidence_gathered = set(e.get("type") if isinstance(e, dict) else e
                                for e in completion_evidence)
        missing_evidence = set(evidence_required) - evidence_gathered

        if missing_evidence and completion_confidence < 50:
            # Lower effective confidence to trigger PAL consultation
            effective_confidence = min(confidence, 65)

    mandate = get_mandate(
        confidence=effective_confidence,
        intent=intent,
        cascade_failure=cascade_failure,
        edit_oscillation=edit_oscillation,
        sunk_cost=sunk_cost,
        goal_drift=goal_drift,
        consecutive_failures=consecutive_failures,
    )

    if mandate is None and check_keyword_mandate is not None:
        mandate = check_keyword_mandate(prompt, confidence)

    # Check for Repomix triggers (codebase analysis, GitHub repos, etc.)
    if mandate is None and check_repomix_mandate is not None:
        mandate = check_repomix_mandate(prompt)

    # Check for Serena triggers (symbol lookup, references, semantic edits)
    if mandate is None and check_serena_mandate is not None:
        mandate = check_serena_mandate(prompt)

    # Check for Crawl4AI triggers (web scraping, search, documentation)
    if mandate is None and check_crawl4ai_mandate is not None:
        mandate = check_crawl4ai_mandate(prompt)

    # Check for PAL analyze triggers (performance, quality, code analysis)
    if mandate is None and check_analyze_mandate is not None:
        mandate = check_analyze_mandate(prompt)

    # Check for PAL challenge triggers (assumptions, claims, pushback)
    if mandate is None and check_challenge_mandate is not None:
        mandate = check_challenge_mandate(prompt)

    # Check for PAL precommit triggers (git commit, PR creation)
    if mandate is None and check_precommit_mandate is not None:
        mandate = check_precommit_mandate(prompt)

    # Check for code-mode triggers (multi-tool orchestration, batch operations)
    if mandate is None and check_codemode_mandate is not None:
        mastermind_class = state.get("mastermind_classification")
        mandate = check_codemode_mandate(
            prompt, mastermind_classification=mastermind_class
        )

    # Check for ralph-wiggum task tracking triggers (missing evidence, low completion confidence)
    if mandate is None and check_ralph_mandate is not None:
        mandate = check_ralph_mandate(
            ralph_mode=ralph_mode,
            task_contract=task_contract,
            completion_confidence=completion_confidence,
            completion_evidence=completion_evidence,
            confidence=confidence,
        )

    if mandate is None:
        return HookResult.allow()

    state.set("active_pal_mandate", mandate.tool)
    state.set("mandate_reason", mandate.reason)

    return HookResult.allow(mandate.directive)


# =============================================================================
# RESOURCE POINTER (priority 90)
# =============================================================================

TOOL_INDEX = {
    "probe": (
        ["api", "signature", "method", "inspect", "class"],
        "runtime API inspection",
        "/probe httpx.Client",
    ),
    "research": (
        ["docs", "documentation", "library", "how", "api"],
        "web search for docs",
        "/research 'fastapi 2024'",
    ),
    "xray": (
        ["find", "class", "function", "structure", "ast"],
        "AST search",
        "/xray --type function --name handle_",
    ),
    "audit": (
        ["security", "vulnerability", "injection", "secrets"],
        "security audit",
        "/audit src/auth.py",
    ),
    "void": (
        ["stub", "todo", "incomplete", "missing"],
        "find incomplete code",
        "/void src/handlers/",
    ),
    "think": (
        ["complex", "decompose", "stuck", "approach"],
        "problem decomposition",
        "/think 'concurrent writes'",
    ),
    "council": (
        ["decision", "tradeoff", "choice", "should"],
        "multi-perspective analysis",
        "/council 'REST vs GraphQL'",
    ),
    "orchestrate": (
        ["batch", "aggregate", "many", "multiple", "scan"],
        "batch tasks",
        "/orchestrate 'scan all py'",
    ),
}

FOLDER_HINTS = {
    "src/": ["source", "code", "main", "app"],
    ".claude/ops/": ["tool", "script", "ops", "command"],
    ".claude/hooks/": ["hook", "gate", "enforce", "check"],
    ".claude/lib/": ["library", "core", "shared", "state"],
    "api/": ["api", "endpoint", "route", "handler"],
    "tests/": ["test", "spec", "fixture"],
}


def _match_folders(kw_set: set[str]) -> list[str]:
    """Match keywords against folder hints."""
    parts = []
    cwd = Path.cwd()
    for folder, hints in FOLDER_HINTS.items():
        if (cwd / folder.rstrip("/")).exists() and kw_set & set(hints):
            parts.append(f"  • {folder}")
        if len(parts) >= 2:
            break
    return parts


def _match_tools(kw_set: set[str]) -> list[str]:
    """Match keywords against tool index."""
    tool_parts = []
    for tool, (tool_kws, desc, example) in TOOL_INDEX.items():
        if score := len(kw_set & set(tool_kws)):
            tool_parts.append((f"  • /{tool} - {desc}", f"    eg: {example}", score))
        if len(tool_parts) >= 2:
            break
    tool_parts.sort(key=lambda x: -x[2])
    parts = []
    for t, e, _ in tool_parts[:2]:
        parts.extend([t, e])
    return parts


_RE_TRIVIAL_RESOURCE = re.compile(
    r"^(commit|push|status|help|yes|no|ok|thanks)\b", re.I
)


@register_hook("resource_pointer", priority=90)
def check_resource_pointer(data: dict, state: SessionState) -> HookResult:
    """Surface sparse pointers to possibly relevant resources."""
    prompt = data.get("prompt", "")
    if not prompt or len(prompt) < 15 or _RE_TRIVIAL_RESOURCE.match(prompt):
        return HookResult.allow()

    keywords = extract_keywords(prompt)
    if len(keywords) < 2:
        return HookResult.allow()

    kw_set = set(keywords)
    parts = _match_folders(kw_set) + _match_tools(kw_set)

    if not parts:
        return HookResult.allow()

    return HookResult.allow("📍 POSSIBLY RELEVANT:\n" + "\n".join(parts))


# =============================================================================
# WORK PATTERNS (priority 91)
# =============================================================================

_WORK_PATTERNS = [
    (
        r"\b(edit|change|update|modify|fix|add|create|implement|refactor)\b",
        "🎯 **ASSUMPTIONS**: Before acting, state key assumptions (paths, APIs, behavior)",
    ),
    (
        r"\b(delete|remove|drop|reset|overwrite|replace|migrate)\b",
        "↩️ **ROLLBACK**: Note undo path before destructive ops",
    ),
    (
        r"\b(should|best|optimal|recommend|which|how to|complex|tricky)\b",
        "📊 **CONFIDENCE**: State confidence % and reasoning for recommendations",
    ),
    (
        r"\b(function|method|api|endpoint|signature|interface|class)\b",
        "🔗 **INTEGRATION**: After edits, grep callers and note impact",
    ),
    (
        r"\b(can you|is it possible|can't|cannot|impossible|no way to|not able)\b",
        "🚫 **IMPOSSIBILITY CHECK**: Before claiming 'can't', verify: MCP tools, Task agents, WebSearch, /inventory. Try first.",
    ),
]

_PARALLEL_SIGNALS = [
    r"\b(1\.|2\.|3\.)",
    r"\b(first|second|third|then|next|after that)\b",
    r"\b(all|each|every|multiple|several|many)\s+(file|component|test|module)",
    r"\band\b.*\band\b",
    r"[,;]\s*\w+[,;]\s*\w+",
]

# Recursive decomposition signals - complex multi-angle questions
_DECOMPOSITION_TRIGGERS = [
    r"\b(why|how|what\s+makes|what\s+causes)\s+.{15,}\?",  # Complex why/how questions
    r"\b(research|explore|investigate|deep\s+dive|analyze)\s+.{10,}",  # Research intent
    r"\b(comprehensive|thorough|in-depth|complete)\s+(analysis|review|investigation)",  # Depth signals
    r"\b(all|every|various|different|multiple)\s+(aspects?|angles?|perspectives?|factors?)",  # Multi-angle
    r"\b(compare|contrast|evaluate)\s+.{5,}\s+(vs|versus|and|or)\s+",  # Comparison questions
]

_DECOMPOSITION_MESSAGE = """🔀 **RECURSIVE DECOMPOSITION**: Complex multi-angle question detected.
Option A - Use dedicated agent:
```
Task(subagent_type="deep-research", prompt="[full question]")
```
Option B - Manual decomposition:
```
Task(subagent_type="Explore", prompt="Angle 1: [specific sub-question]")
Task(subagent_type="Explore", prompt="Angle 2: [specific sub-question]")  # Same message = parallel
Task(subagent_type="Explore", prompt="Angle 3: [specific sub-question]")
```
Each agent explores independently → synthesize into unified answer."""


@register_hook("work_patterns", priority=91)
def check_work_patterns(data: dict, state: SessionState) -> HookResult:
    """Inject work behavior patterns - assumptions, rollback, confidence, integration."""
    prompt = data.get("prompt", "")
    if not prompt or len(prompt) < 40:
        return HookResult.allow()

    prompt_lower = prompt.lower()
    if re.match(r"^(yes|no|ok|hi|hello|thanks|status|/\w+)\b", prompt_lower):
        return HookResult.allow()

    parts = [msg for pattern, msg in _WORK_PATTERNS if re.search(pattern, prompt_lower)]

    # Parallel opportunity
    if any(re.search(p, prompt_lower) for p in _PARALLEL_SIGNALS):
        if state.consecutive_single_tasks >= 1 or state.parallel_nudge_count >= 1:
            parts.append(
                "⚡ **PARALLEL AGENTS**: Multiple items detected. "
                "Spawn independent Task agents in ONE message, not sequentially."
            )

    # Recursive decomposition for complex research questions
    decomp_matches = sum(
        1 for p in _DECOMPOSITION_TRIGGERS if re.search(p, prompt_lower)
    )
    if decomp_matches >= 2 and len(prompt) >= 50:
        parts.append(_DECOMPOSITION_MESSAGE)

    return HookResult.allow("\n".join(parts)) if parts else HookResult.allow()


# =============================================================================
# QUALITY SIGNALS (priority 93)
# =============================================================================


@register_hook("quality_signals", priority=93)
def check_quality_signals(data: dict, state: SessionState) -> HookResult:
    """Inject quality signals - pattern smells, context decay."""
    prompt = data.get("prompt", "")
    parts = []

    prompt_lower = prompt.lower() if prompt else ""
    if re.search(r"\b(review|refactor|clean|improve|optimize)\b", prompt_lower):
        parts.append(
            "👃 **PATTERN SMELL**: Flag anti-patterns with severity (🟢minor → 🔴critical)"
        )

    if state.turn_count >= 15:
        if state.turn_count >= 30:
            parts.append(
                "⚠️ **CONTEXT DECAY**: 30+ turns - strongly consider `/compact` or summarize"
            )
        else:
            parts.append(
                "💭 **CONTEXT NOTE**: 15+ turns - context may be stale, verify assumptions"
            )

    if not parts:
        return HookResult.allow()

    return HookResult.allow("\n".join(parts))


# =============================================================================
# RESPONSE FORMAT (priority 95)
# =============================================================================


@register_hook("response_format", priority=95)
def check_response_format(data: dict, state: SessionState) -> HookResult:
    """Inject structured response format requirements."""
    prompt = data.get("prompt", "")
    if not prompt or len(prompt) < 30:
        return HookResult.allow()

    if re.match(
        r"^(yes|no|ok|hi|hello|thanks|commit|push|status|/\w+)\b", prompt.lower()
    ):
        return HookResult.allow()

    format_req = """📋 **RESPONSE FORMAT** - End substantive responses with applicable sections (skip empty):

### 💥 Integration Impact
`💥[sev] [file]: [how affected]` - What breaks after this change

### 🦨 Code Smells & Patterns
`🦨[sev] [pattern]: [location] - [why matters]` - Anti-patterns detected

### ⚠️ Technical Debt & Risks
`⚠️[sev] [risk]` - Security, perf, maintainability (🟢1-25 🟡26-50 🟠51-75 🔴76-100)

### ⚡ Quick Wins
`⚡[E:S/M/L] [action] → [benefit]` - Low-effort improvements spotted

### 🏗️ Architecture Pressure
`🏗️[sev] [location]: [strain] → [relief]` - Design strain points

### 📎 Prior Art & Memory
`📎 [context]: [relevance]` - Past decisions with inline context

### 💡 SME Insights
`💡[domain]: [insight]` - Domain expertise, gotchas

### 📚 Documentation Updates
`📚[sev] [what]` - Docs/comments needing update

### ➡️ Next Steps (2-3 divergent paths requiring user decision)
**Path A: [Focus]** (if [priority/constraint])
- `⭐[pri] DO: [action]` | `🔗[pri] Unlocks → [what]`

**Path B: [Different Outcome]** (if [different priority])
- `🔮[pri] You'll hit → [problem]` | `🧭[pri] Trajectory → [pivot]`

❌ NO: "Validate/Test" | "Done" | Same outcome variants | Things I could just do
✅ YES: Paths needing user input (priorities, constraints, preferences I can't infer)

Patterns: ⭐DO | 🔗Chain | 🔮Predict | 🚫Anti | 🧭Strategic | Priority: ⚪1-25 🔵26-50 🟣51-75 ⭐76-100"""

    return HookResult.allow(format_req)
