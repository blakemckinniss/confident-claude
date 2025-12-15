#!/usr/bin/env python3
"""
Confidence Constants - Shared constants for all confidence modules.

This module exists to break circular import dependencies.
"""

# Confidence thresholds
THRESHOLD_ROCK_BOTTOM = 10  # At or below: FORCED realignment with user
THRESHOLD_MANDATORY_EXTERNAL = 30  # Below this: external LLM MANDATORY
THRESHOLD_REQUIRE_RESEARCH = 50  # Below this: research REQUIRED
THRESHOLD_PRODUCTION_ACCESS = 51  # Below this: no production writes

# Rock bottom recovery target (nerfed from 85 to prevent gaming)
ROCK_BOTTOM_RECOVERY_TARGET = 65  # Boost to this after realignment

# Tier emoji mapping
TIER_EMOJI = {
    "IGNORANCE": "\U0001f534",  # Red circle
    "HYPOTHESIS": "\U0001f7e0",  # Orange circle
    "WORKING": "\U0001f7e1",  # Yellow circle
    "CERTAINTY": "\U0001f7e2",  # Green circle
    "TRUSTED": "\U0001f49a",  # Green heart
    "EXPERT": "\U0001f48e",  # Gem
}

# Default starting confidence for new sessions
DEFAULT_CONFIDENCE = 70  # Start at WORKING level

# Rate limit constants
MAX_CONFIDENCE_DELTA_PER_TURN = 15
MAX_CONFIDENCE_RECOVERY_DELTA = 30
STASIS_FLOOR = 80

# Streak constants
STREAK_MULTIPLIERS = {2: 1.25, 3: 1.5, 5: 2.0}
STREAK_DECAY_ON_FAILURE = 0

# Diminishing returns
FARMABLE_INCREASERS = {"file_read", "productive_bash", "search_tool"}
DIMINISHING_MULTIPLIERS = {1: 1.0, 2: 0.75, 3: 0.5, 4: 0.25}
DIMINISHING_CAP = 5

# Mean reversion
MEAN_REVERSION_TARGET = 75
MEAN_REVERSION_RATE = 0.02
