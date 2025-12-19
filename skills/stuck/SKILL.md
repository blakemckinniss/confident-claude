---
name: stuck
description: "Break out of debugging loops. Forces research before more attempts."
---

# /stuck - Circuit Breaker

**Purpose:** When debugging isn't working, STOP and research before trying again.

## When to Invoke

- Same fix attempted 2+ times without success
- Error message doesn't make sense
- "This should work but doesn't"
- Confidence below 60% during debugging

## Execution Sequence

### Step 1: Document Current State
```
What I tried:
1. [attempt 1]
2. [attempt 2]

What happened:
- [error/behavior]

What I expected:
- [expected behavior]
```

### Step 2: MANDATORY Research (pick at least one)
```bash
# Web search for the error
mcp__crawl4ai__ddg_search "error message + technology"

# External LLM perspective
mcp__pal__debug with full context

# API/library docs
mcp__pal__apilookup "library behavior"
```

### Step 3: Hypothesize Based on Research
Before attempting fix #3:
- State hypothesis from research
- Explain why this attempt will be different

### Step 4: Targeted Fix
Make ONE change based on research findings.

### Step 5: Verify
Run the specific test/check that was failing.

## Behavior Rules

- NO more edits until research is done
- NO "let me try one more thing" without new information
- External input MANDATORY before attempt #3
- If research doesn't help, ASK USER for more context

## Anti-Patterns (what got you here)

- Changing random things hoping something works
- Re-reading same code expecting different understanding
- Making code "cleaner" instead of fixing the bug
- Assuming you know what the error means
