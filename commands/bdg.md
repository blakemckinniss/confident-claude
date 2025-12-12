---
description: Browser Debugger - Chrome DevTools Protocol CLI (start, navigate, eval, DOM, network)
argument-hint: <cmd> [args]
allowed-tools: Bash
---

# Browser Debugger (bdg)

**Semantic aliases:** browser, chrome, devtools, cdp, headless, web automation, page, DOM, network inspector

**Tool location:** `~/.claude/ops/bdg.py`

## Commands

| Command | Description |
|---------|-------------|
| `start` | Launch Chrome with CDP on port 9222 |
| `stop` | Stop Chrome instance |
| `status` | Check CDP connection and list open pages |
| `page navigate <url>` | Navigate to URL |
| `page screenshot <file>` | Capture screenshot |
| `page pdf <file>` | Save page as PDF |
| `page reload` | Reload current page |
| `dom query <selector>` | Query DOM elements |
| `dom html` | Get page HTML |
| `eval <js>` | Execute JavaScript |
| `network enable` | Start network monitoring |
| `network requests` | List captured requests |
| `list [domain]` | List CDP domains/methods |
| `search <term>` | Search CDP methods |
| `describe <method>` | Describe CDP method signature |

## Examples

```bash
# Start browser and navigate
bdg start
bdg page navigate https://example.com
bdg status

# Inspect page
bdg dom query "h1"
bdg eval "document.title"

# Capture
bdg page screenshot ~/screenshot.png

# Cleanup
bdg stop
```

## Invocation

!`~/.claude/hooks/py ~/.claude/ops/bdg.py $ARGUMENTS`
