# Scripts Directory

User-run scripts for setup and maintenance. Run manually after cloning.

## Quick Start

```bash
./scripts/bootstrap.sh           # First-time setup wizard
./scripts/bootstrap.sh --check   # Health check (read-only)
./scripts/bootstrap.sh --fix     # Auto-fix issues
./scripts/bootstrap.sh --help    # Full help
```

## bootstrap.sh - Setup Wizard

Comprehensive setup for getting the framework running from a fresh clone.

### What It Checks & Fixes

| Step        | Check               | Auto-Fix           |
| ----------- | ------------------- | ------------------ |
| Python      | Version 3.10+, venv | Creates venv       |
| Packages    | requirements.txt    | Installs missing   |
| Node.js     | Version 18+ (MCP)   | Shows instructions |
| Binaries    | git, ruff, bd, jq   | Shows hints        |
| Directories | Framework structure | Creates missing    |
| Hooks       | ~/.claude.json      | Shows config       |
| API Keys    | Environment vars    | Shows setup        |
| Plugins     | Install paths       | Reports issues     |

### Modes

- **Interactive** (default): Asks before changes
- **--check**: Read-only health check
- **--fix**: Auto-fix without prompting
- **--minimal**: Venv + packages only

## Adding New Scripts

1. `chmod +x script.sh`
2. Add shebang: `#!/usr/bin/env bash`
3. Include `--help` flag
4. Keep standalone

## Directory Reference

| Directory  | Purpose           | Runs           |
| ---------- | ----------------- | -------------- |
| `scripts/` | Manual scripts    | User runs      |
| `hooks/`   | Claude Code hooks | Auto on events |
| `ops/`     | Operational tools | Claude invokes |
| `config/`  | Setup scripts     | One-time       |
