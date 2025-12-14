# Suggested Commands

## Python Environment

```bash
# Use the venv Python (preferred)
~/.claude/.venv/bin/python script.py

# Or use the py wrapper (auto-detects venv)
~/.claude/hooks/py ~/.claude/ops/script.py
```

## Linting & Code Quality

```bash
# Lint Python files
ruff check ~/.claude/hooks/
ruff check ~/.claude/ops/
ruff check ~/.claude/lib/

# Lint specific file
ruff check path/to/file.py

# Auto-fix lint issues
ruff check --fix path/to/file.py

# Format code
ruff format path/to/file.py
```

## Testing

```bash
# Run all tests
~/.claude/.venv/bin/pytest ~/.claude/tests/

# Run specific test file
~/.claude/.venv/bin/pytest ~/.claude/tests/test_hook_result.py

# Run with verbose output
~/.claude/.venv/bin/pytest -v ~/.claude/tests/
```

## Security & Quality Audits

```bash
# Security audit with bandit
bandit -r ~/.claude/ops/

# Code complexity analysis
radon cc ~/.claude/lib/ -a

# Use built-in audit tool
~/.claude/hooks/py ~/.claude/ops/audit.py <file>

# Use void tool for completeness check
~/.claude/hooks/py ~/.claude/ops/void.py <file>
```

## Task Tracking (Beads)

```bash
# Find available work
bd ready

# Create task
bd create --title="Description" --type=task|bug|feature

# Start work
bd update <id> --status=in_progress

# Complete task
bd close <id>

# View all open issues
bd list --status=open

# Show blocked issues
bd blocked

# Project health
bd stats
bd doctor
```

## Git Operations

```bash
# Standard git workflow
git status
git diff
git add <files>
git commit -m "message"

# Sync beads from main (for ephemeral branches)
bd sync --from-main
```

## System Utilities

```bash
# List directory
ls -la

# Find files
find ~/.claude -name "*.py"

# Search in files
grep -r "pattern" ~/.claude/

# View file
cat path/to/file
```

## Running Hooks Manually (for testing)

```bash
# Post tool use runner
echo '{"tool":"Bash","result":"test"}' | ~/.claude/hooks/py ~/.claude/hooks/post_tool_use_runner.py

# Pre tool use runner  
echo '{"tool":"Edit","input":{}}' | ~/.claude/hooks/py ~/.claude/hooks/pre_tool_use_runner.py
```
