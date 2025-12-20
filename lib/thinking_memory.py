#!/usr/bin/env python3
"""
thinking_memory.py - Metacognitive memory system for thinking token capture and retrieval.

This module provides infrastructure for:
1. Extracting thinking blocks from session transcripts
2. Summarizing and classifying reasoning patterns
3. Storing thinking with semantic metadata
4. Retrieving relevant past thinking for context injection

The goal is to give Claude "metacognitive memory" - remembering not just WHAT was done,
but HOW problems were reasoned through, enabling cross-session learning.

Storage Format (JSONL at ~/.claude/memory/thinking_index.jsonl):
{
    "id": "think_abc123",
    "session_id": "uuid",
    "timestamp": "ISO8601",
    "thinking_summary": "Compressed reasoning trace",
    "problem_type": "debugging|planning|refactoring|...",
    "keywords": ["keyword1", "keyword2"],
    "tools_used": ["Bash", "Read", "Edit"],
    "files_touched": ["path/to/file.py"],
    "outcome": "success|failure|partial",
    "confidence_delta": -15,  # Net confidence change during this reasoning
    "full_thinking_hash": "sha256",  # For deduplication
    "reasoning_patterns": ["hypothesis_testing", "verification", "decomposition"]
}
"""

import json
import os
import re
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, asdict

# Framework paths
CLAUDE_DIR = Path.home() / ".claude"
MEMORY_DIR = CLAUDE_DIR / "memory"
THINKING_INDEX_PATH = MEMORY_DIR / "thinking_index.jsonl"
THINKING_CACHE_PATH = CLAUDE_DIR / "tmp" / "thinking_cache.json"
PROJECTS_DIR = CLAUDE_DIR / "projects"

# Reasoning pattern detectors
REASONING_PATTERNS = {
    "hypothesis_testing": [
        r"(?:my|the) (?:hypothesis|theory) is",
        r"I (?:think|suspect|believe) (?:the|this|that)",
        r"let me (?:check|verify|test) (?:if|whether)",
        r"this (?:might|could|may) be (?:because|due to)",
    ],
    "verification": [
        r"to (?:confirm|verify|validate)",
        r"let me (?:check|make sure|double-check)",
        r"I should (?:verify|confirm|test)",
        r"checking (?:if|whether|that)",
    ],
    "decomposition": [
        r"(?:first|step 1|to start)",
        r"break(?:ing)? (?:this|it) down",
        r"the (?:steps|approach|plan) (?:is|are|would be)",
        r"(?:then|next|after that)",
    ],
    "elimination": [
        r"(?:not|isn't|can't be) (?:the|this|that)",
        r"ruling out",
        r"this (?:isn't|is not|can't be) (?:the|it)",
        r"(?:eliminated|excluding|ruled out)",
    ],
    "evidence_gathering": [
        r"(?:found|see|notice) that",
        r"the (?:error|output|result) (?:shows|indicates|suggests)",
        r"looking at (?:the|this)",
        r"based on (?:the|this|what)",
    ],
    "dead_end_recognition": [
        r"(?:this|that) (?:didn't|doesn't|won't) work",
        r"(?:wrong|incorrect) approach",
        r"(?:tried|attempted) .* but",
        r"need(?:s)? (?:a different|another) approach",
    ],
    "solution_synthesis": [
        r"the (?:fix|solution|answer) is",
        r"(?:should|need to|must) (?:be|do|use)",
        r"(?:works|fixed|resolved) because",
        r"the (?:key|trick|insight) is",
    ],
}

# Problem type classifiers
PROBLEM_TYPES = {
    "debugging": [
        r"(?:bug|error|issue|problem|broken|failing|crash)",
        r"(?:doesn't|does not|isn't|won't) (?:work|run|compile|pass)",
        r"(?:fix|debug|trace|investigate)",
    ],
    "implementation": [
        r"(?:implement|create|build|add|write) (?:a|the|new)",
        r"(?:feature|functionality|capability)",
        r"(?:how (?:to|do I)|need to) (?:implement|create|add)",
    ],
    "refactoring": [
        r"(?:refactor|restructure|reorganize|clean up)",
        r"(?:move|rename|extract|consolidate)",
        r"(?:improve|optimize) (?:the|this) (?:code|structure)",
    ],
    "investigation": [
        r"(?:understand|figure out|find|locate|search)",
        r"(?:where|what|how|why) (?:is|does|did)",
        r"(?:looking for|searching|exploring)",
    ],
    "configuration": [
        r"(?:config|setting|environment|setup)",
        r"(?:configure|set up|enable|disable)",
        r"(?:\.env|yaml|json|toml) (?:file)?",
    ],
    "integration": [
        r"(?:integrate|connect|hook|wire)",
        r"(?:api|service|endpoint|webhook)",
        r"(?:between|with) (?:the|this|these)",
    ],
}


