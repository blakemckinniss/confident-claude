# Confidence Increasers

## Overview

Increasers are reward mechanisms that boost confidence based on positive signals. They encourage due diligence, research, and verification.

## Location
- **Definition**: `lib/_confidence_increasers.py`
- **Applied in**: `hooks/post_tool_use_runner.py`

## Due Diligence Rewards

| Increaser | Delta | Trigger |
|-----------|-------|---------|
| `file_read` | +1 | Read tool (gathering evidence) |
| `productive_bash` | +1 | ls, pwd, which, tree, stat (inspection commands) |
| `research` | +2 | WebSearch, WebFetch, crawl4ai |
| `search_tool` | +2 | Grep, Glob, Task (understanding codebase) |
| `efficient_search` | +2 | Found target on first search attempt |
| `lint_pass` | +3 | ruff check, eslint, cargo clippy passes |
| `small_diff` | +3 | Diffs under 400 LOC (focused changes) |
| `rules_update` | +3 | Edit CLAUDE.md or /rules/ |
| `parallel_tools` | +3 | Used parallel tool calls efficiently |
| `git_explore` | +3 | git log/diff/status/show/blame |
| `git_commit` | +3 | Committed work with message |
| `batch_fix` | +3 | Fixed multiple related issues together |

## Verification Rewards

| Increaser | Delta | Trigger |
|-----------|-------|---------|
| `test_pass` | +5 | pytest/jest/cargo test passes |
| `build_success` | +5 | npm build/cargo build/tsc succeeds |
| `custom_script` | +5 | Ran ~/.claude/ops/* scripts (audit, void, etc.) |
| `external_validation` | +5 | Using `mcp__pal__*` tools for validation |

## Task Management Rewards

| Increaser | Delta | Trigger |
|-----------|-------|---------|
| `bead_create` | +10 | bd create/update (task tracking) |
| `bead_close` | +5 | bd close (completing tracked work) |
| `memory_consult` | +10 | Read ~/.claude/memory/ files |

## User Interaction Rewards

| Increaser | Delta | Trigger |
|-----------|-------|---------|
| `user_ok` | +2 | Short positive feedback ("ok", "thanks") |
| `ask_user` | +8 | AskUserQuestion (epistemic humility) |
| `trust_regained` | +15 | User says "CONFIDENCE_BOOST_APPROVED" |

## Quality Behavior Rewards

| Increaser | Delta | Trigger |
|-----------|-------|---------|
| `first_attempt_success` | +3 | Task completed without retry/correction |
| `dead_code_removal` | +3 | Removing unused code/imports |
| `scoped_change` | +2 | Changes stayed within requested scope |
| `premise_challenge` | +5 | Suggested existing solution or challenged build-vs-buy |

## Workflow Rewards

| Increaser | Delta | Trigger |
|-----------|-------|---------|
| `pr_created` | +5 | `gh pr create` succeeds |
| `issue_closed` | +3 | `gh issue close` succeeds |
| `review_addressed` | +5 | PR review comments resolved |
| `ci_pass` | +5 | `gh run`/`gh pr checks` shows passing CI |
| `merge_complete` | +5 | `gh pr merge` succeeds |

## Class Structure

```python
@dataclass
class ConfidenceIncreaser:
    name: str
    delta: int  # Positive value
    description: str

    def should_trigger(self, context: dict, state: SessionState) -> bool:
        # Specific trigger logic
        pass
```

## Rate Limiting

- **Per-turn cap**: Maximum +15 per turn normally
- **Recovery mode**: When below 80%, cap raised to +30
- Encourages steady accumulation over gaming

## Streak System

Consecutive successes earn multiplied rewards:
- 2 consecutive: 1.25x
- 3 consecutive: 1.5x
- 5+ consecutive: 2.0x

Resets on any reducer firing.
