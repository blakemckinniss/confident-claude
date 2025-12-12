---
name: browser-automation
description: |
  Browser testing, debugging, automation, screenshots, DOM inspection, network monitoring,
  Chrome DevTools, Playwright, web scraping, page interaction, console errors, UI verification,
  headless browser, selenium alternative, puppeteer, CDP, frontend debugging.

  Trigger phrases: test the UI, check the browser, take a screenshot, debug the page,
  inspect elements, network requests, console errors, DevTools, headless browser,
  web scraping, page automation, browser testing, check if page loads, verify UI,
  what's on the page, render check, visual testing, e2e test, end to end,
  click button, fill form, automate browser, scrape website, get page content,
  DOM tree, element selector, CSS selector, XPath, page source, HTML content,
  HTTP requests, API calls from browser, fetch requests, XHR, websocket,
  JavaScript errors, runtime errors, page crashes, white screen, blank page,
  responsive test, mobile view, viewport, screen size, browser window.
---

# Browser Automation

Tools for browser control, testing, and debugging.

## Primary Tools

### bdg.py - Chrome DevTools Protocol
Direct CDP access for browser debugging and automation.

```bash
# Lifecycle
bdg start                    # Launch browser
bdg stop                     # Close browser

# Navigation
bdg navigate "<url>"         # Go to URL
bdg reload                   # Refresh page

# Inspection
bdg dom                      # Get DOM tree
bdg screenshot -o file.png   # Capture screen
bdg eval "document.title"    # Run JavaScript
bdg console                  # View console logs
bdg network                  # Monitor requests
```

### playwright.py - Playwright Setup
```bash
playwright.py --install      # Install browsers
playwright.py --verify       # Check installation
```

## Slash Commands
- `/bdg <cmd>` - Browser debugger
- `/f <error>` - Fix console errors

## Common Workflows

### After CSS/UI Changes
```bash
bdg start && bdg navigate "http://localhost:3000"
bdg screenshot -o .claude/tmp/ui.png
bdg stop
```

### Debug JavaScript Errors
```bash
bdg console    # See errors
bdg eval "window.onerror = (e) => console.log('ERROR:', e)"
```
