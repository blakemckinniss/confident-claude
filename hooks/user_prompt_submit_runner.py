#!/usr/bin/env python3
"""
Composite UserPromptSubmit Runner: Runs all UserPromptSubmit hooks in a single process.

PERFORMANCE: ~50ms for 12 hooks vs ~500ms for individual processes (10x faster)

HOOKS INDEX (by priority):
  GATING (0-10):
    1  goal_anchor              - Block scope expansion, warn on drift
    3  confidence_initializer   - Assess confidence, mandate research/external
    5  intake_protocol          - Show complexity-tiered checklists
    7  confidence_approval_gate - Handle trust restoration requests
    8  confidence_dispute       - Handle false positive reducer disputes

  EXTRACTION (15-25):
    15 intention_tracker   - Extract mentioned files/searches

  CONTEXT (30-70):
    30 prompt_disclaimer   - System context + task checklist
    35 project_context     - Git state, project structure
    40 memory_injector     - Lessons, spark, decisions, scope
    45 context_injector    - Session state, command suggestions
    50 reminder_injector   - Custom trigger-based reminders

  SUGGESTIONS (75-95):
    72 self_heal_diagnostic - Diagnostic commands when self-heal active
    75 proactive_nudge     - Actionable suggestions from state
    80 ops_nudge           - Tool suggestions (comprehensive)
    85 ops_awareness       - Script awareness (fallback)
    86 ops_audit_reminder  - Periodic unused tool reminder (v3.9)
    89 expert_probe        - Force probing questions, assume user needs guidance
    90 resource_pointer    - Sparse pointers to resources
    91 work_patterns       - Assumptions, rollback, confidence, integration
    93 quality_signals     - Pattern smells, context decay alerts
    95 response_format     - Structured response sections (docs/debt/next)

ARCHITECTURE:
  - Hooks register via @register_hook(name, priority)
  - Lower priority = runs first
  - First DENY wins (for gating hooks)
  - Contexts are aggregated and joined
  - Single state load/save per invocation
"""

import _lib_path  # noqa: F401
import sys
import json
import re
import time
import os
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from typing import Callable, Optional
from pathlib import Path

# Performance: cached file I/O and git commands
from _cache import (
    cached_file_read,
    cached_json_read,
    cached_git_branch,
    cached_git_status,
)

from session_state import (
    load_state,
    save_state,
    SessionState,
    set_goal,
    check_goal_drift,
    should_nudge,
    record_nudge,
    start_feature,
    add_pending_file,
    add_pending_search,
    add_domain_signal,
    Domain,
    generate_context,
    get_ops_tool_stats,
    get_unused_ops_tools,
    update_confidence,
    set_confidence,
)
from _hook_result import HookResult

# Confidence system
from confidence import (
    # Rock bottom system
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
    # False positive dispute system
    detect_dispute_in_prompt,
    dispute_reducer,
    get_recent_reductions,
)

# =============================================================================
# HOOK REGISTRY

# Format: (name, check_function, priority)
HOOKS: list[tuple[str, Callable, int]] = []


def register_hook(name: str, priority: int = 50):
    """Decorator to register a hook check function.

    Hooks can be disabled via environment variable:
        CLAUDE_HOOK_DISABLE_<NAME>=1

    Example:
        CLAUDE_HOOK_DISABLE_GOAL_ANCHOR=1 claude
    """

    def decorator(func: Callable[[dict, SessionState], HookResult]):
        # Check if hook is disabled via environment variable
        env_key = f"CLAUDE_HOOK_DISABLE_{name.upper()}"
        if os.environ.get(env_key, "0") == "1":
            return func  # Skip registration
        HOOKS.append((name, func, priority))
        return func

    return decorator


# =============================================================================
# PATHS AND CONFIG
# =============================================================================

SCRIPT_DIR = Path(__file__).parent
CLAUDE_DIR = SCRIPT_DIR.parent
MEMORY_DIR = CLAUDE_DIR / "memory"
REMINDERS_DIR = CLAUDE_DIR / "reminders"
OPS_DIR = CLAUDE_DIR / "ops"

# Feature toggles
SESSION_RAG_ENABLED = os.environ.get("CLAUDE_SESSION_RAG", "0") == "1"
COMMAND_SUGGEST_ENABLED = os.environ.get("CLAUDE_CMD_SUGGEST", "1") == "1"

# Stop words for keyword extraction
STOP_WORDS = frozenset(
    [
        "the",
        "a",
        "an",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
        "will",
        "would",
        "could",
        "should",
        "may",
        "might",
        "must",
        "shall",
        "can",
        "need",
        "dare",
        "to",
        "of",
        "in",
        "for",
        "on",
        "with",
        "at",
        "by",
        "from",
        "as",
        "into",
        "through",
        "during",
        "before",
        "after",
        "above",
        "below",
        "and",
        "but",
        "if",
        "or",
        "because",
        "until",
        "while",
        "this",
        "that",
        "these",
        "those",
        "what",
        "which",
        "who",
        "whom",
        "i",
        "me",
        "my",
        "you",
        "your",
        "we",
        "our",
        "they",
        "them",
        "it",
        "its",
        "he",
        "she",
        "him",
        "her",
        "his",
        "hers",
        "please",
        "thanks",
        "help",
        "know",
        "think",
        "look",
        "see",
        "try",
        "just",
        "get",
        "make",
        "use",
        "want",
        "like",
        "so",
        "then",
        "there",
    ]
)


def extract_keywords(text: str, min_length: int = 4) -> list[str]:
    """Extract meaningful keywords from text."""
    words = re.findall(r"\b[a-z_][a-z0-9_]*\b", text.lower())
    keywords = [w for w in words if len(w) >= min_length and w not in STOP_WORDS]
    seen = set()
    return [k for k in keywords if not (k in seen or seen.add(k))][:15]


# =============================================================================
# GATING HOOKS (priority 0-10)
# =============================================================================

# Scope expansion patterns (pre-compiled for performance)
_SCOPE_EXPANSION_PATTERNS = [
    re.compile(
        r"(?:now|also|next|then)\s+(?:let'?s?|we\s+should|i\s+want|can\s+you)\s+",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:add|create|implement|build|write)\s+(?:a\s+)?(?:new|another)\s+",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:before\s+we|while\s+we're|since\s+we're)\s+(?:here|at\s+it)", re.IGNORECASE
    ),
    re.compile(r"(?:one\s+more\s+thing|actually|wait)", re.IGNORECASE),
    re.compile(
        r"(?:unrelated|different|separate)\s+(?:thing|task|feature)", re.IGNORECASE
    ),
]
EXPLICIT_SWITCH_KEYWORDS = [
    "switch to",
    "move on to",
    "let's do",
    "new task",
    "different feature",
    "forget about",
    "instead of",
    "actually let's",
    "change of plans",
]


def detect_scope_expansion(state: SessionState, prompt: str) -> tuple[bool, str]:
    """Detect if prompt is expanding scope beyond original goal."""
    if not state.original_goal:
        return False, ""
    prompt_lower = prompt.lower()
    for keyword in EXPLICIT_SWITCH_KEYWORDS:
        if keyword in prompt_lower:
            return True, f"Explicit scope switch detected: '{keyword}'"
    for pattern in _SCOPE_EXPANSION_PATTERNS:
        if pattern.search(prompt_lower):
            return True, "Scope expansion pattern detected"
    # Check for many new keywords
    original_keywords = set(state.goal_keywords)
    prompt_words = set(re.findall(r"\b[a-z]{4,}\b", prompt_lower))
    common = {
        "this",
        "that",
        "with",
        "from",
        "have",
        "been",
        "will",
        "would",
        "could",
        "should",
        "make",
        "just",
        "like",
        "want",
        "need",
        "some",
    }
    prompt_words -= common
    new_keywords = prompt_words - original_keywords
    if len(new_keywords) > 5 and len(original_keywords) > 0:
        if len(prompt_words & original_keywords) < 2:
            return (
                True,
                f"Significant new scope detected ({len(new_keywords)} new terms)",
            )
    return False, ""


