#!/usr/bin/env python3
"""
Composite UserPromptSubmit Runner: Runs all UserPromptSubmit hooks in a single process.

PERFORMANCE: ~50ms for 29 hooks vs ~500ms for individual processes (10x faster)

HOOKS INDEX (by priority):
  GATING (0-10) - _prompt_gating.py:
    0  confidence_override      - SUDO bypass and CONFIDENCE_BOOST
    1  context_guard_check      - Proactive context exhaustion check (v4.22)
    1  goal_anchor              - Block scope expansion, warn on drift
    2  user_sentiment           - Detect user frustration/correction
    3  rock_bottom_realignment  - Force realignment at 0% confidence
    4  confidence_initializer   - Assess confidence, mandate research/external
    5  intake_protocol          - Show complexity-tiered checklists
    6  build_vs_buy             - Challenge custom build proposals
    7  confidence_approval_gate - Handle trust restoration requests
    8  confidence_dispute       - Handle false positive reducer disputes
   10  verified_library_unlock  - Unlock verified libraries

  EXTRACTION/CONTEXT (12-70) - _prompt_context.py:
   12  tool_debt_enrichment - Enrich context with tool debt tracking
   15  intention_tracker   - Extract mentioned files/searches
   30  prompt_disclaimer   - System context + task checklist
   32  tech_version_risk   - Warn about outdated AI knowledge
   35  project_context     - Git state, project structure
   40  memory_injector     - Lessons, spark, decisions, scope
   45  context_injector    - Session state, command suggestions
   50  reminder_injector   - Custom trigger-based reminders

  SUGGESTIONS (2, 70-95) - _prompt_suggestions.py:
    2  beads_periodic_sync   - Periodic background beads sync
   70  complexity_assessment - BMAD-style task complexity detection
   71  advisor_context     - Persona-flavored advisory (security, architecture, etc.)
   72  self_heal_diagnostic - Diagnostic commands when self-heal active
   75  proactive_nudge     - Actionable suggestions from state
   80  ops_nudge           - Tool suggestions (comprehensive)
   81  agent_suggestion    - Suggest Task agents based on prompt patterns
   82  skill_suggestion    - Suggest Skills based on prompt patterns
   85  ops_awareness       - Script awareness (fallback)
   86  ops_audit_reminder  - Periodic unused tool reminder
   88  intent_classifier   - ML-based intent classification
   89  expert_probe        - Force probing questions
   89  pal_mandate         - PAL tool mandates based on state
   90  resource_pointer    - Sparse pointers to resources
   91  work_patterns       - Assumptions, rollback, confidence, integration
   93  quality_signals     - Pattern smells, context decay alerts
   95  response_format     - Structured response sections

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
import time

from session_state import load_state, save_state, SessionState  # noqa: F401

# =============================================================================
# HOOK REGISTRY (shared across modules)
# =============================================================================

from _prompt_registry import HOOKS

# Import hook modules (triggers registration via decorators)
import _prompt_gating  # noqa: F401 - Gating hooks (priority 0-10)
import _prompt_mastermind  # noqa: F401 - Mastermind orchestration (priority 6)
import _prompt_context  # noqa: F401 - Context hooks (priority 15-70)
import _prompt_suggestions  # noqa: F401 - Suggestion hooks (priority 72-95)


# =============================================================================
# MAIN RUNNER
# =============================================================================


def run_hooks(data: dict, state: SessionState) -> dict:
    """Run all hooks and return aggregated result."""
    contexts = []

    for name, check_func, priority in HOOKS:
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

        except Exception:
            import traceback

            print(
                f"[ups-runner] Hook {name} crashed:\n{traceback.format_exc()}",
                file=sys.stderr,
            )

    # Build output
    output = {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit"}}
    if contexts:
        # Limit to avoid context explosion
        output["hookSpecificOutput"]["additionalContext"] = "\n\n".join(contexts[:8])

    return output


# Pre-sort hooks by priority at module load (avoid re-sorting on every call)
HOOKS.sort(key=lambda x: x[2])


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
