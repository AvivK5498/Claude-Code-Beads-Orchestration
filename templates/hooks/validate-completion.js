#!/usr/bin/env node
'use strict';

// SubagentStop: Enforce bead lifecycle — work verification

const fs = require('fs');
const path = require('path');
const {
  readStdinJSON, getField, approve, block,
  execCommand, execCommandJSON, getRepoRoot, runHook,
} = require('./hook-utils');

runHook('validate-completion', () => {
const input = readStdinJSON();
const agentTranscript = getField(input, 'agent_transcript_path');
const mainTranscript = getField(input, 'transcript_path');
const agentId = getField(input, 'agent_id');

if (!agentTranscript || !fs.existsSync(agentTranscript)) approve();

// --- Extract last assistant text response ---
let lastResponse = '';
try {
  const lines = fs.readFileSync(agentTranscript, 'utf8').split('\n').filter(Boolean).slice(-200);
  const entries = lines
    .map(line => { try { return JSON.parse(line); } catch { return null; } })
    .filter(Boolean);

  // Find last assistant text content
  for (let i = entries.length - 1; i >= 0; i--) {
    const msg = entries[i].message;
    if (msg && msg.role === 'assistant' && Array.isArray(msg.content)) {
      for (const block of msg.content) {
        if (block.text) {
          lastResponse = block.text;
          break;
        }
      }
      if (lastResponse) break;
    }
  }
} catch {
  // Can't read transcript — fail open
  approve();
}

// === LAYER 1: Extract subagent_type from main transcript ===
let subagentType = '';
if (agentId && mainTranscript && fs.existsSync(mainTranscript)) {
  try {
    const mainContent = fs.readFileSync(mainTranscript, 'utf8');
    const mainLines = mainContent.split('\n').filter(Boolean);

    // Find the line with this agentId to get parentToolUseID
    let parentToolUseId = '';
    for (const line of mainLines) {
      if (line.includes(`"agentId":"${agentId}"`)) {
        try {
          const parsed = JSON.parse(line);
          parentToolUseId = parsed.parentToolUseID || '';
        } catch { /* skip */ }
        break;
      }
    }

    // Find the Task tool_use with that ID to get subagent_type
    if (parentToolUseId) {
      for (const line of mainLines) {
        if (line.includes(`"id":"${parentToolUseId}"`) && line.includes('"name":"Task"')) {
          try {
            const parsed = JSON.parse(line);
            const content = parsed.message && parsed.message.content;
            if (Array.isArray(content)) {
              for (const c of content) {
                if (c.type === 'tool_use' && c.id === parentToolUseId && c.input) {
                  subagentType = c.input.subagent_type || '';
                  break;
                }
              }
            }
          } catch { /* skip */ }
          break;
        }
      }
    }
  } catch {
    // Can't parse main transcript — continue without subagent_type
  }
}

// === LAYER 2: Check completion format ===
const hasBeadComplete = /BEAD.*COMPLETE/.test(lastResponse);
const hasWorktreeOrBranch = /(Worktree:|Branch:).*bd-/.test(lastResponse);

const isSupervisor = subagentType.includes('supervisor');
let needsVerification = isSupervisor || (hasBeadComplete && hasWorktreeOrBranch);

if (!needsVerification) approve();

// Worker supervisor is exempt
if (subagentType.includes('worker')) approve();

// === VERIFICATION CHECKS ===

// Check 1: Completion format required for supervisors
if (isSupervisor && (!hasBeadComplete || !hasWorktreeOrBranch)) {
  block(
    'Work verification failed: completion report missing.\n\n' +
    'Required format:\n' +
    'BEAD {BEAD_ID} COMPLETE\n' +
    'Worktree: .worktrees/bd-{BEAD_ID}\n' +
    'Files: [list]\n' +
    'Tests: pass\n' +
    'Summary: [1 sentence]'
  );
}

// Extract BEAD_ID from response
const beadMatch = lastResponse.match(/BEAD\s+([A-Za-z0-9._-]+)/);
const beadIdFromResponse = beadMatch ? beadMatch[1] : '';

// Check 2: Comment required
let hasComment = false;
try {
  const transcriptContent = fs.readFileSync(agentTranscript, 'utf8');
  hasComment = transcriptContent.includes('bd comment') || transcriptContent.includes('"command":"bd comment');
} catch { /* skip */ }

if (!hasComment) {
  block('Work verification failed: no comment on bead.\n\nRun: bd comment {BEAD_ID} "Completed: [summary]"');
}

// Check 3: Worktree verification
const repoRoot = getRepoRoot();
if (repoRoot && beadIdFromResponse) {
  const worktreePath = path.join(repoRoot, '.worktrees', `bd-${beadIdFromResponse}`);

  if (!fs.existsSync(worktreePath)) {
    block('Work verification failed: worktree not found.\n\nCreate worktree first via API.');
  }

  // Check 4: Uncommitted changes
  const uncommitted = execCommand('git', ['-C', worktreePath, 'status', '--porcelain']);
  if (uncommitted) {
    block('Work verification failed: uncommitted changes.\n\nRun in worktree:\n  git add -A && git commit -m "..."');
  }

  // Check 5: Remote push
  const hasRemote = execCommand('git', ['-C', worktreePath, 'remote', 'get-url', 'origin']);
  if (hasRemote) {
    const branchName = `bd-${beadIdFromResponse}`;
    const remoteExists = execCommand('git', ['-C', worktreePath, 'ls-remote', '--heads', 'origin', branchName]);
    if (!remoteExists) {
      block('Work verification failed: branch not pushed.\n\nRun: git push -u origin bd-{BEAD_ID}');
    }
  }
}

// Check 6: Bead status
if (beadIdFromResponse) {
  const beadData = execCommandJSON('bd', ['show', beadIdFromResponse, '--json']);
  const beadStatus = beadData && beadData[0] ? (beadData[0].status || 'unknown') : 'unknown';
  const expectedStatus = 'inreview';

  if (beadStatus !== expectedStatus) {
    block(`Work verification failed: bead status is '${beadStatus}'.\n\nRun: bd update ${beadIdFromResponse} --status ${expectedStatus}`);
  }
}

// Check 7: Verbosity limit
const lineCount = lastResponse.split('\n').length;
const charCount = lastResponse.length;

if (lineCount > 15 || charCount > 800) {
  block(`Work verification failed: response too verbose (${lineCount} lines, ${charCount} chars). Max: 15 lines, 800 chars.`);
}

approve();
});