@dataclass
class ThinkingRecord:
    """A single indexed thinking memory."""
    id: str
    session_id: str
    timestamp: str
    thinking_summary: str
    problem_type: str
    keywords: List[str]
    tools_used: List[str]
    files_touched: List[str]
    outcome: str
    confidence_delta: int
    full_thinking_hash: str
    reasoning_patterns: List[str]
    relevance_score: float = 0.0  # Set during retrieval

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ThinkingRecord":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class SessionContext:
    """Context extracted from a session for thinking analysis."""
    session_id: str
    thinking_blocks: List[str]
    tools_used: List[str]
    files_touched: List[str]
    user_messages: List[str]
    confidence_start: int
    confidence_end: int
    outcome: str  # success, failure, partial, unknown


def extract_session_context(transcript_path: str) -> Optional[SessionContext]:
    """Extract full context from a session transcript for thinking indexing."""
    if not os.path.exists(transcript_path):
        return None

    session_id = Path(transcript_path).stem
    thinking_blocks = []
    tools_used = set()
    files_touched = set()
    user_messages = []
    confidence_start = 75  # Default
    confidence_end = 75

    try:
        with open(transcript_path, "r", encoding="utf-8", errors="replace") as f:
            first_conf_seen = False
            for line in f:
                if not line.strip():
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                entry_type = entry.get("type", "")

                # Extract thinking blocks
                if entry_type == "assistant":
                    content = entry.get("message", {}).get("content", [])
                    if isinstance(content, list):
                        for block in content:
                            if isinstance(block, dict) and block.get("type") == "thinking":
                                thinking_text = block.get("thinking", "")
                                if len(thinking_text) > 100:  # Skip trivial thinking
                                    thinking_blocks.append(thinking_text)

                # Extract tool usage
                if entry_type == "tool_use":
                    tool_name = entry.get("name", "")
                    if tool_name:
                        tools_used.add(tool_name)
                    # Extract file paths from tool input
                    tool_input = entry.get("input", {})
                    for key in ["file_path", "path", "paths", "relative_path"]:
                        val = tool_input.get(key)
                        if val:
                            if isinstance(val, list):
                                files_touched.update(val)
                            else:
                                files_touched.add(val)

                # Extract user messages
                if entry_type == "user":
                    msg = entry.get("message", {})
                    if isinstance(msg, dict):
                        content = msg.get("content", "")
                        if isinstance(content, str) and len(content) > 10:
                            user_messages.append(content[:500])  # Truncate long messages

                # Track confidence (look for confidence patterns in system reminders)
                if entry_type == "assistant":
                    content = entry.get("message", {}).get("content", [])
                    if isinstance(content, list):
                        for block in content:
                            if isinstance(block, dict) and block.get("type") == "text":
                                text = block.get("text", "")
                                # Look for confidence percentages
                                conf_match = re.search(r"(\d{1,3})%", text)
                                if conf_match:
                                    conf_val = int(conf_match.group(1))
                                    if 0 <= conf_val <= 100:
                                        if not first_conf_seen:
                                            confidence_start = conf_val
                                            first_conf_seen = True
                                        confidence_end = conf_val

        # Determine outcome based on confidence trajectory
        if confidence_end >= confidence_start + 10:
            outcome = "success"
        elif confidence_end <= confidence_start - 15:
            outcome = "failure"
        elif thinking_blocks:
            outcome = "partial"
        else:
            outcome = "unknown"

        return SessionContext(
            session_id=session_id,
            thinking_blocks=thinking_blocks,
            tools_used=list(tools_used),
            files_touched=list(files_touched),
            user_messages=user_messages,
            confidence_start=confidence_start,
            confidence_end=confidence_end,
            outcome=outcome,
        )

    except Exception:
        return None


