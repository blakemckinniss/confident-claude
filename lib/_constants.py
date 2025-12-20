"""
Shared constants for the .claude framework.

Consolidates magic numbers to enable:
- Single source of truth
- Easier configuration tuning
- Self-documenting code
"""

# =============================================================================
# TIME CONSTANTS
# =============================================================================

SECONDS_PER_MINUTE = 60
SECONDS_PER_HOUR = 3600
SECONDS_PER_DAY = 86400

# =============================================================================
# BYTE SIZE CONSTANTS
# =============================================================================

BYTES_PER_KB = 1024
BYTES_PER_MB = 1024 * 1024
BYTES_PER_GB = 1024 * 1024 * 1024

# =============================================================================
# NETWORK / PORTS
# =============================================================================

CLAUDE_MEM_PORT = 37777
CLAUDE_MEM_URL = f"http://127.0.0.1:{CLAUDE_MEM_PORT}"

# =============================================================================
# TOKEN BUDGETS (for deliberation/context packing)
# =============================================================================

TOKEN_BUDGET_TRIVIAL = 5000
TOKEN_BUDGET_SIMPLE = 10000
TOKEN_BUDGET_COMPLEX = 20000
TOKEN_BUDGET_STRATEGIC = 30000

# Default token limits for various operations
DEFAULT_DOCS_TOKEN_LIMIT = 5000
ROUTER_TOKEN_BUDGET = 1200
PLANNER_TOKEN_BUDGET = 4000

# =============================================================================
# RETENTION POLICIES (in days unless noted)
# =============================================================================

RETENTION_DEBUG_DAYS = 7
RETENTION_FILE_HISTORY_DAYS = 30
RETENTION_SESSION_ENV_DAYS = 14
RETENTION_SHELL_SNAPSHOTS_DAYS = 7
RETENTION_TODOS_DAYS = 30

# Mastermind state cleanup (hours, not days - accumulates fast)
MASTERMIND_STATE_MAX_HOURS = 24

# =============================================================================
# COMPLEXITY THRESHOLDS (text length in chars)
# =============================================================================

COMPLEXITY_TRIVIAL_MAX_CHARS = 100
COMPLEXITY_SIMPLE_MAX_CHARS = 300
COMPLEXITY_COMPLEX_MAX_CHARS = 800

# =============================================================================
# CONFIDENCE SYSTEM
# =============================================================================

CONFIDENCE_DEFAULT = 75
CONFIDENCE_STASIS_FLOOR = 80
CONFIDENCE_STASIS_CEILING = 90

# Zone thresholds
CONFIDENCE_IGNORANCE_MAX = 30
CONFIDENCE_HYPOTHESIS_MAX = 50
CONFIDENCE_WORKING_MAX = 70
CONFIDENCE_CERTAINTY_MAX = 85
CONFIDENCE_TRUSTED_MAX = 94
# EXPERT = 95-100

# =============================================================================
# FILE SIZE THRESHOLDS
# =============================================================================

GOD_OBJECT_LINE_THRESHOLD = 500
LARGE_DIFF_LOC_THRESHOLD = 400

# =============================================================================
# HOOK / RETRY LIMITS
# =============================================================================

MAX_CONSECUTIVE_FAILURES = 3
CASCADE_BLOCK_THRESHOLD = 3
EDIT_OSCILLATION_THRESHOLD = 3
STUCK_LOOP_EDIT_THRESHOLD = 4
