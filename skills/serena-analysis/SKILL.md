---
name: serena-analysis
description: |
  Serena MCP semantic code analysis, find symbols, find references,
  find definitions, type information, hover info, code intelligence,
  symbol search, semantic search, language server features.

  Trigger phrases: serena, find symbol, find definition, find references,
  who calls this, where is defined, type info, hover info, semantic search,
  symbol lookup, go to definition, find usages, find implementations,
  code intelligence, LSP, language server.
---

# Serena Analysis

Semantic code analysis via Serena MCP.

## Activation

Serena is available when `.serena/` directory exists in the project.

```bash
# Check if available
ls -la .serena/
```

## Primary Tools

### Find Symbol
```
mcp__serena__find_symbol
```
Find a symbol by its fully-qualified name path.

### Get Hover Info
```
mcp__serena__get_hover_info
```
Get type information and documentation for a symbol.

### Find References
```
mcp__serena__find_references
```
Find all references to a symbol across the codebase.

### Find Definitions
```
mcp__serena__go_to_definition
```
Jump to where a symbol is defined.

### Symbols Overview
```
mcp__serena__get_symbols_overview
```
Get an overview of all symbols in a file.

### Pattern Search
```
mcp__serena__search_for_pattern
```
Regex search across the codebase.

## Common Workflows

### Understanding a Function
1. `mcp__serena__get_hover_info` - See signature and docs
2. `mcp__serena__find_references` - See all call sites
3. `mcp__serena__go_to_definition` - Jump to implementation

### Renaming Safely
1. `mcp__serena__find_symbol` - Locate the symbol
2. `mcp__serena__find_references` - Find ALL usages
3. Edit each location
4. Verify no references missed

### Exploring Codebase
1. `mcp__serena__get_symbols_overview` - See file structure
2. `mcp__serena__search_for_pattern` - Find patterns
3. `mcp__serena__find_symbol` - Drill into specifics

## When to Use Serena vs Grep

| Use Serena | Use Grep |
|------------|----------|
| Find all callers of a method | Find text patterns |
| Get type information | Search in comments |
| Semantic symbol lookup | Search across file types |
| Find implementations | Quick string search |

## Serena vs xray.py

| Serena | xray.py |
|--------|---------|
| Language server (real types) | AST parsing |
| Cross-file references | Single file focus |
| Runtime type info | Static structure |
| Requires .serena/ setup | Works anywhere |

## Tips

- Serena understands language semantics (types, inheritance)
- Use for refactoring to ensure all references found
- Faster than grep for targeted symbol lookups
- Best for TypeScript, Python, JavaScript projects
