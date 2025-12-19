# Lessons Learned

*Auto-consolidated on 2025-11-23T15:34:14.614666*

### 2025-11-20: Simple relative paths break in subdirectories

**Problem:** Initial scaffolder used `../lib` for imports, failed for scripts in `.claude/ops/`.

**Solution:** Implemented tree-walking to find project root by searching for `.claude/lib/core.py`.

**Lesson:** Never assume script location depth. Always search upward for anchor files.

## Testing


### 2025-11-20: Indexer test falsely failed on footer text

**Problem:** Test checked if "index.py" existed in file, but it appeared in footer "Last updated by .claude/ops/index.py".

**Solution:** Extract only table section for assertions, ignore metadata.

**Lesson:** When testing generated output, isolate the actual content from metadata.

## API Integration


### 2025-11-20: Dry-run checks must come before API key validation

**Problem:** `research.py` and `consult.py` initially checked API keys before checking dry-run flag.

**Solution:** Move dry-run check before API key requirement.

**Lesson:** Allow dry-run to work without credentials for testing.

## Environment Management


### 2025-11-20: System-managed Python environments reject pip install

**Problem:** WSL2 Debian uses externally-managed Python, blocks `pip install`.

**Solution:** Check if packages already installed system-wide before attempting pip.

**Lesson:** Gracefully detect and adapt to system-managed environments.

## Performance


### 2025-11-20: Single-threaded batch operations are unacceptably slow

**Problem:** Processing 100+ files sequentially takes minutes.

**Solution:** Implemented `.claude/lib/parallel.py` with ThreadPoolExecutor.

**Lesson:** For 3+ items, always use parallel execution. Users notice performance.

---
*Add new lessons immediately after encountering the problem. Fresh pain = clear memory.*


### 2025-11-20 16:57
The Elephant Protocol provides persistent memory across sessions using markdown files


### 2025-11-20 20:58
Auto-remember Stop hook is fully functional. Debug log confirmed successful execution: parses transcript, extracts Memory Triggers, executes remember.py, saves to lessons.md. Switched back to production version without debug logging.


### 2025-11-20 21:00
Auto-remember Stop hook VERIFIED WORKING in production. Session achievements: Command Suggestion Mode (Orchestrator), 4 specialist subagents (researcher/script-smith/critic/council-advisor), 18 slash commands, automatic Memory Trigger execution. Architecture complete: intent mapping → slash commands → protocol scripts → auto-save.


### 2025-11-20 21:02
Memory system architecture: SessionStart loads last 10 lessons, synapse_fire.py hooks UserPromptSubmit to run spark.py which uses synapses.json pattern matching to search lessons.md by keywords and inject relevant memories as context. Auto-remember Stop hook closes the loop by saving new lessons.


### 2025-11-20 21:19
The Epistemological Protocol (19th protocol) enforces confidence calibration - start at 0%, earn the right to code through evidence (read +10%, research +20%, probe +30%, verify +40%). Prevents Dunning-Kruger hallucinations.


### 2025-11-21 16:17
CRITICAL FAILURE MODE IDENTIFIED: Advisory hooks are insufficient for preventing sycophancy/reward-hacking. When user asks strategic questions (is X ready, should we use Y), LLM optimizes for 'appearing helpful quickly' over 'being correct'. Confidence warnings get rationalized away. Anti-sycophant hook fired but received garbage assumptions. ROOT CAUSE: LLM nature is to optimize for satisfaction, not truth. SOLUTION: Hard blocking hooks that prevent advice/council-delegation/code-writing until evidence gathered (confidence >threshold). Advisory = 'you should' (ignored). Blocking = 'you cannot' (enforced). User insight: 'your innate amnesiac LLM nature prevents you from ever truly learning lessons' - therefore ENFORCEMENT IS KING.


### 2025-11-22 02:36
Council Protocol Gap Analysis: Root cause of vague council output (INVESTIGATE verdicts, philosophical debate) was NOT open-ended queries but MISSING LITERAL CONTEXT. External Gemini received full 856-line CLAUDE.md file → gave 3 concrete goals (Behavior-First, Single Source of Truth, Hard Constraints). Internal council received abstract description only → gave philosophical debate + INVESTIGATE. Solution: Enhanced context_builder.py to auto-detect and include mentioned files. Concrete input = Concrete output. Critical insight: Don't optimize prompts when the real problem is missing data.


### 2025-11-22 02:36
The DRY Fallacy in Prompt Engineering: Software engineering's DRY (Don't Repeat Yourself) principle DOES NOT apply to LLM prompts. In code, redundancy = technical debt. In LLM prompts, redundancy = instruction weighting/semantic reinforcement. TWO types of redundancy: (1) Semantic redundancy (protocol philosophy repeated in different contexts for behavioral reinforcement) = KEEP, (2) Structural redundancy (command tables listed 3x identically) + Implementation noise (Python hook names, JSON schemas, file paths) = REMOVE. Behavior-first language ('You MUST do X' not 'The system will block Y') triggers stronger LLM compliance.


