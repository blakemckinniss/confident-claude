# Resume Previous Session

**Purpose:** Recover FULL context from the previous session for the CURRENT project.

---

## Instructions

### Step 1: Identify Current Project

Run this to find the current project's session state:
```bash
# Get project info from index
python3 -c "
import json
from pathlib import Path

cwd = '$(pwd)'
index_file = Path.home() / '.claude/memory/projects/_index.json'

if not index_file.exists():
    print('NO_INDEX')
    exit()

index = json.load(open(index_file))
projects = index.get('projects', {})

# Find project matching current directory
for pid, info in projects.items():
    root = info.get('root_path', '')
    if cwd.startswith(root) or root.startswith(cwd):
        state_file = Path.home() / f'.claude/memory/projects/{pid}/session_state.json'
        if state_file.exists():
            print(f'PROJECT_ID={pid}')
            print(f'PROJECT_NAME={info.get(\"name\", \"unknown\")}')
            print(f'STATE_FILE={state_file}')
            exit()

print('NO_MATCH')
"
```

### Step 2: Load Project Session State

Read the state file identified above (NOT a random recent one). Extract:
- `original_goal` - What the user was trying to accomplish
- `progress_log` - Work completed
- `files_edited` and `files_created` - Files touched
- `errors_unresolved` - Outstanding issues
- `handoff_blockers` - Known blockers
- `handoff_next_steps` - Planned next actions
- `work_queue` - Discovered work items
- `current_feature` - Feature in progress

### Step 3: Check Git State (This Project Only)

```bash
git status --short
git log --oneline -5
```

### Step 4: Check Beads (This Project Only)

Beads are project-isolated. Run from project directory:
```bash
bd list --status=in_progress
bd list --status=open --limit=10
```

### Step 5: Load Recent Session History

```bash
# Get last 3 sessions for this project from session log
python3 -c "
import json
from pathlib import Path

log_file = Path.home() / '.claude/memory/session_log.jsonl'
project = '${PROJECT_NAME:-unknown}'

if log_file.exists():
    sessions = []
    for line in open(log_file):
        try:
            s = json.loads(line)
            # Match by files_edited containing project path or domain
            files = s.get('files_edited', [])
            if any(project.lower() in f.lower() for f in files) or s.get('domain') == project:
                sessions.append(s)
        except: pass

    # Show last 3
    for s in sessions[-3:]:
        print(f\"Session {s.get('session_id', 'unknown')[:8]}:\")
        print(f\"  Domain: {s.get('domain')}\")
        print(f\"  Files: {', '.join(s.get('files_edited', [])[:5])}\")
        print(f\"  Errors: {s.get('errors_unresolved', [])}\")
        print()
"
```

### Step 6: Load Framework Memories (Lessons & Decisions)

Read these files and extract entries relevant to the current project:

```bash
# Recent lessons (last 20 lines)
tail -20 ~/.claude/memory/__lessons.md 2>/dev/null

# Recent decisions (last 20 lines)
tail -20 ~/.claude/memory/__decisions.md 2>/dev/null
```

Look for entries mentioning the project name or related technologies.

### Step 7: Check Serena Memories (If Available)

If `.serena/` exists in project root:
```
mcp__serena__activate_project("{project_path}")
mcp__serena__list_memories
```

Read any memories with names matching current work.

### Step 8: Present Recovery Summary

```
## 🔄 SESSION RECOVERED - {project_name}

### Original Goal
[From session_state.original_goal]

### Current Feature
[From session_state.current_feature]

### Progress Made
[From progress_log - last 5 entries]

### Files Modified
[From files_edited - deduplicated]

### Outstanding Issues
[From errors_unresolved + handoff_blockers]

### Next Steps
[From handoff_next_steps or work_queue]

### Git Status
[From git status/log output]

### Active Beads
[From bd list output - IN_PROGRESS items first, then OPEN]

### Session History
[Brief summary of last 3 sessions for this project]

### Relevant Memories
[Any serena memories or framework lessons that apply]

---

**Context sources loaded:**
- [ ] Session state file
- [ ] Git status
- [ ] Beads (project-scoped)
- [ ] Session history log
- [ ] Framework memories
- [ ] Serena memories
- [auto] claude-mem (injected via hooks)

**Ready to continue.** What would you like me to work on?
```

---

## Fallback: No Project Match

If Step 1 returns `NO_MATCH`, list recent states and ask user which project:
```bash
ls -lt ~/.claude/memory/projects/*/session_state.json 2>/dev/null | head -5
cat ~/.claude/memory/projects/_index.json | python3 -c "import json,sys; d=json.load(sys.stdin); [print(f'{k}: {v[\"name\"]} ({v[\"root_path\"]})') for k,v in d.get('projects',{}).items()]"
```

Then ask: "Which project would you like to resume?"

---

**CRITICAL:** Always load the CURRENT project's state, not the most recently modified one across all projects.
