"""
Routing hooks for UserPromptSubmit (priority 80-82).

Hooks that route prompts to appropriate tools:
  80 ops_nudge          - Suggest ops tools based on patterns
  81 agent_suggestion   - Suggest Task agents based on prompt patterns
  82 skill_suggestion   - Suggest Skills based on prompt patterns

Extracted from _prompt_suggestions.py to reduce file size.
"""

import re

from _prompt_registry import register_hook
from _hook_result import HookResult
from session_state import SessionState


# =============================================================================
# OPS NUDGE (priority 80)
# =============================================================================

_TOOL_TRIGGERS = {
    "research": {
        "patterns": [
            re.compile(
                r"(latest|current|new)\s+(docs?|documentation|api|version)",
                re.IGNORECASE,
            ),
            re.compile(r"how\s+does\s+.+\s+work", re.IGNORECASE),
        ],
        "command": 'python3 .claude/ops/research.py "<query>"',
        "reason": "Live web search for current documentation",
    },
    "probe": {
        "patterns": [
            re.compile(r"what\s+(methods?|attributes?)", re.IGNORECASE),
            re.compile(
                r"(inspect|introspect)\s+(the\s+)?(api|object|class)", re.IGNORECASE
            ),
        ],
        "command": 'python3 .claude/ops/probe.py "<object_path>"',
        "reason": "Runtime introspection - see actual API before coding",
    },
    "xray": {
        "patterns": [
            re.compile(
                r"(find|list|show)\s+(all\s+)?(class|function)s?\s+in", re.IGNORECASE
            ),
            re.compile(r"ast\s+(analysis|search)", re.IGNORECASE),
        ],
        "command": "python3 .claude/ops/xray.py --type <class|function> --name <Name>",
        "reason": "AST-based structural code search",
    },
    "think": {
        "patterns": [
            re.compile(r"(complex|tricky)\s+(problem|issue|bug)", re.IGNORECASE),
            re.compile(r"(break\s+down|decompose)", re.IGNORECASE),
            re.compile(r"i('m| am)\s+(stuck|confused)", re.IGNORECASE),
        ],
        "command": 'python3 .claude/ops/think.py "<problem>"',
        "reason": "Structured problem decomposition",
    },
    "council": {
        "patterns": [
            re.compile(r"(major|big)\s+(decision|choice)", re.IGNORECASE),
            re.compile(r"(pros\s+and\s+cons|trade-?offs?)", re.IGNORECASE),
        ],
        "command": 'python3 .claude/ops/council.py "<proposal>"',
        "reason": "Multi-perspective analysis (Judge+Critic+Skeptic)",
    },
    "audit": {
        "patterns": [
            re.compile(r"(security|vulnerability)\s+(check|scan|audit)", re.IGNORECASE),
            re.compile(r"(safe|secure)\s+to\s+(deploy|commit)", re.IGNORECASE),
        ],
        "command": "python3 .claude/ops/audit.py <file>",
        "reason": "Security and code quality audit",
    },
    "void": {
        "patterns": [
            re.compile(r"(stub|todo|fixme|incomplete)", re.IGNORECASE),
            re.compile(r"(missing|forgot)\s+(implementation|handler)", re.IGNORECASE),
        ],
        "command": "python3 .claude/ops/void.py <file>",
        "reason": "Completeness check - finds stubs and gaps",
    },
    "orchestrate": {
        "patterns": [
            re.compile(
                r"(process|analyze|scan)\s+(all|many|multiple)\s+files?", re.IGNORECASE
            ),
            re.compile(r"(batch|bulk|aggregate)\s+(process|operation)", re.IGNORECASE),
        ],
        "command": 'python3 .claude/ops/orchestrate.py "<task description>"',
        "reason": "Claude API code_execution - 37% token reduction for batch tasks",
    },
    # PAL MCP tools
    "pal_thinkdeep": {
        "patterns": [
            re.compile(r"(uncertain|not\s+sure)\s+(how|what|why)", re.IGNORECASE),
            re.compile(
                r"need\s+(to\s+)?(investigate|analyze|understand)", re.IGNORECASE
            ),
            re.compile(
                r"(complex|difficult)\s+(issue|problem|architecture)", re.IGNORECASE
            ),
            re.compile(r"what\s+can\s+we", re.IGNORECASE),
            re.compile(r"find\s+out\s+(why|how|what)", re.IGNORECASE),
        ],
        "command": "mcp__pal__thinkdeep",
        "reason": "PAL MCP: Multi-stage investigation with external LLM",
    },
    "pal_debug": {
        "patterns": [
            re.compile(
                r"(mysterious|strange|weird)\s+(bug|error|behavior)", re.IGNORECASE
            ),
            re.compile(r"(root\s+cause|why\s+is\s+this\s+happening)", re.IGNORECASE),
            re.compile(r"(debugging|troubleshoot)\s+(help|assistance)", re.IGNORECASE),
        ],
        "command": "mcp__pal__debug",
        "reason": "PAL MCP: Systematic debugging with hypothesis testing",
    },
    "pal_consensus": {
        "patterns": [
            re.compile(
                r"(multiple|different)\s+(perspectives?|opinions?|views?)",
                re.IGNORECASE,
            ),
            re.compile(r"(second\s+opinion|another\s+view)", re.IGNORECASE),
            re.compile(r"(consensus|agreement)\s+on", re.IGNORECASE),
            re.compile(r"what\s+is\s+the\s+best", re.IGNORECASE),
        ],
        "command": "mcp__pal__consensus",
        "reason": "PAL MCP: Multi-model consensus for decisions",
    },
    "pal_challenge": {
        "patterns": [
            re.compile(r"(am\s+i|are\s+we)\s+(right|wrong|correct)", re.IGNORECASE),
            re.compile(
                r"(challenge|question)\s+(this|my)\s+(assumption|approach)",
                re.IGNORECASE,
            ),
            re.compile(r"(sanity\s+check|reality\s+check)", re.IGNORECASE),
            re.compile(r"(can|should)\s+we\b", re.IGNORECASE),
        ],
        "command": "mcp__pal__challenge",
        "reason": "PAL MCP: Force critical thinking on assumptions",
    },
    "pal_codereview": {
        "patterns": [
            re.compile(r"\banti[- ]?patterns?\b", re.IGNORECASE),
            re.compile(r"\btechnical\s+debt\b", re.IGNORECASE),
            re.compile(r"\bcode\s+(smell|quality|review)\b", re.IGNORECASE),
        ],
        "command": "mcp__pal__codereview",
        "reason": "PAL MCP: Expert code review for quality issues",
    },
    "pal_apilookup": {
        "patterns": [
            re.compile(r"(latest|current|updated)\s+(api|sdk|docs?)", re.IGNORECASE),
            re.compile(r"(breaking\s+changes?|deprecat)", re.IGNORECASE),
            re.compile(r"(migration\s+guide|upgrade)", re.IGNORECASE),
            re.compile(
                r"\bresearch\b.*\b(api|library|framework|docs?)\b", re.IGNORECASE
            ),
            re.compile(r"get\s+the\s+latest", re.IGNORECASE),
        ],
        "command": "mcp__pal__apilookup",
        "reason": "PAL MCP: Current API/SDK documentation lookup",
    },
    "pal_chat": {
        "patterns": [
            re.compile(r"^\s*research\b", re.IGNORECASE),
            re.compile(r"\bresearch\s+(this|how|what|why)", re.IGNORECASE),
            re.compile(r"search\s+online", re.IGNORECASE),
        ],
        "command": "mcp__pal__chat",
        "reason": "PAL MCP: General consultation with external LLM",
    },
    # Crawl4AI MCP
    "crawl4ai": {
        "patterns": [
            re.compile(
                r"(scrape|crawl|fetch|extract)\s+.*(web|page|site|url)", re.IGNORECASE
            ),
            re.compile(
                r"(get|read|pull)\s+.*(from\s+)?(url|website|page|article)",
                re.IGNORECASE,
            ),
            re.compile(
                r"(content|data|text)\s+(from|of)\s+.*(url|site|page)", re.IGNORECASE
            ),
            re.compile(r"https?://", re.IGNORECASE),
            re.compile(r"\burl\b.*\b(content|fetch|get|read)\b", re.IGNORECASE),
            re.compile(
                r"(read|fetch|get)\s+.*(docs?|documentation|readme)", re.IGNORECASE
            ),
            re.compile(r"(article|blog|post)\s+(content|text)", re.IGNORECASE),
            re.compile(
                r"(bypass|avoid|get\s+around)\s+.*(guard|block|protection|captcha)",
                re.IGNORECASE,
            ),
            re.compile(r"(cloudflare|bot\s+detect|anti-bot)", re.IGNORECASE),
            re.compile(r"(web|online)\s+(data|content|info)", re.IGNORECASE),
            re.compile(r"(download|retrieve)\s+.*(page|content)", re.IGNORECASE),
            re.compile(
                r"(check|look\s+at|see)\s+(what|how)\s+.*(site|page|url)", re.IGNORECASE
            ),
        ],
        "command": "mcp__crawl4ai__crawl (single URL) or mcp__crawl4ai__search (discover URLs)",
        "reason": "🌟 Crawl4AI: JS rendering + bot bypass - BEST tool for web content retrieval",
    },
}


