---
name: mcp-servers
description: |
  MCP servers, Model Context Protocol, crawl4ai, serena, repomix, PAL,
  claude-mem, filesystem MCP, external tools, MCP configuration,
  server capabilities, MCP tool usage.

  Trigger phrases: MCP server, crawl4ai, serena, repomix, PAL tools,
  claude-mem, filesystem MCP, Model Context Protocol, MCP configuration,
  which MCP, available MCP tools, MCP capabilities, use serena,
  use repomix, pack codebase, semantic code, memory search.
---

# MCP Servers

Available Model Context Protocol servers and their capabilities.

## crawl4ai - Web Scraping (PRIORITY)

**Use instead of WebFetch for any web content.**

| Tool | Purpose |
|------|---------|
| `mcp__crawl4ai__crawl` | Fetch URL with JS rendering + bot bypass |
| `mcp__crawl4ai__search` | DuckDuckGo search, returns URLs |

Capabilities: Cloudflare bypass, CAPTCHA handling, SPA rendering, auth flows.

## PAL - External LLM Consultation

| Tool | Purpose |
|------|---------|
| `mcp__pal__chat` | General brainstorming |
| `mcp__pal__thinkdeep` | Deep investigation |
| `mcp__pal__debug` | Root cause analysis |
| `mcp__pal__codereview` | Systematic code review |
| `mcp__pal__consensus` | Multi-model consensus |
| `mcp__pal__planner` | Sequential planning |
| `mcp__pal__precommit` | Pre-commit validation |
| `mcp__pal__challenge` | Challenge assumptions |
| `mcp__pal__apilookup` | Current API docs |
| `mcp__pal__listmodels` | Available models |

## Serena - Semantic Code Analysis

| Tool | Purpose |
|------|---------|
| `mcp__serena__find_symbol` | Find by name path |
| `mcp__serena__find_referencing_symbols` | Find callers/references |
| `mcp__serena__get_symbols_overview` | File structure overview |
| `mcp__serena__search_for_pattern` | Regex search in code |
| `mcp__serena__replace_symbol_body` | Edit symbol |
| `mcp__serena__rename_symbol` | Rename across codebase |
| `mcp__serena__list_memories` | Project memories |

Activate project first: `mcp__serena__activate_project`

## Repomix - Codebase Packaging

| Tool | Purpose |
|------|---------|
| `mcp__...__pack_codebase` | Package local directory |
| `mcp__...__pack_remote_repository` | Package GitHub repo |
| `mcp__...__generate_skill` | Create Claude skill from code |
| `mcp__...__grep_repomix_output` | Search packed output |

## Claude-Mem - Persistent Memory

| Tool | Purpose |
|------|---------|
| `mcp__...__search` | Unified memory search |
| `mcp__...__decisions` | Find past decisions |
| `mcp__...__changes` | Find code changes |
| `mcp__...__how_it_works` | Architecture understanding |
| `mcp__...__timeline` | Observations timeline |

## Filesystem MCP

| Tool | Purpose |
|------|---------|
| `mcp__filesystem__read_text_file` | Read file |
| `mcp__filesystem__write_file` | Write file |
| `mcp__filesystem__edit_file` | Edit file |
| `mcp__filesystem__search_files` | Glob search |
| `mcp__filesystem__directory_tree` | Tree view |

## When to Use Which

| Need | MCP Server |
|------|------------|
| Web scraping | crawl4ai |
| External reasoning | PAL |
| Code navigation | Serena |
| Package codebase | Repomix |
| Cross-session memory | Claude-Mem |
| File operations | Filesystem |
