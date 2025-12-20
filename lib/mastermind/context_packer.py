"""Structured context packer for mastermind routing and planning.

Packs context with strict token budgets:
- Router: 1200 tokens (fast classification)
- Planner: 4000 tokens (detailed blueprint)

Includes: repo structure, git diff, beads, test status, serena context, memories.
"""

from __future__ import annotations

import logging
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
    "__infrastructure.md",  # Key directories/APIs reference
]

# TF-IDF cache for memory relevance scoring
_idf_cache: dict[str, float] | None = None
_idf_cache_time: float = 0
_IDF_CACHE_TTL = 300  # 5 minutes

# Bead status cache (per-turn, keyed by timestamp truncated to 10s)
_bead_cache: dict[str, bool] = {}
_bead_cache_time: float = 0
_BEAD_CACHE_TTL = 10  # 10 seconds (covers a single turn)


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


def has_in_progress_bead() -> bool:
    """Check if there's an in_progress bead (active tracked work).

    Used for bead-aware routing - if work is already tracked and in progress,
    we can adjust PAL routing recommendations.

    Results are cached for 10 seconds to avoid repeated subprocess calls
    within the same turn.
    """
    global _bead_cache, _bead_cache_time
    import time

    now = time.time()

    # Check cache (TTL-based)
    if now - _bead_cache_time < _BEAD_CACHE_TTL and "in_progress" in _bead_cache:
        return _bead_cache["in_progress"]

    # Cache miss - run subprocess
    result_value = False
    try:
        result = subprocess.run(
            ["bd", "list", "--status=in_progress"],
            capture_output=True,
            text=True,
            timeout=3,
            env={"BEADS_DIR": str(Path.home() / ".beads"), **subprocess.os.environ},
        )
        if result.returncode == 0 and result.stdout.strip():
            # Check if there are any non-header lines
            lines = [
                line
                for line in result.stdout.strip().split("\n")
                if line.strip() and not line.startswith("ID")
            ]
            result_value = len(lines) > 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    # Update cache
    _bead_cache["in_progress"] = result_value
    _bead_cache_time = now
    return result_value


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


