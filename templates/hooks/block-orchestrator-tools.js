#!/usr/bin/env node
'use strict';

// PreToolUse: Block orchestrator from implementation tools
// Orchestrators investigate and delegate — they don't implement.

const fs = require('fs');
const path = require('path');
const {
  readStdinJSON, getField, deny, ask,
  getCurrentBranch, containsPathSegment, runHook,
} = require('./hook-utils');

runHook('block-orchestrator-tools', () => {
const input = readStdinJSON();
const toolName = getField(input, 'tool_name');

// Always allow Task (delegation)
if (toolName === 'Task') process.exit(0);

// --- Detect SUBAGENT context — subagents get full tool access ---
const transcriptPath = getField(input, 'transcript_path');
const toolUseId = getField(input, 'tool_use_id');

if (transcriptPath && toolUseId) {
  const sessionDir = transcriptPath.replace(/\.jsonl$/, '');
  const subagentsDir = path.join(sessionDir, 'subagents');

  try {
    const files = fs.readdirSync(subagentsDir).filter(f => f.startsWith('agent-') && f.endsWith('.jsonl'));
    for (const f of files) {
      const content = fs.readFileSync(path.join(subagentsDir, f), 'utf8');
      if (content.includes(`"id":"${toolUseId}"`)) {
        // This is a subagent — allow everything
        process.exit(0);
      }
    }
  } catch {
    // No subagents dir or read error — continue as orchestrator
  }
}

// --- Edit / Write tool checks ---
if (toolName === 'Edit' || toolName === 'Write') {
  const filePath = getField(input, 'tool_input.file_path');
  const fileName = path.basename(filePath);

  // Allow Plan mode
  if (containsPathSegment(filePath, '.claude/plans')) process.exit(0);

  // Allow CLAUDE.md / CLAUDE.local.md
  if (fileName === 'CLAUDE.md' || fileName === 'CLAUDE.local.md') process.exit(0);

  // Allow git-issues.md
  if (fileName === 'git-issues.md') process.exit(0);

  // Allow memory files
  if (containsPathSegment(filePath, 'memory')) {
    const norm = filePath.replace(/\\/g, '/');
    if (norm.includes('.claude') && norm.includes('memory')) process.exit(0);
  }

  // Allow if editing within a worktree
  if (containsPathSegment(filePath, '.worktrees')) process.exit(0);

  // --- QUICK-FIX ESCAPE HATCH ---
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

  // On feature branch → ask for quick-fix approval
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
}

// Block NotebookEdit
if (toolName === 'NotebookEdit') {
  deny(`Tool '${toolName}' blocked. Orchestrators investigate and delegate via Task(). Supervisors implement.`);
}

// Validate provider_delegator agent invocations
if (toolName === 'mcp__provider_delegator__invoke_agent') {
  const agent = getField(input, 'tool_input.agent');
  const allowed = ['scout', 'detective', 'architect', 'scribe', 'code-reviewer'];
  if (!allowed.includes(agent)) {
    deny(`Agent '${agent}' cannot be invoked via Codex. Implementation agents (*-supervisor, discovery) must use Task() with BEAD_ID for beads workflow.`);
  }
}

// Validate Bash commands for orchestrator
if (toolName === 'Bash') {
  const command = getField(input, 'tool_input.command');
  const firstWord = command.split(/\s+/)[0] || '';

  if (firstWord === 'git') {
    // Block --no-verify
    if (command.includes('--no-verify') || / -n\b/.test(command)) {
      deny(
        'git commit --no-verify is blocked.\n\n' +
        'Pre-commit hooks exist for a reason (type-check, lint, tests).\n' +
        'Run the commit without --no-verify and fix any issues.'
      );
    }
    // Allow all git commands (read and write)
    process.exit(0);
  }

  if (firstWord === 'bd') {
    const parts = command.split(/\s+/);
    const subCmd = parts[1] || '';

    // Validate bd create requires description
    if (subCmd === 'create' || subCmd === 'new') {
      if (!command.includes('-d ') && !command.includes('--description ') && !command.includes('--description=')) {
        deny('bd create requires description (-d or --description) for supervisor context.');
      }
    }
    process.exit(0);
  }

  // Allow other bash commands
  process.exit(0);
}

// Allow everything else
process.exit(0);
});
