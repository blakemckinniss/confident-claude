# Session Lifecycle Coherence

**Version:** 1.0 (2025-12-21)
**Purpose:** Ensure all hooks align on session state flow across compaction and revival.

## Lifecycle Phases

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         SESSION LIFECYCLE                                │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  SESSION_START ──────────────────────────────────────────────────────►  │
│       │                                                                  │
│       ├── Checkpoint recovery (Tier1 always, Tier2 if <1hr)             │
│       ├── Handoff loading (if <24hr)                                    │
│       ├── Work queue restoration                                        │
│       ├── Cache pre-warming (synapses, schemas)                         │
│       └── Beads sync                                                     │
│                                                                          │
│  SESSION_RUNNING ────────────────────────────────────────────────────►  │
│       │                                                                  │
│       ├── State accumulation (files, commands, errors)                  │
│       ├── Confidence tracking (reducers, increasers)                    │
│       ├── Goal tracking (original_goal, keywords)                       │
│       └── Evidence collection (Ralph completion)                        │
│                                                                          │
│  PRE_COMPACT ────────────────────────────────────────────────────────►  │
│       │                                                                  │
│       ├── Checkpoint creation (Tier1 + Tier2 based on phase)            │
│       ├── Context injection (GOAL, CONF, SERENA, BEADS, etc.)           │
│       └── State summarization for compaction                            │
│                                                                          │
│  POST_COMPACT ───────────────────────────────────────────────────────►  │
│       │                                                                  │
│       ├── Reduced context (summary only)                                │
│       ├── Tier1 state preserved in checkpoint                           │
│       └── Serena reactivation via injected command                      │
│                                                                          │
│  SESSION_STOP ───────────────────────────────────────────────────────►  │
│       │                                                                  │
│       ├── Context exhaustion check (150K tokens)                        │
│       ├── Close protocol (bd sync, next steps)                          │
│       ├── Ralph evidence gate                                           │
│       ├── Auto-close beads                                              │
│       └── Session commit                                                 │
│                                                                          │
│  SESSION_CLEANUP ────────────────────────────────────────────────────►  │
│       │                                                                  │
│       ├── Handoff persistence (JSON)                                    │
│       ├── Progress log persistence                                      │
│       ├── Memory grooming (Serena, thinking)                            │
│       └── Scratch cleanup                                                │
│                                                                          │
│  SESSION_REVIVAL ────────────────────────────────────────────────────►  │
│       │                                                                  │
│       ├── /resume command or continuation prompt                        │
│       ├── Checkpoint loading (if available)                             │
│       └── Handoff context injection                                      │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

## State Tiers

### Tier 1: Critical (ALWAYS Preserve)

These fields MUST survive compaction and revival - they cannot be reconstructed.

| Field | Purpose | Recovery Impact |
|-------|---------|-----------------|
| `original_goal` | Prevents drift | Loss = goal confusion |
| `goal_keywords` | Searchable indexing | Loss = weak revival |
| `confidence` | Gating decisions | Loss = wrong permissions |
| `completion_confidence` | Ralph gate | Loss = premature exit |
| `serena_activated` | Semantic search state | Loss = re-activation needed |
| `serena_project` | Project context | Loss = wrong project |
| `ralph_mode` | Completion tracking | Loss = no enforcement |
| `task_contract` | What was promised | Loss = scope confusion |
| `pal_continuation_id` | Second brain pointer | Loss = context break |
| `session_id` | Identity | Loss = state orphaned |

### Tier 2: Extended (Preserve if <1hr old)

High-value cache that SHOULD persist but can be reconstructed.

| Field | Purpose | Reconstruction Cost |
|-------|---------|---------------------|
| `files_read` | Read cache | Re-read files |
| `files_edited` | Edit history | git diff |
| `files_created` | New files | git status |
| `tool_counts` | Analytics | Not critical |
| `commands_succeeded` | Command history | Not critical |
| `errors_unresolved` | Error tracking | Re-encounter |
| `turn_count` | Session length | Start fresh |
| `nudge_history` | Cooldown state | Re-trigger |
| `repair_debt` | Redemption tracking | Start fresh |

### Tier 3: Ephemeral (Discard at CONDENSED+)

