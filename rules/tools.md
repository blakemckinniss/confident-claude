# Operational Tools Reference

Quick reference for framework tools. Use when you need tool syntax.

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
| Browser/CDP | `bdg <cmd>` (start/stop/status/page/dom/eval/network) |

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
