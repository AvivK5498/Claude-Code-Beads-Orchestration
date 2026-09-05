#!/usr/bin/env node
'use strict';

// PreToolUse: Bash — Git safety, bd validation, epic close checks
// Consolidated from: validate-epic-close + block-orchestrator-tools (Bash logic)

const {
  readStdinJSON, getField, deny, isSubagent, hasBeads,
  execCommand, execCommandJSON, splitCommandSegments, runHook,
} = require('./hook-utils.cjs');

runHook('bash-guard', () => {
  const input = readStdinJSON();

  // Subagents get full access
  if (isSubagent(input)) process.exit(0);

  // As a plugin this runs in every project it is enabled for. Refusing
  // `git commit --no-verify` in a repository that never asked for any of this
  // is not our call, and the bd checks below have nothing to check.
  if (!hasBeads()) process.exit(0);

  // Get command — prefer env var (original behavior), fall back to stdin
  let toolInput;
  try {
    toolInput = process.env.CLAUDE_TOOL_INPUT
      ? JSON.parse(process.env.CLAUDE_TOOL_INPUT)
      : getField(input, 'tool_input') || {};
  } catch {
    toolInput = getField(input, 'tool_input') || {};
  }

  // Every command in the chain gets its own turn. Reading only the first word
  // of the whole line saw `cd` in `cd sub && git commit --no-verify` and let
  // the guarded command through untouched.
  for (const segment of splitCommandSegments(toolInput.command || '')) {
    const words = segment.split(/\s+/).filter(Boolean);
    const program = words[0] || '';

    if (program === 'git') checkGit(segment, words.slice(1));
    else if (program === 'bd') checkBd(segment, words.slice(1));
  }

  // Allow everything else
  process.exit(0);
});

// ---------------------------------------------------------------------------
// Guards — each one denies (and exits) or returns
// ---------------------------------------------------------------------------

/** Git safety: no skipped pre-commit hooks, no raw worktree creation. */
function checkGit(segment, args) {
  if (segment.includes('--no-verify') || /\bcommit\b.*\s-n\b/.test(segment)) {
    deny(
      'git commit --no-verify is blocked.\n\n' +
      'Pre-commit hooks exist for a reason (type-check, lint, tests).\n' +
      'Run the commit without --no-verify and fix any issues.'
    );
  }

  // Block raw `git worktree add` — it creates a shadow .beads/ (process leak,
  // data loss). Match by argument structure (subcommand=worktree, action=add),
  // not a naive includes('add'), so branch/path names containing "add" and
  // `git worktree remove`/`prune`/`list` are unaffected.
  if (args[0] === 'worktree' && args[1] === 'add') {
    deny(
      'git worktree add is blocked — use `bd worktree create` instead.\n\n' +
      'Raw `git worktree add` creates a shadow .beads/ copy (process leak, data loss).\n' +
      'For removing worktrees, raw `git worktree remove` is allowed ' +
      '(bd worktree remove is broken on Windows, see u51).'
    );
  }
}

/** bd validation: descriptions on create, epic integrity on close. */
function checkBd(segment, args) {
  const subCmd = args[0] || '';

  // bd create must have description
  if (subCmd === 'create' || subCmd === 'new') {
    if (!segment.includes('-d ') && !segment.includes('--description ') && !segment.includes('--description=')) {
      deny('bd create requires description (-d or --description) for supervisor context.');
    }
  }

  if (subCmd === 'close') checkEpicClose(segment);
}

/** Epic close: branch must be merged, children must be done. */
function checkEpicClose(segment) {
  if (/--force/.test(segment)) return;

  const closeMatch = segment.match(/bd\s+close\s+([A-Za-z0-9._-]+)/);
  if (!closeMatch) return;
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
  if (issueType !== 'epic') return;

  const allBeads = execCommandJSON('bd', ['list', '--json']);
  if (!Array.isArray(allBeads)) return;

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
