# Confidence System

## Overview

The confidence system is a **mechanical behavioral regulation system** that prevents:
- Sycophancy (agreeing with users to avoid conflict)
- Reward hacking (claiming success without verification)
- Lazy completion (saying "done" without earning it)
- Self-assessment bias (overestimating correctness)

**Key principle:** Claude cannot accurately judge its own confidence - it's mechanically regulated based on actual signals.

## Location
- **Core module**: `lib/confidence.py`
- **Applied in**: `hooks/post_tool_use_runner.py` (reducers/increasers)
- **Gates in**: `hooks/pre_tool_use_runner.py` (tool permissions)
- **Completion gate**: `hooks/stop_runner.py`

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
**Stasis target**: 80-90% (healthy operation range)

## Reducers (Penalties)

### Base Class
```python
@dataclass
class ConfidenceReducer:
    name: str
    delta: int  # Negative value
    description: str
    cooldown_turns: int = 3

    def should_trigger(self, context: dict, state: SessionState, last_trigger_turn: int) -> bool:
        # Cooldown check first
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        return False  # Override in subclasses
```

### Reducer Categories

**Core reducers** (detect real problems):
- `tool_failure` (-5): Bash exit != 0
- `cascade_block` (-15): Same hook blocks 3+ times
- `sunk_cost` (-20): 3+ consecutive failures
- `user_correction` (-10): User says "wrong", "fix that"
- `edit_oscillation` (-12): Same file edited 3+ times in 5 turns
- `goal_drift` (-8): Activity diverges from original goal

**Bad behavior reducers** (BANNED patterns):
- `backup_file` (-10): Creating .bak, .backup, .old files
- `version_file` (-10): Creating _v2, _new, _copy files
- `markdown_creation` (-8): Creating .md files unnecessarily
- `overconfident_completion` (-15): "100% done", "completely finished"
- `deferral` (-12): "skip for now", "come back later"
- `sycophancy` (-8): "you're absolutely right"

**Micro-penalties** (constant drag):
- `bash-risk` (-1): Any bash command
- `edit-risk` (-1): Any file edit
- `decay` (-1): Natural drift toward uncertainty

## Increasers (Rewards)

**Due diligence rewards**:
- `file_read` (+1): Read tool
- `productive_bash` (+1): ls, pwd, which, tree, stat
- `research` (+2): WebSearch, WebFetch, crawl4ai
- `search_tool` (+2): Grep, Glob, Task
- `lint_pass` (+3): ruff check passes
- `test_pass` (+5): pytest/jest passes
- `build_success` (+5): npm build/cargo build succeeds
- `memory_consult` (+10): Read ~/.claude/memory/ files
- `bead_create` (+10): bd create/update
- `git_explore` (+10): git log/diff/status
- `ask_user` (+20): AskUserQuestion

## Key Functions

```python
# lib/confidence.py
apply_reducers(context, state) -> list[tuple[str, int, str]]
apply_increasers(context, state) -> list[tuple[str, int, str]]
apply_rate_limit(delta) -> int  # Max ±15 per turn
apply_mean_reversion(confidence, state) -> int  # Pulls toward 85%
get_tier_info(confidence) -> tuple[str, str, str]
check_tool_permission(tool, confidence, path) -> tuple[bool, str]
```

## False Positive Handling

```python
# lib/confidence.py
record_false_positive(reducer_name: str, reason: str)
get_adaptive_cooldown(reducer_name: str) -> int  # Increases with FPs
dispute_reducer(reducer_name: str) -> str  # User dispute
```

Each FP recorded increases cooldown by 50% (max 3x original).

## Usage in Hooks

```python
# In post_tool_use_runner.py
from lib.confidence import apply_reducers, apply_increasers

# Check reducers
reductions = apply_reducers(context, state)
for name, delta, reason in reductions:
    state.confidence += delta

# Check increasers  
boosts = apply_increasers(context, state)
for name, delta, reason in boosts:
    state.confidence += delta
```
