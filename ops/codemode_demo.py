#!/usr/bin/env python3
"""
Code-Mode Pipeline Demo

Demonstrates the full code-mode infrastructure:
1. Schema cache - Tool schema management
2. PlanExecutor - Dependency-aware execution
3. ResultCache - TTL-based caching for repeated calls
4. HandoffState - Queuing calls for Claude execution
5. Hook integration - Context injection for pending calls

Usage:
    codemode_demo.py --all          # Run all demos
    codemode_demo.py --cache        # Demo ResultCache
    codemode_demo.py --plan         # Demo PlanExecutor
    codemode_demo.py --handoff      # Demo HandoffState protocol
    codemode_demo.py --hook         # Demo hook integration
    codemode_demo.py --status       # Show system status
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

from _codemode_executor import (  # noqa: E402
    PlanExecutor,
    ResultCache,
    ToolCallRequest,
    clear_handoff_state,
    get_completed_result,
    get_pending_calls,
    read_handoff_state,
    record_tool_result,
    submit_tool_call,
    HANDOFF_STATE,
    EXECUTION_LOG,
)
from _codemode_planner import (
    CodeModePlanner,
    ToolCallSpec,
    ExecutionPlan,
    generate_run_id,
)  # noqa: E402
from _codemode_interfaces import SCHEMA_CACHE  # noqa: E402

# Demo constants
CONTEXT_PREVIEW_CHARS = 500
DEMO_CACHE_TTL_SECONDS = 10
DEMO_CACHE_MAX_ENTRIES = 5
MOCK_LATENCY_SECONDS = 0.05
PARALLEL_CACHE_TTL_SECONDS = 60


def print_header(title: str) -> None:
    """Print a formatted section header."""
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}\n")


def print_subheader(title: str) -> None:
    """Print a formatted subsection header."""
    print(f"\n--- {title} ---\n")


def demo_status() -> None:
    """Show current system status."""
    print_header("Code-Mode System Status")

    # Schema cache status
    print_subheader("Schema Cache")
    if SCHEMA_CACHE.exists():
        try:
            data = json.loads(SCHEMA_CACHE.read_text())
            meta = data.get("_metadata", {})
            tool_count = meta.get("tool_count", 0)
            expires_at = meta.get("expires_at", 0)
            ttl_remaining = max(0, expires_at - time.time())
            print(f"  ✅ Cache exists: {tool_count} tools")
            print(f"  ⏱️  TTL remaining: {ttl_remaining / 3600:.1f} hours")
        except (json.JSONDecodeError, OSError):
            print("  ⚠️  Cache exists but corrupted")
    else:
        print("  ❌ Cache not populated")
        print("     Run: python ~/.claude/ops/schema_cache.py --populate")

    # Handoff state
    print_subheader("Handoff State")
    state = read_handoff_state()
    if state:
        print(f"  📋 Pending calls: {len(state.pending)}")
        print(f"  ✅ Completed calls: {len(state.completed)}")
        age = time.time() - state.created_at
        print(f"  ⏱️  State age: {age:.1f}s")
    else:
        print("  📭 No active handoff state")

    # Execution log
    print_subheader("Execution Log")
    if EXECUTION_LOG.exists():
        try:
            lines = EXECUTION_LOG.read_text().strip().split("\n")
            print(f"  📝 Log entries: {len(lines)}")
            if lines:
                last = json.loads(lines[-1])
                print(f"  📊 Last execution: {'✅' if last.get('success') else '❌'}")
        except (json.JSONDecodeError, OSError):
            print("  ⚠️  Log exists but unreadable")
    else:
        print("  📭 No execution log yet")


def demo_cache() -> None:
    """Demonstrate ResultCache functionality."""
    print_header("ResultCache Demo")

    cache = ResultCache(
        ttl_seconds=DEMO_CACHE_TTL_SECONDS, max_entries=DEMO_CACHE_MAX_ENTRIES
    )

    print_subheader("1. Cache Miss (First Call)")
    hit, result = cache.get("mcp__serena__find_symbol", {"pattern": "Foo"})
    print(f"  Hit: {hit}, Result: {result}")
    print(f"  Stats: {cache.stats()}")

    print_subheader("2. Cache Set")
    mock_result = {"symbols": [{"name": "Foo", "type": "class"}]}
    cache.set("mcp__serena__find_symbol", {"pattern": "Foo"}, mock_result)
    print("  Stored result for 'find_symbol(pattern=Foo)'")
    print(f"  Stats: {cache.stats()}")

    print_subheader("3. Cache Hit (Repeated Call)")
    hit, result = cache.get("mcp__serena__find_symbol", {"pattern": "Foo"})
    print(f"  Hit: {hit}")
    print(f"  Result: {json.dumps(result, indent=4)}")
    print(f"  Stats: {cache.stats()}")

    print_subheader("4. Cache Miss (Different Args)")
    hit, result = cache.get("mcp__serena__find_symbol", {"pattern": "Bar"})
    print(f"  Hit: {hit} (different args)")
    print(f"  Stats: {cache.stats()}")

    print_subheader("5. LRU Eviction (max_entries=5)")
    for i in range(6):
        cache.set(f"tool_{i}", {"arg": i}, {"result": i})
    print("  Added 6 entries to cache with max 5")
    print(f"  Stats: {cache.stats()}")
    print("  Oldest entry evicted")


def demo_plan() -> None:
    """Demonstrate PlanExecutor with dependency resolution."""
    print_header("PlanExecutor Demo")

    # Create a mock invoker that simulates tool results
    call_log = []

    def mock_invoker(tool: str, args: dict) -> dict:
        call_log.append((tool, args))
        time.sleep(MOCK_LATENCY_SECONDS)  # Simulate latency
        return {"mock": True, "tool": tool, "args": args}

    print_subheader("1. Create Execution Plan with Dependencies")

    # Manually build plan with dependencies using ToolCallSpec
    calls = [
        ToolCallSpec(
            id="call-01",
            tool="mcp__serena__list_dir",
            args={"relative_path": ".", "recursive": False},
            description="List directory contents",
        ),
        ToolCallSpec(
            id="call-02",
            tool="mcp__serena__find_symbol",
            args={"name_path_pattern": "CodeMode*"},
            depends_on=["call-01"],  # Depends on list_dir
            description="Find CodeMode symbols",
        ),
        ToolCallSpec(
            id="call-03",
            tool="mcp__serena__get_symbols_overview",
            args={"relative_path": "lib/_codemode_executor.py"},
            depends_on=["call-01"],  # Also depends on list_dir
            description="Get executor overview",
        ),
        ToolCallSpec(
            id="call-04",
            tool="mcp__pal__chat",
            args={
                "prompt": "Analyze results",
                "model": "auto",
                "working_directory_absolute_path": "/tmp",
            },
            depends_on=["call-02", "call-03"],  # Depends on both
            description="Analyze with PAL",
        ),
    ]

    plan = ExecutionPlan(
        run_id=generate_run_id(),
        calls=calls,
        instructions="Execute tool calls respecting dependencies",
    )
    print(f"  Plan ID: {plan.run_id}")
    print(f"  Call count: {len(plan.calls)}")
    print("\n  Dependency graph:")
    for call in plan.calls:
        deps = call.depends_on if call.depends_on else ["(none)"]
        print(f"    {call.id}: {call.tool.split('__')[-1]} → depends on {deps}")

    print_subheader("2. Execute Plan (Sequential)")
    executor = PlanExecutor(tool_invoker=mock_invoker, parallel=False)
    result = executor.execute(plan)
    print(f"  Success: {result.success}")
    print(f"  Duration: {result.total_duration_ms:.1f}ms")
    print(f"  Execution order: {list(result.results.keys())}")

    print_subheader("3. Execute Plan (Parallel)")
    call_log.clear()
    planner2 = CodeModePlanner()
    # Independent calls (no dependencies) - use create_tool_plan
    plan2 = planner2.create_tool_plan(
        [
            ("mcp__crawl4ai__ddg_search", {"query": "Python async"}),
            ("mcp__crawl4ai__ddg_search", {"query": "MCP tools"}),
            ("mcp__crawl4ai__ddg_search", {"query": "code-mode LLM"}),
        ]
    )

    executor2 = PlanExecutor(tool_invoker=mock_invoker, parallel=True, max_workers=3)
    result2 = executor2.execute(plan2)
    print(f"  Success: {result2.success}")
    print(f"  Duration: {result2.total_duration_ms:.1f}ms (parallel)")
    print("  3 calls × 50ms each = ~50ms total (not 150ms)")

    print_subheader("4. Execute with Cache")
    cache = ResultCache(ttl_seconds=PARALLEL_CACHE_TTL_SECONDS)
    executor3 = PlanExecutor(tool_invoker=mock_invoker, cache=cache)

    # First execution (populate cache)
    _first_run = executor3.execute(plan2)
    print(f"  First run - cache stats: {cache.stats()}")

    # Second execution (should hit cache)
    result3b = executor3.execute(plan2)
    cached_count = sum(1 for r in result3b.results.values() if r.cached)
    print(f"  Second run - cached results: {cached_count}/{len(result3b.results)}")
    print(f"  Cache stats: {cache.stats()}")


def demo_handoff() -> None:
    """Demonstrate HandoffState protocol for Claude-mediated execution."""
    print_header("HandoffState Protocol Demo")

    # Clean start
    clear_handoff_state()

    print_subheader("1. Submit Tool Calls")
    submit_tool_call(
        ToolCallRequest(
            id="demo-01",
            tool="mcp__serena__find_symbol",
            args={"name_path_pattern": "ResultCache", "include_body": True},
            priority=0,
        )
    )
    submit_tool_call(
        ToolCallRequest(
            id="demo-02",
            tool="mcp__pal__chat",
            args={
                "prompt": "Review this code",
                "model": "kimi-k2",
                "working_directory_absolute_path": "/tmp",
            },
            priority=1,
        )
    )
    print("  Submitted 2 tool calls to handoff queue")

    print_subheader("2. Read Pending Calls")
    pending = get_pending_calls()
    print(f"  Pending calls: {len(pending)}")
    for call in pending:
        print(f"    [{call.priority}] {call.id}: {call.tool}")

    print_subheader("3. Simulate Claude Execution")
    # Claude would execute and record results
    record_tool_result(
        call_id="demo-01",
        success=True,
        result={"symbols": [{"name": "ResultCache", "type": "class", "line": 473}]},
    )
    print("  Recorded result for demo-01")

    record_tool_result(
        call_id="demo-02",
        success=True,
        result={"response": "Code looks good!"},
    )
    print("  Recorded result for demo-02")

    print_subheader("4. Check State")
    pending = get_pending_calls()
    print(f"  Pending calls: {len(pending)}")

    result1 = get_completed_result("demo-01")
    result2 = get_completed_result("demo-02")
    print(f"  demo-01 result: {result1.success if result1 else 'not found'}")
    print(f"  demo-02 result: {result2.success if result2 else 'not found'}")

    print_subheader("5. View Handoff File")
    state = read_handoff_state()
    if state:
        print(f"  File: {HANDOFF_STATE}")
        print(f"  Age: {time.time() - state.created_at:.1f}s")
        print(f"  Pending: {len(state.pending)}, Completed: {len(state.completed)}")

    # Cleanup
    clear_handoff_state()
    print("\n  Cleaned up handoff state")


def demo_hook() -> None:
    """Demonstrate hook integration for context injection."""
    print_header("Hook Integration Demo")

    # Clean start
    clear_handoff_state()

    print_subheader("1. Submit Pending Calls")
    submit_tool_call(
        ToolCallRequest(
            id="hook-test-01",
            tool="mcp__serena__find_symbol",
            args={"name_path_pattern": "check_codemode_handoff"},
            priority=0,
        )
    )
    submit_tool_call(
        ToolCallRequest(
            id="hook-test-02",
            tool="mcp__pal__debug",
            args={
                "step": "Investigate hook behavior",
                "step_number": 1,
                "total_steps": 2,
                "next_step_required": True,
                "findings": "Testing hook integration",
                "model": "kimi-k2",
            },
            priority=1,
        )
    )
    print("  Submitted 2 calls to trigger hook")

    print_subheader("2. Simulate Hook Execution")
    # Import and run the hook
    try:
        sys.path.insert(0, str(Path(__file__).parent.parent / "hooks"))
        from _prompt_codemode import check_codemode_handoff

        class MockState:
            pass

        result = check_codemode_handoff({"prompt": "test"}, MockState())
        print("  Hook executed successfully")
        print(
            f"  Context injected: {len(result.context) if result.context else 0} chars"
        )

        if result.context:
            print("\n  --- Injected Context Preview ---")
            preview = result.context[:CONTEXT_PREVIEW_CHARS]
            for line in preview.split("\n"):
                print(f"  {line}")
            if len(result.context) > CONTEXT_PREVIEW_CHARS:
                print("  ...")

    except ImportError as e:
        print(f"  ⚠️  Could not import hook: {e}")
        print("     This is expected if hook dependencies are missing")

    print_subheader("3. What Happens Next")
    print("""
  When this context is injected into Claude's prompt:

  1. Claude sees the pending tool calls
  2. Claude executes them using native tool-calling
  3. Claude records results via record_tool_result()
  4. Downstream code can read completed results

  This bridges Python-generated plans with Claude's execution.
