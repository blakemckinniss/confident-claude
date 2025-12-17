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
from session_state import SessionState

# =============================================================================
# CONFIGURATION
# =============================================================================

# Thresholds for stuck detection
MAX_FIX_ATTEMPTS_BEFORE_RESEARCH = get_magic_number("max_fix_attempts", 3)
MAX_SAME_FILE_EDITS_DEBUGGING = get_magic_number("max_debug_edits", 4)
SYMPTOM_SIMILARITY_THRESHOLD = 0.6  # How similar symptoms must be to count as "same"
RESEARCH_TOOLS = {"WebSearch", "WebFetch", "mcp__crawl4ai__crawl", "mcp__crawl4ai__ddg_search",
                  "mcp__pal__chat", "mcp__pal__thinkdeep", "mcp__pal__debug", "mcp__pal__apilookup"}

# State file for stuck loop tracking
STUCK_LOOP_STATE_FILE = Path(__file__).parent.parent / "memory" / "stuck_loop_state.json"

# Patterns indicating debugging activity
DEBUG_INTENT_PATTERNS = [
    r"\b(?:fix|debug|solve|resolve|troubleshoot)\b",
    r"\b(?:error|bug|issue|problem|broken|failing|blank|crash)\b",
    r"\b(?:doesn't|doesn't|won't|can't|cannot)\s+(?:work|load|render|show|display|run)\b",
    r"\b(?:still|again|same)\s+(?:broken|failing|error|blank|issue)\b",
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
    (r"(?:not|isn't|doesn't)\s+(?:rendering|showing|displaying|loading)", "not_rendering"),
    (r"(?:hydration|hydrate)\s+(?:error|issue|problem|failed)", "hydration_issue"),
    (r"(?:auth|authentication|login)\s+(?:error|issue|problem|failed|broken)", "auth_issue"),
    (r"(?:state|store)\s+(?:not|isn't)\s+(?:persisting|saving|updating)", "state_persistence"),
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
    """Check if we're in a debugging context based on recent activity."""
    # Check if original goal mentions debugging
    goal = (state.original_goal or "").lower()
    if any(re.search(p, goal) for p in DEBUG_INTENT_PATTERNS):
        return True

    # Check recent prompts
    last_prompt = (state.last_user_prompt or "").lower()
    if any(re.search(p, last_prompt) for p in DEBUG_INTENT_PATTERNS):
        return True

    # Check for recent failures
    if state.consecutive_failures >= 2:
        return True

    return False


def _get_stuck_state(runner_state: dict) -> dict:
    """Get or initialize stuck loop tracking state."""
    stuck = runner_state.get("stuck_loop_state", {})
    stuck.setdefault("symptoms_seen", [])  # [(symptom_id, turn, text_hash)]
    stuck.setdefault("fix_attempts", {})   # {file_path: [(turn, text_hash)]}
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


def _check_recurring_symptom(stuck: dict, current_symptoms: list[str], turn: int) -> str | None:
    """Check if we're seeing the same symptom repeatedly."""
    if not current_symptoms:
        return None

    symptoms_seen = stuck.get("symptoms_seen", [])

    # Count how many times each current symptom appeared recently
    recent_window = 15  # turns
    for symptom in current_symptoms:
        recent_occurrences = [
            s for s in symptoms_seen
            if s[0] == symptom and (turn - s[1]) < recent_window
        ]
        if len(recent_occurrences) >= 3:
            return symptom

    return None


# =============================================================================
# HOOK: FIX ATTEMPT TRACKER (priority 78)
# =============================================================================

@register_hook("fix_attempt_tracker", "Edit|Write", priority=78)
def track_fix_attempt(data: dict, state: SessionState, runner_state: dict) -> HookResult:
    """Track edit attempts during debugging sessions."""
    if not _is_debugging_context(state):
        return HookResult.none()

    tool_input = data.get("tool_input", {})
    file_path = tool_input.get("file_path", "")
    if not file_path:
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
            return HookResult.with_context(
                f"🔴 **STUCK LOOP DETECTED** ({attempt_count} edits to `{file_name}`)\n"
                f"⚡ **CIRCUIT BREAKER**: Research REQUIRED before more edits\n"
                f"   → `WebSearch` for current docs/patterns\n"
                f"   → `mcp__pal__debug` for external analysis\n"
                f"   → `mcp__pal__apilookup` for API verification\n"
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
            f"   → WebSearch for \"{symptom_name}\" solutions\n"
            f"   → mcp__pal__debug for systematic analysis"
        )

    return HookResult.none()


# =============================================================================
# HOOK: RESEARCH TRACKER (priority 80)
# =============================================================================

@register_hook("research_tracker", "WebSearch|WebFetch|mcp__pal__*|mcp__crawl4ai__*", priority=80)
def track_research(data: dict, state: SessionState, runner_state: dict) -> HookResult:
    """Track when research is performed to reset stuck state."""
    tool_name = data.get("tool_name", "")

    # Check if this is a research tool
    is_research = (
        tool_name in RESEARCH_TOOLS or
        tool_name.startswith("mcp__pal__") or
        tool_name.startswith("mcp__crawl4ai__")
    )

    if not is_research:
        return HookResult.none()

    stuck = _get_stuck_state(runner_state)
    stuck["research_done"] = True
    stuck["last_research_turn"] = state.turn_count
    stuck["circuit_breaker_active"] = False
    runner_state["stuck_loop_state"] = stuck

    return HookResult.with_context(
        "✅ **Research performed** - Circuit breaker reset\n"
        "💡 Apply learnings from research to your next attempt"
    )


# =============================================================================
# HOOK: VERIFICATION PROMPT (priority 81)
# =============================================================================

@register_hook("verification_prompt", "Bash", priority=81)
def check_verification_needed(data: dict, state: SessionState, runner_state: dict) -> HookResult:
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
        "npm run", "npm start", "npm test", "yarn", "pnpm",
        "python", "pytest", "cargo", "go run", "go test",
        "curl", "http", "localhost", "browser",
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

@register_hook("circuit_breaker", "Edit|Write", priority=82)
def enforce_circuit_breaker(data: dict, state: SessionState, runner_state: dict) -> HookResult:
    """Enforce circuit breaker - block edits until research is done."""
    stuck = _get_stuck_state(runner_state)

    if not stuck.get("circuit_breaker_active", False):
        return HookResult.none()

    tool_input = data.get("tool_input", {})
    file_path = tool_input.get("file_path", "")

    # Allow edits to different files (might be legitimate other work)
    problem_files = [f for f, attempts in stuck.get("fix_attempts", {}).items()
                     if len(attempts) >= MAX_FIX_ATTEMPTS_BEFORE_RESEARCH]

    if file_path not in problem_files:
        return HookResult.none()

    file_name = Path(file_path).name
    return HookResult.with_context(
        f"🛑 **CIRCUIT BREAKER ACTIVE**: Cannot edit `{file_name}` until research done\n"
        f"⚡ Required actions:\n"
        f"   1. `WebSearch` or `mcp__crawl4ai__ddg_search` for solutions\n"
        f"   2. `mcp__pal__debug` or `mcp__pal__chat` for external perspective\n"
        f"   3. `mcp__pal__apilookup` if it's an API/library issue\n"
        f"💡 Research resets the breaker and provides fresh approach"
    )


# =============================================================================
# HOOK: DEBUG SESSION RESET (priority 83)
# =============================================================================

@register_hook("debug_session_reset", "Bash", priority=83)
def check_debug_session_reset(data: dict, state: SessionState, runner_state: dict) -> HookResult:
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
