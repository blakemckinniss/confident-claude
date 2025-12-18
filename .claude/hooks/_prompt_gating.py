"""
Gating hooks for UserPromptSubmit.

Priority range: 0-10
Handles: confidence management, goal tracking, intake protocol, build-vs-buy checks.
"""

import _lib_path  # noqa: F401
import re

from _prompt_registry import register_hook
from _hook_result import HookResult
from session_state import (
    SessionState,
    set_goal,
    check_goal_drift,
    should_nudge,
    record_nudge,
    start_feature,
    update_confidence,
    set_confidence,
)

# Confidence system imports
from confidence import (
    is_rock_bottom,
    check_realignment_complete,
    mark_realignment_complete,
    get_realignment_questions,
    ROCK_BOTTOM_RECOVERY_TARGET,
    DEFAULT_CONFIDENCE,
    format_confidence_change,
    should_require_research,
    should_mandate_external,
    assess_prompt_complexity,
    apply_increasers,
    get_tier_info,
    generate_approval_prompt,
    UserCorrectionReducer,
    detect_dispute_in_prompt,
    dispute_reducer,
    get_recent_reductions,
)

# Fuzzy matching for build-vs-buy detection
try:
    from rapidfuzz import fuzz, process as rf_process

    RAPIDFUZZ_AVAILABLE = True
except ImportError:
    RAPIDFUZZ_AVAILABLE = False

# =============================================================================
# PATTERNS AND CONSTANTS
# =============================================================================

# Sentiment patterns
POSITIVE_SENTIMENT = [
    r"^(nice|great|perfect|awesome|excellent|love\s+it|good\s+job|well\s+done)[!.,\s]?$",
    r"^(yes|yep|yeah|yup|exactly|correct|right)[!.,\s]?$",
    r"^(thanks|thank\s+you|thx|ty)[!.,\s]?$",
    r"\bthat'?s?\s+(perfect|great|exactly|what\s+i\s+(wanted|needed))\b",
    r"\blove\s+(it|this|that)\b",
    r"\bbeautiful\b",
    r"^(ok|okay|k|sure)[!.,\s]?$",
]

NEGATIVE_SENTIMENT = [
    r"^(no|nope|nah|wrong)[!.,\s]?$",
    r"^(ugh|argh|damn|dammit|shit|fuck)\b",
    r"\b(frustrated|annoying|annoyed|irritated)\b",
    r"\bwhat\s+the\s+(hell|heck|fuck)\b",
    r"\bthis\s+is\s+(wrong|broken|bad|terrible)\b",
    r"\bstop\s+(it|that|doing\s+that)\b",
    r"\bi\s+said\b",
    r"\bagain\s*[?!]",
]

# Scope expansion patterns
_SCOPE_EXPANSION_PATTERNS = [
    (
        r"\b(also|additionally|and\s+also|while\s+you'?re?\s+at\s+it)\b",
        "scope addition",
    ),
    (r"\b(another|different|new)\s+(feature|task|thing|project)\b", "new feature"),
    (r"\b(switch|pivot|change)\s+to\b", "direction change"),
    (r"\b(actually|instead|forget\s+that)\b", "goal replacement"),
    (r"\b(one\s+more|btw|by\s+the\s+way)\b", "tangent"),
]

# Complexity patterns
_COMPLEX_SIGNALS = [
    re.compile(r"\b(architect|design|refactor|migrate|restructure)\b", re.IGNORECASE),
    re.compile(r"\b(system|infrastructure|deploy|production)\b", re.IGNORECASE),
    re.compile(r"\b(integrate|integration|api|endpoint)\b", re.IGNORECASE),
    re.compile(r"\b(multiple|several|all|every|across)\b", re.IGNORECASE),
    re.compile(r"\b(database|auth|security|permission)\b", re.IGNORECASE),
    re.compile(r"\b(how|why|should|could|best|optimal)\b", re.IGNORECASE),
    re.compile(r"\b(investigate|debug|diagnose|figure out)\b", re.IGNORECASE),
    re.compile(
        r"\b(feature|implement|build|create|add)\b.*\b(new|from scratch)\b",
        re.IGNORECASE,
    ),
]

