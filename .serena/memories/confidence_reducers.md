# Confidence Reducers

**59 reducer classes** that apply automatic penalties based on detected patterns.

## Core Reducers (Detect Real Problems)

| Reducer | Delta | Trigger | Cooldown |
|---------|-------|---------|----------|
| `tool_failure` | -5 | Bash exit != 0 | 1 turn |
| `cascade_block` | -15 | Same hook blocks 3+ times in 5 turns | 5 turns |
| `sunk_cost` | -20 | 3+ consecutive failures on same approach | 5 turns |
| `user_correction` | -10 | User says "wrong", "incorrect", "fix that" | 3 turns |
| `goal_drift` | -8 | < 20% keyword overlap with original goal | 8 turns |
| `edit_oscillation` | -12 | Same file edited 3+ times in 5 turns | 5 turns |
| `contradiction` | -10 | Contradictory claims detected | 5 turns |
| `follow_up_question` | -3 | User asks clarifying question (indicates unclear response) | 3 turns |

## Bad Behavior Reducers (BANNED Patterns)

| Reducer | Delta | Trigger | Cooldown |
|---------|-------|---------|----------|
| `backup_file` | -10 | Creating .bak, .backup, .old files | 1 turn |
| `version_file` | -10 | Creating _v2, _new, _copy files | 1 turn |
| `markdown_creation` | -8 | Creating .md files (except memory/docs) | 1 turn |
| `overconfident_completion` | -15 | "100% done", "completely finished" | 3 turns |
| `deferral` | -12 | "skip for now", "come back later" | 3 turns |
| `apologetic` | -5 | "sorry", "my mistake", "I apologize" | 2 turns |
| `sycophancy` | -8 | "you're absolutely right", "great point" | 2 turns |
| `unresolved_antipattern` | -10 | Mentioning issues without fixing | 3 turns |
| `spotted_ignored` | -8 | Acknowledging problem but not addressing | 3 turns |
| `debt_bash` | -10 | --force, --hard, --no-verify commands | 1 turn |
| `large_diff` | -8 | Diffs over 400 LOC | 1 turn |
| `hook_block` | -5 | When hooks block actions | 1 turn |

## Sequential/Efficiency Reducers

| Reducer | Delta | Trigger | Cooldown |
|---------|-------|---------|----------|
| `sequential_repetition` | -5 | Repeating same action type 3+ times | 3 turns |
| `sequential_when_parallel` | -8 | Sequential Task calls when parallel possible | 3 turns |
| `sequential_file_ops` | -1 | 3+ Read/Edit/Write without batching | 3 turns |

## Verification Reducers

| Reducer | Delta | Trigger | Cooldown |
|---------|-------|---------|----------|
| `unbacked_verification_claim` | -10 | Claiming "verified" without evidence | 3 turns |
| `fixed_without_chain` | -8 | Claiming "fixed" without running tests | 3 turns |
| `unverified_edits` | -5 | Multiple edits without verification | 5 turns |
| `git_spam` | -3 | Excessive git status/log calls | 5 turns |

## Code Quality Reducers

| Reducer | Delta | Trigger | Cooldown |
|---------|-------|---------|----------|
| `placeholder_impl` | -8 | `pass`, `...`, NotImplementedError in new code | 1 turn |
| `silent_failure` | -8 | `except: pass` or `except Exception: pass` | 1 turn |
| `hallmark_phrase` | -3 | AI-speak: "certainly", "I'd be happy to" | 2 turns |
| `scope_creep` | -8 | "while I'm at it", "might as well" | 3 turns |
| `incomplete_refactor` | -10 | Partial renames/changes | 3 turns |
| `deep_nesting` | -3 | Creating code with >4 levels of nesting | 2 turns |
| `long_function` | -3 | Creating functions >50 lines | 2 turns |
| `mutable_default_arg` | -5 | Using mutable default arguments | 1 turn |
| `import_star` | -3 | Using `from x import *` | 1 turn |
| `bare_raise` | -3 | Bare `raise` in wrong context | 1 turn |
| `commented_code` | -3 | Leaving large blocks of commented code | 2 turns |

## Token Efficiency Reducers

| Reducer | Delta | Trigger | Cooldown |
|---------|-------|---------|----------|
| `reread_unchanged` | -2 | Re-reading file that hasn't changed | 3 turns |
| `verbose_preamble` | -3 | Long explanations before action | 2 turns |
| `huge_output_dump` | -5 | Outputting >500 lines without summary | 2 turns |
| `redundant_explanation` | -3 | Repeating explanations already given | 3 turns |
| `trivial_question` | -5 | Asking questions with obvious answers | 3 turns |
| `obvious_next_steps` | -3 | Stating obvious next steps user would do anyway | 2 turns |

## Test Coverage Reducers

| Reducer | Delta | Trigger | Cooldown |
|---------|-------|---------|----------|
| `test_ignored` | -5 | Modified test files without running tests | 5 turns |
| `change_without_test` | -3 | Production code changed without test coverage | 5 turns |

## Framework Alignment Reducers (Micro-penalties)

| Reducer | Delta | Trigger | Cooldown |
|---------|-------|---------|----------|
| `webfetch_over_crawl` | -1 | WebFetch used (prefer crawl4ai) | None |
| `websearch_basic` | -1 | WebSearch used (prefer crawl4ai.ddg_search) | None |
| `todowrite_bypass` | -2 | TodoWrite used (beads required) | None |
| `raw_symbol_hunt` | -1 | Reading code file without serena activation | None |
| `grep_over_serena` | -1 | Grep on code when serena is active | None |
| `file_reedit` | -2 | Re-editing file already edited this session | None |

## Scripting Escape Hatch Reducers

| Reducer | Delta | Trigger | Cooldown |
|---------|-------|---------|----------|
| `complex_bash_chain` | -2 | 3+ pipes/semicolons/&& in bash command | 2 turns |
| `bash_data_transform` | -3 | Complex awk/sed/jq expressions | 2 turns |

## Stuck Loop Reducers

| Reducer | Delta | Trigger | Cooldown |
|---------|-------|---------|----------|
| `stuck_loop` | -15 | Same file edited 4+ times without research | 5 turns |
| `no_research_debug` | -10 | Extended debugging without web search/external LLM | 8 turns |

## Mastermind Drift Reducers

| Reducer | Delta | Trigger | Cooldown |
|---------|-------|---------|----------|
| `mastermind_file_drift` | -5 | Touching files outside blueprint scope | 5 turns |
| `mastermind_test_drift` | -8 | 3+ consecutive test failures | 5 turns |
| `mastermind_approach_drift` | -10 | Significant pivot from planned approach | 8 turns |

## Location

- **Definitions**: `lib/_confidence_reducers.py`
- **Applied in**: `hooks/post_tool_use_runner.py`

*Updated: 2025-12-17*
