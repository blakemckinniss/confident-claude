#!/usr/bin/env bash
# ============================================================================
# Claude Code Framework - Bootstrap Script
# ============================================================================
# Run this after cloning the repository to set up all dependencies.
#
# Usage:
#   ./scripts/bootstrap.sh           # Full bootstrap
#   ./scripts/bootstrap.sh --check   # Check only, no install
#   ./scripts/bootstrap.sh --fix     # Install missing Python packages
#   ./scripts/bootstrap.sh --help    # Show help
#
# What this script does:
#   1. Creates Python virtual environment (if missing)
#   2. Installs Python dependencies from requirements.txt
#   3. Checks for required external binaries
#   4. Validates critical directories exist
#   5. Runs the full dependency check
# ============================================================================

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Paths
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLAUDE_DIR="$(dirname "$SCRIPT_DIR")"
VENV_DIR="$CLAUDE_DIR/.venv"
REQUIREMENTS="$CLAUDE_DIR/requirements.txt"
DEP_CHECK="$CLAUDE_DIR/hooks/dependency_check.py"

# Defaults
CHECK_ONLY=false
AUTO_FIX=false
VERBOSE=false

# ============================================================================
# Helper Functions
# ============================================================================

print_header() {
    echo ""
    echo -e "${BLUE}============================================${NC}"
    echo -e "${BLUE}  $1${NC}"
    echo -e "${BLUE}============================================${NC}"
    echo ""
}

print_step() {
    echo -e "${BLUE}➤${NC} $1"
}

print_success() {
    echo -e "${GREEN}✅${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}⚠️${NC}  $1"
}

print_error() {
    echo -e "${RED}❌${NC} $1"
}

print_info() {
    echo -e "   $1"
}

usage() {
    cat << EOF
Claude Code Framework Bootstrap

Usage: $(basename "$0") [OPTIONS]

Options:
    --check, -c     Check dependencies only (no installation)
    --fix, -f       Auto-install missing Python packages
    --verbose, -v   Show detailed output
    --help, -h      Show this help message

Examples:
    # Full bootstrap (creates venv, installs deps)
    ./scripts/bootstrap.sh

    # Check what's missing without installing
    ./scripts/bootstrap.sh --check

    # Install missing Python packages only
    ./scripts/bootstrap.sh --fix

EOF
    exit 0
}

# ============================================================================
# Parse Arguments
# ============================================================================

while [[ $# -gt 0 ]]; do
    case $1 in
        --check|-c)
            CHECK_ONLY=true
            shift
            ;;
        --fix|-f)
            AUTO_FIX=true
            shift
            ;;
        --verbose|-v)
            VERBOSE=true
            shift
            ;;
        --help|-h)
            usage
            ;;
        *)
            echo "Unknown option: $1"
            usage
            ;;
    esac
done

# ============================================================================
# Main Bootstrap Process
# ============================================================================

print_header "Claude Code Framework Bootstrap"

echo "Framework directory: $CLAUDE_DIR"
echo ""

# ----------------------------------------------------------------------------
# Step 1: Check Python
# ----------------------------------------------------------------------------

print_step "Checking Python installation..."

if command -v python3 &> /dev/null; then
    PYTHON_VERSION=$(python3 --version 2>&1)
    print_success "Python found: $PYTHON_VERSION"
else
    print_error "Python 3 not found!"
    echo "    Please install Python 3.10+ from https://python.org"
    exit 1
fi

# ----------------------------------------------------------------------------
# Step 2: Create/Check Virtual Environment
# ----------------------------------------------------------------------------

print_step "Checking virtual environment..."

if [[ -d "$VENV_DIR" ]] && [[ -f "$VENV_DIR/bin/python" ]]; then
    print_success "Virtual environment exists: $VENV_DIR"
else
    if [[ "$CHECK_ONLY" == true ]]; then
        print_warning "Virtual environment missing: $VENV_DIR"
    else
        print_info "Creating virtual environment..."
        python3 -m venv "$VENV_DIR"

        if [[ -f "$VENV_DIR/bin/python" ]]; then
            print_success "Virtual environment created"
        else
            print_error "Failed to create virtual environment"
            exit 1
        fi
    fi
fi

# ----------------------------------------------------------------------------
# Step 3: Install Python Dependencies
# ----------------------------------------------------------------------------

print_step "Checking Python dependencies..."

if [[ ! -f "$REQUIREMENTS" ]]; then
    print_warning "requirements.txt not found: $REQUIREMENTS"
