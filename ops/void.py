#!/usr/bin/env python3
"""
The Void Hunter: Scans code for missing functionality, stubs, and logical gaps.

Uses AST-aware detection to avoid false positives from pattern definitions.
"""

import ast
import sys
import os
import re
import requests

# Add .claude/lib to path
_script_path = os.path.abspath(__file__)
_script_dir = os.path.dirname(_script_path)
# Find project root by looking for '.claude' directory
_current = _script_dir
while _current != "/":
    if os.path.exists(os.path.join(_current, ".claude", "lib", "core.py")):
        _project_root = _current
        break
    _current = os.path.dirname(_current)
else:
    raise RuntimeError("Could not find project root with .claude/lib/core.py")
sys.path.insert(0, os.path.join(_project_root, ".claude", "lib"))
from core import setup_script, finalize, logger, handle_debug  # noqa: E402


def _is_inside_string_literal(line: str, pattern: str) -> bool:
    """Check if pattern appears inside a string literal (crude heuristic)."""
    # Find where the pattern matches
    match = re.search(pattern, line, re.IGNORECASE)
    if not match:
        return False

    pos = match.start()

    # Check if there's an opening quote before the pattern
    # that suggests it's inside a string
    before = line[:pos]

    # Count unescaped quotes - odd count means we're inside a string
    # This is a heuristic, not perfect
    single_quotes = len(re.findall(r"(?<!\\)'", before))
    double_quotes = len(re.findall(r'(?<!\\)"', before))

    # Also check for byte string prefixes
    if re.search(r'[bBrRfF]?["\'][^"\']*$', before):
        return True

    # Check for common patterns that indicate string definitions
    string_def_patterns = [
        r'=\s*["\[]',  # Assignment to string or list
        r'["\'],\s*$',  # Trailing comma after string
        r'\(["\']',  # Function call with string arg
        r':\s*["\']',  # Dict value
    ]
    for pat in string_def_patterns:
        if re.search(pat, before):
            return True

    return (single_quotes % 2 == 1) or (double_quotes % 2 == 1)


def hunt_stubs_ast(file_path: str) -> list[dict]:
    """Use AST to find real stub patterns (not string literals)."""
    stubs = []

    try:
        with open(file_path, "r") as f:
            source = f.read()
            lines = source.splitlines()

        tree = ast.parse(source, filename=file_path)
    except SyntaxError:
        # Fall back to regex for non-parseable files
        return hunt_stubs_regex(file_path)
    except Exception as e:
        logger.error(f"Failed to parse {file_path}: {e}")
        return []

    for node in ast.walk(tree):
        # Find raise NotImplementedError
        if isinstance(node, ast.Raise):
            if node.exc:
                exc = node.exc
                # raise NotImplementedError or raise NotImplementedError(...)
                if isinstance(exc, ast.Name) and exc.id == "NotImplementedError":
                    stubs.append(
                        {
                            "line": node.lineno,
                            "type": "NotImplementedError",
                            "content": lines[node.lineno - 1].strip()
                            if node.lineno <= len(lines)
                            else "",
                        }
                    )
                elif isinstance(exc, ast.Call):
                    if (
                        isinstance(exc.func, ast.Name)
                        and exc.func.id == "NotImplementedError"
                    ):
                        stubs.append(
                            {
                                "line": node.lineno,
                                "type": "NotImplementedError",
                                "content": lines[node.lineno - 1].strip()
                                if node.lineno <= len(lines)
                                else "",
                            }
                        )

        # Find function stubs: def foo(): pass or def foo(): ...
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if len(node.body) == 1:
                body = node.body[0]
                # pass statement
                if isinstance(body, ast.Pass):
                    stubs.append(
                        {
                            "line": node.lineno,
                            "type": "Function stub (pass)",
                            "content": lines[node.lineno - 1].strip()
                            if node.lineno <= len(lines)
                            else "",
                        }
                    )
                # Ellipsis (...)
                elif isinstance(body, ast.Expr) and isinstance(
                    body.value, ast.Constant
                ):
                    if body.value.value is ...:
                        stubs.append(
                            {
                                "line": node.lineno,
                                "type": "Function stub (...)",
                                "content": lines[node.lineno - 1].strip()
                                if node.lineno <= len(lines)
                                else "",
                            }
                        )

    # Also check for TODO/FIXME comments (not in AST, use regex with heuristics)
    for line_num, line in enumerate(lines, 1):
        # Skip if line looks like it's defining patterns
        if "PATTERN" in line.upper() or "STUB_" in line.upper():
            continue

        for pattern, desc in [
            (r"#\s*TODO(?:\s|:|$)", "TODO comment"),
            (r"#\s*FIXME(?:\s|:|$)", "FIXME comment"),
        ]:
            if re.search(pattern, line, re.IGNORECASE):
                # Make sure it's a real comment, not inside a string
                if not _is_inside_string_literal(line, pattern):
                    # Extra check: the # must not be inside quotes
                    hash_pos = line.find("#")
                    if hash_pos >= 0:
                        before_hash = line[:hash_pos]
                        # Simple check: balanced quotes before #
                        if (
                            before_hash.count('"') % 2 == 0
                            and before_hash.count("'") % 2 == 0
                        ):
                            stubs.append(
                                {
                                    "line": line_num,
                                    "type": desc,
                                    "content": line.strip(),
                                }
                            )
                            break  # Only report once per line

    return stubs


