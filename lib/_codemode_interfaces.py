#!/usr/bin/env python3
"""
Code-Mode Tool Interface Generator (v1.0)

Discovers MCP tool schemas and generates Python interfaces for code-mode execution.
Tools become callable as `namespace.tool_name(param1=value1, ...)`.

Philosophy: https://ghuntley.com/ralph/
- LLMs are better at writing code than orchestrating tool calls
- 67-88% efficiency improvement by reducing API round-trips
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

# Cache location for discovered schemas
SCHEMA_CACHE = Path.home() / ".claude" / "tmp" / "codemode_schemas.json"

CACHE_PROTOCOL_VERSION = "1.0"  # Increment when cache format changes

# Runtime tool executor - bound by codemode_executor at execution time
_tool_executor: Callable[[str, dict], dict] | None = None


def bind_executor(executor: Callable[[str, dict], dict]) -> None:
    """Bind the runtime tool executor function."""
    global _tool_executor
    _tool_executor = executor


@dataclass
class ToolParameter:
    """A parameter for an MCP tool."""

    name: str
    type: str
    description: str = ""
    required: bool = False
    default: Any = None


@dataclass
class ToolInterface:
    """Generated interface for an MCP tool."""

    namespace: str  # e.g., "serena", "pal", "crawl4ai"
    name: str  # e.g., "find_symbol", "crawl"
    full_name: str  # e.g., "mcp__serena__find_symbol"
    description: str
    parameters: list[ToolParameter] = field(default_factory=list)

    def signature(self) -> str:
        """Generate Python function signature."""
        params = []
        for p in sorted(self.parameters, key=lambda x: (not x.required, x.name)):
            if p.required:
                params.append(f"{p.name}: {p.type}")
            else:
                default = repr(p.default) if p.default is not None else "None"
                params.append(f"{p.name}: {p.type} = {default}")
        return f"def {self.name}({', '.join(params)}) -> dict"

    def docstring(self) -> str:
        """Generate docstring."""
        lines = [f'"""{self.description}']
        if self.parameters:
            lines.append("")
            lines.append("Args:")
            for p in self.parameters:
                req = " (required)" if p.required else ""
                lines.append(f"    {p.name}: {p.description}{req}")
        lines.append('"""')
        return "\n".join(lines)


def parse_mcp_tool_name(tool_name: str) -> tuple[str, str]:
    """
    Parse MCP tool name into namespace and function name.

    Examples:
        mcp__serena__find_symbol -> (serena, find_symbol)
        mcp__pal__debug -> (pal, debug)
        mcp__crawl4ai__crawl -> (crawl4ai, crawl)
        mcp__plugin_repomix-mcp_repomix__pack_codebase -> (repomix, pack_codebase)
    """
    if not tool_name.startswith("mcp__"):
        return ("custom", tool_name)

    # Remove mcp__ prefix
    rest = tool_name[5:]

    # Handle plugin format: plugin_<name>_<server>__<tool>
    if rest.startswith("plugin_"):
        # mcp__plugin_context7_context7__resolve-library-id
        # -> namespace: context7, name: resolve_library_id
        match = re.match(r"plugin_[\w-]+_([\w-]+)__(.+)", rest)
        if match:
            namespace = match.group(1).replace("-", "_")
            name = match.group(2).replace("-", "_")
            return (namespace, name)

    # Standard format: namespace__tool
    parts = rest.split("__", 1)
    if len(parts) == 2:
        namespace = parts[0].replace("-", "_")
        name = parts[1].replace("-", "_")
        return (namespace, name)

    return ("unknown", tool_name)


def json_type_to_python(json_type: str | list | None) -> str:
    """Convert JSON Schema type to Python type hint."""
    if json_type is None:
        return "Any"
    if isinstance(json_type, list):
        # Union type like ["string", "number"]
        types = [json_type_to_python(t) for t in json_type if t != "null"]
        if len(types) == 1:
            return f"{types[0]} | None"
        return f"{' | '.join(types)} | None"

    mapping = {
        "string": "str",
        "number": "float",
        "integer": "int",
        "boolean": "bool",
        "array": "list",
        "object": "dict",
        "null": "None",
    }
    return mapping.get(json_type, "Any")


