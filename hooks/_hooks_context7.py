"""
Context7 Integration - Smart library documentation lookup.

Context7 provides up-to-date library documentation with code examples.
This module detects when Context7 is the optimal research tool and
provides helpers for library name extraction.

Integration points:
- Stuck loop detection: Suggest Context7 FIRST for library-specific issues
- Research tracking: Count Context7 lookups as research (resets circuit breaker)
- PAL mandates: Suggest Context7 before generic web search for API questions

Priority: Context7 > PAL apilookup > WebSearch for library docs
"""

import re
from typing import NamedTuple

# =============================================================================
# CONTEXT7 MCP TOOL NAMES
# =============================================================================

CONTEXT7_TOOLS = {
    "mcp__plugin_context7_context7__resolve-library-id",
    "mcp__plugin_context7_context7__get-library-docs",
}

# =============================================================================
# LIBRARY DETECTION PATTERNS
# =============================================================================

# Common library name patterns in error messages and prompts
LIBRARY_MENTION_PATTERNS = [
    # Direct mentions: "react", "nextjs", "prisma"
    r"\b(react|vue|angular|svelte|solid)\b",
    r"\b(next\.?js|nuxt|gatsby|remix|astro)\b",
    r"\b(express|fastify|koa|hono|nest\.?js)\b",
    r"\b(prisma|drizzle|sequelize|typeorm|mongoose)\b",
    r"\b(tailwind|styled-components|emotion|chakra)\b",
    r"\b(redux|zustand|jotai|recoil|mobx|pinia)\b",
    r"\b(axios|fetch|ky|got|superagent)\b",
    r"\b(zod|yup|joi|valibot|typebox)\b",
    r"\b(vitest|jest|mocha|playwright|cypress)\b",
    r"\b(trpc|graphql|apollo|urql)\b",
    r"\b(supabase|firebase|appwrite|convex)\b",
    r"\b(stripe|clerk|auth\.?js|lucia)\b",
    r"\b(tanstack|react-query|swr)\b",
    r"\b(framer-motion|react-spring|gsap)\b",
    r"\b(radix|headless-?ui|shadcn|mantine)\b",
    # Python libraries
    r"\b(fastapi|flask|django|starlette)\b",
    r"\b(pydantic|sqlalchemy|alembic)\b",
    r"\b(pandas|numpy|scipy|matplotlib)\b",
    r"\b(pytorch|tensorflow|transformers|langchain)\b",
    r"\b(pytest|unittest|hypothesis)\b",
    r"\b(httpx|requests|aiohttp)\b",
    r"\b(celery|rq|dramatiq)\b",
    # Go libraries
    r"\b(gin|echo|fiber|chi)\b",
    r"\b(gorm|sqlx|ent)\b",
    # Rust libraries
    r"\b(tokio|actix|axum|rocket)\b",
    r"\b(serde|sqlx|diesel)\b",
]

# Import statement patterns for library extraction
IMPORT_PATTERNS = [
    # JavaScript/TypeScript
    r"import\s+.*?\s+from\s+['\"]([^'\"@][^'\"]*)['\"]",
    r"require\s*\(\s*['\"]([^'\"@][^'\"]*)['\"]",
    r"from\s+['\"]([^'\"@][^'\"]*)['\"]",
    # Python
    r"^import\s+(\w+)",
    r"^from\s+(\w+)",
    # Go
    r'import\s+"([^"]+)"',
    # Rust
    r"use\s+(\w+)::",
]

# Error patterns that indicate library-specific issues
LIBRARY_ERROR_PATTERNS = [
    # Module not found
    (r"cannot find module ['\"]([^'\"]+)['\"]", 1),
    (r"module not found[:\s]+['\"]?([^'\">\s]+)", 1),
    (r"no module named ['\"]?(\w+)", 1),
    # Type errors mentioning library types
    (r"type ['\"](\w+)['\"] is not", 1),
    (r"property ['\"](\w+)['\"].*does not exist on type", None),  # Not library name
    # Import errors
    (r"cannot resolve ['\"]([^'\"]+)['\"]", 1),
    (r"failed to resolve import ['\"]([^'\"]+)['\"]", 1),
]

# Package file patterns for library detection
PACKAGE_FILE_PATTERNS = {
    "package.json": r'"([^"]+)":\s*"[\^~]?\d',  # npm dependencies
    "requirements.txt": r"^([a-zA-Z0-9_-]+)",  # Python packages
    "Cargo.toml": r'(\w+)\s*=\s*"[\d.]+"',  # Rust crates
    "go.mod": r"require\s+([^\s]+)",  # Go modules
    "pyproject.toml": r'"([^"]+)"',  # Python pyproject
}


class LibraryContext(NamedTuple):
    """Detected library context for Context7 lookup."""

    library_name: str
    confidence: float  # 0.0 to 1.0
    source: str  # "error", "import", "mention", "package"
    original_text: str  # The text that triggered detection


