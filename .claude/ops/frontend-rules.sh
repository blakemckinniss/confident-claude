#!/bin/bash
# Activate/deactivate frontend rules for current project
# Usage: frontend-rules [on|off|status]

FRONTEND_DIR="$HOME/.claude/rules/frontend"
PROJECT_RULES=".claude/rules"

case "${1:-status}" in
  on)
    mkdir -p "$PROJECT_RULES"
    for f in "$FRONTEND_DIR"/*.md; do
      [ -f "$f" ] && ln -sf "$f" "$PROJECT_RULES/$(basename "$f")" && echo "✓ Linked $(basename "$f")"
    done
    ;;
  off)
    for f in "$FRONTEND_DIR"/*.md; do
      target="$PROJECT_RULES/$(basename "$f")"
      [ -L "$target" ] && rm "$target" && echo "✓ Removed $(basename "$f")"
    done
    ;;
  status)
    echo "Frontend rules in $FRONTEND_DIR:"
    ls -1 "$FRONTEND_DIR"/*.md 2>/dev/null | xargs -I{} basename {}
    echo ""
    echo "Active in project:"
    ls -la "$PROJECT_RULES"/*.md 2>/dev/null | grep -E "(react|nextjs|shadcn|tailwind)" || echo "  (none)"
    ;;
  *) echo "Usage: frontend-rules [on|off|status]" ;;
esac
