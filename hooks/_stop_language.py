"""
Language pattern detection hooks for Stop runner (priorities 46-48).

Extracted from stop_runner.py to reduce file size.

Hooks:
  46 bad_language_detector        - Detect and penalize bad language patterns
  47 good_language_detector       - Reward verification language patterns
  48 verification_theater_detector - Catch claims without tool evidence
"""

import re
from pathlib import Path

from session_state import SessionState
from _stop_registry import register_hook, StopHookResult


# =============================================================================
# SHARED UTILITIES
# =============================================================================


def _read_tail_content(path: str, tail_bytes: int = 10000) -> str | None:
    """Read last N bytes of file as string, or None on error."""
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - tail_bytes))
            return f.read().decode("utf-8", errors="ignore").lower()
    except (OSError, PermissionError):
        return None


# =============================================================================
# BAD LANGUAGE PATTERNS
# =============================================================================

BAD_LANGUAGE_PATTERNS = {
    "overconfident_completion": {
        "delta": -15,
        "patterns": [
            r"\b100%\s*(done|complete|finished|ready)\b",
            r"\bcompletely\s+(done|finished|ready)\b",
            r"\bperfectly\s+(done|finished|working)\b",
            r"\bfully\s+complete[d]?\b",
        ],
    },
    "deferral": {
        "delta": -12,
        "patterns": [
            r"\bskip\s+(this\s+)?(for\s+)?now\b",
            r"\bcome\s+back\s+(to\s+(this|it)\s+)?later\b",
            r"\bdo\s+(this|it)\s+later\b",
            r"\bleave\s+(this|it)\s+for\s+(now|later)\b",
            r"\bwe\s+can\s+(do|address|handle)\s+(this|it)\s+later\b",
            r"\bpostpone\b",
            r"\bdefer\s+(this|it)\b",
            r"\b(bug|issue|problem|this)\s+to\s+investigate\s+later\b",
            r"\binvestigate\s+(this\s+)?(later|another\s+time)\b",
            r"\blook\s+into\s+(this\s+)?(later|another\s+time)\b",
            r"\bfix\s+(this\s+)?(later|another\s+time)\b",
            r"\baddress\s+(this\s+)?(later|another\s+time)\b",
            r"\btable\s+(this|it)\s+for\s+(now|later)\b",
            r"\bpunt\s+(on\s+)?(this|it)\b",
            r"\bshelve\s+(this|it)\b",
            r"\bbacklog\s+(this|it)\b",
        ],
    },
    "apologetic": {
        "delta": -5,
        "patterns": [
            r"\b(i'?m\s+)?sorry\b",
            r"\bmy\s+(mistake|bad|apologies|fault)\b",
            r"\bi\s+apologize\b",
            r"\bapologies\s+for\b",
        ],
    },
    "sycophancy": {
        "delta": -8,
        "patterns": [
            r"\byou'?re\s+(absolutely|totally|completely|entirely)\s+right\b",
            r"\babsolutely\s+right\b",
            r"\byou'?re\s+right,?\s+(i|my)\b",
            r"\bthat'?s\s+(absolutely|totally|completely)\s+(correct|true|right)\b",
            r"\bgreat\s+(point|observation|catch)\b",
            r"\bexcellent\s+(point|observation|catch)\b",
        ],
    },
    "filler_preamble": {
        "delta": -5,
        "patterns": [
            r"\bgreat\s+question\b",
            r"\bgood\s+question\b",
            r"\bi\s+understand\s+(your|the|what)\b",
            r"\bi'?d\s+be\s+happy\s+to\b",
            r"\bi'?ll\s+be\s+happy\s+to\b",
            r"^certainly[!.,]",
            r"^absolutely[!.,]",
            r"^of\s+course[!.,]",
            r"\blet\s+me\s+help\s+you\s+with\b",
        ],
    },
    "confirmation_theater": {
        "delta": -5,
        "patterns": [
            r"\bwould\s+you\s+like\s+me\s+to\b",
            r"\bshould\s+i\s+proceed\b",
            r"\bdo\s+you\s+want\s+me\s+to\b",
            r"\bshall\s+i\s+(start|begin|proceed|continue)\b",
            r"\bwant\s+me\s+to\s+(go\s+ahead|proceed)\b",
        ],
    },
    "announcement_theater": {
        "delta": -3,
        "patterns": [
            r"\bnow\s+i\s+will\b",
            r"\bnow\s+i'?m\s+going\s+to\b",
            r"\bi'?m\s+now\s+going\s+to\b",
            r"\blet\s+me\s+now\b",
            r"\bi'?ll\s+now\b",
            r"\bnext,?\s+i\s+will\b",
            r"\bnext,?\s+i'?ll\b",
        ],
    },
    "excessive_affirmation": {
        "delta": -3,
        "patterns": [
            r"^sure[!.,]\s",
            r"^yes[!.,]\s+i\s+(can|will)\b",
            r"\bhappy\s+to\s+help\b",
            r"\bglad\s+to\s+help\b",
            r"\bno\s+problem[!.,]",
        ],
    },
    "bikeshedding": {
        "delta": -8,
        "patterns": [
            r"\bwe\s+could\s+(call|name)\s+it\s+\w+\s+or\s+\w+\b",
            r"\b(name|call)\s+it\s+(either\s+)?\w+\s+or\s+\w+\b",
            r"\boption\s+(a|1)[:\s].*\boption\s+(b|2)\b",
            r"\bon\s+(the\s+)?one\s+hand\b.*\bon\s+the\s+other\s+hand\b",
            r"\bpros\s+and\s+cons\b.{0,50}\b(naming|style|format)",
            r"\b(tabs?\s+vs\.?\s+spaces?|spaces?\s+vs\.?\s+tabs?)\b",
            r"\b(single|double)\s+quotes?\s+vs\.?\s+(single|double)\b",
        ],
    },
    "greenfield_impulse": {
        "delta": -10,
        "patterns": [
            r"\bstart\s+(from\s+)?scratch\b",
            r"\bbuild\s+(it\s+)?fresh\b",
            r"\brewrite\s+(it\s+)?from\s+(the\s+)?ground\s+up\b",
            r"\bscrap\s+(it|this|the)\s+and\s+(start|build)\b",
            r"\bthrow\s+(it|this)\s+away\s+and\b",
            r"\bcreate\s+a\s+new\s+\w+\s+(instead|rather)\b",
            r"\bwrite\s+a\s+new\s+\w+\s+(instead|rather)\b",
            r"\bbuild\s+a\s+new\s+\w+\s+(instead|rather)\b",
        ],
    },
    "passive_deflection": {
        "delta": -8,
        "patterns": [
            r"\b(up\s+to\s+you|your\s+(choice|call|decision))\b",
            r"\blet\s+me\s+know\s+(what\s+you\s+prefer|your\s+preference)\b",
            r"\bwhatever\s+you\s+(think|prefer|want)\b",
            r"\bi'?ll\s+leave\s+(it|that)\s+(up\s+)?to\s+you\b",
            r"\bit\s+depends\b(?!\s+on\s+(the|whether))",
            r"\bthere\s+are\s+many\s+(ways|approaches|options)\b(?!\.\s+i\s+recommend)",
            r"\bi'?m\s+not\s+(sure|certain)\b(?!\s*(,\s*)?(but|so)\s+let\s+me)",
            r"\bi\s+don'?t\s+know\b(?!\s*(,\s*)?(but|so)\s+(let\s+me|i'?ll))",
            r"\byou\s+could\s+(try|do|use)\s+\w+\s+or\s+\w+\b(?!\.\s*(i\s+)?(recommend|suggest))",
            r"\beither\s+(way|option)\s+(works|is\s+fine)\b",
            r"\bboth\s+(approaches|options)\s+(are|have)\s+(valid|merit)\b",
            r"\bthat'?s\s+beyond\s+(my|the)\s+scope\b",
            r"\bi\s+can'?t\s+(help|assist)\s+with\s+that\b(?!\s+because)",
        ],
    },
    "obvious_next_steps": {
        "delta": -5,
        "patterns": [
            r"\btest\s+(?:in\s+)?(?:real\s+)?usage\b",
            r"\btest\s+the\s+(?:new\s+)?(?:patterns?|changes?|implementation)\b",
            r"\bverify\s+(?:it\s+)?works\b",
            r"\bplay\s*test\b",
            r"\btry\s+it\s+out\b",
            r"\bsee\s+how\s+it\s+(?:works|performs)\b",
            r"\btune\s+(?:the\s+)?(?:values?|deltas?|parameters?)\b",
            r"\badjust\s+(?:as\s+)?needed\b",
            r"\bmonitor\s+(?:for\s+)?(?:issues?|problems?)\b",
            r"\bwatch\s+(?:for\s+)?(?:issues?|problems?|errors?)\b",
            r"\b(?:run|do)\s+(?:the\s+)?(?:tests?|builds?)\s+(?:to\s+)?(?:verify|check|confirm)\b",
        ],
    },
    "surrender_pivot": {
        "delta": -20,
        "patterns": [
            r"\b(given|due\s+to)\s+(the\s+)?time\s+constraints?\b",
            r"\btime\s+(is\s+)?limited\b",
            r"\bfor\s+(the\s+)?sake\s+of\s+time\b",
            r"\bto\s+save\s+time\b",
            r"\bquickly\s+switch\s+to\b",
            r"\blet\s+me\s+(switch|use|try)\s+\w+\s+instead\b",
            r"\bi'?ll\s+(switch|use)\s+\w+\s+instead\b",
            r"\bswitching\s+to\s+\w+\s+(instead|which)\b",
            r"\b(is\s+)?incomplete[.,]?\s+(so\s+)?(let\s+me|i'?ll)\s+(switch|use)\b",
            r"\bdoesn'?t\s+work[.,]?\s+(so\s+)?(let\s+me|i'?ll)\s+(switch|use)\b",
            r"\bproven\s+(model|solution|approach)\s+that\s+works\b",
            r"\bout[- ]of[- ]the[- ]box\s+(solution|alternative)\b",
            r"\bworks\s+out[- ]of[- ]the[- ]box\b",
            r"\bgiven\s+(the\s+)?(issues?|problems?|difficulties?)[.,]\s+(let\s+me|i'?ll)\s+(switch|use|try)\b",
            r"\beasier\s+(to\s+)?(just\s+)?use\s+\w+\s+instead\b",
        ],
    },
}


