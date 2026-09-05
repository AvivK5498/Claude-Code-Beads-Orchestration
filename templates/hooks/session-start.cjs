#!/usr/bin/env node
'use strict';

// SessionStart: Surface what the task tracker cannot see.
//
// Deliberately NOT here: the list of in-progress / ready / blocked / stale
// beads. `bd prime` already prints it at session start, and running four more
// `bd` calls to print the same thing twice only slows the session down. What
// stays is what bd has no way to know: the state of the working tree, merged
// worktrees waiting to be cleaned up, and open pull requests.

const fs = require('fs');
const path = require('path');
const {
  injectText, execCommand, getProjectDir, runHook,
  parseBdVersion, versionBelow, BD_MIN_VERSION,
  hasBeads, isPluginInstall, readOwnVersion, updateNotice,
} = require('./hook-utils.cjs');

runHook('session-start', () => {
  const projectDir = getProjectDir();

  if (!hasBeads()) {
    // A copy installed under a project's .claude/hooks/ is there because
    // someone put it there, so the missing directory is worth saying out loud.
    // The plugin runs in every project it is enabled for, and telling each of
    // them to run `bd init` every session is noise, not help.
    if (!isPluginInstall()) {
      injectText("No .beads directory found. Run 'bd init' to initialize.\n");
    }
    process.exit(0);
  }

  const output = [];
  const repoRoot = execCommand('git', ['-C', projectDir, 'rev-parse', '--show-toplevel']);

  collectOutdatedBd(output);
  collectUpdateNotice(output);
  collectDirtyWarning(repoRoot, output);
  collectMergedWorktrees(projectDir, repoRoot, output);
  collectOpenPrs(output);

  if (output.length === 0) process.exit(0);
  injectText(output.join('\n') + '\n');
});

// ---------------------------------------------------------------------------
// Sections
// ---------------------------------------------------------------------------

/**
 * A bd older than the rules rely on does not announce itself: it fails one
 * command at a time with "unknown command" in the middle of a task. One line
 * here is the explanation. Silent when bd cannot be read at all — an
 * unreadable version is not evidence of an old one.
 */
function collectOutdatedBd(output) {
  const found = parseBdVersion(execCommand('bd', ['version']) || '');
  if (!versionBelow(found, BD_MIN_VERSION)) return;

  output.push(`WARNING: bd ${found} is older than ${BD_MIN_VERSION}, which the rules rely on`);
  output.push('   (bd memories, bd remember, bd worktree, bd prime).');
  output.push('   Update it: npm install -g @beads/bd@latest');
  output.push('');
}

/**
 * A newer claude-protocol than the one running here.
 *
 * The check lives in its own process with a hard time limit, and its answer is
 * cached for a week — a session start is not the place to wait on the network.
 * Nothing to say when the version cannot be read, when the check fails, or
 * when there is no network: an update people do not hear about costs less than
 * a slow start every time.
 */
function collectUpdateNotice(output) {
  const current = readOwnVersion();
  if (!current) return;

  const script = path.join(__dirname, 'update-check.cjs');
  if (!fs.existsSync(script)) return;

  const latest = execCommand(process.execPath, [script],
                             { shell: false, timeout: 6000 });
  const lines = updateNotice(current, latest, isPluginInstall());
  if (lines) output.push(...lines);
}

/** Uncommitted work in the main checkout means agents would branch off it. */
function collectDirtyWarning(repoRoot, output) {
  if (!repoRoot) return;
  if (!execCommand('git', ['-C', repoRoot, 'status', '--porcelain'])) return;

  output.push('WARNING: Main directory has uncommitted changes.');
  output.push('   Agents should only work in .worktrees/');
  output.push('');
}

/** A merged branch whose worktree and bead are still around. */
function collectMergedWorktrees(projectDir, repoRoot, output) {
  if (!repoRoot || !fs.existsSync(path.join(projectDir, '.worktrees'))) return;

  const worktreeList = execCommand('git', ['-C', repoRoot, 'worktree', 'list', '--porcelain']);
  if (!worktreeList) return;

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

    // Exact match prevents bd-1 matching bd-10
    if (!mergedBranches.includes(dirName)) continue;

    const beadId = dirName.replace('bd-', '');
    output.push(`ACTION REQUIRED: ${dirName} was merged but bead "${beadId}" is still open.`);
    output.push(`   Run: bd close "${beadId}" && git worktree remove "${wtPath}"`);
    output.push('');
  }
}

/** Open pull requests are easy to forget between sessions. */
function collectOpenPrs(output) {
  const openPrs = execCommand('gh', [
    'pr', 'list', '--author', '@me', '--state', 'open',
    '--json', 'number,title,headRefName',
  ]);
  if (!openPrs || openPrs === '[]') return;

  let prs;
  try {
    prs = JSON.parse(openPrs);
  } catch {
    return;
  }
  if (!Array.isArray(prs) || prs.length === 0) return;

  output.push('You have open PRs:');
  for (const pr of prs) {
    output.push(`  #${pr.number} ${pr.title} (${pr.headRefName})`);
  }
  output.push('');
}
