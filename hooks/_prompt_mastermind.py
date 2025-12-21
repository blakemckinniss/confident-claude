"""
Mastermind Integration Hook - Multi-model orchestration for complex tasks.

Priority 6: Runs after confidence gating, before context extraction.

Phase 0 (dark_launch): Logs routing decisions without affecting execution
Phase 1 (explicit_override_only): Only ^ prefix triggers planning
Phase 2+: Auto-planning for complex tasks
"""

import json
import sys
from pathlib import Path
from typing import Any

# Add lib to path for mastermind imports
lib_path = Path(__file__).parent.parent / "lib"
if str(lib_path) not in sys.path:
    sys.path.insert(0, str(lib_path))

# Priming packs cache
_PRIMING_PACKS: dict | None = None


def _load_priming_packs() -> dict:
    """Load task-type priming packs from config."""
    global _PRIMING_PACKS
    if _PRIMING_PACKS is not None:
        return _PRIMING_PACKS

    packs_path = Path(__file__).parent.parent / "config" / "task_priming_packs.json"
    try:
        if packs_path.exists():
            _PRIMING_PACKS = json.loads(packs_path.read_text())
        else:
            _PRIMING_PACKS = {}
    except Exception:
        _PRIMING_PACKS = {}
    return _PRIMING_PACKS


def _format_priming_pack(task_type: str) -> str | None:
    """Format priming pack for injection based on task type."""
    packs = _load_priming_packs()
    pack = packs.get(task_type, packs.get("general", {}))

    if not pack or not pack.get("constraints"):
        return None

    parts = []
    if pack.get("header"):
        parts.append(pack["header"])

    if pack.get("constraints"):
        parts.append("**Do:**")
        for constraint in pack["constraints"]:
            parts.append(f"- {constraint}")

    if pack.get("anti_patterns"):
        parts.append("**Don't:**")
        for anti in pack["anti_patterns"]:
            parts.append(f"- {anti}")

    return "\n".join(parts) if parts else None


# Hint catalog cache
_HINT_CATALOG: dict | None = None


def _load_hint_catalog() -> dict:
    """Load action hint catalog from config."""
    global _HINT_CATALOG
    if _HINT_CATALOG is not None:
        return _HINT_CATALOG

    catalog_path = Path(__file__).parent.parent / "config" / "hint_catalog.json"
    try:
        if catalog_path.exists():
            _HINT_CATALOG = json.loads(catalog_path.read_text())
        else:
            _HINT_CATALOG = {}
    except Exception:
        _HINT_CATALOG = {}
    return _HINT_CATALOG


def _format_action_hints(action_hints: list | None) -> str | None:
    """Expand and format action hints from IDs."""
    if not action_hints:
        return None

    catalog = _load_hint_catalog()
    hints_data = catalog.get("action_hints", {})

    parts = []
    for hint in action_hints:
        hint_id = hint.id if hasattr(hint, "id") else hint.get("id", "")
        priority = (
            hint.priority if hasattr(hint, "priority") else hint.get("priority", "p1")
        )

        if hint_id in hints_data:
            h = hints_data[hint_id]
            icon = h.get("icon", "💡")
            message = h.get("message", hint_id)
            kind = h.get("kind", "do")

            # Priority indicator
            pri_icon = "🔴" if priority == "p0" else "🟡" if priority == "p1" else "🔵"

            if kind == "caution":
                parts.append(f"{pri_icon} ⚠️ {message}")
            else:
                parts.append(f"{pri_icon} {icon} {message}")

    if not parts:
        return None

    return "**Action Hints:**\n" + "\n".join(parts)