_TRIVIAL_SIGNALS = [
    re.compile(r"^(fix|typo|update|change|rename)\s+\w+$", re.IGNORECASE),
    re.compile(r"^(run|execute|test)\s+", re.IGNORECASE),
    re.compile(r"^(commit|push|pr|status)\b", re.IGNORECASE),
    re.compile(r"^(hi|hello|thanks|ok|yes|no)\b", re.IGNORECASE),
    re.compile(r"^/\w+"),
    re.compile(r"^(what is|where is|show me)\s+\w+", re.IGNORECASE),
]

# Build-vs-Buy patterns
_BUILD_FROM_SCRATCH_PATTERNS = [
    re.compile(
        r"\b(build|create|implement|make|write)\s+(a|an|my|the)\s+\w+\s*(app|application|tool|system|service|cli|bot|script)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\bfrom\s+scratch\b", re.IGNORECASE),
    re.compile(
        r"\b(todo|task|note|bookmark|password|budget|expense|habit|timer|pomodoro|reminder|calendar|journal|diary|inventory|kanban|crm)\s*(app|manager|tracker|tool|system)?\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(implement|build|create)\s+(my\s+own|a\s+custom|a\s+simple)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b(don't|do not)\s+want\s+to\s+use\s+(any|existing)\b", re.IGNORECASE),
]

# Common "wheel reinvention" apps
_COMMON_REINVENTIONS: list[tuple[str, list[str]]] = [
    ("todo app", ["Todoist", "TickTick", "Things 3", "Microsoft To Do"]),
    ("task manager", ["Todoist", "Asana", "Trello", "Linear"]),
    ("note taking app", ["Obsidian", "Notion", "Logseq", "Bear"]),
    ("bookmark manager", ["Raindrop.io", "Pocket", "Pinboard"]),
    ("password manager", ["1Password", "Bitwarden", "KeePassXC"]),
    ("budget tracker", ["YNAB", "Mint", "Lunch Money", "Actual Budget"]),
    ("expense tracker", ["Expensify", "Splitwise", "Mint"]),
    ("habit tracker", ["Habitica", "Streaks", "Loop Habit Tracker"]),
    ("pomodoro timer", ["Forest", "Focus Keeper", "Pomofocus"]),
    ("calendar app", ["Fantastical", "Google Calendar", "Calendly"]),
    ("journal app", ["Day One", "Journey", "Notion"]),
    ("inventory system", ["Sortly", "inFlow", "Zoho Inventory"]),
    ("kanban board", ["Trello", "Notion", "Linear", "Jira"]),
    ("crm system", ["HubSpot", "Salesforce", "Pipedrive"]),
    ("url shortener", ["Bitly", "Short.io", "YOURLS"]),
    ("chat app", ["Slack", "Discord", "Mattermost"]),
    ("blog platform", ["Ghost", "WordPress", "Hugo", "11ty"]),
    ("static site generator", ["Hugo", "11ty", "Astro", "Next.js"]),
    ("file uploader", ["Dropzone.js", "FilePond", "Uppy"]),
    ("weather app", ["OpenWeatherMap API", "Weather.com", "wttr.in"]),
    ("recipe manager", ["Paprika", "Mealime", "Notion templates"]),
    ("time tracker", ["Toggl", "Clockify", "RescueTime"]),
    ("invoice generator", ["Invoice Ninja", "Wave", "Zoho Invoice"]),
    ("markdown editor", ["Typora", "MarkText", "VS Code"]),
    ("screenshot tool", ["Flameshot", "ShareX", "CleanShot X"]),
    ("clipboard manager", ["CopyQ", "Ditto", "Maccy"]),
    ("countdown timer", ["Online-Stopwatch.com", "Countdown apps"]),
    ("flashcard app", ["Anki", "Quizlet", "RemNote"]),
    ("rss reader", ["Feedly", "Inoreader", "NewsBlur"]),
    ("link in bio", ["Linktree", "bio.link", "Carrd"]),
]

_REINVENTION_NAMES = [name for name, _ in _COMMON_REINVENTIONS]
_REINVENTION_LOOKUP = {name: alts for name, alts in _COMMON_REINVENTIONS}

