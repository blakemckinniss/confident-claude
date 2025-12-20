#!/usr/bin/env python3
"""
Code-Mode Executor (v1.0)

Executes Python code with access to MCP tools as namespaced functions.
Provides sandboxed execution environment for tool chaining.

Philosophy: https://ghuntley.com/ralph/
- LLMs are better at writing code than orchestrating tool calls
- 67-88% efficiency improvement by reducing API round-trips

Usage:
    from _codemode_executor import CodeModeExecutor

    executor = CodeModeExecutor(tool_schemas)
    result = executor.execute('''
        # Find all Python files and analyze them
        files = serena.find_file(file_mask="*.py", relative_path=".")
        for f in files.get("files", []):
            overview = serena.get_symbols_overview(relative_path=f)
            print(f"{f}: {len(overview.get('symbols', []))} symbols")
    ''')
"""

from __future__ import annotations

import json
import sys
import traceback
from dataclasses import dataclass, field
from io import StringIO
from pathlib import Path
from typing import Any, Callable

# Ensure lib directory is in path for sibling imports
_LIB_DIR = Path(__file__).parent
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

from _codemode_interfaces import (  # noqa: E402
    ToolInterface,
    bind_executor,
    generate_interface,
    generate_namespace_code,
)
from _codemode_planner import (  # noqa: E402
    ExecutionPlan,
    ToolCallSpec,
)

# Execution log location
EXECUTION_LOG = Path.home() / ".claude" / "tmp" / "codemode_execution.jsonl"


@dataclass
class ExecutionResult:
    """Result of code-mode execution."""

    success: bool
    output: str  # stdout/stderr captured
    return_value: Any = None
    tool_calls: list[dict] = field(default_factory=list)
    error: str | None = None
    execution_time_ms: float = 0.0


@dataclass
class ToolCall:
    """Record of a tool invocation."""

    tool_name: str
    params: dict
    result: dict
    success: bool
    error: str | None = None


