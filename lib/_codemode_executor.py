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
