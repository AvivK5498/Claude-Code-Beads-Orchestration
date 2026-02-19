#!/usr/bin/env node

const { execSync } = require('child_process');
const path = require('path');
const fs = require('fs');

const args = process.argv.slice(2);
const command = args[0];

const packageDir = path.dirname(__dirname);
const bootstrapScript = path.join(packageDir, 'bootstrap.py');

function showHelp() {
  console.log(`
beads-orchestration - Multi-agent orchestration for Claude Code

Usage:
  beads-orchestration <command> [options]

Commands:
  install          Run postinstall to copy skill to ~/.claude/
  bootstrap        Run bootstrap.py directly (advanced)
  help             Show this help message

Examples:
  beads-orchestration install
  beads-orchestration bootstrap --project-dir /path/to/project --with-mux

After installing, use /create-beads-orchestration in Claude Code.
`);
}

function runInstall() {
  const postinstall = path.join(__dirname, 'postinstall.js');
  require(postinstall);
}

function runBootstrap() {
  const bootstrapArgs = args.slice(1).join(' ');
  try {
    execSync(`python3 "${bootstrapScript}" ${bootstrapArgs}`, { stdio: 'inherit' });
  } catch (err) {
    process.exit(err.status || 1);
  }
}

switch (command) {
  case 'install':
    runInstall();
    break;
  case 'bootstrap':
    runBootstrap();
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
