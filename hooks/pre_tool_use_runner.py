#!/usr/bin/env python3
"""
Composite PreToolUse Runner: Runs all PreToolUse hooks in a single process.

PERFORMANCE: ~35ms for 24 hooks vs ~400ms for individual processes (10x faster)

HOOKS INDEX (by priority):
  ORCHESTRATION (0-5):
    1  fp_fix_enforcer     - HARD BLOCK until false positive is fixed (Hard Block #14)
    2  self_heal_enforcer  - Block unrelated work until framework errors fixed
    3  exploration_cache   - Return cached exploration results
    3  parallel_bead_delegation - Force parallel Task agents for multiple open beads
    4  parallel_nudge      - Nudge sequential Task spawns → parallel + background
    4  beads_parallel      - Nudge sequential bd commands → batch/parallel
    4  bead_enforcement    - Require in_progress bead before Edit/Write

  SAFETY (5-20):
    5  recursion_guard     - Block nested .claude/.claude paths
    10 loop_detector       - Block bash loops
    14 inline_server_background - Block server & curl/sleep patterns
    15 background_enforcer - Require background for slow commands
    18 confidence_tool_gate - Block tools at low confidence levels

  GATES (20-50):
    20 commit_gate         - Warn on git commit without upkeep
    25 tool_preference     - Nudge toward preferred tools
    30 oracle_gate         - Enforce think/council after failures
    32 confidence_external_suggestion - Suggest alternatives at low confidence
    35 integration_gate    - Require grep after function edits
    40 error_suppression   - Block until errors resolved
    45 content_gate        - Block eval/exec/SQL injection
    47 crawl4ai_preference - Suggest crawl4ai over WebFetch
    50 gap_detector        - Block edit without read

  QUALITY (55-95):
    55 production_gate     - Audit/void for .claude/ops writes
    60 deferral_gate       - Block "TODO: later" comments
    65 doc_theater_gate    - Block standalone .md files
    70 root_pollution_gate - Block home directory clutter
    75 recommendation_gate - Warn on duplicate infrastructure
    80 security_claim_gate - Warn on security-sensitive code
    85 epistemic_boundary  - Warn on unverified identifiers
    88 research_gate       - Block unverified libraries
    92 import_gate         - Warn on third-party imports
    95 modularization_nudge- Occasional modularization reminder
    96 curiosity_injection - Metacognitive prompts before major edits

  SESSION (80-90):
    80 sunk_cost_detector  - Detect failure loops
    90 thinking_coach      - Detect reasoning flaws

ARCHITECTURE:
  - Hooks register via @register_hook(name, matcher, priority)
  - Lower priority = runs first
  - First DENY wins, contexts are aggregated
  - Single state load/save per invocation
"""

import _lib_path  # noqa: F401
import sys
import json
import os
import re
import time
from typing import Optional, Callable

# PERFORMANCE: Minimal top-level imports. Heavy modules loaded lazily inside hooks.
# This reduces import time from ~55ms to ~20ms per invocation.

# Core session state - needed for run_hooks orchestration
from session_state import (
    load_state,
    save_state,
    SessionState,
    track_block,
    clear_blocks,
    check_cascade_failure,
)
from _hook_result import HookResult

# LAZY IMPORTS - These are loaded inside hooks that need them:
# - confidence (check_tool_permission, get_tier_info) -> confidence_tool_gate, homeostatic_drive, threat_anticipation
# - _beads (get_open_beads, etc.) -> bead_enforcement, parallel_bead_delegation
# - _confidence_constants -> homeostatic_drive, threat_anticipation
# - _confidence_streaks -> threat_anticipation

# =============================================================================
# MODULE-LEVEL STATE (for hooks that need cross-invocation caching)
# =============================================================================
_BD_CACHE: dict = {}  # Beads cache for beads_parallel hook
_BD_CACHE_TURN: int = 0  # Turn when cache was last valid


# =============================================================================
# SHARED HELPERS
# =============================================================================

# NOTE: _detect_serena_project moved to hooks/gates/_serena.py

# =============================================================================
# HOOK REGISTRY
# =============================================================================

# Format: (name, matcher_pattern, check_function, priority)
# Lower priority = runs first. Blocks stop execution.
# matcher_pattern: None = all tools, str = regex pattern
HOOKS: list[tuple[str, Optional[str], Callable, int]] = []


def register_hook(name: str, matcher: Optional[str], priority: int = 50):
    """Decorator to register a hook check function.

    Hooks can be disabled via environment variable:
        CLAUDE_HOOK_DISABLE_<NAME>=1

    Example:
        CLAUDE_HOOK_DISABLE_CONTENT_GATE=1 claude
    """

    def decorator(func: Callable[[dict, SessionState], HookResult]):
        # Check if hook is disabled via environment variable
        env_key = f"CLAUDE_HOOK_DISABLE_{name.upper()}"
        if os.environ.get(env_key, "0") == "1":
            return func  # Skip registration
        HOOKS.append((name, matcher, func, priority))
        return func

    return decorator


# =============================================================================
# IMPORT MODULAR GATES
# =============================================================================
# Gates are being extracted to hooks/gates/ for better organization.
# Import them here so their @register_hook decorators execute.
from gates import HOOKS as GATES_HOOKS  # noqa: E402

HOOKS.extend(GATES_HOOKS)

# =============================================================================
# HOOK IMPLEMENTATIONS (remaining inline hooks)
# =============================================================================


# NOTE: Confidence system gates (homeostatic_drive, threat_anticipation,
#       confidence_tool_gate, oracle_gate, confidence_external_suggestion,
#       integration_gate, error_suppression_gate)
# moved to hooks/gates/_confidence.py - imported via gates package above

