---
name: implementation-planning
description: |
  Plan implementation, best approach, how to implement, worth building,
  implementation strategy, research before coding, optimal approach,
  technology selection, library comparison, build vs buy, existing solutions.

  Trigger phrases: how should I implement, best way to, what's the best approach,
  how would you implement, implementation plan, worth building, should I build,
  research this, optimal approach, recommended way, best practice for,
  compare libraries, which library, build vs buy, existing solution,
  implementation strategy, technical approach, architecture for.
---

# Implementation Planning

Tools for planning implementations before coding.

## Research First

### /imp - Implementation Research
```bash
/imp <tool/feature/pattern>
```
Researches optimal setup for X in current project.

### /bestway - Approach Evaluation
```bash
/bestway "<question>"
```
Evaluates optimal approaches for implementing X.

### /wcwd - Implementation Brainstorm
```bash
/wcwd "<feature>" in "<system>"
```
Explores options for implementing X in Y.

## Worth Assessment

### /worth - Value Check
```bash
/worth <feature/tool/dependency>
```
Is X worth adding to this project?

### /opt - Optimality Check
```bash
/opt "<proposal>"
```
Is X the best choice for this project?

### /roi - ROI Analysis
```bash
/roi [context]
```
Implements highest-value concepts by impact/effort ratio.

## Build vs Buy

**Before implementing, ask:**
1. Does this already exist?
2. Is there a library/tool for this?
3. What's the maintenance burden?

```bash
/worth "<feature>"           # Value assessment
research.py "<feature> library"  # Find existing
```

## Planning Flow

1. **Research** - `/imp <feature>` or `/research "<topic>"`
2. **Evaluate** - `/bestway "<approach>"` or `/worth "<dep>"`
3. **Decide** - `/opt "<proposal>"` or `/council "<decision>"`
4. **Plan** - Break into beads with `bd create`
5. **Execute** - Implement with verification

## Task Tool Agents

For complex planning:
```
Task(subagent_type="Plan", prompt="Design implementation for X")
```

## PAL Planning

```
mcp__pal__planner  # Interactive sequential planning
```

## Anti-Patterns

- Starting code without research
- Adding deps without checking stdlib
- Building custom when library exists
- No verification plan before implementing
