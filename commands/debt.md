---
description: 🧹 Tech Debt Auditor - Scan for debt, anti-patterns, and code smells
argument-hint: [path_or_focus]
allowed-tools: Bash, Read, Glob, Grep, Task, mcp__serena__*
---

Perform a comprehensive technical debt audit on the codebase.

## Input

Use `$ARGUMENTS` as:
- A specific path/file to audit (e.g., `src/`, `api/handlers.py`)
- A focus area (e.g., "authentication", "database", "tests")
- If empty, audit the entire project from current directory

## Audit Categories

### 1. Code Debt Markers
Scan for explicit debt markers:
```
TODO, FIXME, HACK, XXX, TEMP, WORKAROUND, KLUDGE, BUG, REFACTOR
```

### 2. Anti-Patterns
Detect common anti-patterns:
- **God objects/files** - Files > 500 lines, classes with > 10 methods
- **Shotgun surgery** - Same change needed in many places
- **Feature envy** - Methods that use other class's data excessively
- **Dead code** - Unused imports, functions, variables
- **Copy-paste code** - Duplicate logic blocks
- **Magic numbers/strings** - Hardcoded values without constants
- **Deep nesting** - > 4 levels of indentation
- **Long parameter lists** - Functions with > 5 parameters
- **Primitive obsession** - Using primitives instead of small objects

### 3. Structural Issues
- Circular dependencies
- Missing type hints (Python) / any types (TypeScript)
- Inconsistent naming conventions
- Missing error handling
- Broad exception catches (`except:`, `catch (e)`)
- Empty catch blocks

### 4. Test Debt
- Missing test files for source files
- Skipped/disabled tests
- Tests without assertions
- Low coverage indicators

### 5. Dependency Debt
- Outdated dependencies (check package.json, requirements.txt, Cargo.toml)
- Unused dependencies
- Version pinning issues
- Security vulnerabilities (if lockfile available)

## Output Format

Report findings grouped by severity:

```
## 🔴 Critical (Fix Now)
- [file:line] [category] Description

## 🟠 High (Fix Soon)
- [file:line] [category] Description

## 🟡 Medium (Plan to Fix)
- [file:line] [category] Description

## 🟢 Low (Track)
- [file:line] [category] Description

## 📊 Summary
- Total issues: N
- Critical: N | High: N | Medium: N | Low: N
- Estimated cleanup effort: S/M/L
- Top 3 quick wins (low effort, high impact)
```

## Execution Strategy

1. **Detect project type** - Check for package.json, requirements.txt, Cargo.toml, go.mod
2. **Use Serena** if active for semantic analysis (symbol usage, dead code)
3. **Use Grep** for pattern-based scanning (TODOs, anti-patterns)
4. **Use Glob** to find files and assess structure
5. **Prioritize** findings by:
   - Severity (bugs > maintainability > style)
   - Frequency (repeated issues score higher)
   - Location (core code > tests > scripts)

## Do NOT
- Create any files (this is read-only audit)
- Fix issues automatically (report only)
- Include third-party/vendor code
- Report on node_modules, .venv, target/, dist/
