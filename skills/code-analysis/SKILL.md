---
name: code-analysis
description: |
  Code structure analysis, AST search, find classes, find functions, imports,
  code navigation, symbol lookup, runtime inspection, object introspection,
  style drift detection, architectural patterns, code metrics, complexity.

  Trigger phrases: find class, find function, where is defined, who calls this,
  show structure, code structure, AST, abstract syntax tree, symbol lookup,
  inspect object, runtime introspection, what methods, what properties,
  style drift, architectural drift, pattern violation, code metrics,
  complexity analysis, cyclomatic complexity, find imports, find usages,
  callers, references, dependencies, call graph.
---

# Code Analysis

Tools for understanding code structure and patterns.

## Structural Search

### xray.py - AST-Based Search
```bash
# Find classes
xray.py --type class --name "ClassName" <path>

# Find functions
xray.py --type function --name "func_name" <path>

# Find all imports
xray.py --type import <path>

# Substring match
xray.py --type function --name "handle" <path>  # Finds handleClick, handleSubmit, etc.
```

### Slash Command
```bash
/xray [--type TYPE] [--name NAME] <path>
```

## Runtime Inspection

### probe.py - Object Introspection
```bash
probe.py "<module.object>"
probe.py "requests.Session"
probe.py "pathlib.Path"
```

Shows: methods, properties, signatures, docstrings.

### Slash Command
```bash
/probe <object_path>
```

## Style Drift Detection

### drift.py - Pattern Compliance
```bash
drift.py  # Check against reference templates
```

Detects when code violates established patterns.

### Slash Command
```bash
/drift  # Check project consistency
```

## Serena MCP (Semantic Analysis)

```
mcp__serena__find_symbol          # Find by name path
mcp__serena__find_referencing_symbols  # Find callers
mcp__serena__get_symbols_overview # File structure
mcp__serena__search_for_pattern   # Regex search
```

## Common Patterns

### Find Where Function Is Called
```bash
# Quick grep
grep -rn "function_name(" --include="*.py"

# Semantic (more accurate)
mcp__serena__find_referencing_symbols
```

### Understand Class Structure
```bash
xray.py --type class --name "MyClass" src/
# Shows methods, inheritance, decorators
```

### Check Import Dependencies
```bash
xray.py --type import src/module.py
# Lists all imports
```

### Inspect Unknown API
```bash
probe.py "library.ClassName"
# Shows available methods/properties
```

## Metrics & Complexity

```bash
# Ruff complexity check
ruff check --select=C901 <path>

# Function length
xray.py --type function <path> | wc -l
```
