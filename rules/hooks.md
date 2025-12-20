---
paths: "**/.claude/hooks/**"
---

# Hook Development Guidelines

Rules for developing and maintaining the Whitebox hook system.

## Architecture

```
~/.claude/hooks/
├── pre_tool_use_runner.py       # PreToolUse orchestrator (gates)
├── post_tool_use_runner.py      # PostToolUse orchestrator
├── user_prompt_submit_runner.py # UserPromptSubmit orchestrator (injection)
├── stop_runner.py               # Stop orchestrator (completion gate)
├── session_init.py              # SessionStart handler
├── session_cleanup.py           # SessionEnd handler
├── subagent_stop.py             # SubagentStop handler
├── pre_compact.py               # PreCompact handler
├── statusline.py                # Status bar renderer
│
│   # Core Infrastructure
├── _hook_result.py              # HookResult API (approve/deny/none)
├── _hook_registry.py            # Decorator-based hook registration
├── _config.py                   # Centralized config with hot-reload
├── _cooldown.py                 # Cooldown management (spam prevention)
├── _patterns.py                 # Path patterns (scratch, protected paths)
├── _cache.py                    # Hook result caching
├── _logging.py                  # Hook logging utilities
├── _lib_path.py                 # Library path management
│
│   # Code-Mode Infrastructure (Plan Protocol)
├── _prompt_codemode.py          # Code-mode plan injection
├── _hooks_codemode.py           # Code-mode result handling
│
│   # Thinking & Suggestions
├── _thinking_suggester.py       # Pattern-based capability suggestions from thinking
├── _prompt_suggestions.py       # Prompt-based tool suggestions
├── _pal_mandates.py             # PAL MCP mandate handling
├── _intent_classifier.py        # Intent classification
│
│   # Quality & State
├── _hooks_state.py              # Session state management
├── _hooks_state_reducers.py     # Confidence reducers
├── _hooks_state_increasers.py   # Confidence increasers
├── _hooks_quality.py            # Code quality checks
├── _quality_scanner.py          # Code quality scanning
├── _ast_utils.py                # AST analysis utilities
│
│   # Integration
├── _beads.py                    # Bead/task tracking helpers (bd CLI)
├── _integration.py              # Cross-system integration
└── py                           # Python wrapper script (auto-detects venv)
```

## Hook Registration Pattern

```python
@register_hook("hook_name", "ToolName|OtherTool", priority=50)
def check_hook_name(data: dict, state: SessionState) -> HookResult:
    """Docstring becomes hook description."""
    # Implementation
    return HookResult.approve()  # or .deny(message) or .approve(message)
```

## Priority Ranges

| Range | Category | Examples |
|-------|----------|----------|
| 1-25 | Security | content_gate, security_claim_gate |
| 26-45 | Safety | production_gate, gap_detector |
| 46-54 | Complexity | god_component_gate |
| 55-95 | Quality | deferral_gate, doc_theater_gate |
| 96-100 | Cleanup | Final checks |

## HookResult Options

```python
HookResult.approve()           # Silent pass
HookResult.approve("message")  # Pass with injected message
HookResult.deny("message")     # Block with error message
```

## Bypass Mechanisms

1. **SUDO** - Pre-computed in `run_hooks()`, available via `data.get("_sudo_bypass")`
2. **File markers** - `# LARGE_FILE_OK: reason` as first line
3. **Path exclusions** - Use `is_scratch_path()` from `_patterns.py`

```python
# SUDO bypass (pre-computed once per tool call, not per hook)
if data.get("_sudo_bypass"):
    return HookResult.approve()

# Scratch path bypass
from _patterns import is_scratch_path
if is_scratch_path(file_path):
    return HookResult.none()
```

## State Management

```python
# Session state for cross-hook communication
state.get("key", default)
state.set("key", value)
state.get_file_edit_count(path)  # Track edit frequency
```

## Common Patterns

### Gate Pattern (block bad actions)
```python
if bad_condition:
    return HookResult.deny(f"**BLOCKED**: Reason.\nSay SUDO to bypass.")
return HookResult.approve()
```

### Injection Pattern (add context)
```python
parts = []
if condition_a:
    parts.append("Context A")
if condition_b:
    parts.append("Context B")
return HookResult.approve("\n".join(parts)) if parts else HookResult.approve()
```

### Cooldown Pattern (avoid spam)
```python
from _cooldown import should_run_check

if not should_run_check("check_name", cooldown_seconds=300):
    return HookResult.approve()
```

## Testing Hooks

```bash
# Lint
ruff check ~/.claude/hooks/pre_tool_use_runner.py

# Test specific hook behavior
# Trigger the condition and verify behavior
```

## Code-Mode Plan Protocol

Hooks cannot invoke MCP tools directly. Code-mode generates structured plans that Claude executes.

```
Hook generates plan → Claude executes tools → Results flow back → Next iteration
```

**Key files:**
- `lib/_codemode_planner.py` - Plan generation with ToolCallSpec
- `lib/_codemode_executor.py` - PlanExecutor for structured execution
- `lib/_codemode_interfaces.py` - Schema cache for MCP tool discovery
- `hooks/_prompt_codemode.py` - Plan injection into prompts
- `hooks/_hooks_codemode.py` - Result handling and handoff

**Plan phases:** `NEED_SCHEMAS` → `NEED_TOOLS` → `HAVE_RESULTS` → `DONE`

## Thinking Suggester

Analyzes Claude's thinking blocks to surface relevant tools proactively.

```python
# Pattern → Suggestion mapping in _thinking_suggester.py
(regex_pattern, Suggestion(emoji, title, tools, hint))

# Example: thinking mentions "browser" → Playwright suggestion
```

**Philosophy:** Thinking tokens contain rich intent signal. Proactive suggestion beats reactive correction.

## Important Rules

1. **Never block `.claude/` paths** - Framework must be self-maintainable
2. **Always provide bypass** - SUDO or explicit marker
3. **Keep hooks fast** - They run on every tool call
4. **Avoid side effects** - Hooks should be pure functions
5. **Use cooldowns** - Prevent spam for periodic checks
6. **Document priority** - Add to runner docstring when adding hooks