class CodeModeExecutor:
    """
    Executes Python code with MCP tool access.

    Tools are available as namespaced class methods:
        serena.find_symbol(name_path_pattern="Foo")
        pal.debug(step="Investigating", findings="...", model="auto")
        crawl4ai.crawl(url="https://example.com")
    """

    def __init__(
        self,
        tool_schemas: dict[str, dict],
        tool_invoker: Callable[[str, dict], dict] | None = None,
        max_tool_calls: int = 50,
        timeout_seconds: float = 300.0,
    ):
        """
        Initialize executor with tool schemas.

        Args:
            tool_schemas: Dict mapping tool names to their JSON schemas
            tool_invoker: Function to actually invoke tools (for real execution)
            max_tool_calls: Maximum number of tool calls allowed
            timeout_seconds: Execution timeout
        """
        self.tool_schemas = tool_schemas
        self.tool_invoker = tool_invoker
        self.max_tool_calls = max_tool_calls
        self.timeout_seconds = timeout_seconds

        # Generate interfaces
        self.interfaces: list[ToolInterface] = []
        for name, schema in tool_schemas.items():
            self.interfaces.append(generate_interface(name, schema))

        # Track execution state
        self.tool_calls: list[ToolCall] = []
        self._call_count = 0

    def _invoke_tool(self, tool_name: str, params: dict) -> dict:
        """Internal tool invocation with tracking."""
        self._call_count += 1

        if self._call_count > self.max_tool_calls:
            error = f"Tool call limit exceeded ({self.max_tool_calls})"
            self.tool_calls.append(
                ToolCall(
                    tool_name=tool_name,
                    params=params,
                    result={},
                    success=False,
                    error=error,
                )
            )
            return {"error": error}

        # If no real invoker, return mock result
        if self.tool_invoker is None:
            result = {"_mock": True, "tool": tool_name, "params": params}
            self.tool_calls.append(
                ToolCall(
                    tool_name=tool_name,
                    params=params,
                    result=result,
                    success=True,
                )
            )
            return result

        # Real invocation
        try:
            result = self.tool_invoker(tool_name, params)
            self.tool_calls.append(
                ToolCall(
                    tool_name=tool_name,
                    params=params,
                    result=result,
                    success=True,
                )
            )
            return result
        except Exception as e:
            error = f"{type(e).__name__}: {e}"
            self.tool_calls.append(
                ToolCall(
                    tool_name=tool_name,
                    params=params,
                    result={},
                    success=False,
                    error=error,
                )
            )
            return {"error": error}

    def _build_execution_namespace(self) -> dict[str, Any]:
        """Build the namespace dict for code execution."""
        # Bind our invoker to the interface module
        bind_executor(self._invoke_tool)

        # Generate and compile namespace code
        code = generate_namespace_code(self.interfaces)

        # Create execution namespace with builtins
        namespace: dict[str, Any] = {
            "__builtins__": __builtins__,
            "_call_tool": self._invoke_tool,
            "json": json,
            "Path": Path,
        }

        # Execute the generated code to define classes
        exec(code, namespace)  # noqa: S102 - intentional for code-mode

        return namespace

    def execute(self, code: str) -> ExecutionResult:
        """
        Execute Python code with tool access.

        Args:
            code: Python code to execute

        Returns:
            ExecutionResult with output, tool calls, and any errors
        """
        import time

        start_time = time.time()
        self.tool_calls = []
        self._call_count = 0

        # Capture stdout/stderr
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        captured_output = StringIO()
        sys.stdout = captured_output
        sys.stderr = captured_output

        try:
            namespace = self._build_execution_namespace()

            # Execute the user's code
            exec(code, namespace)  # noqa: S102 - intentional for code-mode

            output = captured_output.getvalue()
            execution_time = (time.time() - start_time) * 1000

            result = ExecutionResult(
                success=True,
                output=output,
                tool_calls=[
                    {
                        "tool": tc.tool_name,
                        "params": tc.params,
                        "success": tc.success,
                        "error": tc.error,
                    }
                    for tc in self.tool_calls
                ],
                execution_time_ms=execution_time,
            )

            self._log_execution(code, result)
            return result

        except Exception as e:
            output = captured_output.getvalue()
            error_msg = f"{type(e).__name__}: {e}\n{traceback.format_exc()}"
            execution_time = (time.time() - start_time) * 1000

            result = ExecutionResult(
                success=False,
                output=output,
                error=error_msg,
                tool_calls=[
                    {
                        "tool": tc.tool_name,
                        "params": tc.params,
                        "success": tc.success,
                        "error": tc.error,
                    }
                    for tc in self.tool_calls
                ],
                execution_time_ms=execution_time,
            )

            self._log_execution(code, result)
            return result

        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr

    def _log_execution(self, code: str, result: ExecutionResult) -> None:
        """Log execution to JSONL file. Silently skips on I/O errors."""
        try:
            EXECUTION_LOG.parent.mkdir(parents=True, exist_ok=True)
            log_entry = {
                "code_preview": code[:200] + "..." if len(code) > 200 else code,
                "success": result.success,
                "tool_call_count": len(result.tool_calls),
                "execution_time_ms": result.execution_time_ms,
                "error": result.error,
            }
            with EXECUTION_LOG.open("a") as f:
                f.write(json.dumps(log_entry) + "\n")
        except OSError:
            return  # Logging failure is non-fatal

    def dry_run(self, code: str) -> dict[str, Any]:
        """
        Analyze code without executing.

        Returns info about what tools would be called.
        """
        import ast

        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            return {"valid": False, "error": f"Syntax error: {e}"}

        # Find all attribute calls that look like tool invocations
        tool_calls = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Attribute):
                    if isinstance(node.func.value, ast.Name):
                        namespace = node.func.value.id
                        method = node.func.attr
                        tool_calls.append(f"{namespace}.{method}")

        return {
            "valid": True,
            "estimated_tool_calls": tool_calls,
            "unique_tools": list(set(tool_calls)),
            "call_count": len(tool_calls),
        }


