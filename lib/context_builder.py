#!/usr/bin/env python3
"""
Context Builder for Council Consultations (v2)
==========================================

Enriches council proposals with relevant project context.
Fixes from void analysis:
- Explicit error handling (no silent failures)
- Audit trail (logs enriched context)
- Structured output (dict, not pre-formatted string)
- Configurable limits

Usage:
    from context_builder import build_council_context
    result = build_council_context("Should we migrate to GraphQL?", "session-123")
    if result["success"]:
        enriched = result["formatted"]
    else:
        print(f"Error: {result['error']}")
"""

import os
import re
import json
import subprocess
import logging
from pathlib import Path
from typing import List, Dict, Tuple, Optional
from datetime import datetime

# Setup logging
logger = logging.getLogger(__name__)


class ContextBuildError(Exception):
    """Raised when context building fails critically"""

    pass


# Configuration (can be overridden)
class ContextConfig:
    """Configuration for context builder"""

    STOP_WORDS = {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "has",
        "he",
        "in",
        "is",
        "it",
        "its",
        "of",
        "on",
        "that",
        "the",
        "to",
        "was",
        "will",
        "with",
        "we",
        "should",
        "can",
        "could",
        "would",
        "this",
        "what",
        "when",
        "where",
        "who",
        "how",
        "why",
        "i",
        "you",
        "they",
        "them",
        "their",
        "our",
    }

    # Scoring weights
    SUMMARY_SCORE_WEIGHT = 2
    TOPIC_SCORE_WEIGHT = 3
    ENTITY_SCORE_WEIGHT = 1

    # Limits
    TOP_MEMORIES = 3
    TOP_SESSIONS = 3
    TOP_FILES_READ = 5
    TOP_KEYWORDS = 10
    MIN_SECTION_LENGTH = 20
    MIN_KEYWORD_LENGTH = 3
    MAX_FILE_LINES = 500  # Truncate files longer than this
    FILE_TRUNCATE_HEAD = 250  # Show first N lines
    FILE_TRUNCATE_TAIL = 250  # Show last N lines

    # Timeouts
    GIT_TIMEOUT = 5

    # Paths (relative to project root)
    MEMORY_DIR = ".claude/memory"
    LESSONS_FILE = "__lessons.md"
    DECISIONS_FILE = "__decisions.md"
    DIGESTS_DIR = "session_digests"
    AUDIT_DIR = "context_audit"

    # Project root marker
    ROOT_MARKER = ".claude/lib/core.py"


def find_project_root(start_path: str = None) -> Optional[Path]:
    """
    Find project root by walking up directory tree looking for marker file.

    Returns:
        Path to project root, or None if not found
    """
    if start_path is None:
        start_path = os.path.abspath(__file__)

    current = Path(start_path).resolve()

    # Walk up to root
    while str(current) != "/":
        marker = current / ContextConfig.ROOT_MARKER
        if marker.exists():
            logger.debug(f"Found project root: {current}")
            return current
        current = current.parent

    logger.error(
        f"Could not find project root (looking for {ContextConfig.ROOT_MARKER})"
    )
    return None


def extract_keywords(text: str, min_length: int = None) -> List[str]:
    """Extract significant keywords from text"""
    if min_length is None:
        min_length = ContextConfig.MIN_KEYWORD_LENGTH

    # Tokenize
    tokens = re.findall(r"\b\w+\b", text.lower())

    # Filter stop words and short tokens
    keywords = [
        t for t in tokens if t not in ContextConfig.STOP_WORDS and len(t) >= min_length
    ]

    # Return unique keywords (preserve order)
    seen = set()
    unique = []
    for k in keywords:
        if k not in seen:
            seen.add(k)
            unique.append(k)

    return unique


