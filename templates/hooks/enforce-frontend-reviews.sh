#!/bin/bash
#
# SubagentStop: Enforce frontend reviews (RAMS + Web Interface Guidelines)
#
# Frontend supervisors listed in .claude/frontend-supervisors.txt must run:
#   1. /rams - Accessibility review
#   2. /web-interface-guidelines - Vercel Web Interface Guidelines compliance
#
# Discovery agent populates the config file.
#

INPUT=$(cat)
AGENT_TRANSCRIPT=$(echo "$INPUT" | jq -r '.agent_transcript_path // empty')
PARENT_TRANSCRIPT=$(echo "$INPUT" | jq -r '.transcript_path // empty')
AGENT_ID=$(echo "$INPUT" | jq -r '.agent_id // empty')
CWD=$(echo "$INPUT" | jq -r '.cwd // empty')

[[ -z "$AGENT_TRANSCRIPT" || ! -f "$AGENT_TRANSCRIPT" ]] && echo '{"decision":"approve"}' && exit 0
[[ -z "$PARENT_TRANSCRIPT" || ! -f "$PARENT_TRANSCRIPT" ]] && echo '{"decision":"approve"}' && exit 0

# Extract subagent_type from parent transcript by finding the Task invocation for this agent
AGENT_TYPE=$(grep -B50 "\"agentId\":\"$AGENT_ID\"" "$PARENT_TRANSCRIPT" | grep -o '"subagent_type":"[^"]*"' | tail -1 | sed 's/"subagent_type":"//;s/"//')

# Check if this supervisor requires frontend reviews (listed in config file)
CONFIG_FILE="${CWD}/.claude/frontend-supervisors.txt"
if [[ ! -f "$CONFIG_FILE" ]]; then
  echo '{"decision":"approve"}'
  exit 0
fi

# Check if agent type is in the frontend supervisors list
if ! grep -qx "$AGENT_TYPE" "$CONFIG_FILE" 2>/dev/null; then
  echo '{"decision":"approve"}'
  exit 0
fi

# Check for required skill invocations
MISSING=""

# Check for RAMS skill invocation
if ! grep '"name":"Skill"' "$AGENT_TRANSCRIPT" 2>/dev/null | grep -q '"skill":"rams"'; then
  MISSING="${MISSING}rams, "
fi

# Check for web-interface-guidelines skill invocation
if ! grep '"name":"Skill"' "$AGENT_TRANSCRIPT" 2>/dev/null | grep -q '"skill":"web-interface-guidelines"'; then
  MISSING="${MISSING}web-interface-guidelines, "
fi

# If any skills are missing, block
if [[ -n "$MISSING" ]]; then
  # Remove trailing comma and space
  MISSING="${MISSING%, }"
  cat << EOF
{"decision":"block","reason":"Frontend supervisor completing without required reviews.\\n\\nMissing: ${MISSING}\\n\\nYou MUST run BOTH skills before completing:\\n  1. Skill(skill=\\"rams\\", args=\\"path/to/component.tsx\\")\\n  2. Skill(skill=\\"web-interface-guidelines\\")\\n\\nThe hook checks for actual Skill tool invocations, not text output."}
EOF
  exit 0
fi

# Check for bead comment with review results
# Look for bd comment (or bd comments add) containing RAMS info
HAS_REVIEW_COMMENT=0

# Check for Bash tool invocation with bd comment containing RAMS
if grep '"name":"Bash"' "$AGENT_TRANSCRIPT" 2>/dev/null | grep -qiE 'bd comment.*rams|bd comments add.*rams'; then
  HAS_REVIEW_COMMENT=1
fi

if [[ "$HAS_REVIEW_COMMENT" -eq 0 ]]; then
  cat << 'EOF'
{"decision":"block","reason":"Frontend supervisor must document review results on the bead.\n\nAfter running reviews, add a bead comment with RAMS score:\n\n  bd comment {BEAD_ID} \"RAMS: 95/100, WIG: passed\"\n\nThis creates an audit trail and confirms you acted on review results."}
EOF
  exit 0
fi

echo '{"decision":"approve"}'
