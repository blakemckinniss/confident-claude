---
name: git-workflow
description: |
  Git operations, commits, branches, merging, pull requests, conflict resolution,
  version control, history, blame, diff, stash, rebase, cherry-pick, reset,
  git status, git log, staging, unstaging, amending commits, PR workflow.

  Trigger phrases: commit this, create PR, merge branch, resolve conflict,
  git status, what changed, git diff, git log, git blame, who changed this,
  when was this changed, revert change, undo commit, reset to, checkout branch,
  create branch, delete branch, stash changes, cherry-pick, rebase onto,
  squash commits, amend commit, push changes, pull latest, fetch upstream,
  git history, commit message, staged changes, unstaged changes, untracked files,
  merge conflict, conflict markers, accept theirs, accept mine, PR review,
  pull request, code review, approve PR, request changes.
---

# Git Workflow

Git operations and version control patterns.

## Quick Commands

| Action | Command |
|--------|---------|
| Status | `git status` |
| Changes | `git diff` |
| History | `git log --oneline -20` |
| Blame | `git blame <file>` |
| Stash | `git stash` / `git stash pop` |

## Commit Workflow

### Before Committing
```bash
upkeep  # Run pre-commit checks
```

### Smart Commit
```bash
/commit [message]  # Stage, commit, offer push
```

### Manual Commit
```bash
git add <files>
git commit -m "type: description"
```

## Branch Operations

```bash
# Create and switch
git checkout -b feature/name

# Switch existing
git checkout main

# Delete
git branch -d feature/name
```

## PR Workflow

```bash
# Create PR
gh pr create --title "..." --body "..."

# List PRs
gh pr list

# View PR
gh pr view <number>

# Merge PR
gh pr merge <number>
```

## Conflict Resolution

1. Identify conflicts: `git status`
2. Open conflicted files
3. Look for `<<<<<<<`, `=======`, `>>>>>>>`
4. Edit to resolve
5. Stage resolved: `git add <file>`
6. Complete merge: `git commit`

## History Investigation

```bash
# Who changed this line
git blame <file>

# When was function added
git log -p -S "function_name" -- <file>

# Changes between commits
git diff <commit1>..<commit2>

# File at specific commit
git show <commit>:<file>
```

## Recovery

```bash
# Undo last commit (keep changes)
git reset --soft HEAD~1

# Discard file changes
git checkout -- <file>

# Recover deleted branch
git reflog  # Find commit
git checkout -b recovered <commit>
```

## Beads Integration

```bash
bd sync --from-main  # Pull beads from main (ephemeral branches)
bd sync --status     # Check sync status
```
