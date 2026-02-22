#!/usr/bin/env node
'use strict';

// PostToolUse: Task — Concise response check + dispatch prompt logging (single spawn)
// Consolidated from: enforce-concise-response + log-dispatch-prompt

const {
  readStdinJSON, getField, parseBeadId, execCommand, runHook,
} = require('./hook-utils.cjs');

runHook('task-post-use', () => {
  const input = readStdinJSON();

  // --- Concise response check ---
  const response = getField(input, 'tool_result');
  if (response) {
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
  }

  // --- Dispatch prompt logging ---
  const subagentType = getField(input, 'tool_input.subagent_type');
  if (!subagentType.includes('supervisor')) process.exit(0);

  const prompt = getField(input, 'tool_input.prompt');
  if (!prompt) process.exit(0);

  const beadId = parseBeadId(prompt);
  if (!beadId) process.exit(0);

  const truncated = prompt.length > 2048 ? prompt.slice(0, 2048) : prompt;
  execCommand('bd', ['comment', beadId, `DISPATCH_PROMPT [${subagentType}]:\n\n${truncated}`]);
});
