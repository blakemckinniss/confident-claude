# Confidence System

**You cannot judge your own confidence.** It's mechanically regulated based on actual signals.

## Why This Exists

LLMs are prone to:
- **Sycophancy**: Agreeing with users to avoid conflict
- **Reward hacking**: Claiming success without verification
- **Lazy completion**: Saying "done" without earning it
- **Self-assessment bias**: Overestimating own correctness

The confidence system provides **external mechanical regulation** that bypasses self-judgment.

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

| Reducer | Delta | Trigger | Cooldown |
|---------|-------|---------|----------|
| `tool_failure` | -5 | Bash exit code != 0 | 1 turn |
| `cascade_block` | -15 | Same hook blocks 3+ times in 5 turns | 5 turns |
| `sunk_cost` | -20 | 3+ consecutive failures on same approach | 5 turns |
| `user_correction` | -10 | User says "wrong", "incorrect", "fix that", etc. | 3 turns |
| `edit_oscillation` | -12 | Same file edited 3+ times in 5 turns | 5 turns |
| `goal_drift` | -8 | < 20% keyword overlap with original goal | 8 turns |
| `contradiction` | -10 | Contradictory claims detected | 5 turns |

## Increasers (Automatic Rewards)

| Increaser | Delta | Trigger | Auto? |
|-----------|-------|---------|-------|
| `test_pass` | +5 | pytest/jest/cargo test passes | Yes |
| `build_success` | +5 | npm build/cargo build/tsc succeeds | Yes |
| `user_ok` | +5 | Short positive response ("good", "ok", "yes", "thanks") | Yes |
| `trust_regained` | +15 | User says "trust regained" or "CONFIDENCE_BOOST_APPROVED" | Requires approval |

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
- **< 85%**: Cannot claim task "complete", "done", "finished"
- Must earn confidence through test_pass, build_success, or user_ok

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