@register_hook("confidence_override", priority=0)
def check_confidence_override(data: dict, state: SessionState) -> HookResult:
    """Allow manual confidence override via SET_CONFIDENCE=X in prompt.

    Example: "SET_CONFIDENCE=70" sets confidence to 70%.
    This is the ultimate escape hatch for the confidence system.
    """
    prompt = data.get("prompt", "")

    # Look for SET_CONFIDENCE=X pattern
    match = re.search(r"\bSET_CONFIDENCE\s*=\s*(\d+)\b", prompt, re.IGNORECASE)
    if not match:
        return HookResult.allow()

    try:
        new_confidence = int(match.group(1))
        new_confidence = max(0, min(100, new_confidence))  # Clamp to 0-100
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


# Sentiment patterns for quick detection
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
    r"\bi\s+said\b",  # User repeating themselves = frustration
    r"\bagain\s*[?!]",  # "Again?" = frustration
]


@register_hook("user_sentiment", priority=2)
def check_user_sentiment(data: dict, state: SessionState) -> HookResult:
    """Adjust confidence based on user sentiment in prompt.

    Positive sentiment: +3 (encouragement)
    Negative sentiment: -3 (frustration signal)
    """
    prompt = data.get("prompt", "")
    if not prompt or len(prompt) > 100:  # Only short prompts for sentiment
        return HookResult.allow()

    prompt_lower = prompt.lower().strip()

    # Check positive sentiment
    for pattern in POSITIVE_SENTIMENT:
        if re.search(pattern, prompt_lower, re.IGNORECASE):
            old_conf = state.confidence
            update_confidence(state, 3, "positive_sentiment")
            if state.confidence != old_conf:
                return HookResult.allow(
                    f"😊 Positive sentiment: {old_conf}% → {state.confidence}% (+3)"
                )
            return HookResult.allow()

    # Check negative sentiment
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


@register_hook("goal_anchor", priority=1)
def check_goal_anchor(data: dict, state: SessionState) -> HookResult:
    """Prevent scope drift and block scope expansion."""
    prompt = data.get("prompt", "")
    if not prompt:
        return HookResult.allow()

    # Project-aware goal isolation
    current_project_id = ""
    try:
        from project_detector import get_current_project

        context = get_current_project()
        current_project_id = context.project_id
    except Exception:
        pass

    if state.original_goal and state.goal_project_id and current_project_id:
        if current_project_id != state.goal_project_id:
            # Project changed - reset goal state
            state.original_goal = ""
            state.goal_keywords = []
            state.goal_set_turn = 0
            state.goal_project_id = ""
            if "scope_expansion" in state.nudge_history:
                del state.nudge_history["scope_expansion"]
            if "goal_drift" in state.nudge_history:
                del state.nudge_history["goal_drift"]

    # Set goal if not already set
    if not state.original_goal:
        set_goal(state, prompt)
        start_feature(state, prompt[:100])
        state.goal_project_id = current_project_id
        return HookResult.allow()

    # SUDO SCOPE bypass
    if "SUDO SCOPE" in prompt.upper():
        state.original_goal = ""
        state.goal_keywords = []
        state.goal_set_turn = 0
        state.goal_project_id = ""
        if "scope_expansion" in state.nudge_history:
            del state.nudge_history["scope_expansion"]
        clean_prompt = re.sub(
            r"\bSUDO\s+SCOPE\b", "", prompt, flags=re.IGNORECASE
        ).strip()
        set_goal(state, clean_prompt)
        start_feature(state, clean_prompt[:100])
        state.goal_project_id = current_project_id
        return HookResult.allow()

    # Check scope expansion
    is_expanding, expansion_reason = detect_scope_expansion(state, prompt)
    if is_expanding:
        show, severity = should_nudge(state, "scope_expansion", expansion_reason)
        if show:
            record_nudge(state, "scope_expansion", expansion_reason)
            times_warned = state.nudge_history.get("scope_expansion", {}).get(
                "times_shown", 0
            )
            if times_warned >= 2 or severity == "escalate":
                return HookResult.deny(
                    f"**SCOPE EXPANSION BLOCKED** (One-Feature-Per-Session)\n\n"
                    f"🎯 **Current goal**: {state.original_goal[:80]}\n"
                    f"🚫 **Detected**: {expansion_reason}\n\n"
                    f"**Options:**\n"
                    f"1. Complete current feature first, then start new session\n"
                    f"2. Add 'SUDO SCOPE' to explicitly override\n"
                    f"3. Rephrase request as continuation of current goal"
                )
            else:
                return HookResult.allow(
                    f"⚠️ **SCOPE EXPANSION DETECTED**\n"
                    f'🎯 Current goal: "{state.original_goal[:60]}..."\n'
                    f"🔀 {expansion_reason}\n\n"
                    f"Finish current feature before switching. (Will block after {2 - times_warned} more attempts)"
                )

    # Check drift
    is_drifting, drift_message = check_goal_drift(state, prompt)
    if is_drifting:
        show, severity = should_nudge(state, "goal_drift", drift_message)
        if show:
            record_nudge(state, "goal_drift", drift_message)
            if severity == "escalate":
                drift_message = f"🚨 **REPEATED DRIFT WARNING** (ignored {state.nudge_history.get('goal_drift', {}).get('times_ignored', 0)}x)\n{drift_message}"
            return HookResult.allow(f"\n{drift_message}\n")

    return HookResult.allow()


# =============================================================================
# CONFIDENCE SYSTEM HOOKS


@register_hook("rock_bottom_realignment", priority=2)
def check_rock_bottom(data: dict, state: SessionState) -> HookResult:
    """Force realignment questions when confidence hits rock bottom.

    At <= 10% confidence, Claude MUST ask realignment questions before continuing.
    After user answers, confidence is restored to 85%.
    """
    prompt = data.get("prompt", "").strip()

    # Skip if not at rock bottom
    if not is_rock_bottom(state.confidence):
        return HookResult.allow()

    # Check if realignment already completed this session
    if check_realignment_complete(state):
        return HookResult.allow()

    # Check if user just answered realignment questions (detect answer patterns)
    # AskUserQuestion responses typically have "Answer:" prefix or are selections
    answer_patterns = [
        r"^(continue|new|debug|careful|fast|ask|misunderstood|technical|wrong|nothing)",
        r"^\d\.",  # Numbered selection
        r"^(a|b|c|d)\)",  # Letter selection
    ]
    is_answer = any(re.search(p, prompt.lower()) for p in answer_patterns)

    # Also check if user explicitly says something positive/confirming
    positive_patterns = [r"^(ok|yes|sure|go|proceed|continue|let's|alright|good)"]
    is_positive = any(re.search(p, prompt.lower()) for p in positive_patterns)

    if is_answer or is_positive or len(prompt) < 30:
        # User answered - restore confidence!
        new_confidence = mark_realignment_complete(state)
        old_confidence = state.confidence
        set_confidence(state, new_confidence, "rock bottom realignment complete")

        return HookResult.allow(
            f"🔄 **REALIGNMENT COMPLETE**\n"
            f"Confidence restored: {old_confidence}% → {state.confidence}%\n\n"
            f"Ready to proceed with renewed focus."
        )

    # First time at rock bottom - inject realignment requirement
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


# =============================================================================


