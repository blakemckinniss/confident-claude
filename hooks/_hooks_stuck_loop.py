"""
Stuck Loop Detection - Smart debugging session monitoring.

Detects when Claude is stuck in a debugging loop without making progress.
Key signals:
1. Same file edited multiple times without verified fix
2. Similar error/symptom descriptions recurring
3. Multiple "let me try" without success
4. No web research despite repeated failures

Priority range: 78-82
"""

import _lib_path  # noqa: F401
import re
import hashlib
from pathlib import Path
from difflib import SequenceMatcher

from _hook_registry import register_hook
from _hook_result import HookResult
from _config import get_magic_number
from _cooldown import _resolve_state_path
from session_state import SessionState

# Context7 integration for library-specific stuck loops
try:
    from _hooks_context7 import (
        detect_library_context,
        format_context7_circuit_breaker_suggestion,
        is_context7_tool,
        get_context7_research_credit,
    )

    CONTEXT7_AVAILABLE = True
except ImportError:
    CONTEXT7_AVAILABLE = False
    detect_library_context = None
    format_context7_circuit_breaker_suggestion = None
    is_context7_tool = None
    get_context7_research_credit = None

# =============================================================================
# CONFIGURATION
# =============================================================================

# Thresholds for stuck detection
MAX_FIX_ATTEMPTS_BEFORE_RESEARCH = get_magic_number("max_fix_attempts", 3)
MAX_SAME_FILE_EDITS_DEBUGGING = get_magic_number("max_debug_edits", 4)
SYMPTOM_SIMILARITY_THRESHOLD = 0.6  # How similar symptoms must be to count as "same"

# Confidence floor integration (v4.9.1)
# When confidence drops below this during debugging, force research
CONFIDENCE_FLOOR_DEBUG = get_magic_number("confidence_floor_debug", 50)
# Confidence threshold that indicates struggling (triggers softer warning)
CONFIDENCE_STRUGGLING = get_magic_number("confidence_struggling", 65)

RESEARCH_TOOLS = {
    "WebSearch",
    "WebFetch",
    "mcp__crawl4ai__crawl",
    "mcp__crawl4ai__ddg_search",
    "mcp__pal__chat",
    "mcp__pal__thinkdeep",
    "mcp__pal__debug",
    "mcp__pal__apilookup",
    # claude-mem memory search - counts as research since it surfaces past solutions
    "mcp__mem-search__search",
    "mcp__plugin_claude-mem_mem-search__search",
    # Context7 library documentation - high-quality structured docs with code examples
    "mcp__plugin_context7_context7__resolve-library-id",
    "mcp__plugin_context7_context7__get-library-docs",
}


# State file for stuck loop tracking (project-isolated via _cooldown)
def _get_stuck_loop_state_file() -> Path:
    """Get project-isolated stuck loop state file."""
    return _resolve_state_path("stuck_loop_state.json")


# Patterns indicating debugging activity
# IMPORTANT: These must be SPECIFIC to avoid false positives
# "fix the bug" = debugging, "add error handling" = NOT debugging
DEBUG_INTENT_PATTERNS = [
    r"\b(?:debug|troubleshoot)\b",  # Strong debugging signals
    r"\bfix\s+(?:the|this|that|a|an)?\s*(?:bug|error|issue|problem|crash)\b",  # "fix the bug"
    r"\b(?:error|bug|issue|problem|crash)\s+(?:with|in|on|when|while)\b",  # "error with X"
    r"\b(?:doesn't|doesn't|won't|can't|cannot)\s+(?:work|load|render|show|display|run)\b",
    r"\b(?:still|again|same)\s+(?:\w+\s+)*(?:broken|failing|error|blank|issue)\b",  # "still shows blank"
    r"\bwhy\s+(?:is|isn't|does|doesn't)\s+(?:it|this|the)\b.*\?",  # "why doesn't it work?"
]

# Anti-patterns that should EXCLUDE from debugging context
# These indicate feature work that happens to mention error-related words
DEBUG_EXCLUSION_PATTERNS = [
    r"\badd\s+(?:error|exception)\s+handling\b",  # Adding error handling
    r"\bcreate\s+(?:an?\s+)?(?:issue|bug)\s+(?:tracker|system|feature)\b",  # Issue tracker feature
    r"\b(?:error|exception)\s+(?:class|type|message|format)\b",  # Error class design
    r"\bblank\s+(?:page|component|template)\s+(?:design|styling|layout)\b",  # Blank page as feature
    r"\b(?:implement|build|create)\s+(?:error|issue|problem)\b",  # Implementing error features
]

