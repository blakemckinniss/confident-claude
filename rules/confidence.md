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
| `bash-risk` | -1 | Any bash command (state change risk) | None |
| `edit-risk` | -1 | Any file edit | None |
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

**Code quality reducers (v4.4):**

| Reducer | Delta | Trigger | Cooldown |
|---------|-------|---------|----------|
| `placeholder_impl` | -8 | `pass`, `...`, NotImplementedError in new code | 1 turn |
| `silent_failure` | -8 | `except: pass` or `except Exception: pass` | 1 turn |
| `hallmark_phrase` | -3 | AI-speak: "certainly", "I'd be happy to" | 2 turns |
| `scope_creep` | -8 | "while I'm at it", "might as well", "let's also" | 3 turns |
| `incomplete_refactor` | -10 | Partial renames/changes (context-based) | 3 turns |

## Increasers (Automatic Rewards)

**Due diligence rewards balance natural decay:**

| Increaser | Delta | Trigger |
|-----------|-------|---------|
| `file_read` | +1 | Read tool (gathering evidence) |
| `productive_bash` | +1 | ls, pwd, which, tree, stat (inspection) |
| `research` | +2 | WebSearch, WebFetch, crawl4ai |
| `search_tool` | +2 | Grep, Glob, Task (understanding) |
| `rules_update` | +3 | Edit CLAUDE.md or /rules/ |
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

**Per-turn cap:** Maximum +15 or -15 total change per turn (prevents death spirals and gaming).

## False Positive Handling

When a reducer fires incorrectly:

**As Claude:**
```bash
~/.claude/ops/fp.py <reducer_name> "reason"
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
- **< 80%**: Cannot claim task "complete", "done", "finished"
- Must be in stasis range (80-90%) to claim completion
- Earn confidence through test_pass, build_success, git_explore, or user_ok

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

## Philosophy

**You cannot learn between sessions.** The only way to improve behavior is through:
1. External context injection (CLAUDE.md, rules files)
2. Mechanical guardrails (hooks, gates)
3. State persistence (session_state, nudge_history)

The confidence system compensates for your inability to learn by providing external regulation that shapes behavior through mechanical signals rather than self-assessment.