@register_hook("confidence_initializer", priority=3)
def check_confidence_initializer(data: dict, state: SessionState) -> HookResult:
    """Initialize and assess confidence on every prompt.

    Trust Debt System: Hitting the floor has consequences.
    - Each floor hit increments reputation_debt
    - While debt > 0: max tier capped at CERTAINTY (can't reach TRUSTED/EXPERT)
    - Debt decays via test_pass/build_success (+1 debt cleared per success)
    """
    prompt = data.get("prompt", "")

    # Floor with Trust Debt - hitting floor has consequences
    CONFIDENCE_FLOOR = 70
    if state.confidence == 0:
        set_confidence(state, DEFAULT_CONFIDENCE, "session initialization")
    elif state.confidence < CONFIDENCE_FLOOR:
        # Increment trust debt before resetting - repeated floor hits accumulate
        old_debt = getattr(state, "reputation_debt", 0)
        state.reputation_debt = old_debt + 1
        set_confidence(
            state, CONFIDENCE_FLOOR, f"floor reset (debt now {state.reputation_debt})"
        )

    # Skip further analysis for trivial prompts
    if not prompt or len(prompt) < 20:
        return HookResult.allow()

    # Save prompt for contradiction detection in post_tool_use
    state.last_user_prompt = prompt

    parts = []

    # Assess prompt complexity and adjust
    delta, reasons = assess_prompt_complexity(prompt)
    old_confidence = state.confidence
    if delta != 0:
        update_confidence(state, delta, ", ".join(reasons))

    # Check for user correction patterns (reducer)
    correction_reducer = UserCorrectionReducer()
    last_trigger = state.nudge_history.get(
        "confidence_reducer_user_correction", {}
    ).get("last_turn", -999)
    if correction_reducer.should_trigger({"prompt": prompt}, state, last_trigger):
        update_confidence(state, correction_reducer.delta, correction_reducer.name)
        if "confidence_reducer_user_correction" not in state.nudge_history:
            state.nudge_history["confidence_reducer_user_correction"] = {}
        state.nudge_history["confidence_reducer_user_correction"]["last_turn"] = (
            state.turn_count
        )
        parts.append(
            format_confidence_change(
                old_confidence, state.confidence, f"({correction_reducer.name})"
            )
        )
        old_confidence = state.confidence

    # Check for positive feedback (increasers)
    triggered_increasers = apply_increasers(state, {"prompt": prompt})
    for name, inc_delta, desc, requires_approval in triggered_increasers:
        if not requires_approval:
            update_confidence(state, inc_delta, name)
            parts.append(
                format_confidence_change(old_confidence, state.confidence, f"({name})")
            )
            old_confidence = state.confidence

    # Cap confidence at 85% after user prompt (harsh - must earn trust)
    # BUT: Don't cap if recent verified boost (test_pass, build_success)
    PROMPT_CONFIDENCE_CAP = 85
    if state.confidence > PROMPT_CONFIDENCE_CAP:
        # Check for recent verified boosts (within last 3 turns)
        verified_increasers = ["test_pass", "build_success"]
        has_recent_verified = False
        for inc_name in verified_increasers:
            key = f"confidence_increaser_{inc_name}"
            last_turn = state.nudge_history.get(key, {}).get("last_turn", -999)
            if state.turn_count - last_turn <= 3:
                has_recent_verified = True
                break

        if has_recent_verified:
            # Don't cap - verified success earned this confidence
            parts.append(
                f"✅ Confidence at {state.confidence}% (verified success protected)"
            )
        else:
            # Cap it - no recent verified boost
            set_confidence(
                state, PROMPT_CONFIDENCE_CAP, "prompt cap (no verified boost)"
            )
            parts.append(
                f"⚖️ Confidence capped at {PROMPT_CONFIDENCE_CAP}% "
                "(earn higher via verified success)"
            )

    # Check if external consultation is mandatory
    mandatory, mandatory_msg = should_mandate_external(state.confidence)
    if mandatory:
        parts.append(mandatory_msg)

    # Check if research is required
    elif state.confidence < 50:
        require_research, research_msg = should_require_research(state.confidence, {})
        if require_research:
            parts.append(research_msg)

    # Always show current confidence status at start of complex prompts
    if len(prompt) > 100:
        tier_name, emoji, desc = get_tier_info(state.confidence)
        parts.insert(0, f"{emoji} **Confidence: {state.confidence}% ({tier_name})**")

    return HookResult.allow("\n\n".join(parts)) if parts else HookResult.allow()


@register_hook("confidence_approval_gate", priority=7)
def check_confidence_approval_gate(data: dict, state: SessionState) -> HookResult:
    """Handle explicit trust restoration requests requiring approval."""
    prompt = data.get("prompt", "")
    if not prompt:
        return HookResult.allow()

    prompt_upper = prompt.upper()

    # Check for approval confirmation
    if "CONFIDENCE_BOOST_APPROVED" in prompt_upper:
        # Check if there's a pending approval request
        pending = state.nudge_history.get("confidence_boost_pending", {})
        if pending.get("requested", False):
            requested_delta = pending.get("delta", 15)
            old_confidence = state.confidence
            update_confidence(state, requested_delta, "trust_regained (approved)")
            # Clear pending
            state.nudge_history["confidence_boost_pending"] = {"requested": False}
            return HookResult.allow(
                "✅ **Confidence Restored**\n\n"
                + format_confidence_change(
                    old_confidence, state.confidence, "(trust_regained)"
                )
            )
        return HookResult.allow()

    # Check for trust restoration request patterns
    trust_patterns = [
        r"\btrust\s+regained\b",
        r"\bconfidence\s+(?:restored|boost(?:ed)?)\b",
        r"\brestore\s+(?:my\s+)?confidence\b",
    ]

    for pattern in trust_patterns:
        if re.search(pattern, prompt, re.IGNORECASE):
            # Generate approval prompt
            approval_msg = generate_approval_prompt(
                state.confidence,
                requested_delta=15,
                reasons=["User requested trust restoration"],
            )
            # Mark as pending
            if "confidence_boost_pending" not in state.nudge_history:
                state.nudge_history["confidence_boost_pending"] = {}
            state.nudge_history["confidence_boost_pending"]["requested"] = True
            state.nudge_history["confidence_boost_pending"]["delta"] = 15
            state.nudge_history["confidence_boost_pending"]["turn"] = state.turn_count

            return HookResult.allow(approval_msg)

    return HookResult.allow()


# -----------------------------------------------------------------------------
# CONFIDENCE DISPUTE (priority 8) - Handle false positive disputes
# -----------------------------------------------------------------------------


@register_hook("confidence_dispute", priority=8)
def check_confidence_dispute(data: dict, state: SessionState) -> HookResult:
    """Handle false positive disputes for confidence reducers.

    Detects patterns like:
    - "false positive"
    - "FP: edit_oscillation"
    - "dispute cascade_block"
    - "that was wrong" (when recent reducer fired)
    """
    prompt = data.get("prompt", "")
    if not prompt:
        return HookResult.allow()

    # Detect dispute in prompt
    is_dispute, reducer_name, reason = detect_dispute_in_prompt(prompt)

    if not is_dispute:
        return HookResult.allow()

    # If no specific reducer named, check for recent reductions
    if not reducer_name:
        recent = get_recent_reductions(state, turns=3)
        if len(recent) == 1:
            # Only one recent reducer - assume that's the target
            reducer_name = recent[0]
        elif recent:
            # Multiple recent reducers - ask for clarification
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

    # Process the dispute
    old_confidence = state.confidence
    restore_amount, message = dispute_reducer(state, reducer_name, reason)

    if restore_amount > 0:
        update_confidence(state, restore_amount, f"FP:{reducer_name}")
        change_msg = format_confidence_change(
            old_confidence, state.confidence, f"(FP: {reducer_name})"
        )
        return HookResult.allow(f"{message}\n{change_msg}")

    return HookResult.allow(message)


# Complexity patterns for intake_protocol (pre-compiled for performance)
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

# Build-vs-Buy patterns - detect "reinventing the wheel" requests
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
_TRIVIAL_SIGNALS = [
    re.compile(r"^(fix|typo|update|change|rename)\s+\w+$", re.IGNORECASE),
    re.compile(r"^(run|execute|test)\s+", re.IGNORECASE),
    re.compile(r"^(commit|push|pr|status)\b", re.IGNORECASE),
    re.compile(r"^(hi|hello|thanks|ok|yes|no)\b", re.IGNORECASE),
    re.compile(r"^/\w+"),
    re.compile(r"^(what is|where is|show me)\s+\w+", re.IGNORECASE),
]


