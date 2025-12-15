---
name: autonomous-mode
description: |
  Autonomous execution, just do it, fix everything, work independently,
  minimal guidance, auto mode, yes mode, batch operations, parallel work,
  hands-off, self-directed, proactive, initiative.

  Trigger phrases: just do it, go ahead, do what's best, fix everything,
  work autonomously, yes mode, auto mode, minimal guidance, take initiative,
  be proactive, handle it, figure it out, do your thing, run with it,
  batch this, parallel execution, hands off, self-directed.
---

# Autonomous Mode

Patterns for self-directed execution with minimal guidance.

## Autonomous Commands

### /yes - Full Autonomous
```bash
/yes [guidance]
```
Execute what's best for project health and success.

### /doit - Execute Last Discussed
```bash
/doit [clarification]
```
Execute the last discussed action without re-explaining.

### /fix - Fix All Issues
```bash
/fix [scope]
```
Fix all issues, fill gaps, verify work.

## Parallel Execution

### Multiple Beads
When 2+ beads open, spawn parallel agents:
```
Task(prompt="work on bead 1")  # concurrent
Task(prompt="work on bead 2")  # concurrent
```

### Background Agents
```
Task(subagent_type="Explore", run_in_background=true, prompt="...")
Task(subagent_type="Plan", run_in_background=true, prompt="...")
```
Check later with `TaskOutput`.

### Batch Operations
```bash
/orchestrate  # Claude API batch/aggregate tasks
```

## Operator Protocol

**NEVER ask permission for:**
- Reading files
- Running non-destructive commands
- Fixing obvious errors
- Following established patterns

**Replace:**
- "Would you like me to X?" → "Doing: X"
- "Should I proceed?" → Just proceed
- "I can do X" → Do X

## Self-Healing

Framework errors in `~/.claude/` = Priority 0.
Fix before continuing other work.

## Proactive Patterns

### Error Encountered
```
1. Diagnose immediately
2. Fix root cause
3. Verify fix
4. Continue original task
```

### Gap Noticed
```
1. Note in response
2. Fix if quick (<5 min equivalent)
3. Create bead if larger
```

### Dependency Missing
```
1. Check stdlib first
2. Research alternatives
3. Install minimal solution
4. Continue
```

## Guardrails

Even in autonomous mode:
- Confidence system still applies
- Production gates still enforced
- Never abandon user's stated goal
- Ask if genuinely ambiguous
