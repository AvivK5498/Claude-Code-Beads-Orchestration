#!/usr/bin/env node
'use strict';

// PreToolUse:Task — Enforce bead exists before supervisor dispatch

const { readStdinJSON, getField, deny, runHook } = require('./hook-utils');

runHook('enforce-bead-for-supervisor', () => {
  const input = readStdinJSON();
  const toolName = getField(input, 'tool_name');

  if (toolName !== 'Task') process.exit(0);

  const subagentType = getField(input, 'tool_input.subagent_type');
  const prompt = getField(input, 'tool_input.prompt');

  // Only enforce for supervisors
  if (!subagentType.includes('supervisor')) process.exit(0);

  // Exception: merge-supervisor is exempt
  if (subagentType === 'merge-supervisor') process.exit(0);

  // Check for BEAD_ID in prompt
  if (!prompt.includes('BEAD_ID:')) {
    deny(
    '<bead-required>\n' +
    'All supervisor work MUST be tracked with a bead.\n\n' +
    '<action>\n' +
    'For standalone tasks:\n' +
    '  1. bd create "Task title" -d "Description"\n' +
    '  2. Dispatch with: BEAD_ID: {id}\n\n' +
    'For epic children:\n' +
    '  1. bd create "Epic" -d "..." --type epic\n' +
    '  2. bd create "Child" -d "..." --parent {EPIC_ID}\n' +
    '  3. Dispatch with: BEAD_ID: {child_id}, EPIC_ID: {epic_id}\n' +
    '</action>\n\n' +
    'Each task creates its own worktree at .worktrees/bd-{BEAD_ID}/\n' +
    '</bead-required>'
    );
  }
});
