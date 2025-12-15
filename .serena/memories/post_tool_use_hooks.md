# Post Tool Use Hooks

## Overview

23 hooks in `post_tool_use_runner.py` that process tool output. Unlike PreToolUse, these run AFTER tool execution and cannot block - they observe, track, and inject context.

## Architecture

The runner imports hooks from 4 modular files:
```
post_tool_use_runner.py  (orchestrator)
├── _hooks_cache.py      (priority 5-6)     - 3 hooks
├── _hooks_state.py      (priority 10-16)   - 5 hooks
├── _hooks_quality.py    (priority 22-50)   - 10 hooks
└── _hooks_tracking.py   (priority 55-72)   - 5 hooks
```

## Performance

- **Target**: ~40ms for all hooks
- **Design**: Single state load/save, pre-sorted by priority
- **Warning**: Logs to stderr if >100ms

## Hooks by Module

### Cache Hooks (`_hooks_cache.py`) - Priority 5-6

| Hook | Matcher | Priority | Purpose |
|------|---------|----------|---------|
| `exploration_cacher` | Task | 5 | Cache exploration agent results |
| `read_cacher` | Read | 6 | Cache file read results |
| `read_cache_invalidator` | Write\|Edit | 6 | Invalidate cache when files change |

### State Hooks (`_hooks_state.py`) - Priority 10-16

| Hook | Matcher | Priority | Purpose |
|------|---------|----------|---------|
| `state_updater` | None | 10 | Track files read/edited, commands, libraries, errors |
| `confidence_decay` | None | 11 | Natural decay + tool-specific boosts (context-scaled) |
| `confidence_reducer` | None | 12 | Apply deterministic confidence reductions on failures |
| `confidence_increaser` | None | 14 | Apply confidence increases on success signals |
| `thinking_quality_boost` | None | 16 | Reward good reasoning (evidence, verification, diagnosis) |

### Quality Hooks (`_hooks_quality.py`) - Priority 22-50

| Hook | Matcher | Priority | Purpose |
|------|---------|----------|---------|
| `assumption_check` | Edit\|Write | 22 | Surface hidden assumptions in code changes |
| `verification_reminder` | Edit\|Write\|MultiEdit | 25 | Remind to verify after fix iterations |
| `ui_verification_gate` | Edit\|Write\|MultiEdit | 30 | Remind to screenshot after CSS/UI changes |
| `code_quality_gate` | Edit\|Write | 35 | Detect anti-patterns (N+1, O(n³), blocking I/O, nesting) |
| `quality_scanner` | Edit\|Write | 36 | Run ruff + radon on edited files |
| `state_mutation_guard` | Edit\|Write | 37 | Detect React/Python mutation anti-patterns |
| `dev_toolchain_suggest` | Edit\|Write | 40 | Suggest lint/format/typecheck per language |
| `large_file_helper` | Read | 45 | Line range guidance for big files |
| `crawl4ai_promo` | WebFetch | 48 | Promote crawl4ai over WebFetch for web content |
| `tool_awareness` | Read\|Bash\|Task | 50 | Remind about Playwright, Zen MCP, WebSearch, agents |

### Tracking Hooks (`_hooks_tracking.py`) - Priority 55-72

| Hook | Matcher | Priority | Purpose |
|------|---------|----------|---------|
| `scratch_enforcer` | None | 55 | Detect repetitive patterns, suggest scripts |
| `auto_learn` | None | 60 | Capture lessons from errors, quality hints |
| `velocity_tracker` | Read\|Edit\|Write\|Bash\|Glob\|Grep | 65 | Detect oscillation/spinning patterns |
| `info_gain_tracker` | None | 70 | Detect reads without progress |
| `beads_auto_sync` | Bash | 72 | Auto-sync beads on git commits |

## Key Hook Details

### state_updater (Priority 10)
Central state tracking - updates:
- `state.files_read` / `state.files_edited` / `state.files_created`
- `state.edit_counts[file]` - for oscillation detection
- `state.commands_run` - bash history
- `state.libraries_detected` - import tracking
- `state.errors_detected` - failure tracking

### confidence_decay (Priority 11)
Applies natural confidence decay:
- Base decay: -1 per turn
- Context-scaled: Higher decay at high confidence
- Tool boosts: +1 for productive tools (Read, Grep, etc.)

### confidence_reducer (Priority 12)
Checks all reducers from `lib/_confidence_reducers.py`:
- tool_failure, cascade_block, sunk_cost, etc.
- Applies cooldowns and compounding
- Logs significant changes to journal

### confidence_increaser (Priority 14)
Checks all increasers from `lib/_confidence_increasers.py`:
- test_pass, build_success, file_read, etc.
- Applies rate limiting (+15 cap, +30 in recovery)
- Updates streak counter

### code_quality_gate (Priority 35)
Detects anti-patterns in edited code:
- N+1 queries (loop with DB call)
- O(n³) complexity (triple nested loops)
- Blocking I/O in async
- Deep nesting (>4 levels)
- God components (>500 lines)

### quality_scanner (Priority 36)
Runs static analysis on edited files:
- `ruff check` for linting
- `radon cc` for complexity
- Reports issues as context injection

### velocity_tracker (Priority 65)
Detects spinning/oscillation:
- Same file edited 3+ times in 5 turns
- Same error repeated
- Back-and-forth changes

Suggests: `think` command, step back, different approach

### info_gain_tracker (Priority 70)
Detects reads without progress:
- Many file reads without edits
- Grep/Glob spam
- No forward motion

Suggests: Focus on specific goal, stop exploring

## Runner State

Hooks share runner-specific state via `runner_state` dict:
```python
runner_state["scratch_state"]    # Repetitive pattern tracking
runner_state["info_gain_state"]  # Read-without-progress tracking
```

Persisted to:
- `~/.claude/cache/scratch_state.json`
- `~/.claude/cache/info_gain_state.json`

## HookResult in PostToolUse

```python
HookResult.approve()           # Silent (no injection)
HookResult.approve("context")  # Inject context message
# Note: deny() has no effect in PostToolUse - tools already ran
```

## Adding New Hooks

1. Choose appropriate module by category
2. Add function with `@register_hook` decorator
3. Assign priority in correct range
4. Return `HookResult.approve()` or `.approve(message)`
5. Update runner docstring with hook documentation