@register_hook("intake_protocol", priority=5)
def check_intake_protocol(data: dict, state: SessionState) -> HookResult:
    """Show complexity-tiered checklists."""
    prompt = data.get("prompt", "")
    if not prompt:
        return HookResult.allow()

    prompt_lower = prompt.lower().strip()
    prompt_len = len(prompt)

    # Check trivial
    for pattern in _TRIVIAL_SIGNALS:
        if pattern.search(prompt_lower):
            return HookResult.allow()

    if prompt_len < 50:
        return HookResult.allow()

    # Count complex signals
    complex_score = sum(1 for p in _COMPLEX_SIGNALS if p.search(prompt_lower))

    # Complex task
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

    # Medium task
    if complex_score >= 1 or prompt_len > 50:
        checklist = """
┌─ INTAKE ─────────────────────────────────┐
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

    # Check if this looks like a "build from scratch" request
    matches = [p for p in _BUILD_FROM_SCRATCH_PATTERNS if p.search(prompt)]
    if not matches:
        return HookResult.allow()

    # Don't trigger if user explicitly mentions learning/practice
    learning_patterns = re.compile(
        r"\b(learn|practice|exercise|tutorial|study|understand|educational)\b",
        re.IGNORECASE,
    )
    if learning_patterns.search(prompt):
        return HookResult.allow()

    return HookResult.allow(
        "🔄 **BUILD-VS-BUY CHECK** (Principle #23)\n"
        "Before building custom, verify:\n"
        "- [ ] Searched for existing tools/libraries\n"
        "- [ ] Listed 2-3 alternatives with pros/cons\n"
        "- [ ] User explicitly wants custom OR existing solutions don't fit\n\n"
        "💡 Earn +5 confidence by suggesting alternatives (`premise_challenge` increaser)"
    )


# =============================================================================
# EXTRACTION HOOKS (priority 15-25)
# =============================================================================

# File and search patterns (pre-compiled for performance)
_FILE_PATTERNS = [
    re.compile(
        r'[`"\']?([\w./\-]+\.(?:py|ts|tsx|js|jsx|json|yaml|yml|md|txt|toml|rs|go))[`"\']?',
        re.IGNORECASE,
    ),
    re.compile(r'[`"\']?((?:\.{0,2}/)?[\w\-]+/[\w./\-]+)[`"\']?', re.IGNORECASE),
]
_SEARCH_PATTERNS = [
    re.compile(
        r'(?:search|grep|find|look)\s+(?:for\s+)?[`"\']?(\w+)[`"\']?', re.IGNORECASE
    ),
    re.compile(
        r'(?:search|grep|find)\s+[`"\']?([^`"\']+)[`"\']?\s+(?:in|across)',
        re.IGNORECASE,
    ),
]


@register_hook("intention_tracker", priority=15)
def check_intention_tracker(data: dict, state: SessionState) -> HookResult:
    """Extract mentioned files/searches and track as pending."""
    prompt = data.get("prompt", "")
    if not prompt:
        return HookResult.allow()

    # Extract files
    files = []
    for pattern in _FILE_PATTERNS:
        for match in pattern.findall(prompt):
            if isinstance(match, tuple):
                match = match[0]
            if (
                match
                and not match.startswith("http")
                and ("/" in match or "." in match)
            ):
                clean = match.strip("`\"'")
                if 3 < len(clean) < 200:
                    files.append(clean)
    files = list(set(files))

    # Extract searches
    searches = []
    for pattern in _SEARCH_PATTERNS:
        for match in pattern.findall(prompt):
            if isinstance(match, tuple):
                match = match[0]
            clean = match.strip()
            if 2 < len(clean) < 100:
                searches.append(clean)
    searches = list(set(searches))

    if not files and not searches:
        return HookResult.allow()

    # Track in state
    for f in files:
        add_pending_file(state, f)
    for s in searches:
        add_pending_search(state, s)

    # If multiple items, remind about batching
    total = len(files) + len(searches)
    if total >= 2:
        items_preview = (files + searches)[:4]
        return HookResult.allow(
            f"⚡ DETECTED {total} ITEMS: {items_preview}\n"
            f"RULE: Batch ALL Read/Grep calls in ONE message. Do NOT read sequentially."
        )

    return HookResult.allow()


# =============================================================================
# CONTEXT HOOKS (priority 30-70)
# =============================================================================

DISCLAIMER = """⚠️ SYSTEM ASSISTANT MODE: Full access to /home/jinx & /mnt/c/. Ask if unsure. Read before edit. Verify before claiming. Use ~/projects/ for project work, ~/ai/ for AI projects/services, ~/.claude/tmp/ for scratch. For python scripts use /home/jinx/.claude/.venv/bin/python as interpreter. Always confirm file paths exist before referencing. For task tracking use `bd` (beads) NOT TodoWrite. ⚠️"""

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
# TECH VERSION RISK DATABASE (v3.7)
# Warns when prompt mentions fast-moving technologies that may have had major
# version changes since the AI's knowledge cutoff. Ported from claude-starter.
# =============================================================================

# Format: (compiled_pattern, release_date, risk_level, version_info)
# Risk levels: HIGH (breaking changes), MEDIUM (significant updates), LOW (minor)
# Pre-compiled at module load for performance
_TECH_RISK_DATABASE = [
    # Frontend frameworks - HIGH risk (frequent breaking changes)
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

# Keywords that suggest version-sensitive operations
VERSION_SENSITIVE_KEYWORDS = re.compile(
    r"\b(install|add|upgrade|migrate|config|setup|init|create|new project|from scratch|latest)\b",
    re.IGNORECASE,
)


@register_hook("tech_version_risk", priority=32)
def check_tech_version_risk(data: dict, state: SessionState) -> HookResult:
    """Warn about potentially outdated AI knowledge for fast-moving technologies.

    This catches prompts that mention technologies with recent major version changes,
    suggesting the user verify current documentation before proceeding.
    """
    prompt = data.get("prompt", "")
    if not prompt or len(prompt) < 10:
        return HookResult.allow()

    prompt_lower = prompt.lower()

    # Fast path: skip if no version-sensitive keywords
    if not VERSION_SENSITIVE_KEYWORDS.search(prompt_lower):
        return HookResult.allow()

    # Check against tech risk database
    warnings = []
    for compiled_pattern, release_date, risk_level, version_info in _TECH_RISK_DATABASE:
        match = compiled_pattern.search(prompt_lower)
        if match:
            # Additional check: is this about installation/config/setup?
            if VERSION_SENSITIVE_KEYWORDS.search(prompt_lower):
                emoji = (
                    "🚨"
                    if risk_level == "HIGH"
                    else "⚠️"
                    if risk_level == "MEDIUM"
                    else "ℹ️"
                )
                tech_name = match.group(0).upper()
                warnings.append(
                    f"{emoji} **{tech_name}** ({risk_level} risk): {version_info}\n"
                    f"   Released ~{release_date} - may be beyond knowledge cutoff"
                )
                # Limit to 2 warnings per prompt
                if len(warnings) >= 2:
                    break

    if not warnings:
        return HookResult.allow()

    # Check for package.json version mismatch (if in a project) - uses cached read
    version_mismatch = ""
    pkg_json_path = str(Path.cwd() / "package.json")
    pkg_data = cached_json_read(pkg_json_path)
    if pkg_data:
        try:
            deps = {
                **pkg_data.get("dependencies", {}),
                **pkg_data.get("devDependencies", {}),
            }

            # Check Tailwind version mismatch
            if "tailwind" in prompt_lower and "tailwindcss" in deps:
                installed = deps["tailwindcss"].lstrip("^~")
                if installed.startswith("4") and re.search(
                    r"v3|version\s*3", prompt_lower
                ):
                    version_mismatch = f"\n⚠️ **VERSION MISMATCH**: package.json has Tailwind v{installed} but prompt mentions v3"
                elif installed.startswith("3") and re.search(
                    r"v4|version\s*4", prompt_lower
                ):
                    version_mismatch = f"\n⚠️ **VERSION MISMATCH**: package.json has Tailwind v{installed} but prompt mentions v4"

            # Check React version mismatch
            if "react" in prompt_lower and "react" in deps:
                installed = deps["react"].lstrip("^~")
                if installed.startswith("19") and re.search(
                    r"v18|version\s*18", prompt_lower
                ):
                    version_mismatch = f"\n⚠️ **VERSION MISMATCH**: package.json has React v{installed} but prompt mentions v18"
        except (json.JSONDecodeError, OSError, KeyError):
            pass

    result = (
        "🔍 **OUTDATED KNOWLEDGE RISK**\n"
        + "\n".join(warnings)
        + version_mismatch
        + "\n\n💡 **Action**: Use `/research <tech>` or WebSearch to verify current docs before proceeding."
    )

    return HookResult.allow(result)


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


@register_hook("project_context", priority=35)
def check_project_context(data: dict, state: SessionState) -> HookResult:
    """Inject git state and project structure."""
    cwd = Path.cwd()
    home = Path.home()
    parts = []

    # Git info (uses cached git commands - 5s TTL)
    branch = cached_git_branch()
    if branch:
        git_parts = [f"branch: {branch}"]
        status = cached_git_status()
        if status:
            lines = [ln for ln in status.split("\n") if ln.strip()]
            modified = len([ln for ln in lines if len(ln) > 1 and ln[1] == "M"])
            untracked = len([ln for ln in lines if ln.startswith("??")])
            staged = len([ln for ln in lines if len(ln) > 0 and ln[0] in "MADRC"])
            changes = []
            if modified:
                changes.append(f"{modified} modified")
            if untracked:
                changes.append(f"{untracked} untracked")
            if staged:
                changes.append(f"{staged} staged")
            if changes:
                git_parts.append(f"changes: {', '.join(changes)}")
        parts.append(f"Git: {' | '.join(git_parts)}")

    # Directories
    found_dirs = [d for d in KEY_DIRS if (cwd / d).is_dir()]
    if found_dirs:
        parts.append(f"Dirs: {', '.join(found_dirs)}")

    if not parts:
        return HookResult.allow()

    # Context label
    label = "SYSTEM"
    if str(cwd).startswith(str(home / "projects")) and cwd != home / "projects":
        label = "PROJECT"
    elif str(cwd).startswith(str(home / "ai")) and cwd != home / "ai":
        label = "AI"

    return HookResult.allow(f"📁 {label}: {' | '.join(parts)}")


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


@register_hook("memory_injector", priority=40)
def check_memory_injector(data: dict, state: SessionState) -> HookResult:
    """Auto-surface relevant memories."""
    prompt = data.get("prompt", "")
    if not prompt or len(prompt) < 10:
        return HookResult.allow()

    keywords = extract_keywords(prompt)

    # Get spark associations (with 2s timeout to prevent hook slowdown)
    spark_associations = []
    try:
        from synapse_core import run_spark, MAX_ASSOCIATIONS, MAX_MEMORIES

        # Timeout wrapper - synapse can be slow if DB is large or network issues
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(run_spark, prompt)
            try:
                spark_result = future.result(timeout=2.0)
            except FuturesTimeoutError:
                spark_result = None  # Skip on timeout, don't block hook
        if spark_result:
            for assoc in spark_result.get("associations", []):
                spark_associations.append(assoc)
            for memory in spark_result.get("memories", []):
                spark_associations.append(memory)
            spark_associations = spark_associations[: MAX_ASSOCIATIONS + MAX_MEMORIES]
    except Exception:
        pass

    lessons = find_relevant_lessons(keywords) if keywords else []
    scope = get_active_scope()

    if not lessons and not scope and not spark_associations:
        return HookResult.allow()

    parts = []
    if spark_associations:
        assoc_lines = "\n".join(f"   * {a[:100]}" for a in spark_associations[:3])
        parts.append(f"SUBCONSCIOUS RECALL:\n{assoc_lines}")
    if lessons:
        lesson_lines = "\n".join(f"   * {lesson}" for lesson in lessons)
        parts.append(f"RELEVANT LESSONS:\n{lesson_lines}")
    if scope:
        scope_line = f"ACTIVE TASK: {scope['task']} [{scope['progress']}]"
        if scope["next"]:
            scope_line += f"\n   Next: {scope['next']}"
        parts.append(scope_line)

    return HookResult.allow("\n\n".join(parts))


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
        except Exception:
            pass

    return HookResult.allow("\n".join(parts)) if parts else HookResult.allow()


def parse_reminder_frontmatter(content: str) -> tuple[dict, str]:
    """Parse YAML frontmatter from reminder file."""
    if not content.startswith("---"):
        return {}, content
    lines = content.split("\n")
    end_idx = -1
    for i, line in enumerate(lines[1:], 1):
        if line.strip() == "---":
            end_idx = i
            break
    if end_idx == -1:
        return {}, content
    frontmatter_lines = lines[1:end_idx]
    body = "\n".join(lines[end_idx + 1 :]).strip()
    meta = {}
    current_key = None
    current_list = []
    for line in frontmatter_lines:
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


# =============================================================================
# SUGGESTION HOOKS (priority 72-95)
# =============================================================================


@register_hook("self_heal_diagnostic", priority=72)
def check_self_heal_diagnostic(data: dict, state: SessionState) -> HookResult:
    """Inject diagnostic guidance when self-heal mode is active.

    When framework errors require self-healing, inject specific diagnostic
    commands to help identify and fix the issue.
    """
    if not getattr(state, "self_heal_required", False):
        return HookResult.allow()

    target = getattr(state, "self_heal_target", "unknown")
    error = getattr(state, "self_heal_error", "unknown error")
    attempts = getattr(state, "self_heal_attempts", 0)
    max_attempts = getattr(state, "self_heal_max_attempts", 3)

    # Build diagnostic commands based on error type
    diagnostics = []

    # Generic diagnostics
    diagnostics.append("ruff check ~/.claude/hooks/  # Lint all hooks")

    # Path-specific diagnostics
    if "hook" in target.lower() or "runner" in target.lower():
        diagnostics.append(
            "~/.claude/.venv/bin/python -c \"import sys; sys.path.insert(0, '/home/jinx/.claude/hooks'); import pre_tool_use_runner\"  # Test import"
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


@register_hook("proactive_nudge", priority=75)
def check_proactive_nudge(data: dict, state: SessionState) -> HookResult:
    """Surface actionable suggestions based on state."""
    prompt = data.get("prompt", "")
    if not prompt or len(prompt) < 10 or prompt.startswith("/"):
        return HookResult.allow()
    if state.turn_count < 5:
        return HookResult.allow()

    suggestions = []

    # Pending files
    if state.pending_files:
        names = [Path(f).name for f in state.pending_files[:3]]
        suggestions.append(f"📂 Mentioned but unread: {names}")

    # Edits without verification
    if state.files_edited and not state.last_verify:
        if len(state.files_edited) >= 2:
            suggestions.append(
                f"✅ {len(state.files_edited)} files edited, no /verify run"
            )

    # Multiple edits without tests
    if any(c >= 3 for c in state.edit_counts.values()) and not state.tests_run:
        suggestions.append("🧪 Multiple edits without test run")

    # Consecutive failures
    if state.consecutive_failures >= 2:
        suggestions.append(
            f"⚠️ {state.consecutive_failures} failures - consider different approach"
        )

    # Integration greps pending
    if state.pending_integration_greps:
        funcs = [p["function"] for p in state.pending_integration_greps[:2]]
        suggestions.append(f"🔗 Grep callers for: {funcs}")

    # Background tasks pending
    if hasattr(state, "background_tasks") and state.background_tasks:
        # Filter to tasks from last 10 turns
        recent_bg = [
            t
            for t in state.background_tasks
            if state.turn_count - t.get("turn", 0) <= 10
        ]
        if recent_bg:
            types = [t.get("type", "agent")[:15] for t in recent_bg[:2]]
            suggestions.append(
                f"⏳ Background agents running: {types} - check with `TaskOutput`"
            )

    if not suggestions:
        return HookResult.allow()

    lines = ["💡 **PROACTIVE CHECKLIST:**"]
    lines.extend(f"  • {s}" for s in suggestions[:3])
    lines.append("  → Act on these or consciously skip them.")
    return HookResult.allow("\n".join(lines))


# Comprehensive tool triggers for ops_nudge (patterns pre-compiled for performance)
_TOOL_TRIGGERS = {
    "research": {
        "patterns": [
            re.compile(
                r"(latest|current|new)\s+(docs?|documentation|api|version)",
                re.IGNORECASE,
            ),
            re.compile(r"how\s+does\s+.+\s+work", re.IGNORECASE),
        ],
        "command": 'python3 .claude/ops/research.py "<query>"',
        "reason": "Live web search for current documentation",
    },
    "probe": {
        "patterns": [
            re.compile(r"what\s+(methods?|attributes?)", re.IGNORECASE),
            re.compile(
                r"(inspect|introspect)\s+(the\s+)?(api|object|class)", re.IGNORECASE
            ),
        ],
        "command": 'python3 .claude/ops/probe.py "<object_path>"',
        "reason": "Runtime introspection - see actual API before coding",
    },
    "xray": {
        "patterns": [
            re.compile(
                r"(find|list|show)\s+(all\s+)?(class|function)s?\s+in", re.IGNORECASE
            ),
            re.compile(r"ast\s+(analysis|search)", re.IGNORECASE),
        ],
        "command": "python3 .claude/ops/xray.py --type <class|function> --name <Name>",
        "reason": "AST-based structural code search",
    },
    "think": {
        "patterns": [
            re.compile(r"(complex|tricky)\s+(problem|issue|bug)", re.IGNORECASE),
            re.compile(r"(break\s+down|decompose)", re.IGNORECASE),
            re.compile(r"i('m| am)\s+(stuck|confused)", re.IGNORECASE),
        ],
        "command": 'python3 .claude/ops/think.py "<problem>"',
        "reason": "Structured problem decomposition",
    },
    "council": {
        "patterns": [
            re.compile(r"(major|big)\s+(decision|choice)", re.IGNORECASE),
            re.compile(r"(pros\s+and\s+cons|trade-?offs?)", re.IGNORECASE),
        ],
        "command": 'python3 .claude/ops/council.py "<proposal>"',
        "reason": "Multi-perspective analysis (Judge+Critic+Skeptic)",
    },
    "audit": {
        "patterns": [
            re.compile(r"(security|vulnerability)\s+(check|scan|audit)", re.IGNORECASE),
            re.compile(r"(safe|secure)\s+to\s+(deploy|commit)", re.IGNORECASE),
        ],
        "command": "python3 .claude/ops/audit.py <file>",
        "reason": "Security and code quality audit",
    },
    "void": {
        "patterns": [
            re.compile(r"(stub|todo|fixme|incomplete)", re.IGNORECASE),
            re.compile(r"(missing|forgot)\s+(implementation|handler)", re.IGNORECASE),
        ],
        "command": "python3 .claude/ops/void.py <file>",
        "reason": "Completeness check - finds stubs and gaps",
    },
    "orchestrate": {
        "patterns": [
            re.compile(
                r"(process|analyze|scan)\s+(all|many|multiple)\s+files?", re.IGNORECASE
            ),
            re.compile(r"(batch|bulk|aggregate)\s+(process|operation)", re.IGNORECASE),
        ],
        "command": 'python3 .claude/ops/orchestrate.py "<task description>"',
        "reason": "Claude API code_execution - 37% token reduction for batch tasks",
    },
    # PAL MCP tools (external LLM consultation)
    "pal_thinkdeep": {
        "patterns": [
            re.compile(r"(uncertain|not\s+sure)\s+(how|what|why)", re.IGNORECASE),
            re.compile(
                r"need\s+(to\s+)?(investigate|analyze|understand)", re.IGNORECASE
            ),
            re.compile(
                r"(complex|difficult)\s+(issue|problem|architecture)", re.IGNORECASE
            ),
            re.compile(r"what\s+can\s+we", re.IGNORECASE),
            re.compile(r"find\s+out\s+(why|how|what)", re.IGNORECASE),
        ],
        "command": "mcp__pal__thinkdeep",
        "reason": "PAL MCP: Multi-stage investigation with external LLM",
    },
    "pal_debug": {
        "patterns": [
            re.compile(
                r"(mysterious|strange|weird)\s+(bug|error|behavior)", re.IGNORECASE
            ),
            re.compile(r"(root\s+cause|why\s+is\s+this\s+happening)", re.IGNORECASE),
            re.compile(r"(debugging|troubleshoot)\s+(help|assistance)", re.IGNORECASE),
        ],
        "command": "mcp__pal__debug",
        "reason": "PAL MCP: Systematic debugging with hypothesis testing",
    },
    "pal_consensus": {
        "patterns": [
            re.compile(
                r"(multiple|different)\s+(perspectives?|opinions?|views?)",
                re.IGNORECASE,
            ),
            re.compile(r"(second\s+opinion|another\s+view)", re.IGNORECASE),
            re.compile(r"(consensus|agreement)\s+on", re.IGNORECASE),
            re.compile(r"what\s+is\s+the\s+best", re.IGNORECASE),
        ],
        "command": "mcp__pal__consensus",
        "reason": "PAL MCP: Multi-model consensus for decisions",
    },
    "pal_challenge": {
        "patterns": [
            re.compile(r"(am\s+i|are\s+we)\s+(right|wrong|correct)", re.IGNORECASE),
            re.compile(
                r"(challenge|question)\s+(this|my)\s+(assumption|approach)",
                re.IGNORECASE,
            ),
            re.compile(r"(sanity\s+check|reality\s+check)", re.IGNORECASE),
            re.compile(r"(can|should)\s+we\b", re.IGNORECASE),
        ],
        "command": "mcp__pal__challenge",
        "reason": "PAL MCP: Force critical thinking on assumptions",
    },
    "pal_codereview": {
        "patterns": [
            re.compile(r"\banti[- ]?patterns?\b", re.IGNORECASE),
            re.compile(r"\btechnical\s+debt\b", re.IGNORECASE),
            re.compile(r"\bcode\s+(smell|quality|review)\b", re.IGNORECASE),
        ],
        "command": "mcp__pal__codereview",
        "reason": "PAL MCP: Expert code review for quality issues",
    },
    "pal_apilookup": {
        "patterns": [
            re.compile(r"(latest|current|updated)\s+(api|sdk|docs?)", re.IGNORECASE),
            re.compile(r"(breaking\s+changes?|deprecat)", re.IGNORECASE),
            re.compile(r"(migration\s+guide|upgrade)", re.IGNORECASE),
            re.compile(
                r"\bresearch\b.*\b(api|library|framework|docs?)\b", re.IGNORECASE
            ),
            re.compile(r"get\s+the\s+latest", re.IGNORECASE),
        ],
        "command": "mcp__pal__apilookup",
        "reason": "PAL MCP: Current API/SDK documentation lookup",
    },
    "pal_chat": {
        "patterns": [
            re.compile(r"^\s*research\b", re.IGNORECASE),
            re.compile(r"\bresearch\s+(this|how|what|why)", re.IGNORECASE),
            re.compile(r"search\s+online", re.IGNORECASE),
        ],
        "command": "mcp__pal__chat",
        "reason": "PAL MCP: General consultation with external LLM",
    },
    # Crawl4AI MCP - PRIORITY: User's most important MCP for web data retrieval
    "crawl4ai": {
        "patterns": [
            # Direct web operations
            re.compile(
                r"(scrape|crawl|fetch|extract)\s+.*(web|page|site|url)", re.IGNORECASE
            ),
            re.compile(
                r"(get|read|pull)\s+.*(from\s+)?(url|website|page|article)",
                re.IGNORECASE,
            ),
            re.compile(
                r"(content|data|text)\s+(from|of)\s+.*(url|site|page)", re.IGNORECASE
            ),
            # URL mentions (very broad - any URL discussion)
            re.compile(r"https?://", re.IGNORECASE),
            re.compile(r"\burl\b.*\b(content|fetch|get|read)\b", re.IGNORECASE),
            # Documentation/article fetching
            re.compile(
                r"(read|fetch|get)\s+.*(docs?|documentation|readme)", re.IGNORECASE
            ),
            re.compile(r"(article|blog|post)\s+(content|text)", re.IGNORECASE),
            # Bypass/protection keywords (crawl4ai's strength)
            re.compile(
                r"(bypass|avoid|get\s+around)\s+.*(guard|block|protection|captcha)",
                re.IGNORECASE,
            ),
            re.compile(r"(cloudflare|bot\s+detect|anti-bot)", re.IGNORECASE),
            # Generic web data retrieval
            re.compile(r"(web|online)\s+(data|content|info)", re.IGNORECASE),
            re.compile(r"(download|retrieve)\s+.*(page|content)", re.IGNORECASE),
            # Competitive intelligence / research
            re.compile(
                r"(check|look\s+at|see)\s+(what|how)\s+.*(site|page|url)", re.IGNORECASE
            ),
        ],
        "command": "mcp__crawl4ai__crawl (single URL) or mcp__crawl4ai__search (discover URLs)",
        "reason": "🌟 Crawl4AI: JS rendering + bot bypass - BEST tool for web content retrieval",
    },
}


@register_hook("ops_nudge", priority=80)
def check_ops_nudge(data: dict, state: SessionState) -> HookResult:
    """Suggest ops tools based on prompt patterns."""
    prompt = data.get("prompt", "")
    if not prompt or len(prompt) < 10:
        return HookResult.allow()

    prompt_lower = prompt.lower()
    matches = []
    for tool_name, config in _TOOL_TRIGGERS.items():
        for pattern in config["patterns"]:
            if pattern.search(prompt_lower):
                matches.append((tool_name, config))
                break
        if len(matches) >= 3:
            break

    if not matches:
        return HookResult.allow()

    suggestions = []
    for tool_name, config in matches:
        display_name = tool_name.replace("_", " ").upper()
        suggestions.append(
            f"🛠️ {display_name}: {config['reason']}\n   → {config['command']}"
        )

    return HookResult.allow("OPS TOOLS AVAILABLE:\n" + "\n\n".join(suggestions))


# Simpler script catalog for ops_awareness (pre-compiled for performance)
_OPS_SCRIPTS = {
    "research": (
        [
            re.compile(r"look up", re.IGNORECASE),
            re.compile(r"find docs", re.IGNORECASE),
            re.compile(r"documentation", re.IGNORECASE),
        ],
        "Web search via Tavily API",
    ),
    "probe": (
        [
            re.compile(r"inspect.*object", re.IGNORECASE),
            re.compile(r"what methods", re.IGNORECASE),
            re.compile(r"api.*signature", re.IGNORECASE),
        ],
        "Runtime introspection",
    ),
    "xray": (
        [
            re.compile(r"find.*class", re.IGNORECASE),
            re.compile(r"find.*function", re.IGNORECASE),
            re.compile(r"code structure", re.IGNORECASE),
        ],
        "AST-based code search",
    ),
    "audit": (
        [
            re.compile(r"security.*check", re.IGNORECASE),
            re.compile(r"vulnerability", re.IGNORECASE),
        ],
        "Security audit",
    ),
    "void": (
        [
            re.compile(r"find.*stubs", re.IGNORECASE),
            re.compile(r"todo.*code", re.IGNORECASE),
            re.compile(r"incomplete", re.IGNORECASE),
        ],
        "Find stubs and TODOs",
    ),
    "think": (
        [
            re.compile(r"break.*down", re.IGNORECASE),
            re.compile(r"decompose", re.IGNORECASE),
            re.compile(r"complex.*problem", re.IGNORECASE),
        ],
        "Problem decomposition",
    ),
    "verify": (
        [
            re.compile(r"check.*exists", re.IGNORECASE),
            re.compile(r"verify.*file", re.IGNORECASE),
            re.compile(r"confirm.*works", re.IGNORECASE),
        ],
        "Reality checks",
    ),
    "remember": (
        [
            re.compile(r"save.*lesson", re.IGNORECASE),
            re.compile(r"remember.*this", re.IGNORECASE),
        ],
        "Persistent memory",
    ),
    "spark": (
        [
            re.compile(r"recall.*about", re.IGNORECASE),
            re.compile(r"what.*learned", re.IGNORECASE),
        ],
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


@register_hook("ops_audit_reminder", priority=86)
def check_ops_audit_reminder(data: dict, state: SessionState) -> HookResult:
    """Periodic reminder about ops tool usage and unused tools (v3.9).

    Fires occasionally to surface:
    - Tools that haven't been used in 7+ days
    - Suggestions for useful diagnostics
    """
    from _cooldown import check_and_reset_cooldown

    # Only run every 3 hours - check cooldown and reset if running
    if not check_and_reset_cooldown("ops_audit_reminder"):
        return HookResult.allow()

    parts = []

    # Check for unused tools (7 day threshold)
    unused = get_unused_ops_tools(days_threshold=7)
    if unused and len(unused) >= 5:
        # Only mention if significant number unused
        sample = unused[:5]
        parts.append(
            f"📊 **OPS TOOLS**: {len(unused)} tools unused in 7+ days: "
            f"`{', '.join(sample)}`{'...' if len(unused) > 5 else ''}"
        )

    # Check tool stats for suggestions
    stats = get_ops_tool_stats()
    if stats:
        # Find most-used tools (positive reinforcement)
        by_usage = sorted(
            stats.items(), key=lambda x: x[1].get("total_uses", 0), reverse=True
        )
        if by_usage:
            top_tool = by_usage[0][0]
            top_uses = by_usage[0][1].get("total_uses", 0)
            if top_uses >= 10:
                parts.append(f"💡 Most-used tool: `{top_tool}` ({top_uses} uses)")

        # Check for tools with high failure rates
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


# Tool index for resource_pointer
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


@register_hook("expert_probe", priority=89)
def check_expert_probe(data: dict, state: SessionState) -> HookResult:
    """Force AI to ask probing questions - assume user needs guidance."""
    prompt = data.get("prompt", "")
    if not prompt or len(prompt) < 15:
        return HookResult.allow()

    prompt_lower = prompt.lower()

    # Skip if already asking a question or giving explicit details
    if "?" in prompt or len(prompt) > 300:
        return HookResult.allow()

    # Skip trivial
    if re.match(r"^(yes|no|ok|hi|thanks|commit|push|/\w+)\b", prompt_lower):
        return HookResult.allow()

    probes = []

    # Vagueness Probe - vague improvement requests
    if re.search(r"\b(fix|improve|better|faster|clean|help|make it)\b", prompt_lower):
        if not re.search(
            r"\b(because|since|error|exception|line \d|specific)\b", prompt_lower
        ):
            probes.append(
                '❓ **VAGUENESS**: Ask "What specific behavior/output is wrong?"'
            )

    # Claim Challenge - unsubstantiated problem claims
    if re.search(
        r"\b(broken|doesn't work|not working|wrong|bug|issue|problem)\b", prompt_lower
    ):
        if not re.search(
            r"\b(error|traceback|expected|actual|instead|got)\b", prompt_lower
        ):
            probes.append(
                '🔍 **CLAIM CHECK**: Ask "Expected vs actual? Any error message?"'
            )

    # Scope Lock - ambiguous scope
    if re.search(r"\b(update|change|modify|refactor|rewrite)\b", prompt_lower):
        if not re.search(
            r"\b(file|function|class|line|method|in \w+\.)\b", prompt_lower
        ):
            probes.append('📍 **SCOPE**: Ask "Which specific files/functions?"')

    # Hidden Constraint Probe - new feature requests
    if re.search(r"\b(add|create|implement|build|new feature)\b", prompt_lower):
        if state.turn_count <= 3:  # Early in conversation
            probes.append(
                "🚧 **CONSTRAINTS**: Ask about edge cases, error handling, existing patterns"
            )

    # Expertise Assert - when user makes technical claims
    if re.search(
        r"\b(i think|probably|maybe|might be|could be|seems like)\b", prompt_lower
    ):
        probes.append(
            "🎓 **EXPERT MODE**: User uncertain - investigate first, don't assume they're right"
        )

    if not probes:
        return HookResult.allow()

    header = "🧠 **PROBE BEFORE ACTING** (assume user needs guidance):\n"
    return HookResult.allow(header + "\n".join(probes))


@register_hook("work_patterns", priority=91)
def check_work_patterns(data: dict, state: SessionState) -> HookResult:
    """Inject work behavior patterns - assumptions, rollback, confidence, integration."""
    prompt = data.get("prompt", "")
    if not prompt or len(prompt) < 40:
        return HookResult.allow()

    prompt_lower = prompt.lower()

    # Skip trivial
    if re.match(r"^(yes|no|ok|hi|hello|thanks|status|/\w+)\b", prompt_lower):
        return HookResult.allow()

    parts = []

    # Assumption Declaration - for edit/create/change requests
    if re.search(
        r"\b(edit|change|update|modify|fix|add|create|implement|refactor)\b",
        prompt_lower,
    ):
        parts.append(
            "🎯 **ASSUMPTIONS**: Before acting, state key assumptions (paths, APIs, behavior)"
        )

    # Rollback Breadcrumb - for destructive operations
    if re.search(
        r"\b(delete|remove|drop|reset|overwrite|replace|migrate)\b", prompt_lower
    ):
        parts.append("↩️ **ROLLBACK**: Note undo path before destructive ops")

    # Confidence Gate - for complex/uncertain requests
    if re.search(
        r"\b(should|best|optimal|recommend|which|how to|complex|tricky)\b", prompt_lower
    ):
        parts.append(
            "📊 **CONFIDENCE**: State confidence % and reasoning for recommendations"
        )

    # Integration Radar - for function/API changes
    if re.search(
        r"\b(function|method|api|endpoint|signature|interface|class)\b", prompt_lower
    ):
        parts.append("🔗 **INTEGRATION**: After edits, grep callers and note impact")

    # Impossibility Challenge - prevent learned helplessness
    if re.search(
        r"\b(can you|is it possible|can't|cannot|impossible|no way to|not able)\b",
        prompt_lower,
    ):
        parts.append(
            "🚫 **IMPOSSIBILITY CHECK**: Before claiming 'can't', verify: "
            "MCP tools, Task agents, WebSearch, /inventory. Try first."
        )

    # Parallel Opportunity - detect multi-item/multi-file work
    # Pattern: numbered lists, "and" chains, multiple files, bulk operations
    parallel_signals = [
        r"\b(1\.|2\.|3\.)",  # Numbered list
        r"\b(first|second|third|then|next|after that)\b",  # Sequential words
        r"\b(all|each|every|multiple|several|many)\s+(file|component|test|module)",  # Bulk
        r"\band\b.*\band\b",  # Multiple "and" (A and B and C)
        r"[,;]\s*\w+[,;]\s*\w+",  # Comma-separated items
    ]
    if any(re.search(p, prompt_lower) for p in parallel_signals):
        # Only nudge if we've had sequential patterns before
        if state.consecutive_single_tasks >= 1 or state.parallel_nudge_count >= 1:
            parts.append(
                "⚡ **PARALLEL AGENTS**: Multiple items detected. "
                "Spawn independent Task agents in ONE message, not sequentially."
            )

    if not parts:
        return HookResult.allow()

    return HookResult.allow("\n".join(parts))


@register_hook("quality_signals", priority=93)
def check_quality_signals(data: dict, state: SessionState) -> HookResult:
    """Inject quality signals - pattern smells, context decay."""
    prompt = data.get("prompt", "")
    parts = []

    # Pattern Smell - for code review/refactor
    prompt_lower = prompt.lower() if prompt else ""
    if re.search(r"\b(review|refactor|clean|improve|optimize)\b", prompt_lower):
        parts.append(
            "👃 **PATTERN SMELL**: Flag anti-patterns with severity (🟢minor → 🔴critical)"
        )

    # Context Decay Alert - based on turn count
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


@register_hook("response_format", priority=95)
def check_response_format(data: dict, state: SessionState) -> HookResult:
    """Inject structured response format requirements."""
    prompt = data.get("prompt", "")
    if not prompt or len(prompt) < 30:
        return HookResult.allow()

    # Skip trivial prompts
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


@register_hook("resource_pointer", priority=90)
def check_resource_pointer(data: dict, state: SessionState) -> HookResult:
    """Surface sparse pointers to possibly relevant resources."""
    prompt = data.get("prompt", "")
    if not prompt or len(prompt) < 15:
        return HookResult.allow()
    if re.match(r"^(commit|push|status|help|yes|no|ok|thanks)\b", prompt.lower()):
        return HookResult.allow()

    keywords = extract_keywords(prompt)
    if len(keywords) < 2:
        return HookResult.allow()

    kw_set = set(keywords)
    parts = []

    # Match folders
    cwd = Path.cwd()
    for folder, hints in FOLDER_HINTS.items():
        if (cwd / folder.rstrip("/")).exists():
            score = len(kw_set & set(hints))
            if score >= 1:
                parts.append(f"  • {folder}")
        if len(parts) >= 2:
            break

    # Match tools
    tool_parts = []
    for tool, (tool_kws, desc, example) in TOOL_INDEX.items():
        score = len(kw_set & set(tool_kws))
        if score >= 1:
            tool_parts.append((f"  • /{tool} - {desc}", f"    eg: {example}", score))
        if len(tool_parts) >= 2:
            break
    tool_parts.sort(key=lambda x: -x[2])
    for t, e, _ in tool_parts[:2]:
        parts.append(t)
        parts.append(e)

    if not parts:
        return HookResult.allow()

    return HookResult.allow("📍 POSSIBLY RELEVANT:\n" + "\n".join(parts))


# -----------------------------------------------------------------------------
# BEADS PERIODIC SYNC (priority 2) - Sync beads every 10 minutes
# -----------------------------------------------------------------------------

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
# MAIN RUNNER
# =============================================================================


def run_hooks(data: dict, state: SessionState) -> dict:
    """Run all hooks and return aggregated result."""
    # Sort by priority
    sorted_hooks = sorted(HOOKS, key=lambda x: x[2])
    contexts = []

    for name, check_func, priority in sorted_hooks:
        try:
            result = check_func(data, state)

            # First deny wins
            if result.decision == "deny":
                return {
                    "hookSpecificOutput": {
                        "hookEventName": "UserPromptSubmit",
                        "permissionDecision": "deny",
                        "permissionDecisionReason": result.reason,
                    }
                }

            # Collect contexts
            if result.context:
                contexts.append(result.context)

        except Exception as e:
            print(f"[ups-runner] Hook {name} error: {e}", file=sys.stderr)

    # Build output
    output = {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit"}}
    if contexts:
        # Limit to avoid context explosion
        output["hookSpecificOutput"]["additionalContext"] = "\n\n".join(contexts[:8])

    return output


def main():
    """Main entry point."""
    start = time.time()

    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit"}}))
        sys.exit(0)

    # Normalize prompt field
    prompt = data.get("prompt", "") or data.get("user_prompt", "")
    data["prompt"] = prompt

    # Single state load
    state = load_state()

    # Increment turn count
    state.turn_count += 1

    # Run all hooks
    result = run_hooks(data, state)

    # Single state save
    save_state(state)

    # Output result
    print(json.dumps(result))

    # Debug timing
    elapsed = (time.time() - start) * 1000
    if elapsed > 100:
        print(f"[ups-runner] Slow: {elapsed:.1f}ms", file=sys.stderr)

    sys.exit(0)


if __name__ == "__main__":
    main()