else
    if [[ "$CHECK_ONLY" == true ]]; then
        print_info "Skipping installation (--check mode)"
    else
        print_info "Installing from requirements.txt..."

        # Upgrade pip first
        "$VENV_DIR/bin/pip" install --quiet --upgrade pip

        # Install requirements
        if "$VENV_DIR/bin/pip" install --quiet -r "$REQUIREMENTS" 2>/dev/null; then
            print_success "Python dependencies installed"
        else
            print_warning "Some packages failed to install (may be optional)"
            print_info "Run with --verbose for details"
        fi
    fi
fi

# ----------------------------------------------------------------------------
# Step 4: Check Required Binaries
# ----------------------------------------------------------------------------

print_step "Checking required binaries..."

MISSING_REQUIRED=()
MISSING_OPTIONAL=()

# Required binaries
for bin in git python3; do
    if command -v "$bin" &> /dev/null; then
        [[ "$VERBOSE" == true ]] && print_success "$bin found"
    else
        MISSING_REQUIRED+=("$bin")
    fi
done

# Optional binaries
for bin in node npm ruff bd; do
    if command -v "$bin" &> /dev/null; then
        [[ "$VERBOSE" == true ]] && print_success "$bin found (optional)"
    else
        MISSING_OPTIONAL+=("$bin")
    fi
done

if [[ ${#MISSING_REQUIRED[@]} -gt 0 ]]; then
    print_error "Missing required binaries: ${MISSING_REQUIRED[*]}"
else
    print_success "All required binaries found"
fi

if [[ ${#MISSING_OPTIONAL[@]} -gt 0 ]]; then
    print_warning "Missing optional binaries: ${MISSING_OPTIONAL[*]}"
    print_info "Some features may be unavailable"
fi

# ----------------------------------------------------------------------------
# Step 5: Check Critical Directories
# ----------------------------------------------------------------------------

print_step "Checking critical directories..."

MISSING_DIRS=()
for dir in hooks ops lib memory skills agents commands rules config; do
    dir_path="$CLAUDE_DIR/$dir"
    if [[ -d "$dir_path" ]]; then
        [[ "$VERBOSE" == true ]] && print_success "$dir/"
    else
        MISSING_DIRS+=("$dir")
    fi
done

if [[ ${#MISSING_DIRS[@]} -gt 0 ]]; then
    print_warning "Missing directories: ${MISSING_DIRS[*]}"
    print_info "These may need to be created or the clone may be incomplete"
else
    print_success "All critical directories exist"
fi

# ----------------------------------------------------------------------------
# Step 6: Run Full Dependency Check
# ----------------------------------------------------------------------------

print_step "Running full dependency check..."

if [[ -f "$DEP_CHECK" ]] && [[ -f "$VENV_DIR/bin/python" ]]; then
    DEP_ARGS=""
    [[ "$AUTO_FIX" == true ]] && DEP_ARGS="--fix"
    [[ "$VERBOSE" == true ]] && DEP_ARGS="$DEP_ARGS --verbose"
    [[ "$CHECK_ONLY" == true ]] && DEP_ARGS="$DEP_ARGS --no-cache"

    echo ""
    "$VENV_DIR/bin/python" "$DEP_CHECK" $DEP_ARGS
    DEP_EXIT=$?
    echo ""

    if [[ $DEP_EXIT -eq 0 ]]; then
        print_success "Dependency check passed"
    else
        print_warning "Dependency check found issues (see above)"
    fi
else
    print_warning "Cannot run dependency check (missing script or venv)"
fi

# ----------------------------------------------------------------------------
# Summary
# ----------------------------------------------------------------------------

print_header "Bootstrap Complete"

echo "Next steps:"
echo ""
echo "  1. Set up API keys (optional):"
echo "     export OPENROUTER_API_KEY='your-key'    # For oracle/council"
echo "     export TAVILY_API_KEY='your-key'        # For web research"
echo "     export ANTHROPIC_API_KEY='your-key'     # For orchestrate"
echo ""
echo "  2. Configure Claude Code to use this framework:"
echo "     Add hooks to ~/.claude.json or Claude Code settings"
echo ""
echo "  3. Run dependency check anytime:"
echo "     $VENV_DIR/bin/python $DEP_CHECK"
echo ""
echo "  4. To re-run bootstrap:"
echo "     $SCRIPT_DIR/$(basename "$0")"
echo ""

if [[ ${#MISSING_REQUIRED[@]} -gt 0 ]]; then
    exit 1
fi

exit 0
