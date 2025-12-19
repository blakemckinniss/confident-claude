---
description: 🚀 Proceed - Autonomous implementation based on recommendations and research
argument-hint: [golden|path A|path B|A+B|all|focus]
allowed-tools: Bash, Read, Edit, Write, Glob, Grep, Task, WebSearch, mcp__pal__*
---

Proceed autonomously to implement what's best for the project based on recommendations and educated research.

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
| (other text) | Treat as focus area filter |

**Examples:**
- `/proceed` → Auto-select best path based on context
- `/proceed golden` → Just the Golden Step
- `/proceed a` → Path A items
- `/proceed g+b` → Golden Step, then Path B
- `/proceed all` → Everything in priority order
- `/proceed auth` → Focus on auth-related recommendations

## Scope

If path specifier provided, extract those specific items from conversation.
If no specifier or unrecognized text:
1. Scan conversation for recommendations (Next Steps, Quick Wins, Paths)
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
4. **Nice-to-haves** - defer or create beads

### Phase 3: Implement
For each action:
1. Create bead if substantial: `bd create "[task]" --type=task`
2. Implement using project conventions
3. Verify with tests/lints where applicable
4. Mark complete: `bd close <id>`

### Phase 4: Report
Summarize what was done:
```
✅ Implemented:
- [action 1] - [outcome]
- [action 2] - [outcome]

⏸️ Deferred (beads created):
- [bead-id]: [reason]

🔮 Resume: "[context for next session]"
```

## Autonomy Guidelines

**DO autonomously:**
- Fix obvious bugs and issues
- Implement clearly specified features
- Apply quick wins from conversation
- Follow established project patterns
- Run tests and verification

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
