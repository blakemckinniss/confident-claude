#!/usr/bin/env bash
# ============================================================================
# Claude Code Framework - Bootstrap & Setup Wizard
# ============================================================================
# Comprehensive setup script for getting the framework running from scratch.
# Designed for users who clone from GitHub and need guided setup.
#
# Usage:
#   ./scripts/bootstrap.sh              # Interactive setup wizard
#   ./scripts/bootstrap.sh --check      # Quick health check (no changes)
#   ./scripts/bootstrap.sh --fix        # Auto-fix all fixable issues
#   ./scripts/bootstrap.sh --minimal    # Minimal setup (venv + deps only)
#   ./scripts/bootstrap.sh --help       # Show help
#
# What this script handles:
#   1. Python virtual environment setup
#   2. Python package installation
#   3. Node.js/npm verification (for MCP servers)
#   4. Claude Code hooks configuration
#   5. API key setup guidance
#   6. Plugin verification
#   7. Directory structure validation
#   8. Common issue repair
# ============================================================================

set -euo pipefail

# ============================================================================
# Configuration
# ============================================================================

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
MAGENTA='\033[0;35m'
BOLD='\033[1m'
DIM='\033[2m'
NC='\033[0m'

# Paths
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLAUDE_DIR="$(dirname "$SCRIPT_DIR")"
VENV_DIR="$CLAUDE_DIR/.venv"
REQUIREMENTS="$CLAUDE_DIR/requirements.txt"
DEP_CHECK="$CLAUDE_DIR/hooks/dependency_check.py"
SETTINGS_JSON="$CLAUDE_DIR/settings.json"
CLAUDE_JSON="$HOME/.claude.json"

# Modes
MODE="interactive"  # interactive, check, fix, minimal
VERBOSE=false
SKIP_OPTIONAL=false

# Counters
ISSUES_FOUND=0
ISSUES_FIXED=0
WARNINGS=0

# ============================================================================
# Helper Functions
# ============================================================================

print_banner() {
    echo ""
    echo -e "${BLUE}╔════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${BLUE}║${NC}  ${BOLD}Claude Code Framework${NC} - Setup Wizard                      ${BLUE}║${NC}"
    echo -e "${BLUE}║${NC}  ${DIM}v2.0 - Comprehensive bootstrap for new installations${NC}      ${BLUE}║${NC}"
    echo -e "${BLUE}╚════════════════════════════════════════════════════════════╝${NC}"
    echo ""
}

print_section() {
    echo ""
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${CYAN}  $1${NC}"
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
}

print_step() {
    echo -e "\n${BLUE}▶${NC} ${BOLD}$1${NC}"
}

print_substep() {
    echo -e "  ${DIM}├─${NC} $1"
}

print_success() {
    echo -e "  ${GREEN}✓${NC} $1"
}

print_warning() {
    echo -e "  ${YELLOW}⚠${NC} $1"
    ((WARNINGS++)) || true
}

print_error() {
    echo -e "  ${RED}✗${NC} $1"
    ((ISSUES_FOUND++)) || true
}

print_info() {
    echo -e "  ${DIM}ℹ${NC} $1"
}

print_fix() {
    echo -e "  ${MAGENTA}⚡${NC} $1"
    ((ISSUES_FIXED++)) || true
}

print_skip() {
    echo -e "  ${DIM}○${NC} $1 ${DIM}(skipped)${NC}"
}

# Ask yes/no question, returns 0 for yes, 1 for no
ask_yn() {
    local prompt="$1"
    local default="${2:-y}"

    if [[ "$MODE" != "interactive" ]]; then
        [[ "$default" == "y" ]] && return 0 || return 1
    fi

    local yn_hint="[Y/n]"
    [[ "$default" == "n" ]] && yn_hint="[y/N]"

    read -r -p "  → $prompt $yn_hint " response
    response="${response:-$default}"
    [[ "$response" =~ ^[Yy] ]]
}

# Check if command exists
has_command() {
    command -v "$1" &> /dev/null
}

# Get OS type
get_os() {
    case "$(uname -s)" in
        Linux*)  echo "linux" ;;
        Darwin*) echo "macos" ;;
        MINGW*|MSYS*|CYGWIN*) echo "windows" ;;
        *)       echo "unknown" ;;
    esac
}

# Check if running in WSL
is_wsl() {
    [[ -f /proc/version ]] && grep -qi microsoft /proc/version
}

