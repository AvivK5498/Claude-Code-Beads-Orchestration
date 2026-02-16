#!/usr/bin/env node
'use strict';

// PreToolUse:Bash — Validate bead close: PR must be merged, epic children must be complete

const { readStdinJSON, getField, deny, execCommand, execCommandJSON, runHook } = require('./hook-utils');

runHook('validate-epic-close', () => {
// This hook reads from CLAUDE_TOOL_INPUT env var (not stdin for the command check)
// but also reads stdin for the standard hook contract
const input = readStdinJSON();

// Get tool input — prefer env var (original behavior), fall back to stdin
let toolInput;
try {
  toolInput = process.env.CLAUDE_TOOL_INPUT
    ? JSON.parse(process.env.CLAUDE_TOOL_INPUT)
    : getField(input, 'tool_input') || {};
} catch {
  toolInput = getField(input, 'tool_input') || {};
}

const command = toolInput.command || '';

// Only check bd close commands
if (!/bd\s+close/.test(command)) process.exit(0);

// Allow --force override
if (/--force/.test(command)) process.exit(0);

// Extract the ID being closed
const closeMatch = command.match(/bd\s+close\s+([A-Za-z0-9._-]+)/);
if (!closeMatch) process.exit(0);
const closeId = closeMatch[1];

// === CHECK 1: PR merge validation ===
const branch = `bd-${closeId}`;
const hasRemote = execCommand('git', ['remote', 'get-url', 'origin']);

if (hasRemote) {
  const remoteBranch = execCommand('git', ['ls-remote', '--heads', 'origin', branch]);

  if (remoteBranch) {
    // Branch exists on remote — check for merged PR
    const mergedPr = execCommand('gh', [
      'pr', 'list', '--head', branch, '--state', 'merged',
      '--json', 'number', '--jq', '.[0].number',
    ]);

    if (!mergedPr) {
      deny(
        `Cannot close bead '${closeId}' — branch '${branch}' has no merged PR. ` +
        `Create and merge a PR first, or use 'bd close ${closeId} --force' to override.`
      );
    }
  }
}

// === CHECK 2: Epic children validation ===
const beadData = execCommandJSON('bd', ['show', closeId, '--json']);
const issueType = beadData && beadData[0] ? (beadData[0].issue_type || '') : '';

if (issueType !== 'epic') process.exit(0);

// This is an epic — check all children are complete
const allBeads = execCommandJSON('bd', ['list', '--json']);
if (!Array.isArray(allBeads)) process.exit(0);

const prefix = closeId + '.';
const incomplete = allBeads.filter(
  b => b.id && b.id.startsWith(prefix) && b.status !== 'done' && b.status !== 'closed'
);

if (incomplete.length > 0) {
  const list = incomplete.map(b => `${b.id} (${b.status})`).join(', ');
  deny(
    `Cannot close epic '${closeId}' - has ${incomplete.length} incomplete children: ${list}. ` +
    'Mark all children as done first.'
  );
}
});
