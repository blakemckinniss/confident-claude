---
description: 🚨 Critical Fixer - Fix issues from most critical to least based on severity
argument-hint: [scope]
allowed-tools: Bash, Read, Edit, Write, Glob, Grep, Task
---

Fix all issues in priority order from most critical to least.

## Scope

If `$ARGUMENTS` provided, use as focus area. Otherwise, scan the current conversation.

## Priority Sources (scan in order)

### 1. Response Format Sections
Extract severity scores from these markers:
- `💥[severity]` Integration Impact (highest priority)
- `⚠️[severity]` Technical Debt & Risks
- `🦨[severity]` Code Smells & Patterns
- `🏗️[severity]` Architecture Pressure
- `📚[severity]` Documentation Updates

Severity scale: 🔴76-100 | 🟠51-75 | 🟡26-50 | 🟢1-25

### 2. Beads (if present)
Check `bd list --status=open` for tracked issues.

### 3. Inline Markers
Scan changed files for:
- `FIXME:` (critical)
- `TODO:` (medium)
- `XXX:` (low)
- `HACK:` (medium)

## Execution Protocol

### Phase 1: Collect & Rank
1. Extract all issues from sources above
2. Assign numeric severity (use explicit numbers if present, else: 💥=90, ⚠️=70, 🦨=50, 🏗️=40, 📚=20)
3. Sort descending by severity
4. Present ranked list to user before proceeding

### Phase 2: Fix in Order
For each issue (highest severity first):
1. State: "Fixing [severity] [category]: [description]"
2. Diagnose root cause
3. Implement fix
4. Verify fix works
5. Mark as resolved

### Phase 3: Verify
After all fixes:
- Run relevant tests
- Run `void` on modified files
- Confirm no regressions

### Phase 4: Report
```
Fixed (by priority):
🔴 [count] critical issues
🟠 [count] high issues
🟡 [count] medium issues
🟢 [count] low issues

Remaining: [any issues not addressed and why]
```

## Rules
- Never skip a higher-severity issue to fix a lower one
- If blocked on critical issue, escalate immediately (don't proceed to lower items)
- Group related fixes when they touch same file
- Create beads for issues that can't be fixed now: `bd create "[issue]"`
