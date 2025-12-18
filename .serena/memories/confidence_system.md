# Confidence System

## Overview

The confidence system is a **mechanical behavioral regulation system** that prevents:
- Sycophancy (agreeing with users to avoid conflict)
- Reward hacking (claiming success without verification)
- Lazy completion (saying "done" without earning it)
- Self-assessment bias (overestimating correctness)

**Key principle:** Claude cannot accurately judge its own confidence - it's mechanically regulated based on actual signals.

## Location
- **Core module**: `lib/confidence.py` (facade)
- **Reducers**: `lib/_confidence_reducers.py` (59 reducers)
- **Increasers**: `lib/_confidence_increasers.py` (51 increasers)
- **Applied in**: `hooks/post_tool_use_runner.py`
- **Gates in**: `hooks/pre_tool_use_runner.py`
- **Completion gate**: `hooks/stop_runner.py`

## Stasis Target: 80-90%

**Healthy operation means confidence stays in the 80-90% range.** This "stasis zone" represents balanced operation where small penalties balance with small rewards.

**If confidence drops below 80%**, proactively recover by:
1. Reading relevant files (+1 each)
2. Running `git status/log/diff` (+3, cooldown 5)
3. Consulting `~/.claude/memory/` files (+10)
4. Creating beads with `bd create` (+10)
5. Running lints/tests (+3/+5)
6. Asking clarifying questions (+8)

## Confidence Zones

| Zone | Range | Emoji | Capabilities |
|------|-------|-------|--------------|
| IGNORANCE | 0-30 | 🔴 | Read/Research ONLY, external LLM MANDATORY |
| HYPOTHESIS | 31-50 | 🟠 | Scratch only, research REQUIRED |
| WORKING | 51-70 | 🟡 | Scratch + git read, research suggested |
| CERTAINTY | 71-85 | 🟢 | Production with gates |
| TRUSTED | 86-94 | 💚 | Production with warnings |
| EXPERT | 95-100 | 💎 | Maximum freedom |

**Default starting confidence**: 70 (WORKING tier)

## Reducer Categories (59 total)

| Category | Count | Examples |
|----------|-------|----------|
| Core (real problems) | 8 | tool_failure, cascade_block, sunk_cost |
| Bad behavior (BANNED) | 12 | backup_file, deferral, sycophancy |
| Sequential/efficiency | 3 | sequential_repetition, sequential_when_parallel |
| Verification | 4 | unbacked_verification_claim, fixed_without_chain |
| Code quality | 11 | placeholder_impl, silent_failure, deep_nesting |
| Token efficiency | 6 | verbose_preamble, redundant_explanation |
| Test coverage | 2 | test_ignored, change_without_test |
| Framework alignment | 6 | todowrite_bypass, grep_over_serena |
| Scripting | 2 | complex_bash_chain, bash_data_transform |
| Stuck loop | 2 | stuck_loop, no_research_debug |
| Mastermind drift | 3 | mastermind_file_drift, mastermind_approach_drift |

See `confidence_reducers` memory for full list.

## Increaser Categories (51 total)

| Category | Count | Examples |
|----------|-------|----------|
| Due diligence | 14 | file_read, test_pass, memory_consult |
| User interaction | 3 | ask_user, user_ok, trust_regained |
| Efficiency | 7 | parallel_tools, batch_fix, direct_action |
| Completion quality | 6 | bead_close, first_attempt_success |
| Workflow signals | 5 | pr_created, ci_pass, merge_complete |
| Code quality | 6 | docstring_addition, security_fix |
| Framework alignment | 6 | crawl4ai_used, serena_symbolic |
| Scripting | 3 | tmp_script_created, background_script |
| Self-improvement | 1 | framework_self_heal |

See `confidence_increasers` memory for full list.

## Rate Limiting

- **Per-turn cap**: Maximum ±15 total change per turn normally
- **Below stasis (< 80%)**: Positive cap raised to +30 for faster recovery
- **Streak multiplier**: Consecutive successes earn 1.25x/1.5x/2x rewards

## Hard Blocks

### Pre-Tool Blocks (confidence_tool_gate)
- **< 30%**: All writes blocked (Edit, Write, Bash state changes)
- **< 51%**: Production writes blocked (only scratch allowed)

### Completion Gate (Stop)
- **< 70%**: Cannot claim task "complete", "done", "finished"
- **< 75% with negative trend**: Also blocked

## False Positive Handling

When a reducer fires incorrectly:
- **Claude**: Run `~/.claude/ops/fp.py <reducer> [reason]`
- **User**: Say `FP: <reducer>` or `dispute <reducer>`

Each FP recorded increases cooldown by 50% (max 3x original).

## Fatigue System

Session length affects decay rate:

| Tier | Turns | Multiplier |
|------|-------|------------|
| Fresh | 0-29 | 1.0x |
| Warming | 30-59 | 1.25x |
| Working | 60-99 | 1.5x |
| Tired | 100-149 | 2.0x |
| Exhausted | 150+ | 2.5x |

## Key Functions

```python
# lib/confidence.py (facade)
apply_reducers(context, state) -> list[tuple[str, int, str]]
apply_increasers(context, state) -> list[tuple[str, int, str]]
apply_rate_limit(delta) -> int
apply_mean_reversion(confidence, state) -> int
get_tier_info(confidence) -> tuple[str, str, str]
check_tool_permission(tool, confidence, path) -> tuple[bool, str]
predict_trajectory(state, planned_edits, planned_bash, turns) -> dict
record_false_positive(reducer_name, reason)
get_adaptive_cooldown(reducer_name) -> int
```

*Updated: 2025-12-17*