# =============================================================================
# AGENT SUGGESTION (priority 81)
# =============================================================================

_AGENT_TRIGGERS = {
    # Haiku agents (fast/cheap)
    "scout": {
        "patterns": [
            re.compile(r"(where|find|locate)\s+(is|are|the)\s+\w+", re.I),
            re.compile(r"(which\s+file|what\s+file)", re.I),
        ],
        "model": "haiku",
        "desc": "Find files/symbols when you don't know where",
    },
    "config-auditor": {
        "patterns": [
            re.compile(r"(env|environment)\s+(var|variable|config)", re.I),
            re.compile(r"(missing|check)\s+.*(config|\.env)", re.I),
            re.compile(r"config\s+(drift|mismatch|consistency)", re.I),
        ],
        "model": "haiku",
        "desc": "Env var consistency, config drift detection",
    },
    "log-analyzer": {
        "patterns": [
            re.compile(r"(parse|analyze|check)\s+.*(log|logs)", re.I),
            re.compile(r"(error|exception)\s+(pattern|spike|frequency)", re.I),
            re.compile(r"(log|logs)\s+.*(pattern|trace|correlat)", re.I),
        ],
        "model": "haiku",
        "desc": "Parse logs, find error patterns, correlate events",
    },
    "dependency-mapper": {
        "patterns": [
            re.compile(r"(circular|cyclic)\s+(import|depend)", re.I),
            re.compile(r"(import|dependency)\s+(graph|tree|map)", re.I),
            re.compile(r"(coupling|afferent|efferent)", re.I),
        ],
        "model": "haiku",
        "desc": "Import graphs, circular deps, coupling analysis",
    },
    "bundle-analyzer": {
        "patterns": [
            re.compile(r"(bundle|webpack|vite)\s+(size|bloat|large)", re.I),
            re.compile(r"(tree.?shak|code.?split)", re.I),
            re.compile(r"(heavy|large)\s+(import|package|depend)", re.I),
        ],
        "model": "haiku",
        "desc": "JS bundle size, heavy imports, code splitting",
    },
    "i18n-checker": {
        "patterns": [
            re.compile(r"(hardcoded|missing)\s+(string|translation)", re.I),
            re.compile(r"(i18n|internationali|locali)", re.I),
            re.compile(r"(rtl|right.to.left|translation)", re.I),
        ],
        "model": "haiku",
        "desc": "Hardcoded strings, missing translations",
    },
    "a11y-auditor": {
        "patterns": [
            re.compile(r"(a11y|accessibility|wcag)", re.I),
            re.compile(r"(aria|screen.?reader|keyboard\s+nav)", re.I),
            re.compile(r"(alt\s+text|missing\s+alt)", re.I),
        ],
        "model": "haiku",
        "desc": "WCAG violations, ARIA issues, accessibility",
    },
    "license-scanner": {
        "patterns": [
            re.compile(r"(license|licensing)\s+(scan|check|audit|compliance)", re.I),
            re.compile(r"(gpl|copyleft|mit|apache)\s+(depend|issue)", re.I),
        ],
        "model": "haiku",
        "desc": "Dependency license compliance",
    },
    "docker-analyzer": {
        "patterns": [
            re.compile(r"(docker|dockerfile)\s+(optim|security|size|layer)", re.I),
            re.compile(r"(container|image)\s+(bloat|large|security)", re.I),
        ],
        "model": "haiku",
        "desc": "Dockerfile security, size optimization",
    },
    "ci-optimizer": {
        "patterns": [
            re.compile(r"(ci|pipeline|workflow)\s+(slow|optim|cache|parallel)", re.I),
            re.compile(r"(github\s+actions|gitlab\s+ci|circleci)\s+(slow|fast)", re.I),
        ],
        "model": "haiku",
        "desc": "Pipeline speed, caching, parallelization",
    },
    "env-debugger": {
        "patterns": [
            re.compile(r"works\s+on\s+my\s+machine", re.I),
            re.compile(r"(version|node|python)\s+(mismatch|wrong|different)", re.I),
            re.compile(r"(path|env|environment)\s+(issue|problem|wrong)", re.I),
        ],
        "model": "haiku",
        "desc": "Environment debugging, version mismatches",
    },
    # Sonnet agents (accuracy critical)
    "test-analyzer": {
        "patterns": [
            re.compile(r"(test|coverage)\s+(gap|missing|flaky)", re.I),
            re.compile(r"(flaky|unstable|intermittent)\s+test", re.I),
            re.compile(r"(test|spec)\s+(quality|health)", re.I),
        ],
        "model": "sonnet",
        "desc": "Coverage gaps, flaky tests, test quality",
    },
    "perf-profiler": {
        "patterns": [
            re.compile(r"(n\+1|n \+ 1)\s+(query|problem)", re.I),
            re.compile(r"(memory\s+leak|performance)\s+(issue|problem)", re.I),
            re.compile(r"(slow|expensive)\s+(loop|query|function)", re.I),
        ],
        "model": "sonnet",
        "desc": "N+1 queries, memory leaks, perf anti-patterns",
    },
    "git-archeologist": {
        "patterns": [
            re.compile(r"(when|who)\s+(did|made|introduced|changed)", re.I),
            re.compile(r"(git\s+)?(blame|bisect|history)", re.I),
            re.compile(r"(regression|broke|when\s+did)", re.I),
        ],
        "model": "sonnet",
        "desc": "Blame, bisect, history investigation",
    },
    "error-tracer": {
        "patterns": [
            re.compile(r"(unhandled|uncaught)\s+(error|exception)", re.I),
            re.compile(r"(error|exception)\s+(path|propagat|flow|boundary)", re.I),
            re.compile(r"(swallow|silent)\s+(error|fail)", re.I),
        ],
        "model": "sonnet",
        "desc": "Exception paths, error boundaries, unhandled errors",
    },
    "refactor-planner": {
        "patterns": [
            re.compile(
                r"(refactor|extract|inline)\s+(plan|opportunit|candidate)", re.I
            ),
            re.compile(r"(code\s+smell|technical\s+debt)\s+(fix|address)", re.I),
            re.compile(r"(safe|incremental)\s+refactor", re.I),
        ],
        "model": "sonnet",
        "desc": "Safe refactoring sequences, extract candidates",
    },
    "schema-validator": {
        "patterns": [
            re.compile(r"(schema|db|database)\s+(mismatch|drift|validat)", re.I),
            re.compile(r"(orm|model)\s+.*(schema|column|type)", re.I),
            re.compile(r"(migration)\s+(safe|risk|issue)", re.I),
        ],
        "model": "sonnet",
        "desc": "DB-code mismatches, migration safety",
    },
    "state-mapper": {
        "patterns": [
            re.compile(r"(redux|zustand|mobx|state)\s+(flow|mutation|map)", re.I),
            re.compile(r"(state\s+management|data\s+flow)\s+(trace|debug)", re.I),
        ],
        "model": "sonnet",
        "desc": "Redux/Zustand flows, state mutations",
    },
    "migration-planner": {
        "patterns": [
            re.compile(r"(data|schema|code)\s+migration\s+(plan|strateg)", re.I),
            re.compile(r"(rollback|zero.?downtime)\s+(plan|strateg)", re.I),
            re.compile(r"(safe|incremental)\s+migration", re.I),
        ],
        "model": "sonnet",
        "desc": "Data/schema migrations with rollback plans",
    },
    "type-migrator": {
        "patterns": [
            re.compile(r"(js|javascript)\s+(to|→)\s+(ts|typescript)", re.I),
            re.compile(r"(add|migrate)\s+.*(type|typescript)", re.I),
            re.compile(r"(gradual|incremental)\s+typing", re.I),
        ],
        "model": "sonnet",
        "desc": "JS→TS migration, gradual typing adoption",
    },
}


