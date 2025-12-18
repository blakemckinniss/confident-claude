---
description: 🌐 Reddit - Open reddit.com/r/all in Chrome
argument-hint: [subreddit]
allowed-tools: Bash
---

Open Google Chrome to Reddit.

```bash
# Use Windows Chrome from WSL2
"/mnt/c/Program Files/Google/Chrome/Application/chrome.exe" "https://reddit.com/r/${1:-all}" 2>/dev/null &
```

If $ARGUMENTS provided, use as subreddit (e.g., `/reddit programming` → r/programming).
Default: r/all