# =============================================================================
# GOOD LANGUAGE PATTERNS
# =============================================================================

GOOD_LANGUAGE_PATTERNS = {
    "verification_intent": {
        "delta": 3,
        "patterns": [
            r"\blet\s+me\s+(just\s+)?(check|verify|confirm|validate|inspect)\b",
            r"\bi'?ll\s+(just\s+)?(check|verify|confirm|validate|inspect)\b",
            r"\blet\s+me\s+(first\s+)?(read|look\s+at|examine|review)\b",
            r"\bbefore\s+(i|we)\s+(proceed|continue|start)\b.*\b(check|verify|confirm)\b",
            r"\bfirst,?\s+(let\s+me\s+)?(check|verify|read|confirm)\b",
        ],
    },
    "evidence_gathering": {
        "delta": 2,
        "patterns": [
            r"\bto\s+understand\s+(this|the|how)\b",
            r"\bto\s+see\s+(what|how|if|whether)\b",
            r"\bto\s+confirm\s+(that|this|the|whether)\b",
            r"\bto\s+verify\s+(that|this|the|whether)\b",
        ],
    },
    "proactive_contribution": {
        "delta": 5,
        "patterns": [
            r"\bi\s+also\s+(fixed|addressed|cleaned|updated|improved|noticed\s+and\s+fixed)\b",
            r"\bwhile\s+(i\s+was\s+)?(there|at\s+it|doing\s+this),?\s+i\s+(also\s+)?(fixed|cleaned|updated)\b",
            r"\badditionally,?\s+i\s+(went\s+ahead\s+and\s+)?(fixed|addressed|cleaned|improved)\b",
            r"\bi\s+went\s+ahead\s+and\s+(also\s+)?(fixed|cleaned|ran|added)\b",
            r"\b(bonus|as\s+a\s+bonus)[:\s]+\s*i\b",
            r"\bextra[:\s]+i\s+(also\s+)?\b",
            r"\bi\s+ran\s+(the\s+)?(tests?|lints?|checks?)\s+(to\s+make\s+sure|to\s+verify|proactively)\b",
            r"\bcaught\s+(and\s+fixed|this\s+while)\b",
        ],
    },
    "debt_removal": {
        "delta": 10,
        "patterns": [
            r"\b(removed|deleted|cleaned\s+up)\s+(dead|unused|obsolete|stale)\s+(code|imports?|files?|functions?)\b",
            r"\b(removed|deleted)\s+\d+\s+(unused|dead)\b",
            r"\bpaid\s+(down|off)\s+(tech(nical)?|org(anizational)?)\s+debt\b",
            r"\b(resolved|completed|addressed|fixed)\s+(the\s+)?(TODO|FIXME|HACK)\b",
            r"\b(removed|cleared)\s+(a\s+)?(TODO|FIXME)\b",
            r"\bcleaned\s+up\s+(the\s+)?(codebase|code|file|module)\b",
            r"\brefactored\s+(away|out)\s+(the\s+)?(tech(nical)?\s+)?debt\b",
            r"\beliminated\s+(the\s+)?(tech(nical)?\s+)?debt\b",
            r"\bdeleted\s+(the\s+)?(deprecated|legacy|old)\s+(code|file|module)\b",
            r"\bremoved\s+(commented|commented-out)\s+code\b",
        ],
    },
    "assertive_stance": {
        "delta": 5,
        "patterns": [
            r"\bi\s+recommend\b",
            r"\byou\s+should\b",
            r"\bthe\s+(best|right|correct)\s+(approach|way|solution)\s+is\b",
            r"\buse\s+this\b",
            r"\bdo\s+this\b",
            r"\bhere'?s\s+(the|my)\s+(fix|solution|recommendation)\b",
            r"\bi'?ll\s+(do|handle|fix|implement)\s+(this|it|that)\b",
            r"\bdoing\s+(this|it)\s+now\b",
            r"\bfixing\s+(this|it)\s+now\b",
            r"\bthis\s+is\s+(the|a)\s+(bug|issue|problem|cause)\b",
            r"\bthe\s+(issue|problem|bug)\s+is\b",
            r"\bi\s+disagree\b",
            r"\bthat'?s\s+(incorrect|wrong|not\s+right)\b",
        ],
    },
}


