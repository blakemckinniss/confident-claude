#!/usr/bin/env python3
"""
Gates Package - Modular PreToolUse hook gates.

This package breaks down pre_tool_use_runner.py into category-based modules.
Each module registers its hooks into the shared HOOKS list on import.

Modules:
  _serena.py  - Serena activation and code tool gates
  _content.py - Content quality gates (dangerous patterns, stubs, docs, etc.)
"""

from ._common import HOOKS, register_hook, HookResult
from ._serena import (
    check_serena_activation_gate,
    check_code_tools_require_serena,
)
from ._content import (
    check_content_gate,
    suggest_crawl4ai,
    check_god_component_gate,
    check_gap_detector,
    check_production_gate,
    check_deferral_gate,
    check_doc_theater_gate,
    check_root_pollution_gate,
    check_recommendation_gate,
    check_security_claim_gate,
    check_epistemic_boundary,
    check_research_gate,
    check_import_gate,
    check_modularization,
    inject_curiosity_prompt,
)

__all__ = [
    "HOOKS",
    "register_hook",
    "HookResult",
    # Serena gates
    "check_serena_activation_gate",
    "check_code_tools_require_serena",
    # Content gates
    "check_content_gate",
    "suggest_crawl4ai",
    "check_god_component_gate",
    "check_gap_detector",
    "check_production_gate",
    "check_deferral_gate",
    "check_doc_theater_gate",
    "check_root_pollution_gate",
    "check_recommendation_gate",
    "check_security_claim_gate",
    "check_epistemic_boundary",
    "check_research_gate",
    "check_import_gate",
    "check_modularization",
    "inject_curiosity_prompt",
]