# Patterns indicating a fix attempt
FIX_ATTEMPT_PATTERNS = [
    r"\blet\s+me\s+(?:try|fix|change|update|modify)\b",
    r"\b(?:trying|attempting|fixing)\b",
    r"\bthis\s+should\s+(?:fix|solve|resolve)\b",
    r"\bmaybe\s+(?:if|we|I)\b",
    r"\blet's\s+(?:try|see|check)\b",
]

# Symptom extraction patterns (for detecting recurring issues)
SYMPTOM_PATTERNS = [
    (r"(?:page|screen|app)\s+(?:is\s+)?(?:blank|empty|white)", "blank_page"),
    (
        r"(?:not|isn't|doesn't)\s+(?:rendering|showing|displaying|loading)",
        "not_rendering",
    ),
    (r"(?:hydration|hydrate)\s+(?:error|issue|problem|failed)", "hydration_issue"),
    (
        r"(?:auth|authentication|login)\s+(?:error|issue|problem|failed|broken)",
        "auth_issue",
    ),
    (
        r"(?:state|store)\s+(?:not|isn't)\s+(?:persisting|saving|updating)",
        "state_persistence",
    ),
    (r"(?:redirect|redirecting)\s+(?:to\s+)?(?:login|home)", "redirect_issue"),
    (r"(?:null|undefined)\s+(?:error|exception)", "null_error"),
    (r"(?:timeout|timed?\s*out)", "timeout"),
    (r"(?:cors|cross.?origin)", "cors_issue"),
    (r"(?:404|not\s+found)", "not_found"),
    (r"(?:500|server\s+error|internal\s+error)", "server_error"),
    (r"(?:type\s*error|cannot\s+read\s+propert)", "type_error"),
]


def _extract_symptoms(text: str) -> list[str]:
    """Extract symptom categories from text."""
    symptoms = []
    text_lower = text.lower()
    for pattern, symptom_id in SYMPTOM_PATTERNS:
        if re.search(pattern, text_lower):
            symptoms.append(symptom_id)
    return symptoms


def _text_similarity(a: str, b: str) -> float:
    """Calculate similarity between two strings."""
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def _is_debugging_context(state: SessionState) -> bool:
    """Check if we're in a debugging context based on recent activity.

    IMPORTANT: Must avoid false positives for feature work that mentions
    error-related words (e.g., "add error handling", "create issue tracker").
    """

    def _matches_debug_intent(text: str) -> bool:
        """Check if text matches debug patterns but NOT exclusion patterns."""
        text_lower = text.lower()
        # First check exclusions - if any match, NOT debugging
        if any(re.search(p, text_lower) for p in DEBUG_EXCLUSION_PATTERNS):
            return False
        # Then check for debug intent
        return any(re.search(p, text_lower) for p in DEBUG_INTENT_PATTERNS)

    # Check if original goal mentions debugging
    goal = state.original_goal or ""
    if _matches_debug_intent(goal):
        return True

    # Check recent prompts
    last_prompt = state.last_user_prompt or ""
    if _matches_debug_intent(last_prompt):
        return True

    # Check for recent failures - raised threshold from 2 to 3
    # Two failures could be typos; three suggests actual debugging
    if state.consecutive_failures >= 3:
        return True

    return False


def _get_stuck_state(runner_state: dict) -> dict:
    """Get or initialize stuck loop tracking state."""
    stuck = runner_state.get("stuck_loop_state", {})
    stuck.setdefault("symptoms_seen", [])  # [(symptom_id, turn, text_hash)]
    stuck.setdefault("fix_attempts", {})  # {file_path: [(turn, text_hash)]}
    stuck.setdefault("debug_session_start", 0)
    stuck.setdefault("research_done", False)
    stuck.setdefault("last_research_turn", 0)
    stuck.setdefault("last_verification_prompt", 0)
    stuck.setdefault("circuit_breaker_active", False)
    stuck.setdefault("pending_verification", None)  # {file, turn, symptom}
    return stuck


