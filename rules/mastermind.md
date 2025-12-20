# Mastermind: Multi-Model Orchestration

Intelligent task routing using external LLMs for classification, planning, and drift detection.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                      User Prompt                                │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  Groq Router (Kimi K2) - Fast Classification (~100ms)           │
│  • trivial/medium/complex                                       │
│  • task_type: debugging|planning|review|architecture|...        │
│  • suggested_tool: debug|planner|codereview|consensus|...       │
│  • Risk lexicon override (security, auth, deploy → complex)     │
└─────────────────────────────────────────────────────────────────┘
                              │
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
         ┌────────┐     ┌─────────┐     ┌─────────┐
         │trivial │     │ medium  │     │ complex │
         │        │     │         │     │         │
         │ Direct │     │ PAL     │     │ GPT-5.2 │
         │ exec   │     │ suggest │     │ Blueprint│
         └────────┘     └─────────┘     └─────────┘
                              │               │
                              ▼               ▼
┌─────────────────────────────────────────────────────────────────┐
│  Claude Execution with Injected Context                         │
│  • Classification info shown in prompt                          │
│  • Blueprint steps for complex tasks                            │
│  • Drift detection monitors execution                           │
└─────────────────────────────────────────────────────────────────┘
```

## Task Classification

### Classification Levels

| Level | Description | Handling |
|-------|-------------|----------|
| `trivial` | Single-file changes, lookups, explanations | Direct execution |
| `medium` | Multi-file changes, moderate refactoring | PAL tool suggestion |
| `complex` | New systems, architecture, security-sensitive | Full blueprint |

### Task Types

| Type | Suggested Tool | Use Cases |
|------|----------------|-----------|
| `debugging` | `mcp__pal__debug` | Bug investigation, error tracing, fix attempts |
| `planning` | `mcp__pal__planner` | New features, implementation design, multi-step |
| `review` | `mcp__pal__codereview` | Code review, quality check, refactoring |
| `architecture` | `mcp__pal__consensus` | System design, technology choices, tradeoffs |
| `research` | `mcp__pal__apilookup` | API lookups, documentation, library usage |
| `validation` | `mcp__pal__precommit` | Pre-commit checks, change verification |
| `general` | `mcp__pal__chat` | Discussion, brainstorming, unclear category |

### Risk Lexicon Override

Certain keywords **always escalate to complex** regardless of router decision:

- Security: `security`, `auth`, `password`, `credential`, `secret`, `api key`, `token`, `encrypt`, `vulnerability`, `injection`
- Operations: `production`, `deploy`, `migration`, `rollback`
- Destructive: `delete all`, `drop table`, `rm -rf`, `sudo`

## Rollout Phases

| Phase | Behavior | Use Case |
|-------|----------|----------|
| 0 | Dark launch - logs decisions, no injection | Testing/validation |
| 1 | Explicit override only (`^` prefix triggers) | Conservative rollout |
| 2 | Auto-planning for complex tasks | Production-ready |
| 3 | Full auto-planning with drift detection | **Current** |

Change phase: `~/.claude/ops/mastermind_rollout.py --phase N`

## User Override

Prefix any prompt with `^` to force complex planning:

```
^Refactor the authentication system
```

This bypasses classification and immediately generates a full blueprint.

## Capability Registry

### Structure

```
~/.claude/capabilities/
├── registry.yaml           # Master capability catalog (YAML)
├── capabilities_index.json # Auto-generated JSON index
└── tag_vocab.json          # Controlled tag vocabulary
```

### Capability Types

| Type | ID Prefix | Example |
|------|-----------|---------|
| Agents | `agent__` | `agent__explore`, `agent__deep_security` |
| MCP Tools | `mcp__` | `mcp__pal__debug`, `mcp__serena__find_symbol` |
| Ops Scripts | `ops__` | `ops__audit`, `ops__void` |
| Slash Commands | `cmd__` | `cmd__commit`, `cmd__research` |

### Capability Metadata

Each capability includes:

```yaml
- id: agent__explore
  name: Explore
  summary: "Fast codebase exploration"
  stages: [locate, analyze]           # When in pipeline
  tags: [code_reading, semantic_search]
  cost: { price_tier: low, latency_tier: low }
  risk: { writes_repo: false, network: false }
  scope: repo                         # repo|web|local_machine|external_api
  family_id: family__semantic_code_search