def _format_recommended_capabilities(recommended) -> str | None:
    """Format capability recommendations by category."""
    if not recommended:
        return None

    parts = []

    # Skills
    skills = (
        recommended.skills
        if hasattr(recommended, "skills")
        else recommended.get("skills")
    )
    if skills:
        parts.append(f"🎯 **Skills:** {', '.join(skills)}")

    # Agents
    agents = (
        recommended.agents
        if hasattr(recommended, "agents")
        else recommended.get("agents")
    )
    if agents:
        parts.append(f"🤖 **Agents:** {', '.join(agents)}")

    # MCP Tools
    mcp = (
        recommended.mcp_tools
        if hasattr(recommended, "mcp_tools")
        else recommended.get("mcp_tools")
    )
    if mcp:
        parts.append(f"🔧 **MCP Tools:** {', '.join(mcp)}")

    # Ops Scripts
    ops = (
        recommended.ops_scripts
        if hasattr(recommended, "ops_scripts")
        else recommended.get("ops_scripts")
    )
    if ops:
        parts.append(f"📜 **Ops Scripts:** {', '.join(ops)}")

    if not parts:
        return None

    return "**Recommended Capabilities:**\n" + "\n".join(parts)


def _format_intent_clarification(intent) -> str | None:
    """Format intent clarification (prompt enhancement) for context injection.

    This helps Claude understand vague/ambiguous prompts by surfacing:
    - The inferred goal (what success looks like)
    - The inferred scope (what's in/out)
    - Unstated constraints (implicit assumptions)
    - Whether ambiguity exists (should confirm with user)
    """
    if not intent:
        return None

    # Extract fields (handle both object and dict)
    goal = (
        intent.inferred_goal
        if hasattr(intent, "inferred_goal")
        else intent.get("inferred_goal")
    )
    scope = (
        intent.inferred_scope
        if hasattr(intent, "inferred_scope")
        else intent.get("inferred_scope")
    )
    constraints = (
        intent.unstated_constraints
        if hasattr(intent, "unstated_constraints")
        else intent.get("unstated_constraints")
    )
    ambiguous = (
        intent.ambiguity_detected
        if hasattr(intent, "ambiguity_detected")
        else intent.get("ambiguity_detected", False)
    )
    confidence = (
        intent.clarification_confidence
        if hasattr(intent, "clarification_confidence")
        else intent.get("clarification_confidence", 0.0)
    )

    # Only format if there's meaningful content
    if not goal and not scope and not constraints and not ambiguous:
        return None

    parts = []

    # Confidence indicator
    conf_pct = f"{confidence:.0%}" if confidence else "?"

    if goal:
        parts.append(f"**Goal:** {goal}")
    if scope:
        parts.append(f"**Scope:** {scope}")
    if constraints:
        constraints_str = ", ".join(constraints[:3])
        parts.append(f"**Implicit constraints:** {constraints_str}")

    # Semantic pointers - only show when confidence >= 0.7 to avoid noise
    # Low confidence pointers are often generic guesses that don't help
    if confidence >= 0.7:
        likely = (
            intent.likely_relevant
            if hasattr(intent, "likely_relevant")
            else intent.get("likely_relevant")
        )
        concepts = (
            intent.related_concepts
            if hasattr(intent, "related_concepts")
            else intent.get("related_concepts")
        )
        prior = (
            intent.prior_art
            if hasattr(intent, "prior_art")
            else intent.get("prior_art")
        )

        if likely:
            likely_str = ", ".join(f"`{f}`" for f in likely[:3])
            parts.append(f"**Likely relevant:** {likely_str}")
        if concepts:
            concepts_str = ", ".join(concepts[:3])
            parts.append(f"**Related:** {concepts_str}")
        if prior:
            parts.append(f"**Prior art:** {prior}")

    if not parts:
        return None

    # Header with confidence and optional ambiguity warning
    header = f"📋 **Router Interpretation** (confidence: {conf_pct}):"
    if ambiguous:
        header += "\n⚠️ **Ambiguity detected** - consider confirming scope with user"

    return header + "\n" + "\n".join(f"  {p}" for p in parts)


# ============================================================================
# SKILL AUTO-INJECTION
# ============================================================================

# Skill content cache: {skill_name: content}
_SKILL_CACHE: dict[str, str] = {}

# Skill cooldowns: {skill_name: last_turn_injected}
_SKILL_COOLDOWNS: dict[str, int] = {}