# =============================================================================
# VERIFICATION CLAIMS (patterns that need tool evidence)
# =============================================================================

VERIFICATION_CLAIMS = {
    "test_claim": {
        "patterns": [
            r"\btests?\s+(are\s+)?(pass(ing|ed)?|green|succeed(ed|ing)?)\b",
            r"\ball\s+tests?\s+(pass|green)\b",
            r"\bpytest\s+(pass|succeed)\b",
            r"\bi\s+ran\s+(the\s+)?tests?\b",
        ],
        "evidence_key": "tests_run",
    },
    "lint_claim": {
        "patterns": [
            r"\blint\s+(is\s+)?(clean|pass(ing|ed)?|green)\b",
            r"\bruff\s+(check\s+)?(pass|clean|green)\b",
            r"\bno\s+(lint(ing)?|ruff)\s+(errors?|issues?|warnings?)\b",
        ],
        "evidence_key": "lint_run",
    },
    "fixed_claim": {
        "patterns": [
            r"\b(fixed|resolved|solved)\s+(it|this|the\s+(bug|issue|problem))\b",
            r"\bthat\s+(should\s+)?(fix|resolve|solve)\s+(it|this|the)\b",
            r"\b(bug|issue|problem)\s+(is\s+)?(now\s+)?(fixed|resolved|solved)\b",
        ],
        "evidence_key": "recent_write",
    },
}


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def _collect_bad_language_triggers(
    content: str, state: SessionState
) -> list[tuple[str, int]]:
    """Scan content for bad language patterns, respecting cooldowns."""
    triggered = []
    for name, config in BAD_LANGUAGE_PATTERNS.items():
        cooldown_key = f"bad_lang_{name}_turn"
        if state.turn_count - state.nudge_history.get(cooldown_key, 0) < 3:
            continue
        for pattern in config["patterns"]:
            if re.search(pattern, content, re.IGNORECASE):
                triggered.append((name, config["delta"]))
                state.nudge_history[cooldown_key] = state.turn_count
                break
    return triggered


