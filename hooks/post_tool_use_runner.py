#!/usr/bin/env python3
"""
Composite PostToolUse Runner: Runs all PostToolUse hooks in a single process.

PERFORMANCE: ~40ms for 8 hooks vs ~300ms for individual processes (7x faster)

HOOKS INDEX (by priority):
  STATE (0-20):
    10 state_updater       - Track files read/edited, commands, libraries, errors
    11 confidence_decay    - Natural decay + tool boosts (context-scaled)
    12 confidence_reducer  - Apply deterministic confidence reductions on failures
    14 confidence_increaser - Apply confidence increases on success signals
    16 thinking_quality_boost - Reward good reasoning (evidence, verification, diagnosis)

  QUALITY GATES (22-50):
    22 assumption_check    - Surface hidden assumptions in code changes
    25 verification_reminder - Remind to verify after fix iterations
    30 ui_verification     - Remind to screenshot after CSS/UI changes
    35 code_quality_gate   - Detect anti-patterns (N+1, O(n³), blocking I/O, nesting)
    37 state_mutation_guard - Detect React/Python mutation anti-patterns
    40 dev_toolchain_suggest - Suggest lint/format/typecheck per language
    45 large_file_helper   - Line range guidance for big files
    48 crawl4ai_promo      - Promote crawl4ai over WebFetch for web content
    50 tool_awareness      - Remind about Playwright, Zen MCP, WebSearch, Task agents

  TRACKERS (55-77):
    55 scratch_enforcer    - Detect repetitive patterns, suggest scripts
    60 auto_learn          - Capture lessons from errors, quality hints
    65 velocity_tracker    - Detect oscillation/spinning patterns
    70 info_gain_tracker   - Detect reads without progress
    72 beads_auto_sync     - Auto-sync beads after git commit/push
    73 toolchain_bead_creator - Create beads from GPT-5.2 toolchain recommendations
    74 toolchain_stage_tracker - Track tool usage, auto-update/close stage beads
    75 pattern_curiosity   - Pattern recognition prompts after 5+ file reads
    76 failure_curiosity   - Alternative approach prompts after tool failures
    77 low_confidence_curiosity - Uncertainty exploration at <70% confidence

  STUCK LOOP DETECTION (78-85):
    78 fix_attempt_tracker  - Track edit attempts during debugging sessions
    79 symptom_tracker      - Track recurring symptoms/errors
    80 research_tracker     - Track when research is performed
    81 verification_prompt  - Prompt for verification after fix attempts
    82 circuit_breaker      - Block edits until research done
    83 debug_session_reset  - Reset debug session on clear success
    84 confidence_floor_debug - Force research when confidence <50% during debug
    85 confidence_recovery  - Track recovery after confidence-triggered research

  CODE-MODE (88):
    88 codemode_result_recorder - Auto-record results for pending handoff calls

  SMART COMMIT (95-97):
    95 smart_commit_bead_close - Auto-commit on bd close with bead title
    96 smart_commit_track_edit - Track file edits for commit suggestions
    96 smart_commit_track_commit - Track git commits to reset state
    97 smart_commit_periodic   - Periodic commit suggestions

ARCHITECTURE:
  - Hooks register via @register_hook(name, matcher, priority)
  - Lower priority = runs first
  - All hooks run (no blocking for PostToolUse)
  - Contexts are aggregated and returned
  - Single state load/save per invocation
"""

import _lib_path  # noqa: F401
import sys
import json
import time

# Performance: centralized configuration

from session_state import (
    load_state,
    save_state,
    SessionState,
)

# Confidence system imports (v4.0)
# Note: Quality scanner imported in _hooks_quality.py where it's used

# =============================================================================
# PRE-COMPILED PATTERNS (Performance: compile once at module load)
# =============================================================================

# =============================================================================
# HOOK REGISTRY (shared across modules)
# =============================================================================

from _hook_registry import HOOKS, matches_tool

# Import hook modules (triggers registration via decorators)
import _hooks_cache  # noqa: F401 - Cache hooks (priority 5-6)
import _hooks_state_pal  # noqa: F401 - PAL mandate hook (priority 5)
import _hooks_state  # noqa: F401 - State hooks (priority 9-10) + shared utilities
import _hooks_state_decay  # noqa: F401 - Confidence decay (priority 11)
import _hooks_state_reducers  # noqa: F401 - Confidence reducers (priority 12)
import _hooks_state_increasers  # noqa: F401 - Confidence increasers (priority 14-16)
import _hooks_quality  # noqa: F401 - Quality hooks (priority 22-50)
import _hooks_tracking  # noqa: F401 - Tracking hooks (priority 55-72)
import _hooks_stuck_loop  # noqa: F401 - Stuck loop detection (priority 78-83)
import _hooks_mastermind  # noqa: F401 - Mastermind integration (priority 86-89)
import _hooks_smart_commit  # noqa: F401 - Smart auto-commit (priority 95-97)
import _hooks_codemode  # noqa: F401 - Code-mode result recording (priority 88)
from _hooks_tracking import _get_scratch_state_file, _get_info_gain_state_file

# =============================================================================
# MAIN RUNNER
# =============================================================================


def _load_state_file(path) -> dict | None:
    """Load JSON state from file, returning None on error."""
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def _save_state_file(path, data: dict) -> None:
    """Save JSON state to file, logging on error."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data))
    except (IOError, OSError) as e:
        print(f"[post-runner] State save failed: {path}: {e}", file=sys.stderr)


def _load_runner_state() -> dict:
    """Load persisted runner state from disk."""
    runner_state = {}
    if scratch := _load_state_file(_get_scratch_state_file()):
        runner_state["scratch_state"] = scratch
    if info_gain := _load_state_file(_get_info_gain_state_file()):
        runner_state["info_gain_state"] = info_gain
    return runner_state


def _save_runner_state(runner_state: dict) -> None:
    """Save runner state to disk."""
    if "scratch_state" in runner_state:
        _save_state_file(_get_scratch_state_file(), runner_state["scratch_state"])
    if "info_gain_state" in runner_state:
        _save_state_file(_get_info_gain_state_file(), runner_state["info_gain_state"])


def run_hooks(data: dict, state: SessionState) -> dict:
    """Run all applicable hooks and return aggregated result."""
    tool_name = data.get("tool_name", "")
    runner_state = _load_runner_state()
    contexts = []

    for name, matcher, check_func, priority in HOOKS:
        if not matches_tool(matcher, tool_name):
            continue
        try:
            result = check_func(data, state, runner_state)
            if result.context:
                contexts.append(result.context)
        except Exception as e:
            print(f"[post-runner] Hook {name} error: {e}", file=sys.stderr)

    _save_runner_state(runner_state)

    output = {"hookSpecificOutput": {"hookEventName": "PostToolUse"}}
    if contexts:
        if len(contexts) > 5:
            print(
                f"[post-runner] Truncated {len(contexts) - 5} contexts", file=sys.stderr
            )
        output["hookSpecificOutput"]["additionalContext"] = "\n\n".join(contexts[:5])
    return output


# Pre-sort hooks by priority at module load (avoid re-sorting on every call)
HOOKS.sort(key=lambda x: x[3])


def main():
    """Main entry point."""
    start = time.time()

    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse"}}))
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
    if elapsed > 100:
        print(f"[post-runner] Slow: {elapsed:.1f}ms", file=sys.stderr)

    sys.exit(0)


if __name__ == "__main__":
    main()
