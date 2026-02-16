/**
 * hook-utils.js — Shared utilities for Claude Code hooks.
 *
 * Replaces bash+jq patterns with cross-platform Node.js equivalents.
 * No external dependencies — only Node.js built-ins.
 */

'use strict';

const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');

// ---------------------------------------------------------------------------
// Stdin
// ---------------------------------------------------------------------------

/**
 * Read all of stdin and parse as JSON.
 * Returns empty object on failure (hooks should fail open).
 */
function readStdinJSON() {
  try {
    const raw = fs.readFileSync(0, 'utf8');
    return JSON.parse(raw);
  } catch {
    return {};
  }
}

// ---------------------------------------------------------------------------
// Field access
// ---------------------------------------------------------------------------

/**
 * Safe nested property access via dot-path.
 *   getField(obj, 'tool_input.prompt') → obj.tool_input.prompt || ''
 */
function getField(obj, dotPath) {
  const parts = dotPath.split('.');
  let cur = obj;
  for (const p of parts) {
    if (cur == null || typeof cur !== 'object') return '';
    cur = cur[p];
  }
  return cur == null ? '' : cur;
}

// ---------------------------------------------------------------------------
// Output helpers (PreToolUse)
// ---------------------------------------------------------------------------

function deny(reason) {
  const out = {
    hookSpecificOutput: {
      hookEventName: 'PreToolUse',
      permissionDecision: 'deny',
      permissionDecisionReason: reason,
    },
  };
  process.stdout.write(JSON.stringify(out));
  process.exit(0);
}

function ask(reason) {
  const out = {
    hookSpecificOutput: {
      hookEventName: 'PreToolUse',
      permissionDecision: 'ask',
      permissionDecisionReason: reason,
    },
  };
  process.stdout.write(JSON.stringify(out));
  process.exit(0);
}

// ---------------------------------------------------------------------------
// Output helpers (SubagentStop)
// ---------------------------------------------------------------------------

function approve() {
  process.stdout.write('{"decision":"approve"}');
  process.exit(0);
}

function block(reason) {
  const out = { decision: 'block', reason };
  process.stdout.write(JSON.stringify(out));
  process.exit(0);
}

// ---------------------------------------------------------------------------
// Output helpers (plain text — SessionStart, UserPromptSubmit, PreCompact)
// ---------------------------------------------------------------------------

function injectText(text) {
  process.stdout.write(text);
}

// ---------------------------------------------------------------------------
// External CLI
// ---------------------------------------------------------------------------

/**
 * Run an external command and return trimmed stdout, or `null` on failure.
 * Uses execFileSync (no shell) to avoid command-injection risks.
 *
 * @param {string}   cmd   - Executable name (e.g. 'git', 'bd', 'gh')
 * @param {string[]} args  - Argument array
 * @param {object}   [opts] - Extra execFileSync options (cwd, env, etc.)
 * @returns {string|null}
 */
function execCommand(cmd, args, opts) {
  try {
    const result = execFileSync(cmd, args, {
      encoding: 'utf8',
      timeout: 10000,
      stdio: ['pipe', 'pipe', 'pipe'],
      ...opts,
    });
    return result.trim();
  } catch {
    return null;
  }
}

/**
 * Run a command and parse its stdout as JSON, or return `null` on failure.
 */
function execCommandJSON(cmd, args, opts) {
  const raw = execCommand(cmd, args, opts);
  if (raw == null) return null;
  try {
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

// ---------------------------------------------------------------------------
// Git helpers
// ---------------------------------------------------------------------------

function getRepoRoot() {
  return execCommand('git', ['rev-parse', '--show-toplevel']);
}

function getCurrentBranch() {
  return execCommand('git', ['branch', '--show-current']) || '';
}

// ---------------------------------------------------------------------------
// Project helpers
// ---------------------------------------------------------------------------

function getProjectDir() {
  return process.env.CLAUDE_PROJECT_DIR || process.cwd();
}

// ---------------------------------------------------------------------------
// Bead helpers
// ---------------------------------------------------------------------------

/**
 * Extract BEAD_ID from text.  Matches "BEAD_ID: <id>" where id may contain
 * alphanumerics, dots, dashes, underscores.  Returns empty string if not found.
 */
function parseBeadId(text) {
  if (!text) return '';
  const m = text.match(/BEAD_ID:\s*([A-Za-z0-9._-]+)/);
  return m ? m[1] : '';
}

/**
 * Extract EPIC_ID from text (same pattern as BEAD_ID but with EPIC_ID prefix).
 */
function parseEpicId(text) {
  if (!text) return '';
  const m = text.match(/EPIC_ID:\s*([A-Za-z0-9._-]+)/);
  return m ? m[1] : '';
}

// ---------------------------------------------------------------------------
// Path helpers
// ---------------------------------------------------------------------------

/**
 * Check whether a file path contains a segment, using platform-independent
 * comparison.  Normalises separators to forward slashes before matching.
 *   containsPathSegment('/foo/.worktrees/bd-1/bar.ts', '.worktrees') → true
 */
function containsPathSegment(filePath, segment) {
  if (!filePath) return false;
  const normalised = filePath.replace(/\\/g, '/');
  return normalised.includes('/' + segment + '/') ||
    normalised.endsWith('/' + segment);
}

// ---------------------------------------------------------------------------
// Error logging
// ---------------------------------------------------------------------------

const LOG_FILE_NAME = 'beads_orchestrator_errors.log';

/**
 * Append a timestamped error entry to beads_orchestrator_errors.log
 * in the project root.  Never throws — logging failure must not break hooks.
 */
function logError(hookName, err) {
  try {
    const projectDir = getProjectDir();
    const logPath = path.join(projectDir, LOG_FILE_NAME);
    const ts = new Date().toISOString();
    const msg = err instanceof Error ? err.stack || err.message : String(err);
    fs.appendFileSync(logPath, `[${ts}] [${hookName}] ${msg}\n`);
  } catch {
    // Logging must never break the hook
  }
}

/**
 * Wrap a hook's main function with error handling.
 * On unhandled exception: logs to beads_orchestrator_errors.log and exits 0
 * (fail open — hook error should not block the user).
 *
 * Usage in each hook file:
 *   const { runHook } = require('./hook-utils');
 *   runHook('hook-name', () => { ... });
 */
function runHook(hookName, fn) {
  try {
    fn();
  } catch (err) {
    logError(hookName, err);
    process.exit(0);
  }
}

// ---------------------------------------------------------------------------
// Exports
// ---------------------------------------------------------------------------

module.exports = {
  readStdinJSON,
  getField,
  deny,
  ask,
  approve,
  block,
  injectText,
  execCommand,
  execCommandJSON,
  getRepoRoot,
  getCurrentBranch,
  getProjectDir,
  parseBeadId,
  parseEpicId,
  containsPathSegment,
  logError,
  runHook,
};