class ResultCache:
    """
    Cache for tool call results with TTL support.

    Reduces redundant MCP calls for repeated (tool, args) patterns.
    """

    # Default cache settings
    DEFAULT_TTL_SECONDS = 300  # 5 minutes
    DEFAULT_MAX_ENTRIES = 100
    HASH_PREFIX_LEN = 16

    def __init__(
        self,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
        max_entries: int = DEFAULT_MAX_ENTRIES,
    ):
        """
        Initialize result cache.

        Args:
            ttl_seconds: Time-to-live for cache entries (default 5 min).
            max_entries: Maximum cache entries before eviction.
        """
        self._cache: dict[str, tuple[Any, float]] = {}  # hash -> (result, expires_at)
        self._ttl = ttl_seconds
        self._max_entries = max_entries
        self._hits = 0
        self._misses = 0

    def _make_key(self, tool: str, args: dict) -> str:
        """Generate cache key from tool name and args."""
        import hashlib

        # Stable JSON serialization for consistent hashing
        args_str = json.dumps(args, sort_keys=True, default=str)
        content = f"{tool}:{args_str}"
        return hashlib.sha256(content.encode()).hexdigest()[: self.HASH_PREFIX_LEN]

    def get(self, tool: str, args: dict) -> tuple[bool, Any]:
        """
        Get cached result if available and not expired.

        Returns:
            (hit, result) - hit is True if cache hit, result is cached value
        """
        import time

        key = self._make_key(tool, args)
        if key in self._cache:
            result, expires_at = self._cache[key]
            if time.time() < expires_at:
                self._hits += 1
                return (True, result)
            # Expired - remove
            del self._cache[key]

        self._misses += 1
        return (False, None)

    def set(self, tool: str, args: dict, result: Any) -> None:
        """Cache a result."""
        import time

        # Evict oldest if at capacity
        if len(self._cache) >= self._max_entries:
            oldest_key = min(self._cache, key=lambda k: self._cache[k][1])
            del self._cache[oldest_key]

        key = self._make_key(tool, args)
        self._cache[key] = (result, time.time() + self._ttl)

    def stats(self) -> dict:
        """Return cache statistics."""
        total = self._hits + self._misses
        return {
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": self._hits / total if total > 0 else 0.0,
            "entries": len(self._cache),
        }

    def clear(self) -> None:
        """Clear all cached entries."""
        self._cache.clear()


@dataclass
class PlanResult:
    """Result from a single tool call in a plan."""

    call_id: str
    tool: str
    success: bool
    result: Any = None
    error: str | None = None
    duration_ms: float = 0.0
    cached: bool = False  # Whether result came from cache

    def to_dict(self) -> dict:
        return {
            "call_id": self.call_id,
            "tool": self.tool,
            "success": self.success,
            "result": self.result,
            "error": self.error,
            "duration_ms": self.duration_ms,
            "cached": self.cached,
        }


@dataclass
class PlanExecutionResult:
    """Aggregated results from plan execution."""

    run_id: str
    success: bool
    results: dict[str, PlanResult] = field(default_factory=dict)
    failed_calls: list[str] = field(default_factory=list)
    total_duration_ms: float = 0.0

    def to_dict(self) -> dict:
        return {
            "codemode_results": {
                call_id: r.to_dict() for call_id, r in self.results.items()
            },
            "run_id": self.run_id,
            "success": self.success,
            "failed_calls": self.failed_calls,
            "total_duration_ms": self.total_duration_ms,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)


