#!/usr/bin/env node
'use strict';

// PreToolUse:Task — Enforce sequential dispatch and design doc existence

const fs = require('fs');
const {
  readStdinJSON, getField, deny, parseBeadId,
  execCommand, execCommandJSON, runHook,
} = require('./hook-utils');

runHook('enforce-sequential-dispatch', () => {
const input = readStdinJSON();
const toolName = getField(input, 'tool_name');

if (toolName !== 'Task') process.exit(0);

const subagentType = getField(input, 'tool_input.subagent_type');
const prompt = getField(input, 'tool_input.prompt');

// Only check for supervisors
if (!subagentType.includes('supervisor')) process.exit(0);

// Worker-supervisor is exempt
if (subagentType.includes('worker')) process.exit(0);

// Extract BEAD_ID
const beadId = parseBeadId(prompt);
if (!beadId) process.exit(0);

// Block dispatch to closed/done beads
const beadData = execCommandJSON('bd', ['show', beadId, '--json']);
const beadStatus = beadData && beadData[0] ? (beadData[0].status || '') : '';

if (beadStatus === 'closed' || beadStatus === 'done') {
  deny(
    `<closed-bead>\nBead ${beadId} is already ${beadStatus}. Do not reopen closed beads.\n\n` +
    'Create a new bead for follow-up work and relate it:\n\n' +
    `  bd create "Fix: [description]" -d "Follow-up to ${beadId}: [details]"\n` +
    '  # Returns: {NEW_ID}\n' +
    `  bd dep relate {NEW_ID} ${beadId}\n\n` +
    'Then dispatch with the NEW bead ID.\n</closed-bead>'
  );
}

// Check if this is an epic child (contains dot)
if (beadId.includes('.')) {
  // Extract EPIC_ID (everything before last dot)
  const epicId = beadId.replace(/\.[0-9]+$/, '');

  // Check for unresolved blockers (exclude parent epic)
  const deps = execCommandJSON('bd', ['dep', 'list', beadId, '--json']);
  if (Array.isArray(deps)) {
    const blockers = deps.filter(
      d => d.id !== epicId && d.status !== 'done' && d.status !== 'closed'
    );
    if (blockers.length > 0) {
      const blockerIds = blockers.map(b => b.id).join(', ');
      deny(
        `<blocked-task>\nCannot dispatch ${beadId} - unresolved blockers: ${blockerIds}\n\n` +
        'Complete blocking tasks first, then dispatch this one.\n\n' +
        'Use: bd ready --json to see tasks with no blockers.\n</blocked-task>'
      );
    }
  }

  // Check design doc exists (if epic has design field)
  const epicData = execCommandJSON('bd', ['show', epicId, '--json']);
  const designPath = epicData && epicData[0] ? (epicData[0].design || '') : '';

  if (designPath && !fs.existsSync(designPath)) {
    deny(
      `<design-doc-missing>\nEpic ${epicId} has design path '${designPath}' but file doesn't exist.\n\n` +
      '<stop-and-think>\nBefore dispatching architect, verify you fully understand the epic:\n\n' +
      '1. Are the requirements clear and unambiguous?\n' +
      '2. Do you know the expected inputs/outputs?\n' +
      '3. Are there edge cases or constraints to consider?\n' +
      '4. Do you understand how this integrates with existing code?\n\n' +
      'If ANY ambiguity exists -> Use AskUserQuestion to clarify FIRST.\n' +
      'Do NOT dispatch architect with vague requirements.\n' +
      '</stop-and-think>\n\n' +
      '<next-steps>\nIf requirements are CLEAR:\n' +
      '  Task(\n' +
      '    subagent_type="architect",\n' +
      `    prompt="Create design doc for EPIC_ID: ${epicId}\n` +
      `           Output: ${designPath}\n` +
      '           \n' +
      '           [Provide clear, specific requirements]"\n' +
      '  )\n\n' +
      'If requirements are UNCLEAR:\n' +
      '  AskUserQuestion(\n' +
      '    questions=[{\n' +
      '      "question": "[Your specific clarifying question]",\n' +
      '      "header": "Clarify",\n' +
      '      "options": [...],\n' +
      '      "multiSelect": false\n' +
      '    }]\n' +
      '  )\n</next-steps>\n</design-doc-missing>'
    );
  }
}
});
