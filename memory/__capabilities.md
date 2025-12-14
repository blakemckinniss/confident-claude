# Capabilities Index

**Generated:** 2025-12-14 (complexity refactoring documented)

**PURPOSE:** Before proposing new functionality, check if it exists here.

---

## 🌟 Priority MCP Tools

> **These MCP tools are PREFERRED over built-in alternatives.**

### crawl4ai (HIGHEST PRIORITY for web content)

**USE INSTEAD OF:** WebFetch, basic HTTP requests

| Tool | Purpose |
|------|---------|
| `mcp__crawl4ai__crawl` | Fetch single URL with JS rendering + bot bypass |
| `mcp__crawl4ai__search` | DuckDuckGo search, returns URLs to crawl |

**Why crawl4ai is superior:**
- ✅ Full JavaScript rendering (SPAs, React, Vue, dynamic content)
- ✅ Bypasses Cloudflare, bot detection, anti-scraping, CAPTCHAs
- ✅ Returns clean, LLM-friendly markdown
- ✅ Handles cookies, sessions, authentication flows

**When to use:**
- ANY web content retrieval
- Documentation fetching from protected sites
- Scraping dynamic/JS-heavy pages
- Research requiring multiple page fetches

---

## 🏗️ Architecture Notes

### Hook Runner Complexity (Dec 2025)

All 4 hook runners refactored for maintainability:

| Runner | Functions | Avg Complexity | Status |
|--------|-----------|----------------|--------|
| `post_tool_use_runner.py` | 78 | B (8.0) | ✅ All C901 resolved |
| `user_prompt_submit_runner.py` | ~60 | B (7.5) | ✅ All C901 resolved |
| `pre_tool_use_runner.py` | ~40 | B (7.0) | ✅ All C901 resolved |
| `stop_runner.py` | ~25 | B (6.5) | ✅ All C901 resolved |

**Patterns applied:**
- Pre-compiled regex at module level (e.g., `_RE_PATTERN = re.compile(...)`)
- Data-driven lookup tables (e.g., `_TOOL_BOOST_MAP = {...}`)
- Helper extraction for nested logic (e.g., `_check_js_mutations()`)
- Frozensets for O(1) membership tests (e.g., `_RESEARCH_TOOLS = frozenset(...)`)

**Result:** 21 → 0 C901 violations, avg complexity B (7.25)

### Lib Files Complexity (Dec 2025)

Key lib files refactored for maintainability:

| File | Functions Refactored | Before | After |
|------|---------------------|--------|-------|
| `context_builder.py` | 7 (`find_related_sessions`, `format_context`, `build_council_context`, `search_memories`, `get_git_status`, `extract_mentioned_files`) | C (12-20) | A-B (3-9) |
| `confidence.py` | 1 (`check_tool_permission`) | C (19) | B (8) |
| `hook_registry.py` | 2 (`_infer_from_settings`, `validate_hook`) | C (11-15) | A-B (5-7) |
| `ast_analysis.py` | 1 (`_check_attribute_call`) | C (13) | B (7) |
| `project_detector.py` | 2 (`find_project_file`, `detect_project`) | C (12-13) | A-B (4-7) |
| `session_rag.py` | 2 (`_build_index`, `search_sessions`) | C (12-16) | A-B (4-6) |
| `synapse_core.py` | 1 (`extract_recent_text`) | C (11) | A (5) |

**Patterns applied:**
- Helper extraction (`_load_session_digests()`, `_score_digest()`, `_format_*_section()`)
- Module-level frozensets (`_ALWAYS_ALLOWED_TOOLS`, `_WRITE_TOOLS`, `_STOPWORDS`)
- Data-driven tuples (`_JS_FRAMEWORKS`, `_PY_FRAMEWORKS`, `_PROJECT_FILES`)
- Early returns to flatten nesting

**Result:** Overall lib complexity A (4.35 avg), 21 C901 violations remaining (down from ~50+)

---

## 🔒 Security Gates

- `audit.py` - The Sentinel: Runs static analysis and anti-pattern detection on target files
- `audit_hooks.py` - System Auditor (The Hook Sheriff)
- `orchestrate.py` - Orchestrate: Claude-powered programmatic tool orchestration

## 📋 Workflow Gates

- `coderabbit.py` - CodeRabbit: AI-powered code review and commit workflow
- **pre_tool_use_runner** - Composite PreToolUse Runner: Runs all PreToolUse hooks in a single process
- `upkeep.py` - The Janitor: Pre-commit health checks and project maintenance

## ✅ Quality Gates

- `groq.py` - Groq: Zero-Dependency Groq API Client

## 🎯 Scope Control

- `drift.py` - The Court: Detects stylistic drift by comparing code against reference templates
- `scope.py` - The Project Manager: Manages the Definition of Done (DoD) for the current task
- **user_prompt_submit_runner** - Composite UserPromptSubmit Runner: Runs all UserPromptSubmit hooks in a single p

