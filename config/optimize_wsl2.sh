#!/bin/bash
# WSL2 Optimization for Claude Code Performance
# Run: ~/.claude/config/optimize_wsl2.sh
# Some changes require: wsl --shutdown (from Windows) to take effect

set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log() { echo -e "${GREEN}[+]${NC} $1"; }
warn() { echo -e "${YELLOW}[!]${NC} $1"; }
err() { echo -e "${RED}[x]${NC} $1"; }

# ─────────────────────────────────────────────────────────────────────────────
# 1. SYSCTL OPTIMIZATIONS
# ─────────────────────────────────────────────────────────────────────────────
configure_sysctl() {
    log "Configuring sysctl optimizations..."

    SYSCTL_CONF="/etc/sysctl.d/99-claude-code.conf"

    sudo tee "$SYSCTL_CONF" > /dev/null << 'EOF'
# Claude Code WSL2 Optimizations
# Apply: sudo sysctl -p /etc/sysctl.d/99-claude-code.conf

# ─── Memory Management ───
# Reduce swappiness (default 60 is too aggressive for dev work)
vm.swappiness = 10
# Reduce tendency to reclaim cache memory
vm.vfs_cache_pressure = 50
# More aggressive dirty page writeback (helps with file operations)
vm.dirty_ratio = 15
vm.dirty_background_ratio = 5

# ─── File System ───
# Increase inotify limits (for file watchers, hot reload)
fs.inotify.max_user_watches = 1048576
fs.inotify.max_user_instances = 512
fs.inotify.max_queued_events = 32768
# Increase file handle limits
fs.file-max = 2097152

# ─── Network (localhost performance) ───
# Larger socket buffers for local IPC
net.core.rmem_max = 16777216
net.core.wmem_max = 16777216
net.core.rmem_default = 1048576
net.core.wmem_default = 1048576
# Increase connection backlog
net.core.somaxconn = 65535
net.core.netdev_max_backlog = 65535
# TCP optimizations for localhost
net.ipv4.tcp_max_syn_backlog = 65535
net.ipv4.tcp_fin_timeout = 15
net.ipv4.tcp_keepalive_time = 300
net.ipv4.tcp_keepalive_intvl = 15
net.ipv4.tcp_keepalive_probes = 5
EOF

    sudo sysctl -p "$SYSCTL_CONF"
    log "Sysctl optimizations applied"
}

# ─────────────────────────────────────────────────────────────────────────────
# 2. LIMITS CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────
configure_limits() {
    log "Configuring user limits..."

    LIMITS_CONF="/etc/security/limits.d/99-claude-code.conf"

    sudo tee "$LIMITS_CONF" > /dev/null << 'EOF'
# Claude Code resource limits
# Applies on next login

# File descriptors
*               soft    nofile          1048576
*               hard    nofile          1048576

# Max processes
*               soft    nproc           unlimited
*               hard    nproc           unlimited

# Core dumps (disabled for speed)
*               soft    core            0
*               hard    core            0

# Stack size
*               soft    stack           32768
*               hard    stack           65536
EOF

    log "Limits configured (requires re-login)"
}

