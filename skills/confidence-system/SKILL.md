---
name: confidence-system
description: |
  Confidence tracking, confidence recovery, false positive, dispute reducer,
  confidence boost, zone change, penalty, reward, stasis, gates, blocks,
  why am I blocked, confidence too low, can't complete, completion gate.

  Trigger phrases: confidence low, recover confidence, false positive, FP,
  dispute reducer, wrong penalty, confidence boost, why blocked, can't edit,
  completion blocked, zone change, penalty, reward, stasis floor, gates,
  confidence system, how to increase confidence, confidence recovery,
  reduce penalty, adaptive cooldown, confidence journal, trajectory.
---

# Confidence System

Understanding and managing the confidence regulation system.

## Current State

Confidence shown in statusline: `💎 98%` or `🟡 65%`

## Zones

| Zone | Range | Emoji | Capabilities |
|------|-------|-------|--------------|
| IGNORANCE | 0-30 | 🔴 | Read only, external LLM MANDATORY |
| HYPOTHESIS | 31-50 | 🟠 | Scratch only, research REQUIRED |
| WORKING | 51-70 | 🟡 | Scratch + git read |
| CERTAINTY | 71-85 | 🟢 | Production with gates |
| TRUSTED | 86-94 | 💚 | Production with warnings |
| EXPERT | 95-100 | 💎 | Maximum freedom |

## Stasis Target: 80-90%

Healthy operation stays in 80-90% range where small penalties balance with small rewards.

## Recovery (When Below 80%)

| Action | Boost |
|--------|-------|
| Read files | +1 each |
| `git status/log/diff` | +10 |
| Read `~/.claude/memory/` | +10 |
| `bd create/update` | +10 |
| Run lints | +3 |
| Run tests | +5 |
| Ask clarifying questions | +20 |

## False Positive Handling

When reducer fires incorrectly:

### As Claude
```bash
~/.claude/ops/fp.py <reducer_name> "reason"
```

### As User
Say `FP: <reducer_name>` or `dispute <reducer_name>`

## Common Reducers

| Reducer | Delta | Trigger |
|---------|-------|---------|
| tool_failure | -5 | Bash exit != 0 |
| user_correction | -10 | "wrong", "fix that" |
| edit_oscillation | -12 | Same file 3x in 5 turns |
| surrender_pivot | -20 | Abandoning user's goal |
| bash-risk | -1 | Any bash command |
| edit-risk | -1 | Any file edit |

## Completion Gate

**Cannot claim "done" if:**
- Confidence < 70%
- Confidence < 75% with negative trend

Earn completion rights through:
- `test_pass` (+5)
- `build_success` (+5)
- `git_explore` (+10)
- `user_ok` (+2)

## SUDO Bypass

User says **SUDO** to bypass gates. Use sparingly.

## Key Files

- `~/.claude/lib/confidence.py` - Core engine
- `~/.claude/ops/fp.py` - Record false positives
- `~/.claude/rules/confidence.md` - Full reference
