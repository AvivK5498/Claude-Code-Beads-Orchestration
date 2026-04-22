#!/usr/bin/env node
'use strict';

// SessionStart: Show full task context for orchestrator

const fs = require('fs');
const path = require('path');
const { injectText, execCommand, getProjectDir, runHook } = require('./hook-utils.cjs');

runHook('session-start', () => {
  const projectDir = getProjectDir();
  const beadsDir = path.join(projectDir, '.beads');

  if (!fs.existsSync(beadsDir)) {
    injectText("No .beads directory found. Run 'bd init' to initialize.\n");
    process.exit(0);
  }

  // Check if bd is available
  if (!execCommand('bd', ['--version'])) {
    injectText('beads CLI (bd) not found. Install from: https://github.com/gastownhall/beads\n');
    process.exit(0);
  }

  const output = [];

  // ============================================================
  // Dirty Parent Check
  // ============================================================
  const repoRoot = execCommand('git', ['-C', projectDir, 'rev-parse', '--show-toplevel']);
  if (repoRoot) {
    const dirty = execCommand('git', ['-C', repoRoot, 'status', '--porcelain']);
    if (dirty) {
      output.push('WARNING: Main directory has uncommitted changes.');
      output.push('   Agents should only work in .worktrees/');
      output.push('');
    }
  }

  // ============================================================
  // Auto-cleanup: Detect merged PRs and cleanup worktrees
  // ============================================================
  const worktreesDir = path.join(projectDir, '.worktrees');
  if (fs.existsSync(worktreesDir) && repoRoot) {
    const worktreeList = execCommand('git', ['-C', repoRoot, 'worktree', 'list', '--porcelain']);
    if (worktreeList) {
      const worktreeLines = worktreeList.split('\n')
        .filter(line => line.startsWith('worktree ') && line.includes('.worktrees/bd-'));

      // Hoist git branch --merged outside the loop (was called per-worktree before)
      const merged = execCommand('git', ['-C', repoRoot, 'branch', '--merged', 'main']);
      const mergedBranches = merged
        ? merged.split('\n').map(b => b.trim().replace(/^\*\s*/, ''))
        : [];

      for (const line of worktreeLines) {
        const wtPath = line.replace('worktree ', '').trim();
        const dirName = path.basename(wtPath);
        const beadId = dirName.replace('bd-', '');

        // Exact match prevents bd-1 matching bd-10
        if (mergedBranches.includes(dirName)) {
          output.push(`ACTION REQUIRED: ${dirName} was merged but bead "${beadId}" is still open.`);
          output.push(`   Run: bd close "${beadId}" && git worktree remove "${wtPath}"`);
          output.push('');
        }
      }
    }
  }

  // ============================================================
  // Open PR Reminder
  // ============================================================
  const openPrs = execCommand('gh', ['pr', 'list', '--author', '@me', '--state', 'open', '--json', 'number,title,headRefName']);
  if (openPrs && openPrs !== '[]') {
    try {
      const prs = JSON.parse(openPrs);
      if (prs.length > 0) {
        output.push('You have open PRs:');
        for (const pr of prs) {
          output.push(`  #${pr.number} ${pr.title} (${pr.headRefName})`);
        }
        output.push('');
      }
    } catch {
      // Skip if gh output can't be parsed
    }
  }

  output.push('');
  output.push('## Task Status');
  output.push('');

  // Show in-progress beads
  const inProgress = execCommand('bd', ['list', '--status', 'in_progress']);
  if (inProgress) {
    const lines = inProgress.split('\n').slice(0, 5).join('\n');
    output.push('### In Progress (resume these):');
    output.push(lines);
    output.push('');
  }

  // Show ready (unblocked) beads
  const ready = execCommand('bd', ['ready']);
  if (ready) {
    const lines = ready.split('\n').slice(0, 5).join('\n');
    output.push('### Ready (no blockers):');
    output.push(lines);
    output.push('');
  }

  // Show blocked beads
  const blocked = execCommand('bd', ['blocked']);
  if (blocked) {
    const lines = blocked.split('\n').slice(0, 3).join('\n');
    output.push('### Blocked:');
    output.push(lines);
    output.push('');
  }

  // Show stale beads
  const stale = execCommand('bd', ['stale', '--days', '3']);
  if (stale) {
    const lines = stale.split('\n').slice(0, 3).join('\n');
    output.push('### Stale (no activity in 3 days):');
    output.push(lines);
    output.push('');
  }

  // If nothing found
  if (!inProgress && !ready && !blocked && !stale) {
    output.push('No active beads. Create one with: bd create "Task title" -d "Description"');
  }

  output.push('');
  injectText(output.join('\n'));
});
