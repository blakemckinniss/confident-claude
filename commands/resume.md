# Resume Previous Session

**Purpose:** Recover context from a previous near-saturated session into this fresh session.

---

## Instructions

Read the previous session's state and present it to continue work seamlessly.

### Step 1: Load Previous Session State

Read `~/.claude/memory/session_state_v3.json` and extract:
- `original_goal` - What the user was trying to accomplish
- `progress_log` - Work completed
- `files_edited` and `files_created` - Files touched
- `errors_unresolved` - Outstanding issues
- `handoff_blockers` - Known blockers
- `handoff_next_steps` - Planned next actions
- `work_queue` - Discovered work items
- `evidence_ledger` - Evidence gathered
- `approach_history` - What was tried
- `session_id` - For transcript lookup

### Step 2: Check Beads Status

Run these commands to see current task state:
```bash
bd list --status=open
bd list --status=in_progress
```

### Step 3: Check Git State

Run to see uncommitted work from previous session:
```bash
git status --short
git diff --stat
```

### Step 4: Check Serena

If `.serena/` exists in the working directory, activate Serena:
```
mcp__serena__activate_project
```

Also check Serena memories at `~/.claude/.serena/memories/` if relevant.

### Step 5: Present Recovery Summary

Output a structured summary:

```
## 🔄 SESSION RECOVERED

### Original Goal
[From session_state.original_goal]

### Progress Made (Previous Session)
[From progress_log]

### Files Modified
[From files_edited + files_created]

### Outstanding Issues
[From errors_unresolved + handoff_blockers]

### Next Steps (From Previous Session)
[From handoff_next_steps or work_queue]

### Current Beads
[From bd list output]

### Git Status
[From git status output]

---

**Ready to continue.** What would you like me to work on?
```

### Step 6: Consult Memory Systems

If additional context needed, check:
- `~/.claude/memory/` - Framework memories (lessons, decisions)
- `~/.claude/.serena/memories/` - Serena project memories
- Previous transcript at `~/.claude/projects/{project}/` by session ID

---

**The goal is to bring this new session up to speed on everything the previous session knew.**
