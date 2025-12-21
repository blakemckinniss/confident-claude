# Perpetual Momentum (v4.24)

**Philosophy:** "What can we do to make this even better?" - Never stop at done.

## Core Components

### DeadendResponseReducer (-8 confidence)
Penalizes responses that end without actionable forward motion.

**Minimum length:** 100 chars (avoids false positives on short responses)

**Deadend patterns (trigger penalty):**
- `\bthat'?s\s+(?:all|it)\s+(?:for now|i have)\b` - "That's all for now"
- `\bwe'?re\s+(?:all\s+)?(?:done|finished|complete)\b` - "We're done"
- `\blet\s+me\s+know\s+if\s+(?:you\s+)?(?:need|want|have)\b` - "Let me know if you need"
- `\bhope\s+(?:this|that)\s+helps?\b` - "Hope this helps"
- `\banything\s+else\s+(?:you\s+)?(?:need|want)\b` - "Anything else you need"
- `\bfeel\s+free\s+to\s+(?:ask|reach out)\b` - "Feel free to ask"
- `\bi'?m\s+here\s+if\s+you\s+need\b` - "I'm here if you need"
- `\bdon'?t\s+hesitate\s+to\b` - "Don't hesitate to"

**Passive patterns (also trigger penalty):**
- `\byou\s+(?:could|might|may)\s+(?:want\s+to|consider|try)\b` - "You could consider"
- `\byou\s+(?:should|can)\s+(?:also\s+)?(?:consider|look at|check)\b` - "You should also consider"
- `\bit\s+(?:might|could)\s+be\s+worth\b` - "It might be worth"

**Momentum exemptions (prevent penalty):**
- `\bi\s+(?:can|will|could)\s+(?:also\s+)?(?:now\s+)?(?:\w+)` - "I can now..."
- `\blet\s+me\s+(?:now\s+)?(?:\w+)` - "Let me verify..."
- `\bnext\s+(?:i'?ll|step|steps?)[\s:]+` - "Next I'll..." or "## Next Steps"
- `\b(?:shall|should)\s+i\s+(?:\w+)` - "Shall I run...?"
- `\bwant\s+me\s+to\b` - "Want me to...?"
- `(?:^|\n)#+\s*(?:next\s+steps?)` - Markdown "## Next Steps" section
- `(?:^|\n)\*\*(?:next\s+steps?)\*\*` - Bold **Next Steps**

---

### MomentumForwardIncreaser (+2 confidence)
Rewards responses that maintain forward motion.

**Minimum length:** 50 chars (avoids noise on short responses)

**Momentum patterns (trigger reward):**
- `\bi\s+(?:can|will|could)\s+(?:also\s+)?(?:now\s+)?(?:\w+)` - "I can now test..."
- `\blet\s+me\s+(?:now\s+)?(?:\w+)` - "Let me verify..."
- `\bnext\s+(?:i'?ll|step|steps?)[\s:]+` - "Next I'll..."
- `\b(?:shall|should)\s+i\s+(?:\w+)` - "Shall I...?"
- `\bwant\s+me\s+to\b` - "Want me to...?"
- `(?:^|\n)#+\s*(?:next\s+steps?)` - "## Next Steps" section
- `(?:^|\n)\*\*(?:next\s+steps?)\*\*` - "**Next Steps**"
- `\bi'?ll\s+(?:now\s+)?(?:proceed|continue|start|begin)\b` - "I'll proceed..."

---

## Edge Cases & Gotchas

1. **"Let me know" vs "Let me"**: The pattern `\blet\s+me\s+` matches both, but:
   - "Let me verify..." = momentum (good)
   - "Let me know if you need..." = deadend (bad)
   The deadend check happens FIRST, so "Let me know..." triggers the penalty.

2. **Passive "also"**: The pattern `\byou\s+(?:could|might|may)\s+(?:want\s+to|consider|try)\b`
   does NOT match "You could also consider" because "also" breaks the pattern.
   Fixed: Use `\byou\s+(?:should|can)\s+(?:also\s+)?(?:consider|...)` for the "also" variant.

3. **Cooldowns:**
   - DeadendResponseReducer: 2 turns
   - MomentumForwardIncreaser: 1 turn

4. **Zone scaling applies**: Cooldowns scale by confidence zone per v4.13.

---

## Files

| File | Purpose |
|------|---------|
| `lib/reducers/_language.py` | DeadendResponseReducer class |
| `lib/_confidence_increasers.py` | MomentumForwardIncreaser class |
| `hooks/stop_runner.py` | momentum_gate hook |
| `tests/confidence_system/test_perpetual_momentum.py` | 20 unit tests |

---

## Why This Matters

Deadend language is a symptom of:
1. **Task myopia** - Treating each request as isolated instead of part of a flow
2. **Passive delegation** - Putting burden back on user ("let me know")
3. **Premature closure** - Declaring "done" without exploring improvements

Forward momentum creates:
1. **Continuous value** - Every response offers next actions
2. **Proactive ownership** - Claude drives, user steers
3. **Natural flow** - Work progresses without explicit prompting

---

*Added: 2025-12-21 (v4.24)*