# ─────────────────────────────────────────────────────────────────────────────
# 3. SHELL STARTUP OPTIMIZATION
# ─────────────────────────────────────────────────────────────────────────────
optimize_bashrc() {
    log "Checking shell startup time..."

    # Measure current startup time
    STARTUP_TIME=$(bash -ic "exit" 2>&1 | head -1 || time bash -ic "exit" 2>&1 | grep real | awk '{print $2}')

    # Create fast-path bashrc additions
    FAST_BASHRC="$HOME/.bashrc.d/99-claude-fast.sh"
    mkdir -p "$HOME/.bashrc.d"

    cat > "$FAST_BASHRC" << 'EOF'
# Claude Code fast-path shell config
# Loaded by .bashrc if $HOME/.bashrc.d/ exists

# Fast prompt (no git status by default - slows down prompt in large repos)
if [[ -z "$CLAUDE_FAST_PROMPT" ]]; then
    export CLAUDE_FAST_PROMPT=1
fi

# Aliases for common Claude Code operations
alias cc="claude"
alias ccc="claude --dangerously-skip-permissions -c"
alias bd="~/.claude/hooks/py ~/.claude/ops/beads.py"

# Quick navigation
alias cdp="cd ~/projects"
alias cdc="cd ~/.claude"
alias cda="cd ~/ai"

# Performance: don't check mail
unset MAILCHECK

# History optimization
export HISTSIZE=10000
export HISTFILESIZE=20000
export HISTCONTROL=ignoreboth:erasedups
shopt -s histappend
EOF

    # Add loader to .bashrc if not present
    if ! grep -q "bashrc.d/99-claude-fast.sh" "$HOME/.bashrc" 2>/dev/null; then
        echo '' >> "$HOME/.bashrc"
        echo '# Load Claude Code optimizations' >> "$HOME/.bashrc"
        echo '[[ -f ~/.bashrc.d/99-claude-fast.sh ]] && source ~/.bashrc.d/99-claude-fast.sh' >> "$HOME/.bashrc"
        log "Added fast-path loader to .bashrc"
    else
        log "Fast-path already in .bashrc"
    fi
}

# ─────────────────────────────────────────────────────────────────────────────
# 4. TMPFS FOR SCRATCH (RAM-BACKED /tmp/.claude)
# ─────────────────────────────────────────────────────────────────────────────
setup_tmpfs_scratch() {
    log "Setting up RAM-backed scratch directory..."

    SCRATCH_DIR="/tmp/.claude-scratch"

    # Create mount script that runs on boot
    MOUNT_SCRIPT="/etc/profile.d/claude-scratch.sh"

    sudo tee "$MOUNT_SCRIPT" > /dev/null << 'EOF'
# Mount tmpfs scratch for Claude Code if not already mounted
SCRATCH="/tmp/.claude-scratch"
if [[ ! -d "$SCRATCH" ]] || ! mountpoint -q "$SCRATCH" 2>/dev/null; then
    sudo mkdir -p "$SCRATCH"
    sudo mount -t tmpfs -o size=2G,mode=1777 tmpfs "$SCRATCH" 2>/dev/null || true
fi
EOF

    sudo chmod +x "$MOUNT_SCRIPT"

    # Mount now
    if [[ ! -d "$SCRATCH_DIR" ]]; then
        sudo mkdir -p "$SCRATCH_DIR"
    fi

    if ! mountpoint -q "$SCRATCH_DIR" 2>/dev/null; then
        sudo mount -t tmpfs -o size=2G,mode=1777 tmpfs "$SCRATCH_DIR"
        log "Mounted 2GB tmpfs at $SCRATCH_DIR"
    else
        log "Tmpfs already mounted at $SCRATCH_DIR"
    fi

    # Symlink from ~/.claude/tmp if desired
    if [[ ! -L "$HOME/.claude/tmp" ]]; then
        warn "Consider: ln -sf $SCRATCH_DIR $HOME/.claude/tmp"
    fi
}

# ─────────────────────────────────────────────────────────────────────────────
# 5. GIT OPTIMIZATIONS
# ─────────────────────────────────────────────────────────────────────────────
optimize_git() {
    log "Configuring Git optimizations..."

    # Multi-pack index for faster operations
    git config --global feature.manyFiles true

    # Faster status
    git config --global core.untrackedCache true
    git config --global core.fsmonitor true

    # Parallel operations
    git config --global pack.threads 0
    git config --global index.threads true

    # Compression (balance speed vs size)
    git config --global core.compression 1

    # Credential caching
    git config --global credential.helper 'cache --timeout=86400'

    log "Git optimizations applied"
}

