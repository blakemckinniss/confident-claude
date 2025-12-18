---
description: 🔍 Everything Search - Instant file search across Windows + WSL2
argument-hint: <query> [options]
allowed-tools: Bash
---

# Everything Search (Voidtools)

Instant file search across entire PC using Everything's indexed database.

**Argument:** $ARGUMENTS

## Usage

| Example | Description |
|---------|-------------|
| `/find CLAUDE.md` | Find files named CLAUDE.md |
| `/find *.py -n 20` | Find Python files (limit 20) |
| `/find ext:pdf` | Find all PDFs |
| `/find "project report"` | Find files with spaces in name |
| `/find path:D:\Games *.exe` | Search in specific path |
| `/find dm:today` | Files modified today |
| `/find size:>100mb` | Files larger than 100MB |

## Search Syntax

| Syntax | Description |
|--------|-------------|
| `ext:pdf` | Extension filter |
| `path:C:\folder` | Search in path |
| `dm:today` | Modified today |
| `dm:thisweek` | Modified this week |
| `size:>1gb` | Size greater than |
| `folder:` | Only folders |
| `file:` | Only files |
| `*.txt` | Wildcard match |
| `"exact phrase"` | Exact name match |

## Options

| Flag | Description |
|------|-------------|
| `-n <num>` | Limit results (default: 50) |
| `-s` | Sort by size |
| `-r` | Use regex |
| `-i` | Case sensitive |
| `-w` | Whole word match |
| `-p` | Match full path |

## Execution

```bash
/mnt/c/Windows/System32/cmd.exe /c "cd /d C:\Users\Blake && C:\Users\Blake\AppData\Local\Microsoft\WindowsApps\es.exe <query>"
```

## Notes

- Everything must be running (or have run once to build index)
- Searches Windows drives AND WSL2 filesystems
- Results are instant (indexed, not live scan)
- WSL paths shown as `\\wsl.localhost\Ubuntu\...`

## Protocol

1. If no arguments, show usage examples
2. If arguments provided, run: `es.exe $ARGUMENTS`
3. If no `-n` flag in arguments, add `-n 50` to limit output
4. Present results clearly, converting WSL paths to Linux format when helpful
