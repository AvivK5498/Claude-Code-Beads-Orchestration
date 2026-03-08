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

# ============================================================
# Dirty Parent Check - Warn if main directory has uncommitted changes
# ============================================================
REPO_ROOT=$(git -C "$CLAUDE_PROJECT_DIR" rev-parse --show-toplevel 2>/dev/null)
if [[ -n "$REPO_ROOT" ]]; then
  DIRTY=$(git -C "$REPO_ROOT" status --porcelain 2>/dev/null)
  if [[ -n "$DIRTY" ]]; then
    echo "⚠️  WARNING: Main directory has uncommitted changes."
    echo "   Agents should only work in .worktrees/"
    echo ""
  fi
fi

# ============================================================
# Auto-cleanup: Detect merged PRs and cleanup worktrees
# ============================================================
WORKTREES_DIR="$CLAUDE_PROJECT_DIR/.worktrees"
if [[ -d "$WORKTREES_DIR" ]]; then
  for worktree in $(git -C "$REPO_ROOT" worktree list --porcelain 2>/dev/null | grep "^worktree.*\.worktrees/bd-" | awk '{print $2}'); do
    BEAD_ID=$(basename "$worktree" | sed 's/bd-//')
    BRANCH=$(basename "$worktree")
    
    # Check if branch was merged to main
    if git -C "$REPO_ROOT" branch --merged main 2>/dev/null | grep -q "$BRANCH"; then
      echo "✓ $BRANCH was merged - consider cleaning up"
      echo "   Run: git worktree remove \"$worktree\" && bd close \"$BEAD_ID\""
      echo ""
    fi
  done
fi

# ============================================================
# Open PR Reminder
# ============================================================
if command -v gh &>/dev/null; then
  OPEN_PRS=$(gh pr list --author "@me" --state open --json number,title,headRefName 2>/dev/null)
  if [[ -n "$OPEN_PRS" && "$OPEN_PRS" != "[]" ]]; then
    echo "📋 You have open PRs:"
    echo "$OPEN_PRS" | jq -r '.[] | "  #\(.number) \(.title) (\(.headRefName))"' 2>/dev/null
    echo ""
  fi
fi

echo ""
echo "## Task Status"
echo ""

# Show active beads first (highest priority).
# Configure with BEADS_ACTIVE_STATUSES (comma-separated) or BEADS_ACTIVE_STATUS (single).
ACTIVE_STATUSES="${BEADS_ACTIVE_STATUSES:-${BEADS_ACTIVE_STATUS:-in_progress}}"
ACTIVE_ITEMS=""
IFS=',' read -ra ACTIVE_STATUS_LIST <<< "$ACTIVE_STATUSES"
for STATUS in "${ACTIVE_STATUS_LIST[@]}"; do
  CLEAN_STATUS=$(echo "$STATUS" | xargs)
  [[ -z "$CLEAN_STATUS" ]] && continue
  MATCHES=$(bd list --status "$CLEAN_STATUS" 2>/dev/null | head -5)
  [[ -n "$MATCHES" ]] && ACTIVE_ITEMS+="${MATCHES}"$'\n'
done
IN_PROGRESS=$(echo "$ACTIVE_ITEMS" | awk 'NF && !seen[$0]++' | head -5)
if [[ -n "$IN_PROGRESS" ]]; then
  echo "### Active (resume these):"
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

# ============================================================
# Knowledge Base - Surface recent learnings
# ============================================================
KNOWLEDGE_FILE="$BEADS_DIR/memory/knowledge.jsonl"
if [[ -f "$KNOWLEDGE_FILE" && -s "$KNOWLEDGE_FILE" ]]; then
  TOTAL_ENTRIES=$(wc -l < "$KNOWLEDGE_FILE" | tr -d ' ')
  echo ""
  echo "## Recent Knowledge ($TOTAL_ENTRIES entries)"
  echo ""
  # Show 5 most recent, deduplicated by key (latest wins)
  tail -20 "$KNOWLEDGE_FILE" | jq -s '
    group_by(.key) | map(max_by(.ts)) | sort_by(-.ts) | .[0:5] | .[] |
    "  [\(.type | ascii_upcase | .[0:5])] \(.content | .[0:100])  (\(.source))"
  ' -r 2>/dev/null
  echo ""
  echo "  Search: .beads/memory/recall.sh \"keyword\""
fi

echo ""
