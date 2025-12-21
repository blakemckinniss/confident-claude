---
description: 🚀 Proceed - Autonomous implementation with perpetual momentum
argument-hint: [golden|path A|path B|A+B|all|branch|focus]
allowed-tools: Bash, Read, Edit, Write, Glob, Grep, Task, WebSearch, mcp__pal__*, mcp__beads__*
---

Proceed autonomously to implement what's best for the project. Always surfaces branching opportunities - completion without continuation options is a failed response.

## Trigger

User says `/proceed` when they trust Claude to make implementation decisions without micro-approval.

## Arguments

Parse `$ARGUMENTS` for path specifiers from the response format:

| Argument | Meaning |
|----------|---------|
| `golden` or `g` | Execute 👑 Golden Step only |
| `path a` or `a` | Execute Path A items |
| `path b` or `b` | Execute Path B items |
| `path c` or `c` | Execute Path C items (etc.) |
| `a+b` or `a b` | Execute multiple paths in order |
| `golden+a` or `g+a` | Golden Step then Path A |
| `all` | Execute Golden Step + all Paths in order |
| `quick` or `qw` | Execute ⚡ Quick Wins only |
| `horizon` or `h` | Address 🔭 Horizon items proactively |
| `branch` or `🌱` | Execute 🌱 Branching Opportunities |
| (other text) | Treat as focus area filter |

**Examples:**
- `/proceed` → Auto-select best path based on context
- `/proceed golden` → Just the Golden Step
- `/proceed a` → Path A items
- `/proceed g+b` → Golden Step, then Path B
- `/proceed all` → Everything in priority order
- `/proceed branch` → Execute branching opportunities
- `/proceed auth` → Focus on auth-related recommendations

## Scope

If path specifier provided, extract those specific items from conversation.
If no specifier or unrecognized text:
1. Scan conversation for recommendations (Next Steps, Quick Wins, Paths, Branches)
2. Check open beads: `bd list --status=open`
3. Review any pending tech debt or issues mentioned

## Execution Protocol

### Phase 1: Gather Context
- Extract all actionable recommendations from conversation
- Check project patterns via file reads (don't reinvent)
- If uncertain about approach, use `mcp__pal__chat` for quick validation

### Phase 2: Prioritize
Rank actions by:
1. **Blocking issues** (errors, broken builds) - do first
2. **Quick wins** (high impact, low effort) - do second
3. **Strategic improvements** (medium effort, high value) - do third
4. **Branching opportunities** (discovered during work) - surface and offer
5. **Nice-to-haves** - defer or create beads

### Phase 3: Implement
For each action:
1. Create bead if substantial: `bd create "[task]" --type=task`
2. Implement using project conventions
3. Verify with tests/lints where applicable
4. Mark complete: `bd close <id>`
5. **Surface any new opportunities discovered**

### Phase 4: Report with Momentum

Summarize what was done AND offer forward motion:

```
✅ Implemented:
- [action 1] - [outcome]
- [action 2] - [outcome]

⏸️ Deferred (beads created):
- [bead-id]: [reason]

🌱 One More Bead (discovered opportunities):
- 🔧 [Hardening]: [what would make this more robust]
- 🔀 [Adjacent]: [related area that could benefit]
- 🧪 [Coverage]: [test/validation gaps to fill]
- 🔬 [Deep dive]: [aspect worth investigating]

➡️ I can now:
- [Claude-actionable next step 1]
- [Claude-actionable next step 2]

🔮 Resume: "[context for next session]"
```

**CRITICAL:** Never end with passive suggestions ("you might want to..."). Always end with Claude-owned actions ("I can now...", "Shall I...").

## Perpetual Momentum Philosophy

**"What can we do to make this even better?" is not a question - it's a mandate.**

Every completed task reveals adjacent opportunities. Mine them:

| Category | Question | Example |
|----------|----------|---------|
| Hardening | "What could break this?" | Add error handling, edge cases |
| Adjacent | "What else uses this pattern?" | Apply fix to similar code |
| Coverage | "How do we know this works?" | Add tests, verify in prod |
| Meta | "What does this teach us?" | Update rules, create bead |
| Upstream | "What caused this need?" | Fix root cause |
| Downstream | "What does this enable?" | Unlock blocked work |

**The user should never have to ask "what's next?"** - paths should already be laid out.

## Autonomy Guidelines

**DO autonomously:**
- Fix obvious bugs and issues
- Implement clearly specified features
- Apply quick wins from conversation
- Follow established project patterns
- Run tests and verification
- Surface branching opportunities
- Create beads for discovered work

**ASK before:**
- Major architectural changes
- New dependencies
- Deleting significant code
- Changes outside stated scope
- Anything security-sensitive

## Constraints
- Stay aligned with project conventions (read existing code first)
- Prefer minimal changes over extensive refactoring
- If blocked after 2 attempts, use `/think` before continuing
- Create beads for work that exceeds current scope
- **NEVER end without offering forward motion**
