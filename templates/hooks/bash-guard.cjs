#!/usr/bin/env node
'use strict';

// PreToolUse: Bash — Git safety, bd validation, epic close checks
// Consolidated from: validate-epic-close + block-orchestrator-tools (Bash logic)

const {
  readStdinJSON, getField, deny, isSubagent,
  execCommand, execCommandJSON, runHook,
} = require('./hook-utils.cjs');

runHook('bash-guard', () => {
  const input = readStdinJSON();

  // Subagents get full access
  if (isSubagent(input)) process.exit(0);

  // Get command — prefer env var (original behavior), fall back to stdin
  let toolInput;
  try {
    toolInput = process.env.CLAUDE_TOOL_INPUT
      ? JSON.parse(process.env.CLAUDE_TOOL_INPUT)
      : getField(input, 'tool_input') || {};
  } catch {
    toolInput = getField(input, 'tool_input') || {};
  }

  const command = toolInput.command || '';
  const firstWord = command.split(/\s+/)[0] || '';

  // === Git safety checks ===
  if (firstWord === 'git') {
    if (command.includes('--no-verify') || / -n\b/.test(command)) {
      deny(
        'git commit --no-verify is blocked.\n\n' +
        'Pre-commit hooks exist for a reason (type-check, lint, tests).\n' +
        'Run the commit without --no-verify and fix any issues.'
      );
    }
    process.exit(0);
  }

  // === bd validation ===
  if (firstWord === 'bd') {
    const parts = command.split(/\s+/);
    const subCmd = parts[1] || '';

    // bd create must have description
    if (subCmd === 'create' || subCmd === 'new') {
      if (!command.includes('-d ') && !command.includes('--description ') && !command.includes('--description=')) {
        deny('bd create requires description (-d or --description) for supervisor context.');
      }
    }

    // === Epic close validation ===
    if (subCmd === 'close') {
      if (/--force/.test(command)) process.exit(0);

      const closeMatch = command.match(/bd\s+close\s+([A-Za-z0-9._-]+)/);
      if (!closeMatch) process.exit(0);
      const closeId = closeMatch[1];

      // CHECK 1: PR merge validation
      const branch = `bd-${closeId}`;
      const hasRemote = execCommand('git', ['remote', 'get-url', 'origin']);

      if (hasRemote) {
        const remoteBranch = execCommand('git', ['ls-remote', '--heads', 'origin', branch]);
        if (remoteBranch) {
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

      // CHECK 2: Epic children validation
      const beadData = execCommandJSON('bd', ['show', closeId, '--json']);
      const issueType = beadData && beadData[0] ? (beadData[0].issue_type || '') : '';

      if (issueType === 'epic') {
        const allBeads = execCommandJSON('bd', ['list', '--json']);
        if (Array.isArray(allBeads)) {
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
        }
      }
    }

    process.exit(0);
  }

  // Allow everything else
  process.exit(0);
});
