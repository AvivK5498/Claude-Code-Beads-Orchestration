#!/bin/bash
#
# PreToolUse: Block Edit/Write on main branch outside worktrees
#
# Supervisors must work in .worktrees/bd-{BEAD_ID}/ directories, not main.
# This prevents accidental commits to main directory.
#

INPUT=$(cat)
TOOL_NAME=$(echo "$INPUT" | jq -r '.tool_name // empty')

# Only check Edit and Write tools
[[ "$TOOL_NAME" != "Edit" ]] && [[ "$TOOL_NAME" != "Write" ]] && exit 0

# Get the file path being edited
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')

# Allow Plan mode files (outside repo)
if [[ "$FILE_PATH" == *"/.claude/plans/"* ]]; then
  exit 0
fi

# Allow if editing within .worktrees/ directory
if [[ "$FILE_PATH" == *"/.worktrees/"* ]] || [[ "$FILE_PATH" == *"\.worktrees\"* ]]; then
  exit 0
fi

# Get current working directory
CWD=$(pwd)

# Allow if currently inside a .worktrees/ directory
if [[ "$CWD" == *"/.worktrees/"* ]] || [[ "$CWD" == *"\.worktrees\"* ]]; then
  exit 0
fi

# Check current branch (if we're in a git repo outside worktrees)
CURRENT_BRANCH=$(git branch --show-current 2>/dev/null)

# Block if on main or master (and not in a worktree)
if [[ "$CURRENT_BRANCH" == "main" ]] || [[ "$CURRENT_BRANCH" == "master" ]]; then
  cat << EOF
{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"Cannot edit files on $CURRENT_BRANCH branch. Supervisors must work in worktrees.

Create a worktree first using the API:
  POST /api/git/worktree { repo_path, bead_id }

Then cd into .worktrees/bd-{BEAD_ID}/ to make changes."}}
EOF
  exit 0
fi

exit 0
