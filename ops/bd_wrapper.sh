#!/usr/bin/env bash
# bd_wrapper.sh - Automatic project-scoped beads
# Detects project from $PWD and auto-injects --label project:<name>

set -euo pipefail

# Find project root by looking for markers
find_project() {
    local dir="$PWD"
    while [[ "$dir" != "/" ]]; do
        # Check for project markers
        if [[ -f "$dir/CLAUDE.md" ]] || [[ -d "$dir/.beads" ]] || [[ -f "$dir/package.json" ]] || [[ -f "$dir/Cargo.toml" ]] || [[ -f "$dir/pyproject.toml" ]]; then
            basename "$dir"
            return 0
        fi
        dir="$(dirname "$dir")"
    done
    echo ""  # No project found
    return 1
}

# Get project name (cached for performance)
get_project() {
    if [[ -n "${BD_PROJECT:-}" ]]; then
        echo "$BD_PROJECT"
        return 0
    fi
    find_project
}

# Commands that should auto-filter by project
FILTER_COMMANDS="list|ready|blocked|count|stats"

# Commands that should auto-label on create
CREATE_COMMANDS="create"

PROJECT=$(get_project || echo "")

# If no project detected or --global flag, pass through directly
if [[ -z "$PROJECT" ]] || [[ " $* " == *" --global "* ]]; then
    # Remove --global flag if present and pass through
    exec /home/jinx/.local/bin/bd "${@//--global/}"
fi

# Parse command (first non-flag argument)
CMD=""
for arg in "$@"; do
    if [[ ! "$arg" =~ ^- ]]; then
        CMD="$arg"
        break
    fi
done

# Check if already has project label (don't double-add)
if [[ " $* " == *"project:$PROJECT"* ]] || [[ " $* " == *"project:"* ]]; then
    exec /home/jinx/.local/bin/bd "$@"
fi

# Auto-inject project scope
case "$CMD" in
    list|ready|blocked|count)
        # Auto-filter to current project
        exec /home/jinx/.local/bin/bd "$@" --label "project:$PROJECT"
        ;;
    create)
        # Auto-label new issues with project
        exec /home/jinx/.local/bin/bd "$@" --label "project:$PROJECT"
        ;;
    *)
        # Pass through unchanged
        exec /home/jinx/.local/bin/bd "$@"
        ;;
esac
