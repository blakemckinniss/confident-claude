"""Hook integration for mastermind in UserPromptSubmit.

Wires mastermind components into the hook lifecycle:
1. Turn 0-1: Route and optionally plan
2. Turn 2+: Monitor for drift
3. Inject executor instructions when blueprint exists
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

from .config import get_config, PAL_MANDATE_LOCK_PATH
from .state import MastermindState, RoutingDecision, load_state, save_state
from .context_packer import pack_for_router, has_in_progress_bead
from .routing import parse_user_override, make_routing_decision
from .router_groq import (
    call_groq_router,
    apply_risk_lexicon,
    RecommendedCapabilities,
    DiscoveryAids,
)
from .redaction import redact_text
from .drift import evaluate_drift, should_escalate
from .executor_instructions import (
    generate_executor_instructions,
    should_inject_instructions,
)
from .telemetry import log_router_decision, log_escalation
from .variance import generate_variance_report, format_variance_for_user
from .router_gpt import build_routing_prompt, load_capabilities_index


def get_session_id() -> str:
    """Get current session ID from environment or generate one.

    Always truncates to 16 chars for consistency across the codebase.
    """
    session_id = os.environ.get("CLAUDE_SESSION_ID", f"session_{int(time.time())}")
    return session_id[:16] if session_id else ""


# =============================================================================
# PAL MCP CONSULTATION - HYBRID APPROACH
# =============================================================================
# Groq suggests a tool, Claude can choose any PAL tool, but MUST use one.
# Enforcement happens at completion gate if no PAL tool was used.
# =============================================================================

# Brief models summary for PAL auto-selection context
# Derived from PAL MCP's openrouter_models.json - update if models change significantly
PAL_MODELS_SUMMARY = """| Model | Score | Context | Best For |
|-------|-------|---------|----------|
| gpt-5.2 | 100 | 400K | Reasoning, code-gen, complex planning |
| gemini-3-pro | 100 | 1M | Large context, multimodal, code-gen |
| kimi-k2 | 94 | 256K | Long-horizon reasoning, coding |
| gemini-3-flash | 91 | 1M | Fast reasoning, large context |
| claude-haiku-4.5 | 68 | 200K | Efficient, quick tasks |"""


# Tool descriptions for the suggestion template
PAL_TOOL_DESCRIPTIONS = {
    "debug": "mcp__pal__debug - Deep debugging analysis, root cause investigation",
    "planner": "mcp__pal__planner - Strategic planning for multi-step implementations",
    "codereview": "mcp__pal__codereview - Code quality, security, and architecture review",
    "consensus": "mcp__pal__consensus - Multi-model consultation for architecture decisions",
    "apilookup": "mcp__pal__apilookup - API documentation and library usage research",
    "precommit": "mcp__pal__precommit - Pre-commit validation and change verification",
    "chat": "mcp__pal__chat - General discussion and brainstorming",
    "thinkdeep": "mcp__pal__thinkdeep - Complex problem decomposition",
    "clink": "mcp__pal__clink - Spawn isolated CLI subagent (Gemini 1M context) for heavy analysis",
    "clink_codex": "mcp__pal__clink(cli_name='codex') - Codex CLI for code generation with GPT-5.1-codex-max",
}

# Alternatives mapping for each tool type
PAL_TOOL_ALTERNATIVES = {
    "debug": ["thinkdeep", "chat", "clink", "clink_codex"],
    "planner": ["chat", "thinkdeep", "clink_codex"],
    "codereview": ["precommit", "chat", "clink", "clink_codex"],
    "consensus": ["planner", "chat", "clink"],
    "apilookup": ["chat", "clink"],
    "precommit": ["codereview", "chat"],
    "chat": ["thinkdeep", "clink", "clink_codex"],
    "thinkdeep": ["debug", "chat", "clink", "clink_codex"],
    "clink": ["chat", "thinkdeep", "clink_codex"],  # Gemini CLI - codex is alternative
    "clink_codex": ["chat", "clink", "thinkdeep"],  # Codex CLI - gemini is alternative
}

PAL_SUGGESTION_TEMPLATE = """
# PAL MCP Consultation Suggested