# Confidence constants
_CONFIDENCE_FLOOR = 70
_PROMPT_CONFIDENCE_CAP = 85
_VERIFIED_INCREASERS = ("test_pass", "build_success")


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def detect_scope_expansion(state: SessionState, prompt: str) -> tuple[bool, str]:
    """Detect scope expansion in prompt."""
    if not state.original_goal:
        return False, ""
    prompt_lower = prompt.lower()
    for pattern, reason in _SCOPE_EXPANSION_PATTERNS:
        if re.search(pattern, prompt_lower, re.IGNORECASE):
            return (
                True,
                f"Detected {reason}: prompt suggests expanding beyond original goal",
            )
    return False, ""


def _reset_goal_state(state: SessionState) -> None:
    """Clear all goal-related state."""
    state.original_goal = ""
    state.goal_keywords = []
    state.goal_set_turn = 0
    state.goal_project_id = ""
    state.nudge_history.pop("scope_expansion", None)
    state.nudge_history.pop("goal_drift", None)


def _init_goal(state: SessionState, prompt: str, project_id: str) -> None:
    """Initialize goal from prompt."""
    set_goal(state, prompt)
    start_feature(state, prompt[:100])
    state.goal_project_id = project_id


# Cache for project ID (avoids 27ms lookup per call)
_PROJECT_ID_CACHE: dict = {"value": None, "time": 0.0}
_PROJECT_ID_TTL = 10.0  # seconds


def _get_current_project_id() -> str:
    """Get current project ID or empty string (cached)."""
    import time

    now = time.time()
    if (
        _PROJECT_ID_CACHE["value"] is not None
        and now - _PROJECT_ID_CACHE["time"] < _PROJECT_ID_TTL
    ):
        return _PROJECT_ID_CACHE["value"]
    try:
        from project_detector import get_current_project

        result = get_current_project().project_id
    except Exception:
        result = ""
    _PROJECT_ID_CACHE["value"] = result
    _PROJECT_ID_CACHE["time"] = now
    return result


def _handle_scope_expansion(state: SessionState, prompt: str) -> HookResult | None:
    """Handle scope expansion detection."""
    is_expanding, reason = detect_scope_expansion(state, prompt)
    if not is_expanding:
        return None
    show, severity = should_nudge(state, "scope_expansion", reason)
    if not show:
        return None
    record_nudge(state, "scope_expansion", reason)
    times_warned = state.nudge_history.get("scope_expansion", {}).get("times_shown", 0)
    if times_warned >= 2 or severity == "escalate":
        return HookResult.deny(
            f"🚫 **SCOPE BLOCKED**: {reason}\nGoal: {state.original_goal[:60]}... | SUDO SCOPE to override"
        )
    return HookResult.allow(
        f'⚠️ **SCOPE EXPANSION DETECTED**\n🎯 Current goal: "{state.original_goal[:60]}..."\n'
        f"🔀 {reason}\n\nFinish current feature before switching. (Will block after {2 - times_warned} more attempts)"
    )


def _handle_confidence_floor(state: SessionState) -> None:
    """Handle floor reset with trust debt accumulation."""
    if state.confidence == 0:
        set_confidence(state, DEFAULT_CONFIDENCE, "session initialization")
    elif state.confidence < _CONFIDENCE_FLOOR:
        old_debt = getattr(state, "reputation_debt", 0)
        state.reputation_debt = old_debt + 1
        set_confidence(
            state, _CONFIDENCE_FLOOR, f"floor reset (debt now {state.reputation_debt})"
        )


def _apply_user_correction(state: SessionState, prompt: str, parts: list) -> int:
    """Apply user correction reducer if triggered."""
    old_conf = state.confidence
    reducer = UserCorrectionReducer()
    key = "confidence_reducer_user_correction"
    last_trigger = state.nudge_history.get(key, {}).get("last_turn", -999)
    if reducer.should_trigger({"prompt": prompt}, state, last_trigger):
        update_confidence(state, reducer.delta, reducer.name)
        if key not in state.nudge_history:
            state.nudge_history[key] = {}
        state.nudge_history[key]["last_turn"] = state.turn_count
        parts.append(
            format_confidence_change(old_conf, state.confidence, f"({reducer.name})")
        )
    return state.confidence


def _has_recent_verified_boost(state: SessionState) -> bool:
    """Check if there's a recent verified boost."""
    for inc_name in _VERIFIED_INCREASERS:
        key = f"confidence_increaser_{inc_name}"
        last_turn = state.nudge_history.get(key, {}).get("last_turn", -999)
        if state.turn_count - last_turn <= 3:
            return True
    return False


