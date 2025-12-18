---
description: 🔬 Serena Verify - Test language server setup and diagnose issues
allowed-tools: mcp__serena__*, Bash, Read, Grep
---

# Serena Language Server Verification

Verify that Serena's language server is properly configured for the current project.

## Verification Steps

1. **Check project config exists**
   - Look for `.serena/project.yml` in the project root
   - If missing, suggest running onboarding first

2. **Activate the project**
   ```
   mcp__serena__activate_project with project path
   ```

3. **Test find_symbol**
   ```
   mcp__serena__find_symbol with a common pattern like "main" or "index"
   ```

4. **Diagnose failures**
   If find_symbol fails with "language server manager is not initialized":

   **For Python projects:**
   ```bash
   # Check if pyright is installed in project venv
   <project>/.venv/bin/pip list | grep pyright

   # If missing, install it:
   <project>/.venv/bin/pip install pyright
   ```

   **For TypeScript projects:**
   - Usually works out of the box
   - Check if node_modules exists: `ls <project>/node_modules`

5. **Re-activate and verify**
   After fixing, re-activate the project and test find_symbol again.

## Common Issues

| Language | Issue | Fix |
|----------|-------|-----|
| Python | `No module named 'pyright'` | `pip install pyright` in project venv |
| Python | Wrong Python interpreter | Check `.serena/project.yml` or venv path |
| TypeScript | Missing node_modules | Run `npm install` |
| Any | LSP timeout | Restart Claude Code session |

## Usage

Run this command from within a project directory that has `.serena/` configured:

```
/serena-verify
```

If no project path argument provided, uses current working directory.
