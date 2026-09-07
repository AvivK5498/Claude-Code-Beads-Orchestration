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
const os = require('os');
const path = require('path');

// Module-level permission mode — set by readStdinJSON(), read by deny()/ask()
let _permissionMode = '';

// The oldest beads CLI the rules work against: they call bd memories, bd
// remember, bd worktree and bd prime. Keep in sync with BD_MIN_VERSION in
// bootstrap.py — a test asserts the two agree, because two copies of a
// constant in two languages drift silently.
const BD_MIN_VERSION = '1.1.0';

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
 * Quote one argument for `cmd.exe`. Letting Node do it is not enough: Node
 * quotes an argument only when it contains whitespace, so `x&&whoami` arrives
 * bare and cmd.exe runs it as a second command (measured — an argument built
 * that way really did create a file). Inside double quotes cmd.exe treats
 * `&`, `|`, `<`, `>` and `^` as ordinary characters, and the callee's C
 * runtime strips the quotes again, so the program sees what the caller wrote.
 *
 * `%VAR%` is the one thing quoting cannot stop — cmd.exe expands it before it
 * looks at quotes. That substitutes an environment value into an argument; it
 * cannot start a command, and this path only ever runs .cmd wrappers.
 */
function quoteForCmdExe(arg) {
  // A backslash is only special in front of a quote, so double those runs —
  // the trailing run included, since the closing quote follows it.
  const escaped = String(arg).replace(/(\\*)"/g, '$1$1\\"').replace(/(\\*)$/, '$1$1');
  return `"${escaped}"`;
}

/** Run a command through cmd.exe — the only way to reach a .cmd/.bat wrapper. */
function runViaCmdExe(cmd, args, options) {
  // `/s` makes cmd.exe strip exactly the outermost pair of quotes and take the
  // rest literally, which is why the whole command goes inside one more pair.
  // windowsVerbatimArguments stops Node from re-quoting what is already quoted.
  const line = [cmd, ...args].map(quoteForCmdExe).join(' ');
  return execFileSync('cmd.exe', ['/d', '/s', '/c', `"${line}"`], {
    ...options,
    windowsVerbatimArguments: true,
  });
}

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
 * `cmd.exe /d /s /c` with arguments quoted by quoteForCmdExe below.
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
  try {
    const direct = _needsCmdExe.has(cmd)
      ? runViaCmdExe(cmd, args, options)
      : execFileSync(cmd, args, options);
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
      const viaShim = runViaCmdExe(cmd, args, options);
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
// beads version
// ---------------------------------------------------------------------------

/**
 * First dotted version in `bd version` output: 'bd version 1.1.0 (...)'.
 * Returns null when the text holds none.
 */
function parseBdVersion(text) {
  if (!text) return null;
  const match = /\d+\.\d+\.\d+/.exec(text);
  return match ? match[0] : null;
}

/**
 * True when `current` is older than `minimum`.
 *
 * Anything unreadable is false: a version we cannot parse is not evidence of
 * an old one, and a false alarm on every session start is worse than silence.
 */
function versionBelow(current, minimum) {
  const parts = (v) => String(v).split('.').map(Number);
  const a = parts(current);
  const b = parts(minimum);
  if (a.length !== 3 || a.some(Number.isNaN)) return false;
  if (b.length !== 3 || b.some(Number.isNaN)) return false;
  for (let i = 0; i < 3; i++) {
    if (a[i] !== b[i]) return a[i] < b[i];
  }
  return false;
}

// ---------------------------------------------------------------------------
// Our own version
// ---------------------------------------------------------------------------

/**
 * The version of claude-protocol this project is running, or null.
 *
 * Two installs, two places to look. As a plugin the version is the plugin's
 * own manifest. Installed with npx, bootstrap records it in the project's
 * .claude/.manifest.json, which is the only record of it there.
 */
function readOwnVersion() {
  const file = isPluginInstall()
    ? path.join(process.env.CLAUDE_PLUGIN_ROOT, '.claude-plugin', 'plugin.json')
    : path.join(getProjectDir(), '.claude', '.manifest.json');
  try {
    const version = JSON.parse(fs.readFileSync(file, 'utf8')).version;
    return typeof version === 'string' ? version : null;
  } catch {
    return null;
  }
}

/**
 * The lines to print when a newer version is out, or null when it is not.
 *
 * The two installs are updated differently, and the plugin path needs the part
 * people do not expect: auto-update is off by default for a third-party
 * marketplace, so nothing arrives until someone turns it on.
 */
function updateNotice(current, latest, fromPlugin) {
  if (!versionBelow(current, latest)) return null;
  return [
    `claude-protocol ${current} is behind ${latest}.`,
    fromPlugin
      ? '   Update it in /plugin → Marketplaces → claude-protocol. Auto-update is'
        + ' off by default for third-party marketplaces — turn it on there too.'
      : '   Update it with: npx claude-protocol@latest upgrade',
    '',
  ];
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
  // Walking up from __dirname is only meaningful for the copy installed under
  // a project's .claude/hooks/. Started from the plugin, this file lives in the
  // plugin's own checkout — which has a .claude/ and a .beads/ of its own, so
  // the guess would answer with the plugin instead of the project being worked
  // on, and every check built on the answer would be about the wrong place.
  if (!isPluginInstall()) {
    const fromHere = path.resolve(__dirname, '..', '..');
    if (fs.existsSync(path.join(fromHere, '.claude'))) return fromHere;
  }
  return process.cwd();
}

/** True when this hook was started by the plugin, not by a copy in a project. */
function isPluginInstall() {
  return Boolean(process.env.CLAUDE_PLUGIN_ROOT);
}

/** Claude Code's own record of which plugins are installed, and where. */
function pluginRegistryPath() {
  const dir = process.env.CLAUDE_CONFIG_DIR || path.join(os.homedir(), '.claude');
  return path.join(dir, 'plugins', 'installed_plugins.json');
}

/** The same directory, however either side happened to spell it. */
function samePath(a, b) {
  if (!a || !b) return false;
  const tidy = (p) => {
    const resolved = path.resolve(String(p).replace(/[\\/]+$/, ''));
    return process.platform === 'win32' ? resolved.toLowerCase() : resolved;
  };
  return tidy(a) === tidy(b);
}

/**
 * True when settings anywhere switch the plugin off.
 *
 * A plugin can be installed and disabled, and standing down for one that never
 * runs leaves the project with no hooks and nothing said about it. An explicit
 * false therefore outranks the registry. Absence is not a false: a
 * project-scope install writes no enabledPlugins entry at all.
 */
function pluginSwitchedOff(projectDir) {
  const dir = process.env.CLAUDE_CONFIG_DIR || path.join(os.homedir(), '.claude');
  const files = [
    path.join(dir, 'settings.json'),
    path.join(projectDir, '.claude', 'settings.json'),
    path.join(projectDir, '.claude', 'settings.local.json'),
  ];
  for (const file of files) {
    let enabled;
    try {
      enabled = JSON.parse(fs.readFileSync(file, 'utf8')).enabledPlugins;
    } catch {
      continue; // Absent or unreadable settings say nothing either way.
    }
    if (!enabled || typeof enabled !== 'object') continue;
    for (const [name, on] of Object.entries(enabled)) {
      if (name.split('@')[0] === 'claude-protocol' && on === false) return true;
    }
  }
  return false;
}

/**
 * True when the registry says claude-protocol is the plugin supplying hooks
 * here: installed at user scope, which covers every project, or at project
 * scope naming this one.
 *
 * Both install routes wire the same three hooks and Claude Code merges hooks
 * from every source, so a project carrying both fires each one twice. This is
 * how the copy installed under a project knows to stand down.
 *
 * Missing, unreadable or a shape we do not recognise all answer false. A copy
 * that stands down on a guess enforces nothing and says nothing about it,
 * which is the worse of the two failures by far.
 */
function pluginActiveHere(projectDir) {
  const here = projectDir || getProjectDir();
  if (pluginSwitchedOff(here)) return false;
  try {
    const registry = JSON.parse(fs.readFileSync(pluginRegistryPath(), 'utf8'));
    const plugins = registry && registry.plugins;
    if (!plugins || typeof plugins !== 'object') return false;
    for (const [name, entries] of Object.entries(plugins)) {
      if (name.split('@')[0] !== 'claude-protocol') continue;
      if (!Array.isArray(entries)) continue;
      for (const entry of entries) {
        if (!entry || typeof entry !== 'object') continue;
        if (entry.scope === 'user') return true;
        if (entry.scope === 'project' && samePath(entry.projectPath, here)) return true;
      }
    }
  } catch {
    // No registry, or one we cannot read. Neither is evidence of a plugin.
  }
  return false;
}

/**
 * True when the project being worked on tracks its work in beads.
 *
 * The plugin's hooks run in every project it is enabled for. Everything these
 * hooks enforce — bead lifecycle, worktree isolation, the completion report —
 * is meaningless where there is no .beads/, and refusing `git commit
 * --no-verify` in someone's unrelated repository is not our call to make.
 */
function hasBeads() {
  return fs.existsSync(path.join(getProjectDir(), '.beads'));
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
  // Both install routes wire the same hooks, and Claude Code merges hooks from
  // every source, so a project carrying both runs each one twice — a doubled
  // `bd prime` alone is ~19KB of context per session. Where the plugin is
  // active it is the one source; the copy installed under the project stands
  // down. Silently: the plugin's session-start says the leftovers are there
  // and what removes them, and one voice saying it is enough.
  if (!isPluginInstall() && pluginActiveHere()) process.exit(0);
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
  BD_MIN_VERSION,
  parseBdVersion,
  versionBelow,
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
  isPluginInstall,
  pluginActiveHere,
  hasBeads,
  readOwnVersion,
  updateNotice,
  parseBeadId,
  parseEpicId,
  containsPathSegment,
  splitCommandSegments,
  isSubagent,
  logError,
  runHook,
};