def hunt_stubs_regex(file_path: str) -> list[dict]:
    """Fallback regex-based stub detection for non-Python files."""
    stubs_found = []
    patterns = [
        (r"#\s*TODO(?:\s|:|$)", "TODO comment"),
        (r"#\s*FIXME(?:\s|:|$)", "FIXME comment"),
        (r"def\s+\w+\([^)]*\):\s*pass\s*$", "Function stub (pass)"),
        (r"def\s+\w+\([^)]*\):\s*\.\.\.\s*$", "Function stub (...)"),
        (r"^\s*raise\s+NotImplementedError", "NotImplementedError"),
    ]

    try:
        with open(file_path, "r") as f:
            for line_num, line in enumerate(f, 1):
                for pattern, description in patterns:
                    if re.search(pattern, line, re.IGNORECASE):
                        # Skip obvious string definitions
                        if _is_inside_string_literal(line, pattern):
                            continue
                        stubs_found.append(
                            {
                                "line": line_num,
                                "type": description,
                                "content": line.strip(),
                            }
                        )
                        break  # Only one match per line
    except Exception as e:
        logger.error(f"Failed to scan {file_path}: {e}")
        return []

    return stubs_found


def hunt_stubs(file_path: str) -> list[dict]:
    """Scan a file for stub patterns using AST-aware detection."""
    if file_path.endswith(".py"):
        return hunt_stubs_ast(file_path)
    else:
        return hunt_stubs_regex(file_path)