def _should_force_research(stuck: dict, state: SessionState) -> tuple[bool, str]:
    """Check if we should force research based on stuck signals."""
    # Count unique files with multiple fix attempts
    files_with_attempts = {
        f: len(attempts)
        for f, attempts in stuck.get("fix_attempts", {}).items()
        if len(attempts) >= MAX_FIX_ATTEMPTS_BEFORE_RESEARCH
    }

    if not files_with_attempts:
        return False, ""

    # Check if research was done recently
    turns_since_research = state.turn_count - stuck.get("last_research_turn", 0)
    if turns_since_research < 5:
        return False, ""

    # Check if research was never done in this debug session
    if not stuck.get("research_done", False):
        worst_file = max(files_with_attempts, key=files_with_attempts.get)
        attempts = files_with_attempts[worst_file]
        return True, f"`{Path(worst_file).name}` edited {attempts}x without research"

    return False, ""


def _check_recurring_symptom(
    stuck: dict, current_symptoms: list[str], turn: int
) -> str | None:
    """Check if we're seeing the same symptom repeatedly."""
    if not current_symptoms:
        return None

    symptoms_seen = stuck.get("symptoms_seen", [])

    # Count how many times each current symptom appeared recently
    recent_window = 15  # turns
    for symptom in current_symptoms:
        recent_occurrences = [
            s
            for s in symptoms_seen
            if s[0] == symptom and (turn - s[1]) < recent_window
        ]
        if len(recent_occurrences) >= 3:
            return symptom

    return None


# =============================================================================
# HOOK: FIX ATTEMPT TRACKER (priority 78)
# =============================================================================


# Files exempt from fix attempt tracking (iterative refinement expected)
FIX_TRACKING_EXEMPT_PATTERNS = (
    "/.claude/",  # Framework files often need iterative work
    "/rules/",  # Rule files are refined iteratively
    "CLAUDE.md",  # Project config
    "/.serena/",  # Serena memories
    "/plans/",  # Plan mode files
)


@register_hook("fix_attempt_tracker", "Edit|Write", priority=78)
def track_fix_attempt(
    data: dict, state: SessionState, runner_state: dict
) -> HookResult:
    """Track edit attempts during debugging sessions."""
    if not _is_debugging_context(state):
        return HookResult.none()

    tool_input = data.get("tool_input", {})
    file_path = tool_input.get("file_path", "")
    if not file_path:
        return HookResult.none()

    # Exempt framework files from fix attempt tracking
    if any(pattern in file_path for pattern in FIX_TRACKING_EXEMPT_PATTERNS):
        return HookResult.none()

    stuck = _get_stuck_state(runner_state)

    # Initialize debug session if needed
    if stuck["debug_session_start"] == 0:
        stuck["debug_session_start"] = state.turn_count

    # Track this fix attempt
    attempts = stuck["fix_attempts"].setdefault(file_path, [])
    content_hash = hashlib.md5(
        (tool_input.get("new_string", "") or tool_input.get("content", "")).encode()
    ).hexdigest()[:8]
    attempts.append((state.turn_count, content_hash))

    # Keep only last 10 attempts per file
    stuck["fix_attempts"][file_path] = attempts[-10:]

    # Set up verification prompt
    symptoms = _extract_symptoms(state.last_user_prompt or state.original_goal or "")
    if symptoms:
        stuck["pending_verification"] = {
            "file": file_path,
            "turn": state.turn_count,
            "symptom": symptoms[0],
        }

    runner_state["stuck_loop_state"] = stuck

    # Check if we should warn about stuck pattern
    attempt_count = len(stuck["fix_attempts"].get(file_path, []))
    if attempt_count >= MAX_SAME_FILE_EDITS_DEBUGGING:
        file_name = Path(file_path).name

        # Check if research was done
        if not stuck.get("research_done", False):
            stuck["circuit_breaker_active"] = True
            runner_state["stuck_loop_state"] = stuck

            # Detect library context for smarter suggestions
            library_ctx = None
            context7_suggestion = ""
            if CONTEXT7_AVAILABLE and detect_library_context:
                library_ctx = detect_library_context(
                    prompt=state.last_user_prompt or state.original_goal or "",
                    error_output=stuck.get("last_error_output", ""),
                )
                if library_ctx:
                    context7_suggestion = format_context7_circuit_breaker_suggestion(
                        library_ctx
                    )

            # Build suggestion list - Context7 first if library detected
            if library_ctx and context7_suggestion:
                suggestions = (
                    f"{context7_suggestion}"
                    f"   → `mcp__pal__debug` for external analysis\n"
                    f"   → `WebSearch` for community solutions"
                )
            else:
                suggestions = (
                    "   → `mcp__plugin_context7_context7__resolve-library-id` if library-related\n"
                    "   → `WebSearch` for current docs/patterns\n"
                    "   → `mcp__pal__debug` for external analysis\n"
                    "   → `mcp__pal__apilookup` for API verification"
                )

            return HookResult.with_context(
                f"🔴 **STUCK LOOP DETECTED** ({attempt_count} edits to `{file_name}`)\n"
                f"⚡ **CIRCUIT BREAKER**: Research REQUIRED before more edits\n"
                f"{suggestions}\n"
                f"💡 The same approach isn't working. Get external perspective."
            )
        else:
            return HookResult.with_context(
                f"⚠️ **REPEATED EDITS**: `{file_name}` edited {attempt_count}x\n"
                f"💡 Consider: Is this the right file? Different approach needed?"
            )

    return HookResult.none()