usage() {
    cat << 'EOF'
Claude Code Framework - Bootstrap & Setup Wizard

USAGE:
    ./scripts/bootstrap.sh [OPTIONS]

OPTIONS:
    --check, -c         Quick health check (no modifications)
    --fix, -f           Auto-fix all fixable issues without prompting
    --minimal, -m       Minimal setup (venv + Python deps only)
    --skip-optional     Skip optional components (API keys, plugins)
    --verbose, -v       Show detailed output
    --help, -h          Show this help message

EXAMPLES:
    # First-time setup (interactive wizard)
    ./scripts/bootstrap.sh

    # Quick health check
    ./scripts/bootstrap.sh --check

    # Fix everything automatically
    ./scripts/bootstrap.sh --fix

    # Minimal setup for CI/testing
    ./scripts/bootstrap.sh --minimal

WHAT IT CHECKS:
    ✓ Python 3.10+ installation
    ✓ Virtual environment setup
    ✓ Python package dependencies
    ✓ Node.js 18+ (for MCP servers)
    ✓ Required binaries (git, etc.)
    ✓ Framework directory structure
    ✓ Claude Code hooks configuration
    ✓ Installed plugins validation
    ✓ API key configuration

For more information, see the README.md in this directory.
EOF
    exit 0
}

# ============================================================================
# Parse Arguments
# ============================================================================

while [[ $# -gt 0 ]]; do
    case $1 in
        --check|-c)
            MODE="check"
            shift
            ;;
        --fix|-f)
            MODE="fix"
            shift
            ;;
        --minimal|-m)
            MODE="minimal"
            SKIP_OPTIONAL=true
            shift
            ;;
        --skip-optional)
            SKIP_OPTIONAL=true
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
            echo "Run with --help for usage information"
            exit 1
            ;;
    esac
done

# ============================================================================
# Pre-flight Checks
# ============================================================================

preflight_checks() {
    print_section "Pre-flight Checks"

    # Check we're in the right directory
    if [[ ! -f "$CLAUDE_DIR/requirements.txt" ]]; then
        print_error "Cannot find requirements.txt - are you in the right directory?"
        print_info "Expected: $CLAUDE_DIR/requirements.txt"
        exit 1
    fi

    print_success "Framework directory: $CLAUDE_DIR"

    # Detect environment
    local os=$(get_os)
    local env_info="$os"
    is_wsl && env_info="WSL2 ($os)"
    print_success "Environment: $env_info"

    # Check mode
    case $MODE in
        check)      print_info "Mode: Health check (read-only)" ;;
        fix)        print_info "Mode: Auto-fix (will make changes)" ;;
        minimal)    print_info "Mode: Minimal setup" ;;
        interactive) print_info "Mode: Interactive wizard" ;;
    esac
}

# ============================================================================
# Step 1: Python Setup
# ============================================================================