def extract_library_from_error(error_text: str) -> LibraryContext | None:
    """Extract library name from error message."""
    error_lower = error_text.lower()

    for pattern, group in LIBRARY_ERROR_PATTERNS:
        match = re.search(pattern, error_lower)
        if match and group:
            lib_name = match.group(group)
            # Clean up the library name
            lib_name = lib_name.split("/")[0]  # Handle scoped packages
            lib_name = lib_name.split("@")[0]  # Remove version
            if len(lib_name) > 1 and not lib_name.startswith("."):
                return LibraryContext(
                    library_name=lib_name,
                    confidence=0.9,
                    source="error",
                    original_text=match.group(0),
                )
    return None


def extract_library_from_mention(text: str) -> LibraryContext | None:
    """Extract library name from direct mention in text."""
    text_lower = text.lower()

    for pattern in LIBRARY_MENTION_PATTERNS:
        match = re.search(pattern, text_lower, re.IGNORECASE)
        if match:
            lib_name = match.group(1)
            # Normalize common variations
            lib_name = lib_name.replace(".", "").replace("-", "")
            return LibraryContext(
                library_name=lib_name,
                confidence=0.8,
                source="mention",
                original_text=match.group(0),
            )
    return None


def extract_library_from_import(code: str) -> list[LibraryContext]:
    """Extract library names from import statements."""
    libraries = []

    for pattern in IMPORT_PATTERNS:
        for match in re.finditer(pattern, code, re.MULTILINE):
            lib_name = match.group(1)
            # Skip relative imports and builtins
            if lib_name.startswith(".") or lib_name in {
                "os",
                "sys",
                "re",
                "json",
                "typing",
            }:
                continue
            # Get package name (first part before /)
            lib_name = lib_name.split("/")[0]
            libraries.append(
                LibraryContext(
                    library_name=lib_name,
                    confidence=0.7,
                    source="import",
                    original_text=match.group(0),
                )
            )

    return libraries


def detect_library_context(
    prompt: str = "", error_output: str = "", code_content: str = ""
) -> LibraryContext | None:
    """
    Detect library context from various sources.

    Priority:
    1. Error messages (highest confidence - user is stuck on specific library)
    2. Direct mentions in prompt (user asking about specific library)
    3. Import statements (context for what libraries are in use)

    Returns the highest-confidence library context found.
    """
    contexts = []

    # Check error output first (highest priority)
    if error_output:
        ctx = extract_library_from_error(error_output)
        if ctx:
            contexts.append(ctx)

    # Check prompt for direct mentions
    if prompt:
        ctx = extract_library_from_mention(prompt)
        if ctx:
            contexts.append(ctx)

    # Check code for imports (lower priority)
    if code_content:
        import_contexts = extract_library_from_import(code_content)
        contexts.extend(import_contexts)

    # Return highest confidence
    if contexts:
        return max(contexts, key=lambda c: c.confidence)
    return None


def get_context7_suggestion(library_ctx: LibraryContext) -> str:
    """Generate a Context7 suggestion message for the detected library."""
    lib = library_ctx.library_name
    source = library_ctx.source

    if source == "error":
        return (
            f"📚 **Library Issue Detected**: `{lib}`\n"
            f"⚡ **Context7 recommended** (faster than web search for library docs):\n"
            f"   1. `mcp__plugin_context7_context7__resolve-library-id` with `{lib}`\n"
            f"   2. `mcp__plugin_context7_context7__get-library-docs` for API reference\n"
            f"💡 Context7 has {lib} docs with code snippets - check there first"
        )
    elif source == "mention":
        return (
            f"📚 **Library mentioned**: `{lib}`\n"
            f"💡 Use Context7 for up-to-date docs: resolve-library-id → get-library-docs"
        )
    else:
        return f"💡 Context7 available for `{lib}` documentation"


def format_context7_circuit_breaker_suggestion(
    library_ctx: LibraryContext | None,
) -> str:
    """Format Context7 as part of circuit breaker suggestions."""
    if library_ctx:
        lib = library_ctx.library_name
        return (
            f"   → `mcp__plugin_context7_context7__resolve-library-id` for `{lib}` docs (FASTEST)\n"
            f"   → `mcp__plugin_context7_context7__get-library-docs` for API reference\n"
        )
    else:
        return "   → `mcp__plugin_context7_context7__resolve-library-id` if library-related\n"


# =============================================================================
# RESEARCH TOOL CLASSIFICATION
# =============================================================================


def is_context7_tool(tool_name: str) -> bool:
    """Check if a tool is a Context7 tool."""
    return tool_name in CONTEXT7_TOOLS


def get_context7_research_credit() -> str:
    """Get the message for Context7 research credit."""
    return (
        "✅ **Context7 lookup performed** - Circuit breaker reset\n"
        "💡 Apply library documentation to your implementation"
    )
