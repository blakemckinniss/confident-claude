#!/usr/bin/env python3
"""
Schema Cache Manager for Code-Mode

Manages the MCP tool schema cache used by code-mode for multi-tool orchestration.

Usage:
    schema_cache.py --status      # Check cache state
    schema_cache.py --populate    # Populate from manifest
    schema_cache.py --clear       # Clear the cache
    schema_cache.py --ttl HOURS   # Set TTL when populating (default: 24)
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

# Add lib to path
LIB_DIR = Path(__file__).parent.parent / "lib"
if str(LIB_DIR) not in sys.path:
    sys.path.insert(0, str(LIB_DIR))

from _codemode_interfaces import (  # noqa: E402
    CACHE_PROTOCOL_VERSION,
    SCHEMA_CACHE,
    save_schemas_cache,
)

# =============================================================================
# SCHEMA MANIFEST - Curated list of commonly-used MCP tools
# =============================================================================
# This manifest contains the most frequently used tools for code-mode.
# Add new tools here as they become available.

SCHEMA_MANIFEST: dict[str, dict] = {
    # Serena - Semantic code analysis
    "mcp__serena__find_symbol": {
        "description": "Find symbols matching the given name path pattern.",
        "parameters": {
            "type": "object",
            "properties": {
                "name_path_pattern": {
                    "type": "string",
                    "description": "The name path matching pattern",
                },
                "relative_path": {
                    "type": "string",
                    "description": "Restrict search to this file or directory",
                },
                "include_body": {
                    "type": "boolean",
                    "description": "Include the symbol's source code",
                    "default": False,
                },
                "depth": {
                    "type": "integer",
                    "description": "Depth for retrieving descendants",
                    "default": 0,
                },
            },
            "required": ["name_path_pattern"],
        },
    },
    "mcp__serena__get_symbols_overview": {
        "description": "Get a high-level overview of code symbols in a file.",
        "parameters": {
            "type": "object",
            "properties": {
                "relative_path": {
                    "type": "string",
                    "description": "The relative path to the file",
                },
                "depth": {
                    "type": "integer",
                    "description": "Depth for retrieving descendants",
                    "default": 0,
                },
            },
            "required": ["relative_path"],
        },
    },
    "mcp__serena__find_referencing_symbols": {
        "description": "Find references to a symbol.",
        "parameters": {
            "type": "object",
            "properties": {
                "name_path": {
                    "type": "string",
                    "description": "Name path of the symbol to find references for",
                },
                "relative_path": {
                    "type": "string",
                    "description": "The relative path to the file containing the symbol",
                },
            },
            "required": ["name_path", "relative_path"],
        },
    },
    "mcp__serena__search_for_pattern": {
        "description": "Search for patterns in the codebase.",
        "parameters": {
            "type": "object",
            "properties": {
                "substring_pattern": {
                    "type": "string",
                    "description": "Regular expression pattern to search for",
                },
                "relative_path": {
                    "type": "string",
                    "description": "Restrict search to this path",
                },
                "context_lines_before": {
                    "type": "integer",
                    "description": "Context lines before match",
                    "default": 0,
                },
                "context_lines_after": {
                    "type": "integer",
                    "description": "Context lines after match",
                    "default": 0,
                },
            },
            "required": ["substring_pattern"],
        },
    },
    "mcp__serena__list_dir": {
        "description": "List files and directories in a directory.",
        "parameters": {
            "type": "object",
            "properties": {
                "relative_path": {
                    "type": "string",
                    "description": "The relative path to the directory",
                },
                "recursive": {
                    "type": "boolean",
                    "description": "Whether to scan subdirectories recursively",
                },
            },
            "required": ["relative_path", "recursive"],
        },
    },
    # PAL - External LLM consultation
    "mcp__pal__chat": {
        "description": "General chat and collaborative thinking partner.",
        "parameters": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "Your question or idea for collaborative thinking",
                },
                "model": {
                    "type": "string",
                    "description": "Model to use for the chat",
                },
                "working_directory_absolute_path": {
                    "type": "string",
                    "description": "Absolute path to working directory",
                },
                "continuation_id": {
                    "type": "string",
                    "description": "Thread continuation ID for multi-turn conversations",
                },
            },
            "required": ["prompt", "working_directory_absolute_path", "model"],
        },
    },
    "mcp__pal__debug": {
        "description": "Systematic debugging and root cause analysis.",
        "parameters": {
            "type": "object",
            "properties": {
                "step": {
                    "type": "string",
                    "description": "Investigation step content",
                },
                "step_number": {
                    "type": "integer",
                    "description": "Current step number",
                },
                "total_steps": {
                    "type": "integer",
                    "description": "Estimated total steps needed",
                },
                "next_step_required": {
                    "type": "boolean",
                    "description": "Whether another step is needed",
                },
                "findings": {
                    "type": "string",
                    "description": "Discoveries from this step",
                },
                "model": {
                    "type": "string",
                    "description": "Model to use",
                },
            },
            "required": ["step", "step_number", "total_steps", "next_step_required", "findings", "model"],
        },
    },
    "mcp__pal__thinkdeep": {
        "description": "Multi-stage investigation and reasoning for complex problems.",
        "parameters": {
            "type": "object",
            "properties": {
                "step": {
                    "type": "string",
                    "description": "Current work step content",
                },
                "step_number": {
                    "type": "integer",
                    "description": "Current step number",
                },
                "total_steps": {
                    "type": "integer",
                    "description": "Estimated total steps",
                },
                "next_step_required": {
                    "type": "boolean",
                    "description": "Whether another step is needed",
                },
                "findings": {
                    "type": "string",
                    "description": "Important findings discovered",
                },
                "model": {
                    "type": "string",
                    "description": "Model to use",
                },
            },
            "required": ["step", "step_number", "total_steps", "next_step_required", "findings", "model"],
        },
    },
    # Crawl4AI - Web scraping
    "mcp__crawl4ai__crawl": {
        "description": "Fetch and extract content from any URL with JS rendering.",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The URL to crawl",
                },
                "extract_links": {
                    "type": "boolean",
                    "description": "Whether to extract all links",
                    "default": False,
                },
            },
            "required": ["url"],
        },
    },
    "mcp__crawl4ai__ddg_search": {
        "description": "Search the web using DuckDuckGo.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query",
                },
                "num_results": {
                    "type": "integer",
                    "description": "Number of results to return",
                    "default": 10,
                },
            },
            "required": ["query"],
        },
    },
    # Repomix - Codebase packaging
    "mcp__plugin_repomix_mcp_repomix__pack_codebase": {
        "description": "Package a local code directory into a consolidated file.",
        "parameters": {
            "type": "object",
            "properties": {
                "directory": {
                    "type": "string",
                    "description": "Directory to pack (absolute path)",
                },
                "style": {
                    "type": "string",
                    "description": "Output format style",
                    "enum": ["xml", "markdown", "json", "plain"],
                    "default": "xml",
                },
                "compress": {
                    "type": "boolean",
                    "description": "Enable Tree-sitter compression",
                    "default": False,
                },
            },
            "required": ["directory"],
        },
    },
    # Filesystem - File operations
    "mcp__filesystem__read_text_file": {
        "description": "Read the complete contents of a file as text.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the file",
                },
                "head": {
                    "type": "number",
                    "description": "Only return first N lines",
                },
                "tail": {
                    "type": "number",
                    "description": "Only return last N lines",
                },
            },
            "required": ["path"],
        },
    },
    "mcp__filesystem__write_file": {
        "description": "Create or overwrite a file with new content.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the file",
                },
                "content": {
                    "type": "string",
                    "description": "Content to write",
                },
            },
            "required": ["path", "content"],
        },
    },
    "mcp__filesystem__list_directory": {
        "description": "Get a detailed listing of files and directories.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the directory",
                },
            },
            "required": ["path"],
        },
    },
    # Beads - Task tracking
    "mcp__beads__list_beads": {
        "description": "List beads/issues.",
        "parameters": {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "description": "Filter by status",
                    "enum": ["open", "in_progress", "blocked", "closed"],
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum results to return",
                    "default": 20,
                },
            },
        },
    },
    "mcp__beads__create_bead": {
        "description": "Create a new bead/issue.",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Bead title",
                },
                "description": {
                    "type": "string",
                    "description": "Bead description",
                },
                "type": {
                    "type": "string",
                    "description": "Bead type",
                    "enum": ["bug", "feature", "task", "epic", "chore"],
                    "default": "task",
                },
                "priority": {
                    "type": "string",
                    "description": "Priority 0-4 (0=highest)",
                    "default": "2",
                },
            },
            "required": ["title"],
        },
    },
    "mcp__beads__update_bead": {
        "description": "Update a bead's status or other fields.",
        "parameters": {
            "type": "object",
            "properties": {
                "id": {
                    "type": "string",
                    "description": "Bead ID",
                },
                "status": {
                    "type": "string",
                    "description": "New status",
                    "enum": ["open", "in_progress", "blocked", "closed"],
                },
            },
            "required": ["id"],
        },
    },
    "mcp__beads__close_bead": {
        "description": "Close a bead/issue.",
        "parameters": {
            "type": "object",
            "properties": {
                "id": {
                    "type": "string",
                    "description": "Bead ID to close",
                },
            },
            "required": ["id"],
        },
    },
}


def check_status() -> dict:
    """Check cache status and return info."""
    if not SCHEMA_CACHE.exists():
        return {
            "exists": False,
            "message": "Cache does not exist",
            "tool_count": 0,
        }

    try:
        data = json.loads(SCHEMA_CACHE.read_text())
        meta = data.get("_metadata", {})

        expires_at = meta.get("expires_at", 0)
        now = time.time()
        expired = now > expires_at

        return {
            "exists": True,
            "expired": expired,
            "protocol_version": meta.get("protocol_version"),
            "current_version": CACHE_PROTOCOL_VERSION,
            "version_match": meta.get("protocol_version") == CACHE_PROTOCOL_VERSION,
            "tool_count": meta.get("tool_count", 0),
            "created_at": meta.get("created_at"),
            "expires_at": expires_at,
            "ttl_remaining": max(0, expires_at - now) if not expired else 0,
            "message": "Cache valid" if not expired else "Cache expired",
        }
    except (json.JSONDecodeError, OSError) as e:
        return {
            "exists": True,
            "error": str(e),
            "message": "Cache corrupted",
            "tool_count": 0,
        }


def populate_cache(ttl_hours: float = 24) -> dict:
    """Populate cache from manifest."""
    ttl_seconds = int(ttl_hours * 3600)
    save_schemas_cache(SCHEMA_MANIFEST, ttl_seconds=ttl_seconds)

    return {
        "success": True,
        "tool_count": len(SCHEMA_MANIFEST),
        "ttl_hours": ttl_hours,
        "cache_path": str(SCHEMA_CACHE),
    }


def clear_cache() -> dict:
    """Clear the schema cache."""
    if SCHEMA_CACHE.exists():
        SCHEMA_CACHE.unlink()
        return {"success": True, "message": "Cache cleared"}
    return {"success": True, "message": "Cache did not exist"}


def main():
    parser = argparse.ArgumentParser(description="Manage code-mode schema cache")
    parser.add_argument("--status", action="store_true", help="Check cache status")
    parser.add_argument("--populate", action="store_true", help="Populate from manifest")
    parser.add_argument("--clear", action="store_true", help="Clear the cache")
    parser.add_argument("--ttl", type=float, default=24, help="TTL in hours (default: 24)")
    parser.add_argument("--json", action="store_true", help="Output as JSON")

    args = parser.parse_args()

    if args.status:
        result = check_status()
    elif args.populate:
        result = populate_cache(args.ttl)
    elif args.clear:
        result = clear_cache()
    else:
        # Default: show status
        result = check_status()

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        # Human-friendly output
        if "error" in result:
            print(f"❌ Error: {result['error']}")
        elif result.get("success"):
            print(f"✅ {result.get('message', 'Success')}")
            if "tool_count" in result:
                print(f"   Tools: {result['tool_count']}")
            if "ttl_hours" in result:
                print(f"   TTL: {result['ttl_hours']} hours")
        else:
            status_icon = "✅" if result.get("exists") and not result.get("expired") else "⚠️"
            print(f"{status_icon} {result.get('message', 'Unknown')}")
            if result.get("tool_count"):
                print(f"   Tools: {result['tool_count']}")
            if result.get("ttl_remaining"):
                hours = result["ttl_remaining"] / 3600
                print(f"   TTL remaining: {hours:.1f} hours")
            if result.get("expired"):
                print("   Run --populate to refresh")


if __name__ == "__main__":
    main()