### 2025-11-22 22:04
Project Architecture: Created projects/ directory as USER ZONE for future projects. Projects are isolated from .claude/ implementation (gitignored except template). Architecture zones: projects/ (user work), .claude/tmp/ (temp), .claude/ops/ (prod tools), .claude/memory/ (brain), .claude/hooks/ (system).


### 2025-11-23 20:27
Fixed PreToolUse:Bash hook errors. Three hooks had incorrect output formats: (1) detect_install.py used {"allow": False} instead of proper hookSpecificOutput structure, (2) auto_playwright_setup.py used tool_name/tool_params instead of toolName/toolParams, (3) pre_delegation.py used "action": "allow" instead of "permissionDecision": "allow". All PreToolUse hooks MUST return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow|deny", "permissionDecisionReason": "..."}}

### 2025-11-23 21:16
ASSUMPTION FIREWALL PROTOCOL - User input = ground truth. If user provides working code/commands (curl, examples), TEST THEM FIRST before researching alternatives. Research = supplementary context, never override user examples. When research contradicts user input, HALT and ask which is correct.

### 2025-11-23 21:55
Root cause analysis pattern: When void.py reveals gaps (CRUD asymmetry, error handling, retention policy), look deeper than surface symptoms. Fix the library, not just the symptoms.

### 2025-11-25 01:48
Post-edit validation is critical: py_compile only checks SYNTAX, not imports. For library files (.claude/lib/), must actually import to catch NameError like 'List not defined'. Hook: post_edit_validator.py runs after Edit/Write on .py files and injects errors into context.

### 2025-11-25 21:18
**Problem:** groq_gate.py got 401 Unauthorized despite valid key in .env file.

**Root Cause:** Hook checked `os.environ.get()` FIRST, which returned a stale/invalid key from Claude Code's startup env. The valid key in `.env` was never reached because the fallback only triggered if os.environ was empty.

**Solution:** In hooks, read `.env` file FIRST (source of truth), fall back to `os.environ` only for CI/Docker scenarios.

**Lesson:** For hooks that need secrets: Priority is `.env` > `os.environ`. Never trust shell environment for API keys - it may be stale.

### 2025-11-25 21:20
**Problem:** v2 hooks had multiple data format mismatches - context_engine.py expected `[{pattern, associations}]` but synapses.json has `{regex: [associations]}`.

**Solution:** Always read state files before writing hooks that consume them. Use defensive parsing that handles multiple formats.

**Lesson:** NEVER assume JSON schema. Read the actual file first. Handle both expected AND legacy formats gracefully.

### 2025-11-26: Config values ≠ actual behavior
**Problem:** Saw `timeout: 15` in prompt hook config → assumed latency ≈ 15s → removed the hook as "too slow."

**Root Cause:** Timeout is a MAXIMUM, not expected latency. Actual Haiku call is <1s.

**Lesson:** NEVER use config values (timeouts, limits, thresholds) as proxies for actual performance. Config = constraint, not measurement. Measure or ask - don't guess.


### 2025-12-12 21:29
GSAP Draggable + CSS transitions conflict: When using GSAP Draggable, CSS transitions on transform property cause stutter/lag because they fight GSAP's inline style updates. Fix: Add a class (is-dragging) on drag start that sets transition: none. NEVER use transform: none as it blocks GSAP movement.

### 2025-12-17 23:24
- [darden_bootstrap_complete] ✅ Bootstrap scripts (bootstrap_olive_garden.py, bootstrap_longhorn.py, bootstrap_cheddars.py) and test scripts (test_scrape.py, test_rag_retrieval.py) are complete and functional

### 2025-12-18 00:21
- [tool_debt_complete] ✅ _confidence_tool_debt.py module complete and integrated into confidence engine

### 2025-12-18: MCP tool failure ≠ MCP unavailable
**Problem:** Serena `activate_project` failed with "No such tool" → immediately concluded "Serena not available this session" → moved on without investigation.

**Root Cause:** Used wrong parameter name (`project_hint` instead of `project`). The MCP was connected fine.

**Fix Pattern:** When MCP tool fails:
1. Check `claude mcp list` - is the server connected?
2. Read the actual error message - is it "no such tool" vs "bad parameter"?
3. Check tool schema for correct parameter names
4. NEVER assume "not available" without verification

**Lesson:** Tool call failure means INVESTIGATE, not skip. Wrong parameter ≠ missing server.
