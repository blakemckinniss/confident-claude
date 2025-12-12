---
paths: "**/*.py"
---

# Python Development Rules

## Style & Structure

- Use type hints for all function signatures
- Prefer `pathlib.Path` over `os.path`
- Use f-strings over `.format()` or `%`
- Imports: stdlib, blank line, third-party, blank line, local
- Max line length: 100 chars (ruff default)

## Error Handling

- Prefer `assert` and stack traces over defensive `try/except`
- Crash early - don't suppress errors
- If catching exceptions, be specific - never bare `except:`

## Dependencies

- FORBIDDEN from adding dependencies until stdlib fails twice
- Check if stdlib has equivalent before proposing packages
- Use venv at `~/.claude/.venv/`

## Testing

- Tests live in `tests/` mirroring `src/` structure
- Use pytest, not unittest
- Name test files `test_<module>.py`
- Name test functions `test_<behavior>()`

## File Operations

- Always use `with` for file handles
- Use `pathlib` for path manipulation
- Check file exists before reading (Map Before Territory)

## Interpreter

Use the framework venv:
```bash
~/.claude/.venv/bin/python script.py
# Or via wrapper:
~/.claude/hooks/py script.py
```