def parse_json_schema(schema: dict) -> list[ToolParameter]:
    """Parse JSON Schema into ToolParameter list."""
    params = []
    properties = schema.get("properties", {})
    required = set(schema.get("required", []))

    for name, prop in properties.items():
        param = ToolParameter(
            name=name,
            type=json_type_to_python(prop.get("type")),
            description=prop.get("description", ""),
            required=name in required,
            default=prop.get("default"),
        )
        params.append(param)

    return params


def generate_interface(tool_name: str, tool_schema: dict) -> ToolInterface:
    """Generate a ToolInterface from MCP tool schema."""
    namespace, name = parse_mcp_tool_name(tool_name)

    # Extract description
    description = tool_schema.get("description", "")
    if isinstance(description, str):
        # Take first line/sentence for brevity
        description = description.split("\n")[0].strip()

    # Parse parameters from JSON schema
    params_schema = tool_schema.get("parameters", tool_schema.get("inputSchema", {}))
    parameters = parse_json_schema(params_schema)

    return ToolInterface(
        namespace=namespace,
        name=name,
        full_name=tool_name,
        description=description,
        parameters=parameters,
    )


def _call_tool(tool_name: str, params: dict) -> dict:
    """Execute MCP tool and return result."""
    # Remove 'cls' if present (from classmethod locals())
    params = {
        k: v for k, v in params.items() if k not in ("cls", "self") and v is not None
    }

    if _tool_executor is None:
        return {"error": "Tool executor not bound. Call bind_executor() first."}

    return _tool_executor(tool_name, params)


def generate_namespace_code(interfaces: list[ToolInterface]) -> str:
    """
    Generate Python code for a namespace of tools.

    Creates code like:
        class serena:
            @staticmethod
            def find_symbol(name_path_pattern: str, ...) -> dict:
                '''Find symbols matching pattern.'''
                return _call_tool("mcp__serena__find_symbol", locals())
    """
    # Group by namespace
    by_namespace: dict[str, list[ToolInterface]] = {}
    for iface in interfaces:
        by_namespace.setdefault(iface.namespace, []).append(iface)

    lines = [
        '"""Auto-generated MCP tool interfaces for code-mode execution."""',
        "",
        "from typing import Any",
        "from _codemode_interfaces import _call_tool",
        "",
    ]

    for namespace, tools in sorted(by_namespace.items()):
        lines.append("")
        lines.append(f"class {namespace}:")
        lines.append(f'    """MCP tools from {namespace} namespace."""')
        lines.append("")

        for tool in sorted(tools, key=lambda t: t.name):
            # Method signature
            params = ["cls"]
            for p in sorted(tool.parameters, key=lambda x: (not x.required, x.name)):
                if p.required:
                    params.append(f"{p.name}: {p.type}")
                else:
                    default = repr(p.default) if p.default is not None else "None"
                    params.append(f"{p.name}: {p.type} = {default}")

            lines.append("    @classmethod")
            lines.append(f"    def {tool.name}({', '.join(params)}) -> dict:")

            # Docstring (abbreviated)
            doc = (
                tool.description[:100] + "..."
                if len(tool.description) > 100
                else tool.description
            )
            lines.append(f'        """{doc}"""')

            # Body
            lines.append(f'        return _call_tool("{tool.full_name}", locals())')
            lines.append("")

    return "\n".join(lines)


