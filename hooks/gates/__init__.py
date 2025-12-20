#!/usr/bin/env python3
"""
Gates Package - Modular PreToolUse hook gates.

This package breaks down pre_tool_use_runner.py into category-based modules.
Each module registers its hooks into the shared HOOKS list on import.

Modules:
  _serena.py     - Serena activation and code tool gates
  _content.py    - Content quality gates (dangerous patterns, stubs, docs, etc.)
  _confidence.py - Confidence system gates (Entity Model self-regulation)
  _bash.py       - Bash command validation and guidance gates
  _pal.py        - PAL mandate enforcement gates
  _beads.py      - Beads/parallel execution gates
  _meta.py       - Meta/recovery gates (self-heal, caching, thinking coach)
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
from ._confidence import (
    check_homeostatic_drive,
    check_threat_anticipation,
    check_confidence_tool_gate,
    check_oracle_gate,
    check_confidence_external_suggestion,
    check_integration_gate,
    check_error_suppression,
)
from ._bash import (
    check_loop_detector,
    check_python_path_enforcer,
    check_script_nudge,
    check_inline_server_background,
    check_background_enforcer,
    check_probe_gate,
    check_commit_gate,
    check_tool_preference,
    check_hf_cli_redirect,
)
from ._pal import (
    check_pal_mandate_enforcer,
    track_pal_tool_usage,
    check_pal_mandate_lock,
    clear_pal_mandate_lock,
)
from ._beads import (
    check_parallel_nudge,
    check_beads_parallel,
    check_bead_enforcement,
    check_parallel_bead_delegation,
    check_recursion_guard,
)
from ._meta import (
    check_fp_fix_enforcer,
    check_self_heal_enforcer,
    check_read_cache,
    check_exploration_cache,
    check_sunk_cost,
    check_thinking_coach,
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
    # Confidence gates
    "check_homeostatic_drive",
    "check_threat_anticipation",
    "check_confidence_tool_gate",
    "check_oracle_gate",
    "check_confidence_external_suggestion",
    "check_integration_gate",
    "check_error_suppression",
    # Bash gates
    "check_loop_detector",
    "check_python_path_enforcer",
    "check_script_nudge",
    "check_inline_server_background",
    "check_background_enforcer",
    "check_probe_gate",
    "check_commit_gate",
    "check_tool_preference",
    "check_hf_cli_redirect",
    # PAL mandate gates
    "check_pal_mandate_enforcer",
    "track_pal_tool_usage",
    "check_pal_mandate_lock",
    "clear_pal_mandate_lock",
    # Beads/parallel gates
    "check_parallel_nudge",
    "check_beads_parallel",
    "check_bead_enforcement",
    "check_parallel_bead_delegation",
    "check_recursion_guard",
    # Meta/recovery gates
    "check_fp_fix_enforcer",
    "check_self_heal_enforcer",
    "check_read_cache",
    "check_exploration_cache",
    "check_sunk_cost",
    "check_thinking_coach",
]
