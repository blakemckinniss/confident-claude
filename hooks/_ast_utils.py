"""
Cached AST utilities for hook pattern matching.

Provides AST-based extraction for patterns where regex is fragile.
Falls back gracefully on parse errors.
"""

import ast
from functools import lru_cache

# Standard library modules (Python 3.12) - skip these in dependency checks
STDLIB_MODULES = frozenset(
    {
        "abc",
        "aifc",
        "argparse",
        "array",
        "ast",
        "asyncio",
        "atexit",
        "base64",
        "bdb",
        "binascii",
        "bisect",
        "builtins",
        "bz2",
        "calendar",
        "cgi",
        "cgitb",
        "chunk",
        "cmath",
        "cmd",
        "code",
        "codecs",
        "codeop",
        "collections",
        "colorsys",
        "compileall",
        "concurrent",
        "configparser",
        "contextlib",
        "contextvars",
        "copy",
        "copyreg",
        "cProfile",
        "crypt",
        "csv",
        "ctypes",
        "curses",
        "dataclasses",
        "datetime",
        "dbm",
        "decimal",
        "difflib",
        "dis",
        "doctest",
        "email",
        "encodings",
        "enum",
        "errno",
        "faulthandler",
        "fcntl",
        "filecmp",
        "fileinput",
        "fnmatch",
        "fractions",
        "ftplib",
        "functools",
        "gc",
        "getopt",
        "getpass",
        "gettext",
        "glob",
        "graphlib",
        "grp",
        "gzip",
        "hashlib",
        "heapq",
        "hmac",
        "html",
        "http",
        "idlelib",
        "imaplib",
        "imghdr",
        "importlib",
        "inspect",
        "io",
        "ipaddress",
        "itertools",
        "json",
        "keyword",
        "lib2to3",
        "linecache",
        "locale",
        "logging",
        "lzma",
        "mailbox",
        "mailcap",
        "marshal",
        "math",
        "mimetypes",
        "mmap",
        "modulefinder",
        "multiprocessing",
        "netrc",
        "nis",
        "nntplib",
        "numbers",
        "operator",
        "optparse",
        "os",
        "pathlib",
        "pdb",
        "pickle",
        "pickletools",
        "pipes",
        "pkgutil",
        "platform",
        "plistlib",
        "poplib",
        "posix",
        "posixpath",
        "pprint",
        "profile",
        "pstats",
        "pty",
        "pwd",
        "py_compile",
        "pyclbr",
        "pydoc",
        "queue",
        "quopri",
        "random",
        "re",
        "readline",
        "reprlib",
        "resource",
        "rlcompleter",
        "runpy",
        "sched",
        "secrets",
        "select",
        "selectors",
        "shelve",
        "shlex",
        "shutil",
        "signal",
        "site",
        "smtpd",
        "smtplib",
        "sndhdr",
        "socket",
        "socketserver",
        "spwd",
        "sqlite3",
        "ssl",
        "stat",
        "statistics",
        "string",
        "stringprep",
        "struct",
        "subprocess",
        "sunau",
        "symtable",
        "sys",
        "sysconfig",
        "syslog",
        "tabnanny",
        "tarfile",
        "telnetlib",
        "tempfile",
        "termios",
        "test",
        "textwrap",
        "threading",
        "time",
        "timeit",
        "tkinter",
        "token",
        "tokenize",
        "tomllib",
        "trace",
        "traceback",
        "tracemalloc",
        "tty",
        "turtle",
        "turtledemo",
        "types",
        "typing",
        "unicodedata",
        "unittest",
        "urllib",
        "uu",
        "uuid",
        "venv",
        "warnings",
        "wave",
        "weakref",
        "webbrowser",
        "winreg",
        "winsound",
        "wsgiref",
        "xdrlib",
        "xml",
        "xmlrpc",
        "zipapp",
        "zipfile",
        "zipimport",
        "zlib",
        # typing extensions often bundled
        "typing_extensions",
    }
)


@lru_cache(maxsize=32)
def _parse_python(content: str) -> ast.Module | None:
    """Parse Python with caching. Returns None on syntax error."""
    try:
        return ast.parse(content)
    except SyntaxError:
        return None


def extract_imports(content: str) -> set[str]:
    """
    Extract all imported module names via AST.

    Returns top-level module names only (e.g., 'requests' not 'requests.auth').
    Falls back to empty set on parse error.

    Handles all import forms:
    - import foo
    - import foo, bar
    - import foo.bar.baz  -> 'foo'
    - from foo import bar
    - from foo.bar import baz  -> 'foo'
    - from . import foo  -> skipped (relative)
    """
    tree = _parse_python(content)
    if not tree:
        return set()

    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                # Get top-level module (before first dot)
                imports.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            # Skip relative imports (module is None or level > 0)
            if node.module and node.level == 0:
                imports.add(node.module.split(".")[0])

    return imports


def extract_non_stdlib_imports(content: str) -> set[str]:
    """Extract imports that are not in the standard library."""
    all_imports = extract_imports(content)
    return all_imports - STDLIB_MODULES


def extract_calls(content: str) -> tuple[set[str], set[str]]:
    """
    Extract function and method calls via AST.

    Returns (class_calls, method_calls):
    - class_calls: PascalCase names like MyClass(), Exception(), etc.
    - method_calls: Method/function names like .append(), print(), etc.

    More accurate than regex - ignores strings, comments, and variable names.
    """
    tree = _parse_python(content)
    if not tree:
        return set(), set()

    class_calls = set()
    method_calls = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                name = node.func.id
                # PascalCase heuristic: starts with uppercase
                if name[0].isupper():
                    class_calls.add(name)
                else:
                    method_calls.add(name)
            elif isinstance(node.func, ast.Attribute):
                # Method call like obj.method()
                method_calls.add(node.func.attr)

    return class_calls, method_calls


def extract_all_calls(content: str) -> set[str]:
    """Extract all function/method call names (combined set)."""
    class_calls, method_calls = extract_calls(content)
    return class_calls | method_calls


# Common builtins to filter from epistemic checks
BUILTIN_CALLS = frozenset(
    {
        "True",
        "False",
        "None",
        "Exception",
        "BaseException",
        "Error",
        "print",
        "len",
        "str",
        "int",
        "float",
        "bool",
        "list",
        "dict",
        "set",
        "tuple",
        "range",
        "enumerate",
        "zip",
        "map",
        "filter",
        "sorted",
        "reversed",
        "open",
        "input",
        "type",
        "isinstance",
        "issubclass",
        "hasattr",
        "getattr",
        "setattr",
        "sum",
        "min",
        "max",
        "abs",
        "round",
        "pow",
        "divmod",
        "any",
        "all",
        "iter",
        "next",
        "repr",
        "hash",
        "id",
        "hex",
        "bin",
        "oct",
        "ord",
        "chr",
        "format",
        "vars",
        "dir",
        "help",
        "callable",
        "eval",
        "exec",
        "compile",
        "globals",
        "locals",
        "super",
        "object",
        "classmethod",
        "staticmethod",
        "property",
        "slice",
        "complex",
        "bytes",
        "bytearray",
        "memoryview",
        "frozenset",
    }
)


def extract_non_builtin_calls(content: str) -> set[str]:
    """Extract calls that aren't Python builtins."""
    all_calls = extract_all_calls(content)
    return {c for c in all_calls if c not in BUILTIN_CALLS and len(c) > 2}


def clear_cache():
    """Clear the AST parse cache."""
    _parse_python.cache_clear()