@register_hook("agent_suggestion", priority=81)
def check_agent_suggestion(data: dict, state: SessionState) -> HookResult:
    """Suggest Task agents based on prompt patterns."""
    from _cooldown import check_and_reset_cooldown

    # 3-minute cooldown to prevent suggestion spam
    if not check_and_reset_cooldown("agent_suggestion", cooldown_seconds=180):
        return HookResult.allow()

    prompt = data.get("prompt", "")
    if not prompt or len(prompt) < 20:
        return HookResult.allow()

    prompt_lower = prompt.lower()
    matches = []
    for agent_name, config in _AGENT_TRIGGERS.items():
        for pattern in config["patterns"]:
            if pattern.search(prompt_lower):
                matches.append((agent_name, config))
                break
        if len(matches) >= 2:
            break

    if not matches:
        return HookResult.allow()

    suggestions = []
    for agent_name, config in matches:
        model_badge = "⚡" if config["model"] == "haiku" else "🎯"
        suggestions.append(
            f"{model_badge} **{agent_name}**: {config['desc']}\n"
            f'   → `Task(subagent_type="{agent_name}", prompt="...")`'
        )

    return HookResult.allow("🤖 TASK AGENTS AVAILABLE:\n" + "\n\n".join(suggestions))


# =============================================================================
# SKILL SUGGESTION (priority 82)
# =============================================================================

