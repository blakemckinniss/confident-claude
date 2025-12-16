# Resume Prompt Generator

Generate a comprehensive resume prompt for continuing work in a new session.

---

Read the current session state from `~/.claude/memory/session_state_v3.json` and the transcript to gather context.

Generate a **complete, copy-paste ready** resume prompt containing:

## 1. Context Snapshot
- Current context usage (check statusline or transcript for token count)
- Session duration and turn count

## 2. Original Goal
From `session_state.original_goal` or infer from conversation history.

## 3. Progress Summary
From `session_state.progress_log` or summarize what was accomplished.

## 4. Files Modified
List from `session_state.files_edited` and `session_state.files_created`.

## 5. Key Decisions Made
Document important choices and their rationale from this session.

## 6. Current Blockers
From `session_state.errors_unresolved` and `session_state.handoff_blockers`.

## 7. Beads Status
Run `bd list --status=open` and `bd list --status=in_progress` to capture task state.

## 8. Git State
Run `git status --short` and `git diff --stat` to capture uncommitted work.

## 9. Memory Files Consulted
Filter `session_state.files_read` for paths containing `/.claude/memory/`.

## 10. Evidence Gathered
From `session_state.evidence_ledger`.

## 11. Approaches Tried
From `session_state.approach_history` - what worked and what failed.

## 12. Work Queue
From `session_state.work_queue` - discovered work items.

## 13. Next Steps (Priority Order)
From `session_state.handoff_next_steps` or derive from current state.

## 14. Critical Context
Any information the next session MUST know:
- Environment variables or config needed
- Ports/services that should be running
- API keys location or auth setup
- Workarounds or gotchas discovered

---

**Output Format:**

Output the resume prompt in a clearly marked block:

```
---BEGIN RESUME PROMPT---
[Full resume content here, ready to paste into new session]
---END RESUME PROMPT---
```

Make it comprehensive but not redundant. The goal is for the next session to pick up exactly where this one left off.