# =============================================================================
# HOOK: SYMPTOM TRACKER (priority 79)
# =============================================================================


@register_hook("symptom_tracker", "Bash|Read", priority=79)
def track_symptoms(data: dict, state: SessionState, runner_state: dict) -> HookResult:
    """Track recurring symptoms/errors to detect stuck patterns."""
    tool_result = data.get("tool_result", {})
    result_str = ""

    if isinstance(tool_result, dict):
        result_str = tool_result.get("output", "") or tool_result.get("error", "") or ""
    elif isinstance(tool_result, str):
        result_str = tool_result

    # Also check recent user prompt for symptom descriptions
    prompt_text = state.last_user_prompt or ""
    combined_text = f"{result_str} {prompt_text}"

    symptoms = _extract_symptoms(combined_text)
    if not symptoms:
        return HookResult.none()

    stuck = _get_stuck_state(runner_state)

    # Record symptoms
    text_hash = hashlib.md5(combined_text[:500].encode()).hexdigest()[:8]
    for symptom in symptoms:
        stuck["symptoms_seen"].append((symptom, state.turn_count, text_hash))

    # Keep only last 50 symptoms
    stuck["symptoms_seen"] = stuck["symptoms_seen"][-50:]

    runner_state["stuck_loop_state"] = stuck

    # Check for recurring symptom
    recurring = _check_recurring_symptom(stuck, symptoms, state.turn_count)
    if recurring and not stuck.get("research_done", False):
        symptom_name = recurring.replace("_", " ")
        return HookResult.with_context(
            f"🔄 **RECURRING SYMPTOM**: `{symptom_name}` seen 3+ times\n"
            f"⚡ Same problem keeps appearing → Research the root cause\n"
            f'   → WebSearch for "{symptom_name}" solutions\n'
            f"   → mcp__pal__debug for systematic analysis"
        )

    return HookResult.none()


# =============================================================================
# HOOK: RESEARCH TRACKER (priority 80)
# =============================================================================


@register_hook(
    "research_tracker",
    "WebSearch|WebFetch|mcp__pal__*|mcp__crawl4ai__*|mcp__plugin_context7_context7__*",
    priority=80,
)
def track_research(data: dict, state: SessionState, runner_state: dict) -> HookResult:
    """Track when research is performed to reset stuck state."""
    tool_name = data.get("tool_name", "")

    # Check if this is a research tool
    is_context7 = (
        CONTEXT7_AVAILABLE and is_context7_tool and is_context7_tool(tool_name)
    )
    is_research = (
        tool_name in RESEARCH_TOOLS
        or tool_name.startswith("mcp__pal__")
        or tool_name.startswith("mcp__crawl4ai__")
        or tool_name.startswith("mcp__plugin_context7_context7__")
    )

    if not is_research:
        return HookResult.none()

    stuck = _get_stuck_state(runner_state)
    stuck["research_done"] = True
    stuck["last_research_turn"] = state.turn_count
    stuck["circuit_breaker_active"] = False
    runner_state["stuck_loop_state"] = stuck

    # Context7-specific feedback
    if is_context7:
        return HookResult.with_context(
            "✅ **Context7 library docs retrieved** - Circuit breaker reset\n"
            "💡 Apply the API patterns and code examples to your implementation"
        )

    return HookResult.with_context(
        "✅ **Research performed** - Circuit breaker reset\n"
        "💡 Apply learnings from research to your next attempt"
    )


# =============================================================================
# HOOK: VERIFICATION PROMPT (priority 81)
# =============================================================================


