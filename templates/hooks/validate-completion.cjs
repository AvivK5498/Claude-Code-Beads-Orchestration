#!/usr/bin/env node
'use strict';

// SubagentStop: Enforce bead lifecycle — work verification
// Refactored: main function <30 lines, helpers handle each check.

const fs = require('fs');
const path = require('path');
const {
  readStdinJSON, getField, approve, block,
  execCommand, getRepoRoot, runHook,
} = require('./hook-utils.cjs');

runHook('validate-completion', () => {
  const input = readStdinJSON();
  const agentTranscript = getField(input, 'agent_transcript_path');
  const mainTranscript = getField(input, 'transcript_path');
  const agentId = getField(input, 'agent_id');

  if (!agentTranscript || !fs.existsSync(agentTranscript)) approve();

  // Determine subagent type BEFORE expensive transcript parsing
  const subagentType = extractSubagentType(agentId, mainTranscript);
  const isSupervisor = subagentType.includes('supervisor');

  // Worker supervisors are exempt from all checks
  if (subagentType.includes('worker')) approve();

  // Read agent transcript once, reuse for all checks
  let agentTranscriptContent = '';
  try { agentTranscriptContent = fs.readFileSync(agentTranscript, 'utf8'); } catch { approve(); }

  const lastResponse = extractLastResponse(agentTranscriptContent);

  // Non-supervisors: only verify if they output completion patterns
  if (!isSupervisor) {
    const hasCompletion = /BEAD.*COMPLETE/.test(lastResponse)
      && /(Worktree:|Branch:).*bd-/.test(lastResponse);
    if (!hasCompletion) approve();
  }

  // Supervisors must include completion report
  if (isSupervisor) verifyCompletionFormat(lastResponse);

  const beadId = extractBeadId(lastResponse);
  verifyChecklist(lastResponse, beadId);
  verifyComment(agentTranscriptContent);
  verifyWorktree(beadId);
  verifyVerbosity(lastResponse);

  approve();
});

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Extract subagent_type by scanning main transcript for the Task tool_use. */
function extractSubagentType(agentId, mainTranscript) {
  if (!agentId || !mainTranscript || !fs.existsSync(mainTranscript)) return '';
  try {
    const lines = fs.readFileSync(mainTranscript, 'utf8').split('\n').filter(Boolean);

    // Find parentToolUseID from the agent entry
    let parentToolUseId = '';
    for (const line of lines) {
      if (line.includes(`"agentId":"${agentId}"`)) {
        try { parentToolUseId = JSON.parse(line).parentToolUseID || ''; } catch { /* skip */ }
        break;
      }
    }
    if (!parentToolUseId) return '';

    // Find the Task tool_use with that ID
    for (const line of lines) {
      if (line.includes(`"id":"${parentToolUseId}"`) && line.includes('"name":"Task"')) {
        try {
          const content = JSON.parse(line).message?.content;
          if (Array.isArray(content)) {
            for (const c of content) {
              if (c.type === 'tool_use' && c.id === parentToolUseId && c.input) {
                return c.input.subagent_type || '';
              }
            }
          }
        } catch { /* skip */ }
        break;
      }
    }
  } catch { /* fail open */ }
  return '';
}

/** Extract last assistant text response from raw transcript content. */
function extractLastResponse(transcriptContent) {
  try {
    const lines = transcriptContent.split('\n').filter(Boolean).slice(-200);
    for (let i = lines.length - 1; i >= 0; i--) {
      try {
        const msg = JSON.parse(lines[i]).message;
        if (msg?.role === 'assistant' && Array.isArray(msg.content)) {
          for (const b of msg.content) {
            if (b.text) return b.text;
          }
        }
      } catch { /* skip line */ }
    }
  } catch { /* fail open */ }
  return '';
}

/** Extract BEAD_ID from response text. */
function extractBeadId(response) {
  const m = response.match(/BEAD\s+([A-Za-z0-9._-]+)/);
  return m ? m[1] : '';
}

/** Block if completion report format is missing. */
function verifyCompletionFormat(response) {
  const hasBeadComplete = /BEAD.*COMPLETE/.test(response);
  const hasWorktreeOrBranch = /(Worktree:|Branch:).*bd-/.test(response);
  if (!hasBeadComplete || !hasWorktreeOrBranch) {
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
}

/** Block if completion report has no checklist or has unchecked items. */
function verifyChecklist(response, beadId) {
  if (!response.includes('Checklist:')) {
    block(
      'Work verification failed: completion report missing Checklist.\n\n' +
      'Re-read the bead description with `bd show ' + (beadId || '{BEAD_ID}') + '` and add:\n' +
      'Checklist:\n- [x] requirement 1\n- [x] requirement 2'
    );
  }

  const unchecked = response.match(/- \[ \]/g);
  if (unchecked) {
    block(
      `Work verification failed: ${unchecked.length} unchecked item(s) in Checklist.\n\n` +
      'Complete all requirements before marking done, or update the bead description if requirements changed.'
    );
  }
}

/** Block if no bd comment found in agent transcript content. */
function verifyComment(transcriptContent) {
  if (transcriptContent.includes('bd comment') || transcriptContent.includes('"command":"bd comment')) return;
  block('Work verification failed: no comment on bead.\n\nRun: bd comment {BEAD_ID} "Completed: [summary]"');
}

/** Block if worktree missing, has uncommitted changes, or branch not pushed. */
function verifyWorktree(beadId) {
  const repoRoot = getRepoRoot();
  if (!repoRoot || !beadId) return;

  const worktreePath = path.join(repoRoot, '.worktrees', `bd-${beadId}`);
  if (!fs.existsSync(worktreePath)) {
    block('Work verification failed: worktree not found.\n\nCreate worktree first via API.');
  }

  const uncommitted = execCommand('git', ['-C', worktreePath, 'status', '--porcelain']);
  if (uncommitted) {
    block('Work verification failed: uncommitted changes.\n\nRun in worktree:\n  git add -A && git commit -m "..."');
  }

  const hasRemote = execCommand('git', ['-C', worktreePath, 'remote', 'get-url', 'origin']);
  if (hasRemote) {
    const branchName = `bd-${beadId}`;
    const remoteExists = execCommand('git', ['-C', worktreePath, 'ls-remote', '--heads', 'origin', branchName]);
    if (!remoteExists) {
      block('Work verification failed: branch not pushed.\n\nRun: git push -u origin bd-{BEAD_ID}');
    }
  }
}

/** Block if response exceeds verbosity limits (15 lines / 800 chars). */
function verifyVerbosity(response) {
  const lineCount = response.split('\n').length;
  const charCount = response.length;
  if (lineCount > 25 || charCount > 1200) {
    block(`Work verification failed: response too verbose (${lineCount} lines, ${charCount} chars). Max: 25 lines, 1200 chars.`);
  }
}
