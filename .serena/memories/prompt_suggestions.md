# Prompt Suggestions System

## Overview

The `_prompt_suggestions.py` module contains ~18 suggestion functions that inject contextual help into user prompts. These run during UserPromptSubmit and provide proactive guidance.

## Location
- **File**: `hooks/_prompt_suggestions.py`
- **Called from**: `hooks/user_prompt_submit_runner.py`
- **Execution**: Functions called in priority order, suggestions collected and injected

## Suggestion Functions

### Task Management
| Function | Purpose |
|----------|---------|
| `check_beads_periodic_sync` | Remind to sync beads periodically |
| `check_self_heal_diagnostic` | Suggest self-heal when framework errors detected |

### Proactive Nudges
| Function | Purpose |
|----------|---------|
| `check_proactive_nudge` | Collect and inject proactive suggestions |
| `check_agent_suggestion` | Suggest appropriate Task agents for the task |
| `check_skill_suggestion` | Suggest relevant skills to invoke |
| `check_ops_nudge` | Suggest ops tools (audit, void, etc.) |
| `check_ops_awareness` | Inject awareness of available ops tools |
| `check_ops_audit_reminder` | Remind about audit requirements |

### Intelligence
| Function | Purpose |
|----------|---------|
| `check_intent_classifier` | Classify user intent and tailor suggestions |
| `check_expert_probe` | Inject expert-level probing questions |
| `check_pal_mandate` | Handle PAL MCP mandates |

### Resource Matching
| Function | Purpose |
|----------|---------|
| `check_resource_pointer` | Point to relevant files/folders based on keywords |

### Quality Patterns
| Function | Purpose |
|----------|---------|
| `check_work_patterns` | Detect and inject work pattern suggestions |
| `check_quality_signals` | Inject quality signal reminders |
| `check_response_format` | Remind about response format requirements |

## Helper Functions

```python
_collect_proactive_suggestions(state) -> list[str]
    # Aggregates suggestions from various sources

_collect_expert_probes(prompt_lower, turn_count) -> list[str]
    # Generates expert-level follow-up questions

_match_folders(kw_set) -> list[str]
    # Match keywords to relevant folders

_match_tools(kw_set) -> list[str]
    # Match keywords to relevant tools
```

## Integration Pattern

```python
# In user_prompt_submit_runner.py
def main():
    suggestions = []
    
    for check_func in SUGGESTION_FUNCTIONS:
        result = check_func(data, state)
        if result.message:
            suggestions.append(result.message)
    
    if suggestions:
        inject_context("\n".join(suggestions))
```

## Suggestion Output Format

Suggestions are injected as system reminders:
```
<system-reminder>
UserPromptSubmit hook additional context:
📋 Consider using /audit for code quality
🔧 Ops tools available: void, gaps, drift
</system-reminder>
```

## Priority-Based Execution

Suggestions execute in priority order (defined in module):
1. Self-heal diagnostics (highest)
2. Intent classification
3. Resource pointers
4. Agent/skill suggestions
5. Ops nudges
6. Quality signals
7. Response format (lowest)

## Cooldowns

Many suggestions use cooldowns to prevent spam:
```python
if state.should_nudge("ops_awareness", content):
    state.record_nudge("ops_awareness", content)
    return HookResult.approve(suggestion)
```

## Agent Suggestion Logic

`check_agent_suggestion` matches prompt patterns to agents:
- "explore" / "find" → Explore agent
- "plan" / "design" → Plan agent
- "debug" / "error" → error-debugging:debugger agent
- "review" / "audit" → code-refactoring:code-reviewer agent
