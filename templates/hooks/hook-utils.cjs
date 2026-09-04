/**
 * hook-utils.js — Shared utilities for Claude Code hooks.
 *
 * Replaces bash+jq patterns with cross-platform Node.js equivalents.
 * No external dependencies — only Node.js built-ins.
 *
 * cwd contract: a hook process does NOT run in the project root — it inherits
 * the working directory of the last Bash tool call. Everything path-related
 * here is therefore anchored to getProjectDir(), and hook commands in
 * settings.json resolve this file through CLAUDE_PROJECT_DIR (see the
 * `node -e` wrapper written by bootstrap.py) instead of a relative path.
 */

'use strict';

const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');

// Module-level permission mode — set by readStdinJSON(), read by deny()/ask()
let _permissionMode = '';

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
    const parsed = JSON.parse(raw);
    _permissionMode = parsed.permission_mode || '';
    return parsed;
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
  // In bypass mode (--dangerously-skip-permissions), convert deny to warning
  if (_permissionMode === 'bypassPermissions') {
    process.stdout.write(`[HOOK WARNING — would deny] ${reason}\n`);
    process.exit(0);
  }
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
  // In bypass mode, skip ask entirely (allow the action)
  if (_permissionMode === 'bypassPermissions') process.exit(0);
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
  // In bypass mode, convert block to approve with warning
  if (_permissionMode === 'bypassPermissions') {
    process.stdout.write(`[HOOK WARNING — would block] ${reason}\n`);
    approve(); // approve() calls process.exit(0)
    return;    // unreachable, but signals intent to readers
  }
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

// Programs that turned out to be .cmd/.bat wrappers, so the direct spawn is
// known to fail for them. A single hook run calls the same tool several times;
// remember the answer instead of paying for a doomed spawn every time.
const _needsCmdExe = new Set();

/**
 * Run an external command and return trimmed stdout, or `null` on failure.
 *
 * No shell, ever. An args array combined with `shell: true` is NOT escaped —
 * Node concatenates it into one command line (that is what DEP0190 warns
 * about). Measured on Windows: a space splits one argument into two, quotes
 * are stripped, `^` disappears, `%VAR%` expands, and `&&`, `|`, `>` are
 * executed by the shell. It also breaks ordinary use: `git -C "C:\Users\Ivan
 * Petrov\repo" status` falls apart on the space, execCommand returns null, and
 * every check built on the answer silently passes.
 *
 * Windows still needs a shell for one case: `.cmd`/`.bat` wrappers (bd and gh
 * installed through npm) cannot be spawned directly at all — Node refuses with
 * EINVAL for a full path and ENOENT for a bare name. Those go through
 * `cmd.exe /d /s /c`, which finds the wrapper on PATH and — unlike
 * `shell: true` — keeps every argument intact.
 *
 * @param {string}   cmd   - Executable name (e.g. 'git', 'bd', 'gh')
 * @param {string[]} args  - Argument array
 * @param {object}   [opts] - Extra execFileSync options (cwd, env, etc.)
 * @returns {string|null}
 */