_SKILL_TRIGGERS = {
    "debugging": {
        "patterns": [
            re.compile(r"(debug|fix)\s+(this|the|an?)\s+(error|bug|issue)", re.I),
            re.compile(r"stack\s*trace", re.I),
            re.compile(r"(why|what).*(fail|crash|broken|not\s+work)", re.I),
            re.compile(r"(exception|error\s+message|runtime\s+error)", re.I),
            re.compile(r"(troubleshoot|diagnose|root\s+cause)", re.I),
        ],
        "desc": "Debug errors, stack traces, root cause analysis",
        "invoke": 'Skill(skill="debugging")',
    },
    "testing": {
        "patterns": [
            re.compile(r"(run|write|add)\s+tests?", re.I),
            re.compile(r"(pytest|jest|vitest|mocha)", re.I),
            re.compile(r"test\s+(coverage|driven|tdd)", re.I),
            re.compile(r"(mock|fixture|assertion)", re.I),
            re.compile(r"(unit|integration)\s+test", re.I),
        ],
        "desc": "Run/write tests, pytest, jest, TDD, coverage",
        "invoke": 'Skill(skill="testing")',
    },
    "browser-automation": {
        "patterns": [
            re.compile(r"(screenshot|headless|browser\s+test)", re.I),
            re.compile(r"(devtools|chrome\s+debug|cdp)", re.I),
            re.compile(r"(scrape|crawl)\s+(web|page|site)", re.I),
            re.compile(r"(dom|element|selector)\s+(inspect|check)", re.I),
            re.compile(r"(playwright|puppeteer|selenium)", re.I),
            re.compile(r"(e2e|end.to.end)\s+test", re.I),
        ],
        "desc": "Browser testing, DevTools, screenshots, scraping",
        "invoke": 'Skill(skill="browser-automation")',
    },
    "code-quality": {
        "patterns": [
            re.compile(r"(review|audit)\s+(this|the|my)?\s*code", re.I),
            re.compile(r"(security|vulnerabilit|owasp)", re.I),
            re.compile(r"(code\s+smell|anti.?pattern|technical\s+debt)", re.I),
            re.compile(r"before\s+(I\s+)?(commit|deploy|merge)", re.I),
            re.compile(r"(pr|pull\s+request)\s+review", re.I),
        ],
        "desc": "Code review, security audit, anti-patterns",
        "invoke": 'Skill(skill="code-quality")',
    },
    "completeness-checking": {
        "patterns": [
            re.compile(r"(find|check).*(gaps?|missing|incomplete)", re.I),
            re.compile(r"(stub|placeholder|todo)\s+(impl|code)", re.I),
            re.compile(r"(void|completeness)\s+check", re.I),
            re.compile(r"(dead|unused)\s+code", re.I),
            re.compile(r"notimplementederror", re.I),
        ],
        "desc": "Find gaps, stubs, missing implementations, dead code",
        "invoke": 'Skill(skill="completeness-checking")',
    },
    "frontend-design": {
        "patterns": [
            re.compile(r"(build|create|design)\s+(a\s+)?(ui|interface|page)", re.I),
            re.compile(r"(react|vue|svelte|nextjs)\s+(component|page)", re.I),
            re.compile(r"(css|tailwind|styled|aesthetic)", re.I),
            re.compile(r"(landing|dashboard|form|modal)\s+(page|design)", re.I),
            re.compile(r"(responsive|mobile)\s+(design|layout)", re.I),
        ],
        "desc": "Distinctive, production-grade frontend interfaces",
        "invoke": 'Skill(skill="frontend-design")',
    },
    "git-workflow": {
        "patterns": [
            re.compile(r"(commit|push|merge|rebase)\s+(this|the|my)?", re.I),
            re.compile(r"(create|open)\s+(a\s+)?(pr|pull\s+request)", re.I),
            re.compile(r"(git\s+)(blame|log|diff|status)", re.I),
            re.compile(r"(resolve|fix)\s+(merge\s+)?conflict", re.I),
            re.compile(r"(undo|revert|reset)\s+(commit|change)", re.I),
        ],
        "desc": "Git operations, commits, PRs, conflict resolution",
        "invoke": 'Skill(skill="git-workflow")',
    },
    "memory-workflow": {
        "patterns": [
            re.compile(r"(remember|recall|store)\s+(this|for\s+later)", re.I),
            re.compile(r"(what|did)\s+(we|I)\s+(do|decide)\s+(before|last)", re.I),
            re.compile(r"(lesson|decision).*(learned|made)", re.I),
            re.compile(r"(previous|past|old)\s+session", re.I),
            re.compile(r"(search|find)\s+(memor|past\s+work)", re.I),
        ],
        "desc": "Persistent memory, recall past work, lessons learned",
        "invoke": 'Skill(skill="memory-workflow")',
    },
    "research-docs": {
        "patterns": [
            re.compile(r"(how\s+do\s+I|what.s\s+the)\s+(use|api)", re.I),
            re.compile(r"(latest|current)\s+(version|docs|documentation)", re.I),
            re.compile(r"(look\s*up|search\s+for)\s+(doc|info)", re.I),
            re.compile(r"(api|sdk)\s+(reference|docs)", re.I),
            re.compile(r"(changelog|release\s+notes|breaking\s+change)", re.I),
        ],
        "desc": "Documentation lookup, API docs, web research",
        "invoke": 'Skill(skill="research-docs")',
    },
    "verification": {
        "patterns": [
            re.compile(r"(verify|check|confirm)\s+(this|it|the)\s+(work|exist)", re.I),
            re.compile(r"(is\s+the|does\s+the)\s+(file|port|server)", re.I),
            re.compile(r"(reality|sanity)\s+check", re.I),
            re.compile(r"(prove|assert|ensure)\s+(it|that)", re.I),
            re.compile(r"(did\s+it|does\s+it)\s+(work|run|succeed)", re.I),
        ],
        "desc": "Verify state, check existence, validate claims",
        "invoke": 'Skill(skill="verification")',
    },
    "hook-development": {
        "patterns": [
            re.compile(r"(create|write|add)\s+(a\s+)?hook", re.I),
            re.compile(r"(pre|post).?tool.?use", re.I),
            re.compile(r"hookresult\.(allow|deny)", re.I),
            re.compile(r"register_hook", re.I),
        ],
        "desc": "Claude Code hook development patterns",
        "invoke": 'Skill(skill="hook-development")',
    },
    "confidence-system": {
        "patterns": [
            re.compile(r"confidence\s+(system|level|zone)", re.I),
            re.compile(r"(reducer|increaser)\s+(fire|trigger)", re.I),
            re.compile(r"(false\s+positive|fp:)", re.I),
        ],
        "desc": "Confidence system mechanics and signals",
        "invoke": 'Skill(skill="confidence-system")',
    },
    "project-scaffold": {
        "patterns": [
            re.compile(r"(create|start|init)\s+(new|a)\s+(project|app)", re.I),
            re.compile(r"(scaffold|bootstrap|boilerplate)", re.I),
            re.compile(r"(set\s*up|initialize)\s+(repo|project)", re.I),
        ],
        "desc": "Create new projects, scaffold, initialize repos",
        "invoke": 'Skill(skill="project-scaffold")',
    },
    "autonomous-mode": {
        "patterns": [
            re.compile(r"(just\s+do\s+it|go\s+ahead)", re.I),
            re.compile(r"(fix\s+everything|work\s+autonomously)", re.I),
            re.compile(r"(yes\s+mode|auto\s+mode|hands\s*off)", re.I),
        ],
        "desc": "Self-directed execution, minimal guidance",
        "invoke": 'Skill(skill="autonomous-mode")',
    },
    "session-management": {
        "patterns": [
            re.compile(r"(compress|save)\s+(session|context)", re.I),
            re.compile(r"(context\s+recovery|recover\s+context)", re.I),
            re.compile(r"(blocking\s+issue|detour)", re.I),
            re.compile(r"(pick\s+up|continue)\s+where", re.I),
        ],
        "desc": "Session context, compression, blocking issues",
        "invoke": 'Skill(skill="session-management")',
    },
    "system-maintenance": {
        "patterns": [
            re.compile(r"(system|disk)\s+(health|space|cleanup)", re.I),
            re.compile(r"(housekeeping|maintenance)", re.I),
            re.compile(r"(free\s+some|clean\s+up)\s+space", re.I),
            re.compile(r"(cpu|memory)\s+usage", re.I),
        ],
        "desc": "System health, disk cleanup, performance",
        "invoke": 'Skill(skill="system-maintenance")',
    },
    "task-tracking": {
        "patterns": [
            re.compile(r"(track|create)\s+(this\s+)?task", re.I),
            re.compile(r"(what\s+needs|remaining\s+work)", re.I),
            re.compile(r"(beads?|bd)\s+(ready|list|create)", re.I),
            re.compile(r"(open|in.progress)\s+(tasks?|issues?)", re.I),
        ],
        "desc": "Beads task tracking, issues, blockers",
        "invoke": 'Skill(skill="task-tracking")',
    },
    "decision-support": {
        "patterns": [
            re.compile(r"(should\s+I|help\s+me)\s+(use|decide)", re.I),
            re.compile(r"(pros?\s+and\s+cons?|trade.?offs?)", re.I),
            re.compile(r"(compare|which)\s+(framework|library)", re.I),
            re.compile(r"(architecture|design)\s+(decision|choice)", re.I),
        ],
        "desc": "Complex decisions, multi-perspective analysis",
        "invoke": 'Skill(skill="decision-support")',
    },
    "mcp-servers": {
        "patterns": [
            re.compile(r"mcp\s+(server|tool)", re.I),
            re.compile(r"(crawl4ai|serena|repomix|pal\s+mcp)", re.I),
            re.compile(r"(which|available)\s+mcp", re.I),
        ],
        "desc": "MCP server capabilities and usage",
        "invoke": 'Skill(skill="mcp-servers")',
    },
    "external-llm": {
        "patterns": [
            re.compile(r"(ask|consult)\s+(another|external)\s+(model|ai)", re.I),
            re.compile(r"(second\s+opinion|multi.?model)", re.I),
            re.compile(r"(use|what\s+does)\s+(gpt|gemini|groq)", re.I),
        ],
        "desc": "External AI consultation, PAL tools, consensus",
        "invoke": 'Skill(skill="external-llm")',
    },
    "windows-interop": {
        "patterns": [
            re.compile(r"(windows|wsl2?)\s+(path|file|interop)", re.I),
            re.compile(r"/mnt/c/", re.I),
            re.compile(r"(winget|powershell|cmd\.exe)", re.I),
        ],
        "desc": "WSL2/Windows integration, paths, winget",
        "invoke": 'Skill(skill="windows-interop")',
    },
    "code-analysis": {
        "patterns": [
            re.compile(r"(find|where\s+is)\s+(class|function)", re.I),
            re.compile(r"(code\s+structure|ast|symbol\s+lookup)", re.I),
            re.compile(r"(who\s+calls|callers|references)", re.I),
            re.compile(r"(inspect|introspect)\s+(object|api)", re.I),
        ],
        "desc": "AST search, symbol lookup, code navigation",
        "invoke": 'Skill(skill="code-analysis")',
    },
    "implementation-planning": {
        "patterns": [
            re.compile(r"(how\s+should|best\s+way)\s+(I\s+)?implement", re.I),
            re.compile(r"(implementation|technical)\s+(plan|strategy)", re.I),
            re.compile(r"(build\s+vs?\s+buy|existing\s+solution)", re.I),
            re.compile(r"(worth\s+building|should\s+I\s+build)", re.I),
        ],
        "desc": "Implementation strategy, build vs buy",
        "invoke": 'Skill(skill="implementation-planning")',
    },
}


