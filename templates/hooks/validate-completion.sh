#!/bin/bash
#
# SubagentStop: Enforce bead lifecycle - work verification
#

INPUT=$(cat)
AGENT_TRANSCRIPT=$(echo "$INPUT" | jq -r '.agent_transcript_path // empty')
MAIN_TRANSCRIPT=$(echo "$INPUT" | jq -r '.transcript_path // empty')
AGENT_ID=$(echo "$INPUT" | jq -r '.agent_id // empty')

normalize_status() {
  local value="$1"
  value="${value//-/_}"
  echo "$value" | tr '[:upper:]' '[:lower:]' | xargs
}

status_in_csv() {
  local status
  status="$(normalize_status "$1")"
  local csv="$2"
  IFS=',' read -ra items <<< "$csv"
  for item in "${items[@]}"; do
    if [[ -n "$(normalize_status "$item")" && "$status" == "$(normalize_status "$item")" ]]; then
      return 0
    fi
  done
  return 1
}

[[ -z "$AGENT_TRANSCRIPT" || ! -f "$AGENT_TRANSCRIPT" ]] && echo '{"decision":"approve"}' && exit 0

# Extract last assistant text response
LAST_RESPONSE=$(tail -200 "$AGENT_TRANSCRIPT" | jq -rs '
  [.[] | select(.message?.role == "assistant" and .message?.content != null)
   | .message.content[] | select(.text != null) | .text] | last // ""
' 2>/dev/null || echo "")

# === LAYER 1: Extract subagent_type from transcript (fail open) ===
SUBAGENT_TYPE=""
if [[ -n "$AGENT_ID" && -n "$MAIN_TRANSCRIPT" && -f "$MAIN_TRANSCRIPT" ]]; then
  PARENT_TOOL_USE_ID=$(grep "\"agentId\":\"$AGENT_ID\"" "$MAIN_TRANSCRIPT" 2>/dev/null | head -1 | jq -r '.parentToolUseID // empty' 2>/dev/null)
  if [[ -n "$PARENT_TOOL_USE_ID" ]]; then
    SUBAGENT_TYPE=$(grep "\"id\":\"$PARENT_TOOL_USE_ID\"" "$MAIN_TRANSCRIPT" 2>/dev/null | \
      grep '"name":"Task"' | \
      jq -r '.message.content[]? | select(.type == "tool_use" and .id == "'"$PARENT_TOOL_USE_ID"'") | .input.subagent_type // empty' 2>/dev/null | \
      head -1)
  fi
fi

# === LAYER 2: Check completion format (backup detection) ===
HAS_BEAD_COMPLETE=$(echo "$LAST_RESPONSE" | grep -cE "BEAD.*COMPLETE" 2>/dev/null || true)
HAS_WORKTREE_OR_BRANCH=$(echo "$LAST_RESPONSE" | grep -cE "(Worktree:|Branch:).*bd-" 2>/dev/null || true)
[[ -z "$HAS_BEAD_COMPLETE" ]] && HAS_BEAD_COMPLETE=0
[[ -z "$HAS_WORKTREE_OR_BRANCH" ]] && HAS_WORKTREE_OR_BRANCH=0

# Determine if this is a supervisor (Layer 1) or has completion format (Layer 2)
IS_SUPERVISOR="false"
[[ "$SUBAGENT_TYPE" == *"supervisor"* ]] && IS_SUPERVISOR="true"

NEEDS_VERIFICATION="false"
[[ "$IS_SUPERVISOR" == "true" ]] && NEEDS_VERIFICATION="true"
[[ "$HAS_BEAD_COMPLETE" -ge 1 && "$HAS_WORKTREE_OR_BRANCH" -ge 1 ]] && NEEDS_VERIFICATION="true"

# Skip verification if not needed
[[ "$NEEDS_VERIFICATION" == "false" ]] && echo '{"decision":"approve"}' && exit 0

# Worker supervisor is exempt
[[ "$SUBAGENT_TYPE" == *"worker"* ]] && echo '{"decision":"approve"}' && exit 0

# === VERIFICATION CHECKS ===

# Check 1: Completion format required for supervisors
if [[ "$IS_SUPERVISOR" == "true" ]] && [[ "$HAS_BEAD_COMPLETE" -lt 1 || "$HAS_WORKTREE_OR_BRANCH" -lt 1 ]]; then
  cat << 'EOF'
{"decision":"block","reason":"Work verification failed: completion report missing.\n\nRequired format:\nBEAD {BEAD_ID} COMPLETE\nWorktree: .worktrees/bd-{BEAD_ID}\nFiles: [list]\nTests: pass\nSummary: [1 sentence]"}
EOF
  exit 0
fi

# Extract BEAD_ID from response
BEAD_ID_FROM_RESPONSE=$(echo "$LAST_RESPONSE" | grep -oE "BEAD [A-Za-z0-9._-]+" | head -1 | awk '{print $2}')
IS_EPIC_CHILD="false"
[[ "$BEAD_ID_FROM_RESPONSE" == *"."* ]] && IS_EPIC_CHILD="true"

# Check 2: Comment required
HAS_COMMENT=$(grep -c '"bd comment\|"command":"bd comment' "$AGENT_TRANSCRIPT" 2>/dev/null) || HAS_COMMENT=0
if [[ "$HAS_COMMENT" -lt 1 ]]; then
  cat << 'EOF'
{"decision":"block","reason":"Work verification failed: no comment on bead.\n\nRun: bd comment {BEAD_ID} \"Completed: [summary]\""}
EOF
  exit 0
fi

# Check 3: Worktree verification
REPO_ROOT=$(cd "$(git rev-parse --git-common-dir)/.." 2>/dev/null && pwd)
WORKTREE_PATH="$REPO_ROOT/.worktrees/bd-${BEAD_ID_FROM_RESPONSE}"

if [[ ! -d "$WORKTREE_PATH" ]]; then
  cat << 'EOF'
{"decision":"block","reason":"Work verification failed: worktree not found.\n\nCreate worktree first via API."}
EOF
  exit 0
fi

# Check 4: Uncommitted changes
UNCOMMITTED=$(git -C "$WORKTREE_PATH" status --porcelain 2>/dev/null)
if [[ -n "$UNCOMMITTED" ]]; then
  cat << 'EOF'
{"decision":"block","reason":"Work verification failed: uncommitted changes.\n\nRun in worktree:\n  git add -A && git commit -m \"...\""}
EOF
  exit 0
fi

# Check 5: Remote push
HAS_REMOTE=$(git -C "$WORKTREE_PATH" remote get-url origin 2>/dev/null)
if [[ -n "$HAS_REMOTE" ]]; then
  BRANCH="bd-${BEAD_ID_FROM_RESPONSE}"
  REMOTE_EXISTS=$(git -C "$WORKTREE_PATH" ls-remote --heads origin "$BRANCH" 2>/dev/null)
  if [[ -z "$REMOTE_EXISTS" ]]; then
    cat << 'EOF'
{"decision":"block","reason":"Work verification failed: branch not pushed.\n\nRun: git push -u origin bd-{BEAD_ID}"}
EOF
    exit 0
  fi
fi

# Check 6: Bead status
BEAD_STATUS=$(bd show "$BEAD_ID_FROM_RESPONSE" --json 2>/dev/null | jq -r '.[0].status // "unknown"')
EXPECTED_STATUSES="${BEADS_REVIEW_STATUSES:-${BEADS_REVIEW_STATUS:-inreview}}"
# Configure via BEADS_REVIEW_STATUS or BEADS_REVIEW_STATUSES.
if ! status_in_csv "$BEAD_STATUS" "$EXPECTED_STATUSES"; then
  cat << EOF
{"decision":"block","reason":"Work verification failed: bead status is '${BEAD_STATUS}'.\n\nExpected one of: ${EXPECTED_STATUSES}\nRun: bd update ${BEAD_ID_FROM_RESPONSE} --status <review-status>"}
EOF
  exit 0
fi

# Check 7: Verbosity limit
DECODED_RESPONSE=$(printf '%b' "$LAST_RESPONSE")
LINE_COUNT=$(echo "$DECODED_RESPONSE" | wc -l | tr -d ' ')
CHAR_COUNT=${#DECODED_RESPONSE}

if [[ "$LINE_COUNT" -gt 15 ]] || [[ "$CHAR_COUNT" -gt 800 ]]; then
  cat << EOF
{"decision":"block","reason":"Work verification failed: response too verbose (${LINE_COUNT} lines, ${CHAR_COUNT} chars). Max: 15 lines, 800 chars."}
EOF
  exit 0
fi

echo '{"decision":"approve"}'