@register_hook("verification_prompt", "Bash", priority=81)
def check_verification_needed(
    data: dict, state: SessionState, runner_state: dict
) -> HookResult:
    """Prompt for verification after fix attempts."""
    stuck = _get_stuck_state(runner_state)
    pending = stuck.get("pending_verification")

    if not pending:
        return HookResult.none()

    # Only prompt if we're testing/running after an edit
    tool_input = data.get("tool_input", {})
    command = tool_input.get("command", "").lower()

    # Check if this looks like a test/verification command
    verification_patterns = [
        "npm run",
        "npm start",
        "npm test",
        "yarn",
        "pnpm",
        "python",
        "pytest",
        "cargo",
        "go run",
        "go test",
        "curl",
        "http",
        "localhost",
        "browser",
    ]

    is_verification = any(p in command for p in verification_patterns)
    if not is_verification:
        return HookResult.none()

    # Check if enough turns passed since the edit
    turns_since_edit = state.turn_count - pending.get("turn", 0)
    if turns_since_edit < 1:
        return HookResult.none()

    # Check cooldown
    turns_since_prompt = state.turn_count - stuck.get("last_verification_prompt", 0)
    if turns_since_prompt < 3:
        return HookResult.none()

    stuck["last_verification_prompt"] = state.turn_count
    runner_state["stuck_loop_state"] = stuck

    file_name = Path(pending.get("file", "unknown")).name
    symptom = pending.get("symptom", "issue").replace("_", " ")

    return HookResult.with_context(
        f"❓ **VERIFICATION CHECK**: Did the edit to `{file_name}` fix the {symptom}?\n"
        f"   → If YES: Great! Clear the debug session\n"
        f"   → If NO: The approach may need rethinking. Consider research."
    )


# =============================================================================
# HOOK: CIRCUIT BREAKER ENFORCER (priority 82)
# =============================================================================


# Files exempt from circuit breaker (iterative refinement expected)
CIRCUIT_BREAKER_EXEMPT_PATTERNS = (
    "/.claude/",  # Framework files often need iterative work
    "/rules/",  # Rule files are refined iteratively
    "CLAUDE.md",  # Project config
    "/.serena/",  # Serena memories
    "/plans/",  # Plan mode files
)


@register_hook("circuit_breaker", "Edit|Write", priority=82)
def enforce_circuit_breaker(
    data: dict, state: SessionState, runner_state: dict
) -> HookResult:
    """Enforce circuit breaker - block edits until research is done."""
    stuck = _get_stuck_state(runner_state)

    if not stuck.get("circuit_breaker_active", False):
        return HookResult.none()

    tool_input = data.get("tool_input", {})
    file_path = tool_input.get("file_path", "")

    # Exempt framework files - iterative refinement is expected
    if any(pattern in file_path for pattern in CIRCUIT_BREAKER_EXEMPT_PATTERNS):
        return HookResult.none()

    # Allow edits to different files (might be legitimate other work)
    problem_files = [
        f
        for f, attempts in stuck.get("fix_attempts", {}).items()
        if len(attempts) >= MAX_FIX_ATTEMPTS_BEFORE_RESEARCH
    ]

    if file_path not in problem_files:
        return HookResult.none()

    file_name = Path(file_path).name
    return HookResult.with_context(
        f"🛑 **CIRCUIT BREAKER ACTIVE**: Cannot edit `{file_name}` until research done\n"
        f"⚡ Required actions:\n"
        f"   1. `mcp__mem-search__search` for past solutions to similar issues\n"
        f"   2. `WebSearch` or `mcp__crawl4ai__ddg_search` for online solutions\n"
        f"   3. `mcp__pal__debug` or `mcp__pal__chat` for external perspective\n"
        f"   4. `mcp__pal__apilookup` if it's an API/library issue\n"
        f"💡 Memory search is fastest - check if this was solved before!"
    )


# =============================================================================
# HOOK: DEBUG SESSION RESET (priority 83)
# =============================================================================


@register_hook("debug_session_reset", "Bash", priority=83)
def check_debug_session_reset(
    data: dict, state: SessionState, runner_state: dict
) -> HookResult:
    """Reset debug session on clear success signals."""
    tool_result = data.get("tool_result", {})
    result_str = ""

    if isinstance(tool_result, dict):
        result_str = tool_result.get("output", "") or ""
    elif isinstance(tool_result, str):
        result_str = tool_result

    # Success patterns
    success_patterns = [
        r"all\s+\d+\s+tests?\s+passed",
        r"passed\s+in\s+[\d.]+s",
        r"build\s+succeeded",
        r"compiled\s+successfully",
        r"✓.*passed",
        r"0\s+(?:errors?|failures?)",
    ]

    is_success = any(re.search(p, result_str.lower()) for p in success_patterns)

    if is_success:
        stuck = _get_stuck_state(runner_state)
        if stuck.get("debug_session_start", 0) > 0:
            # Reset the debug session
            runner_state["stuck_loop_state"] = {
                "symptoms_seen": [],
                "fix_attempts": {},
                "debug_session_start": 0,
                "research_done": False,
                "last_research_turn": 0,
                "last_verification_prompt": 0,
                "circuit_breaker_active": False,
                "pending_verification": None,
            }
            return HookResult.with_context(
                "✅ **Success detected** - Debug session cleared\n"
                "💡 Problem resolved. Ready for next task."
            )

    return HookResult.none()