These actively harm revival by creating context pollution.

| Field | Purpose | Why Discard |
|-------|---------|-------------|
| `edit_history` | Detailed edit log | Noise, reconstruct from git |
| `approach_history` | Debug attempts | Stale context |
| `progress_log` | Verbose progress | Summarized in handoff |
| `framework_errors` | Debug info | Session-specific |
| `evidence_ledger` | Proof-of-work | Session-specific |
| `pending_files` | Temp tracking | Stale |
| `pending_searches` | Temp tracking | Stale |
| `pending_integration_greps` | Verification queue | Cleared on session end |

## Conservation Protocol

### What to Preserve (Conservation Set)

```python
CONSERVATION_SET = {
    # Identity
    "session_id",
    "original_goal",
    "goal_keywords",

    # Confidence (gating)
    "confidence",
    "completion_confidence",

    # Active state
    "serena_activated",
    "serena_project",
    "ralph_mode",
    "task_contract",

    # Files (artifacts)
    "files_created",
    "files_edited",

    # Errors (blockers)
    "errors_unresolved",
}
```

### What to Discard (Expiration Set)

```python
EXPIRATION_SET = {
    # Verbose logs
    "edit_history",
    "approach_history",
    "evidence_ledger",

    # Temp tracking
    "pending_files",
    "pending_searches",
    "pending_integration_greps",

    # Debug info
    "framework_errors",
    "consecutive_blocks",
}
```

## Hook Phase Awareness

Hooks should check their lifecycle phase and behave accordingly:

```python
from token_budget import get_budget_manager, Phase

def my_hook(data, state):
    mgr = get_budget_manager()
    phase = mgr.get_phase()

    if phase == Phase.CRITICAL:
        # Minimal output, skip non-essential work
        return HookResult.allow()

    if phase == Phase.SIGNALS:
        # Compressed output, essential signals only
        return HookResult.allow(context="[SIGNAL] key point")

    # Full verbosity at VERBOSE/CONDENSED
    return HookResult.allow(context="Full detailed output...")
```

## Revival Hygiene

### Schema Versioning

Checkpoints include `schema_version` field. On revival:
1. Check version matches current
2. If mismatch, apply migration or discard
3. Never load incompatible schemas

### Staleness Validation

Beyond age checks, validate:
- `session_id` doesn't conflict
- `goal_keywords` are still relevant
- `serena_project` path still exists

### Context Pollution Prevention

1. Clear ephemeral fields on revival
2. Don't restore Tier3 data
3. Validate Tier2 age before restoring

## Phase Markers

Hooks inject phase markers for context visibility:

```
[PHASE: SESSION_START] - Loading from checkpoint
[PHASE: SESSION_RUNNING] - Normal operation
[PHASE: PRE_COMPACT] - About to summarize
[PHASE: POST_COMPACT] - Reduced context
[PHASE: SESSION_STOP] - Wrapping up
```

## Key Files

| File | Phase | Purpose |
|------|-------|---------|
| `session_init.py` | START, REVIVAL | Initialize/recover state |
| `pre_compact.py` | PRE_COMPACT | Create checkpoint, inject context |
| `stop_runner.py` | STOP | Enforce close protocol |
| `session_cleanup.py` | CLEANUP | Persist handoff, groom memory |
| `session_checkpoint.py` | PRE_COMPACT, REVIVAL | Tier-based state management |
| `token_budget.py` | ALL | Phase detection |
| `phase_gate.py` | ALL | Hook tier gating |

## Coherence Rules

1. **Tier1 always survives** - Never discard critical state
2. **Tier3 always expires** - Never persist ephemeral data
3. **Phase awareness required** - Hooks must check phase
4. **Schema versioning** - Always include version in checkpoints
5. **Staleness validation** - Check content, not just age
6. **Explicit handoff** - Document next steps before stop

## Anti-Patterns

| Anti-Pattern | Correct Approach |
|--------------|------------------|
| Restoring all state blindly | Filter by tier |
| Ignoring schema version | Validate or migrate |
| Persisting debug logs | Discard Tier3 |
| No phase checking in hooks | Use `get_budget_manager()` |
| Stale handoff loading | Validate relevance |
| Missing goal on revival | Always restore Tier1 first |
