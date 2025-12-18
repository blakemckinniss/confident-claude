"""Structured context packer for mastermind routing and planning.

Packs context with strict token budgets:
- Router: 1200 tokens (fast classification)
- Planner: 4000 tokens (detailed blueprint)

Includes: repo structure, git diff, beads, test status, serena context, memories.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import get_config


# Memory files that contain decisions/lessons (high value for routing)
CORE_MEMORY_FILES = [
    "__decisions.md",
    "__lessons.md",
    "__capabilities.md",
    "__integration_synergy.md",
]

# TF-IDF cache for memory relevance scoring
_idf_cache: dict[str, float] | None = None
_idf_cache_time: float = 0
_IDF_CACHE_TTL = 300  # 5 minutes


def _compute_idf(documents: list[str]) -> dict[str, float]:
    """Compute IDF values for all terms in document corpus."""
    from math import log

    doc_count = len(documents)
    if doc_count == 0:
        return {}

    term_doc_counts: dict[str, int] = {}

    for doc in documents:
        terms = set(re.findall(r"\b[a-zA-Z]{3,}\b", doc.lower()))
        for term in terms:
            term_doc_counts[term] = term_doc_counts.get(term, 0) + 1

    # IDF = log(N / df) where N = total docs, df = docs containing term
    idf = {}
    for term, df in term_doc_counts.items():
        idf[term] = log(doc_count / df) if df > 0 else 0

    return idf


def _get_idf_values(cwd: Path | None = None) -> dict[str, float]:
    """Get cached IDF values, recomputing if stale (>5 min)."""
    global _idf_cache, _idf_cache_time
    import time

    now = time.time()
    if _idf_cache is not None and (now - _idf_cache_time) < _IDF_CACHE_TTL:
        return _idf_cache

    # Collect all memory documents
    documents = []
    memory_dir = Path.home() / ".claude" / "memory"
    if memory_dir.exists():
        for f in memory_dir.glob("__*.md"):
            if f.name in CORE_MEMORY_FILES:
                try:
                    documents.append(f.read_text(encoding="utf-8")[:2000])
                except (OSError, UnicodeDecodeError):
                    continue

    # Check serena memories
    serena_dirs = []
    if cwd:
        serena_dirs.append(cwd / ".serena" / "memories")
    serena_dirs.append(Path.home() / ".claude" / ".serena" / "memories")

    for serena_dir in serena_dirs:
        if not serena_dir.exists():
            continue
        for f in serena_dir.glob("*.md"):
            if not f.name.startswith("session_"):
                try:
                    documents.append(f.read_text(encoding="utf-8")[:1000])
                except (OSError, UnicodeDecodeError):
                    continue

    _idf_cache = _compute_idf(documents) if documents else {}
    _idf_cache_time = now
    return _idf_cache


def _tfidf_score(query_terms: set[str], doc_text: str, idf: dict[str, float]) -> float:
    """Compute TF-IDF relevance score for document against query."""
    doc_terms = re.findall(r"\b[a-zA-Z]{3,}\b", doc_text.lower())
    doc_len = len(doc_terms)
    if doc_len == 0:
        return 0.0

    # Term frequency in document
    tf: dict[str, float] = {}
    for term in doc_terms:
        tf[term] = tf.get(term, 0) + 1

    # Normalize TF by doc length
    for term in tf:
        tf[term] = tf[term] / doc_len

    # Score = sum(tf * idf) for matching query terms
    score = 0.0
    for term in query_terms:
        if term in tf:
            score += tf[term] * idf.get(term, 1.0)

    return score


def estimate_tokens(text: str) -> int:
    """Rough token estimate (4 chars per token average)."""
    return len(text) // 4


def truncate_to_budget(text: str, budget: int) -> str:
    """Truncate text to fit within token budget."""
    estimated = estimate_tokens(text)
    if estimated <= budget:
        return text
    # Truncate with buffer for "..." indicator
    char_limit = (budget - 10) * 4
    return text[:char_limit] + "\n... [truncated]"


@dataclass
class PackedContext:
    """Packed context ready for router or planner."""

    prompt: str
    sections: dict[str, str]
    token_estimate: int
    budget: int
    truncated: bool


def get_repo_structure(cwd: Path, max_depth: int = 2) -> str:
    """Get repository structure via tree or ls."""
    try:
        result = subprocess.run(
            [
                "tree",
                "-L",
                str(max_depth),
                "--noreport",
                "-I",
                "node_modules|__pycache__|.git|.venv",
            ],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout[:2000]
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    # Fallback to ls
    try:
        result = subprocess.run(
            ["ls", "-la"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.stdout[:1000]
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return "[repo structure unavailable]"


def get_git_diff(cwd: Path, max_lines: int = 100) -> str:
    """Get current git diff (staged + unstaged)."""
    try:
        result = subprocess.run(
            ["git", "diff", "HEAD", "--stat"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            lines = result.stdout.strip().split("\n")
            if len(lines) > max_lines:
                return (
                    "\n".join(lines[:max_lines])
                    + f"\n... [{len(lines) - max_lines} more files]"
                )
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return "[no changes]"


def get_beads_summary(max_items: int = 5) -> str:
    """Get summary of open beads."""
    try:
        result = subprocess.run(
            ["bd", "list", "--status=open"],
            capture_output=True,
            text=True,
            timeout=5,
            env={"BEADS_DIR": str(Path.home() / ".beads"), **subprocess.os.environ},
        )
        if result.returncode == 0 and result.stdout.strip():
            lines = result.stdout.strip().split("\n")
            if len(lines) > max_items + 2:  # header + items
                return (
                    "\n".join(lines[: max_items + 2])
                    + f"\n... [{len(lines) - max_items - 2} more]"
                )
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return "[no beads]"


def get_test_status(cwd: Path) -> str:
    """Get recent test status if available."""
    # Check for common test result files
    for pattern in ["pytest.xml", "test-results.xml", ".pytest_cache"]:
        if (cwd / pattern).exists():
            return "[tests configured]"

    # Check package.json for test script
    pkg_json = cwd / "package.json"
    if pkg_json.exists():
        return "[npm tests available]"

    return "[no test info]"


def get_memory_hints(cwd: Path | None = None) -> dict[str, Any]:
    """Get lightweight memory signals for router (Path B).

    Returns boolean hints about available memories without full content.
    Used to inform classification without consuming token budget.
    """
    hints: dict[str, Any] = {
        "file_memories_available": False,
        "serena_memories_available": False,
        "memory_count": 0,
        "memory_topics": [],  # First few filenames as topic hints
    }

    # Check ~/.claude/memory/
    memory_dir = Path.home() / ".claude" / "memory"
    if memory_dir.exists():
        memories = [f for f in memory_dir.glob("__*.md") if f.name in CORE_MEMORY_FILES]
        if memories:
            hints["file_memories_available"] = True
            hints["memory_count"] += len(memories)
            hints["memory_topics"].extend(
                m.stem.replace("__", "")[:20] for m in memories[:3]
            )

    # Check serena memories (project-local or global .serena)
    serena_dirs = []
    if cwd:
        serena_dirs.append(cwd / ".serena" / "memories")
    serena_dirs.append(Path.home() / ".claude" / ".serena" / "memories")

    for serena_dir in serena_dirs:
        if serena_dir.exists():
            serena_mems = list(serena_dir.glob("*.md"))
            # Exclude session files, keep topic memories
            topic_mems = [m for m in serena_mems if not m.name.startswith("session_")]
            if topic_mems:
                hints["serena_memories_available"] = True
                hints["memory_count"] += len(topic_mems)
                hints["memory_topics"].extend(m.stem[:20] for m in topic_mems[:2])
                break  # Use first found

    # Limit topics to 5
    hints["memory_topics"] = hints["memory_topics"][:5]
    return hints


def get_memory_content(prompt: str, budget: int = 800, cwd: Path | None = None) -> str:
    """Get relevant memory content for planner (Path A).

    Searches memories for keyword relevance to prompt and returns
    top matches within token budget.
    """
    # Extract keywords from prompt (alphanumeric words, 3+ chars)
    keywords = set(w.lower() for w in re.findall(r"\b[a-zA-Z]{3,}\b", prompt.lower()))
    # Remove common stop words
    stop_words = {
        "the",
        "and",
        "for",
        "are",
        "but",
        "not",
        "you",
        "all",
        "can",
        "had",
        "her",
        "was",
        "one",
        "our",
        "out",
        "has",
        "have",
        "been",
        "this",
        "that",
        "with",
        "they",
        "from",
        "would",
        "could",
        "should",
        "what",
        "when",
        "where",
        "which",
        "there",
        "their",
        "about",
        "into",
        "some",
        "than",
        "them",
        "then",
    }
    keywords -= stop_words

    if not keywords:
        return "[no relevant memories]"

    # Get IDF values for TF-IDF scoring
    idf = _get_idf_values(cwd)

    relevant: list[tuple[float, str, str]] = []  # (score, name, content)

    # Search ~/.claude/memory/
    memory_dir = Path.home() / ".claude" / "memory"
    if memory_dir.exists():
        for mem_file in memory_dir.glob("__*.md"):
            if mem_file.name not in CORE_MEMORY_FILES:
                continue
            try:
                content = mem_file.read_text(encoding="utf-8")[:1500]
                # TF-IDF scoring with name boost
                score = _tfidf_score(keywords, content, idf)
                # Boost score if query terms appear in filename
                name_words = set(mem_file.stem.lower().replace("_", " ").split())
                if keywords & name_words:
                    score *= 2.0  # 2x boost for name matches
                if score > 0:
                    relevant.append((score, mem_file.stem, content[:500]))
            except (OSError, UnicodeDecodeError):
                continue

    # Search serena memories
    serena_dirs = []
    if cwd:
        serena_dirs.append(cwd / ".serena" / "memories")
    serena_dirs.append(Path.home() / ".claude" / ".serena" / "memories")

    for serena_dir in serena_dirs:
        if not serena_dir.exists():
            continue
        for mem_file in serena_dir.glob("*.md"):
            if mem_file.name.startswith("session_"):
                continue  # Skip session logs
            try:
                content = mem_file.read_text(encoding="utf-8")[:1000]
                # TF-IDF scoring with name boost
                score = _tfidf_score(keywords, content, idf)
                name_words = set(mem_file.stem.lower().replace("_", " ").split())
                if keywords & name_words:
                    score *= 2.0  # 2x boost for name matches
                if score > 0:
                    relevant.append((score, f"serena:{mem_file.stem}", content[:400]))
            except (OSError, UnicodeDecodeError):
                continue

    if not relevant:
        return "[no relevant memories]"

    # Sort by relevance, take top entries within budget
    relevant.sort(reverse=True, key=lambda x: x[0])
    output = []
    tokens_used = 0
    for score, name, content in relevant:
        entry = f"### {name} (relevance: {score:.2f})\n{content}\n"
        entry_tokens = estimate_tokens(entry)
        if tokens_used + entry_tokens > budget:
            break
        output.append(entry)
        tokens_used += entry_tokens

    return "\n".join(output) if output else "[no relevant memories]"


def get_pal_continuation_hint(
    session_id: str, suggested_tool: str | None = None
) -> str:
    """Get PAL continuation hint for routing context.

    If a continuation_id exists for the suggested PAL tool (or any PAL tool),
    returns a hint that Claude can use to resume context.

    Args:
        session_id: Current session ID for loading mastermind state
        suggested_tool: Specific PAL tool type (e.g., "debug", "planner")

    Returns:
        Hint string or empty string if no continuation available
    """
    try:
        from .state import load_state

        mm_state = load_state(session_id)
        continuations = mm_state.pal_continuations

        if not continuations:
            return ""

        # If specific tool suggested, check for its continuation
        if suggested_tool:
            tool_type = suggested_tool.replace("mcp__pal__", "")
            if cont_id := continuations.get(tool_type):
                return f'📎 Resume PAL {tool_type} context: continuation_id="{cont_id}"'

        # Otherwise, list all available continuations
        available = [f"{k}: {v[:12]}..." for k, v in continuations.items() if v]
        if available:
            return f"📎 PAL continuations available: {', '.join(available)}"

        return ""
    except Exception:
        return ""


def get_confidence_context(confidence: int | None) -> str:
    """Format confidence level for router context.

    Provides the router with agent confidence state so it can
    bias toward complex classification when confidence is low.
    """
    if confidence is None:
        return ""

    # Determine zone name
    if confidence >= 95:
        zone = "EXPERT"
    elif confidence >= 86:
        zone = "TRUSTED"
    elif confidence >= 71:
        zone = "CERTAINTY"
    elif confidence >= 51:
        zone = "WORKING"
    elif confidence >= 31:
        zone = "HYPOTHESIS"
    else:
        zone = "IGNORANCE"

    ctx = f"Agent confidence: {confidence}% ({zone})"
    if confidence < 50:
        ctx += " - VERY LOW, strongly recommend complex + PAL consultation"
    elif confidence < 70:
        ctx += " - LOW, consider escalating classification"

    return ctx


def pack_for_router(
    user_prompt: str, cwd: Path | None = None, confidence: int | None = None
) -> PackedContext:
    """Pack minimal context for router classification (1200 token budget).

    Focus on: user prompt, repo type, basic structure.

    Args:
        user_prompt: The user's request
        cwd: Working directory for repo detection
        confidence: Current agent confidence level (0-100)
    """
    config = get_config()
    budget = config.context_packer.router_token_budget
    cwd = cwd or Path.cwd()

    sections: dict[str, str] = {}

    # User prompt is highest priority
    sections["prompt"] = user_prompt

    # Repo type detection
    repo_type = "unknown"
    if (cwd / "package.json").exists():
        repo_type = "node/javascript"
    elif (cwd / "pyproject.toml").exists() or (cwd / "setup.py").exists():
        repo_type = "python"
    elif (cwd / "Cargo.toml").exists():
        repo_type = "rust"
    elif (cwd / "go.mod").exists():
        repo_type = "go"
    sections["repo_type"] = repo_type

    # Compact structure (only if budget allows)
    if config.context_packer.include_repo_structure:
        sections["structure"] = get_repo_structure(cwd, max_depth=1)[:500]

    # Add confidence context if provided
    if confidence is not None:
        sections["confidence"] = get_confidence_context(confidence)

    # Add memory hints (Path B - lightweight signals)
    if config.context_packer.include_memory_hints:
        memory_hints = get_memory_hints(cwd)
        if memory_hints["memory_count"] > 0:
            sections["memory_hints"] = memory_hints

    # Build packed prompt
    packed = f"""## User Request
{sections["prompt"]}

