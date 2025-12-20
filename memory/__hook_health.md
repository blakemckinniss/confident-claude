# Hook System Health Log

**Purpose:** Track hook effectiveness, friction patterns, and recommendations across sessions.
**Location:** `~/.claude/memory/__hook_health.md`
**Last Audit:** 2025-12-20

---

## Quick Reference

| Metric | Value | Status |
|--------|-------|--------|
| Total Hooks | 164 | High complexity |
| Runners | 4 | OK |
| God Files | 4 | Needs refactor |
| Recommended Disables | 4 | Pending test |

---

## Hook Health Matrix

### High Value (Keep)

| Hook | Runner | Friction | Value | Notes |
|------|--------|----------|-------|-------|
| `confidence_tool_gate` | pre | Low | High | Core safety |
| `cascade_block` detection | pre | Low | High | Prevents infinite loops |
| `confidence_reducer` | post | Low | High | Mechanical regulation |
| `confidence_increaser` | post | Low | High | Rewards good behavior |
| `context_exhaustion` | stop | Low | High | Session continuity |
| `verification_theater_detector` | stop | Medium | High | Catches unbacked claims |

### Medium Value (Monitor)

| Hook | Runner | Friction | Value | Notes |
|------|--------|----------|-------|-------|
| `goal_drift` | prompt | Medium | Medium | Can false-positive on related work |
| `ralph_evidence` | stop | Medium | Medium | Useful for impl tasks, not research |
| `bead_enforcement` | pre | Medium | Medium | Good for tracking, can feel rigid |
| `tool_debt` | post | Medium | Low | Fires too often on legitimate tool use |

### Low Value / High Friction (Disabled)

| Hook | Runner | Friction | Value | Status |
|------|--------|----------|-------|--------|
| `modularization_nudge` | pre | High | Low | ✅ DISABLED 2025-12-20 |
| `curiosity_injection` | pre | High | Low | ✅ DISABLED 2025-12-20 |
| `ops_audit_reminder` | prompt | High | Low | ✅ DISABLED 2025-12-20 |
| `crawl4ai_promo` | post | Medium | Low | ✅ DISABLED 2025-12-20 |
| `expert_probe` | prompt | Medium | Low | Consider disable |

---

## Known False Positive Patterns

### `goal_drift` (-8) ✅ FIXED 2025-12-20
- **Trigger:** Working on related subtask that shares <20% keywords with original prompt
- **Pattern:** Audit → implementation → creates beads → drift detected
- **Fix:** Lowered threshold from 20% to 10% in `lib/_session_goals.py`

### `tool_debt` (-2) ✅ FIXED 2025-12-20
- **Trigger:** Using MCP tools legitimately
- **Pattern:** Fires on nearly every mcp__* call
- **Fix:** Skip penalty if any `mcp__*` tool used this turn in `lib/_confidence_tool_debt.py`

### `ralph_evidence` (blocks stop) ✅ FIXED 2025-12-20
- **Trigger:** Research/audit tasks blocked for missing "build" evidence
- **Pattern:** Non-implementation tasks treated as impl tasks
- **Fix:** Added `_is_research_task()` detection in `hooks/stop_runner.py`

### `sequential_when_parallel` (-2) ✅ FIXED 2025-12-20
- **Trigger:** Reading 4 files to understand a system
- **Pattern:** Exploratory reads flagged as inefficient
- **Fix:** Exempt exploratory contexts (no files edited OR goal contains audit/explore keywords) in `lib/reducers/_efficiency.py`

### `hook_block` (-5) ✅ DISABLED 2025-12-20
- **Trigger:** Any hook blocks an action
- **Pattern:** Double-jeopardy - being blocked IS the corrective signal
- **Fix:** Disabled reducer entirely in `lib/reducers/_behavioral.py`

### `grep_over_serena` (-1) ✅ FIXED 2025-12-20
- **Trigger:** Using Grep when Serena is active
- **Pattern:** Single-file Grep is appropriate, only broad searches need Serena
- **Fix:** Exempt single-file searches in `lib/reducers/_framework.py`

---

## God Files (Refactor Targets)

| File | Lines | Problem | Priority |
|------|-------|---------|----------|
| `stop_runner.py` | 1800 | Inline language patterns, debt scanning | High |
| `_prompt_suggestions.py` | 2469 | Massive aggregator | High |
| `gates/_content.py` | ~800 | Too many gates | Medium |
| `_hooks_tracking.py` | 868 | Multiple trackers | Medium |

---

## Duplicate Hooks (Consolidation Targets)

| Hooks | Overlap | Action |
|-------|---------|--------|
| `crawl4ai_preference` + `crawl4ai_promo` | Both promote crawl4ai | Keep one |
| 4 beads hooks | Beads lifecycle scattered | Consolidate to `_hooks_beads.py` |
| 3 curiosity hooks | All inject metacognitive prompts | Consider single `curiosity` hook |

---

## Session Friction Log

Format: `DATE | HOOK | FRICTION(1-5) | OUTCOME | NOTES`

```
2025-12-20 | goal_drift | 4 | false_positive | Audit task flagged during subtask
2025-12-20 | tool_debt | 3 | false_positive | Fires on every MCP tool
2025-12-20 | ralph_evidence | 4 | false_positive | Blocked research task for missing build
2025-12-20 | sequential_when_parallel | 2 | false_positive | Reading runners for audit
```

---

## Recommended Environment Overrides

Test these in a session to measure impact:

```bash
# Disable low-value nudges
export CLAUDE_HOOK_DISABLE_MODULARIZATION_NUDGE=1
export CLAUDE_HOOK_DISABLE_CURIOSITY_INJECTION=1
export CLAUDE_HOOK_DISABLE_OPS_AUDIT_REMINDER=1

# Disable duplicate
export CLAUDE_HOOK_DISABLE_CRAWL4AI_PROMO=1
```

---

## Metrics Over Time

| Date | Hooks | FPs Logged | Friction Events | Notes |
|------|-------|------------|-----------------|-------|
| 2025-12-20 | 164 | 4 | 4 | Initial audit |
| 2025-12-20 | 164 | 6 | 0 | Fixed 6 FPs, disabled 4 low-value hooks |

---

## Next Session Actions

1. Monitor for new friction patterns post-cleanup
2. Consider disabling `expert_probe` if still noisy
3. Track "God Files" refactoring (stop_runner.py, _prompt_suggestions.py)
4. Log new friction events to this file
