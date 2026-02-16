#!/usr/bin/env node
'use strict';

// PostToolUse: Enforce concise responses from subagents

const { readStdinJSON, getField, runHook } = require('./hook-utils');

runHook('enforce-concise-response', () => {
const input = readStdinJSON();
const toolName = getField(input, 'tool_name');

if (toolName !== 'Task') process.exit(0);

const response = getField(input, 'tool_result');
if (!response) process.exit(0);

const lineCount = response.split('\n').length;
const charCount = response.length;
const MAX_LINES = 10;
const MAX_CHARS = 500;

if (lineCount > MAX_LINES || charCount > MAX_CHARS) {
  const out = {
    hookSpecificOutput: {
      hookEventName: 'PostToolUse',
      warning: `Subagent response exceeded limits (${lineCount} lines, ${charCount} chars). Target: ${MAX_LINES} lines, ${MAX_CHARS} chars. Consider asking agents for more concise reports.`,
    },
  };
  process.stdout.write(JSON.stringify(out));
}
});
