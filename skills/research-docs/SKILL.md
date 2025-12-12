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

### docs.py - Library Documentation
```bash
docs.py "<library>"
docs.py "<library>" --topic "<topic>"
```

### research.py - Web Search
```bash
research.py "<query>"
```

### probe.py - Runtime Introspection
```bash
probe.py "<module.path>"
probe.py "requests.Session"
probe.py "pathlib.Path"
```

### firecrawl.py - Web Scraping
```bash
firecrawl.py "<url>"
```

### PAL MCP
- `mcp__pal__apilookup` - Current SDK docs
- `mcp__crawl4ai__crawl` - Full page scraping

## Slash Commands
- `/docs <library>` - Library docs
- `/research <query>` - Web search
- `/probe <object>` - Runtime API

## Built-in Tools
- `WebSearch` - Quick search
- `WebFetch` - Fetch URL

## When to Use What
| Need | Tool |
|------|------|
| Library docs | `/docs` |
| Current news | `/research` |
| Python API | `/probe` |
| Scrape page | `firecrawl.py` |
