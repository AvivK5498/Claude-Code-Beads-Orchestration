#!/usr/bin/env node
'use strict';

// PreCompact: Nudge orchestrator to update CLAUDE.md

const fs = require('fs');
const path = require('path');
const { getRepoRoot, injectText, runHook } = require('./hook-utils');

runHook('nudge-claude-md-update', () => {
const repoRoot = getRepoRoot();
if (!repoRoot) process.exit(0);

const claudeMd = path.join(repoRoot, 'CLAUDE.md');
try {
  fs.accessSync(claudeMd);
} catch {
  process.exit(0);
}

// Check if Current State section exists and has content
const content = fs.readFileSync(claudeMd, 'utf8');
const sectionMatch = content.match(/^## Current State\s*\n([\s\S]*?)(?=\n## |\n*$)/m);
const sectionBody = sectionMatch ? sectionMatch[1] : '';

// Strip comments and blank lines to check for real content
const meaningful = sectionBody
  .split('\n')
  .filter(line => !line.startsWith('<!--') && !line.startsWith('-->') && line.trim() !== '')
  .join('');

if (!meaningful) {
  injectText(`CLAUDE.md MAINTENANCE REMINDER:

The "## Current State" section in CLAUDE.md is empty. Before this context is compacted, consider updating it with:
- Active work in progress (bead IDs, what's being built)
- Recent architectural decisions or trade-offs made
- Known issues or blockers discovered
- Key files or patterns identified during investigation

This information will persist across sessions and help future investigations.

Update with: Edit CLAUDE.md → add content under "## Current State"
`);
} else {
  injectText(`Context is being compacted. If significant progress was made this session, consider updating CLAUDE.md:
- "## Current State" for active work and decisions
- "## Project Overview" if project scope became clearer
- "## Tech Stack" if new technologies were discovered
`);
}
});
