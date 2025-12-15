# Pre Tool Use Hooks

## Overview

38 registered hooks in `pre_tool_use_runner.py` that gate tool execution. These run BEFORE a tool executes and can block or modify the action.

## Location
- **File**: `hooks/pre_tool_use_runner.py`
- **Total hooks**: 38 registered via `@register_hook`

## Hooks by Category

### Caching & Performance (Priority 2-4)
| Hook | Matcher | Priority | Purpose |
|------|---------|----------|---------|
| `read_cache` | Read | 2 | Cache file reads to prevent redundant I/O |
| `self_heal_enforcer` | None | 2 | Force framework error fixes |
| `exploration_cache` | Task | 3 | Cache exploration results |
| `parallel_bead_delegation` | Task | 3 | Delegate bead work to agents |
| `parallel_nudge` | Task | 4 | Nudge toward parallel Task spawns |
| `beads_parallel` | Bash | 4 | Parallel bead operations |
| `bead_enforcement` | Edit\|Write | 4 | Require in_progress bead for edits |

### Recursion & Safety (Priority 5-15)
| Hook | Matcher | Priority | Purpose |
|------|---------|----------|---------|
| `recursion_guard` | Edit\|Write\|Bash | 5 | Prevent recursive/runaway operations |
| `loop_detector` | Bash | 10 | Detect bash command loops |
| `python_path_enforcer` | Bash | 12 | Enforce correct Python path |
| `script_nudge` | Bash | 14 | Suggest scripts over manual commands |
| `background_enforcer` | Bash | 15 | Enforce background for slow commands |

### Confidence Gates (Priority 18-32)
| Hook | Matcher | Priority | Purpose |
|------|---------|----------|---------|
| `confidence_tool_gate` | None | 18 | Block writes below confidence threshold |
| `probe_gate` | Bash | 18 | Gate probe commands |
| `commit_gate` | Bash | 20 | Gate git commits |
| `tool_preference` | Bash\|TodoWrite | 25 | Prefer native tools over bash |
| `hf_cli_redirect` | Bash | 26 | Redirect HuggingFace CLI |
| `oracle_gate` | Edit\|Write\|Bash | 30 | Gate production actions |
| `confidence_external_suggestion` | None | 32 | Suggest external LLM consultation |

### Quality Gates (Priority 35-55)
| Hook | Matcher | Priority | Purpose |
|------|---------|----------|---------|
| `integration_gate` | Edit\|Write\|Task | 35 | Require integration check |
| `error_suppression_gate` | Edit\|Write\|MultiEdit\|Task | 40 | Block error suppression patterns |
| `content_gate` | Edit\|Write | 45 | Content quality checks |
| `crawl4ai_preference` | WebFetch | 47 | Prefer crawl4ai over WebFetch |
| `god_component_gate` | Edit\|Write | 48 | Block overly complex components |
| `gap_detector` | Edit\|Write | 50 | Detect implementation gaps |
| `production_gate` | Write\|Edit | 55 | Gate production file writes |

### Content Quality (Priority 60-95)
| Hook | Matcher | Priority | Purpose |
|------|---------|----------|---------|
| `deferral_gate` | Edit\|Write\|MultiEdit | 60 | Block deferral language |
| `doc_theater_gate` | Write | 65 | Block documentation theater |
| `root_pollution_gate` | Edit\|Write | 70 | Block home directory pollution |
| `recommendation_gate` | Write | 75 | Block unrequested recommendations |
| `security_claim_gate` | Edit\|Write | 80 | Gate security claims |
| `epistemic_boundary` | Edit\|Write | 85 | Enforce epistemic boundaries |
| `research_gate` | Edit\|Write | 88 | Require research before unfamiliar libs |
| `import_gate` | Write | 92 | Gate import additions |
| `modularization_nudge` | Edit\|Write | 95 | Suggest modularization |

### Meta-cognition (Priority 80-90)
| Hook | Matcher | Priority | Purpose |
|------|---------|----------|---------|
| `sunk_cost_detector` | None | 80 | Detect sunk cost fallacy |
| `thinking_coach` | None | 90 | Suggest structured thinking |

## HookResult Actions

```python
HookResult.approve()       # Allow tool to proceed
HookResult.approve("msg")  # Proceed + inject context
HookResult.deny("msg")     # Block tool with message
HookResult.none()          # Skip this hook
```

## SUDO Bypass

All gates can be bypassed with `SUDO` in user message:
```python
if data.get("_sudo_bypass"):
    return HookResult.approve()
```

## Priority Ranges

| Range | Category |
|-------|----------|
| 1-10 | Caching, critical safety |
| 11-25 | Bash safety, tool preference |
| 26-50 | Confidence gates, quality |
| 51-75 | Content quality, production |
| 76-100 | Meta-cognition, final checks |
