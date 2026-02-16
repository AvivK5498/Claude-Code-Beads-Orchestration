#!/usr/bin/env node
'use strict';

// PostToolUse:Task (async) — Auto-log dispatch prompts to bead comments

const { readStdinJSON, getField, parseBeadId, execCommand, runHook } = require('./hook-utils');

runHook('log-dispatch-prompt', () => {
const input = readStdinJSON();
const toolName = getField(input, 'tool_name');

if (toolName !== 'Task') process.exit(0);

const subagentType = getField(input, 'tool_input.subagent_type');

// Only log supervisor dispatches
if (!subagentType.includes('supervisor')) process.exit(0);

const prompt = getField(input, 'tool_input.prompt');
if (!prompt) process.exit(0);

const beadId = parseBeadId(prompt);
if (!beadId) process.exit(0);

// Truncate prompt at 2048 chars
const truncated = prompt.length > 2048 ? prompt.slice(0, 2048) : prompt;

// Log dispatch to bead (fail silently)
execCommand('bd', ['comment', beadId, `DISPATCH_PROMPT [${subagentType}]:\n\n${truncated}`]);
});