# =============================================================================
# HOOK: CONFIDENCE FLOOR TRIGGER (priority 84)
# =============================================================================


@register_hook("confidence_floor_debug", "Edit|Write|Bash", priority=84)
def check_confidence_floor(
    data: dict, state: SessionState, runner_state: dict
) -> HookResult:
    """Force research when confidence drops below floor during debugging.

    This creates a dual-trigger system:
    1. Attempt-based: After N edits to same file (handled by circuit_breaker)
    2. Confidence-based: When confidence drops below threshold (this hook)

    The confidence floor trigger catches cases where multiple small failures
    accumulate without triggering the attempt counter.
    """
    # Only relevant during debugging sessions
    if not _is_debugging_context(state):
        return HookResult.none()

    stuck = _get_stuck_state(runner_state)

    # Skip if no debug session active
    if stuck.get("debug_session_start", 0) == 0:
        return HookResult.none()

    # Skip if research was done recently
    if stuck.get("research_done", False):
        turns_since = state.turn_count - stuck.get("last_research_turn", 0)
        if turns_since < 10:  # Research is still "fresh"
            return HookResult.none()

    confidence = state.confidence

    # Hard floor: confidence below 50% during debugging = mandatory research
    if confidence < CONFIDENCE_FLOOR_DEBUG:
        # Activate circuit breaker via confidence
        stuck["circuit_breaker_active"] = True
        stuck["confidence_triggered"] = True
        runner_state["stuck_loop_state"] = stuck

        return HookResult.with_context(
            f"🔴 **CONFIDENCE FLOOR BREACH** ({confidence}% < {CONFIDENCE_FLOOR_DEBUG}%)\n"
            f"⚡ **RESEARCH MANDATORY** - Confidence dropped too low during debugging\n"
            f"   → `mcp__pal__debug` for systematic root cause analysis\n"
            f"   → `WebSearch` or `mcp__crawl4ai__ddg_search` for solutions\n"
            f"   → `mcp__pal__chat` for external perspective\n"
            f"💡 Low confidence + debugging loop = wrong approach. Get help."
        )

    # Soft warning: confidence below 65% during debugging = suggest research
    if confidence < CONFIDENCE_STRUGGLING:
        # Check cooldown for soft warning
        last_warn = stuck.get("last_confidence_warn", 0)
        if state.turn_count - last_warn < 5:
            return HookResult.none()

        stuck["last_confidence_warn"] = state.turn_count
        runner_state["stuck_loop_state"] = stuck

        return HookResult.with_context(
            f"⚠️ **STRUGGLING SIGNAL** ({confidence}% confidence during debugging)\n"
            f"💡 Consider research before confidence drops further:\n"
            f"   → `mcp__pal__apilookup` if it's an API/library question\n"
            f"   → `WebSearch` for common solutions to this pattern"
        )

    return HookResult.none()


# =============================================================================
# HOOK: CONFIDENCE RECOVERY TRACKER (priority 85)
# =============================================================================


@register_hook(
    "confidence_recovery",
    "WebSearch|WebFetch|mcp__pal__*|mcp__crawl4ai__*",
    priority=85,
)
def track_confidence_recovery(
    data: dict, state: SessionState, runner_state: dict
) -> HookResult:
    """Track confidence recovery after research during low-confidence debugging."""
    stuck = _get_stuck_state(runner_state)

    # Only relevant if confidence triggered the circuit breaker
    if not stuck.get("confidence_triggered", False):
        return HookResult.none()

    # Research was done, clear the confidence trigger
    stuck["confidence_triggered"] = False
    runner_state["stuck_loop_state"] = stuck

    return HookResult.with_context(
        "✅ **Confidence-triggered research complete**\n"
        f"💡 Apply fresh insights. Current confidence: {state.confidence}%"
    )
