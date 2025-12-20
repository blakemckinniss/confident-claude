#!/usr/bin/env python3
"""
Gates Package - Modular PreToolUse hook gates.

This package breaks down pre_tool_use_runner.py into category-based modules.
Each module registers its hooks into the shared HOOKS list on import.

Modules:
  _serena.py  - Serena activation and code tool gates
  (more to come...)
"""

from ._common import HOOKS, register_hook, HookResult
from ._serena import (
    check_serena_activation_gate,
    check_code_tools_require_serena,
)

__all__ = [
    "HOOKS",
    "register_hook",
    "HookResult",
    "check_serena_activation_gate",
    "check_code_tools_require_serena",
]