def extract_mentioned_files(
    proposal: str, project_root: Path
) -> List[Tuple[str, Path, int]]:
    """
    Extract file paths mentioned in proposal.

    Returns:
        List of (mention, resolved_path, line_count) tuples for files that exist
    """
    found_files = []

    # Pattern 1: Common filename patterns (CLAUDE.md, README.md, config.json, etc.)
    filename_pattern = (
        r"\b([A-Z_][A-Za-z0-9_\-]*\.(md|py|json|yaml|yml|txt|sh|js|ts))\b"
    )
    for match in re.finditer(filename_pattern, proposal):
        filename = match.group(1)

        # Try to find file in project root and common directories
        search_paths = [
            project_root / filename,
            project_root / ".claude" / filename,
            project_root / ".claude" / filename,
            project_root / ".claude" / "ops" / filename,
            project_root / ".claude" / "lib" / filename,
        ]

        for path in search_paths:
            if path.exists() and path.is_file():
                try:
                    line_count = len(path.read_text().split("\n"))
                    found_files.append((filename, path, line_count))
                    break
                except Exception as e:
                    logger.warning(f"Could not read {path}: {e}")

    # Pattern 2: Explicit file paths (.claude/ops/council.py, ./src/main.py, etc.)
    # Match paths with directory separators
    path_pattern = r"(?:\.{0,2}/)?(?:[a-zA-Z0-9_\-]+/)+[a-zA-Z0-9_\-]+\.[a-z]{2,4}"
    for match in re.finditer(path_pattern, proposal):
        path_str = match.group(0)
        path = project_root / path_str.lstrip("./")

        if path.exists() and path.is_file():
            try:
                line_count = len(path.read_text().split("\n"))
                # Avoid duplicates
                if not any(str(p[1]) == str(path) for p in found_files):
                    found_files.append((path_str, path, line_count))
            except Exception as e:
                logger.warning(f"Could not read {path}: {e}")

    return found_files


def read_file_with_truncation(file_path: Path, max_lines: int = None) -> Dict:
    """
    Read file with intelligent truncation.

    Returns:
        Dict with 'content', 'total_lines', 'truncated' keys
    """
    if max_lines is None:
        max_lines = ContextConfig.MAX_FILE_LINES

    try:
        full_content = file_path.read_text()
        lines = full_content.split("\n")
        total_lines = len(lines)

        if total_lines <= max_lines:
            return {
                "content": full_content,
                "total_lines": total_lines,
                "truncated": False,
            }

        # Truncate: show head + tail
        head = lines[: ContextConfig.FILE_TRUNCATE_HEAD]
        tail = lines[-ContextConfig.FILE_TRUNCATE_TAIL :]
        truncated_content = "\n".join(head)
        truncated_content += (
            f"\n\n... [{total_lines - max_lines} lines omitted] ...\n\n"
        )
        truncated_content += "\n".join(tail)

        return {
            "content": truncated_content,
            "total_lines": total_lines,
            "truncated": True,
        }

    except Exception as e:
        logger.error(f"Failed to read {file_path}: {e}")
        return {
            "content": f"ERROR: Could not read file: {e}",
            "total_lines": 0,
            "truncated": False,
        }


# Memory file cache: {file_path: (mtime, list of sections)}
_MEMORY_FILE_CACHE: Dict[str, tuple] = {}


