#!/usr/bin/env node
'use strict';

// PostToolUse:Bash (async) — Capture knowledge from bd comment commands

const fs = require('fs');
const path = require('path');
const { readStdinJSON, getField, getProjectDir, runHook } = require('./hook-utils');

runHook('memory-capture', () => {
const input = readStdinJSON();
const toolName = getField(input, 'tool_name');
if (toolName !== 'Bash') process.exit(0);

const command = getField(input, 'tool_input.command');
if (!command) process.exit(0);

// Only process bd comment commands containing LEARNED:
if (!/bd\s+comment\s+/.test(command)) process.exit(0);
if (!command.includes('LEARNED:')) process.exit(0);

// Extract BEAD_ID (argument after "bd comment")
const beadMatch = command.match(/bd\s+comment\s+([A-Za-z0-9._-]+)\s+/);
if (!beadMatch) process.exit(0);
const beadId = beadMatch[1];

// Extract the comment body (content inside quotes after bead ID)
const bodyMatch = command.match(/bd\s+comment\s+[A-Za-z0-9._-]+\s+["'](.*)["']\s*$/s);
if (!bodyMatch) process.exit(0);
const commentBody = bodyMatch[1].slice(0, 4096);
if (!commentBody) process.exit(0);

// Extract LEARNED content
const learnedMatch = commentBody.match(/LEARNED:\s*([\s\S]*)/);
if (!learnedMatch) process.exit(0);
const content = learnedMatch[1].trim().slice(0, 2048);
if (!content) process.exit(0);

const type = 'learned';

// Generate key (type + slugified first 60 chars)
const slug = content
  .slice(0, 60)
  .toLowerCase()
  .replace(/[^a-z0-9]+/g, '-')
  .replace(/^-|-$/g, '');
const key = `${type}-${slug}`;

// Detect source: inside worktree → supervisor, otherwise orchestrator
const cwd = getField(input, 'cwd');
const source = cwd.replace(/\\/g, '/').includes('.worktrees/') ? 'supervisor' : 'orchestrator';

// Build tags
const tags = [type];
const TAG_KEYWORDS = [
  'swift', 'swiftui', 'appkit', 'menubar', 'api', 'security', 'test', 'database',
  'networking', 'ui', 'layout', 'performance', 'crash', 'bug', 'fix', 'workaround',
  'gotcha', 'pattern', 'convention', 'architecture', 'auth', 'middleware',
  'async', 'concurrency', 'model', 'protocol', 'adapter', 'scanner', 'engine',
];
const contentLower = content.toLowerCase();
for (const tag of TAG_KEYWORDS) {
  if (contentLower.includes(tag)) tags.push(tag);
}

// Build entry
const entry = {
  key,
  type,
  content,
  source,
  tags,
  ts: Math.floor(Date.now() / 1000),
  bead: beadId,
};

// Resolve memory directory
const memoryDir = path.join(getProjectDir(), '.beads', 'memory');
fs.mkdirSync(memoryDir, { recursive: true });
const knowledgeFile = path.join(memoryDir, 'knowledge.jsonl');

// Append entry
fs.appendFileSync(knowledgeFile, JSON.stringify(entry) + '\n');

// Rotation: archive oldest 500 when file exceeds 1000 lines
try {
  const lines = fs.readFileSync(knowledgeFile, 'utf8').split('\n').filter(Boolean);
  if (lines.length > 1000) {
    const archiveFile = path.join(memoryDir, 'knowledge.archive.jsonl');
    const toArchive = lines.slice(0, 500);
    const toKeep = lines.slice(500);
    fs.appendFileSync(archiveFile, toArchive.join('\n') + '\n');
    fs.writeFileSync(knowledgeFile, toKeep.join('\n') + '\n');
  }
} catch {
  // Rotation failure is non-critical
}
});
