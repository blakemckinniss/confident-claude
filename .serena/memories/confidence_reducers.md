# Confidence Reducers

## Overview

Reducers are penalty mechanisms that decrease confidence based on detected problems. They fire automatically when patterns match, with cooldowns to prevent spam.

## Location
- **Definition**: `lib/_confidence_reducers.py`
- **Applied in**: `hooks/post_tool_use_runner.py`

## Core Reducers (Real Problems)

| Reducer | Delta | Trigger | Cooldown |
|---------|-------|---------|----------|
| `tool_failure` | -5 | Bash exit code != 0 | 1 turn |
| `cascade_block` | -15 | Same hook blocked 3+ times recently | 5 turns |
| `sunk_cost` | -20 | 3+ consecutive failures on same approach | 5 turns |
| `user_correction` | -10 | User says "wrong", "incorrect", "fix that" | 3 turns |
| `goal_drift` | -8 | Activity diverged from original goal (<20% keyword overlap) | 8 turns |
| `edit_oscillation` | -12 | Edits reverting previous changes (back-forth pattern) | 5 turns |
| `contradiction` | -10 | Made contradictory claims | 5 turns |
| `follow_up_question` | -5 | User asked follow-up question (answer incomplete) | 3 turns |

## Bad Behavior Reducers (BANNED Patterns)

| Reducer | Delta | Trigger | Cooldown |
|---------|-------|---------|----------|
| `backup_file` | -10 | Creating .bak, .backup, .old files | 1 turn |
| `version_file` | -10 | Creating _v2, _new, _copy files | 1 turn |
| `markdown_creation` | -8 | Creating .md files (documentation theater) | 1 turn |
| `overconfident_completion` | -15 | "100% done", "completely finished" | 3 turns |
| `deferral` | -12 | "skip for now", "come back later" | 3 turns |
| `apologetic` | -5 | "sorry", "my mistake", "I apologize" | 2 turns |
| `sycophancy` | -8 | "you're absolutely right", "great point" | 2 turns |
| `unresolved_antipattern` | -10 | Identified anti-pattern without resolution | 3 turns |
| `spotted_ignored` | -15 | Explicitly spotted issue but didn't fix it | 3 turns |
| `debt_bash` | -10 | Ran debt-creating bash (--force, --hard, --no-verify) | 1 turn |
| `large_diff` | -8 | Large diff (>400 LOC) - risky change | 1 turn |

## Micro-Penalties (Constant Drag)

| Reducer | Delta | Trigger | Cooldown |
|---------|-------|---------|----------|
| `bash-risk` | -1 | Any bash command (state change risk) | None |
| `edit-risk` | -1 | Any file edit | None |
| `decay` | -1 | Natural drift toward uncertainty | None |

## Class Structure

```python
@dataclass
class ConfidenceReducer:
    name: str
    delta: int  # Negative value
    description: str
    cooldown_turns: int = 3

    def should_trigger(self, context: dict, state: SessionState, last_trigger_turn: int) -> bool:
        # Cooldown check + specific trigger logic
        pass
```

## Key Detection Patterns

### tool_failure
Checks `context.get("exit_code", 0) != 0`

### cascade_block
Checks `state.consecutive_blocks[hook_name].count >= 3`

### sunk_cost
Checks `state.consecutive_failures >= 3`

### user_correction
Pattern matches: `wrong|incorrect|fix that|no,|actually,|that's not`

### goal_drift
Computes keyword overlap between `state.goal_keywords` and current activity

### edit_oscillation
Checks `state.edit_counts[file] >= 3` within 5 turns

## Compounding

Multiple reducers in one turn compound penalties:
- 2 patterns = 1.5x multiplier
- 3 patterns = 2.0x multiplier
- 4+ patterns = 3.0x multiplier

## Adaptive Cooldowns

Each false positive recorded increases cooldown by 50% (max 3x):
- Base: 5 turns → 1 FP: 7 turns → 2 FPs: 10 turns → 3 FPs: 15 turns