def generate_interface_summary(interfaces: list[ToolInterface]) -> str:
    """
    Generate a compact summary of available tools for prompt injection.

    Format:
        ## Available Tools (code-mode)
        - serena.find_symbol(name_path_pattern, relative_path?, ...)
        - pal.debug(step, findings, model, ...)
    """
    by_namespace: dict[str, list[ToolInterface]] = {}
    for iface in interfaces:
        by_namespace.setdefault(iface.namespace, []).append(iface)

    lines = ["## Available Tools (code-mode)", ""]

    for namespace, tools in sorted(by_namespace.items()):
        for tool in sorted(tools, key=lambda t: t.name):
            # Compact signature
            req_params = [p.name for p in tool.parameters if p.required]
            opt_count = len([p for p in tool.parameters if not p.required])
            opt_suffix = f", +{opt_count} optional" if opt_count else ""
            params_str = ", ".join(req_params) + opt_suffix
            lines.append(f"- `{namespace}.{tool.name}({params_str})`")

    return "\n".join(lines)


def load_cached_schemas(ttl_seconds: int = 3600) -> dict[str, dict]:
    """
    Load cached tool schemas if available and not expired.

    Args:
        ttl_seconds: Cache TTL in seconds (default 1 hour)

    Returns:
        Dict of tool schemas, or empty dict if cache invalid/expired
    """
    if not SCHEMA_CACHE.exists():
        return {}

    try:
        data = json.loads(SCHEMA_CACHE.read_text())

        # Check metadata
        meta = data.get("_metadata", {})
        if not meta:
            # Old format without metadata - invalidate
            return {}

        # Check expiration
        expires_at = meta.get("expires_at", 0)
        if time.time() > expires_at:
            return {}

        # Check protocol version
        if meta.get("protocol_version") != CACHE_PROTOCOL_VERSION:
            return {}

        # Return schemas without metadata
        schemas = {k: v for k, v in data.items() if not k.startswith("_")}
        return schemas

    except (json.JSONDecodeError, OSError, KeyError):
        return {}


def save_schemas_cache(
    schemas: dict[str, dict],
    ttl_seconds: int = 3600,
    manifest_fingerprint: str = "",
) -> None:
    """
    Save tool schemas to cache with metadata and atomic write.

    Args:
        schemas: Dict of tool schemas to cache
        ttl_seconds: Cache TTL in seconds (default 1 hour)
        manifest_fingerprint: Hash of manifest for change detection (v1.1)
    """
    SCHEMA_CACHE.parent.mkdir(parents=True, exist_ok=True)

    # Build cache with metadata
    now = time.time()
    cache_data = {
        "_metadata": {
            "protocol_version": CACHE_PROTOCOL_VERSION,
            "created_at": now,
            "expires_at": now + ttl_seconds,
            "tool_count": len(schemas),
            "manifest_fingerprint": manifest_fingerprint,
        },
        **schemas,
    }

    # Atomic write: temp file then rename
    tmp_file = SCHEMA_CACHE.with_suffix(".tmp")
    try:
        tmp_file.write_text(json.dumps(cache_data, indent=2))
        tmp_file.rename(SCHEMA_CACHE)
    except OSError:
        # Clean up temp file on failure
        if tmp_file.exists():
            tmp_file.unlink()
        raise


# For direct testing
if __name__ == "__main__":
    # Example schema
    example_schema = {
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
                        "description": "Optional path restriction",
                    },
                    "include_body": {
                        "type": "boolean",
                        "description": "Include source code",
                        "default": False,
                    },
                },
                "required": ["name_path_pattern"],
            },
        },
        "mcp__pal__debug": {
            "description": "Systematic debugging with external LLM assistance.",
            "parameters": {
                "type": "object",
                "properties": {
                    "step": {"type": "string", "description": "Current debug step"},
                    "findings": {"type": "string", "description": "What you found"},
                    "model": {"type": "string", "description": "Model to use"},
                },
                "required": ["step", "findings", "model"],
            },
        },
    }

    interfaces = [
        generate_interface(name, schema) for name, schema in example_schema.items()
    ]

    print("=== Generated Code ===")
    print(generate_namespace_code(interfaces))
    print()
    print("=== Summary ===")
    print(generate_interface_summary(interfaces))