def classify_problem_type(thinking_text: str, user_messages: List[str]) -> str:
    """Classify the problem type based on thinking and user messages."""
    combined = thinking_text.lower() + " " + " ".join(user_messages).lower()

    scores = {}
    for problem_type, patterns in PROBLEM_TYPES.items():
        score = sum(
            len(re.findall(pattern, combined, re.IGNORECASE))
            for pattern in patterns
        )
        scores[problem_type] = score

    if not scores or max(scores.values()) == 0:
        return "general"

    return max(scores, key=scores.get)


def detect_reasoning_patterns(thinking_text: str) -> List[str]:
    """Detect which reasoning patterns are present in thinking."""
    detected = []
    text_lower = thinking_text.lower()

    for pattern_name, pattern_regexes in REASONING_PATTERNS.items():
        for regex in pattern_regexes:
            if re.search(regex, text_lower, re.IGNORECASE):
                detected.append(pattern_name)
                break  # One match per pattern type is enough

    return detected


def extract_keywords(thinking_text: str, user_messages: List[str]) -> List[str]:
    """Extract meaningful keywords for retrieval."""
    combined = thinking_text + " " + " ".join(user_messages)

    # Remove common words and extract meaningful terms
    words = re.findall(r'\b[a-zA-Z_][a-zA-Z0-9_]{2,}\b', combined)

    # Count frequency
    freq = {}
    stopwords = {
        "the", "and", "that", "this", "for", "are", "was", "were", "been",
        "have", "has", "had", "will", "would", "could", "should", "may",
        "might", "must", "can", "let", "see", "look", "need", "want",
        "know", "think", "make", "get", "use", "try", "check", "find",
        "file", "code", "function", "method", "class", "line", "error",
    }

    for word in words:
        word_lower = word.lower()
        if word_lower not in stopwords and len(word) > 3:
            freq[word_lower] = freq.get(word_lower, 0) + 1

    # Return top keywords by frequency
    sorted_keywords = sorted(freq.items(), key=lambda x: x[1], reverse=True)
    return [kw for kw, _ in sorted_keywords[:15]]


def summarize_thinking(thinking_blocks: List[str], max_length: int = 800) -> str:
    """Create a compressed summary of thinking blocks."""
    if not thinking_blocks:
        return ""

    # Take key sentences from each block
    summaries = []
    chars_remaining = max_length

    for block in thinking_blocks:
        if chars_remaining <= 0:
            break

        # Extract first few sentences and any key insights
        sentences = re.split(r'(?<=[.!?])\s+', block)

        # Prioritize sentences with key patterns
        priority_patterns = [
            r"the (?:issue|problem|bug|error) is",
            r"(?:found|discovered|noticed) that",
            r"the (?:fix|solution|answer) is",
            r"(?:because|due to|caused by)",
            r"(?:should|need to|must) (?:be|do|use)",
        ]

        priority_sentences = []
        other_sentences = []

        for sentence in sentences[:10]:  # First 10 sentences
            is_priority = any(re.search(p, sentence, re.I) for p in priority_patterns)
            if is_priority:
                priority_sentences.append(sentence)
            else:
                other_sentences.append(sentence)

        # Take priority sentences first, then fill with others
        selected = priority_sentences[:3] + other_sentences[:2]
        block_summary = " ".join(selected)

        if len(block_summary) > chars_remaining:
            block_summary = block_summary[:chars_remaining] + "..."

        summaries.append(block_summary)
        chars_remaining -= len(block_summary) + 10

    return " | ".join(summaries)


def create_thinking_record(context: SessionContext) -> Optional[ThinkingRecord]:
    """Create a thinking record from session context."""
    if not context.thinking_blocks:
        return None

    combined_thinking = " ".join(context.thinking_blocks)

    # Create hash for deduplication
    thinking_hash = hashlib.sha256(combined_thinking.encode()).hexdigest()[:16]

    # Generate unique ID
    record_id = f"think_{context.session_id[:8]}_{datetime.now().strftime('%H%M%S')}"

    return ThinkingRecord(
        id=record_id,
        session_id=context.session_id,
        timestamp=datetime.now(timezone.utc).isoformat(),
        thinking_summary=summarize_thinking(context.thinking_blocks),
        problem_type=classify_problem_type(combined_thinking, context.user_messages),
        keywords=extract_keywords(combined_thinking, context.user_messages),
        tools_used=context.tools_used,
        files_touched=context.files_touched[:20],  # Limit file list
        outcome=context.outcome,
        confidence_delta=context.confidence_end - context.confidence_start,
        full_thinking_hash=thinking_hash,
        reasoning_patterns=detect_reasoning_patterns(combined_thinking),
    )


