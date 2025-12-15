---
name: debugging
description: |
  Debug errors, fix bugs, diagnose issues, stack traces, error messages, exceptions,
  console errors, runtime errors, build failures, test failures, crash analysis,
  root cause analysis, troubleshooting, why isn't this working, error hunting.

  Trigger phrases: debug this, fix this error, why is this failing, stack trace,
  error message, exception, crash, not working, broken, investigate bug,
  root cause, diagnose, troubleshoot, console error, runtime error, build error,
  test failing, assertion failed, undefined is not, null pointer, type error,
  syntax error, import error, module not found, cannot read property,
  segmentation fault, memory leak, infinite loop, race condition, deadlock,
  what went wrong, find the bug, track down, hunt down the issue.
---

# Debugging

Tools for diagnosing and fixing errors.

## Primary Tools

### PAL Debug - External Analysis
```bash
mcp__pal__debug  # Systematic root cause analysis
```

### /f - Quick Console Fix
```bash
/f "<error description>"
```
Diagnoses browser console errors and suggests fixes.

### think.py - Problem Decomposition
```bash
think.py "Debug: <symptom description>"
```

## Debugging Flow

1. **Reproduce** - Get exact error message/stack trace
2. **Isolate** - Find minimal reproduction
3. **Trace** - Follow data flow to root cause
4. **Fix** - Apply targeted fix
5. **Verify** - Confirm fix resolves issue

## Common Patterns

### Stack Trace Analysis
```bash
# Find error origin
xray.py --type function --name "<function from trace>" <path>

# Check callers
grep -r "<function_name>" --include="*.py"
```

### Build/Test Failures
```bash
# Run with verbose output
npm run build 2>&1 | head -50
pytest -v --tb=long <test_file>

# Check recent changes
git diff HEAD~3 -- <failing_file>
```

### Runtime Errors
```bash
# Inspect object at runtime
probe.py "<module.object>"

# Check types/values
xray.py --type class --name "<ClassName>" <path>
```

## Three-Strike Rule

After 2 consecutive failures:
```bash
think.py "Debug: <problem description>"
```
MANDATORY before attempt #3.

## When to Escalate

- Complex multi-file issues → `mcp__pal__debug`
- Unfamiliar domain → `/research "<technology> debugging"`
- Mysterious behavior → `/think "Why would <X> cause <Y>"`