def _apply_confidence_cap(state: SessionState, parts: list) -> None:
    """Apply confidence cap unless protected by verified boost."""
    if state.confidence <= _PROMPT_CONFIDENCE_CAP:
        return
    if _has_recent_verified_boost(state):
        parts.append(
            f"✅ Confidence at {state.confidence}% (verified success protected)"
        )
    else:
        set_confidence(state, _PROMPT_CONFIDENCE_CAP, "prompt cap (no verified boost)")
        parts.append(
            f"⚖️ Confidence capped at {_PROMPT_CONFIDENCE_CAP}% (earn higher via verified success)"
        )


def _fuzzy_match_reinvention(
    prompt: str, threshold: int = 75
) -> tuple[str | None, list[str]]:
    """Check if prompt mentions a common wheel-reinvention app using fuzzy matching."""
    if not RAPIDFUZZ_AVAILABLE:
        return None, []
    prompt_lower = prompt.lower()
    words = prompt_lower.split()
    candidates = []
    for i in range(len(words)):
        for length in range(2, 5):
            if i + length <= len(words):
                phrase = " ".join(words[i : i + length])
                candidates.append(phrase)
    if len(words) <= 6:
        candidates.append(prompt_lower)
    best_match = None
    best_score = 0
    for candidate in candidates:
        result = rf_process.extractOne(
            candidate, _REINVENTION_NAMES, scorer=fuzz.token_sort_ratio
        )
        if result and result[1] > best_score and result[1] >= threshold:
            best_match = result[0]
            best_score = result[1]
    if best_match:
        return best_match, _REINVENTION_LOOKUP.get(best_match, [])
    return None, []


# =============================================================================
# GATING HOOKS (priority 0-10)
# =============================================================================


@register_hook("confidence_override", priority=0)
def check_confidence_override(data: dict, state: SessionState) -> HookResult:
    """Allow manual confidence override via SET_CONFIDENCE=X in prompt."""
    prompt = data.get("prompt", "")
    match = re.search(r"\bSET_CONFIDENCE\s*=\s*(\d+)\b", prompt, re.IGNORECASE)
    if not match:
        return HookResult.allow()
    try:
        new_confidence = int(match.group(1))
        new_confidence = max(0, min(100, new_confidence))
    except ValueError:
        return HookResult.allow()
    old_confidence = state.confidence
    set_confidence(state, new_confidence, "manual override")
    old_tier, old_emoji, _ = get_tier_info(old_confidence)
    new_tier, new_emoji, _ = get_tier_info(state.confidence)
    return HookResult.allow(
        f"🎛️ **CONFIDENCE OVERRIDE**\n"
        f"{old_emoji} {old_confidence}% ({old_tier}) → {new_emoji} {state.confidence}% ({new_tier})"
    )


@register_hook("goal_anchor", priority=1)
def check_goal_anchor(data: dict, state: SessionState) -> HookResult:
    """Prevent scope drift and block scope expansion."""
    prompt = data.get("prompt", "")
    if not prompt:
        return HookResult.allow()
    project_id = _get_current_project_id()
    if state.original_goal and state.goal_project_id and project_id:
        if project_id != state.goal_project_id:
            _reset_goal_state(state)
    if not state.original_goal:
        _init_goal(state, prompt, project_id)
        return HookResult.allow()
    # /clear command resets goal - user is intentionally starting fresh topic
    if prompt.strip().lower().startswith("/clear"):
        _reset_goal_state(state)
        return HookResult.allow()
    if "SUDO SCOPE" in prompt.upper():
        _reset_goal_state(state)
        clean = re.sub(r"\bSUDO\s+SCOPE\b", "", prompt, flags=re.IGNORECASE).strip()
        _init_goal(state, clean, project_id)
        return HookResult.allow()
    if result := _handle_scope_expansion(state, prompt):
        return result
    is_drifting, drift_msg = check_goal_drift(state, prompt)
    if is_drifting:
        show, severity = should_nudge(state, "goal_drift", drift_msg)
        if show:
            record_nudge(state, "goal_drift", drift_msg)
            if severity == "escalate":
                ignored = state.nudge_history.get("goal_drift", {}).get(
                    "times_ignored", 0
                )
                drift_msg = (
                    f"🚨 **REPEATED DRIFT WARNING** (ignored {ignored}x)\n{drift_msg}"
                )
            return HookResult.allow(f"\n{drift_msg}\n")
    return HookResult.allow()