def search_memories(keywords: List[str], project_root: Path) -> Dict[str, List[str]]:
    """
    Search lessons.md and decisions.md for keyword matches.

    Performance: Caches parsed sections by file mtime to avoid repeated file reads.

    Raises:
        FileNotFoundError: If memory directory doesn't exist
        PermissionError: If files can't be read
    """
    memory_dir = project_root / ContextConfig.MEMORY_DIR

    if not memory_dir.exists():
        raise FileNotFoundError(f"Memory directory not found: {memory_dir}")

    results = {"lessons": [], "decisions": []}

    for memory_type in ["lessons", "decisions"]:
        file_path = memory_dir / f"{memory_type}.md"

        if not file_path.exists():
            logger.warning(f"Memory file not found: {file_path}")
            continue

        # Check cache by file mtime
        cache_key = str(file_path)
        try:
            file_mtime = file_path.stat().st_mtime
        except OSError:
            file_mtime = 0

        cached = _MEMORY_FILE_CACHE.get(cache_key)
        if cached and cached[0] == file_mtime:
            sections = cached[1]
        else:
            try:
                content = file_path.read_text()
            except PermissionError as e:
                raise PermissionError(f"Cannot read {file_path}: {e}")
            except UnicodeDecodeError as e:
                logger.error(f"Encoding error in {file_path}: {e}")
                continue

            # Parse and cache sections
            raw_sections = re.split(r"\n\s*\n", content)
            sections = [
                s.strip()
                for s in raw_sections
                if len(s.strip()) >= ContextConfig.MIN_SECTION_LENGTH
            ]
            _MEMORY_FILE_CACHE[cache_key] = (file_mtime, sections)

        # Score sections by keyword density
        scored_sections = []
        for section in sections:
            section_lower = section.lower()
            matches = sum(1 for kw in keywords if kw in section_lower)
            if matches > 0:
                scored_sections.append((matches, section))

        # Sort by score and take top N
        scored_sections.sort(reverse=True, key=lambda x: x[0])
        top_matches = [s[1] for s in scored_sections[: ContextConfig.TOP_MEMORIES]]

        results[memory_type] = top_matches

    return results


# Session digest cache: {digests_dir: (mtime, list of parsed digests)}
_SESSION_DIGEST_CACHE: Dict[str, tuple] = {}
MAX_SESSION_FILES_SCAN = 50  # Limit to prevent O(n) growth


def _load_session_digests(digests_dir: Path) -> List[Dict]:
    """Load and cache session digests from directory."""
    cache_key = str(digests_dir)
    try:
        dir_mtime = digests_dir.stat().st_mtime
    except OSError:
        dir_mtime = 0

    cached = _SESSION_DIGEST_CACHE.get(cache_key)
    if cached and cached[0] == dir_mtime:
        return cached[1]

    # Rebuild cache - get most recent files only
    digest_files = sorted(
        digests_dir.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True
    )[:MAX_SESSION_FILES_SCAN]

    all_digests = []
    for digest_file in digest_files:
        if digest_file.stem.startswith("tmp."):
            continue
        try:
            with open(digest_file) as f:
                digest = json.load(f)
                digest["_filename"] = digest_file.stem
                all_digests.append(digest)
        except (json.JSONDecodeError, Exception) as e:
            logger.warning(f"Error reading {digest_file}: {e}")

    _SESSION_DIGEST_CACHE[cache_key] = (dir_mtime, all_digests)
    return all_digests


def _score_digest(digest: Dict, keywords: List[str]) -> int:
    """Score a digest by keyword matches in summary, topic, and entities."""
    score = 0
    summary = digest.get("summary", "").lower()
    score += sum(ContextConfig.SUMMARY_SCORE_WEIGHT for kw in keywords if kw in summary)

    topic = digest.get("current_topic", "").lower()
    score += sum(ContextConfig.TOPIC_SCORE_WEIGHT for kw in keywords if kw in topic)

    entities = [e.lower() for e in digest.get("active_entities", [])]
    score += sum(
        ContextConfig.ENTITY_SCORE_WEIGHT
        for kw in keywords
        if any(kw in e for e in entities)
    )
    return score