# Task-type routing matrix: maps task categories to skills, agents, MCPs, ops, and CLI
_TASK_ROUTING = {
    "debug_fix": {
        "triggers": [
            r"debug|fix\s+(this|the|an?)\s+(error|bug)",
            r"stack\s*trace",
            r"(exception|crash|broken|not\s+work)",
        ],
        "skills": ["debugging", "error-handling", "verification"],
        "agents": ["error-tracer"],
        "mcps": ["mcp__pal__debug"],
        "ops": ["think"],
        "cli": [],
        "desc": "Bug investigation",
    },
    "implement_feature": {
        "triggers": [
            r"(implement|build|create|add)\s+(a\s+)?(new\s+)?(feature|function|component)",
            r"(how\s+should|best\s+way)\s+implement",
        ],
        "skills": ["implementation-planning", "code-quality"],
        "agents": [],
        "mcps": ["mcp__pal__thinkdeep"],
        "ops": ["think"],
        "cli": [],
        "desc": "Feature implementation",
    },
    "code_review": {
        "triggers": [
            r"(review|audit)\s+(this|the|my)?\s*code",
            r"before\s+(commit|deploy|merge)",
            r"(pr|pull\s+request)\s+review",
        ],
        "skills": ["code-quality", "completeness-checking"],
        "agents": ["dead-code-hunter"],
        "mcps": ["mcp__pal__codereview"],
        "ops": ["audit", "void", "gaps"],
        "cli": [],
        "desc": "Code review",
    },
    "security_audit": {
        "triggers": [
            r"security\s+(audit|review|check)",
            r"(vulnerabilit|owasp|injection|xss)",
            r"(auth|authentication)\s+(flow|check)",
        ],
        "skills": ["security-audit", "code-quality"],
        "agents": ["deep-security"],
        "mcps": [],
        "ops": ["audit"],
        "cli": [],
        "desc": "Security audit",
    },
    "performance": {
        "triggers": [
            r"(performance|perf)\s+(issue|problem|slow)",
            r"(optimize|speed\s+up)",
            r"(n\+1|memory\s+leak|bundle\s+size)",
        ],
        "skills": ["performance"],
        "agents": ["perf-profiler", "bundle-analyzer"],
        "mcps": [],
        "ops": [],
        "cli": [],
        "desc": "Performance analysis",
    },
    "git_operations": {
        "triggers": [
            r"(commit|push|merge|rebase)",
            r"(create|open)\s+(a\s+)?(pr|pull\s+request)",
            r"(resolve|fix)\s+conflict",
        ],
        "skills": ["git-workflow"],
        "agents": ["git-archeologist"],
        "mcps": [],
        "ops": ["upkeep"],
        "cli": ["git log --oneline -20", "git diff --stat"],
        "desc": "Git operations",
    },
    "testing": {
        "triggers": [
            r"(run|write|add)\s+tests?",
            r"(pytest|jest|vitest|playwright|cypress)",
            r"test\s+(coverage|driven|flaky)",
            r"(react\s+)?testing\s+library",
        ],
        "skills": ["testing", "testing-frontend", "verification"],
        "agents": ["test-analyzer"],
        "mcps": [],
        "ops": ["verify"],
        "cli": [],
        "desc": "Testing",
    },
    "frontend_ui": {
        "triggers": [
            r"(build|create|design)\s+(a\s+)?(ui|interface|page|component)",
            r"(react|vue|nextjs|tailwind)",
            r"(hook|useState|useEffect|component)",
        ],
        "skills": [
            "frontend-design",
            "react-patterns",
            "nextjs",
            "tailwind",
            "typescript-advanced",
        ],
        "agents": ["a11y-auditor"],
        "mcps": [],
        "ops": [],
        "cli": [],
        "desc": "Frontend/UI work",
    },
    "python_backend": {
        "triggers": [
            r"(python|fastapi|flask|django)",
            r"(pydantic|dataclass|typing)",
            r"(async\s+def|await|asyncio)",
            r"(decorator|context\s+manager)",
            r"(pytest|unittest)",
        ],
        "skills": ["python-patterns", "fastapi", "api-development"],
        "agents": [],
        "mcps": [],
        "ops": [],
        "cli": ["ruff check", "pytest -v"],
        "desc": "Python backend development",
    },
    "research_docs": {
        "triggers": [
            r"(how\s+do\s+I|what.s\s+the)\s+(use|api)",
            r"(latest|current)\s+(docs|documentation)",
            r"(look\s*up|search)",
        ],
        "skills": ["research-docs"],
        "agents": ["deep-research"],
        "mcps": ["mcp__pal__apilookup", "mcp__crawl4ai__scrape"],
        "ops": ["research", "docs"],
        "cli": [],
        "desc": "Documentation/research",
    },
    "refactoring": {
        "triggers": [
            r"refactor\s+(this|the|my)",
            r"(restructure|reorganize|clean\s*up)\s+code",
            r"(extract|inline|rename)\s+(method|function|class)",
        ],
        "skills": ["refactoring", "code-quality"],
        "agents": ["refactor-planner", "dependency-mapper"],
        "mcps": [],
        "ops": ["xray"],
        "cli": [],
        "desc": "Refactoring",
    },
    "migration": {
        "triggers": [
            r"(migrate|upgrade|update)\s+(to|from)",
            r"(breaking\s+change|deprecat)",
            r"(version|major)\s+upgrade",
        ],
        "skills": ["migration"],
        "agents": ["migration-planner", "upgrade-scout"],
        "mcps": [],
        "ops": [],
        "cli": [],
        "desc": "Migration/upgrade",
    },
    "codebase_explore": {
        "triggers": [
            r"(where\s+is|find)\s+(the|this)",
            r"(understand|explore)\s+(the\s+)?(codebase|code)",
            r"(how\s+does|what\s+does)\s+.+\s+work",
        ],
        "skills": ["code-analysis"],
        "agents": ["scout", "api-cartographer"],
        "mcps": [],
        "ops": ["xray", "probe"],
        "cli": ["rg -l '<pattern>'", "fd '<pattern>'"],
        "desc": "Codebase exploration",
    },
    "ci_cd": {
        "triggers": [
            r"(ci|cd|pipeline|github\s+actions)",
            r"(build|deploy)\s+(fail|slow|broken)",
            r"(docker|container|dockerfile)",
        ],
        "skills": ["ci-cd", "docker-containers"],
        "agents": ["ci-optimizer", "docker-analyzer"],
        "mcps": [],
        "ops": [],
        "cli": [],
        "desc": "CI/CD & containers",
    },
    "config_env": {
        "triggers": [
            r"(config|env|environment)\s+(issue|problem|variable)",
            r"(wrong|missing)\s+(version|dep)",
            r"works\s+on\s+my\s+machine",
        ],
        "skills": [],
        "agents": ["env-debugger", "config-auditor"],
        "mcps": [],
        "ops": ["sysinfo", "inventory"],
        "cli": ["env | grep -i '<var>'", "which <cmd>"],
        "desc": "Config/environment issues",
    },
    "state_management": {
        "triggers": [
            r"(state|redux|zustand|context)\s+(bug|issue|flow)",
            r"(data\s+flow|mutation)",
            r"(why\s+is|where\s+does)\s+state",
        ],
        "skills": ["state-management"],
        "agents": ["state-mapper"],
        "mcps": [],
        "ops": [],
        "cli": [],
        "desc": "State management",
    },
    "complex_decision": {
        "triggers": [
            r"(should\s+I|help\s+me)\s+(choose|decide)",
            r"(pros?\s+and\s+cons?|trade.?offs?)",
            r"(which|what)\s+(framework|library|approach)",
        ],
        "skills": ["decision-support"],
        "agents": [],
        "mcps": ["mcp__pal__consensus"],
        "ops": ["council", "oracle"],
        "cli": [],
        "desc": "Complex decisions",
    },
    "json_processing": {
        "triggers": [
            r"(parse|extract|transform)\s+(json|csv|yaml|data)",
            r"\.(json|csv|yaml)\s+(file|data)",
            r"(jq|json\s+query)",
        ],
        "skills": ["data-processing"],
        "agents": [],
        "mcps": [],
        "ops": [],
        "cli": ["jq '.' <file>", "jq '.key' <file>", "jq -r '.[]'"],
        "desc": "Data processing",
    },
    "text_search": {
        "triggers": [
            r"(search|find|grep)\s+(for|in)\s+(text|string|pattern)",
            r"(regex|regular\s+expression)",
            r"rg\s+",
        ],
        "skills": [],
        "agents": [],
        "mcps": [],
        "ops": [],
        "cli": [
            "rg '<pattern>' --type <lang>",
            "rg -l '<pattern>'",
            "rg -C3 '<pattern>'",
        ],
        "desc": "Text/pattern search",
    },
    "file_operations": {
        "triggers": [
            r"(find|list|count)\s+(files|dirs)",
            r"(disk|space)\s+usage",
            r"(large|big)\s+files",
        ],
        "skills": [],
        "agents": [],
        "mcps": [],
        "ops": ["housekeeping"],
        "cli": ["fd '<pattern>'", "du -sh *", "fd -e <ext> -x wc -l"],
        "desc": "File operations",
    },
    "system_health": {
        "triggers": [
            r"(system|disk|memory)\s+(health|status|usage)",
            r"(what.s\s+running|process)",
            r"(free\s+space|cleanup)",
        ],
        "skills": ["system-maintenance"],
        "agents": [],
        "mcps": [],
        "ops": ["sysinfo", "housekeeping", "inventory"],
        "cli": ["df -h", "free -h", "ps aux | head"],
        "desc": "System health",
    },
    "memory_recall": {
        "triggers": [
            r"(remember|recall|what\s+did\s+we)",
            r"(past|previous)\s+session",
            r"(lesson|decision)\s+(learned|made)",
        ],
        "skills": ["memory-workflow"],
        "agents": [],
        "mcps": [],
        "ops": ["spark", "remember", "evidence"],
        "cli": [],
        "desc": "Memory/recall",
    },
    "completeness_check": {
        "triggers": [
            r"(find|check)\s+(gaps|missing|stubs)",
            r"(incomplete|todo|fixme)",
            r"(dead|unused)\s+code",
        ],
        "skills": ["completeness-checking"],
        "agents": ["dead-code-hunter"],
        "mcps": [],
        "ops": ["void", "gaps"],
        "cli": ["rg 'TODO|FIXME|XXX'", "rg 'NotImplementedError|pass$'"],
        "desc": "Completeness checking",
    },
    "serena_analysis": {
        "triggers": [
            r"(semantic|symbol|definition|reference)\s+(search|find|analysis)",
            r"(find|go\s+to)\s+(definition|implementation|references)",
            r"(class|function|method)\s+(hierarchy|inheritance)",
            r"(call\s+graph|callers|callees)",
            r"(rename|refactor)\s+(symbol|across\s+files)",
            r"serena",
        ],
        "skills": ["serena-analysis", "code-analysis"],
        "agents": [],
        "mcps": [
            "mcp__serena__find_symbol",
            "mcp__serena__get_hover_info",
            "mcp__serena__find_references",
        ],
        "ops": ["xray", "probe"],
        "cli": [],
        "desc": "Semantic code analysis (serena)",
    },
    "type_analysis": {
        "triggers": [
            r"(type|signature|parameter)\s+(of|for|info)",
            r"(what\s+type|return\s+type)",
            r"(hover|tooltip)\s+info",
        ],
        "skills": [],
        "agents": [],
        "mcps": ["mcp__serena__get_hover_info", "mcp__serena__find_symbol"],
        "ops": ["probe"],
        "cli": [],
        "desc": "Type/signature analysis",
    },
    "api_development": {
        "triggers": [
            r"(create|build|design)\s+(an?\s+)?(api|endpoint|route)",
            r"(rest|graphql)\s+(api|endpoint)",
            r"(request|response)\s+(handler|format)",
            r"(openapi|swagger)",
        ],
        "skills": ["api-development"],
        "agents": ["api-cartographer"],
        "mcps": ["mcp__pal__apilookup"],
        "ops": [],
        "cli": [],
        "desc": "API development",
    },
    "database": {
        "triggers": [
            r"(database|db|sql)\s+(query|schema|migration)",
            r"(prisma|sqlalchemy|orm)",
            r"(index|transaction|join)",
            r"(postgres|mysql|sqlite|mongodb)",
        ],
        "skills": ["database"],
        "agents": ["schema-validator"],
        "mcps": [],
        "ops": [],
        "cli": [],
        "desc": "Database operations",
    },
    "logging_observability": {
        "triggers": [
            r"(logging|log\s+level|structured\s+log)",
            r"(observability|tracing|metrics)",
            r"(monitoring|apm|alerting)",
            r"(correlation\s+id|log\s+aggregat)",
        ],
        "skills": ["logging-observability"],
        "agents": ["log-analyzer"],
        "mcps": [],
        "ops": [],
        "cli": [],
        "desc": "Logging & observability",
    },
}

