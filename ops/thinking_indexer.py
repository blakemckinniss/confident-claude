#!/usr/bin/env python3
"""
thinking_indexer.py - Index and search thinking blocks from session transcripts.

Creates semantic memories from reasoning traces, enabling metacognitive recall
across sessions.

Usage:
  thinking_indexer.py index [--max N]     Index recent sessions
  thinking_indexer.py search "query"      Search thinking memories
  thinking_indexer.py stats               Show index statistics
  thinking_indexer.py prune [--keep N]    Prune old records
  thinking_indexer.py show <id>           Show a specific record
"""

import sys
import os

# Add lib to path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "lib"))

from core import setup_script, finalize, logger, handle_debug  # noqa: E402
from thinking_memory import (  # noqa: E402
    index_recent_sessions,
    search_thinking_records,
    get_thinking_stats,
    prune_old_records,
    load_thinking_records,
    format_thinking_for_injection,
)


def cmd_index(args):
    """Index recent sessions."""
    max_sessions = args.max if hasattr(args, "max") else 20
    logger.info(f"Indexing up to {max_sessions} recent sessions...")

    results = index_recent_sessions(max_sessions=max_sessions)

    logger.info(f"Indexed: {results['indexed']}")
    logger.info(f"Skipped: {results['skipped']} (duplicates or no thinking)")
    if results["failed"]:
        logger.warning(f"Failed: {results['failed']}")

    if getattr(args, "verbose", False):
        for detail in results["details"]:
            status = "+" if detail["success"] else "-"
            logger.debug(f"  {status} {detail['file']}: {detail['message']}")

    return results["indexed"] > 0 or results["skipped"] > 0


def cmd_search(args):
    """Search thinking memories."""
    query = args.query
    limit = args.limit if hasattr(args, "limit") else 5

    logger.info(f"Searching for: {query}")

    records = search_thinking_records(query=query, limit=limit)

    if not records:
        logger.warning("No matching thinking memories found")
        return False

    print(f"\n{'='*60}")
    print(f"Found {len(records)} relevant thinking memories:")
    print(f"{'='*60}\n")

    for i, record in enumerate(records, 1):
        print(f"[{i}] {record.id} (score: {record.relevance_score:.1f})")
        print(f"    Type: {record.problem_type} | Outcome: {record.outcome}")
        print(f"    Patterns: {', '.join(record.reasoning_patterns)}")
        print(f"    Keywords: {', '.join(record.keywords[:8])}")
        print(f"    Summary: {record.thinking_summary[:200]}...")
        print()

    if args.format:
        print("\n--- Injection Format ---")
        print(format_thinking_for_injection(records))

    return True


def cmd_stats(args):
    """Show index statistics."""
    stats = get_thinking_stats()

    if stats["total"] == 0:
        logger.warning("No thinking memories indexed yet")
        logger.info("Run: thinking_indexer.py index")
        return False

    print(f"\n{'='*40}")
    print("Thinking Memory Statistics")
    print(f"{'='*40}")
    print(f"Total records: {stats['total']}")
    print(f"Avg confidence delta: {stats['avg_confidence_delta']:+.1f}")

    print("\nBy problem type:")
    for ptype, count in sorted(stats["by_problem_type"].items(), key=lambda x: -x[1]):
        print(f"  {ptype}: {count}")

    print("\nBy outcome:")
    for outcome, count in sorted(stats["by_outcome"].items(), key=lambda x: -x[1]):
        print(f"  {outcome}: {count}")

    print("\nReasoning patterns detected:")
    for pattern, count in sorted(stats["reasoning_patterns"].items(), key=lambda x: -x[1]):
        print(f"  {pattern}: {count}")

    return True


def cmd_prune(args):
    """Prune old records."""
    keep = args.keep if hasattr(args, "keep") else 500
    logger.info(f"Pruning to keep {keep} most recent records...")

    removed = prune_old_records(keep_count=keep)
    logger.info(f"Removed {removed} old records")

    return True


def cmd_show(args):
    """Show a specific record."""
    record_id = args.id
    records = load_thinking_records(limit=1000)

    for record in records:
        if record.id == record_id:
            print(f"\n{'='*60}")
            print(f"Record: {record.id}")
            print(f"{'='*60}")
            print(f"Session: {record.session_id}")
            print(f"Timestamp: {record.timestamp}")
            print(f"Problem Type: {record.problem_type}")
            print(f"Outcome: {record.outcome}")
            print(f"Confidence Delta: {record.confidence_delta:+d}")
            print(f"\nKeywords: {', '.join(record.keywords)}")
            print(f"Tools: {', '.join(record.tools_used)}")
            print(f"Patterns: {', '.join(record.reasoning_patterns)}")
            print("\nFiles touched:")
            for f in record.files_touched[:10]:
                print(f"  {f}")
            print("\nThinking Summary:")
            print(record.thinking_summary)
            return True

    logger.error(f"Record not found: {record_id}")
    return False


def main():
    parser = setup_script("Index and search thinking blocks from session transcripts")

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # index command
    p_index = subparsers.add_parser("index", help="Index recent sessions")
    p_index.add_argument("--max", type=int, default=20, help="Max sessions to index")

    # search command
    p_search = subparsers.add_parser("search", help="Search thinking memories")
    p_search.add_argument("query", help="Search query")
    p_search.add_argument("--limit", type=int, default=5, help="Max results")
    p_search.add_argument("--format", action="store_true", help="Show injection format")

    # stats command
    subparsers.add_parser("stats", help="Show index statistics")

    # prune command
    p_prune = subparsers.add_parser("prune", help="Prune old records")
    p_prune.add_argument("--keep", type=int, default=500, help="Records to keep")

    # show command
    p_show = subparsers.add_parser("show", help="Show a specific record")
    p_show.add_argument("id", help="Record ID")

    args = parser.parse_args()
    handle_debug(args)

    if not args.command:
        parser.print_help()
        finalize(success=False)

    if args.dry_run:
        logger.warning("DRY RUN MODE")
        finalize(success=True)

    commands = {
        "index": cmd_index,
        "search": cmd_search,
        "stats": cmd_stats,
        "prune": cmd_prune,
        "show": cmd_show,
    }

    success = commands[args.command](args)
    finalize(success=success)


if __name__ == "__main__":
    main()
