#!/usr/bin/env python3
"""
Spark Core: In-process memory retrieval (no subprocess overhead).

Extracted from .claude/ops/spark.py for direct import.
Provides ~100-500ms latency reduction by eliminating subprocess spawn.

Memory sources (in order):
1. Synapses (__synapses.json) - Static pattern→association map
2. Lessons (__lessons.md) - Dynamic keyword matches
3. Session History (session_rag) - Past conversation excerpts
4. Random Constraints - Lateral thinking prompts
"""

import json
import os
import re
import random
from pathlib import Path
from typing import Optional

# Find project root
_LIB_DIR = Path(__file__).parent
_CLAUDE_DIR = _LIB_DIR.parent
_PROJECT_ROOT = _CLAUDE_DIR.parent
MEMORY_DIR = _CLAUDE_DIR / "memory"

# Synapse map location
SYNAPSE_FILE = MEMORY_DIR / "__synapses.json"
LESSONS_FILE = MEMORY_DIR / "__lessons.md"

# Cached synapse map (loaded once per process)
_SYNAPSE_CACHE: Optional[dict] = None

# Lessons file cache: (mtime, list of lines)
_LESSONS_CACHE: Optional[tuple] = None

# Session RAG integration (lazy import to avoid circular deps)
_SESSION_RAG_AVAILABLE: Optional[bool] = None


def _load_synapses() -> dict:
    """Load synapse map with caching."""
    global _SYNAPSE_CACHE
    if _SYNAPSE_CACHE is not None:
        return _SYNAPSE_CACHE

    try:
        if SYNAPSE_FILE.exists():
            _SYNAPSE_CACHE = json.loads(SYNAPSE_FILE.read_text())
        else:
            _SYNAPSE_CACHE = {"patterns": {}, "random_constraints": [], "meta": {}}
    except (json.JSONDecodeError, IOError):
        _SYNAPSE_CACHE = {"patterns": {}, "random_constraints": [], "meta": {}}

    return _SYNAPSE_CACHE


def query_lessons(keywords: list[str], max_results: int = 3) -> list[str]:
    """Scan lessons file for matches with caching.

    Performance: Caches file content by mtime to avoid repeated file reads.
    """
    global _LESSONS_CACHE

    if not LESSONS_FILE.exists():
        return []

    # Check cache by file mtime
    try:
        file_mtime = LESSONS_FILE.stat().st_mtime
    except OSError:
        file_mtime = 0

    if _LESSONS_CACHE and _LESSONS_CACHE[0] == file_mtime:
        lines = _LESSONS_CACHE[1]
    else:
        try:
            lines = LESSONS_FILE.read_text().split("\n")
            _LESSONS_CACHE = (file_mtime, lines)
        except (IOError, OSError):
            return []

    matches = []
    for line in lines:
        if line.startswith("#") or not line.strip():
            continue

        line_lower = line.lower()
        if any(kw.lower() in line_lower for kw in keywords):
            cleaned = line.strip()
            if cleaned and cleaned not in matches:
                matches.append(cleaned)
                if len(matches) >= max_results:
                    break

    return matches


def extract_keywords_from_pattern(pattern: str) -> list[str]:
    """Extract keywords from regex pattern for lesson search."""
    keywords = (
        pattern.replace("(", "")
        .replace(")", "")
        .replace("|", " ")
        .replace("\\", "")
        .split()
    )
    return [k for k in keywords if len(k) > 3]


def query_session_history(query: str, max_results: int = 2) -> list[str]:
    """Query past session transcripts for relevant context.

    Lazy-loads session_rag module to avoid import overhead when not needed.
    Returns list of relevant excerpt strings (truncated for token efficiency).
    """
    global _SESSION_RAG_AVAILABLE

    # Check availability once
    if _SESSION_RAG_AVAILABLE is None:
        try:
            import session_rag

            _SESSION_RAG_AVAILABLE = True
        except ImportError:
            _SESSION_RAG_AVAILABLE = False

    if not _SESSION_RAG_AVAILABLE:
        return []

    try:
        import session_rag

        results = session_rag.search_sessions(query, max_results=max_results)

        # Format as concise strings
        excerpts = []
        for r in results:
            # Truncate to 200 chars for token efficiency
            text = r.get("text", "")[:200]
            if text:
                date = r.get("timestamp", "")[:10]
                excerpts.append(f"[{date}] {text}...")

        return excerpts
    except Exception:
        return []


def fire_synapses(
    prompt: str, include_constraints: bool = True, include_session_history: bool = True
) -> dict:
    """
    Core synapse firing logic - returns associations and memories.

    This is the main function to call. Returns:
    {
        "has_associations": bool,
        "associations": list[str],      # From synapses.json patterns
        "memories": list[str],          # From lessons.md
        "session_history": list[str],   # From past session transcripts
        "constraint": str | None,       # Random lateral thinking prompt
        "matched_patterns": list[str]   # Which patterns fired
    }
    """
    synapses = _load_synapses()
    patterns = synapses.get("patterns", {})
    random_constraints = synapses.get("random_constraints", [])
    meta = synapses.get("meta", {})

    max_associations = meta.get("max_associations", 5)
    max_memories = meta.get("max_memories", 3)
    max_session_excerpts = meta.get("max_session_excerpts", 2)
    constraint_probability = meta.get("constraint_probability", 0.10)

    prompt_lower = prompt.lower()

    # 1. Check Synapse Map (Static Associations)
    associations = []
    active_keywords = []
    matched_patterns = []

    for pattern, links in patterns.items():
        try:
            if re.search(pattern, prompt_lower, re.IGNORECASE):
                matched_patterns.append(pattern)
                associations.extend(links[:max_associations])
                keywords = extract_keywords_from_pattern(pattern)
                active_keywords.extend(keywords)
        except re.error:
            continue  # Skip invalid patterns

    # Remove duplicates while preserving order
    associations = list(dict.fromkeys(associations))[:max_associations]

    # 2. Check Lessons (Dynamic Associations)
    memories = []
    if active_keywords:
        memories = query_lessons(active_keywords, max_results=max_memories)

    # 3. Check Session History (Past Conversations)
    session_history = []
    if include_session_history and len(prompt) >= 10:
        # Use first 100 chars of prompt as query
        session_history = query_session_history(
            prompt[:100], max_results=max_session_excerpts
        )

    # 4. Random Constraint Injection (Lateral Thinking)
    constraint = None
    if include_constraints and random_constraints:
        if random.random() < constraint_probability:
            constraint = random.choice(random_constraints)

    has_content = (
        len(associations) > 0
        or len(memories) > 0
        or len(session_history) > 0
        or constraint is not None
    )

    return {
        "has_associations": has_content,
        "associations": associations,
        "memories": memories,
        "session_history": session_history,
        "constraint": constraint,
        "matched_patterns": matched_patterns,
    }


def invalidate_cache():
    """Clear all caches (synapses, lessons, session history)."""
    global _SYNAPSE_CACHE, _LESSONS_CACHE, _SESSION_RAG_AVAILABLE
    _SYNAPSE_CACHE = None
    _LESSONS_CACHE = None

    # Also invalidate session RAG cache if available
    if _SESSION_RAG_AVAILABLE:
        try:
            import session_rag

            session_rag.invalidate_cache()
        except Exception:
            pass
