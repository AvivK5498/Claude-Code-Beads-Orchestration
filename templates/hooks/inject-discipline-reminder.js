#!/usr/bin/env node
'use strict';

// PreToolUse: Inject discipline skill reminder for supervisor dispatches

const { readStdinJSON, getField, injectText, runHook } = require('./hook-utils');

runHook('inject-discipline-reminder', () => {
  const input = readStdinJSON();
  const toolName = getField(input, 'tool_name');

  if (toolName !== 'Task') process.exit(0);

  const subagentType = getField(input, 'tool_input.subagent_type');

  if (subagentType.includes('-supervisor')) {
    injectText(`<system-reminder>
SUPERVISOR DISPATCH: Before implementing, invoke \`/subagents-discipline\` skill.
This ensures verification-first development with DEMO blocks.
</system-reminder>
`);
  }
});
