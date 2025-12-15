---
name: research-docs
description: |
  Documentation lookup, library research, API docs, web search, current information,
  how does X work, what's the latest version, scraping docs, runtime introspection,
  package documentation, SDK reference, official docs, changelog, release notes.

  Trigger phrases: how do I use X, what's the API for Y, latest version of,
  current documentation, look up, search for, find information, what methods does,
  inspect the API, scrape this page, get the docs, official documentation,
  package docs, npm package, pypi package, library reference, SDK docs,
  API reference, function signature, method parameters, return type, example usage,
  code examples, tutorial, getting started, quick start, installation guide,
  migration guide, upgrade guide, breaking changes, changelog, release notes,
  deprecated, removed, new features, what's new, version history, compatibility,
  supported versions, requirements, dependencies, peer dependencies, runtime API,
  introspection, reflection, available methods, object properties, class members,
  module exports, public API, internal API, undocumented, source code.
---

# Research & Documentation

Tools for documentation lookup and API introspection.

## Primary Tools

### crawl4ai MCP (HIGHEST PRIORITY for web content)
**USE INSTEAD OF WebFetch** - superior in every way.
```
mcp__crawl4ai__crawl    # Single URL with JS rendering + bot bypass
mcp__crawl4ai__search   # DuckDuckGo search, returns URLs
```
Why crawl4ai:
- Full JavaScript rendering (SPAs, React, Vue)
- Bypasses Cloudflare, bot detection, CAPTCHAs
- Returns clean, LLM-friendly markdown
- Handles cookies, sessions, auth flows

### docs.py - Library Documentation
```bash
docs.py "<library>"
docs.py "<library>" --topic "<topic>"
```

### research.py - Web Search (Tavily)
```bash
research.py "<query>"
```

### probe.py - Runtime Introspection
```bash
probe.py "<module.path>"
probe.py "requests.Session"
```

### PAL MCP
- `mcp__pal__apilookup` - Current SDK docs, versions, breaking changes

## Slash Commands
- `/docs <library>` - Library docs via Context7
- `/research <query>` - Tavily web search
- `/probe <object>` - Python runtime API

## When to Use What
| Need | Tool |
|------|------|
| Any web page | `mcp__crawl4ai__crawl` (FIRST CHOICE) |
| Library docs | `/docs` |
| Current news | `/research` |
| Python API | `/probe` |
| Multiple URLs | crawl4ai search → crawl each |