def save_thinking_record(record: ThinkingRecord) -> bool:
    """Append a thinking record to the index."""
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)

    try:
        # Check for duplicates
        existing_hashes = set()
        if THINKING_INDEX_PATH.exists():
            with open(THINKING_INDEX_PATH, "r") as f:
                for line in f:
                    try:
                        existing = json.loads(line)
                        existing_hashes.add(existing.get("full_thinking_hash", ""))
                    except json.JSONDecodeError:
                        continue

        if record.full_thinking_hash in existing_hashes:
            return False  # Duplicate

        with open(THINKING_INDEX_PATH, "a") as f:
            f.write(json.dumps(record.to_dict()) + "\n")

        return True
    except Exception:
        return False


def load_thinking_records(
    limit: int = 100,
    problem_type: Optional[str] = None,
    outcome: Optional[str] = None,
) -> List[ThinkingRecord]:
    """Load thinking records from index with optional filters."""
    if not THINKING_INDEX_PATH.exists():
        return []

    records = []
    try:
        with open(THINKING_INDEX_PATH, "r") as f:
            for line in f:
                try:
                    data = json.loads(line)
                    record = ThinkingRecord.from_dict(data)

                    # Apply filters
                    if problem_type and record.problem_type != problem_type:
                        continue
                    if outcome and record.outcome != outcome:
                        continue

                    records.append(record)
                except (json.JSONDecodeError, TypeError):
                    continue

        # Return most recent first
        records.reverse()
        return records[:limit]

    except Exception:
        return []


def search_thinking_records(
    query: str,
    keywords: Optional[List[str]] = None,
    files: Optional[List[str]] = None,
    problem_type: Optional[str] = None,
    min_confidence_delta: int = -100,
    limit: int = 5,
) -> List[ThinkingRecord]:
    """Search thinking records by relevance."""
    all_records = load_thinking_records(limit=500)

    query_lower = query.lower()
    query_words = set(re.findall(r'\b[a-zA-Z_][a-zA-Z0-9_]{2,}\b', query_lower))

    scored_records = []

    for record in all_records:
        score = 0.0

        # Problem type match
        if problem_type and record.problem_type == problem_type:
            score += 20

        # Confidence filter
        if record.confidence_delta < min_confidence_delta:
            continue

        # Keyword overlap
        record_keywords = set(k.lower() for k in record.keywords)
        keyword_overlap = len(query_words & record_keywords)
        score += keyword_overlap * 10

        # Additional keyword match
        if keywords:
            additional_overlap = len(set(k.lower() for k in keywords) & record_keywords)
            score += additional_overlap * 8

        # File path match
        if files:
            file_basenames = set(Path(f).name for f in files)
            record_basenames = set(Path(f).name for f in record.files_touched)
            file_overlap = len(file_basenames & record_basenames)
            score += file_overlap * 15

        # Summary text match
        summary_lower = record.thinking_summary.lower()
        summary_word_matches = sum(1 for w in query_words if w in summary_lower)
        score += summary_word_matches * 5

        # Outcome bonus (prefer successful reasoning)
        if record.outcome == "success":
            score *= 1.3
        elif record.outcome == "failure":
            score *= 0.7

        # Reasoning pattern diversity bonus
        score += len(record.reasoning_patterns) * 2

        if score > 0:
            record.relevance_score = score
            scored_records.append(record)

    # Sort by score and return top results
    scored_records.sort(key=lambda r: r.relevance_score, reverse=True)
    return scored_records[:limit]


