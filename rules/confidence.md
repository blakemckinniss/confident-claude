# Confidence System

**You cannot judge your own confidence.** It's mechanically regulated based on actual signals.

## Why This Exists

LLMs are prone to:
- **Sycophancy**: Agreeing with users to avoid conflict
- **Reward hacking**: Claiming success without verification
- **Lazy completion**: Saying "done" without earning it
- **Self-assessment bias**: Overestimating own correctness

The confidence system provides **external mechanical regulation** that bypasses self-judgment.

## Stasis Target: 80-90%

**Healthy operation means confidence stays in the 80-90% range.**

This "stasis zone" represents balanced operation where:
- Small penalties (-1 bash-risk, -1 edit-risk, -1 decay) balance with
- Small rewards (+1 file_read, +2 research, +3 lint_pass, +5 test_pass)

**If confidence drops below 80%**, PROACTIVELY recover by:
1. Reading relevant files (+1 each)
2. Running `git status/log/diff` (+10)
3. Consulting `~/.claude/memory/` files (+10)
4. Creating beads with `bd create` (+10)
5. Running lints/tests (+3/+5)
6. Asking clarifying questions (+20)

**Do NOT spam SUDO** - use the increasers to earn confidence back legitimately.

## Confidence Zones

| Zone | Range | Emoji | Allowed Actions |
|------|-------|-------|-----------------|
| IGNORANCE | 0-30 | 🔴 | Read, Grep, Glob, WebSearch only. External LLM MANDATORY. |
| HYPOTHESIS | 31-50 | 🟠 | Above + scratch writes. Research REQUIRED. |
| WORKING | 51-70 | 🟡 | Above + git read. Research suggested. |
| CERTAINTY | 71-85 | 🟢 | Production writes WITH gates (audit/void). |
| TRUSTED | 86-94 | 💚 | Production writes with warnings only. |
| EXPERT | 95-100 | 💎 | Full access. |

**Default starting confidence: 70 (WORKING)**

## Reducers (Automatic Penalties)

These fire **mechanically** based on signals - no self-judgment involved.

**Core reducers:**

| Reducer | Delta | Trigger | Cooldown |
|---------|-------|---------|----------|
| `tool_failure` | -5 | Bash exit code != 0 | 1 turn |
| `cascade_block` | -15 | Same hook blocks 3+ times in 5 turns | 5 turns |
| `sunk_cost` | -20 | 3+ consecutive failures on same approach | 5 turns |
| `user_correction` | -10 | User says "wrong", "incorrect", "fix that", etc. | 3 turns |
| `edit_oscillation` | -12 | Same file edited 3+ times in 5 turns | 5 turns |
| `goal_drift` | -8 | < 20% keyword overlap with original goal | 8 turns |
| `contradiction` | -10 | Contradictory claims detected | 5 turns |
| `bash-risk` | -1 | Any bash command (state change risk) | 3 turns |
| `edit-risk` | -1 | Any file edit | 3 turns |
| `decay` | -1 | Natural drift toward uncertainty | None |

**Bad behavior reducers (BANNED patterns):**

| Reducer | Delta | Trigger | Cooldown |
|---------|-------|---------|----------|
| `backup_file` | -10 | Creating .bak, .backup, .old files | 1 turn |
| `version_file` | -10 | Creating _v2, _new, _copy files | 1 turn |
| `debt_bash` | -10 | --force, --hard, --no-verify commands | 1 turn |
| `markdown_creation` | -8 | Creating .md files (except memory/docs) | 1 turn |
| `large_diff` | -8 | Diffs over 400 LOC (risky changes) | 1 turn |
| `overconfident_completion` | -15 | "100% done", "completely finished" | 3 turns |
| `deferral` | -12 | "skip for now", "come back later" | 3 turns |
| `apologetic` | -5 | "sorry", "my mistake", "I apologize" | 2 turns |
| `sycophancy` | -8 | "you're absolutely right", "great point" | 2 turns |
| `unresolved_antipattern` | -10 | Mentioning issues without fixing | 3 turns |
| `hook_block` | -5 | When hooks block actions | 1 turn |
| `surrender_pivot` | -20 | Abandoning user's goal for "easier" alternative | NO LIMIT |

**Code quality reducers (v4.4):**

| Reducer | Delta | Trigger | Cooldown |
|---------|-------|---------|----------|
| `placeholder_impl` | -8 | `pass`, `...`, NotImplementedError in new code | 1 turn |
| `silent_failure` | -8 | `except: pass` or `except Exception: pass` | 1 turn |
| `hallmark_phrase` | -3 | AI-speak: "certainly", "I'd be happy to" | 2 turns |
| `scope_creep` | -8 | "while I'm at it", "might as well", "let's also" | 3 turns |
| `incomplete_refactor` | -10 | Partial renames/changes (context-based) | 3 turns |

