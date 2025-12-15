# Manual Scripts

User-run scripts for ad-hoc purposes. These are **not** automated hooks—run them manually when needed.

## Scripts

### `bootstrap.sh`

Run after cloning the repository to set up all dependencies.

```bash
# Full bootstrap (creates venv, installs deps)
./scripts/bootstrap.sh

# Check what's missing without installing
./scripts/bootstrap.sh --check

# Auto-install missing Python packages
./scripts/bootstrap.sh --fix

# Verbose output
./scripts/bootstrap.sh --verbose
```

**What it does:**
1. Creates Python virtual environment at `.venv/`
2. Installs dependencies from `requirements.txt`
3. Checks for required binaries (git, python3)
4. Validates critical directories exist
5. Runs the full dependency check

## Adding New Scripts

When adding scripts to this folder:

1. **Make executable**: `chmod +x script.sh`
2. **Add shebang**: `#!/usr/bin/env bash` or `#!/usr/bin/env python3`
3. **Document usage**: Include `--help` flag
4. **Keep standalone**: Don't assume hooks are running

## Difference from Other Directories

| Directory | Purpose | Runs |
|-----------|---------|------|
| `scripts/` | Manual user scripts | User runs manually |
| `hooks/` | Claude Code hooks | Automatically on events |
| `ops/` | Operational tools | Claude invokes via commands |
| `config/` | Setup scripts | One-time configuration |