```

### Stages

Capabilities are organized by pipeline stage:

| Stage | Purpose | Example Tools |
|-------|---------|---------------|
| `triage` | Initial assessment | Groq router, repomix |
| `locate` | Find relevant code/files | serena, grep, glob |
| `analyze` | Understand code/problem | PAL debug, explore agent |
| `modify` | Make changes | serena replace, edit |
| `validate` | Verify changes | tests, lint, precommit |
| `report` | Document/summarize | PAL chat, memory |

## Drift Detection

Monitors for mid-session divergence from blueprints:

### Triggers

| Trigger | Threshold | Action |
|---------|-----------|--------|
| File count | 5+ new files touched | Warning |
| Test failures | 3+ consecutive | Escalation |
| Approach change | Detected pivot | Warning + suggest re-plan |

### Configuration

```json
{
  "drift_detection": {
    "enabled": true,
    "file_count_trigger": 5,
    "test_failure_trigger": 3,
    "approach_change_detection": true,
    "cooldown_turns": 10,
    "max_escalations_per_session": 2
  }
}
```

## Context Packing

Router and planner receive packed context with token budgets:

| Component | Budget | Includes |
|-----------|--------|----------|
| Router | 1200 tokens | Task + key context |
| Planner | 4000 tokens | Full context for blueprint |

Context includes:
- Repository structure (if enabled)
- Git diff (staged/unstaged)
- Active beads
- Test status
- Serena context (if active)

## Telemetry

Decisions logged to `~/.claude/tmp/mastermind/`:

```json
{
  "session_id": "abc123",
  "timestamp": "2025-01-15T10:30:00Z",
  "prompt_hash": "...",
  "classification": "complex",
  "confidence": 0.85,
  "task_type": "debugging",
  "suggested_tool": "debug",
  "reason_codes": ["multi_file", "bug_fix"],
  "latency_ms": 95
}
```

## Configuration Reference

`~/.claude/config/mastermind.json`:

```json
{
  "session_start_router": {
    "enabled": true,
    "force_complex_when_uncertain": true,
    "uncertainty_threshold": 0.6,
    "risk_lexicon_override": true
  },
  "planner": {
    "enabled": true,
    "model": "auto",
    "preferred_models": ["openai/gpt-5.2", "google/gemini-3-pro-preview"],
    "mini_mode_threshold": "trivial",
    "max_blueprint_tokens": 4000
  },
  "drift_detection": {
    "enabled": true,
    "file_count_trigger": 5,
    "test_failure_trigger": 3,
    "approach_change_detection": true,
    "cooldown_turns": 10,
    "max_escalations_per_session": 2
  },
  "context_packer": {
    "router_token_budget": 1200,
    "planner_token_budget": 4000,
    "include_repo_structure": true,
    "include_git_diff": true,
    "include_beads": true,
    "include_test_status": true,
    "include_serena_context": true
  },
  "telemetry": {
    "enabled": true,
    "log_router_decisions": true,
    "log_planner_calls": true,
    "log_escalations": true,
    "jsonl_per_session": true
  },
  "safety": {
    "redact_secrets": true,
    "redact_env_vars": true,
    "redact_api_keys": true,
    "preserve_shape": true
  },
  "rollout_phase": 3
}
```

## Key Files

| File | Purpose |
|------|---------|
| `~/.claude/lib/mastermind/__init__.py` | Module exports |
| `~/.claude/lib/mastermind/config.py` | Configuration loading |
| `~/.claude/lib/mastermind/router_groq.py` | Groq/K2 classification |
| `~/.claude/lib/mastermind/router_gpt.py` | GPT-5.2 toolchain routing |
| `~/.claude/lib/mastermind/state.py` | Blueprint/state management |
| `~/.claude/lib/mastermind/routing.py` | Routing decisions |
| `~/.claude/lib/mastermind/hook_integration.py` | Hook layer interface |
| `~/.claude/lib/mastermind/telemetry.py` | Logging/analytics |
| `~/.claude/hooks/_prompt_mastermind.py` | UserPromptSubmit hook (priority 6) |
| `~/.claude/config/mastermind.json` | Runtime configuration |
| `~/.claude/capabilities/registry.yaml` | Capability catalog |
| `~/.claude/ops/mastermind_rollout.py` | Phase management CLI |
| `~/.claude/ops/capability_inventory.py` | Index regeneration |

## Environment Variables

| Variable | Purpose |
|----------|---------|
| `GROQ_API_KEY` | Required for Groq router |
| `OPENAI_API_KEY` | Required for GPT-5.2 planner (via PAL) |

## PAL Mandates

Conditions that trigger **mandatory** PAL tool usage. Aggressive by design - prefers external consultation over solo work.

**Key file:** `~/.claude/hooks/_pal_mandates.py`

### Mandate Triggers

| Condition | Mandate |
|-----------|---------|
| Confidence < 50% | `mcp__pal__debug` or `mcp__pal__thinkdeep` |
| Complex architecture decision | `mcp__pal__consensus` |
| API/library uncertainty | `mcp__pal__apilookup` |
| Extended debugging (3+ attempts) | `mcp__pal__debug` |
| Pre-commit on significant changes | `mcp__pal__precommit` |

### Code-Mode Integration

PAL mandates can trigger code-mode plan generation when complex tool orchestration is needed. See `hooks/_prompt_codemode.py` for plan injection.

## Troubleshooting

### Router not classifying

1. Check `GROQ_API_KEY` is set
2. Verify `rollout_phase` >= 1 in config
3. Check `~/.claude/tmp/mastermind/` for error logs

### Blueprint not generating

1. Verify task classified as `complex`
2. Check `planner.enabled` is true
3. Ensure PAL MCP is available

### Drift detection not firing

1. Verify `drift_detection.enabled` is true
2. Check `cooldown_turns` hasn't been hit
3. Verify `max_escalations_per_session` not exceeded