function execCommand(cmd, args, opts) {
  const options = {
    encoding: 'utf8',
    timeout: 10000,
    stdio: ['pipe', 'pipe', 'pipe'],
    // Anchor to the project root, not the hook's inherited cwd. Without
    // this, git/bd/gh answer about whatever directory the Bash tool last
    // used — a worktree, a subdirectory, or a path outside the repo — and
    // every check built on the answer silently passes. Callers may still
    // override via opts.cwd.
    cwd: getProjectDir(),
    ...opts,
  };
  const viaCmdExe = () => execFileSync('cmd.exe', ['/d', '/s', '/c', cmd, ...args], options);

  try {
    const direct = _needsCmdExe.has(cmd) ? viaCmdExe() : execFileSync(cmd, args, options);
    return direct.trim();
  } catch (err) {
    // ENOENT/EINVAL here means either "no such program" or "this program is a
    // wrapper script". Only the second is recoverable, and the two are
    // indistinguishable, so retry: a genuinely missing program fails again.
    const mayBeWrapper = process.platform === 'win32' &&
      !_needsCmdExe.has(cmd) &&
      (err.code === 'ENOENT' || err.code === 'EINVAL');
    if (!mayBeWrapper) return null;
    try {
      const viaShim = viaCmdExe();
      _needsCmdExe.add(cmd);
      return viaShim.trim();
    } catch {
      return null;
    }
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

/**
 * Absolute path of the project root.
 *
 * NEVER resolve project paths from process.cwd() alone: a hook process
 * inherits the working directory of the last Bash tool call, so it drifts
 * into subdirectories and worktrees (measured — hook cwd == Bash tool cwd).
 * Resolution order:
 *   1. CLAUDE_PROJECT_DIR — set by Claude Code for hook processes (measured).
 *   2. <this file>/../.. — hooks always live in <project>/.claude/hooks/.
 *   3. process.cwd() — last resort.
 */
function getProjectDir() {
  const fromEnv = process.env.CLAUDE_PROJECT_DIR;
  if (fromEnv) return fromEnv;
  const fromHere = path.resolve(__dirname, '..', '..');
  if (fs.existsSync(path.join(fromHere, '.claude'))) return fromHere;
  return process.cwd();
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
// Command parsing
// ---------------------------------------------------------------------------

/**
 * Split a shell command line into the commands a guard must inspect one by one.
 *
 * A guard that looks at the first word of the whole string sees only `cd` in
 * `cd sub && git commit --no-verify` and lets the rest through. Splitting on
 * the chaining operators gives every command its own turn.
 *
 * Quoted text is never split, so `echo "a && b"` stays a single command.
 * Command substitution (`$(...)`, backticks) is deliberately NOT split: doing
 * so would tear flags away from the command they belong to, which loses more
 * checks than it gains.
 *
 *   splitCommandSegments('cd x && git push | tee log')
 *     → ['cd x', 'git push', 'tee log']
 */
function splitCommandSegments(command) {
  if (!command) return [];
  const segments = [];
  let current = '';
  let quote = '';

  for (let i = 0; i < command.length; i++) {
    const ch = command[i];

    if (quote) {
      current += ch;
      if (ch === quote) quote = '';
      continue;
    }
    if (ch === "'" || ch === '"') {
      quote = ch;
      current += ch;
      continue;
    }
    if ((ch === '&' || ch === '|') && command[i + 1] === ch) {
      segments.push(current);
      current = '';
      i++;
      continue;
    }
    if (ch === ';' || ch === '&' || ch === '|' || ch === '\n') {
      segments.push(current);
      current = '';
      continue;
    }
    current += ch;
  }
  segments.push(current);

  return segments.map(s => s.trim()).filter(Boolean);
}

// ---------------------------------------------------------------------------
// Subagent detection
// ---------------------------------------------------------------------------

/**
 * Detect whether the current tool call originates from a subagent.
 * Subagents get full tool access — orchestrator restrictions don't apply.
 *
 * Checks transcript_path + tool_use_id against the subagents directory.
 * Returns false on any error (fail-open: treat as orchestrator).
 */
function isSubagent(input) {
  const transcriptPath = getField(input, 'transcript_path');
  const toolUseId = getField(input, 'tool_use_id');
  if (!transcriptPath || !toolUseId) return false;

  const sessionDir = transcriptPath.replace(/\.jsonl$/, '');
  const subagentsDir = path.join(sessionDir, 'subagents');

  try {
    const files = fs.readdirSync(subagentsDir)
      .filter(f => f.startsWith('agent-') && f.endsWith('.jsonl'));
    for (const f of files) {
      const content = fs.readFileSync(path.join(subagentsDir, f), 'utf8');
      if (content.includes(`"id":"${toolUseId}"`)) return true;
    }
  } catch {
    // No subagents dir or read error — treat as orchestrator
  }
  return false;
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
 *   const { runHook } = require('./hook-utils.cjs');
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
  splitCommandSegments,
  isSubagent,
  logError,
  runHook,
};
