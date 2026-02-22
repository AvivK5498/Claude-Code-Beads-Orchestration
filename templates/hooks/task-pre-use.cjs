#!/usr/bin/env node
'use strict';

// PreToolUse: Task — Bead validation + guidance reminders (single spawn)
// Consolidated from: enforce-bead-for-supervisor, enforce-sequential-dispatch,
//                    remind-inprogress, inject-discipline-reminder

const fs = require('fs');
const {
  readStdinJSON, getField, deny, injectText, parseBeadId,
  execCommandJSON, runHook,
} = require('./hook-utils.cjs');

runHook('task-pre-use', () => {
  const input = readStdinJSON();
  const subagentType = getField(input, 'tool_input.subagent_type');
  const prompt = getField(input, 'tool_input.prompt');

  // Only enforce for supervisors (not scouts, detectives, architects, etc.)
  if (!subagentType.includes('supervisor')) process.exit(0);

  // merge-supervisor is exempt from bead requirements
  if (subagentType === 'merge-supervisor') process.exit(0);

  // === VALIDATION (blocking) ===

  // 1. BEAD_ID must exist in prompt
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

  const beadId = parseBeadId(prompt);
  if (!beadId) process.exit(0);

  // worker-supervisor is exempt from sequential checks
  if (subagentType.includes('worker')) {
    emitGuidance(subagentType, prompt);
    process.exit(0);
  }

  // 2. Block dispatch to closed/done beads (reuse bd show result)
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

  // 3. Epic child checks — blockers and design doc
  if (beadId.includes('.')) {
    const epicId = beadId.replace(/\.[0-9]+$/, '');

    // Check unresolved blockers (exclude parent epic)
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

    // Check design doc exists
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

  // === GUIDANCE (non-blocking) ===
  emitGuidance(subagentType, prompt);
});

/** Emit soft reminders (in_progress + discipline skill) */
function emitGuidance(subagentType, prompt) {
  if (prompt.includes('BEAD_ID:')) {
    injectText('IMPORTANT: Before dispatching, ensure bead is in_progress: bd update {BEAD_ID} --status in_progress\n');
  }
  if (subagentType.includes('-supervisor')) {
    injectText(`<system-reminder>
SUPERVISOR DISPATCH: Before implementing, invoke \`/subagents-discipline\` skill.
This ensures verification-first development with DEMO blocks.
</system-reminder>
`);
  }
}