{trigger_reason}

## Suggested Tool: `{suggested_tool_full}`

{tool_description}

**Task type detected:** {task_type}

## Alternative Options

If the suggested tool doesn't fit your assessment, you may use any of these instead:
{alternatives_list}

## Requirements

1. **Use ONE PAL MCP tool** before completing this task (any from the list above)
2. **Model:** PAL auto-selects the best model, or specify one if task warrants it
3. **You choose** which tool best fits the actual task context

## Available Models (auto-selected by default)
{models_summary}

## Available PAL Tools

| Tool | Best For |
|------|----------|
| `debug` | Bug investigation, error tracing |
| `planner` | Implementation planning, multi-step work |
| `codereview` | Code quality, refactoring assessment |
| `consensus` | Architecture decisions, technology choices |
| `apilookup` | API docs, library research |
| `precommit` | Change validation, pre-commit checks |
| `chat` | General discussion, brainstorming |
| `thinkdeep` | Complex problem decomposition |
| `clink` | Heavy codebase analysis, isolated subagent (Gemini 1M context) |
| `clink(codex)` | Code generation, implementation (Codex GPT-5.1-codex-max) |

## User's Request

{user_prompt}

---

**Proceed with the PAL tool that best fits this task.**
"""

# Capability-aware routing template (PAL auto-selects model)
CAPABILITY_ROUTING_TEMPLATE = """
# Intelligent Capability Routing

{trigger_reason}

## Routing Request

For optimal tool selection, call `mcp__pal__chat` with the following prompt:

<routing_prompt>
{routing_prompt}
</routing_prompt>

**Model:** PAL auto-selects (or specify: gpt-5.2, gemini-3-pro, kimi-k2 for reasoning-heavy tasks)

The response will contain a staged toolchain recommendation with:
- Primary tool for each stage
- Rationale for selections
- Fallback alternatives

## Quick Reference

| Stage | Purpose |
|-------|---------|
| triage | Classify and assess |
| locate | Find relevant code |
| analyze | Investigate root cause |
| modify | Apply changes |
| validate | Verify results |
| report | Summarize findings |

## User's Request

{user_prompt}

---

**Call `mcp__pal__chat` with the routing prompt above, then follow the recommended toolchain.**
"""

# Hard mandate template for ^ override (user explicitly wants planner)
PLANNER_MANDATE_TEMPLATE = """
# 🚨 MANDATORY: PAL MCP PLANNER REQUIRED 🚨

**User explicitly requested strategic planning via `^` prefix.**

You MUST call `mcp__pal__planner` BEFORE doing ANY other work.

**Model:** PAL auto-selects (prefer gpt-5.2 or gemini-3-pro for complex planning)

## User's Request

{user_prompt}

---