# NOTE: Content gates (content_gate, god_component_gate, gap_detector, production_gate,
#       deferral_gate, doc_theater_gate, root_pollution_gate, recommendation_gate,
#       security_claim_gate, epistemic_boundary, research_gate, import_gate,
#       modularization_nudge, curiosity_injection, crawl4ai_preference)
# moved to hooks/gates/_content.py - imported via gates package above

# =============================================================================
# MAIN RUNNER
# =============================================================================

# Pre-built lookup for fast hook filtering (built after HOOKS.sort())
HOOKS_BY_TOOL: dict[str, list] = {}  # Populated by _build_hook_index()
_HOOK_MATCHERS: dict[str, re.Pattern] = {}  # Pre-compiled regex patterns


def _build_hook_index():
    """Build optimized hook lookup index at module load.

    Creates:
    - _HOOK_MATCHERS: Pre-compiled regex for each unique matcher
    - HOOKS_BY_TOOL["__all__"]: Hooks that match all tools (matcher=None)
    """
    global HOOKS_BY_TOOL, _HOOK_MATCHERS
    HOOKS_BY_TOOL = {"__all__": []}
    _HOOK_MATCHERS = {}

    for hook in HOOKS:
        name, matcher, check_func, priority = hook
        if matcher is None:
            HOOKS_BY_TOOL["__all__"].append(hook)
        elif matcher not in _HOOK_MATCHERS:
            # Pre-compile regex pattern
            _HOOK_MATCHERS[matcher] = re.compile(f"^({matcher})$")


def _get_hooks_for_tool(tool_name: str) -> list:
    """Get applicable hooks for a tool, using cached lookup when possible."""
    if tool_name not in HOOKS_BY_TOOL:
        # Build list for this tool on first access
        applicable = list(HOOKS_BY_TOOL["__all__"])  # Start with "match all" hooks

        for hook in HOOKS:
            name, matcher, check_func, priority = hook
            if matcher is None:
                continue  # Already included in __all__
            # Use pre-compiled pattern
            pattern = _HOOK_MATCHERS.get(matcher)
            if pattern and pattern.match(tool_name):
                applicable.append(hook)

        # Sort by priority (should already be sorted, but ensure)
        applicable.sort(key=lambda x: x[3])
        HOOKS_BY_TOOL[tool_name] = applicable

    return HOOKS_BY_TOOL[tool_name]


def matches_tool(matcher: Optional[str], tool_name: str) -> bool:
    """Check if tool matches the hook's matcher pattern."""
    if matcher is None:
        return True
    return bool(re.match(f"^({matcher})$", tool_name))


def run_hooks(data: dict, state: SessionState) -> dict:
    """Run all applicable hooks and return aggregated result."""
    # Clear integration cache at start of each hook run to avoid stale detection
    # (e.g., Serena availability from a previous project directory)
    from _integration import clear_cache as clear_integration_cache

    clear_integration_cache()

    tool_name = data.get("tool_name", "")

    # Pre-compute SUDO bypass once for all hooks (avoids 18 redundant transcript reads)
    transcript_path = data.get("transcript_path", "")
    if transcript_path:
        from synapse_core import check_sudo_in_transcript

        data["_sudo_bypass"] = check_sudo_in_transcript(transcript_path)
    else:
        data["_sudo_bypass"] = False

    # Use pre-filtered hook list (built at module load, cached per tool name)
    applicable_hooks = _get_hooks_for_tool(tool_name)

    # Collect results
    contexts = []

    for name, matcher, check_func, priority in applicable_hooks:
        try:
            result = check_func(data, state)

            # First deny wins - but check for cascade failure first
            if result.decision == "deny":
                # Track this block for cascade detection
                track_block(state, name)

                # Check if we're in a cascade failure state
                is_cascade, escalation_msg = check_cascade_failure(state, name)
                if is_cascade:
                    # Allow with escalation instead of hard block
                    contexts.append(
                        f"⚠️ **CASCADE DETECTED** ({name} blocked 3+ times):\n"
                        f"{result.reason}\n\n{escalation_msg}"
                    )
                    # Don't return deny - let the operation through with warning
                    continue

                return {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "deny",
                        "permissionDecisionReason": result.reason,
                    }
                }

            # Clear cascade tracking on successful hook pass
            clear_blocks(state, name)

            # Collect contexts
            if result.context:
                contexts.append(result.context)

        except Exception as e:
            # Log error but don't block
            print(f"[runner] Hook {name} error: {e}", file=sys.stderr)

    # Build output
    output = {"hookSpecificOutput": {"hookEventName": "PreToolUse"}}
    if contexts:
        output["hookSpecificOutput"]["additionalContext"] = "\n\n".join(contexts[:3])

    return output


# Pre-sort hooks by priority at module load (avoid re-sorting on every call)
HOOKS.sort(key=lambda x: x[3])

# Build optimized hook index after sorting
_build_hook_index()


def main():
    """Main entry point."""
    start = time.time()

    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse"}}))
        sys.exit(0)

    # Single state load
    state = load_state()

    # Run all hooks
    result = run_hooks(data, state)

    # Single state save
    save_state(state)

    # Output result
    print(json.dumps(result))

    # Debug timing (to stderr)
    elapsed = (time.time() - start) * 1000
    if elapsed > 50:
        print(f"[runner] Slow: {elapsed:.1f}ms", file=sys.stderr)

    sys.exit(0)


if __name__ == "__main__":
    main()