## 🧠 Reasoning Guards

- `think.py` - The Thinker: Decomposes complex problems into atomic steps using Chain of Though

## 💉 Context Injectors

- `council.py` - Deliberative Council: Multi-Round Decision Framework with Convergence
- `docs.py` - The Documentation Hunter: Retrieves latest documentation using Context7 REST API
- **pre_compact** - PreCompact Hook: Fires before compaction
- **statusline** - System Assistant Statusline - Full WSL2 system status at a glance

## 🧠 Memory Injectors

- `remember.py` - The Elephant: Manages persistent project memory (Context, Decisions, Lessons)
- `spark.py` - The Synapse: Scans prompt for keywords and retrieves associated memories and pro

## 🔧 Ops Awareness

- `bdg.py` - Browser Debugger CLI (bdg): Direct Chrome DevTools Protocol access for AI agents
- `detour.py` - CLI management tool for the Detour Protocol - status tracking, resolution, and t
- `hooks.py` - System Tool - Unified audit and testing for Claude Code hooks
- `playwright.py` - The Playwright Enforcer: Browser automation setup and verification tool
- **subagent_stop** - SubagentStop Hook: Fires when Task tool agents finish

## 📊 Trackers

- **post_tool_use_runner** - Composite PostToolUse Runner: Runs all PostToolUse hooks in a single process
- `sysinfo.py` - The System Probe - WSL2 system information and health monitoring

## 🔄 Lifecycle Hooks

- `compress_session.py` - compress_session.py - Preservation-focused session compression with token-effici
- `evidence.py` - Evidence Ledger Viewer - Review evidence gathered during sessions
- `housekeeping.py` - The Housekeeper - Disk space management for .claude runtime directories
- **session_cleanup** - Session Cleanup Hook v3: SessionEnd hook for cleanup and persistence
- **session_init** - Session Init Hook v3: SessionStart hook for initialization
- **stop_runner** - Composite Stop Runner: Runs all Stop hooks in a single process
- `test_hooks.py` - Test Suite: Comprehensive testing for Claude Code hooks

## 🔍 Verification Tools

- `gaps.py` - The Void Hunter: Scans code for missing functionality, stubs, and logical gaps
- `verify.py` - The Fact-Checker: Validates system state assertions. Returns True/False. Use thi
- `void.py` - The Void Hunter: Scans code for missing functionality, stubs, and logical gaps

## 🌐 Research Tools

- `firecrawl.py` - The Firecrawler: Scrape and crawl websites using Firecrawl API
- `probe.py` - The Probe: Introspects Python modules/objects to reveal the ACTUAL runtime API
- `research.py` - The Researcher: Performs deep web search using Tavily to retrieve up-to-date doc

## ⚖️ Decision Tools

- `oracle.py` - Oracle: Generic OpenRouter LLM Consultation
- `recruiter.py` - Council Recruiter: Selects optimal personas for a given proposal
- `swarm.py` - Oracle Swarm: Massive Parallel External Reasoning

## ⌨️ Slash Commands