# ─────────────────────────────────────────────────────────────────────────────
# 6. NODE/NPM OPTIMIZATIONS
# ─────────────────────────────────────────────────────────────────────────────
optimize_node() {
    if command -v node &> /dev/null; then
        log "Configuring Node.js optimizations..."

        # Increase memory for Node
        grep -q "NODE_OPTIONS" "$HOME/.bashrc" || {
            echo '' >> "$HOME/.bashrc"
            echo '# Node.js memory optimization' >> "$HOME/.bashrc"
            echo 'export NODE_OPTIONS="--max-old-space-size=4096"' >> "$HOME/.bashrc"
        }

        # npm cache settings
        npm config set cache "$HOME/.npm-cache" 2>/dev/null || true
        npm config set prefer-offline true 2>/dev/null || true

        log "Node.js optimizations applied"
    else
        warn "Node.js not found, skipping Node optimizations"
    fi
}

# ─────────────────────────────────────────────────────────────────────────────
# 7. PYTHON OPTIMIZATIONS
# ─────────────────────────────────────────────────────────────────────────────
optimize_python() {
    log "Configuring Python optimizations..."

    # Add Python optimizations to shell
    grep -q "PYTHONDONTWRITEBYTECODE" "$HOME/.bashrc" || {
        echo '' >> "$HOME/.bashrc"
        echo '# Python optimizations' >> "$HOME/.bashrc"
        echo '# Disable .pyc files (faster for development)' >> "$HOME/.bashrc"
        echo 'export PYTHONDONTWRITEBYTECODE=1' >> "$HOME/.bashrc"
        echo '# Enable hash randomization (security)' >> "$HOME/.bashrc"
        echo 'export PYTHONHASHSEED=random' >> "$HOME/.bashrc"
    }

    log "Python optimizations applied"
}

# ─────────────────────────────────────────────────────────────────────────────
# 8. GENERATE WINDOWS-SIDE .wslconfig RECOMMENDATIONS
# ─────────────────────────────────────────────────────────────────────────────
suggest_wslconfig() {
    log "Checking .wslconfig..."

    WSLCONFIG="/mnt/c/Users/Blake/.wslconfig"

    echo ""
    echo "Current .wslconfig:"
    echo "─────────────────────"
    cat "$WSLCONFIG" 2>/dev/null || echo "(not found)"
    echo "─────────────────────"
    echo ""

    echo "Recommended .wslconfig additions:"
    cat << 'EOF'
[wsl2]
memory=36GB
processors=16
swap=8GB
networkingMode=mirrored
localhostForwarding=true

[experimental]
autoMemoryReclaim=gradual
sparseVhd=true
hostAddressLoopback=true
EOF
    echo ""
    warn "Edit manually at: C:\\Users\\Blake\\.wslconfig"
    warn "Then run: wsl --shutdown (from PowerShell)"
}

# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────
main() {
    echo "╔═══════════════════════════════════════════════════════════════╗"
    echo "║     WSL2 Optimization for Claude Code Performance            ║"
    echo "╚═══════════════════════════════════════════════════════════════╝"
    echo ""

    case "${1:-all}" in
        sysctl)
            configure_sysctl
            ;;
        limits)
            configure_limits
            ;;
        shell)
            optimize_bashrc
            ;;
        tmpfs)
            setup_tmpfs_scratch
            ;;
        git)
            optimize_git
            ;;
        node)
            optimize_node
            ;;
        python)
            optimize_python
            ;;
        wslconfig)
            suggest_wslconfig
            ;;
        all)
            configure_sysctl
            configure_limits
            optimize_bashrc
            setup_tmpfs_scratch
            optimize_git
            optimize_node
            optimize_python
            echo ""
            suggest_wslconfig
            ;;
        status)
            echo "Current sysctl values:"
            sysctl vm.swappiness vm.vfs_cache_pressure fs.inotify.max_user_watches
            echo ""
            echo "Memory:"
            free -h
            echo ""
            echo "Tmpfs mounts:"
            mount | grep tmpfs | grep -v "cgroup\|sys\|run"
            ;;
        *)
            echo "Usage: $0 [sysctl|limits|shell|tmpfs|git|node|python|wslconfig|status|all]"
            exit 1
            ;;
    esac

    echo ""
    log "Done! Some changes require re-login or WSL restart."
}

main "$@"