@register_hook("user_sentiment", priority=2)
def check_user_sentiment(data: dict, state: SessionState) -> HookResult:
    """Adjust confidence based on user sentiment in prompt."""
    prompt = data.get("prompt", "")
    if not prompt or len(prompt) > 100:
        return HookResult.allow()
    prompt_lower = prompt.lower().strip()
    for pattern in POSITIVE_SENTIMENT:
        if re.search(pattern, prompt_lower, re.IGNORECASE):
            old_conf = state.confidence
            update_confidence(state, 3, "positive_sentiment")
            if state.confidence != old_conf:
                return HookResult.allow(
                    f"😊 Positive sentiment: {old_conf}% → {state.confidence}% (+3)"
                )
            return HookResult.allow()
    for pattern in NEGATIVE_SENTIMENT:
        if re.search(pattern, prompt_lower, re.IGNORECASE):
            old_conf = state.confidence
            update_confidence(state, -3, "negative_sentiment")
            if state.confidence != old_conf:
                return HookResult.allow(
                    f"😟 Negative sentiment detected: {old_conf}% → {state.confidence}% (-3)"
                )
            return HookResult.allow()
    return HookResult.allow()


@register_hook("rock_bottom_realignment", priority=2)
def check_rock_bottom(data: dict, state: SessionState) -> HookResult:
    """Force realignment questions when confidence hits rock bottom."""
    prompt = data.get("prompt", "").strip()
    if not is_rock_bottom(state.confidence):
        return HookResult.allow()
    if check_realignment_complete(state):
        return HookResult.allow()
    answer_patterns = [
        r"^(continue|new|debug|careful|fast|ask|misunderstood|technical|wrong|nothing)",
        r"^\d\.",
        r"^(a|b|c|d)\)",
    ]
    is_answer = any(re.search(p, prompt.lower()) for p in answer_patterns)
    positive_patterns = [r"^(ok|yes|sure|go|proceed|continue|let's|alright|good)"]
    is_positive = any(re.search(p, prompt.lower()) for p in positive_patterns)
    if is_answer or is_positive or len(prompt) < 30:
        new_confidence = mark_realignment_complete(state)
        old_confidence = state.confidence
        set_confidence(state, new_confidence, "rock bottom realignment complete")
        return HookResult.allow(
            f"🔄 **REALIGNMENT COMPLETE**\n"
            f"Confidence restored: {old_confidence}% → {state.confidence}%\n\n"
            f"Ready to proceed with renewed focus."
        )
    questions = get_realignment_questions()
    questions_text = "\n".join(
        [f"**{q['header']}**: {q['question']}" for q in questions]
    )
    return HookResult.allow(
        f"🚨 **ROCK BOTTOM REACHED** (Confidence: {state.confidence}%)\n\n"
        f"I need to realign with you before continuing. Please answer briefly:\n\n"
        f"{questions_text}\n\n"
        f"After you respond, my confidence will be restored to {ROCK_BOTTOM_RECOVERY_TARGET}%."
    )


@register_hook("confidence_initializer", priority=3)
def check_confidence_initializer(data: dict, state: SessionState) -> HookResult:
    """Initialize and assess confidence on every prompt."""
    prompt = data.get("prompt", "")
    _handle_confidence_floor(state)
    if not prompt or len(prompt) < 20:
        return HookResult.allow()
    state.last_user_prompt = prompt
    parts = []
    delta, reasons = assess_prompt_complexity(prompt)
    old_conf = state.confidence
    if delta != 0:
        update_confidence(state, delta, ", ".join(reasons))
    old_conf = _apply_user_correction(state, prompt, parts)
    for name, inc_delta, desc, requires_approval in apply_increasers(
        state, {"prompt": prompt}
    ):
        if not requires_approval:
            update_confidence(state, inc_delta, name)
            parts.append(
                format_confidence_change(old_conf, state.confidence, f"({name})")
            )
            old_conf = state.confidence
    _apply_confidence_cap(state, parts)
    mandatory, mandatory_msg = should_mandate_external(state.confidence)
    if mandatory:
        parts.append(mandatory_msg)
    elif state.confidence < 50:
        require_research, research_msg = should_require_research(state.confidence, {})
        if require_research:
            parts.append(research_msg)
    if len(prompt) > 100:
        tier_name, emoji, _ = get_tier_info(state.confidence)
        parts.insert(0, f"{emoji} **Confidence: {state.confidence}% ({tier_name})**")
    return HookResult.allow("\n\n".join(parts)) if parts else HookResult.allow()


