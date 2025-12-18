# Dynamic Confidence Regulation System

## Overview

Implement a meta-cognition framework that dynamically regulates Claude's confidence throughout a session, with **deterministic (mechanical)** reducers that bypass self-assessment bias.

## Confidence Zones

| Zone | Range | Emoji | Behavior |
|------|-------|-------|----------|
| IGNORANCE | 0-30 | 🔴 | Read/Research ONLY, external LLM MANDATORY |
| HYPOTHESIS | 31-50 | 🟠 | Scratch only, research REQUIRED |
| WORKING | 51-70 | 🟡 | Scratch + git read, research suggested |
| CERTAINTY | 71-85 | 🟢 | Production with MANDATORY gates |
| TRUSTED | 86-94 | 💚 | Production with WARNINGS |
| EXPERT | 95-100 | 💎 | Maximum freedom |

## User Decisions

- **Escalation**: Hybrid (PAL MCP primary → groq fallback)
- **Visibility**: Both (status line + zone change alerts)
- **Reducers**: Comprehensive (failures + anti-patterns + contradictions + oscillations)
- **Trust Regain**: Hybrid (+5 auto on success, +15+ requires user approval)

---

## Implementation Plan

### Phase 1: Core Engine

**File**: `/home/jinx/.claude/lib/confidence.py` (NEW, ~500 LOC)

```python
# Key functions:
def get_confidence_tier(confidence: int) -> Tuple[str, str, str]
def assess_prompt_confidence(prompt: str, state: SessionState) -> int
def should_escalate_to_external(confidence: int) -> Tuple[bool, str]
def format_confidence_status(confidence: int) -> str

# Reducer Registry (MECHANICAL - no judgment)
REDUCERS = {
    "tool_failure":     {"delta": -5,  "trigger": "Bash exit != 0"},
    "cascade_block":    {"delta": -15, "trigger": "Same hook blocks 3+ in 5 turns"},
    "sunk_cost":        {"delta": -20, "trigger": "3+ consecutive failures"},
    "user_correction":  {"delta": -10, "patterns": ["wrong", "incorrect", "fix that"]},
    "goal_drift":       {"delta": -8,  "trigger": "< 20% keyword overlap"},
    "edit_oscillation": {"delta": -12, "trigger": "Same file 3+ edits in 5 turns"},
    "contradiction":    {"delta": -10, "trigger": "Opposite claims in 3 turns"},
}

# Increaser Registry
INCREASERS = {
    "test_pass":      {"delta": +5,  "requires_approval": False},
    "build_success":  {"delta": +5,  "requires_approval": False},
    "user_ok":        {"delta": +5,  "requires_approval": False},
    "trust_regained": {"delta": +15, "requires_approval": True},
}
```

### Phase 2: User Prompt Hooks

**File**: `/home/jinx/.claude/hooks/user_prompt_submit_runner.py` (+100 LOC)

**Hook 1**: `confidence_initializer` (priority 3)
- Assess initial confidence on every prompt
- Inject research requirements at low confidence
- MANDATE external LLM at < 30

**Hook 2**: `confidence_approval_gate` (priority 7)
- Detect "trust regained" patterns
- Show confirmation prompt
- Apply +15 on explicit approval ("CONFIDENCE_BOOST_APPROVED")

### Phase 3: Pre-Tool Hooks

**File**: `/home/jinx/.claude/hooks/pre_tool_use_runner.py` (+120 LOC)

**Hook 1**: `confidence_tool_gate` (priority 18)
- At < 30: BLOCK all except Read, Grep, Glob, WebSearch, external LLMs
- At < 51: BLOCK Edit/Write to production, git write, Bash state mods
- Always allow SUDO bypass

**Hook 2**: `confidence_external_suggestion` (priority 32)
- At < 30: Suggest 2-3 alternative approaches + mandate consultation
- At 30-50: Suggest 1-2 alternatives
- At > 50: Silent

### Phase 4: Post-Tool Hooks

**File**: `/home/jinx/.claude/hooks/post_tool_use_runner.py` (+180 LOC)

**Hook 1**: `confidence_reducer` (priority 12)
- Apply deterministic reductions based on signals
- Check: tool_failure, cascade_block, sunk_cost, goal_drift, edit_oscillation, user_correction
- Return feedback: "Confidence: 85% → 70% (-15 cascade_block)"

**Hook 2**: `confidence_increaser` (priority 14)
- Apply auto-increases on success signals
- Detect: test_pass, build_success, user_ok patterns
- Return feedback: "Confidence: 55% → 60% (+5 test_pass)"

### Phase 5: Status Line

**File**: `/home/jinx/.claude/hooks/statusline.py` (+15 LOC)

Inject confidence into line 2 of status output:
```
abc123 | myproject | 🟢75% CERTAINTY | main [+2]
```

---

## Escalation Protocol

At < 30% confidence, inject this message:

```
🔴 CONFIDENCE CRITICALLY LOW: 25% (IGNORANCE)

External consultation is MANDATORY. Pick one:
1. mcp__pal__thinkdeep - Deep analysis via PAL MCP
2. /think - Problem decomposition
3. /oracle - Expert consultation
4. /research - Verify with current docs

Recent failure signals:
  • tool_failure: -5 (Bash exit 1)
  • cascade_block: -15 (research_gate 3x)

Say SUDO to bypass (not recommended).
```

**Escalation Order**:
1. PAL MCP (`mcp__pal__thinkdeep`, `mcp__pal__debug`)
2. Groq fallback (`~/.claude/ops/groq.py --model kimi-k2`)
3. Oracle fallback (`~/.claude/ops/oracle.py --persona judge`)

---

## Critical Files

| File | Action | LOC |
|------|--------|-----|
| `lib/confidence.py` | CREATE | ~500 |
| `hooks/post_tool_use_runner.py` | MODIFY | +180 |
| `hooks/pre_tool_use_runner.py` | MODIFY | +120 |
| `hooks/user_prompt_submit_runner.py` | MODIFY | +100 |
| `hooks/statusline.py` | MODIFY | +15 |
| **Total** | | ~915 |

---

## Example Flow

```
User: "Debug this FastAPI error"
→ Initial: 45% HYPOTHESIS
→ "Research suggested"

User: Edit main.py
→ BLOCKED (< 51)
→ "Research first or /oracle"

User: /research FastAPI
→ Allowed

User: pytest
→ Pass (+5) → 50%

User: "looks good"
→ User OK (+5) → 55% WORKING
→ Edit now ALLOWED

User: Bash fails 3x
→ -15 tool_failure → 40% HYPOTHESIS
→ BLOCKED again

User: "trust regained"
→ Approval prompt

User: "CONFIDENCE_BOOST_APPROVED"
→ +15 → 55% WORKING
→ Unlocked
```

---

## Key Design Principles

1. **Deterministic Reducers**: Mechanical signals fire WITHOUT judgment
2. **No Self-Assessment**: Confidence reduction bypasses my own evaluation
3. **Escalation Path**: Clear fallback chain (PAL → groq → oracle)
4. **Visibility**: User always sees current confidence and zone changes
5. **Recovery Path**: Clear mechanism to regain trust with explicit approval
