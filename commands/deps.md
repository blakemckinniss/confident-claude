Check all .claude dependencies (API keys, Python packages, binaries, Node.js, MCP servers)

Run `~/.claude/.venv/bin/python ~/.claude/hooks/dependency_check.py --verbose`

Options:
- `--verbose` / `-v`: Full detailed report
- `--fix`: Auto-install missing Python packages
- `--json`: Machine-readable output
- `--quiet` / `-q`: Only show if issues exist
