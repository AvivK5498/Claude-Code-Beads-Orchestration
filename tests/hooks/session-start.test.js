import { describe, it, expect } from 'vitest';
import { spawnSync } from 'child_process';
import fs from 'fs';
import os from 'os';
import path from 'path';

const HOOK_PATH = path.resolve(__dirname, '../../templates/hooks/session-start.cjs');
const OWN_VERSION = JSON.parse(
  fs.readFileSync(path.resolve(__dirname, '../../package.json'), 'utf8')).version;

/**
 * A throwaway project with beads, optionally wiring hooks of ours itself.
 * The hook runs with its working directory inside it, so the git and gh calls
 * in the other sections fail fast instead of reaching a real repository.
 */
function project({ settings } = {}) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'session-start-'));
  fs.mkdirSync(path.join(dir, '.beads'), { recursive: true });
  fs.mkdirSync(path.join(dir, '.claude'), { recursive: true });
  for (const [name, contents] of Object.entries(settings || {})) {
    fs.writeFileSync(path.join(dir, '.claude', name), JSON.stringify(contents));
  }
  return dir;
}

/** A week is the update check's cache window; a fresh entry keeps it offline. */
function pluginDataSayingUpToDate() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'session-start-data-'));
  fs.writeFileSync(path.join(dir, 'claude-protocol-update-check.json'),
                   JSON.stringify({ latest: OWN_VERSION, checkedAt: Date.now() }));
  return dir;
}

function runHook(dir, env = {}) {
  return spawnSync(process.execPath, [HOOK_PATH], {
    cwd: dir,
    encoding: 'utf8',
    timeout: 30000,
    env: {
      ...process.env,
      CLAUDE_PROJECT_DIR: dir,
      CLAUDE_PLUGIN_ROOT: '',
      CLAUDE_PLUGIN_DATA: pluginDataSayingUpToDate(),
      CLAUDE_CONFIG_DIR: fs.mkdtempSync(path.join(os.tmpdir(), 'session-start-cfg-')),
      ...env,
    },
  });
}

const OURS = {
  hooks: {
    PreToolUse: [{
      matcher: 'Bash',
      hooks: [{ type: 'command', command: 'node -e "..." bash-guard.cjs' }],
    }],
  },
};

describe('session-start on a project installed twice', () => {
  const asPlugin = { CLAUDE_PLUGIN_ROOT: path.join(os.tmpdir(), 'pretend-plugin') };

  it('says the npx install is still wired up, and what removes it', () => {
    const result = runHook(project({ settings: { 'settings.json': OURS } }), asPlugin);

    expect(result.stdout).toContain('installed twice');
    expect(result.stdout).toContain('bash-guard.cjs');
    expect(result.stdout).toContain('/claude-protocol:init');
  });

  it('says nothing where the project wires no hooks of ours', () => {
    const result = runHook(project(), asPlugin);

    expect(result.stdout).not.toContain('installed twice');
  });

  it('leaves it to the plugin to say — the project copy keeps quiet', () => {
    const result = runHook(project({ settings: { 'settings.json': OURS } }));

    expect(result.stdout).not.toContain('installed twice');
  });
});
