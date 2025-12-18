"""Mastermind: Multi-model orchestration for Claude Code.

Architecture:
- Groq/K2 router classifies task complexity at session start
- GPT-5.2 planner generates blueprints for complex tasks
- Claude executes with injected constraints and escalation triggers
- Drift detection monitors for mid-session divergence
"""

from .config import (
    MastermindConfig,
    load_config,
    get_config,
    save_config,
    update_drift_thresholds,
)
from .state import MastermindState, Blueprint, load_state, save_state
from .routing import parse_user_override, make_routing_decision
from .hook_integration import process_user_prompt
from .telemetry import get_threshold_effectiveness

__all__ = [
    "MastermindConfig",
    "load_config",
    "get_config",
    "save_config",
    "update_drift_thresholds",
    "MastermindState",
    "Blueprint",
    "load_state",
    "save_state",
    "parse_user_override",
    "make_routing_decision",
    "process_user_prompt",
    "get_threshold_effectiveness",
]