# Behavioral state tracking for pattern detection
_BEHAVIORAL_STATE: dict[str, Any] = {
    "recent_edits": [],  # [(file, turn), ...]
    "recent_failures": 0,
    "last_research_turn": -999,
}

# Confidence zone thresholds for graduated injection
_CONFIDENCE_ZONES = {
    "IGNORANCE": (0, 30),
    "HYPOTHESIS": (31, 50),
    "WORKING": (51, 70),
    "CERTAINTY": (71, 85),
    "TRUSTED": (86, 100),
}

# Enhanced skill trigger definitions with behavioral detection
_SKILL_TRIGGERS = {
    "fix": {
        # Widened keywords - more semantic patterns
        "keywords": [
            "fix",
            "broken",
            "not working",
            "failing",
            "error",
            "bug",
            "issue",
            "problem",
            "doesn't work",
            "won't",
            "can't",
            "unexpected",
            "wrong",
            "incorrect",
            "crash",
            "exception",
        ],
        "task_types": ["debugging", "bugfix"],
        "priority": 3,
        "cooldown": 3,  # Reduced from 5 - more proactive
        # Behavioral: inject when recent failures detected
        "on_failures": 2,
    },
    "commit": {
        "keywords": [
            "commit",
            "save changes",
            "checkpoint",
            "git commit",
            "ready to commit",
            "done with",
            "finished",
            "complete",
            "push",
            "merge",
        ],
        "task_types": [],
        "priority": 2,
        "cooldown": 3,
    },
    "stuck": {
        # Graduated confidence triggers by zone
        "confidence_zones": ["IGNORANCE", "HYPOTHESIS", "WORKING"],  # <71%
        "task_types": ["debugging", "bugfix", "general"],
        "keywords": [
            "stuck",
            "not sure",
            "tried everything",
            "doesn't make sense",
            "why",
            "confused",
            "help",
            "lost",
        ],
        "priority": 1,  # Highest - circuit breaker
        "cooldown": 5,  # Reduced from 8
        # Behavioral: inject on edit oscillation
        "on_edit_oscillation": 3,  # Same file edited 3+ times
        "on_failures": 3,
    },
    "careful": {
        "path_patterns": [
            "auth",
            "payment",
            "billing",
            "secret",
            "config",
            "env",
            "jwt",
            "oauth",
            "session",
            "token",
            "credential",
            "password",
            "migration",
            "database",
            "schema",
            "deploy",
            "production",
            ".claude/ops",
            ".claude/hooks",
            ".claude/lib",  # Framework paths
        ],
        "keywords": ["sensitive", "critical", "important", "careful"],
        "task_types": [],
        "priority": 1,
        "cooldown": 8,  # Reduced from 10
        # Behavioral: inject when editing framework files
        "on_framework_edit": True,
    },
    "context": {
        "keywords": [
            "context",
            "orientation",
            "what is this",
            "project structure",
            "where",
            "find",
            "locate",
            "understand",
            "overview",
            "codebase",
        ],
        "session_start": True,
        "task_types": [],
        "priority": 4,
        "cooldown": 15,  # Reduced from 20
        # Proactive: inject on confidence zone drop
        "on_zone_change": True,
    },
    "new-feature": {
        "keywords": [
            "new feature",
            "scaffold",
            "create feature",
            "add feature",
            "implement",
            "build",
            "create",
            "add",
            "new component",
            "new module",
            "new file",
        ],
        "task_types": ["planning", "feature", "architecture"],
        "priority": 3,
        "cooldown": 8,  # Reduced from 10
    },
}


def _load_skill_content(skill_name: str) -> str | None:
    """Load skill content from SKILL.md file, with caching."""
    if skill_name in _SKILL_CACHE:
        return _SKILL_CACHE[skill_name]

    skill_path = Path.home() / ".claude" / "skills" / skill_name / "SKILL.md"
    try:
        if skill_path.exists():
            content = skill_path.read_text()
            # Strip YAML frontmatter
            if content.startswith("---"):
                parts = content.split("---", 2)
                if len(parts) >= 3:
                    content = parts[2].strip()
            _SKILL_CACHE[skill_name] = content
            return content
    except Exception:
        pass
    return None


