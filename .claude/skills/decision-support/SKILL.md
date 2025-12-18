---
name: decision-support
description: |
  Complex decisions, architecture choices, multi-perspective analysis, risk assessment,
  problem decomposition, thinking through problems, getting second opinions, trade-offs,
  design patterns, technology selection, framework comparison, pros and cons.

  Trigger phrases: should I use X or Y, what's the best approach, help me decide,
  weigh the options, think through this, break this down, devil's advocate,
  second opinion, sanity check, architecture decision, design choice, trade-offs,
  pros and cons, advantages disadvantages, compare options, evaluate alternatives,
  which framework, which library, which database, Redis vs Postgres, React vs Vue,
  monolith vs microservices, REST vs GraphQL, SQL vs NoSQL, when to use,
  is this a good idea, validate my thinking, challenge my assumptions,
  what could go wrong, risk assessment, failure modes, edge cases, gotchas,
  pitfalls, common mistakes, best practices, industry standard, recommended approach,
  expert opinion, experienced perspective, senior developer advice, tech lead input,
  strategic decision, long-term implications, scalability concerns, maintenance burden,
  complexity analysis, cost-benefit, ROI, worth it, overkill, overengineering.
---

# Decision Support

Tools for complex reasoning and multi-perspective analysis.

## Primary Tools

### council.py - Multi-Perspective Analysis
```bash
council.py "<proposal>"
```
Personas: Judge (value), Critic (flaws), Skeptic (assumptions).

### oracle.py - External LLM Consultation
```bash
oracle.py "<question>"
oracle.py --persona judge "<proposal>"
oracle.py --persona critic "<proposal>"
```

### think.py - Problem Decomposition
```bash
think.py "<complex problem>"
```

### PAL MCP
- `mcp__pal__thinkdeep` - Deep investigation
- `mcp__pal__consensus` - Multi-model consensus
- `mcp__pal__challenge` - Challenge assumptions

## Slash Commands
- `/council <proposal>` - Full council
- `/consult <question>` - Oracle
- `/think <problem>` - Decompose
- `/judge`, `/critic`, `/skeptic` - Single perspective

## When to Use What
| Need | Tool |
|------|------|
| Architecture decision | `/council` |
| Quick sanity check | `/judge` |
| Find flaws | `/critic` |
| Risk assessment | `/skeptic` |
| Break down problem | `/think` |