setup_python() {
    print_section "Step 1: Python Environment"

    print_step "Checking Python installation"

    if ! has_command python3; then
        print_error "Python 3 not found!"
        print_info "Install Python 3.10+ from https://python.org"

        case $(get_os) in
            linux)
                print_info "Ubuntu/Debian: sudo apt install python3 python3-venv python3-pip"
                print_info "Fedora: sudo dnf install python3 python3-pip"
                ;;
            macos)
                print_info "macOS: brew install python3"
                ;;
        esac
        return 1
    fi

    local py_version=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
    local py_major=$(echo "$py_version" | cut -d. -f1)
    local py_minor=$(echo "$py_version" | cut -d. -f2)

    if [[ "$py_major" -lt 3 ]] || [[ "$py_major" -eq 3 && "$py_minor" -lt 10 ]]; then
        print_warning "Python $py_version found, but 3.10+ recommended"
    else
        print_success "Python $py_version found"
    fi

    # Virtual environment
    print_step "Checking virtual environment"

    if [[ -d "$VENV_DIR" ]] && [[ -f "$VENV_DIR/bin/python" ]]; then
        print_success "Virtual environment exists"

        # Check venv Python version matches system
        local venv_py=$("$VENV_DIR/bin/python" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
        if [[ "$venv_py" != "$py_version" ]]; then
            print_warning "Venv Python ($venv_py) differs from system ($py_version)"
            if [[ "$MODE" == "fix" ]] || ask_yn "Recreate virtual environment?"; then
                print_fix "Recreating virtual environment..."
                rm -rf "$VENV_DIR"
                python3 -m venv "$VENV_DIR"
                print_success "Virtual environment recreated"
            fi
        fi
    else
        if [[ "$MODE" == "check" ]]; then
            print_error "Virtual environment missing: $VENV_DIR"
            return 1
        else
            print_info "Creating virtual environment..."
            python3 -m venv "$VENV_DIR"

            if [[ -f "$VENV_DIR/bin/python" ]]; then
                print_fix "Virtual environment created"
            else
                print_error "Failed to create virtual environment"
                return 1
            fi
        fi
    fi

    # Python packages
    print_step "Checking Python packages"

    if [[ ! -f "$REQUIREMENTS" ]]; then
        print_error "requirements.txt not found"
        return 1
    fi

    if [[ "$MODE" == "check" ]]; then
        # Use pip to check installed packages (more reliable than import checking)
        local installed
        installed=$("$VENV_DIR/bin/pip" freeze 2>/dev/null | cut -d= -f1 | tr '[:upper:]' '[:lower:]' | tr '_' '-')
        local missing=0
        local missing_list=()

        while IFS= read -r line || [[ -n "$line" ]]; do
            # Skip comments and empty lines
            [[ -z "$line" || "$line" =~ ^# ]] && continue
            # Extract package name (before any version specifier), normalize
            local pkg=$(echo "$line" | sed 's/[<>=!].*//' | tr '[:upper:]' '[:lower:]' | tr '_' '-' | xargs)
            [[ -z "$pkg" ]] && continue

            if ! echo "$installed" | grep -qx "$pkg"; then
                missing_list+=("$pkg")
                ((missing++)) || true
            fi
        done < "$REQUIREMENTS"

        if [[ $missing -gt 0 ]]; then
            # Treat as warning since dependency_check.py validates essential packages
            print_warning "$missing packages from requirements.txt not installed"
            [[ "$VERBOSE" == true ]] && print_info "Missing: ${missing_list[*]}"
            print_info "Run without --check to install all packages"
        else
            print_success "All Python packages installed"
        fi
    else
        print_info "Upgrading pip..."
        "$VENV_DIR/bin/pip" install --quiet --upgrade pip 2>/dev/null || true

        print_info "Installing packages from requirements.txt..."
        if "$VENV_DIR/bin/pip" install --quiet -r "$REQUIREMENTS" 2>/dev/null; then
            print_fix "Python packages installed"
        else
            print_warning "Some packages may have failed (check with --verbose)"
            # Try installing one by one to identify failures
            if [[ "$VERBOSE" == true ]]; then
                while IFS= read -r line || [[ -n "$line" ]]; do
                    [[ -z "$line" || "$line" =~ ^# ]] && continue
                    if ! "$VENV_DIR/bin/pip" install --quiet "$line" 2>/dev/null; then
                        print_error "Failed to install: $line"
                    fi
                done < "$REQUIREMENTS"
            fi
        fi
    fi
}

# ============================================================================
# Step 2: Node.js Setup
# ============================================================================

setup_node() {
    print_section "Step 2: Node.js Environment"

    if [[ "$SKIP_OPTIONAL" == true ]]; then
        print_skip "Node.js check (--skip-optional)"
        return 0
    fi

    print_step "Checking Node.js installation"

    if ! has_command node; then
        print_warning "Node.js not found"
        print_info "Node.js 18+ is needed for MCP servers and some plugins"

        if [[ "$MODE" == "interactive" ]]; then
            echo ""
            echo -e "  ${BOLD}Install Node.js:${NC}"
            case $(get_os) in
                linux)
                    if is_wsl; then
                        echo "    # Using nvm (recommended for WSL):"
                        echo "    curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.0/install.sh | bash"
                        echo "    source ~/.bashrc"
                        echo "    nvm install 20"
                        echo ""
                        echo "    # Or using apt:"
                        echo "    curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -"
                        echo "    sudo apt install -y nodejs"
                    else
                        echo "    curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -"
                        echo "    sudo apt install -y nodejs"
                    fi
                    ;;
                macos)
                    echo "    brew install node"
                    ;;
            esac
            echo ""
        fi
        return 0
    fi

    local node_version=$(node --version | tr -d 'v')
    local node_major=$(echo "$node_version" | cut -d. -f1)

    if [[ "$node_major" -lt 18 ]]; then
        print_warning "Node.js $node_version found, but 18+ recommended for MCP servers"
    else
        print_success "Node.js $node_version found"
    fi

    # Check npm
    print_step "Checking npm"

    if has_command npm; then
        local npm_version=$(npm --version)
        print_success "npm $npm_version found"
    else
        print_warning "npm not found (usually comes with Node.js)"
    fi
}

# ============================================================================
# Step 3: Required Binaries
# ============================================================================

check_binaries() {
    print_section "Step 3: Required Binaries"

    print_step "Checking required tools"

    # Required
    local required_bins=("git" "python3")
    for bin in "${required_bins[@]}"; do
        if has_command "$bin"; then
            local version=$("$bin" --version 2>&1 | head -1)
            print_success "$bin: $version"
        else
            print_error "$bin not found (required)"
        fi
    done

    print_step "Checking optional tools"

    # Optional with install hints
    declare -A optional_bins=(
        ["ruff"]="pip install ruff"
        ["bd"]="cargo install bd (or see beads documentation)"
        ["jq"]="apt install jq / brew install jq"
    )

    for bin in "${!optional_bins[@]}"; do
        if has_command "$bin"; then
            [[ "$VERBOSE" == true ]] && print_success "$bin found"
        else
            print_warning "$bin not found: ${optional_bins[$bin]}"
        fi
    done
}

# ============================================================================
# Step 4: Directory Structure
# ============================================================================

check_directories() {
    print_section "Step 4: Framework Structure"

    print_step "Checking critical directories"

    local dirs=("hooks" "ops" "lib" "memory" "skills" "agents" "commands" "rules" "config" "scripts")
    local missing_dirs=()

    for dir in "${dirs[@]}"; do
        local dir_path="$CLAUDE_DIR/$dir"
        if [[ -d "$dir_path" ]]; then
            [[ "$VERBOSE" == true ]] && print_success "$dir/"
        else
            missing_dirs+=("$dir")
            if [[ "$MODE" == "check" ]]; then
                print_error "Missing: $dir/"
            else
                print_info "Creating: $dir/"
                mkdir -p "$dir_path"
                print_fix "Created $dir/"
            fi
        fi
    done

    if [[ ${#missing_dirs[@]} -eq 0 ]]; then
        print_success "All ${#dirs[@]} directories present"
    fi

    # Check for key files
    print_step "Checking key files"

    local key_files=(
        "requirements.txt"
        "hooks/dependency_check.py"
        "hooks/pre_tool_use_runner.py"
        "hooks/post_tool_use_runner.py"
    )

    for file in "${key_files[@]}"; do
        local file_path="$CLAUDE_DIR/$file"
        if [[ -f "$file_path" ]]; then
            [[ "$VERBOSE" == true ]] && print_success "$file"
        else
            print_error "Missing: $file"
        fi
    done
}

# ============================================================================
# Step 5: Claude Code Configuration
# ============================================================================

setup_claude_config() {
    print_section "Step 5: Claude Code Configuration"

    if [[ "$SKIP_OPTIONAL" == true ]]; then
        print_skip "Configuration setup (--skip-optional)"
        return 0
    fi

    print_step "Checking hooks configuration"

    # Check if hooks are configured in ~/.claude.json
    if [[ -f "$CLAUDE_JSON" ]]; then
        if grep -q "hooks" "$CLAUDE_JSON" 2>/dev/null; then
            print_success "Hooks configured in ~/.claude.json"

            # Verify hook paths exist
            if [[ "$VERBOSE" == true ]]; then
                if grep -q "$CLAUDE_DIR/hooks" "$CLAUDE_JSON" 2>/dev/null; then
                    print_success "Hook paths reference this framework"
                else
                    print_warning "Hook paths may reference different location"
                fi
            fi
        else
            print_warning "No hooks section in ~/.claude.json"

            if [[ "$MODE" == "interactive" ]]; then
                echo ""
                echo -e "  ${BOLD}To enable hooks, add to ~/.claude.json:${NC}"
                echo ""
                cat << 'HOOKS_EXAMPLE'
    "hooks": {
      "PreToolUse": [{"hooks": [{"type": "command", "command": "$HOME/.claude/hooks/py $HOME/.claude/hooks/pre_tool_use_runner.py"}]}],
      "PostToolUse": [{"hooks": [{"type": "command", "command": "$HOME/.claude/hooks/py $HOME/.claude/hooks/post_tool_use_runner.py"}]}],
      "UserPromptSubmit": [{"hooks": [{"type": "command", "command": "$HOME/.claude/hooks/py $HOME/.claude/hooks/user_prompt_submit_runner.py"}]}],
      "Stop": [{"hooks": [{"type": "command", "command": "$HOME/.claude/hooks/py $HOME/.claude/hooks/stop_runner.py"}]}],
      "SessionStart": [{"hooks": [{"type": "command", "command": "$HOME/.claude/hooks/py $HOME/.claude/hooks/session_init.py"}]}]
    }
HOOKS_EXAMPLE
                echo ""
            fi
        fi
    else
        print_warning "~/.claude.json not found"
        print_info "Create it to configure Claude Code hooks"
    fi

    # Check settings.json
    print_step "Checking settings.json"

    if [[ -f "$SETTINGS_JSON" ]]; then
        if python3 -c "import json; json.load(open('$SETTINGS_JSON'))" 2>/dev/null; then
            print_success "settings.json is valid JSON"
        else
            print_error "settings.json has invalid JSON"
        fi
    else
        print_warning "settings.json not found"

        if [[ "$MODE" != "check" ]]; then
            if ask_yn "Create default settings.json?" "y"; then
                cat > "$SETTINGS_JSON" << 'SETTINGS'
{
  "hooks_enabled": true,
  "confidence_tracking": true,
  "statusline_enabled": true
}
SETTINGS
                print_fix "Created settings.json"
            fi
        fi
    fi
}

# ============================================================================
# Step 6: API Keys
# ============================================================================

setup_api_keys() {
    print_section "Step 6: API Keys (Optional)"

    if [[ "$SKIP_OPTIONAL" == true ]]; then
        print_skip "API key setup (--skip-optional)"
        return 0
    fi

    print_step "Checking API keys"

    declare -A api_keys=(
        ["ANTHROPIC_API_KEY"]="Claude API (for orchestrate command)"
        ["OPENROUTER_API_KEY"]="OpenRouter (for oracle/council/think commands)"
        ["TAVILY_API_KEY"]="Tavily (for /research command)"
        ["GROQ_API_KEY"]="Groq (for fast inference)"
    )

    local missing_keys=()

    for key in "${!api_keys[@]}"; do
        if [[ -n "${!key:-}" ]]; then
            # Mask the key value
            local masked="${!key:0:8}...${!key: -4}"
            print_success "$key: $masked"
        else
            missing_keys+=("$key")
            print_warning "$key not set - ${api_keys[$key]}"
        fi
    done

    if [[ ${#missing_keys[@]} -gt 0 && "$MODE" == "interactive" ]]; then
        echo ""
        echo -e "  ${BOLD}To set API keys, add to your shell profile (~/.bashrc or ~/.zshrc):${NC}"
        echo ""
        for key in "${missing_keys[@]}"; do
            echo "    export $key='your-key-here'"
        done
        echo ""
        echo -e "  ${DIM}Get keys from:${NC}"
        echo "    • Anthropic: https://console.anthropic.com/"
        echo "    • OpenRouter: https://openrouter.ai/keys"
        echo "    • Tavily: https://tavily.com/"
        echo "    • Groq: https://console.groq.com/"
        echo ""
    fi
}

# ============================================================================
# Step 7: Plugins
# ============================================================================

check_plugins() {
    print_section "Step 7: Installed Plugins"

    if [[ "$SKIP_OPTIONAL" == true ]]; then
        print_skip "Plugin check (--skip-optional)"
        return 0
    fi

    print_step "Checking installed plugins"

    local plugins_json="$HOME/.claude/plugins/installed_plugins.json"

    if [[ ! -f "$plugins_json" ]]; then
        print_info "No plugins installed yet"
        return 0
    fi

    # Use Python to parse and validate plugins
    "$VENV_DIR/bin/python" - "$plugins_json" << 'PYPLUGINS'
import json
import sys
from pathlib import Path

plugins_file = sys.argv[1]

try:
    with open(plugins_file) as f:
        data = json.load(f)

    plugins = data.get("plugins", {})
    valid = 0
    invalid = 0

    for plugin_id, installations in plugins.items():
        for install in installations:
            path = Path(install.get("installPath", ""))
            version = install.get("version", "?")

            if path.exists():
                # Check for plugin components
                has_content = any([
                    (path / "skills").is_dir(),
                    (path / "agents").is_dir(),
                    (path / "commands").is_dir(),
                    (path / "hooks").is_dir(),
                    (path / ".mcp.json").is_file(),
                ])
                if has_content:
                    valid += 1
                else:
                    print(f"  ⚠ {plugin_id} v{version}: empty plugin directory")
                    invalid += 1
            else:
                print(f"  ✗ {plugin_id} v{version}: path missing")
                invalid += 1

    if valid > 0:
        print(f"  ✓ {valid} plugins validated")
    if invalid > 0:
        print(f"  ⚠ {invalid} plugins have issues")

except Exception as e:
    print(f"  ✗ Error reading plugins: {e}")
PYPLUGINS
}

# ============================================================================
# Step 8: Full Dependency Check
# ============================================================================

run_full_check() {
    print_section "Step 8: Full Dependency Validation"

    print_step "Running comprehensive dependency check"

    if [[ ! -f "$DEP_CHECK" ]]; then
        print_error "dependency_check.py not found"
        return 1
    fi

    if [[ ! -f "$VENV_DIR/bin/python" ]]; then
        print_error "Virtual environment not ready"
        return 1
    fi

    local dep_args="--no-cache"
    [[ "$MODE" == "fix" ]] && dep_args="$dep_args --fix"
    [[ "$VERBOSE" == true ]] && dep_args="$dep_args --verbose"

    echo ""
    # shellcheck disable=SC2086
    if "$VENV_DIR/bin/python" "$DEP_CHECK" $dep_args; then
        print_success "All dependency checks passed"
    else
        print_warning "Some dependency checks reported issues"
    fi
}

# ============================================================================
# Summary and Next Steps
# ============================================================================

print_summary() {
    echo ""
    echo -e "${BLUE}╔════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${BLUE}║${NC}  ${BOLD}Setup Summary${NC}                                              ${BLUE}║${NC}"
    echo -e "${BLUE}╚════════════════════════════════════════════════════════════╝${NC}"
    echo ""

    if [[ $ISSUES_FOUND -eq 0 && $WARNINGS -eq 0 ]]; then
        echo -e "  ${GREEN}✓ All checks passed!${NC}"
    else
        [[ $ISSUES_FIXED -gt 0 ]] && echo -e "  ${MAGENTA}⚡ Fixed: $ISSUES_FIXED issues${NC}"
        [[ $ISSUES_FOUND -gt 0 ]] && echo -e "  ${RED}✗ Issues: $ISSUES_FOUND remaining${NC}"
        [[ $WARNINGS -gt 0 ]] && echo -e "  ${YELLOW}⚠ Warnings: $WARNINGS${NC}"
    fi

    echo ""
    echo -e "${BOLD}Quick Commands:${NC}"
    echo ""
    echo "  # Run Claude Code with this framework"
    echo "  claude"
    echo ""
    echo "  # Check framework health anytime"
    echo "  $SCRIPT_DIR/bootstrap.sh --check"
    echo ""
    echo "  # Run dependency check directly"
    echo "  $VENV_DIR/bin/python $DEP_CHECK"
    echo ""

    if [[ $ISSUES_FOUND -gt 0 || $WARNINGS -gt 0 ]]; then
        echo -e "${BOLD}To fix issues:${NC}"
        echo ""
        echo "  # Auto-fix what can be fixed"
        echo "  $SCRIPT_DIR/bootstrap.sh --fix"
        echo ""
    fi

    echo -e "${DIM}Framework: $CLAUDE_DIR${NC}"
    echo -e "${DIM}Documentation: $CLAUDE_DIR/scripts/README.md${NC}"
    echo ""
}

# ============================================================================
# Main
# ============================================================================

main() {
    print_banner
    preflight_checks

    setup_python || true
    setup_node || true
    check_binaries || true
    check_directories || true

    if [[ "$MODE" != "minimal" ]]; then
        setup_claude_config || true
        setup_api_keys || true
        check_plugins || true
        run_full_check || true
    fi

    print_summary

    # Exit with error if critical issues remain
    if [[ $ISSUES_FOUND -gt 0 ]]; then
        exit 1
    fi

    exit 0
}

main