- `/audit` - description: 🛡️ The Sheriff - Code quality audit (security, complexity, style)
- `/audit-hooks` - description: 🔍 The Hook Sheriff - Audit hooks against official Claude Code spec
- `/bd` - description: 📋 Beads - Persistent task tracking (create, list, close, dependenci
- `/bdg` - description: Browser Debugger - Chrome DevTools Protocol CLI (start, navigate, e
- `/bestway` - description: 🧭 Best Way - Evaluates optimal approaches for implementing X
- `/better` - description: 🔬 Improvement Analyzer - Identifies concrete ways to make things be
- `/capabilities` - description: "Capabilities: Regenerate hook/ops functionality index"
- `/cc` - description: 🏭 Command Creator - Creates new slash commands from description
- `/comfy` - Manage ComfyUI service. Argument: `start`, `restart`, or `stop`
- `/commit` - description: 📦 Smart Commit - Stage, commit all changes, offer push
- `/compress` - description: 📦 Compress Session - Convert JSONL session to token-efficient forma
- `/consult` - description: 🔮 The Oracle - High-level reasoning via OpenRouter
- `/council` - description: 🏛️ The Council - Parallel multi-perspective analysis (Judge, Critic
- `/cr` - description: 🐰 CodeRabbit - Run AI code review on uncommitted changes
- `/critic` - description: 🥊 The Critic - The 10th Man, attacks assumptions and exposes blind 
- `/cs` - description: 🤔 Can/Should - Quick feasibility and advisability check for X
- `/cwms` - description: ✅ Can We Make Sure - Verify and enforce X is true
- `/dc` - description: 🔍 Double Check - Verify work, fix critical gaps, present remaining 
- `/detour` - description: "Detour: Manage blocking issue stack (status, resolve, abandon)"
- `/docs` - description: "Docs: Fetch latest library documentation via Context7"
- `/doit` - description: ⚡ Do It - Execute the last discussed action without re-explaining
- `/drift` - description: ⚖️ The Court - Checks project consistency and style drift
- `/dyr` - description: 🪞 Do You Respect - Verify Claude follows a specific principle/rule
- `/evidence` - description: 📚 Evidence Ledger - Review evidence gathered (review, session <id>)
- `/f` - description: 🔧 Fix Console Errors - Diagnose and fix browser console errors
- `/find` - description: 🔍 Everything Search - Instant file search across Windows + WSL2
- `/firecrawl` - description: "Firecrawl: Scrape websites to clean markdown/HTML/JSON"
- `/fix` - description: 🔧 The Fixer - Fix all issues, fill gaps, and verify work
- `/gaps` - description: 🔍 Gap Hunter - Completeness check (finds stubs, missing CRUD, error
- `/groq` - description: "Groq: Fast LLM inference via Groq API (kimi-k2, llama-3.3, qwen3)"
- `/har` - description: 💡 HAR - Have Any Recommendations for improving X?
- `/hooks` - description: "Hooks: Audit, test, and fix Claude Code hooks"
- `/housekeeping` - description: 🧹 The Housekeeper - Manage .claude disk space (--status, --execute)
- `/imp` - description: 🔧 Implement - Research + optimal setup of X for this project
- `/inventory` - description: 🖇️ MacGyver Scan - Scans for available binaries and system tools
- `/judge` - description: ⚖️ The Judge - Value assurance, ROI, YAGNI, anti-bikeshedding
- `/no` - description: 🚫 No - Reject proposal and get alternatives
- `/opt` - description: ⚖️ Optimality Check - Evaluates if X is the best choice for this pr
- `/oracle` - description: "Oracle: External LLM consultation via OpenRouter (judge, critic, s
- `/orchestrate` - description: 🎯 Orchestrate - Claude API code_execution for batch/aggregate tasks
- `/playwright` - description: "Playwright: Browser automation setup and verification"
- `/probe` - description: 🔬 The Probe - Runtime introspection (inspect object APIs before cod
- `/recall` - Search past session transcripts for relevant context.
- `/reddit` - description: 🌐 Reddit - Open reddit.com/r/all in Chrome
- `/remember` - description: 🐘 The Elephant - Persistent memory (add lessons|decisions|context, 
- `/research` - description: 🌐 The Researcher - Live web search via Tavily API
- `/roi` - description: 💰 ROI Maximizer - Implements highest-value concepts by impact/effor
- `/scope` - description: 🏁 The Finish Line - Manage DoD with checkpoints (init, check, statu
- `/skeptic` - description: 🔍 The Skeptic - Hostile review, finds ways things will fail
- `/spark` - description: ⚡ Synapse Fire - Retrieve associative memories for a topic
- `/swarm` - description: "Swarm: Massive parallel oracle reasoning (10-1000 agents)"
- `/sysinfo` - description: 🖥️ The System Probe - WSL2 system health (CPU/mem/disk/services)
- `/test` - description: 🧪 Test Worth - Evaluate if something deserves test coverage
- `/think` - description: 🧠 The Thinker - Decomposes complex problems into sequential steps
- `/upkeep` - description: 🧹 The Janitor - Project upkeep (sync requirements, tool index, chec
- `/useful` - description: 🔧 Usefulness Amplifier - Makes X more practical, actionable, and va
- `/verify` - description: 🤥 Reality Check - Verifies system state (file_exists, grep_text, po
- `/vo` - description: 🔍 Gap Oracle - Runs gaps.py + oracle analysis on changes
- `/void` - description: 🕳️ The Void Hunter - Completeness check (finds stubs, missing CRUD,
- `/wcwd` - description: 🛠️ Implementation Brainstorm - Explores options for implementing X 
- `/win` - description: 🪟 Windows Manager - Install/uninstall Windows programs via winget
- `/worth` - description: 💎 Worth Check - Is X worth adding to this project?
- `/xray` - description: 🔬 X-Ray - AST-based structural code search (--type class|function|i
- `/yes` - description: 🚀 Autonomous Mode - Execute what's best for project health and succ

## 📦 Other

- `inventory.py` - The Scanner: Detects available system binaries, languages, and network capabilit
- `timekeeper.py` - The Timekeeper: Assesses proposal complexity and sets dynamic deliberation limit
- `xray.py` - The X-Ray: Performs AST-based structural search on Python code (Classes, Functio

---

## Before Creating New Functionality

1. **Search this index** for similar capabilities
2. **Read the existing implementation** if found
3. **Justify why existing is insufficient** before creating new
4. **Consider extending** existing over creating new

**Anti-pattern:** Creating `new_security_gate.py` when `content_gate.py` already handles security.