def analyze_gaps_via_oracle(file_path, model):
    """Analyze code for logical gaps using The Oracle."""
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        logger.error("Missing OPENROUTER_API_KEY environment variable")
        return None

    # Read the file content
    try:
        with open(file_path, "r") as f:
            code_content = f.read()
    except Exception as e:
        logger.error(f"Failed to read {file_path}: {e}")
        return None

    system_prompt = """You are The Void Hunter. You analyze code for what is MISSING, not what exists.

The user will provide code. Your job is to find:

1. **CRUD Asymmetry:** If there's a Create, is there a Delete? If there's a Read, is there a Write?
2. **Error Handling Gaps:** Are there operations that can fail but have no try/except? Are exceptions caught but ignored?
3. **Config Hardcoding:** Are there magic numbers, hardcoded paths, or constants that should be env vars?
4. **Missing User Feedback:** Do operations succeed/fail silently? Are there no logs, no return values, no status indicators?

Output format:
## 🕳️ GAPS DETECTED

### CRUD Asymmetry
[List operations that exist without their complement]

### Error Handling Gaps
[List operations that can fail but have no error handling]

### Config Hardcoding
[List hardcoded values that should be configurable]

### Missing Feedback
[List operations that provide no feedback on success/failure]

If no gaps found, say "✅ NO GAPS DETECTED"

Be thorough. Be pedantic. The goal is to find what SHOULD be there but ISN'T."""

    logger.info("Consulting The Oracle for gap analysis...")

    try:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/claude-code/whitebox",
        }

        data = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": f"Analyze this code for gaps:\n\n```python\n{code_content}\n```",
                },
            ],
            "extra_body": {"reasoning": {"enabled": True}},
        }

        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers=headers,
            json=data,
            timeout=120,
        )
        response.raise_for_status()
        result = response.json()

        content = result["choices"][0]["message"].get("content", "")
        return content

    except requests.exceptions.RequestException as e:
        logger.error(f"Oracle communication failed: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        return None


def collect_python_files(target: str) -> list[str]:
    """Collect Python files from target (file or directory)."""
    from pathlib import Path

    target_path = Path(target)

    if target_path.is_file():
        if target_path.suffix == ".py":
            return [str(target_path)]
        else:
            return []
    elif target_path.is_dir():
        return [str(f) for f in target_path.rglob("*.py") if f.is_file()]
    else:
        return []


def main():
    parser = setup_script(
        "The Void Hunter: Scans code for missing functionality, stubs, and logical gaps."
    )

    # Custom arguments
    parser.add_argument("target", help="Python file or directory to scan for gaps")
    parser.add_argument(
        "--model",
        default="google/gemini-3-pro-preview",
        help="OpenRouter model for gap analysis (default: gemini-3-pro-preview)",
    )
    parser.add_argument(
        "--stub-only",
        action="store_true",
        help="Only hunt for stubs, skip Oracle analysis",
    )

    args = parser.parse_args()
    handle_debug(args)

    if not os.path.exists(args.target):
        logger.error(f"Target not found: {args.target}")
        finalize(success=False)

    # Collect Python files
    py_files = collect_python_files(args.target)

    if not py_files:
        logger.error(f"No Python files found in: {args.target}")
        finalize(success=False)

    logger.info(f"Scanning {len(py_files)} Python file(s) for voids...")

    total_stubs = 0
    files_with_stubs = []

    try:
        # Phase 1: Stub Hunting (all files)
        logger.info("🔍 Phase 1: Stub Hunting")

        for py_file in py_files:
            stubs = hunt_stubs(py_file)
            if stubs:
                total_stubs += len(stubs)
                files_with_stubs.append((py_file, stubs))

        if files_with_stubs:
            print("\n" + "=" * 70)
            print("🚨 STUBS DETECTED")
            print("=" * 70)
            for file_path, stubs in files_with_stubs:
                rel_path = (
                    os.path.relpath(file_path, args.target)
                    if os.path.isdir(args.target)
                    else os.path.basename(file_path)
                )
                print(f"\n📄 {rel_path}")
                for stub in stubs:
                    print(f"  Line {stub['line']}: {stub['type']}")
                    print(f"    → {stub['content']}")
            print("\n" + "=" * 70)
            print(f"Total: {total_stubs} stub(s) in {len(files_with_stubs)} file(s)")
            print("=" * 70 + "\n")
        else:
            logger.info("✅ No stubs detected")

        # Phase 2: Logical Gap Analysis (single file only, unless --stub-only)
        if not args.stub_only and len(py_files) == 1:
            logger.info("🔍 Phase 2: Logical Gap Analysis")
            gap_analysis = analyze_gaps_via_oracle(py_files[0], args.model)

            if gap_analysis:
                print("\n" + "=" * 70)
                print("🕳️ ORACLE GAP ANALYSIS")
                print("=" * 70)
                print(gap_analysis)
                print("=" * 70 + "\n")
            else:
                logger.warning("⚠️  Oracle analysis failed")
        elif not args.stub_only and len(py_files) > 1:
            logger.info(
                "ℹ️  Skipping Oracle analysis for multi-file scan (use single file for deep analysis)"
            )

        # Summary
        if total_stubs > 0:
            logger.warning(
                f"⚠️  Completeness check FAILED: {total_stubs} stub(s) in {len(files_with_stubs)} file(s)"
            )
            finalize(success=False)
        else:
            logger.info(f"✅ Completeness check PASSED ({len(py_files)} files scanned)")

    except Exception as e:
        logger.error(f"Operation failed: {e}")
        finalize(success=False)

    finalize(success=True)


if __name__ == "__main__":
    main()
