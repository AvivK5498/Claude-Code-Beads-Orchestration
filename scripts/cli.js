#!/usr/bin/env node

const { execFileSync } = require('child_process');
const path = require('path');

const args = process.argv.slice(2);
const command = args[0];
const packageDir = path.dirname(__dirname);
const bootstrapScript = path.join(packageDir, 'bootstrap.py');

function showHelp() {
  console.log(`
claude-protocol - Enforcement-first orchestration for Claude Code

Usage:
  claude-protocol <command> [options]

Commands:
  init          Install into current project (beads, agents, hooks, rules, skills)
  upgrade       Re-run init and clean up obsolete artifacts (safe for existing installs)
  help          Show this help message

Options:
  --project-name   Project name (auto-inferred if not provided)
  --project-dir    Project directory (default: current)
  --no-rules       Skip dev rules (implementation, logging, TDD)
  --lang <en|ru>   Language for dev rules (default: en)
  --force          Overwrite all files regardless of user modifications
  --dry-run        Preview changes without writing (upgrade only)
  --all <parent>   Batch upgrade: iterate subdirs of <parent> with .beads/ (upgrade only)

Examples:
  claude-protocol init
  claude-protocol init --lang ru
  claude-protocol init --project-dir /path/to/project
  claude-protocol init --no-rules
  claude-protocol upgrade
  claude-protocol upgrade --dry-run
  claude-protocol upgrade --all /path/to/parent-dir
`);
}

function pythonCmd() {
  return process.platform === 'win32' ? 'python' : 'python3';
}

function normalizeRulesFlag(bootstrapArgs) {
  // --with-rules by default, unless --no-rules is specified
  if (!bootstrapArgs.includes('--no-rules')) {
    if (!bootstrapArgs.includes('--with-rules')) {
      bootstrapArgs.push('--with-rules');
    }
  } else {
    // Remove --no-rules (bootstrap.py doesn't know this flag)
    const idx = bootstrapArgs.indexOf('--no-rules');
    bootstrapArgs.splice(idx, 1);
  }
  return bootstrapArgs;
}

function runInstall() {
  const bootstrapArgs = normalizeRulesFlag(args.slice(1));
  try {
    execFileSync(pythonCmd(), [bootstrapScript, ...bootstrapArgs], { stdio: 'inherit' });
  } catch (err) {
    process.exit(err.status || 1);
  }
}

function runUpgrade() {
  const bootstrapArgs = normalizeRulesFlag(args.slice(1));
  // Auto-append --upgrade only if user didn't pass it — avoids duplicate flags.
  if (!bootstrapArgs.includes('--upgrade')) {
    bootstrapArgs.push('--upgrade');
  }
  try {
    execFileSync(pythonCmd(), [bootstrapScript, ...bootstrapArgs], { stdio: 'inherit' });
  } catch (err) {
    process.exit(err.status || 1);
  }
}

switch (command) {
  case 'init':
  case 'install':
    runInstall();
    break;
  case 'upgrade':
    runUpgrade();
    break;
  case 'help':
  case '--help':
  case '-h':
  case undefined:
    showHelp();
    break;
  default:
    console.error(`Unknown command: ${command}`);
    showHelp();
    process.exit(1);
}
