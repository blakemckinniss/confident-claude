#!/bin/bash
# Claude Code Wrapper Script
# This script wraps the claude command, allowing pre-launch customization.
#
# Usage: claude-wrapper.sh claude [args...]
#
# Customize the DEFAULT_DIR below or add any pre-launch commands.

# ============================================================
# CONFIGURATION
# ============================================================

# Optional: Set a default directory if not already in a project
# Leave empty to use the current directory
DEFAULT_DIR=""

# Optional: Run any setup commands before launching claude
# Example: source ~/.secrets/claude-env.sh
# Example: aws sso login --profile my-profile

# ============================================================
# WRAPPER LOGIC (usually no need to edit below)
# ============================================================

# Change to default directory if set and current dir is home
if [[ -n "$DEFAULT_DIR" && "$PWD" == "$HOME" ]]; then
    if [[ -d "$DEFAULT_DIR" ]]; then
        cd "$DEFAULT_DIR"
    else
        echo "Warning: DEFAULT_DIR ($DEFAULT_DIR) does not exist, using current directory"
    fi
fi

# Execute the command passed to us (typically 'claude' with args)
exec "$@"
