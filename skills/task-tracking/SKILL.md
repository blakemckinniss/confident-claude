---
name: task-tracking
description: |
  Track tasks, create issue, todo list, what needs to be done, task management,
  beads, work items, blockers, dependencies, project tracking, issue tracker,
  kanban, backlog, sprint, agile, work queue, ticket system.

  Trigger phrases: track this task, create an issue, what needs to be done,
  todo list, blockers, dependencies, close this issue, mark complete,
  what's left, remaining work, open tasks, in progress, backlog,
  prioritize, next task, available work, ready to work, unblocked,
  task status, issue status, work item, ticket, bug report, feature request,
  epic, story, subtask, milestone, deadline, due date, assigned to,
  project board, kanban board, task board, work tracking, progress,
  done, completed, finished, closed, resolved, shipped, deployed,
  blocked by, depends on, waiting for, prerequisite, follow-up task.
---

# Task Tracking

Beads (`bd`) task tracking. TodoWrite is forbidden.

## Quick Reference
| Action | Command |
|--------|---------|
| Find work | `bd ready` |
| List open | `bd list --status=open` |
| List active | `bd list --status=in_progress` |
| Create | `bd create --title="..." --type=task` |
| View | `bd show <id>` |
| Start | `bd update <id> --status=in_progress` |
| Complete | `bd close <id>` |
| Close many | `bd close <id1> <id2>` |

## Dependencies
```bash
bd dep add <A> <B>    # A depends on B
bd blocked            # View blocked
bd show <id>          # See blockers
```

## Health
```bash
bd stats              # Statistics
bd doctor             # Health check
bd sync --from-main   # Sync
```

## Slash Command
- `/bd <cmd>` - All beads commands

## Session Workflow
```bash
bd ready                              # Find work
bd update <id> --status=in_progress   # Claim
# ... do work ...
bd close <id>                         # Complete
bd sync --from-main                   # Sync
```