def _get_confidence_zone(confidence: int) -> str:
    """Get the confidence zone name for a given confidence level."""
    for zone_name, (low, high) in _CONFIDENCE_ZONES.items():
        if low <= confidence <= high:
            return zone_name
    return "TRUSTED"


def _detect_edit_oscillation(state: Any, threshold: int = 3) -> str | None:
    """Detect if same file has been edited multiple times recently."""
    if state is None:
        return None
    # Check edit counts from session state
    edit_counts = getattr(state, "_file_edit_counts", {})
    for filepath, count in edit_counts.items():
        if count >= threshold:
            return filepath
    return None


def _get_triggered_skills(
    prompt: str,
    task_type: str,
    confidence: int,
    turn_count: int,
    is_session_start: bool = False,
    state: Any = None,
) -> list[tuple[str, str]]:
    """
    Determine which skills should be auto-injected.

    Enhanced with:
    - Widened keyword triggers
    - Confidence zone-based triggering
    - Behavioral pattern detection (edit oscillation, failures)
    - Proactive task-type matching

    Returns list of (skill_name, content) tuples, ordered by priority.
    Max 2 skills per turn to avoid context bloat.
    """
    triggered = []
    prompt_lower = prompt.lower()
    current_zone = _get_confidence_zone(confidence)

    for skill_name, config in _SKILL_TRIGGERS.items():
        # Check cooldown
        last_turn = _SKILL_COOLDOWNS.get(skill_name, -999)
        cooldown = config.get("cooldown", 5)
        if turn_count - last_turn < cooldown:
            continue

        should_trigger = False
        trigger_reason = ""

        # 1. Session start trigger
        if config.get("session_start") and is_session_start:
            should_trigger = True
            trigger_reason = "session_start"

        # 2. Confidence zone triggers (graduated by zone)
        if not should_trigger and config.get("confidence_zones"):
            if current_zone in config["confidence_zones"]:
                # Check task type if specified
                task_types = config.get("task_types", [])
                if not task_types or task_type in task_types:
                    should_trigger = True
                    trigger_reason = f"confidence_zone:{current_zone}"

        # 3. Keywords (widened)
        if not should_trigger:
            for keyword in config.get("keywords", []):
                if keyword in prompt_lower:
                    should_trigger = True
                    trigger_reason = f"keyword:{keyword}"
                    break

        # 4. Task type match (more proactive - always triggers for matching types)
        if not should_trigger and config.get("task_types"):
            if task_type in config["task_types"]:
                should_trigger = True
                trigger_reason = f"task_type:{task_type}"

        # 5. Path patterns in prompt
        if not should_trigger:
            for pattern in config.get("path_patterns", []):
                if pattern in prompt_lower:
                    should_trigger = True
                    trigger_reason = f"path_pattern:{pattern}"
                    break

        # 6. Behavioral: Edit oscillation detection
        if not should_trigger and config.get("on_edit_oscillation"):
            threshold = config["on_edit_oscillation"]
            oscillating_file = _detect_edit_oscillation(state, threshold)
            if oscillating_file:
                should_trigger = True
                trigger_reason = f"edit_oscillation:{oscillating_file}"

        # 7. Behavioral: Framework file editing
        if not should_trigger and config.get("on_framework_edit"):
            framework_patterns = [".claude/ops", ".claude/hooks", ".claude/lib"]
            for pattern in framework_patterns:
                if pattern in prompt_lower:
                    should_trigger = True
                    trigger_reason = f"framework_edit:{pattern}"
                    break

        if should_trigger:
            content = _load_skill_content(skill_name)
            if content:
                priority = config.get("priority", 5)
                triggered.append((priority, skill_name, content, trigger_reason))

    # Sort by priority (lower = higher priority) and take top 2
    triggered.sort(key=lambda x: x[0])
    result = []
    for item in triggered[:2]:
        priority, skill_name, content = item[0], item[1], item[2]
        trigger_reason = item[3] if len(item) > 3 else ""
        _SKILL_COOLDOWNS[skill_name] = turn_count
        result.append((skill_name, content, trigger_reason))

    return result