def format_thinking_for_injection(
    records: List[ThinkingRecord],
    max_tokens: int = 1500,
) -> str:
    """Format thinking records for context injection."""
    if not records:
        return ""

    lines = ["# Relevant Past Reasoning", ""]
    chars_used = 50

    for i, record in enumerate(records[:3], 1):
        if chars_used >= max_tokens * 4:  # Rough char-to-token ratio
            break

        entry = [
            f"## [{record.problem_type.title()}] {', '.join(record.keywords[:5])}",
            f"**Patterns**: {', '.join(record.reasoning_patterns)}",
            f"**Outcome**: {record.outcome} (confidence {record.confidence_delta:+d})",
            f"**Reasoning**: {record.thinking_summary}",
            "",
        ]

        entry_text = "\n".join(entry)
        if chars_used + len(entry_text) > max_tokens * 4:
            break

        lines.extend(entry)
        chars_used += len(entry_text)

    return "\n".join(lines)


def index_session(transcript_path: str) -> Tuple[bool, str]:
    """Index a single session's thinking blocks."""
    context = extract_session_context(transcript_path)
    if not context:
        return False, "Failed to extract session context"

    if not context.thinking_blocks:
        return False, "No thinking blocks found in session"

    record = create_thinking_record(context)
    if not record:
        return False, "Failed to create thinking record"

    if save_thinking_record(record):
        return True, f"Indexed {len(context.thinking_blocks)} thinking blocks as {record.id}"
    else:
        return False, "Duplicate or failed to save"


def index_recent_sessions(max_sessions: int = 20) -> Dict[str, Any]:
    """Index thinking from recent sessions."""
    results = {"indexed": 0, "skipped": 0, "failed": 0, "details": []}

    # Find all project session directories
    session_files = []
    if PROJECTS_DIR.exists():
        for project_dir in PROJECTS_DIR.iterdir():
            if project_dir.is_dir():
                for jsonl_file in project_dir.glob("*.jsonl"):
                    session_files.append(jsonl_file)

    # Sort by modification time (most recent first)
    session_files.sort(key=lambda p: p.stat().st_mtime, reverse=True)

    for session_file in session_files[:max_sessions]:
        success, message = index_session(str(session_file))
        if success:
            results["indexed"] += 1
        elif "Duplicate" in message or "No thinking" in message:
            results["skipped"] += 1
        else:
            results["failed"] += 1
        results["details"].append({"file": session_file.name, "success": success, "message": message})

    return results


def get_relevant_thinking_for_prompt(
    user_prompt: str,
    current_files: Optional[List[str]] = None,
    max_records: int = 3,
) -> str:
    """Get formatted relevant thinking for injection into a prompt."""
    # Classify the incoming problem
    problem_type = classify_problem_type(user_prompt, [user_prompt])
    keywords = extract_keywords(user_prompt, [])

    # Search for relevant past thinking
    records = search_thinking_records(
        query=user_prompt,
        keywords=keywords,
        files=current_files,
        problem_type=problem_type if problem_type != "general" else None,
        min_confidence_delta=-10,  # Prefer sessions that didn't tank confidence
        limit=max_records,
    )

    # Only include if we have reasonably relevant matches
    if not records or records[0].relevance_score < 15:
        return ""

    return format_thinking_for_injection(records)


# Statistics and maintenance functions

def get_thinking_stats() -> Dict[str, Any]:
    """Get statistics about the thinking memory index."""
    records = load_thinking_records(limit=10000)

    if not records:
        return {"total": 0}

    problem_types = {}
    outcomes = {}
    patterns = {}

    for r in records:
        problem_types[r.problem_type] = problem_types.get(r.problem_type, 0) + 1
        outcomes[r.outcome] = outcomes.get(r.outcome, 0) + 1
        for p in r.reasoning_patterns:
            patterns[p] = patterns.get(p, 0) + 1

    return {
        "total": len(records),
        "by_problem_type": problem_types,
        "by_outcome": outcomes,
        "reasoning_patterns": patterns,
        "avg_confidence_delta": sum(r.confidence_delta for r in records) / len(records),
    }


def prune_old_records(keep_count: int = 500) -> int:
    """Keep only the most recent N records."""
    if not THINKING_INDEX_PATH.exists():
        return 0

    records = load_thinking_records(limit=10000)
    if len(records) <= keep_count:
        return 0

    # Records are already sorted most-recent-first by load_thinking_records
    records_to_keep = records[:keep_count]

    # Rewrite the file
    with open(THINKING_INDEX_PATH, "w") as f:
        for record in reversed(records_to_keep):  # Restore chronological order
            f.write(json.dumps(record.to_dict()) + "\n")

    return len(records) - keep_count
