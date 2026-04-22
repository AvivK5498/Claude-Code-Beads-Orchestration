#!/usr/bin/env node
'use strict';

// PreToolUse: Edit + Write — Branch protection, subagent bypass, quick-fix escape hatch
// Consolidated from: enforce-branch-before-edit + block-orchestrator-tools (Edit/Write logic)

const path = require('path');
const {
  readStdinJSON, getField, deny, ask,
  getCurrentBranch, containsPathSegment, isSubagent, runHook,
} = require('./hook-utils.cjs');

runHook('enforce-branch-before-edit', () => {
  const input = readStdinJSON();
  const toolName = getField(input, 'tool_name');

  // --- Subagents get full access ---
  if (isSubagent(input)) process.exit(0);

  const filePath = getField(input, 'tool_input.file_path');
  const fileName = path.basename(filePath);

  // --- Always-allowed paths ---
  if (containsPathSegment(filePath, '.claude/plans')) process.exit(0);
  if (fileName === 'CLAUDE.md' || fileName === 'CLAUDE.local.md') process.exit(0);
  if (fileName === 'git-issues.md') process.exit(0);

  // Allow memory files (.claude/**/memory/**)
  if (containsPathSegment(filePath, 'memory')) {
    const norm = filePath.replace(/\\/g, '/');
    if (norm.includes('.claude') && norm.includes('memory')) process.exit(0);
  }

  // Allow edits inside worktrees
  if (containsPathSegment(filePath, '.worktrees')) process.exit(0);
  if (containsPathSegment(process.cwd(), '.worktrees')) process.exit(0);

  // --- Branch checks ---
  const branch = getCurrentBranch();

  // On main/master → hard deny
  if (branch === 'main' || branch === 'master') {
    deny(
      `Cannot edit files on ${branch} branch.\n\n` +
      'For quick fixes (<10 lines):\n' +
      '  git checkout -b quick-fix-description\n' +
      '  Then retry the edit (you\'ll be prompted for approval)\n\n' +
      'For larger changes:\n' +
      '  Use the full bead workflow with supervisors.'
    );
  }

  // On feature branch → quick-fix ask with change size
  let sizeInfo;
  if (toolName === 'Edit') {
    const oldStr = getField(input, 'tool_input.old_string');
    const newStr = getField(input, 'tool_input.new_string');
    const newLines = newStr ? newStr.split('\n').length : 0;
    const oldChars = oldStr ? oldStr.length : 0;
    const newChars = newStr ? newStr.length : 0;
    sizeInfo = `~${newLines} lines (${oldChars} → ${newChars} chars)`;
  } else {
    const content = getField(input, 'tool_input.content');
    const contentLines = content ? content.split('\n').length : 0;
    sizeInfo = `~${contentLines} lines (new file)`;
  }

  ask(
    `Quick fix on branch '${branch}'?\n` +
    `  File: ${fileName}\n` +
    `  Change: ${sizeInfo}\n\n` +
    'Approve for trivial changes (<10 lines).\n' +
    'Deny to use full bead workflow instead.'
  );
});