def _format_skill_injection(skills: list[tuple[str, str, str]]) -> str | None:
    """Format triggered skills for context injection."""
    if not skills:
        return None

    parts = [
        "📚 **Auto-Injected Skills** (triggered by behavioral/contextual signals):"
    ]
    for item in skills:
        skill_name = item[0]
        content = item[1]
        trigger_reason = item[2] if len(item) > 2 else ""

        # Truncate content to avoid bloat (first 1500 chars)
        truncated = content[:1500]
        if len(content) > 1500:
            truncated += f"\n\n*[Truncated - invoke `/{skill_name}` for full]*"

        trigger_note = f" *(triggered: {trigger_reason})*" if trigger_reason else ""
        parts.append(f"\n### /{skill_name}{trigger_note}\n{truncated}")

    return "\n".join(parts)


def _get_current_session_id(data: dict) -> str | None:
    """Get current Claude session ID from hook input data.

    Claude Code passes session_id in the JSON stdin data, not as an
    environment variable. This is the ACTUAL current session.
    """
    return data.get("session_id")


from _prompt_registry import register_hook, HookResult  # noqa: E402

try:
    from mastermind import process_user_prompt, load_config

    MASTERMIND_AVAILABLE = True
except ImportError as e:
    MASTERMIND_AVAILABLE = False
    MASTERMIND_ERROR = str(e)


