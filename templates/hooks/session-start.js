#!/usr/bin/env node
'use strict';

// SessionStart: Show full task context for orchestrator

const fs = require('fs');
const path = require('path');
const { injectText, execCommand, getProjectDir, runHook } = require('./hook-utils');

runHook('session-start', () => {
const projectDir = getProjectDir();
const beadsDir = path.join(projectDir, '.beads');

if (!fs.existsSync(beadsDir)) {
  injectText("No .beads directory found. Run 'bd init' to initialize.\n");
  process.exit(0);
}

// Check if bd is available
if (!execCommand('bd', ['--version'])) {
  injectText('beads CLI (bd) not found. Install from: https://github.com/steveyegge/beads\n');
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

    for (const line of worktreeLines) {
      const wtPath = line.replace('worktree ', '').trim();
      const dirName = path.basename(wtPath);
      const beadId = dirName.replace('bd-', '');

      const merged = execCommand('git', ['-C', repoRoot, 'branch', '--merged', 'main']);
      if (merged && merged.includes(dirName)) {
        output.push(`✓ ${dirName} was merged - consider cleaning up`);
        output.push(`   Run: git worktree remove "${wtPath}" && bd close "${beadId}"`);
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

// ============================================================
// Knowledge Base - Surface recent learnings
// ============================================================
const knowledgeFile = path.join(beadsDir, 'memory', 'knowledge.jsonl');
try {
  const stat = fs.statSync(knowledgeFile);
  if (stat.size > 0) {
    const allLines = fs.readFileSync(knowledgeFile, 'utf8').split('\n').filter(Boolean);
    const totalEntries = allLines.length;

    // Parse last 20 entries, deduplicate by key (latest wins), show top 5
    const recent = allLines.slice(-20)
      .map(line => { try { return JSON.parse(line); } catch { return null; } })
      .filter(Boolean);

    const byKey = new Map();
    for (const e of recent) {
      const existing = byKey.get(e.key);
      if (!existing || (e.ts || 0) > (existing.ts || 0)) byKey.set(e.key, e);
    }

    const top5 = [...byKey.values()]
      .sort((a, b) => (b.ts || 0) - (a.ts || 0))
      .slice(0, 5);

    if (top5.length > 0) {
      output.push('');
      output.push(`## Recent Knowledge (${totalEntries} entries)`);
      output.push('');
      for (const e of top5) {
        const typeLabel = (e.type || '').toUpperCase().slice(0, 5);
        const snippet = (e.content || '').slice(0, 100);
        output.push(`  [${typeLabel}] ${snippet}  (${e.source})`);
      }
      output.push('');
      output.push('  Search: .beads/memory/recall.sh "keyword"');
    }
  }
} catch {
  // No knowledge file — skip
}

output.push('');
injectText(output.join('\n'));
});