@register_hook("intake_protocol", priority=5)
def check_intake_protocol(data: dict, state: SessionState) -> HookResult:
    """Show complexity-tiered checklists."""
    prompt = data.get("prompt", "")
    if not prompt:
        return HookResult.allow()
    prompt_lower = prompt.lower().strip()
    prompt_len = len(prompt)
    for pattern in _TRIVIAL_SIGNALS:
        if pattern.search(prompt_lower):
            return HookResult.allow()
    if prompt_len < 50:
        return HookResult.allow()
    complex_score = sum(1 for p in _COMPLEX_SIGNALS if p.search(prompt_lower))
    if (prompt_len > 200 and complex_score >= 2) or complex_score >= 3:
        checklist = """
┌─ INTAKE PROTOCOL ────────────────────────────────────────────┐
│ 📋 Request: [1-line summary]                                 │
│ 🎯 Confidence: [L/M/H] because [reason]                      │
│ ❓ Gaps: [what I don't know / need to verify]                │
│ 🔄 Alternatives: [ ] searched  [ ] none fit  [ ] user wants custom
│ 🔍 Boost: [ ] research  [ ] oracle  [ ] groq  [ ] ask user   │
│ 📊 Adjusted: [L/M/H] after [action taken]                    │
│ 🚦 Gate: [PROCEED / STOP - need X to continue]               │
├──────────────────────────────────────────────────────────────┤
│ 📝 Plan: [numbered steps]                                    │
│ 🤖 Agents: [scout/digest/parallel/chore if needed]           │
│ 🎯 Orchestrate?: [batch/aggregate → /orchestrate for 37% ↓]  │
│ 🛠️ Tools: [specific tools to use]                            │
└──────────────────────────────────────────────────────────────┘"""
        return HookResult.allow(
            f"🔬 COMPLEX TASK DETECTED - Full protocol required:{checklist}\n\n"
            f"⚠️ THRESHOLD: If Confidence < M after boost attempts, STOP and clarify with user."
        )
    if complex_score >= 1 or prompt_len > 50:
        checklist = """
┌─ INTAKE ─────────────────────────────────────┐
│ Request: [summary] | Conf: [L/M/H]       │
│ Gaps: [unknowns] | Boost: [if needed]    │
└──────────────────────────────────────────┘"""
        return HookResult.allow(f"📋 Multi-step task - Abbreviated intake:{checklist}")
    return HookResult.allow()


@register_hook("build_vs_buy", priority=6)
def check_build_vs_buy(data: dict, state: SessionState) -> HookResult:
    """Detect wheel-reinvention and prompt for alternatives consideration."""
    prompt = data.get("prompt", "")
    if not prompt or len(prompt) < 20:
        return HookResult.allow()
    learning_patterns = re.compile(
        r"\b(learn|practice|exercise|tutorial|study|understand|educational)\b",
        re.IGNORECASE,
    )
    if learning_patterns.search(prompt):
        return HookResult.allow()
    fuzzy_match, alternatives = _fuzzy_match_reinvention(prompt)
    regex_match = any(p.search(prompt) for p in _BUILD_FROM_SCRATCH_PATTERNS)
    if not fuzzy_match and not regex_match:
        return HookResult.allow()
    if fuzzy_match and alternatives:
        alt_list = ", ".join(alternatives[:4])
        return HookResult.allow(
            f"🔄 **BUILD-VS-BUY CHECK** - Detected: **{fuzzy_match}**\n"
            f"💡 Existing solutions: {alt_list}\n\n"
            "Before building custom:\n"
            "- [ ] Explain why existing solutions don't fit\n"
            "- [ ] Confirm user wants custom implementation\n\n"
            "💰 +5 confidence for suggesting alternatives (`premise_challenge`)"
        )
    return HookResult.allow(
        "🔄 **BUILD-VS-BUY CHECK** (Principle #23)\n"
        "Before building custom, verify:\n"
        "- [ ] Searched for existing tools/libraries\n"
        "- [ ] Listed 2-3 alternatives with pros/cons\n"
        "- [ ] User explicitly wants custom OR existing solutions don't fit\n\n"
        "💰 +5 confidence for suggesting alternatives (`premise_challenge`)"
    )


