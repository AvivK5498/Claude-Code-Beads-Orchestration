#!/bin/bash
#
# PreToolUse:Task - Soft reminder to set bead status before dispatch
#

INPUT=$(cat)
PROMPT=$(echo "$INPUT" | jq -r '.tool_input.prompt // empty')

# Only remind if dispatching a bead task (prompt contains BEAD_ID)
if [[ "$PROMPT" == *"BEAD_ID:"* ]]; then
  ACTIVE_STATUS="${BEADS_ACTIVE_STATUS:-in_progress}"
  echo "IMPORTANT: Before dispatching, ensure bead is active: bd update {BEAD_ID} --status ${ACTIVE_STATUS}"
fi

exit 0
