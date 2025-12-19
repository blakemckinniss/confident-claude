# Stop Hooks

## Overview

12 registered hooks in `stop_runner.py` that run when Claude attempts to complete a response. These enforce quality gates and detect problematic patterns.

## Location
- **File**: `hooks/stop_runner.py`
- **Total hooks**: 12 registered via `@register_hook`
- **Note**: Stop hooks have no matcher (apply to all stop events)

## Hooks by Priority

| Hook | Priority | Purpose |
|------|----------|---------|
| `session_blocks` | 30 | Track session-level blocking issues |
| `dismissal_check` | 40 | Detect dismissive/incomplete responses |
| `completion_gate` | 45 | **Block "done" claims below 70% confidence** |
| `bad_language_detector` | 46 | Detect banned language patterns |
| `good_language_detector` | 47 | Detect positive patterns (for increasers) |
| `verification_theater_detector` | 48 | Detect fake verification claims |
| `stub_detector` | 50 | Detect placeholder implementations |
| `pending_greps` | 70 | Warn about unfinished grep operations |
| `unresolved_errors` | 80 | Block with unresolved errors in session |
| `session_debt_penalty` | 85 | Apply end-of-session confidence penalties |

## Key Hooks Detail

### completion_gate (Priority 45)
**The hard block for lazy completion.**

Blocks if:
- Confidence < 70%
- Confidence < 75% AND negative trend
- Response contains "done", "complete", "finished"

```python
if confidence < 70:
    return HookResult.deny("Cannot claim complete at {confidence}%")
```

### bad_language_detector (Priority 46)
Scans response for BANNED patterns:
- Apologetic: "sorry", "my mistake"
- Sycophantic: "you're absolutely right"
- Overconfident: "100% done", "completely finished"
- Deferral: "skip for now", "come back later"

Triggers confidence reducers for each match.

### good_language_detector (Priority 47)
Scans response for positive patterns:
- Evidence of verification
- Test execution
- Research performed

Triggers confidence increasers for each match.

### stub_detector (Priority 50)
Detects placeholder code in response:
- `pass` statements in new code
- `...` (ellipsis) in function bodies
- `NotImplementedError` in new code
- `TODO` or `FIXME` without resolution

### verification_theater_detector (Priority 48)
Detects fake verification claims:
- "I've verified" without actual verification
- "Tests pass" without running tests
- "Works correctly" without evidence

### unresolved_errors (Priority 80)
Blocks completion if:
- `state.consecutive_failures > 0`
- `state.framework_errors` not empty
- Unresolved tool failures in session

## HookResult in Stop Context

```python
HookResult.approve()       # Allow stop
HookResult.approve("msg")  # Allow + inject reflection
HookResult.deny("msg")     # Block stop, force continuation
```

## Reflection Injection

Stop hooks can inject reflection prompts:
```python
return HookResult.approve("""
⚠️ Before completing:
- Run tests to verify changes
- Check for unresolved errors
""")
```

## Interaction with Confidence

Stop hooks are the final checkpoint:
1. Bad patterns → confidence reducers fire
2. Confidence drops → completion_gate may block
3. Must earn confidence back to complete