def _get_violation_multiplier(num_violations: int) -> float:
    """Get compounding multiplier for multiple violations."""
    if num_violations >= 4:
        return 3.0
    if num_violations >= 3:
        return 2.0
    if num_violations >= 2:
        return 1.5
    return 1.0


def _has_evidence(state: SessionState, evidence_key: str) -> bool:
    """Check if evidence exists for a verification claim."""
    if evidence_key == "tests_run":
        recent = state.commands_succeeded[-5:] + state.commands_failed[-5:]
        return any(
            t in cmd
            for cmd in recent
            for t in ["pytest", "npm test", "jest", "cargo test", "go test"]
        )
    elif evidence_key == "lint_run":
        return any(
            lc in cmd
            for cmd in state.commands_succeeded[-5:]
            for lc in ["ruff check", "eslint", "clippy", "pylint"]
        )
    elif evidence_key == "recent_write":
        return len(state.files_edited) > 0
    return False


# =============================================================================
# HOOK IMPLEMENTATIONS
# =============================================================================


@register_hook("bad_language_detector", priority=46)
def check_bad_language(data: dict, state: SessionState) -> StopHookResult:
    """Detect and penalize bad language patterns in assistant output."""
    from confidence import (
        apply_rate_limit,
        format_confidence_change,
        format_dispute_instructions,
        get_tier_info,
        set_confidence,
    )

    transcript_path = data.get("transcript_path", "")
    if not transcript_path or not Path(transcript_path).exists():
        return StopHookResult.ok()

    try:
        with open(transcript_path, "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 20000))
            content = f.read().decode("utf-8", errors="ignore")
    except (OSError, PermissionError):
        return StopHookResult.ok()

    triggered = _collect_bad_language_triggers(content, state)
    if not triggered:
        return StopHookResult.ok()

    old_confidence = state.confidence
    total_delta = int(
        sum(d for _, d in triggered) * _get_violation_multiplier(len(triggered))
    )

    has_surrender = any(name == "surrender_pivot" for name, _ in triggered)
    if not has_surrender:
        total_delta = apply_rate_limit(total_delta, state)

    new_confidence = max(0, min(100, old_confidence + total_delta))
    set_confidence(state, new_confidence, "bad language detected")

    reasons = [f"{name}: {delta}" for name, delta in triggered]
    change_msg = format_confidence_change(
        old_confidence, new_confidence, ", ".join(reasons)
    )
    _, emoji, desc = get_tier_info(new_confidence)
    dispute_hint = format_dispute_instructions([n for n, _ in triggered])

    return StopHookResult.warn(
        f"📉 **Bad Language Detected**\n{change_msg}\n\n"
        f"Current: {emoji} {new_confidence}% - {desc}{dispute_hint}"
    )


@register_hook("good_language_detector", priority=47)
def check_good_language(data: dict, state: SessionState) -> StopHookResult:
    """Detect and reward verification language patterns in assistant output."""
    from confidence import (
        apply_rate_limit,
        format_confidence_change,
        get_tier_info,
        set_confidence,
    )

    transcript_path = data.get("transcript_path", "")
    if not transcript_path or not Path(transcript_path).exists():
        return StopHookResult.ok()

    try:
        with open(transcript_path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 20000))
            content = f.read().decode("utf-8", errors="ignore")
    except (OSError, PermissionError):
        return StopHookResult.ok()

    triggered = []

    for name, config in GOOD_LANGUAGE_PATTERNS.items():
        cooldown_key = f"good_lang_{name}_turn"
        last_turn = state.nudge_history.get(cooldown_key, 0)
        if state.turn_count - last_turn < 5:
            continue

        for pattern in config["patterns"]:
            if re.search(pattern, content, re.IGNORECASE):
                triggered.append((name, config["delta"]))
                state.nudge_history[cooldown_key] = state.turn_count
                break

    if not triggered:
        return StopHookResult.ok()

    old_confidence = state.confidence
    total_delta = sum(delta for _, delta in triggered)
    total_delta = apply_rate_limit(total_delta, state)
    new_confidence = max(0, min(100, old_confidence + total_delta))

    set_confidence(state, new_confidence, "verification language detected")

    reasons = [f"{name}: +{delta}" for name, delta in triggered]
    change_msg = format_confidence_change(
        old_confidence, new_confidence, ", ".join(reasons)
    )

    _, emoji, desc = get_tier_info(new_confidence)

    return StopHookResult.ok(
        f"📈 **Verification Language**\n{change_msg}\n\n"
        f"Current: {emoji} {new_confidence}% - {desc}"
    )