@register_hook("confidence_approval_gate", priority=7)
def check_confidence_approval_gate(data: dict, state: SessionState) -> HookResult:
    """Handle explicit trust restoration requests requiring approval."""
    prompt = data.get("prompt", "")
    if not prompt:
        return HookResult.allow()
    prompt_upper = prompt.upper()
    if "CONFIDENCE_BOOST_APPROVED" in prompt_upper:
        pending = state.nudge_history.get("confidence_boost_pending", {})
        if pending.get("requested", False):
            requested_delta = pending.get("delta", 15)
            old_confidence = state.confidence
            update_confidence(state, requested_delta, "trust_regained (approved)")
            state.nudge_history["confidence_boost_pending"] = {"requested": False}
            return HookResult.allow(
                "✅ **Confidence Restored**\n\n"
                + format_confidence_change(
                    old_confidence, state.confidence, "(trust_regained)"
                )
            )
        return HookResult.allow()
    trust_patterns = [
        r"\btrust\s+regained\b",
        r"\bconfidence\s+(?:restored|boost(?:ed)?)\b",
        r"\brestore\s+(?:my\s+)?confidence\b",
    ]
    for pattern in trust_patterns:
        if re.search(pattern, prompt, re.IGNORECASE):
            approval_msg = generate_approval_prompt(
                state.confidence,
                requested_delta=15,
                reasons=["User requested trust restoration"],
            )
            if "confidence_boost_pending" not in state.nudge_history:
                state.nudge_history["confidence_boost_pending"] = {}
            state.nudge_history["confidence_boost_pending"]["requested"] = True
            state.nudge_history["confidence_boost_pending"]["delta"] = 15
            state.nudge_history["confidence_boost_pending"]["turn"] = state.turn_count
            return HookResult.allow(approval_msg)
    return HookResult.allow()


@register_hook("confidence_dispute", priority=8)
def check_confidence_dispute(data: dict, state: SessionState) -> HookResult:
    """Handle false positive disputes for confidence reducers."""
    prompt = data.get("prompt", "")
    if not prompt:
        return HookResult.allow()
    is_dispute, reducer_name, reason = detect_dispute_in_prompt(prompt)
    if not is_dispute:
        return HookResult.allow()
    if not reducer_name:
        recent = get_recent_reductions(state, turns=3)
        if len(recent) == 1:
            reducer_name = recent[0]
        elif recent:
            return HookResult.allow(
                f"🔍 **Which reducer?** Multiple fired recently:\n"
                f"  {', '.join(recent)}\n"
                f"Say `FP: <reducer_name>` to specify."
            )
        else:
            return HookResult.allow(
                "⚠️ No recent confidence reductions to dispute.\n"
                "Use `FP: <reducer_name>` to specify which reducer."
            )
    old_confidence = state.confidence
    restore_amount, message = dispute_reducer(state, reducer_name, reason)
    if restore_amount > 0:
        update_confidence(state, restore_amount, f"FP:{reducer_name}")
        change_msg = format_confidence_change(
            old_confidence, state.confidence, f"(FP: {reducer_name})"
        )
        return HookResult.allow(f"{message}\n{change_msg}")
    return HookResult.allow(message)


@register_hook("verified_library_unlock", priority=9)
def check_verified_library(data: dict, state: SessionState) -> HookResult:
    """Unlock research_gate when user says VERIFIED."""
    from session_state import track_library_researched

    prompt = data.get("prompt", "").strip()
    if not prompt:
        return HookResult.allow()
    if not re.search(r"\bverified\b", prompt, re.IGNORECASE):
        return HookResult.allow()
    blocked_libs = state.get("research_gate_blocked_libs", [])
    if not blocked_libs:
        return HookResult.allow()
    for lib in blocked_libs:
        track_library_researched(state, lib)
    state.set("research_gate_blocked_libs", [])
    return HookResult.allow(
        f"✅ **VERIFIED**: Marked as researched: {', '.join(blocked_libs)}\n"
        f"Research gate unlocked for these libraries."
    )