**Test coverage reducers (v4.5):**

| Reducer | Delta | Trigger | Cooldown |
|---------|-------|---------|----------|
| `test_ignored` | -5 | Modified test files without running tests | 5 turns |
| `change_without_test` | -3 | Production code changed without test coverage | 5 turns |

**Framework alignment reducers (v4.8) - micro-signals for framework drift:**

| Reducer | Delta | Trigger | Cooldown |
|---------|-------|---------|----------|
| `webfetch_over_crawl` | -1 | WebFetch used (prefer crawl4ai) | None |
| `websearch_basic` | -1 | WebSearch used (prefer crawl4ai.ddg_search) | None |
| `todowrite_bypass` | -2 | TodoWrite used (beads required) | None |
| `raw_symbol_hunt` | -1 | Reading code file without serena activation | None |
| `grep_over_serena` | -1 | Grep on code when serena is active | None |
| `file_reedit` | -2 | Re-editing file already edited this session | None |
| `sequential_file_ops` | -1 | 3+ Read/Edit/Write without batching | 3 turns |

## Increasers (Automatic Rewards)

**Due diligence rewards balance natural decay:**

| Increaser | Delta | Trigger |
|-----------|-------|---------|
| `file_read` | +1 | Read tool (gathering evidence) |
| `productive_bash` | +1 | ls, pwd, which, tree, stat (inspection) |
| `research` | +2 | WebSearch, WebFetch, crawl4ai |
| `search_tool` | +2 | Grep, Glob, Task (understanding) |
| `rules_update` | +15 | Edit CLAUDE.md or /rules/ (framework DNA) |
| `lint_pass` | +3 | ruff check, eslint, cargo clippy passes |
| `small_diff` | +3 | Diffs under 400 LOC (focused changes) |
| `custom_script` | +5 | ~/.claude/ops/* scripts (audit, void, etc.) |
| `test_pass` | +5 | pytest/jest/cargo test passes |
| `build_success` | +5 | npm build/cargo build/tsc succeeds |
| `memory_consult` | +10 | Read ~/.claude/memory/ files |
| `bead_create` | +10 | bd create/update (task tracking) |
| `git_explore` | +10 | git log/diff/status/show/blame |
| `ask_user` | +20 | AskUserQuestion (epistemic humility) |
| `user_ok` | +2 | Short positive feedback ("ok", "thanks") |
| `trust_regained` | +15 | User says "CONFIDENCE_BOOST_APPROVED" |
| `premise_challenge` | +5 | Suggested existing solution or challenged build-vs-buy |

**Completion quality increasers (v4.4):**

| Increaser | Delta | Trigger |
|-----------|-------|---------|
| `bead_close` | +5 | `bd close` command (completing tracked work) |
| `first_attempt_success` | +3 | Task completed without retry/correction |
| `dead_code_removal` | +3 | Removing unused code/imports |
| `scoped_change` | +2 | Changes stayed within requested scope |
| `external_validation` | +5 | Using `mcp__pal__*` tools for validation |

**Workflow signals (v4.5):**

| Increaser | Delta | Trigger |
|-----------|-------|---------|
| `pr_created` | +5 | `gh pr create` succeeds (PR ready for review) |
| `issue_closed` | +3 | `gh issue close` succeeds (task completion) |
| `review_addressed` | +5 | PR review comments resolved/addressed |
| `ci_pass` | +5 | `gh run`/`gh pr checks` shows passing CI |
| `merge_complete` | +5 | `gh pr merge` succeeds (work accepted) |

**Framework alignment increasers (v4.8) - micro-signals for framework adoption:**

| Increaser | Delta | Trigger |
|-----------|-------|---------|
| `crawl4ai_used` | +1 | mcp__crawl4ai__* tools (preferred web scraping) |
| `serena_symbolic` | +1 | serena find_symbol, get_symbols_overview |
| `beads_touch` | +1 | Any `bd` command (task tracking) |
| `mcp_integration` | +1 | PAL, Playwright, Filesystem, Serena MCPs |
| `ops_tool` | +1 | ~/.claude/ops/* scripts |
| `agent_delegation` | +1 | Task tool for delegation |

**Per-turn cap:** Maximum ±15 total change per turn normally. **When below 80% (stasis floor), positive cap raised to +30** to enable faster legitimate recovery.

## False Positive Handling

**⚠️ FP = PRIORITY 0 (Hard Block #14)**

When a reducer fires incorrectly, this is a **bug in framework DNA**. Do NOT dismiss and continue.

**Correct Flow:**
1. Identify why the reducer fired incorrectly
2. Fix the detection logic in `_confidence_reducers.py` or hook
3. Test that the fix works
4. ONLY THEN resume original work

**FORBIDDEN:** Running `fp.py` and immediately continuing without fixing root cause.

**As Claude:**
```bash
# Step 1: Record the FP (restores confidence)
~/.claude/ops/fp.py <reducer_name> "reason"

# Step 2: STOP and fix (MANDATORY - do not skip)
# Read the reducer, understand why it fired, fix the logic
```

**As User:**
Say `FP: <reducer_name>` or `dispute <reducer_name>`

### Adaptive Cooldowns

Each FP recorded increases the cooldown for that reducer by 50% (max 3x).
This reduces future false triggers over time.

Example: `edit_oscillation` base cooldown is 5 turns.
- 1 FP → 7 turns
- 2 FPs → 10 turns
- 3 FPs → 15 turns (max)

## Hard Blocks

### Pre-Tool Blocks (confidence_tool_gate)
- **< 30%**: All writes blocked (Edit, Write, Bash state changes)
- **< 51%**: Production writes blocked (only scratch allowed)

### Stop Blocks (completion_gate)
- **< 70%**: Cannot claim task "complete", "done", "finished"
- **< 75% with negative trend**: Also blocked (prevents completing while falling)
- Earn confidence through test_pass, build_success, git_explore, or user_ok

## Compounding Penalties (v4.7)

When multiple bad language patterns fire in a single message, penalties compound:

| Violations | Multiplier | Example |
|------------|------------|---------|
| 1 pattern | 1.0x | -8 stays -8 |
| 2 patterns | 1.5x | -16 becomes -24 |
| 3 patterns | 2.0x | -24 becomes -48 |
| 4+ patterns | 3.0x | -32 becomes -96 |

**`surrender_pivot` bypasses rate limiting entirely** - unforgivable behavior gets full penalty every time.

## Escalation Protocol

At < 30% confidence, you MUST use external consultation:

1. `mcp__pal__thinkdeep` - Deep analysis via PAL MCP
2. `mcp__pal__debug` - Debugging analysis
3. `/think` - Problem decomposition
4. `/oracle` - Expert consultation
5. `/research` - Verify with current docs

## SUDO Bypass

Say **SUDO** to bypass confidence gates. Use sparingly - it's logged.

## Key Files

| File | Purpose |
|------|---------|
| `~/.claude/lib/confidence.py` | Core engine, reducers, increasers |
| `~/.claude/ops/fp.py` | Record false positives |
| `~/.claude/hooks/post_tool_use_runner.py` | Applies reducers/increasers |
| `~/.claude/hooks/user_prompt_submit_runner.py` | Dispute detection, tool gates |
| `~/.claude/hooks/pre_tool_use_runner.py` | Tool permission checks |
| `~/.claude/hooks/stop_runner.py` | Completion gate |
| `~/.claude/tmp/confidence_journal.log` | Significant changes log (v4.6) |

## Streak/Momentum System (v4.6)

Consecutive successes earn multiplied rewards:

| Streak | Multiplier |
|--------|------------|
| 2 consecutive | 1.25x |
| 3 consecutive | 1.5x |
| 5+ consecutive | 2.0x |

**Resets to 0** on any reducer firing. Rewards flow states and sustained quality.

## Trajectory Prediction (v4.6)

Functions available to predict confidence trajectory:
- `predict_trajectory(state, planned_edits, planned_bash, turns_ahead)` → warnings dict
- `format_trajectory_warning(trajectory)` → formatted string

Example output:
```
⚠️ Trajectory: 85% → 77% in 3 turns
  • Will drop below stasis floor (80%)
  Recovery options:
    - Run tests (+5 each) - need ~1 passes
    - git status/diff (+10)
```

## Confidence Journal (v4.6)

Significant changes (≥3 points) logged to `~/.claude/tmp/confidence_journal.log`:
```
[2025-01-15 14:32:00] 87→72 (-15): cascade_block
[2025-01-15 14:35:00] 72→82 (+10): git_explore
```

## Philosophy

**You cannot learn between sessions.** The only way to improve behavior is through:
1. External context injection (CLAUDE.md, rules files)
2. Mechanical guardrails (hooks, gates)
3. State persistence (session_state, nudge_history)

The confidence system compensates for your inability to learn by providing external regulation that shapes behavior through mechanical signals rather than self-assessment.
