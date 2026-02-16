#!/usr/bin/env node
'use strict';

// PreToolUse:Task — Soft reminder to set bead status before dispatch

const { readStdinJSON, getField, injectText, runHook } = require('./hook-utils');

runHook('remind-inprogress', () => {
  const input = readStdinJSON();
  const prompt = getField(input, 'tool_input.prompt');

  if (prompt.includes('BEAD_ID:')) {
    injectText('IMPORTANT: Before dispatching, ensure bead is in_progress: bd update {BEAD_ID} --status in_progress');
  }
});
