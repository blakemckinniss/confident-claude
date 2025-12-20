# Ralph-Wiggum Task Completion System

**Philosophy:** Iteration > Perfection | Failures Are Data | Persistence Wins

Ralph-wiggum ensures tasks are completed fully through sessions until done. No premature "done" claims.

## How It Works

1. **Detection** (priority 15): Prompts are analyzed for implementation signals
2. **Tracking**: Non-trivial tasks activate ralph mode with acceptance criteria
3. **Evidence**: Test/build results accumulate completion confidence
4. **Gate** (priority 35): Stop is blocked until evidence threshold met

## Task Detection

### Activates Ralph (non-trivial)

Keywords: `implement`, `build`, `create`, `develop`, `refactor`, `migrate`, `rewrite`, `integrate`, `setup`, `configure`, `fix bug`, `debug`, `update`, `modify`, `extend`, `enhance`, `improve`, `optimize`

Patterns: `N files`, `multiple`, `across`, `throughout`, `system`, `architecture`, `infrastructure`, `framework`

### Skips Ralph (trivial)

Keywords: `explain`, `what is`, `how does`, `show me`, `list`, `describe`, `help`, `lookup`, `find`, `search`, `read`, `check`, `verify`, `status`, `diff`, `log`

## Completion Confidence

| Evidence | Delta |
|----------|-------|
| test_pass | +25 |
| build_success | +20 |
| lint_pass | +10 |

**Threshold: 80%** required before stop is allowed.

## State Fields

```python
completion_confidence: int = 0      # 0-100%
task_contract: dict = {}            # goal, criteria, evidence_required
completion_evidence: list = []      # accumulated evidence
ralph_mode: str = ""                # "", "auto", "explicit"
ralph_strictness: str = "strict"    # strict, lenient
ralph_nag_budget: int = 2           # warnings before hard block
```

## Escape Hatches

Legitimate exits bypass the gate:
- "I'm stuck/blocked"
- "I can't figure out"
- "Need help/guidance"
- "Escalating to..."
- "I don't know how"

These indicate epistemic humility, not lazy completion.

## User Override

Say **SUDO** to bypass ralph gates (logged).

## Key Files

| File | Purpose |
|------|---------|
| `hooks/_prompt_ralph.py` | Task detection hook |
| `hooks/stop_runner.py` | Completion evidence gate |
| `hooks/_hooks_state_increasers.py` | Evidence accumulation |
| `lib/_session_state_class.py` | State fields |

## Example

```
User: "Implement a new authentication feature with tests"

🎯 Task Tracking Active (ralph-wiggum)
Goal: Implement a new authentication feature with tests
Criteria: Tests pass, Build succeeds
Evidence required before completion.

... work happens ...

[test_pass] → completion_confidence: 25%
[build_success] → completion_confidence: 45%
[test_pass] → completion_confidence: 70%
[test_pass] → completion_confidence: 95%

✅ Evidence threshold met - completion allowed
```