@register_hook("verification_theater_detector", priority=48)
def check_verification_theater(data: dict, state: SessionState) -> StopHookResult:
    """Detect verification claims without tool evidence.

    Hard Block #3: Cannot claim "fixed" without verify passing.
    - Below 70% confidence: BLOCKS (not just warns)
    - Above 70%: Warns with penalty
    """
    from confidence import apply_rate_limit, get_tier_info, set_confidence

    content = _read_tail_content(data.get("transcript_path", ""))
    if not content:
        return StopHookResult.ok()

    triggered = []
    for claim_type, config in VERIFICATION_CLAIMS.items():
        cooldown_key = f"verify_theater_{claim_type}_turn"
        if state.turn_count - state.nudge_history.get(cooldown_key, 0) < 3:
            continue
        if not any(re.search(p, content) for p in config["patterns"]):
            continue
        if not _has_evidence(state, config["evidence_key"]):
            delta = -8 if claim_type == "fixed_claim" else -15
            triggered.append((claim_type, delta))
            state.nudge_history[cooldown_key] = state.turn_count

    if not triggered:
        return StopHookResult.ok()

    total_delta = apply_rate_limit(sum(d for _, d in triggered), state)
    new_conf = max(0, min(100, state.confidence + total_delta))
    set_confidence(state, new_conf, "verification theater")
    _, emoji, desc = get_tier_info(new_conf)

    has_fixed_claim = any(ct == "fixed_claim" for ct, _ in triggered)
    if has_fixed_claim and new_conf < 70:
        claim_types = ", ".join(ct for ct, _ in triggered)
        return StopHookResult.block(
            f"🚫 **VERIFICATION THEATER BLOCKED** (Hard Block #3)\n\n"
            f"{emoji} {new_conf}% - Cannot claim 'fixed' without evidence.\n"
            f"Triggered: {claim_types}\n\n"
            f"**Required:** Run verification (test, lint, or manual check) BEFORE claiming fixed.\n"
            f"Or: 'SUDO' to bypass"
        )

    return StopHookResult.warn(
        f"📉 VERIFICATION THEATER: {emoji} {new_conf}% | Claims without evidence"
    )
