---
name: external-llm
description: |
  External LLM consultation, PAL MCP, multi-model consensus, second opinion,
  deep analysis, Groq, OpenRouter, external AI, model comparison, reasoning,
  think deeper, get another perspective, validate thinking, expert consultation.

  Trigger phrases: ask another model, get second opinion, use GPT, use Gemini,
  consult external, deep analysis, think deeper, validate with another AI,
  multi-model, consensus, what does GPT think, external consultation,
  PAL tools, groq, openrouter, expert model, reasoning model, thinking model,
  challenge my thinking, different perspective, sanity check with AI,
  code review by AI, external code review, model comparison.
---

# External LLM Consultation

Tools for consulting external AI models.

## PAL MCP Tools (Primary)

### Deep Investigation
```
mcp__pal__thinkdeep
```
Multi-stage investigation for complex problems.

### Code Review
```
mcp__pal__codereview
```
Systematic code review with expert validation.

### Debugging
```
mcp__pal__debug
```
Root cause analysis with hypothesis testing.

### Multi-Model Consensus
```
mcp__pal__consensus
```
Consult multiple models for complex decisions.

### Challenge Assumptions
```
mcp__pal__challenge
```
Force critical thinking when questioned.

### API Lookup
```
mcp__pal__apilookup
```
Current documentation and version info.

### General Chat
```
mcp__pal__chat
```
Brainstorming and second opinions.

## Slash Commands

| Command | Purpose |
|---------|---------|
| `/consult <q>` | Oracle consultation |
| `/oracle --persona X` | Specific perspective |
| `/groq <query>` | Fast Groq inference |
| `/swarm <task>` | Parallel multi-agent |

## When to Use External

- **Confidence < 30%** - MANDATORY external consultation
- **Complex architecture** - Multi-model consensus
- **Unfamiliar domain** - API lookup + expert chat
- **Debugging stuck** - External debug analysis
- **Code review** - External code review

## Model Selection

```
mcp__pal__listmodels  # See available models
```

Top models:
- `google/gemini-3-pro-preview` - 1M context, thinking
- `openai/gpt-5-pro` - 400K context, thinking
- `openai/gpt-5.1` - 400K context, thinking

## Cost Awareness

**Expensive tools (use sparingly):**
- `/swarm` - Burns OpenRouter credits
- `/oracle` - External API calls
- `/orchestrate` - Claude API code_execution

**Free/cheap:**
- PAL MCP tools (included)
- `/groq` (fast, cheap)