def find_related_sessions(
    keywords: List[str], project_root: Path, current_session: str
) -> List[Dict]:
    """
    Find session digests with similar topics.

    Performance: Limits scan to MAX_SESSION_FILES_SCAN most recent files,
    and caches parsed digests by directory mtime.

    Returns:
        List of related session dicts, or empty list if directory doesn't exist
    """
    digests_dir = project_root / ContextConfig.MEMORY_DIR / ContextConfig.DIGESTS_DIR

    if not digests_dir.exists():
        logger.warning(f"Session digests directory not found: {digests_dir}")
        return []

    all_digests = _load_session_digests(digests_dir)

    # Score and filter digests
    scored_sessions = [
        (_score_digest(d, keywords), d)
        for d in all_digests
        if d.get("_filename") != current_session and _score_digest(d, keywords) > 0
    ]

    # Sort by score and return top N
    scored_sessions.sort(reverse=True, key=lambda x: x[0])
    return [s[1] for s in scored_sessions[: ContextConfig.TOP_SESSIONS]]


def get_session_state(session_id: str, project_root: Path) -> Dict:
    """
    Load current session state.

    Returns:
        Dict with session state, or default values if file not found

    Raises:
        PermissionError: If state file exists but can't be read
    """
    state_file = (
        project_root / ContextConfig.MEMORY_DIR / f"session_{session_id}_state.json"
    )

    default_state = {
        "confidence": 0,
        "risk": 0,
        "tier": "IGNORANCE",
        "evidence_count": 0,
        "files_read": [],
        "tools_used": [],
    }

    if not state_file.exists():
        logger.debug(f"Session state file not found: {state_file}")
        return default_state

    try:
        with open(state_file) as f:
            state = json.load(f)
    except PermissionError as e:
        raise PermissionError(f"Cannot read session state: {e}")
    except json.JSONDecodeError as e:
        logger.error(f"Corrupted session state file: {e}")
        return default_state

    # Extract relevant fields
    confidence = state.get("confidence", 0)
    tier = state.get("tier", "IGNORANCE")
    risk = state.get("risk", 0)

    # Extract evidence stats
    evidence = state.get("evidence_ledger", [])
    evidence_count = len(evidence)

    # Get unique files read
    files_read = list(
        set(
            e.get("file_path", "")
            for e in evidence
            if e.get("tool") == "Read" and e.get("file_path")
        )
    )[: ContextConfig.TOP_FILES_READ]

    # Get unique tools used
    tools_used = list(set(e.get("tool", "") for e in evidence if e.get("tool")))

    return {
        "confidence": confidence,
        "risk": risk,
        "tier": tier,
        "evidence_count": evidence_count,
        "files_read": files_read,
        "tools_used": tools_used,
    }


def get_git_status(project_root: Path) -> Dict[str, str]:
    """
    Get current git branch and uncommitted changes summary.

    Returns:
        Dict with 'branch', 'changes', 'error' keys
        - If git unavailable/fails, 'error' key will be present
    """
    result = {"branch": None, "changes": None, "error": None}

    try:
        # Get current branch
        branch_result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=ContextConfig.GIT_TIMEOUT,
        )

        if branch_result.returncode == 0:
            result["branch"] = branch_result.stdout.strip()
        else:
            # Not a git repo or git error
            result["error"] = f"Git branch check failed: {branch_result.stderr.strip()}"
            logger.warning(result["error"])
            return result

        # Get uncommitted changes summary
        status_result = subprocess.run(
            ["git", "status", "--short"],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=ContextConfig.GIT_TIMEOUT,
        )

        if status_result.returncode == 0:
            lines = status_result.stdout.strip().split("\n")
            modified = len(
                [
                    line
                    for line in lines
                    if line.startswith(" M") or line.startswith("M ")
                ]
            )
            added = len(
                [
                    line
                    for line in lines
                    if line.startswith("A ") or line.startswith("??")
                ]
            )
            deleted = len(
                [
                    line
                    for line in lines
                    if line.startswith(" D") or line.startswith("D ")
                ]
            )

            result["changes"] = f"{modified} modified, {added} added, {deleted} deleted"
        else:
            result["error"] = f"Git status check failed: {status_result.stderr.strip()}"
            logger.warning(result["error"])

        return result

    except FileNotFoundError:
        result["error"] = "Git binary not found in PATH"
        logger.error(result["error"])
        return result
    except subprocess.TimeoutExpired:
        result["error"] = f"Git command timed out after {ContextConfig.GIT_TIMEOUT}s"
        logger.error(result["error"])
        return result
    except Exception as e:
        result["error"] = f"Git command failed: {e}"
        logger.error(result["error"])
        return result