class PlanExecutor:
    """
    Executes structured ExecutionPlan objects.

    Unlike CodeModeExecutor (which runs Python code), PlanExecutor
    directly executes ToolCallSpec objects with dependency resolution.

    Usage:
        plan = planner.create_tool_plan([...])
        executor = PlanExecutor(tool_invoker=my_invoker)
        result = executor.execute(plan)
    """

    def __init__(
        self,
        tool_invoker: Callable[[str, dict], dict] | None = None,
        log_executions: bool = True,
        parallel: bool = True,
        max_workers: int = 4,
        cache: ResultCache | None = None,
    ):
        """
        Initialize plan executor.

        Args:
            tool_invoker: Function to invoke MCP tools.
                         Signature: (tool_name: str, args: dict) -> dict
                         If None, runs in dry-run mode.
            log_executions: Whether to log executions to JSONL.
            parallel: Execute independent calls concurrently.
            max_workers: Max concurrent executions (default 4).
            cache: Optional ResultCache for caching repeated tool calls.
        """
        self._invoker = tool_invoker
        self._log_executions = log_executions
        self._parallel = parallel
        self._max_workers = max_workers
        self._cache = cache

    def execute(self, plan: ExecutionPlan) -> PlanExecutionResult:
        """
        Execute all tool calls in a plan.

        Respects dependency ordering - calls with depends_on wait for
        their dependencies to complete first. Independent calls run
        in parallel when parallel=True.

        Args:
            plan: The ExecutionPlan to execute

        Returns:
            PlanExecutionResult with all tool results
        """
        import time
        from concurrent.futures import ThreadPoolExecutor, as_completed

        start_time = time.time()
        results: dict[str, PlanResult] = {}
        failed: list[str] = []

        # Build dependency tracking
        pending = {call.id: call for call in plan.calls}
        completed_ids: set[str] = set()

        # Execute in dependency order
        while pending:
            # Find calls whose dependencies are satisfied
            ready = [
                call
                for call in pending.values()
                if all(dep in completed_ids for dep in call.depends_on)
            ]

            if not ready:
                # Circular or missing dependency - fail remaining
                for call_id, call in pending.items():
                    results[call_id] = PlanResult(
                        call_id=call_id,
                        tool=call.tool,
                        success=False,
                        error=f"Unresolved dependencies: {call.depends_on}",
                    )
                    failed.append(call_id)
                break

            # Execute ready calls (parallel if enabled and multiple ready)
            if self._parallel and len(ready) > 1:
                # Parallel execution for independent calls
                with ThreadPoolExecutor(max_workers=self._max_workers) as pool:
                    future_to_call = {
                        pool.submit(self._execute_call, call): call for call in ready
                    }
                    for future in as_completed(future_to_call):
                        call = future_to_call[future]
                        result = future.result()
                        results[call.id] = result

                        if result.success:
                            completed_ids.add(call.id)
                        else:
                            failed.append(call.id)

                        del pending[call.id]
            else:
                # Sequential execution
                for call in ready:
                    result = self._execute_call(call)
                    results[call.id] = result

                    if result.success:
                        completed_ids.add(call.id)
                    else:
                        failed.append(call.id)

                    del pending[call.id]

        total_ms = (time.time() - start_time) * 1000

        exec_result = PlanExecutionResult(
            run_id=plan.run_id,
            success=len(failed) == 0,
            results=results,
            failed_calls=failed,
            total_duration_ms=total_ms,
        )

        if self._log_executions:
            self._log_plan_execution(plan, exec_result)

        return exec_result

    def _execute_call(self, call: ToolCallSpec) -> PlanResult:
        """Execute a single tool call, with optional caching."""
        import time

        # Check cache first
        if self._cache is not None:
            hit, cached_result = self._cache.get(call.tool, call.args)
            if hit:
                return PlanResult(
                    call_id=call.id,
                    tool=call.tool,
                    success=True,
                    result=cached_result,
                    duration_ms=0.0,
                    cached=True,
                )

        start = time.time()

        if self._invoker is None:
            # Dry-run mode
            return PlanResult(
                call_id=call.id,
                tool=call.tool,
                success=True,
                result={"dry_run": True, "args": call.args},
                duration_ms=0.0,
            )

        try:
            result = self._invoker(call.tool, call.args)
            duration = (time.time() - start) * 1000

            # Check for error in result dict
            if isinstance(result, dict) and "error" in result:
                return PlanResult(
                    call_id=call.id,
                    tool=call.tool,
                    success=False,
                    error=str(result["error"]),
                    duration_ms=duration,
                )

            # Cache successful result
            if self._cache is not None:
                self._cache.set(call.tool, call.args, result)

            return PlanResult(
                call_id=call.id,
                tool=call.tool,
                success=True,
                result=result,
                duration_ms=duration,
            )

        except Exception as e:
            duration = (time.time() - start) * 1000
            return PlanResult(
                call_id=call.id,
                tool=call.tool,
                success=False,
                error=f"{type(e).__name__}: {e}",
                duration_ms=duration,
            )

    def _log_plan_execution(
        self, plan: ExecutionPlan, result: PlanExecutionResult
    ) -> None:
        """Log plan execution to JSONL file."""
        try:
            EXECUTION_LOG.parent.mkdir(parents=True, exist_ok=True)
            log_entry = {
                "type": "plan_execution",
                "run_id": plan.run_id,
                "call_count": len(plan.calls),
                "success": result.success,
                "failed_count": len(result.failed_calls),
                "total_ms": result.total_duration_ms,
            }
            with EXECUTION_LOG.open("a") as f:
                f.write(json.dumps(log_entry) + "\n")
        except OSError:
            return  # Logging failure is non-fatal

    def execute_single(self, tool: str, args: dict) -> PlanResult:
        """
        Execute a single tool call directly (no plan).

        Convenience method for one-off calls.
        """
        call = ToolCallSpec(id="single-01", tool=tool, args=args)
        return self._execute_call(call)


