#!/usr/bin/env python3
"""
Session RAG: Semantic search over past session transcripts.

Indexes JSONL files from .claude/projects/-home-jinx/ for keyword-based
retrieval of past conversations. Designed for low-latency, no external deps.
"""

import json
import re
from pathlib import Path
from typing import Optional

# Paths
_LIB_DIR = Path(__file__).parent
_CLAUDE_DIR = _LIB_DIR.parent
_PROJECTS_DIR = _CLAUDE_DIR / "projects" / "-home-jinx"

# Cache: {file_path: (mtime, list of extracted records)}
_SESSION_CACHE: dict = {}

# Index: {keyword: [(file, excerpt, timestamp)]}
_KEYWORD_INDEX: Optional[dict] = None
_INDEX_MTIME: float = 0  # Track latest file mtime for cache invalidation

# Stopwords for keyword filtering (O(1) lookup)
_STOPWORDS = frozenset(
    {
        "this",
        "that",
        "with",
        "from",
        "have",
        "been",
        "will",
        "would",
        "could",
        "should",
        "their",
        "there",
        "they",
        "what",
        "when",
        "where",
        "which",
        "were",
        "your",
        "about",
    }
)


def _extract_text_from_message(msg: dict) -> Optional[str]:
    """Extract searchable text from a message record."""
    content = msg.get("message", {}).get("content")
    if not content:
        return None

    # Handle string content
    if isinstance(content, str):
        return content[:2000]  # Limit length

    # Handle list content (tool use, etc.)
    if isinstance(content, list):
        texts = []
        for block in content:
            if isinstance(block, dict):
                if block.get("type") == "text":
                    texts.append(block.get("text", "")[:1000])
                # Skip thinking blocks - too verbose
        return " ".join(texts)[:2000] if texts else None

    return None


def _parse_session_file(filepath: Path) -> list[dict]:
    """Parse JSONL file and extract relevant records."""
    records = []
    try:
        mtime = filepath.stat().st_mtime

        # Check cache
        cache_key = str(filepath)
        if cache_key in _SESSION_CACHE:
            cached_mtime, cached_records = _SESSION_CACHE[cache_key]
            if cached_mtime == mtime:
                return cached_records

        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                    msg_type = record.get("type")

                    # Only index user and assistant messages
                    if msg_type not in ("user", "assistant"):
                        continue

                    text = _extract_text_from_message(record)
                    if text and len(text) > 50:  # Skip trivial messages
                        records.append(
                            {
                                "text": text,
                                "role": record.get("message", {}).get(
                                    "role", "unknown"
                                ),
                                "timestamp": record.get("timestamp", ""),
                                "session_id": record.get("sessionId", filepath.stem),
                            }
                        )
                except json.JSONDecodeError:
                    continue

        # Cache results
        _SESSION_CACHE[cache_key] = (mtime, records)

    except (IOError, OSError):
        pass

    return records


def _get_session_files() -> list[tuple[float, Path]]:
    """Get session files sorted by mtime descending, excluding agent files."""
    if not _PROJECTS_DIR.exists():
        return []
    session_files = []
    for f in _PROJECTS_DIR.glob("*.jsonl"):
        if f.name.startswith("agent-"):
            continue  # Skip agent transcripts - they're subsets
        try:
            session_files.append((f.stat().st_mtime, f))
        except OSError:
            continue
    session_files.sort(reverse=True)
    return session_files


def _extract_keywords(text: str) -> list[str]:
    """Extract keywords from text (4+ chars, no stopwords)."""
    cleaned = re.sub(r"[^\w\s]", " ", text.lower())
    words = set(cleaned.split())
    return [w for w in words if len(w) >= 4 and w not in _STOPWORDS]


def _add_to_index(index: dict, keywords: list[str], excerpt: dict):
    """Add excerpt to index under each keyword (max 50 per keyword)."""
    for kw in keywords:
        if kw not in index:
            index[kw] = []
        if len(index[kw]) < 50:  # Limit per keyword
            index[kw].append(excerpt)


def _build_index(max_files: int = 20) -> dict:
    """Build keyword index from recent session files."""
    global _KEYWORD_INDEX, _INDEX_MTIME

    session_files = _get_session_files()
    if not session_files:
        return {}

    latest_mtime = session_files[0][0]

    # Check if rebuild needed
    if _KEYWORD_INDEX is not None and latest_mtime <= _INDEX_MTIME:
        return _KEYWORD_INDEX

    # Build fresh index
    index: dict = {}

    for mtime, filepath in session_files[:max_files]:
        records = _parse_session_file(filepath)

        for rec in records:
            keywords = _extract_keywords(rec["text"])
            excerpt = {
                "text": rec["text"][:500],
                "role": rec["role"],
                "timestamp": rec["timestamp"],
                "session_id": rec["session_id"],
                "file": filepath.name,
            }
            _add_to_index(index, keywords, excerpt)

    _KEYWORD_INDEX = index
    _INDEX_MTIME = latest_mtime
    return index


def search_sessions(query: str, max_results: int = 5) -> list[dict]:
    """
    Search past sessions for relevant excerpts.

    Args:
        query: Search query (keywords)
        max_results: Maximum results to return

    Returns:
        List of matching excerpts with metadata
    """
    index = _build_index()
    if not index:
        return []

    # Extract query keywords
    query_lower = query.lower()
    query_words = re.sub(r"[^\w\s]", " ", query_lower).split()
    query_keywords = [w for w in query_words if len(w) >= 3]

    if not query_keywords:
        return []

    # Score excerpts by keyword matches
    scored: dict = {}  # excerpt_key -> (score, excerpt)

    for kw in query_keywords:
        # Exact and prefix matches
        for idx_kw, excerpts in index.items():
            if idx_kw == kw or idx_kw.startswith(kw):
                for exc in excerpts:
                    key = (exc["session_id"], exc["timestamp"])
                    if key not in scored:
                        scored[key] = (0, exc)
                    scored[key] = (scored[key][0] + 1, exc)

    # Sort by score, return top results
    results = sorted(scored.values(), key=lambda x: -x[0])
    return [exc for score, exc in results[:max_results]]


def get_stats() -> dict:
    """Get index statistics."""
    index = _build_index()

    unique_sessions = set()
    total_excerpts = 0
    for excerpts in index.values():
        for exc in excerpts:
            unique_sessions.add(exc["session_id"])
            total_excerpts += 1

    return {
        "indexed_keywords": len(index),
        "total_excerpts": total_excerpts,
        "unique_sessions": len(unique_sessions),
        "projects_dir": str(_PROJECTS_DIR),
    }


def invalidate_cache():
    """Clear all caches (call if files change externally)."""
    global _SESSION_CACHE, _KEYWORD_INDEX, _INDEX_MTIME
    _SESSION_CACHE = {}
    _KEYWORD_INDEX = None
    _INDEX_MTIME = 0


# CLI interface
if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: session_rag.py <query> | --stats")
        sys.exit(1)

    if sys.argv[1] == "--stats":
        stats = get_stats()
        print(f"Keywords indexed: {stats['indexed_keywords']}")
        print(f"Total excerpts: {stats['total_excerpts']}")
        print(f"Sessions: {stats['unique_sessions']}")
        print(f"Source: {stats['projects_dir']}")
    else:
        query = " ".join(sys.argv[1:])
        results = search_sessions(query)

        if not results:
            print(f"No results for: {query}")
        else:
            print(f"Found {len(results)} results for: {query}\n")
            for i, r in enumerate(results, 1):
                print(f"--- [{i}] {r['role']} @ {r['timestamp'][:10]} ---")
                print(r["text"][:300])
                print()