def get_git_diff_compact(cwd: Path, max_files: int = 10) -> str:
    """Get compact git diff - just modified file names for router context."""
    try:
        result = subprocess.run(
            ["git", "diff", "HEAD", "--name-only"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            files = result.stdout.strip().split("\n")
            if len(files) > max_files:
                return (
                    ", ".join(files[:max_files]) + f" (+{len(files) - max_files} more)"
                )
            return ", ".join(files)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return ""


def get_in_progress_beads(max_items: int = 3) -> str:
    """Get in_progress beads - the active task context."""
    try:
        result = subprocess.run(
            ["bd", "list", "--status=in_progress"],
            capture_output=True,
            text=True,
            timeout=5,
            env={"BEADS_DIR": str(Path.home() / ".beads"), **subprocess.os.environ},
        )
        if result.returncode == 0 and result.stdout.strip():
            lines = result.stdout.strip().split("\n")
            # Skip header, get task lines
            tasks = [
                line for line in lines[1:] if line.strip() and not line.startswith("-")
            ]
            if tasks:
                if len(tasks) > max_items:
                    return (
                        "\n".join(tasks[:max_items])
                        + f"\n(+{len(tasks) - max_items} more)"
                    )
                return "\n".join(tasks)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return ""


def get_serena_status() -> str:
    """Check if serena is active and which project."""
    # Check for serena state file
    serena_state = Path.home() / ".claude" / "tmp" / "serena_active.json"
    if serena_state.exists():
        try:
            import json

            data = json.loads(serena_state.read_text())
            project = data.get("project", "unknown")
            return f"Serena active: {project}"
        except (json.JSONDecodeError, OSError, KeyError):
            # Malformed state file or read error - fall through to .serena check
            pass

    # Check for .serena directory in cwd
    cwd = Path.cwd()
    if (cwd / ".serena").exists():
        return "Serena available (project has .serena/)"

    return ""


def get_recent_errors(max_items: int = 3) -> str:
    """Get recent tool errors from session state."""
    import json

    state_file = Path.home() / ".claude" / "tmp" / "session_state.json"
    if not state_file.exists():
        return ""

    try:
        data = json.loads(state_file.read_text())
        errors = data.get("recent_errors", [])
        if not errors:
            return ""

        # Format: tool: error (compact)
        lines = []
        for err in errors[-max_items:]:
            tool = err.get("tool", "unknown")[:20]
            msg = err.get("message", "")[:40]
            lines.append(f"• {tool}: {msg}")

        return "\n".join(lines)
    except (json.JSONDecodeError, OSError, KeyError):
        return ""


def get_confidence_trend() -> str:
    """Get confidence trend from recent history."""
    import json

    state_file = Path.home() / ".claude" / "tmp" / "session_state.json"
    if not state_file.exists():
        return ""

    try:
        data = json.loads(state_file.read_text())
        history = data.get("confidence_history", [])
        if len(history) < 3:
            return ""

        # Get last 5 values
        recent = history[-5:]
        start, end = recent[0], recent[-1]
        diff = end - start

        if diff > 10:
            return "📈 Rising (+{})".format(diff)
        elif diff < -10:
            return "📉 Falling ({})".format(diff)
        else:
            return "➡️ Stable"
    except (json.JSONDecodeError, OSError, KeyError, IndexError):
        return ""


def get_test_results() -> str:
    """Get actual test results from recent runs."""
    # Check for pytest results
    pytest_cache = Path.cwd() / ".pytest_cache" / "v" / "cache" / "lastfailed"
    if pytest_cache.exists():
        try:
            import json

            data = json.loads(pytest_cache.read_text())
            if data:
                return f"⚠️ {len(data)} failing tests"
            return "✅ Tests passing"
        except (json.JSONDecodeError, OSError):
            pass

    # Check for jest results
    jest_results = Path.cwd() / "jest-results.json"
    if jest_results.exists():
        try:
            import json

            data = json.loads(jest_results.read_text())
            failed = data.get("numFailedTests", 0)
            if failed > 0:
                return f"⚠️ {failed} failing tests"
            return "✅ Tests passing"
        except (json.JSONDecodeError, OSError):
            pass

    return ""


def get_open_beads_count() -> int:
    """Get count of open beads for routing context."""
    try:
        result = subprocess.run(
            ["bd", "list", "--status=open"],
            capture_output=True,
            text=True,
            timeout=3,
            env={"BEADS_DIR": str(Path.home() / ".beads"), **subprocess.os.environ},
        )
        if result.returncode == 0 and result.stdout.strip():
            lines = result.stdout.strip().split("\n")
            # Count non-header, non-separator lines
            return len(
                [ln for ln in lines[1:] if ln.strip() and not ln.startswith("-")]
            )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return 0


def get_project_name(cwd: Path) -> str:
    """Get project name from various sources."""
    # Check for CLAUDE.md with project name
    claude_md = cwd / "CLAUDE.md"
    if claude_md.exists():
        return cwd.name

    # Check for package.json name
    pkg_json = cwd / "package.json"
    if pkg_json.exists():
        try:
            import json

            data = json.loads(pkg_json.read_text())
            return data.get("name", cwd.name)
        except (json.JSONDecodeError, OSError):
            pass

    # Check for pyproject.toml
    pyproject = cwd / "pyproject.toml"
    if pyproject.exists():
        return cwd.name

    return ""


def get_top_level_dirs(cwd: Path, max_dirs: int = 12) -> list[str]:
    """Get top-level directories for semantic pointer grounding.

    Returns actual directory names so Groq can suggest accurate file paths
    instead of guessing generic patterns like 'src/auth/'.
    """
    try:
        dirs = []
        for entry in cwd.iterdir():
            if entry.is_dir() and not entry.name.startswith("."):
                # Skip common non-code directories
                if entry.name in (
                    "node_modules",
                    "__pycache__",
                    "venv",
                    ".venv",
                    "dist",
                    "build",
                ):
                    continue
                dirs.append(entry.name)
        # Sort alphabetically, prioritize common code dirs
        priority = {
            "src",
            "lib",
            "app",
            "components",
            "pages",
            "api",
            "services",
            "utils",
        }
        dirs.sort(key=lambda d: (d not in priority, d))
        return dirs[:max_dirs]
    except (OSError, PermissionError):
        return []


def get_serena_memory_topics(cwd: Path | None = None, max_topics: int = 5) -> list[str]:
    """Get Serena memory topics for prior_art pointer suggestions.

    Returns memory filenames (without extension) that Groq can reference
    as prior_art pointers (e.g., "see memory: auth-flow-implementation").
    """
    topics = []

    serena_dirs = []
    if cwd:
        serena_dirs.append(cwd / ".serena" / "memories")
    serena_dirs.append(Path.home() / ".claude" / ".serena" / "memories")

    for serena_dir in serena_dirs:
        if not serena_dir.exists():
            continue
        try:
            for mem_file in serena_dir.glob("*.md"):
                # Skip session logs
                if mem_file.name.startswith("session_"):
                    continue
                topics.append(mem_file.stem)
        except (OSError, PermissionError):
            continue

    # Deduplicate and limit
    seen = set()
    unique_topics = []
    for t in topics:
        if t not in seen:
            seen.add(t)
            unique_topics.append(t)
    return unique_topics[:max_topics]


def get_recent_observations(max_items: int = 5) -> str:
    """Get recent claude-mem observations for router context.

    Queries the claude-mem worker API to get recent observations.
    Returns compact format: type + title for each observation.
    """
    import json
    import urllib.request
    import urllib.error

    # Type emoji mapping for compact display
    type_emoji = {
        "bugfix": "🔴",
        "feature": "🟣",
        "refactor": "🔄",
        "discovery": "🔵",
        "decision": "⚖️",
        "change": "✅",
    }

    try:
        url = f"http://localhost:37777/api/observations?limit={max_items}"
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=2) as resp:
            data = json.loads(resp.read().decode())

        items = data.get("items", [])
        if not items:
            return ""

        # Format: emoji title (compact)
        lines = []
        for obs in items:
            obs_type = obs.get("type", "change")
            emoji = type_emoji.get(obs_type, "📝")
            title = obs.get("title", "")[:60]  # Truncate long titles
            lines.append(f"{emoji} {title}")

        return "\n".join(lines)

    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        # Worker not running or error - gracefully degrade
        return ""


def get_session_start_context(max_sessions: int = 2, max_chars: int = 800) -> str:
    """Get high-value session context for first Groq call.

    At session start, we have no conversation history. Compensate by pulling
    rich context from claude-mem: recent session summaries with learned lessons
    and next steps. These are the highest ROI tokens for task classification.

    Args:
        max_sessions: Maximum number of recent sessions to include
        max_chars: Maximum total characters (token budget proxy)

    Returns:
        Formatted string with session summaries, or empty string on error.
    """
    import json
    import urllib.request
    import urllib.error

    try:
        # Query claude-mem for recent session context
        url = f"http://localhost:37777/api/sessions?limit={max_sessions}"
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode())

        sessions = data.get("items", [])
        if not sessions:
            return ""

        lines = []
        total_chars = 0

        for session in sessions:
            # Extract high-value fields
            summary = session.get("summary", {})
            learned = summary.get("learned", "")
            next_steps = summary.get("next_steps", "")
            request = summary.get("request", "")[:100]  # Truncate request

            # Build compact representation
            parts = []
            if request:
                parts.append(f"Task: {request}")
            if learned:
                # Learned lessons are highest value - include more
                learned_trunc = learned[:300] if len(learned) > 300 else learned
                parts.append(f"Learned: {learned_trunc}")
            if next_steps:
                next_trunc = next_steps[:150] if len(next_steps) > 150 else next_steps
                parts.append(f"Next: {next_trunc}")

            if parts:
                session_block = " | ".join(parts)
                if total_chars + len(session_block) > max_chars:
                    break
                lines.append(f"• {session_block}")
                total_chars += len(session_block)

        return "\n".join(lines) if lines else ""

    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return ""


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
    except Exception as e:
        logging.debug("context_packer: PAL continuation lookup failed: %s", e)
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
    user_prompt: str,
    cwd: Path | None = None,
    confidence: int | None = None,
    conversation_history: list[str] | None = None,
    turn_count: int = 0,
) -> PackedContext:
    """Pack context for router classification (4000 token budget).

    Focus on: user prompt, conversation context, repo type, basic structure.
    At session start (turn 0-1), includes rich claude-mem context to compensate
    for lack of conversation history.

    Args:
        user_prompt: The user's request
        cwd: Working directory for repo detection
        confidence: Current agent confidence level (0-100)
        conversation_history: Recent user prompts for context (max 5)
        turn_count: Current turn number (0-1 = session start, gets richer context)
    """
    config = get_config()
    budget = config.context_packer.router_token_budget
    cwd = cwd or Path.cwd()

    sections: dict[str, str] = {}

    # User prompt is highest priority
    sections["prompt"] = user_prompt

    # Conversation history (prior user prompts for context)
    if conversation_history and len(conversation_history) > 0:
        sections["conversation_history"] = conversation_history

    # Project name (helps with project-specific routing)
    project_name = get_project_name(cwd)
    if project_name:
        sections["project"] = project_name

    # Open beads count (work queue awareness)
    open_beads = get_open_beads_count()
    if open_beads > 0:
        sections["open_beads"] = open_beads

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

    # Top-level directories for semantic pointer grounding
    top_dirs = get_top_level_dirs(cwd)
    if top_dirs:
        sections["top_dirs"] = top_dirs

    # Serena memory topics for prior_art suggestions
    serena_topics = get_serena_memory_topics(cwd)
    if serena_topics:
        sections["serena_topics"] = serena_topics

    # Add confidence context if provided
    if confidence is not None:
        sections["confidence"] = get_confidence_context(confidence)
        # Add trend if available
        trend = get_confidence_trend()
        if trend:
            sections["confidence"] += f" | {trend}"

    # Add recent errors (critical for debugging classification)
    errors = get_recent_errors()
    if errors:
        sections["errors"] = errors

    # Add test results (actual pass/fail status)
    test_results = get_test_results()
    if test_results:
        sections["tests"] = test_results

    # Add memory hints (Path B - lightweight signals)
    if config.context_packer.include_memory_hints:
        memory_hints = get_memory_hints(cwd)
        if memory_hints["memory_count"] > 0:
            sections["memory_hints"] = memory_hints

    # Add compact git diff (file names only - critical for "continue" prompts)
    if config.context_packer.include_git_diff:
        git_diff = get_git_diff_compact(cwd)
        if git_diff:
            sections["git_diff"] = git_diff

    # Add in-progress beads (active task context)
    if config.context_packer.include_beads:
        beads = get_in_progress_beads()
        if beads:
            sections["beads"] = beads

    # Add serena status (semantic analysis availability)
    if config.context_packer.include_serena_context:
        serena = get_serena_status()
        if serena:
            sections["serena"] = serena

    # Add claude-mem context (richer at session start, lighter afterward)
    if config.context_packer.include_memory_hints:
        if turn_count <= 1:
            # Session start: get rich context with learned lessons and next steps
            # This compensates for lack of conversation history
            session_context = get_session_start_context(max_sessions=2, max_chars=800)
            if session_context:
                sections["session_context"] = session_context
        else:
            # Later turns: lightweight observations (conversation history provides context)
            observations = get_recent_observations(max_items=5)
            if observations:
                sections["observations"] = observations

    # Build packed prompt
    project_line = f" ({sections['project']})" if "project" in sections else ""
    beads_line = (
        f" | Open tasks: {sections['open_beads']}" if "open_beads" in sections else ""
    )
    packed = f"""## User Request
{sections["prompt"]}

## Repository
Type: {sections["repo_type"]}{project_line}{beads_line}
"""

    # Add conversation history (high priority - helps understand context)
    if "conversation_history" in sections:
        history = sections["conversation_history"]
        # Format as numbered list of prior prompts (excluding current)
        history_lines = []
        for i, prompt in enumerate(history[:-1], 1):  # Exclude last (current) prompt
            # Truncate long prompts for readability
            truncated = prompt[:200] + "..." if len(prompt) > 200 else prompt
            history_lines.append(f"{i}. {truncated}")
        if history_lines:
            packed += "\n## Prior Context (recent user messages)\n"
            packed += "\n".join(history_lines) + "\n"

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

    # Add top-level dirs for semantic pointer grounding
    if "top_dirs" in sections:
        dirs_str = ", ".join(sections["top_dirs"])
        packed += f"\n## Actual Directories\n{dirs_str}\n"
        packed += "(Use these actual paths in likely_relevant pointers, not generic guesses)\n"

    # Add serena memory topics for prior_art suggestions
    if "serena_topics" in sections:
        topics_str = ", ".join(sections["serena_topics"])
        packed += f"\n## Available Memories\n{topics_str}\n"
        packed += "(Reference these in prior_art pointers as 'see memory: <topic>')\n"

    # Add current work context (high signal for routing)
    if "git_diff" in sections:
        packed += f"\n## Modified Files\n{sections['git_diff']}\n"

    if "beads" in sections:
        packed += f"\n## Active Tasks\n{sections['beads']}\n"

    if "serena" in sections:
        packed += f"\n## Semantic Analysis\n{sections['serena']}\n"

    if "session_context" in sections:
        # Rich session start context (learned lessons, next steps)
        packed += f"\n## Recent Sessions (claude-mem)\n{sections['session_context']}\n"
    elif "observations" in sections:
        # Lightweight observations for later turns
        packed += f"\n## Recent Work (claude-mem)\n{sections['observations']}\n"

    if "errors" in sections:
        packed += f"\n## Recent Errors\n{sections['errors']}\n"

    if "tests" in sections:
        packed += f"\n## Test Status\n{sections['tests']}\n"

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
