#!/usr/bin/env python3
"""
Epistemology Library: State Management for Confidence & Risk Tracking
Provides utilities for the Dual-Metric Epistemological Protocol

NOTE: This is a minimal version with only the functions actually used.
Full version backed up at epistemology.py.bak
"""
import json
from pathlib import Path
from typing import Dict, Optional, Tuple

# Paths
MEMORY_DIR = Path(__file__).resolve().parent.parent / "memory"
STATE_FILE = MEMORY_DIR / "confidence_state.json"

# Confidence Tiers (Graduated System - 6 tiers)
TIER_IGNORANCE = (0, 30)
TIER_HYPOTHESIS = (31, 50)
TIER_WORKING = (51, 70)
TIER_CERTAINTY = (71, 85)
TIER_TRUSTED = (86, 94)
TIER_EXPERT = (95, 100)

# Tier Privilege Mapping
TIER_PRIVILEGES = {
    "IGNORANCE": {
        "write_scratch": False,
        "edit_any": False,
        "write_production": False,
        "git_write": False,
        "bash_production": False,
        "prerequisite_mode": "n/a",
    },
    "HYPOTHESIS": {
        "write_scratch": True,
        "edit_any": False,
        "write_production": False,
        "git_write": False,
        "git_read": False,
        "bash_production": False,
        "prerequisite_mode": "n/a",
    },
    "WORKING": {
        "write_scratch": True,
        "edit_scratch": True,
        "edit_production": False,
        "write_production": False,
        "git_read": True,
        "git_write": False,
        "bash_production": False,
        "prerequisite_mode": "n/a",
    },
    "CERTAINTY": {
        "write_scratch": True,
        "edit_scratch": True,
        "write_production": True,
        "edit_production": True,
        "git_write": True,
        "bash_production": True,
        "prerequisite_mode": "enforce",
    },
    "TRUSTED": {
        "write_scratch": True,
        "edit_any": True,
        "write_production": True,
        "edit_production": True,
        "git_write": True,
        "bash_production": True,
        "prerequisite_mode": "warn",
    },
    "EXPERT": {
        "write_scratch": True,
        "edit_any": True,
        "write_production": True,
        "edit_production": True,
        "git_write": True,
        "bash_production": True,
        "prerequisite_mode": "disabled",
    },
}


def get_session_state_file(session_id: str) -> Path:
    """Get path to session-specific state file"""
    return MEMORY_DIR / f"session_{session_id}_state.json"


def load_session_state(session_id: str) -> Optional[Dict]:
    """Load session state, return None if not found"""
    state_file = get_session_state_file(session_id)
    if not state_file.exists():
        return None

    try:
        with open(state_file) as f:
            return json.load(f)
    except Exception:
        return None


def get_confidence_tier(confidence: int) -> Tuple[str, str]:
    """
    Get confidence tier name and description (graduated 6-tier system)

    Returns:
        Tuple[str, str]: (tier_name, tier_description)
    """
    if TIER_IGNORANCE[0] <= confidence <= TIER_IGNORANCE[1]:
        return "IGNORANCE", "Read/Research/Probe only, no coding"
    elif TIER_HYPOTHESIS[0] <= confidence <= TIER_HYPOTHESIS[1]:
        return "HYPOTHESIS", "Can write to .claude/tmp/ only (no Edit)"
    elif TIER_WORKING[0] <= confidence <= TIER_WORKING[1]:
        return "WORKING", "Can Edit .claude/tmp/, git read-only"
    elif TIER_CERTAINTY[0] <= confidence <= TIER_CERTAINTY[1]:
        return "CERTAINTY", "Production access with MANDATORY quality gates"
    elif TIER_TRUSTED[0] <= confidence <= TIER_TRUSTED[1]:
        return "TRUSTED", "Production access with WARNINGS (not blocks)"
    else:
        return "EXPERT", "Maximum freedom, minimal hook interference"
