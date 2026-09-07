import { describe, it, expect } from 'vitest';
import { spawnSync } from 'child_process';
import fs from 'fs';
import os from 'os';
import path from 'path';

const SCRIPT = path.resolve(__dirname, '../../templates/hooks/update-check.cjs');
const HOURS = 60 * 60 * 1000;

/** A cache directory holding an answer of the given age. */
function cacheAged(hours, latest = '9.9.9') {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'update-check-'));
  fs.writeFileSync(path.join(dir, 'claude-protocol-update-check.json'),
                   JSON.stringify({ latest, checkedAt: Date.now() - hours * HOURS }));
  return dir;
}

function run(cacheDir) {
  return spawnSync(process.execPath, [SCRIPT], {
    encoding: 'utf8',
    timeout: 20000,
    env: { ...process.env, CLAUDE_PLUGIN_DATA: cacheDir },
  }).stdout;
}

describe('update-check cache window', () => {
  it('answers from a cache written today, without asking the network', () => {
    expect(run(cacheAged(12))).toBe('9.9.9');
  });

  it('does not answer from one written the day before', () => {
    // Offline it prints nothing, online it prints the real latest version.
    // Either way the stale answer is gone, which is the whole point of the
    // window: two releases in one afternoon used to stay hidden for a week.
    expect(run(cacheAged(30))).not.toBe('9.9.9');
  });
});