@register_hook("mastermind_orchestrator", priority=6)
def mastermind_orchestrator(data: dict, state) -> HookResult:
    """
    Orchestrate multi-model routing and planning.

    Returns context with routing info and optional blueprint instructions.
    Never denies - only augments context.
    """
    if not MASTERMIND_AVAILABLE:
        # Silently skip if mastermind module not available
        return HookResult(decision="allow", context=None)

    try:
        config = load_config()

        # Get ACTUAL current session ID from hook input data
        # This ensures mastermind detects new sessions correctly
        current_session_id = _get_current_session_id(data)

        # Check if system is enabled at all
        if config.rollout_phase == 0:
            # Dark launch - run but don't inject context
            # Still logs telemetry for validation
            prompt = data.get("prompt", "")
            if prompt:
                process_user_prompt(
                    prompt=prompt,
                    turn_count=getattr(state, "turn_count", 0),
                    session_id=current_session_id,
                )
                # Log but don't inject
                return HookResult(decision="allow", context=None)
            return HookResult(decision="allow", context=None)

        # Phase 1+: Active orchestration
        prompt = data.get("prompt", "")
        if not prompt:
            return HookResult(decision="allow", context=None)

        result = process_user_prompt(
            prompt=prompt,
            turn_count=getattr(state, "turn_count", 0),
            session_id=current_session_id,
            confidence=getattr(state, "confidence", 70),
        )

        # Build context from result
        context_parts = []

        # Get routing info
        routing = result.get("routing_info", {})

        # STATE COORDINATION: Set flags for downstream hooks (pal_mandate, etc.)
        # This prevents duplicate PAL recommendations
        if routing:
            state.set("mastermind_routed", True)
            state.set("mastermind_classification", routing.get("classification", "unknown"))
            suggested_tool = routing.get("suggested_tool")
            if suggested_tool:
                state.set("mastermind_pal_suggested", suggested_tool)
            if routing.get("pal_suggestion") or routing.get("inject_context"):
                state.set("mastermind_pal_injected", True)

        # PRIORITY: Check for PAL mandate injection (^ override)
        # This MUST be injected for the pre_tool_use block to make sense
        inject_context = routing.get("inject_context") or result.get("inject_context")
        if inject_context:
            # PAL mandate or other injected context takes priority
            context_parts.append(inject_context)

        # Add routing classification info
        if routing and not inject_context:  # Skip if mandate already shown
            classification = routing.get("classification", "unknown")
            confidence = routing.get("confidence", 0)
            if classification != "unknown":
                context_parts.append(
                    f"🎯 **Mastermind**: Task classified as `{classification}` "
                    f"(confidence: {confidence:.0%})"
                )

        # Inject task-type priming pack (behavioral constraints)
        task_type = routing.get("task_type", "general") if routing else "general"
        priming_pack = _format_priming_pack(task_type)
        if priming_pack:
            context_parts.append(priming_pack)

        # Inject auto-triggered skills based on context
        turn_count = getattr(state, "turn_count", 0)
        confidence_level = getattr(state, "confidence", 70)
        is_session_start = turn_count <= 1
        triggered_skills = _get_triggered_skills(
            prompt=prompt,
            task_type=task_type,
            confidence=confidence_level,
            turn_count=turn_count,
            is_session_start=is_session_start,
            state=state,
        )
        skill_injection = _format_skill_injection(triggered_skills)
        if skill_injection:
            context_parts.append(skill_injection)

        # Inject action hints (prescriptive recommendations)
        action_hints = routing.get("action_hints") if routing else None
        hints_formatted = _format_action_hints(action_hints)
        if hints_formatted:
            context_parts.append(hints_formatted)

        # Inject recommended capabilities (toolbox for this task)
        recommended = routing.get("recommended") if routing else None
        caps_formatted = _format_recommended_capabilities(recommended)
        if caps_formatted:
            context_parts.append(caps_formatted)

        # Inject intent clarification (prompt enhancement)
        intent = routing.get("intent") if routing else None
        intent_formatted = _format_intent_clarification(intent)
        if intent_formatted:
            context_parts.append(intent_formatted)

        # Add research recommendation if needed
        needs_research = routing.get("needs_research", False) if routing else False
        research_topics = routing.get("research_topics", []) if routing else []
        if needs_research and research_topics:
            # Build structured research directive with exact tool calls
            search_calls = "\n".join(
                f'- `mcp__crawl4ai__ddg_search` query="{topic}"'
                for topic in research_topics[:3]
            )
            context_parts.append(
                f"🔍 **Research First**: Current docs/APIs may be needed for accuracy.\n\n"
                f"**Run these searches before proceeding:**\n{search_calls}\n\n"
                f"**Then:** Summarize top 2-3 findings and include in your PAL tool prompt."
            )

        # Add blueprint if generated
        blueprint = result.get("blueprint")
        if blueprint:
            context_parts.append(
                f"📋 **Blueprint Available**: {blueprint.get('summary', 'See executor instructions')}"
            )

        # Add executor instructions if present
        instructions = result.get("executor_instructions")
        if instructions:
            context_parts.append(f"\n{instructions}")

        context = "\n".join(context_parts) if context_parts else None
        return HookResult(decision="allow", context=context)

    except Exception as e:
        # Never block on mastermind errors - fail silently
        print(f"[mastermind] Error: {e}", file=sys.stderr)
        return HookResult(decision="allow", context=None)


@register_hook("mastermind_drift_check", priority=65)
def mastermind_drift_check(data: dict, state) -> HookResult:
    """
    Check for drift from blueprint and warn if escalation needed.

    Priority 65: Runs after context injection, before suggestions.
    Only active when drift detection is enabled and blueprint exists.
    """
    if not MASTERMIND_AVAILABLE:
        return HookResult(decision="allow", context=None)

    try:
        config = load_config()
        if not config.drift.enabled:
            return HookResult(decision="allow", context=None)

        # Import drift check from hooks state module
        from _hooks_state import check_mastermind_drift

        drift_warning = check_mastermind_drift(state)
        if drift_warning:
            return HookResult(decision="allow", context=drift_warning)

        return HookResult(decision="allow", context=None)

    except Exception as e:
        print(f"[mastermind-drift] Error: {e}", file=sys.stderr)
        return HookResult(decision="allow", context=None)