def execute_plan(
    plan: ExecutionPlan,
    tool_invoker: Callable[[str, dict], dict] | None = None,
) -> PlanExecutionResult:
    """
    Convenience function to execute a plan.

    Args:
        plan: The ExecutionPlan to execute
        tool_invoker: Optional tool invoker. If None, runs dry-run.

    Returns:
        PlanExecutionResult with all outcomes
    """
    executor = PlanExecutor(tool_invoker=tool_invoker)
    return executor.execute(plan)


def create_executor_from_mcp_list(mcp_tools: list[dict]) -> CodeModeExecutor:
    """
    Create executor from MCP tool list (as returned by ListTools).

    Args:
        mcp_tools: List of tool dicts with 'name', 'description', 'inputSchema'

    Returns:
        Configured CodeModeExecutor
    """
    schemas = {}
    for tool in mcp_tools:
        name = tool.get("name", "")
        if name.startswith("mcp__"):
            schemas[name] = {
                "description": tool.get("description", ""),
                "parameters": tool.get("inputSchema", {}),
            }
    return CodeModeExecutor(schemas)


# For direct testing
if __name__ == "__main__":
    # Example with mock tools
    example_schemas = {
        "mcp__serena__find_symbol": {
            "description": "Find symbols matching pattern.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name_path_pattern": {"type": "string"},
                    "include_body": {"type": "boolean", "default": False},
                },
                "required": ["name_path_pattern"],
            },
        },
        "mcp__serena__get_symbols_overview": {
            "description": "Get overview of symbols in a file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "relative_path": {"type": "string"},
                },
                "required": ["relative_path"],
            },
        },
    }

    executor = CodeModeExecutor(example_schemas)

    # Dry run
    test_code = """
result = serena.find_symbol(name_path_pattern="Foo")
print(f"Found: {result}")
overview = serena.get_symbols_overview(relative_path="test.py")
"""

    print("=== Dry Run ===")
    analysis = executor.dry_run(test_code)
    print(json.dumps(analysis, indent=2))

    print("\n=== Execute (mock) ===")
    result = executor.execute(test_code)
    print(f"Success: {result.success}")
    print(f"Output: {result.output}")
    print(f"Tool calls: {len(result.tool_calls)}")
    print(f"Execution time: {result.execution_time_ms:.1f}ms")
