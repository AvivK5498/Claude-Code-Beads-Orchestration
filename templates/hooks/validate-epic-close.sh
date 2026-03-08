#!/bin/bash
# Hook: Validate bead close — PR must be merged, epic children must be complete
# Prevents closing a bead whose branch has no merged PR
# Prevents closing an epic when children are still open

set -euo pipefail

TOOL_INPUT="${CLAUDE_TOOL_INPUT:-}"
COMPLETE_STATUSES="${BEADS_COMPLETE_STATUSES:-done,closed}"

# Only check Bash commands containing "bd close"
if ! echo "$TOOL_INPUT" | jq -e '.command' >/dev/null 2>&1; then
  exit 0
fi

COMMAND=$(echo "$TOOL_INPUT" | jq -r '.command // ""')

# Check if this is a bd close command
if ! echo "$COMMAND" | grep -qE 'bd\s+close'; then
  exit 0
fi

# Allow --force override
if echo "$COMMAND" | grep -qE '\-\-force'; then
  exit 0
fi

# Extract the ID being closed (handles: bd close ID, bd close ID && ..., etc.)
CLOSE_ID=$(echo "$COMMAND" | sed -E 's/.*bd[[:space:]]+close[[:space:]]+([A-Za-z0-9._-]+).*/\1/')

if [ -z "$CLOSE_ID" ]; then
  exit 0
fi

# === CHECK 1: PR merge validation ===
# Only applies if repo has a remote and branch exists
BRANCH="bd-${CLOSE_ID}"

HAS_REMOTE=$(git remote get-url origin 2>/dev/null || echo "")
if [ -n "$HAS_REMOTE" ]; then
  REMOTE_BRANCH=$(git ls-remote --heads origin "$BRANCH" 2>/dev/null || echo "")

  if [ -n "$REMOTE_BRANCH" ]; then
    # Branch exists on remote — check for merged PR
    if command -v gh >/dev/null 2>&1; then
      MERGED_PR=$(gh pr list --head "$BRANCH" --state merged --json number --jq '.[0].number' 2>/dev/null || echo "")

      if [ -z "$MERGED_PR" ]; then
        cat << EOF
{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"Cannot close bead '$CLOSE_ID' — branch '$BRANCH' has no merged PR. Create and merge a PR first, or use 'bd close $CLOSE_ID --force' to override."}}
EOF
        exit 0
      fi
    fi
  fi
fi

# === CHECK 2: Epic children validation ===
# Check if this is an epic by looking at issue_type
ISSUE_TYPE=$(bd show "$CLOSE_ID" --json 2>/dev/null | jq -r '.[0].issue_type // ""' 2>/dev/null || echo "")

if [ "$ISSUE_TYPE" != "epic" ]; then
  # Not an epic, allow close
  exit 0
fi

# This is an epic - check if all children are complete
INCOMPLETE=$(bd list --json 2>/dev/null | jq -r --arg epic "$CLOSE_ID" --arg statuses "$COMPLETE_STATUSES" '
  def normalize: ascii_downcase | gsub("-"; "_");
  def in_statuses($csv):
    (normalize) as $s
    | ($csv | split(",") | map(gsub("^\\s+|\\s+$"; "") | normalize))
    | index($s) != null;
  [.[] | select((.id | startswith($epic + ".")) and ((.status // "") | in_statuses($statuses) | not))] | length
' 2>/dev/null || echo "0")

if [ "$INCOMPLETE" != "0" ] && [ "$INCOMPLETE" != "" ]; then
  # Get list of incomplete children for the error message
  INCOMPLETE_LIST=$(bd list --json 2>/dev/null | jq -r --arg epic "$CLOSE_ID" --arg statuses "$COMPLETE_STATUSES" '
    def normalize: ascii_downcase | gsub("-"; "_");
    def in_statuses($csv):
      (normalize) as $s
      | ($csv | split(",") | map(gsub("^\\s+|\\s+$"; "") | normalize))
      | index($s) != null;
    [.[] | select((.id | startswith($epic + ".")) and ((.status // "") | in_statuses($statuses) | not))] | .[] | "\(.id) (\(.status))"
  ' 2>/dev/null | tr '\n' ', ' | sed 's/,$//')

  cat << EOF
{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"Cannot close epic '$CLOSE_ID' - has $INCOMPLETE incomplete children: $INCOMPLETE_LIST. Mark all children as complete first (allowed: $COMPLETE_STATUSES)."}}
EOF
  exit 0
fi

# All checks passed, allow close
exit 0
