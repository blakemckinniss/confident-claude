# Operational Tools Reference

Quick reference for framework tools. Use when you need tool syntax.

## Mastermind (Multi-Model Routing)

| Need | Tool/Action |
|------|-------------|
| Force complex planning | Prefix prompt with `^` |
| Check current phase | `cat ~/.claude/config/mastermind.json \| jq .rollout_phase` |
| Change rollout phase | `~/.claude/ops/mastermind_rollout.py --phase N` |
| Regenerate capability index | `~/.claude/ops/capability_inventory.py` |
| View capability registry | `~/.claude/capabilities/registry.yaml` |

### PAL Tool Suggestions (from Mastermind)

| Task Type | Suggested Tool |
|-----------|----------------|
| Debugging | `mcp__pal__debug` |
| Planning | `mcp__pal__planner` |
| Code review | `mcp__pal__codereview` |
| Architecture | `mcp__pal__consensus` |
| API/docs lookup | `mcp__pal__apilookup` |
| Pre-commit | `mcp__pal__precommit` |
| General | `mcp__pal__chat` |

See `mastermind.md` for full reference.

## Core Tools

| Need | Tool |
|------|------|
| Task tracking | `bd` (beads - see beads.md) |
| Complex decision | `council "<proposal>"` |
| Risk assessment | `oracle --persona [judge\|critic] "<proposal>"` |
| Problem decomposition | `think "<problem>"` |
| Web/docs lookup | `research "<query>"` |
| Documentation | `docs "<library>"` |
| Runtime API inspection | `probe "<object_path>"` |
| Code structure | `xray --type <type> --name <Name>` |
| File verification | `verify file_exists "<path>"` |
| Security check | `audit <file>` |
| Completeness check | `void <file>` |
| Pre-commit | `upkeep` |

## Confidence System

| Need | Tool |
|------|------|
| Record false positive | `fp.py <reducer> [reason]` |
| Check confidence | Shown in statusline |
| Dispute reducer (user) | Say `FP: <reducer>` or `dispute <reducer>` |
| Force boost (user) | Say `CONFIDENCE_BOOST_APPROVED` |

See `confidence.md` for full reference.

## Context & Session Management

| Need | Tool |
|------|------|
| Session handoff | `/resume` - Generate comprehensive resume prompt |
| Context warning | Auto at 75% - Non-blocking heads up |
| Context exhaustion | Auto at 85% - Forces resume prompt generation |

## Memory & Evidence

| Need | Tool |
|------|------|
| Memory store | `remember add [lessons\|decisions] "<text>"` |
| Memory recall | `spark "<topic>"` |
| Evidence tracking | `evidence review` |

## System Tools

| Need | Tool |
|------|------|
| System binaries | `inventory` |
| System health | `sysinfo` |
| Disk cleanup | `housekeeping --status` or `--execute` |
| Browser automation | `mcp__playwright__*` (navigate, click, type, snapshot, screenshot, evaluate) |

## External LLM (PAL MCP)

| Need | Tool |
|------|------|
| Deep analysis | `mcp__pal__thinkdeep` |
| External debugging | `mcp__pal__debug` |
| Code review | `mcp__pal__codereview` |
| Multi-model consensus | `mcp__pal__consensus` |
| Challenge assumptions | `mcp__pal__challenge` |
| API docs lookup | `mcp__pal__apilookup` |
| External chat | `mcp__pal__chat` |

**🔥 continuation_id:** All PAL tools return this - **reuse it** to preserve reasoning context across calls and sessions. Look for `🔥PAL:` after compaction.

## Integration Synergy

| Need | Tool |
|------|------|
| New project | `/new-project <name> [--description DESC]` |
| Serena status | `/serena status` |
| Symbol impact | `/si <symbol>` |
| File validation | `/sv <file>` |
| Project memories | `/sm [search]` |
| Unified context | `unified_context.py` |
| Install check | `integration_install.py --check` |
| Agent claim bead | `bead_claim.py <bead_id>` |
| Agent release bead | `bead_release.py <bead_id>` |
| Orphan check | `bead_orphan_check.py [--all]` |
| Lifecycle daemon | `bead_lifecycle_daemon.py [--daemon]` |

See `.claude/memory/__integration_synergy.md` for architecture details.

## Expensive Tools (Use Sparingly)

| Tool | Cost |
|------|------|
| `swarm "<task>"` | Burns OpenRouter credits |
| `oracle` | External API calls |
| `orchestrate` | Claude API code_execution |

## CLI Shortcuts

```bash
# Python environment (auto-detects venv):
~/.claude/hooks/py ~/.claude/ops/<tool>.py <args>

# Direct invocation:
~/.claude/.venv/bin/python ~/.claude/ops/audit.py <path>
```