# Compile task routing patterns
for task_type, config in _TASK_ROUTING.items():
    config["_compiled"] = [re.compile(p, re.I) for p in config["triggers"]]


@register_hook("skill_suggestion", priority=82)
def check_skill_suggestion(data: dict, state: SessionState) -> HookResult:
    """Route prompts to Skills, Agents, MCPs, Ops, and CLI - MANDATORY invocation."""
    prompt = data.get("prompt", "")
    if not prompt or len(prompt) < 15:
        return HookResult.allow()

    prompt_lower = prompt.lower()

    # Collect routed items from task matrix
    routed_skills = set()
    routed_agents = set()
    routed_mcps = set()
    routed_ops = set()
    routed_cli = []
    route_reasons = []

    for task_type, config in _TASK_ROUTING.items():
        for pattern in config["_compiled"]:
            if pattern.search(prompt_lower):
                for skill in config.get("skills", []):
                    routed_skills.add(skill)
                for agent in config.get("agents", []):
                    routed_agents.add(agent)
                for mcp in config.get("mcps", []):
                    routed_mcps.add(mcp)
                for op in config.get("ops", []):
                    routed_ops.add(op)
                for cli in config.get("cli", []):
                    if cli not in routed_cli:
                        routed_cli.append(cli)
                route_reasons.append(f"• {task_type}: {config['desc']}")
                break

    # Fallback to individual skill matching if no route matched
    if (
        not routed_skills
        and not routed_agents
        and not routed_mcps
        and not routed_ops
        and not routed_cli
    ):
        for skill_name, config in _SKILL_TRIGGERS.items():
            for pattern in config["patterns"]:
                if pattern.search(prompt_lower):
                    routed_skills.add(skill_name)
                    break
            if len(routed_skills) >= 3:
                break

    # Nothing matched
    if (
        not routed_skills
        and not routed_agents
        and not routed_mcps
        and not routed_ops
        and not routed_cli
    ):
        return HookResult.allow()

    # Build directive output sections
    sections = []

    # Skills section
    if routed_skills:
        skill_lines = []
        for skill_name in list(routed_skills)[:3]:
            if skill_name in _SKILL_TRIGGERS:
                cfg = _SKILL_TRIGGERS[skill_name]
                skill_lines.append(
                    f'  📘 `Skill(skill="{skill_name}")` — {cfg["desc"]}'
                )
            else:
                skill_lines.append(f'  📘 `Skill(skill="{skill_name}")`')
        sections.append("**Skills:**\n" + "\n".join(skill_lines))

    # Agents section
    if routed_agents:
        agent_lines = []
        for agent_name in list(routed_agents)[:2]:
            agent_lines.append(
                f'  🤖 `Task(subagent_type="{agent_name}", prompt="...")`'
            )
        sections.append("**Agents:**\n" + "\n".join(agent_lines))

    # MCPs section
    if routed_mcps:
        mcp_lines = []
        for mcp_name in list(routed_mcps)[:2]:
            mcp_lines.append(f"  🔌 `{mcp_name}`")
        sections.append("**MCPs:**\n" + "\n".join(mcp_lines))

    # Ops section
    if routed_ops:
        ops_lines = []
        for op_name in list(routed_ops)[:3]:
            ops_lines.append(f"  🔧 `~/.claude/ops/{op_name}.py`")
        sections.append("**Ops:**\n" + "\n".join(ops_lines))

    # CLI section
    if routed_cli:
        cli_lines = [f"  💻 `{cmd}`" for cmd in routed_cli[:3]]
        sections.append("**CLI:**\n" + "\n".join(cli_lines))

    output = "⚡ **TASK ROUTER** — INVOKE BEFORE PROCEEDING:\n\n" + "\n\n".join(
        sections
    )

    if route_reasons:
        output += "\n\n_Matched:_ " + ", ".join(
            r.split(":")[0].strip("• ") for r in route_reasons[:3]
        )

    return HookResult.allow(output)


@register_hook("ops_nudge", priority=80)
def check_ops_nudge(data: dict, state: SessionState) -> HookResult:
    """Suggest ops tools based on prompt patterns."""
    prompt = data.get("prompt", "")
    if not prompt or len(prompt) < 10:
        return HookResult.allow()

    prompt_lower = prompt.lower()
    matches = []
    for tool_name, config in _TOOL_TRIGGERS.items():
        for pattern in config["patterns"]:
            if pattern.search(prompt_lower):
                matches.append((tool_name, config))
                break
        if len(matches) >= 3:
            break

    if not matches:
        return HookResult.allow()

    suggestions = []
    for tool_name, config in matches:
        display_name = tool_name.replace("_", " ").upper()
        suggestions.append(
            f"🛠️ {display_name}: {config['reason']}\n   → {config['command']}"
        )

    return HookResult.allow("OPS TOOLS AVAILABLE:\n" + "\n\n".join(suggestions))


