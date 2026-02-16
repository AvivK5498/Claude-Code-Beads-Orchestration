#!/usr/bin/env node
'use strict';

// PreToolUse: Block Edit/Write on main branch outside worktrees

const { readStdinJSON, getField, deny, getCurrentBranch, containsPathSegment, runHook } = require('./hook-utils');

runHook('enforce-branch-before-edit', () => {
const input = readStdinJSON();
const toolName = getField(input, 'tool_name');

if (toolName !== 'Edit' && toolName !== 'Write') process.exit(0);

const filePath = getField(input, 'tool_input.file_path');

// Allow Plan mode files
if (containsPathSegment(filePath, '.claude/plans')) process.exit(0);

// Allow if editing within .worktrees/ directory
if (containsPathSegment(filePath, '.worktrees')) process.exit(0);

// Allow if CWD is inside a worktree
const cwd = process.cwd();
if (containsPathSegment(cwd, '.worktrees')) process.exit(0);

// Block if on main or master
const branch = getCurrentBranch();
if (branch === 'main' || branch === 'master') {
  deny(
    `Cannot edit files on ${branch} branch. Supervisors must work in worktrees.\n\n` +
    'Create a worktree first using the API:\n' +
    '  POST /api/git/worktree { repo_path, bead_id }\n\n' +
    'Then cd into .worktrees/bd-{BEAD_ID}/ to make changes.'
  );
}
});