""")

    # Cleanup
    clear_handoff_state()


def demo_all() -> None:
    """Run all demos."""
    demo_status()
    demo_cache()
    demo_plan()
    demo_handoff()
    demo_hook()

    print_header("Demo Complete")
    print("""
  Code-mode infrastructure provides:

  📋 Schema Cache     - Pre-cached MCP tool schemas for fast planning
  🔧 PlanExecutor     - Dependency-aware parallel execution
  💾 ResultCache      - TTL-based caching for repeated calls
  🤝 HandoffState     - Python-to-Claude execution bridge
  🪝 Hook Integration - Context injection for pending calls

  Next steps:
  - Populate schema cache: python ~/.claude/ops/schema_cache.py --populate
  - Wire into PAL mandates for multi-tool detection
  - Add PostToolUse hook for auto-recording results
""")


def main():
    parser = argparse.ArgumentParser(
        description="Demonstrate code-mode infrastructure",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--all", action="store_true", help="Run all demos")
    parser.add_argument("--cache", action="store_true", help="Demo ResultCache")
    parser.add_argument("--plan", action="store_true", help="Demo PlanExecutor")
    parser.add_argument("--handoff", action="store_true", help="Demo HandoffState")
    parser.add_argument("--hook", action="store_true", help="Demo hook integration")
    parser.add_argument("--status", action="store_true", help="Show system status")

    args = parser.parse_args()

    # Default to status if no args
    if not any([args.all, args.cache, args.plan, args.handoff, args.hook, args.status]):
        args.status = True

    if args.all:
        demo_all()
    else:
        if args.status:
            demo_status()
        if args.cache:
            demo_cache()
        if args.plan:
            demo_plan()
        if args.handoff:
            demo_handoff()
        if args.hook:
            demo_hook()


if __name__ == "__main__":
    main()
