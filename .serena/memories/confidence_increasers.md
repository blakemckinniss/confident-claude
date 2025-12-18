# Confidence Increasers

**51 increaser classes** that apply automatic rewards for positive behaviors.

## Due Diligence Rewards

| Increaser | Delta | Trigger | Cooldown |
|-----------|-------|---------|----------|
| `file_read` | +1 | Read tool (gathering evidence) | None |
| `productive_bash` | +1 | ls, pwd, which, tree, stat (inspection) | None |
| `research` | +2 | WebSearch, WebFetch, crawl4ai | None |
| `search_tool` | +2 | Grep, Glob, Task (understanding) | None |
| `lint_pass` | +3 | ruff check, eslint, cargo clippy passes | None |
| `small_diff` | +3 | Diffs under 400 LOC (focused changes) | None |
| `git_explore` | +3 | git log/diff/status/show/blame | 5 turns |
| `git_commit` | +3 | Committed work with message | None |
| `custom_script` | +5 | ~/.claude/ops/* scripts | None |
| `test_pass` | +5 | pytest/jest/cargo test passes | None |
| `build_success` | +5 | npm build/cargo build/tsc succeeds | None |
| `memory_consult` | +10 | Read ~/.claude/memory/ files | None |
| `bead_create` | +10 | bd create/update (task tracking) | None |
| `rules_update` | +15 | Edit CLAUDE.md or /rules/ (framework DNA) | 1 turn |

## User Interaction Rewards

| Increaser | Delta | Trigger | Cooldown |
|-----------|-------|---------|----------|
| `ask_user` | +8 | AskUserQuestion (epistemic humility) | 8 turns |
| `user_ok` | +2 | Short positive feedback ("ok", "thanks") | None |
| `trust_regained` | +15 | User says "CONFIDENCE_BOOST_APPROVED" | None |

## Efficiency Rewards

| Increaser | Delta | Trigger | Cooldown |
|-----------|-------|---------|----------|
| `parallel_tools` | +2 | Using multiple tools in parallel | None |
| `efficient_search` | +2 | Targeted search patterns | None |
| `batch_fix` | +3 | Fixing multiple issues in one edit | None |
| `direct_action` | +2 | Action without excessive preamble | None |
| `chained_commands` | +2 | Efficient command chaining | None |
| `targeted_read` | +1 | Reading specific file sections | None |
| `subagent_delegation` | +2 | Using Task tool for delegation | None |

## Completion Quality Rewards

| Increaser | Delta | Trigger | Cooldown |
|-----------|-------|---------|----------|
| `premise_challenge` | +5 | Suggested existing solution or challenged build-vs-buy | None |
| `bead_close` | +5 | `bd close` command (completing tracked work) | None |
| `first_attempt_success` | +3 | Task completed without retry/correction | None |
| `dead_code_removal` | +3 | Removing unused code/imports | None |
| `scoped_change` | +2 | Changes stayed within requested scope | None |
| `external_validation` | +5 | Using `mcp__pal__*` tools for validation | None |

## Workflow Signals

| Increaser | Delta | Trigger | Cooldown |
|-----------|-------|---------|----------|
| `pr_created` | +5 | `gh pr create` succeeds | None |
| `issue_closed` | +3 | `gh issue close` succeeds | None |
| `review_addressed` | +5 | PR review comments resolved | None |
| `ci_pass` | +5 | `gh run`/`gh pr checks` shows passing CI | None |
| `merge_complete` | +5 | `gh pr merge` succeeds | None |

## Code Quality Improvements

| Increaser | Delta | Trigger | Cooldown |
|-----------|-------|---------|----------|
| `docstring_addition` | +2 | Adding docstrings to functions | None |
| `type_hint_addition` | +2 | Adding type hints | None |
| `complexity_reduction` | +3 | Reducing cyclomatic complexity | None |
| `security_fix` | +5 | Fixing security vulnerabilities | None |
| `dependency_removal` | +3 | Removing unused dependencies | None |
| `config_externalization` | +2 | Moving hardcoded values to config | None |

## Framework Alignment Rewards (Micro-bonuses)

| Increaser | Delta | Trigger | Cooldown |
|-----------|-------|---------|----------|
| `crawl4ai_used` | +1 | mcp__crawl4ai__* tools (preferred web scraping) | None |
| `serena_symbolic` | +1 | serena find_symbol, get_symbols_overview | None |
| `beads_touch` | +1 | Any `bd` command (task tracking) | None |
| `mcp_integration` | +1 | PAL, Playwright, Filesystem, Serena MCPs | None |
| `ops_tool` | +1 | ~/.claude/ops/* scripts | None |
| `agent_delegation` | +1 | Task tool for delegation | None |

## Scripting Rewards

| Increaser | Delta | Trigger | Cooldown |
|-----------|-------|---------|----------|
| `tmp_script_created` | +3 | Create .py in ~/.claude/tmp/ | None |
| `tmp_script_run` | +2 | Run script from ~/.claude/tmp/ | None |
| `background_script` | +3 | Run script with run_in_background=true | None |

## Self-Improvement Reward

| Increaser | Delta | Trigger | Cooldown |
|-----------|-------|---------|----------|
| `framework_self_heal` | +10 | Self-surgery: fixing reducers/hooks/confidence | None |

## Notes

- **Per-turn cap**: Maximum +15 total increase per turn normally
- **Below stasis (< 80%)**: Positive cap raised to +30 for faster legitimate recovery
- **Streak multiplier**: Consecutive successes earn multiplied rewards (1.25x/1.5x/2x)

## Location

- **Definitions**: `lib/_confidence_increasers.py`
- **Applied in**: `hooks/post_tool_use_runner.py`

*Updated: 2025-12-17*