**NOW: Call `mcp__pal__planner` IMMEDIATELY.**
"""


def generate_pal_suggestion(
    prompt: str,
    state: MastermindState,
    task_type: str = "general",
    suggested_tool: str = "chat",
    use_capability_routing: bool = True,
    *,
    classification: str = "medium",
    groq_confidence: float = 0.0,
    reason_codes: list[str] | None = None,
    needs_research: bool = False,
    research_topics: list[str] | None = None,
    recommended: RecommendedCapabilities | None = None,
    discovery: DiscoveryAids | None = None,
) -> str:
    """Generate PAL MCP tool suggestion (hybrid approach).

    Suggests a tool based on Groq classification but allows Claude
    to choose any PAL tool. Enforcement happens at completion gate.

    When capability routing is enabled and the capabilities index exists,
    generates a routing prompt for GPT-5.2 to recommend a staged toolchain.

    Args:
        prompt: User's original prompt
        state: Current mastermind session state
        task_type: Detected task type from Groq
        suggested_tool: Suggested PAL tool from Groq
        use_capability_routing: Whether to use capability-aware routing
        classification: Groq's complexity classification (trivial/medium/complex)
        groq_confidence: Groq's confidence in classification (0-1)
        reason_codes: Groq's reason codes explaining classification
        needs_research: Whether Groq detected research is needed
        research_topics: Specific topics to research if needed
    """
    # Build continuation hint if available for suggested tool
    continuation_hint = ""
    if cont_id := state.get_pal_continuation(suggested_tool):
        continuation_hint = f'\n\n📎 **Resume PAL context**: `continuation_id="{cont_id}"` available for `mcp__pal__{suggested_tool}`'
    elif state.pal_continuations:
        # Show other available continuations
        available = [f"{k}" for k in state.pal_continuations.keys()]
        if available:
            continuation_hint = (
                f"\n\n📎 **PAL continuations available**: {', '.join(available)}"
            )

    # Build Groq analysis summary - maximize value from classification
    groq_summary_parts = []
    if reason_codes:
        codes_str = ", ".join(reason_codes[:5])  # Limit to 5 for brevity
        groq_summary_parts.append(f"**Signals**: {codes_str}")
    if groq_confidence > 0:
        conf_pct = f"{groq_confidence:.0%}"
        groq_summary_parts.append(f"**Groq confidence**: {conf_pct}")

    groq_summary = ""
    if groq_summary_parts:
        groq_summary = (
            f"\n\n## Groq Classification Summary\n"
            f"- **Type**: {task_type} | **Complexity**: {classification}\n"
            f"- {' | '.join(groq_summary_parts)}\n"
        )

    # Build research directive if Groq detected need
    research_directive = ""
    if needs_research and research_topics:
        topics_list = "\n".join(f"  - `{topic}`" for topic in research_topics[:4])
        research_directive = (
            f"\n\n## 🔍 Research Required (Groq-detected)\n\n"
            f"Before calling PAL, gather current information on:\n{topics_list}\n\n"
            f"**Suggested approach**:\n"
            f"1. `mcp__crawl4ai__ddg_search` for each topic\n"
            f"2. Include top findings in your PAL prompt\n"
            f"3. This ensures PAL has current context, not stale training data\n"
        )

    # Build task-specific recommendations section (from Groq)
    recommendations_section = ""
    if recommended:
        rec_parts = []
        if recommended.agents:
            agents_str = ", ".join(f"`{a}`" for a in recommended.agents[:3])
            rec_parts.append(f"**Agents**: {agents_str}")
        if recommended.skills:
            skills_str = ", ".join(f"`/{s}`" for s in recommended.skills[:3])
            rec_parts.append(f"**Skills**: {skills_str}")
        if recommended.mcp_tools:
            tools_str = ", ".join(f"`{t}`" for t in recommended.mcp_tools[:3])
            rec_parts.append(f"**MCP Tools**: {tools_str}")
        if recommended.ops_scripts:
            ops_str = ", ".join(f"`{o}`" for o in recommended.ops_scripts[:2])
            rec_parts.append(f"**Ops**: {ops_str}")
        if rec_parts:
            recommendations_section = (
                "\n\n## 🎯 Recommended for This Task (Groq-selected)\n\n"
                + "\n".join(f"- {p}" for p in rec_parts)
                + "\n"
            )

    # Build discovery aids section (always populated by Groq)
    discovery_section = ""
    if discovery:
        disc_parts = []
        if discovery.research_suggestions:
            topics = "\n".join(f"  - {t}" for t in discovery.research_suggestions[:3])
            disc_parts.append(f"**📚 Research Topics**:\n{topics}")
        if discovery.tools_suggested:
            tools = ", ".join(f"`{t}`" for t in discovery.tools_suggested[:3])
            disc_parts.append(f"**🛠️ Useful Tools**: {tools}")
        if discovery.discovery_questions:
            questions = "\n".join(f"  - {q}" for q in discovery.discovery_questions[:3])
            disc_parts.append(f"**🤔 Discovery Questions**:\n{questions}")
        if disc_parts:
            discovery_section = (
                "\n\n## 💡 Discovery Aids (Groq-generated)\n\n"
                + "\n\n".join(disc_parts)
                + "\n"
            )

    # Try capability-aware routing first
    if use_capability_routing:
        index = load_capabilities_index()
        if index.get("capabilities"):
            routing_prompt = build_routing_prompt(prompt, task_type)
            trigger_reason = (
                f"Groq classified this as a **{task_type}** task. "
                f"Using intelligent routing with {len(index['capabilities'])} capabilities."
            )
            result = CAPABILITY_ROUTING_TEMPLATE.format(
                trigger_reason=trigger_reason,
                routing_prompt=routing_prompt,
                user_prompt=prompt,
            )
            # Prepend research (do first), add recommendations + discovery, append Groq summary + continuation
            return (
                research_directive
                + recommendations_section
                + discovery_section
                + result
                + groq_summary
                + continuation_hint
            )

    # Fall back to simple PAL tool suggestion
    tool_description = PAL_TOOL_DESCRIPTIONS.get(
        suggested_tool, PAL_TOOL_DESCRIPTIONS["chat"]
    )
    suggested_tool_full = f"mcp__pal__{suggested_tool}"

    alternatives = PAL_TOOL_ALTERNATIVES.get(suggested_tool, ["chat"])
    alternatives_list = "\n".join(
        f"- `mcp__pal__{alt}`: {PAL_TOOL_DESCRIPTIONS.get(alt, 'General purpose')}"
        for alt in alternatives
    )

    trigger_reason = f"Groq classified this as a **{task_type}** task requiring external consultation."

    result = PAL_SUGGESTION_TEMPLATE.format(
        trigger_reason=trigger_reason,
        suggested_tool_full=suggested_tool_full,
        tool_description=tool_description,
        task_type=task_type,
        alternatives_list=alternatives_list,
        models_summary=PAL_MODELS_SUMMARY,
        user_prompt=prompt,
    )
    # Prepend research (do first), add discovery, append Groq summary + continuation
    return (
        research_directive
        + discovery_section
        + result
        + groq_summary
        + continuation_hint
    )


def generate_planner_mandate(
    prompt: str, state: MastermindState, user_forced: bool = False
) -> str:
    """Generate mandatory PAL planner directive (for ^ override only).

    Args:
        prompt: User's original prompt
        state: Current mastermind session state
        user_forced: Should always be True (mandate only for explicit request)
    """
    return PLANNER_MANDATE_TEMPLATE.format(user_prompt=prompt)


# =============================================================================
# PAL MANDATE LOCK FILE - Hard enforcement via pre_tool_use hook
# Lock path defined in config.py (single source of truth)
# =============================================================================


def create_pal_mandate_lock(
    session_id: str,
    project: str,
    prompt: str,
) -> Path:
    """Create lock file that blocks all tools until PAL planner is called.

    The pre_tool_use hook checks this lock and HARD BLOCKS everything
    except mcp__pal__planner with GPT-5.x model.
    """
    import json

    lock_data = {
        "session_id": session_id,
        "project": project,
        "prompt": prompt[:500],  # Truncate for readability
        "created_at": time.time(),
        "created_at_iso": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }

    PAL_MANDATE_LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    PAL_MANDATE_LOCK_PATH.write_text(json.dumps(lock_data, indent=2))

    return PAL_MANDATE_LOCK_PATH


def clear_pal_mandate_lock() -> bool:
    """Clear the PAL mandate lock file."""
    if PAL_MANDATE_LOCK_PATH.exists():
        PAL_MANDATE_LOCK_PATH.unlink()
        return True
    return False


def process_user_prompt(
    prompt: str,
    turn_count: int,
    cwd: Path | None = None,
    session_id: str | None = None,
    confidence: int | None = None,
) -> dict[str, Any]:
    """Process user prompt through mastermind pipeline.

    Called from UserPromptSubmit hook.

    Args:
        prompt: User's raw prompt
        turn_count: Current turn number
        cwd: Working directory
        session_id: Current session ID
        confidence: Current agent confidence level (0-100) for routing bias

    Returns:
        Dict with:
        - inject_context: Optional context to inject
        - modified_prompt: Prompt after override extraction
        - routing_info: Routing decision metadata
        - warnings: Any warnings for user
    """
    config = get_config()
    session_id = session_id or get_session_id()
    result: dict[str, Any] = {
        "inject_context": None,
        "modified_prompt": prompt,
        "routing_info": {},
        "warnings": [],
    }

    # Load or create session state keyed by CURRENT session_id
    # This ensures each Claude session gets fresh state
    state = load_state(session_id)

    # Parse user override
    clean_prompt, override = parse_user_override(prompt)
    result["modified_prompt"] = clean_prompt

    # Check if routing applies:
    # - ALWAYS route if ^ override (user explicitly requested planning)
    # - Route EVERY turn until PAL planner has been called (continuous monitoring)
    # - Once PAL bootstraps the session, skip Groq routing (planner has taken over)
    # This allows complexity to be detected even if a simple task evolves mid-session
    should_route = (
        (override == "^")  # User explicitly requested planning
        or (
            not state.pal_bootstrapped and config.router.enabled
        )  # Route until bootstrapped
    )

    # NOW increment turn counter (after routing check)
    state.increment_turn()
    if should_route:
        result["routing_info"] = handle_session_start_routing(
            clean_prompt, override, state, cwd, confidence
        )

    # Check for drift on subsequent turns
    elif state.turn_count > 1 and config.drift.enabled and state.blueprint:
        drift_result = handle_drift_check(state)
        if drift_result.get("warnings"):
            result["warnings"].extend(drift_result["warnings"])

    # Inject executor instructions if blueprint exists
    if should_inject_instructions(state):
        result["inject_context"] = generate_executor_instructions(
            state.blueprint, state
        )

    # Save state
    save_state(state)

    return result


def handle_session_start_routing(
    prompt: str,
    override: str | None,
    state: MastermindState,
    cwd: Path | None,
    confidence: int | None = None,
) -> dict[str, Any]:
    """Handle routing at session start (turn 0-1).

    Args:
        prompt: Clean user prompt (override prefix removed)
        override: User override prefix (!, ^, or None)
        state: Current mastermind session state
        cwd: Working directory
        confidence: Agent confidence level for routing bias

    Returns routing metadata.
    """
    config = get_config()
    result: dict[str, Any] = {"routed": False}

    # Handle explicit overrides
    if override == "!":
        result["skipped"] = True
        result["reason"] = "user_skip"
        return result

    if override == "^":
        result["forced"] = True
        result["classification"] = "complex"
        result["routed"] = True
        result["planner_mandate"] = True

        # Get project from cwd
        project = cwd.name if cwd else "unknown"

        # CREATE HARD LOCK - blocks ALL tools until PAL planner is called
        create_pal_mandate_lock(
            session_id=state.session_id,
            project=project,
            prompt=prompt,
        )

        # Inject MANDATORY PAL MCP planner directive (user forced via ^)
        result["inject_context"] = generate_planner_mandate(
            prompt, state, user_forced=True
        )
        return result

    # Pack context for router (include confidence for routing bias)
    router_ctx = pack_for_router(prompt, cwd, confidence)

    # Redact before sending
    redacted_prompt, _ = redact_text(router_ctx.prompt)

    # Call router (if not in dark launch)
    if config.rollout_phase > 0:
        router_response = call_groq_router(redacted_prompt)
        router_response = apply_risk_lexicon(prompt, router_response)

        # Log telemetry
        log_router_decision(
            state.session_id,
            state.turn_count,
            router_response.classification,
            router_response.confidence,
            router_response.reason_codes,
            router_response.latency_ms,
            override,
            router_response.needs_research,
            router_response.research_topics,
        )

        result["routed"] = True
        result["classification"] = router_response.classification
        result["confidence"] = router_response.confidence
        result["reason_codes"] = router_response.reason_codes
        result["task_type"] = router_response.task_type
        result["suggested_tool"] = router_response.suggested_tool
        result["needs_research"] = router_response.needs_research
        result["research_topics"] = router_response.research_topics or []
        result["action_hints"] = router_response.action_hints
        result["recommended"] = router_response.recommended
        result["intent"] = router_response.intent

        # Save routing decision to state for confidence tracking
        state.routing_decision = RoutingDecision(
            classification=router_response.classification,
            confidence=router_response.confidence,
            reason_codes=router_response.reason_codes,
            user_override=override,
            task_type=router_response.task_type,
            suggested_tool=router_response.suggested_tool,
        )

        # Apply routing decision
        policy = make_routing_decision(prompt, state.turn_count, router_response)
        result["should_plan"] = policy.should_plan

        # If classified as complex AND planner enabled, SUGGEST PAL tool (hybrid approach)
        # Claude can choose any PAL tool - hard lock ensures at least one is used
        if policy.should_plan and config.planner.enabled:
            project = cwd.name if cwd else "unknown"
            result["pal_suggestion"] = True

            # PHASE 3.2: Three-tier PAL guidance system
            #
            # TIER 1 - HARD BLOCK (conf < 75%):
            #   Creates lock file, blocks all tools until PAL used
            #   For: significant tasks when confidence is shaky
            #
            # TIER 2 - WARNING (conf 75-85%):
            #   Injects prominent warning but doesn't block
            #   For: uncertain territory, strong encouragement to use PAL
            #
            # TIER 3 - SUGGESTION (conf >= 85%):
            #   Normal context injection recommending PAL
            #   For: high confidence, trust agent judgment
            #
            # Risk lexicon (security/auth/deploy/migration/destructive) always
            # escalates to hard block regardless of confidence.
            #
            should_hard_lock = False
            should_warn = False
            classification = router_response.classification
            is_significant = classification in ("medium", "complex")
            has_risk_keywords = is_significant and any(
                code in (router_response.reason_codes or [])
                for code in ["security", "auth", "deploy", "migration", "destructive"]
            )

            # BEAD-AWARE ROUTING: If work is already tracked with an in_progress bead,
            # soften PAL enforcement by one tier (user is actively working on something)
            bead_in_progress = has_in_progress_bead()
            result["has_in_progress_bead"] = bead_in_progress

            if confidence is not None:
                if has_risk_keywords:
                    # Risk lexicon = always hard lock
                    should_hard_lock = True
                    result["lock_reason"] = "risk_lexicon_override"
                elif confidence < 75 and is_significant:
                    # Tier 1: Hard block - confidence below working threshold
                    should_hard_lock = True
                    result["lock_reason"] = "confidence_below_threshold"
                elif confidence < 85 and is_significant:
                    # Tier 2: Warning - uncertain territory
                    should_warn = True
                    result["warn_reason"] = "confidence_uncertain"
                # else: Tier 3 - normal suggestion (no special flags)
            else:
                # No confidence info = conservative (hard lock for significant)
                if is_significant:
                    should_hard_lock = True
                    result["lock_reason"] = "no_confidence_significant"

            # Apply bead-aware tier softening (unless risk lexicon)
            # If user has an in_progress bead, they're actively tracking work
            # This earns one tier of trust (Tier 1→2, Tier 2→3)
            if bead_in_progress and not has_risk_keywords:
                if should_hard_lock:
                    # Soften Tier 1 → Tier 2
                    should_hard_lock = False
                    should_warn = True
                    result["bead_softened"] = True
                    result["warn_reason"] = "bead_softened_from_lock"
                elif should_warn:
                    # Soften Tier 2 → Tier 3
                    should_warn = False
                    result["bead_softened"] = True

            if should_hard_lock:
                create_pal_mandate_lock(
                    session_id=state.session_id,
                    project=project,
                    prompt=prompt,
                )
                result["hard_lock"] = True
                result["pal_tier"] = 1
            elif should_warn:
                result["hard_lock"] = False
                result["pal_warning"] = True
                result["pal_tier"] = 2
            else:
                result["hard_lock"] = False
                result["soft_suggestion"] = True
                result["pal_tier"] = 3

            # Inject PAL MCP tool suggestion with tier-appropriate framing
            # Pass ALL Groq intelligence to maximize value from classification
            base_suggestion = generate_pal_suggestion(
                prompt,
                state,
                task_type=router_response.task_type,
                suggested_tool=router_response.suggested_tool,
                classification=router_response.classification,
                groq_confidence=router_response.confidence,
                reason_codes=router_response.reason_codes,
                needs_research=router_response.needs_research,
                research_topics=router_response.research_topics,
                recommended=router_response.recommended,
                discovery=router_response.discovery,
            )

            # Add tier-specific header
            if should_hard_lock:
                tier_header = (
                    "🚨 **PAL CONSULTATION REQUIRED** (Tier 1 - Hard Lock)\n\n"
                    "Tools are BLOCKED until you call a PAL MCP tool.\n"
                    "This ensures external perspective for this task.\n\n"
                )
            elif should_warn:
                tier_header = (
                    "⚠️ **PAL CONSULTATION RECOMMENDED** (Tier 2 - Warning)\n\n"
                    "Confidence is in uncertain territory (75-85%).\n"
                    "Strongly consider using PAL before proceeding.\n\n"
                )
            else:
                tier_header = ""  # Tier 3: Normal suggestion, no special header

            result["inject_context"] = tier_header + base_suggestion

        else:
            # Trivial task - still inject research directive if detected
            # Maximizes value from Groq call even when PAL isn't needed
            if router_response.needs_research and router_response.research_topics:
                topics = router_response.research_topics[:4]
                topics_list = "\n".join(f"  - `{t}`" for t in topics)
                result["inject_context"] = (
                    f"## 🔍 Research Recommended (Groq-detected)\n\n"
                    f"This looks straightforward, but current docs may help:\n{topics_list}\n\n"
                    f"Use `mcp__crawl4ai__ddg_search` if needed.\n"
                )
                result["research_only"] = True

    else:
        # Dark launch - just log what would happen
        result["dark_launch"] = True
        result["would_route"] = True

    return result


def handle_drift_check(state: MastermindState) -> dict[str, Any]:
    """Check for drift and generate warnings if needed."""
    result: dict[str, Any] = {"warnings": []}

    signals = evaluate_drift(state)

    if signals and should_escalate(signals, state):
        # Generate variance report
        report = generate_variance_report(state, signals)
        warning = format_variance_for_user(report)
        result["warnings"].append(warning)

        # Log escalation
        for signal in signals:
            log_escalation(
                state.session_id,
                state.turn_count,
                signal.trigger,
                state.epoch_id,
                signal.evidence,
            )

        # Record escalation in state
        state.record_escalation(
            signals[0].trigger,
            signals[0].evidence,
        )

    return result


def record_file_modification(file_path: str) -> None:
    """Record a file modification in session state.

    Called from Edit/Write tool hooks.
    """
    session_id = get_session_id()
    state = load_state(session_id)
    state.record_file_modified(file_path)
    save_state(state)


def record_test_failure() -> None:
    """Increment test failure count in session state.

    Called when test commands fail.
    """
    session_id = get_session_id()
    state = load_state(session_id)
    state.test_failures += 1
    save_state(state)
