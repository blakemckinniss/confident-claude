---
name: refactoring
description: |
  Code refactoring, extract function, rename, move, inline, clean code,
  reduce complexity, remove duplication, improve readability, design patterns,
  code smells, technical debt, legacy code modernization.

  Trigger phrases: refactor this, extract function, rename variable, move to,
  inline this, clean up code, reduce complexity, remove duplication, DRY,
  code smell, technical debt, legacy code, modernize, simplify, restructure,
  split file, merge files, extract class, extract module, consolidate.
---

# Refactoring

Tools for safe code restructuring.

## Primary Tools

### refactor-planner Agent
```bash
Task(subagent_type="refactor-planner", prompt="Plan refactoring for <description>")
```
Identifies opportunities, plans safe sequences, finds extract/inline candidates.

### dead-code-hunter Agent
```bash
Task(subagent_type="dead-code-hunter", prompt="Find dead code in <path>")
```
Finds unreachable code, unused exports, stale tests, orphaned files.

## Common Refactorings

### Extract Function
```python
# Before
def process():
    # ... 50 lines of code ...

# After
def process():
    validate_input()
    transform_data()
    save_result()
```

### Rename Symbol
```bash
# Find all usages first
grep -rn "old_name" --include="*.py"

# Serena for semantic rename
mcp__serena__find_references
```

### Move/Reorganize
```bash
# Check dependencies before moving
xray.py --type import <file>

# Find what imports this
grep -rn "from.*import.*ClassName" --include="*.py"
```

## Code Smells to Fix

| Smell | Refactoring |
|-------|-------------|
| Long function | Extract method |
| Large class | Extract class |
| Duplicate code | Extract shared function |
| Long parameter list | Introduce parameter object |
| Feature envy | Move method |
| Shotgun surgery | Consolidate |

## Safe Refactoring Process

1. **Verify tests pass** before starting
2. **Small steps** - one refactoring at a time
3. **Run tests** after each change
4. **Commit frequently** - easy rollback
5. **Review diff** before finalizing

## Tools

### Find Duplication
```bash
# Similar code blocks
jscpd <path>  # JS/TS
pylint --disable=all --enable=duplicate-code <path>
```

### Complexity Analysis
```bash
ruff check --select=C901 <path>  # Cyclomatic complexity
```

### Dead Code Detection
```bash
# Unused imports
ruff check --select=F401 <path>

# Unused variables
ruff check --select=F841 <path>
```

## Patterns

### Strangler Fig
Gradually replace legacy code by routing new functionality to new code.

### Branch by Abstraction
1. Create abstraction over existing code
2. Implement new version behind abstraction
3. Switch to new implementation
4. Remove old code