## Repository
Type: {sections["repo_type"]}
"""

    # Add confidence section (high priority - affects classification)
    if "confidence" in sections and sections["confidence"]:
        packed += f"\n## Agent State\n{sections['confidence']}\n"

    # Add memory hints (lightweight - just signals, not content)
    if "memory_hints" in sections:
        hints = sections["memory_hints"]
        hint_str = f"Memories available: {hints['memory_count']} "
        hint_str += f"(file: {hints['file_memories_available']}, serena: {hints['serena_memories_available']})"
        if hints["memory_topics"]:
            hint_str += f"\nTopics: {', '.join(hints['memory_topics'])}"
        packed += f"\n## Memory Signals\n{hint_str}\n"

    if "structure" in sections:
        packed += f"\n## Structure (top-level)\n{sections['structure']}\n"

    # Check budget and truncate if needed
    token_est = estimate_tokens(packed)
    truncated = token_est > budget
    if truncated:
        packed = truncate_to_budget(packed, budget)
        token_est = budget

    return PackedContext(
        prompt=packed,
        sections=sections,
        token_estimate=token_est,
        budget=budget,
        truncated=truncated,
    )


def pack_for_planner(
    user_prompt: str,
    routing_decision: dict[str, Any],
    cwd: Path | None = None,
) -> PackedContext:
    """Pack full context for planner blueprint generation (4000 token budget).

    Includes: user prompt, routing info, repo structure, git diff, beads, tests.
    """
    config = get_config()
    budget = config.context_packer.planner_token_budget
    cwd = cwd or Path.cwd()

    sections: dict[str, str] = {}

    # Core sections
    sections["prompt"] = user_prompt
    sections["routing"] = (
        f"Classification: {routing_decision.get('classification', 'complex')}\nReason: {', '.join(routing_decision.get('reason_codes', []))}"
    )

    # Repository context
    if config.context_packer.include_repo_structure:
        sections["structure"] = get_repo_structure(cwd, max_depth=2)

    if config.context_packer.include_git_diff:
        sections["diff"] = get_git_diff(cwd)

    if config.context_packer.include_beads:
        sections["beads"] = get_beads_summary()

    if config.context_packer.include_test_status:
        sections["tests"] = get_test_status(cwd)

    # Add relevant memories (Path A - full content for complex tasks)
    if config.context_packer.include_memory_content:
        memory_budget = config.context_packer.memory_token_budget
        memories = get_memory_content(user_prompt, budget=memory_budget, cwd=cwd)
        if memories and memories != "[no relevant memories]":
            sections["memories"] = memories

    # Build packed prompt
    packed = f"""## User Request
{sections["prompt"]}

## Router Classification
{sections["routing"]}

## Repository Structure
{sections.get("structure", "[unavailable]")}

## Current Changes
{sections.get("diff", "[none]")}

## Open Tasks (Beads)
{sections.get("beads", "[none]")}

## Test Status
{sections.get("tests", "[unknown]")}

## Relevant Memories
{sections.get("memories", "[none]")}
"""

    # Check budget and truncate if needed
    token_est = estimate_tokens(packed)
    truncated = token_est > budget
    if truncated:
        packed = truncate_to_budget(packed, budget)
        token_est = budget

    return PackedContext(
        prompt=packed,
        sections=sections,
        token_estimate=token_est,
        budget=budget,
        truncated=truncated,
    )
