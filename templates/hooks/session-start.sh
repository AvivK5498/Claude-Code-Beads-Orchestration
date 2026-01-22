#!/bin/bash
#
# SessionStart: Show full task context for orchestrator
#

BEADS_DIR="$CLAUDE_PROJECT_DIR/.beads"

if [[ ! -d "$BEADS_DIR" ]]; then
  echo "No .beads directory found. Run 'bd init' to initialize."
  exit 0
fi

# Check if bd is available
if ! command -v bd &>/dev/null; then
  echo "beads CLI (bd) not found. Install from: https://github.com/steveyegge/beads"
  exit 0
fi

echo ""
echo "## Task Status"
echo ""

# Show in-progress beads first (highest priority)
IN_PROGRESS=$(bd list --status in_progress 2>/dev/null | head -5)
if [[ -n "$IN_PROGRESS" ]]; then
  echo "### In Progress (resume these):"
  echo "$IN_PROGRESS"
  echo ""
fi

# Show ready (unblocked) beads
READY=$(bd ready 2>/dev/null | head -5)
if [[ -n "$READY" ]]; then
  echo "### Ready (no blockers):"
  echo "$READY"
  echo ""
fi

# Show blocked beads
BLOCKED=$(bd blocked 2>/dev/null | head -3)
if [[ -n "$BLOCKED" ]]; then
  echo "### Blocked:"
  echo "$BLOCKED"
  echo ""
fi

# Show stale beads (no activity in 3 days)
STALE=$(bd stale --days 3 2>/dev/null | head -3)
if [[ -n "$STALE" ]]; then
  echo "### Stale (no activity in 3 days):"
  echo "$STALE"
  echo ""
fi

# If nothing found
if [[ -z "$IN_PROGRESS" && -z "$READY" && -z "$BLOCKED" && -z "$STALE" ]]; then
  echo "No active beads. Create one with: bd create \"Task title\" -d \"Description\""
fi

echo ""