def save_context_audit(
    session_id: str, proposal: str, context_data: Dict, project_root: Path
):
    """
    Save audit trail of enriched context.

    Creates: .claude/memory/context_audit/<session_id>_<timestamp>.json
    """
    audit_dir = project_root / ContextConfig.MEMORY_DIR / ContextConfig.AUDIT_DIR
    audit_dir.mkdir(exist_ok=True, parents=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    audit_file = audit_dir / f"{session_id}_{timestamp}.json"

    audit_data = {
        "session_id": session_id,
        "timestamp": datetime.now().isoformat(),
        "proposal": proposal,
        "context": context_data,
    }

    try:
        with open(audit_file, "w") as f:
            json.dump(audit_data, f, indent=2)
        logger.info(f"Context audit saved: {audit_file}")
    except Exception as e:
        logger.error(f"Failed to save context audit: {e}")


def _format_git_section(git: Dict, repo_name: str) -> List[str]:
    """Format git status section."""
    parts = ["PROJECT CONTEXT:", f"- Repository: {repo_name}"]
    if git.get("error"):
        parts.append(f"- Git: {git['error']}")
    else:
        parts.append(f"- Current Branch: {git.get('branch', 'unknown')}")
        parts.append(f"- Working Tree: {git.get('changes', 'unknown')}")
    parts.append("")
    return parts


def _format_session_section(session: Dict) -> List[str]:
    """Format session state section."""
    parts = [
        "SESSION STATE:",
        f"- Confidence: {session.get('confidence', 0)}% ({session.get('tier', 'UNKNOWN')} tier)",
        f"- Risk: {session.get('risk', 0)}%",
        f"- Evidence Gathered: {session.get('evidence_count', 0)} items",
    ]
    if session.get("files_read"):
        parts.append(f"- Files Examined: {', '.join(session['files_read'])}")
    if session.get("tools_used"):
        parts.append(f"- Tools Used: {', '.join(session['tools_used'])}")
    parts.append("")
    return parts


def _format_memories_section(memories: Dict) -> List[str]:
    """Format relevant memories section."""
    if not memories.get("lessons") and not memories.get("decisions"):
        return []
    parts = ["RELEVANT MEMORIES:"]
    for mem_type in ("lessons", "decisions"):
        items = memories.get(mem_type, [])
        if items:
            parts.append(f"\n{mem_type.title()}:")
            for item in items:
                preview = item if len(item) < 200 else item[:200] + "..."
                parts.append(f"  - {preview}")
    parts.append("")
    return parts


def _format_artifacts_section(file_artifacts: List[Dict]) -> List[str]:
    """Format file artifacts section."""
    if not file_artifacts:
        return []
    parts = ["=" * 70, "FILE ARTIFACTS (Mentioned in Proposal)", "=" * 70, ""]
    for artifact in file_artifacts:
        file_data = artifact["file_data"]
        truncated_mark = ", TRUNCATED" if file_data["truncated"] else ""
        parts.append(
            f"### {artifact['filename']} ({file_data['total_lines']} lines{truncated_mark})"
        )
        parts.extend(["```", file_data["content"], "```", ""])
    parts.extend(["=" * 70, ""])
    return parts


def format_context(proposal: str, context_data: Dict, project_root: Path) -> str:
    """Format enriched context as string for council consumption."""
    parts = ["PROPOSAL:", proposal, ""]

    # Project and git context
    repo_name = project_root.name if project_root else "unknown"
    parts.extend(_format_git_section(context_data.get("git_status", {}), repo_name))

    # Session state
    parts.extend(_format_session_section(context_data.get("session_state", {})))

    # Memories
    parts.extend(_format_memories_section(context_data.get("memories", {})))

    # Related sessions
    sessions = context_data.get("related_sessions", [])
    if sessions:
        parts.append("RELATED PAST SESSIONS:")
        for sess in sessions:
            parts.append(f"  - Topic: {sess.get('current_topic', 'Unknown topic')}")
            parts.append(f"    Summary: {sess.get('summary', 'No summary')}")
        parts.append("")

    # File artifacts
    parts.extend(_format_artifacts_section(context_data.get("file_artifacts", [])))

    # Keywords
    keywords = context_data.get("keywords", [])
    if keywords:
        parts.append(
            f"KEYWORDS EXTRACTED: {', '.join(keywords[: ContextConfig.TOP_KEYWORDS])}"
        )
        parts.append("")

    return "\n".join(parts)


def _load_file_artifacts(proposal: str, project_root: Path) -> List[Dict]:
    """Load file artifacts mentioned in proposal."""
    mentioned_files = extract_mentioned_files(proposal, project_root)
    if not mentioned_files:
        return []

    logger.info(f"Found {len(mentioned_files)} mentioned files in proposal")
    artifacts = []
    for filename, file_path, line_count in mentioned_files:
        logger.info(f"  - {filename} ({line_count} lines)")
        artifacts.append(
            {
                "filename": filename,
                "file_path": str(file_path),
                "file_data": read_file_with_truncation(file_path),
            }
        )
    return artifacts


def _gather_memories(
    keywords: List[str], project_root: Path, warnings: List[str]
) -> Dict:
    """Gather memories with error handling."""
    try:
        return search_memories(keywords, project_root)
    except FileNotFoundError as e:
        warnings.append(f"Memory directory not found: {e}")
        return {"lessons": [], "decisions": []}


def build_council_context(
    proposal: str,
    session_id: str = "unknown",
    project_root: Path = None,
    save_audit: bool = True,
) -> Dict:
    """
    Build enriched context for council consultation.

    Returns:
        Dict with success, formatted, raw_data, error, and warnings keys.
    """
    warnings = []

    # Find project root
    if project_root is None:
        project_root = find_project_root()
        if project_root is None:
            return {
                "success": False,
                "error": f"Could not find project root (looking for {ContextConfig.ROOT_MARKER})",
                "warnings": [],
            }

    try:
        keywords = extract_keywords(proposal)
        if not keywords:
            warnings.append("No keywords extracted from proposal")

        # Gather context - permission errors are fatal
        try:
            session_state = get_session_state(session_id, project_root)
        except PermissionError as e:
            return {"success": False, "error": str(e), "warnings": warnings}

        memories = _gather_memories(keywords, project_root, warnings)
        if memories is None:  # PermissionError case handled differently
            return {
                "success": False,
                "error": "Permission denied reading memories",
                "warnings": warnings,
            }

        git_status = get_git_status(project_root)
        if git_status.get("error"):
            warnings.append(git_status["error"])

        # Build context data
        context_data = {
            "keywords": keywords,
            "session_state": session_state,
            "memories": memories,
            "related_sessions": find_related_sessions(
                keywords, project_root, session_id
            ),
            "git_status": git_status,
            "file_artifacts": _load_file_artifacts(proposal, project_root),
        }

        formatted = format_context(proposal, context_data, project_root)

        if save_audit:
            try:
                save_context_audit(session_id, proposal, context_data, project_root)
            except Exception as e:
                warnings.append(f"Failed to save audit trail: {e}")

        return {
            "success": True,
            "formatted": formatted,
            "raw_data": context_data,
            "warnings": warnings,
        }

    except Exception as e:
        logger.exception("Unexpected error building context")
        return {
            "success": False,
            "error": f"Unexpected error: {e}",
            "warnings": warnings,
        }
