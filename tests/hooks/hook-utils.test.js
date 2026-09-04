import { describe, it, expect } from 'vitest';

// hook-utils.cjs exports pure functions we can test directly
const {
  getField,
  parseBeadId,
  parseEpicId,
  containsPathSegment,
} = require('../../templates/hooks/hook-utils.cjs');

describe('getField', () => {
  it('returns nested value via dot path', () => {
    const obj = { tool_input: { command: 'git status' } };
    expect(getField(obj, 'tool_input.command')).toBe('git status');
  });

  it('returns empty string for missing path', () => {
    expect(getField({ a: 1 }, 'a.b.c')).toBe('');
  });

  it('returns empty string for null input', () => {
    expect(getField(null, 'a')).toBe('');
  });

  it('returns empty string for undefined input', () => {
    expect(getField(undefined, 'a')).toBe('');
  });

  it('returns top-level value', () => {
    expect(getField({ name: 'test' }, 'name')).toBe('test');
  });

  it('returns empty string for null leaf', () => {
    expect(getField({ a: { b: null } }, 'a.b')).toBe('');
  });

  it('returns 0 as-is (not empty string)', () => {
    expect(getField({ count: 0 }, 'count')).toBe(0);
  });

  it('returns false as-is', () => {
    expect(getField({ flag: false }, 'flag')).toBe(false);
  });
});

describe('parseBeadId', () => {
  it('extracts bead ID from text', () => {
    expect(parseBeadId('BEAD_ID: tcp-7uv.1')).toBe('tcp-7uv.1');
  });

  it('handles alphanumeric IDs with dots and dashes', () => {
    expect(parseBeadId('BEAD_ID: BD-001.2')).toBe('BD-001.2');
  });

  it('handles underscores', () => {
    expect(parseBeadId('BEAD_ID: my_bead_1')).toBe('my_bead_1');
  });

  it('returns empty string when no match', () => {
    expect(parseBeadId('no bead here')).toBe('');
  });

  it('returns empty string for null', () => {
    expect(parseBeadId(null)).toBe('');
  });

  it('returns empty string for empty string', () => {
    expect(parseBeadId('')).toBe('');
  });

  it('extracts first match from multiline', () => {
    const text = 'line1\nBEAD_ID: abc-123\nBEAD_ID: def-456';
    expect(parseBeadId(text)).toBe('abc-123');
  });
});

describe('parseEpicId', () => {
  it('extracts epic ID from text', () => {
    expect(parseEpicId('EPIC_ID: tcp-7uv')).toBe('tcp-7uv');
  });

  it('returns empty string when no match', () => {
    expect(parseEpicId('BEAD_ID: abc')).toBe('');
  });

  it('returns empty string for null', () => {
    expect(parseEpicId(null)).toBe('');
  });
});

describe('containsPathSegment', () => {
  it('detects segment in unix path', () => {
    expect(containsPathSegment('/foo/.worktrees/bd-1/bar.ts', '.worktrees')).toBe(true);
  });

  it('detects segment in windows path', () => {
    expect(containsPathSegment('C:\\projects\\.worktrees\\bd-1\\file.js', '.worktrees')).toBe(true);
  });

  it('detects segment at end of path', () => {
    expect(containsPathSegment('/foo/.worktrees', '.worktrees')).toBe(true);
  });

  it('returns false for partial match', () => {
    expect(containsPathSegment('/foo/worktrees-old/file.js', '.worktrees')).toBe(false);
  });

  it('returns false for null path', () => {
    expect(containsPathSegment(null, '.worktrees')).toBe(false);
  });

  it('returns false for empty path', () => {
    expect(containsPathSegment('', '.worktrees')).toBe(false);
  });

  it('detects .claude segment', () => {
    expect(containsPathSegment('/project/.claude/plans/plan.md', '.claude')).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// Project-directory anchoring
// ---------------------------------------------------------------------------
// A hook process inherits the working directory of the last Bash tool call,
// so process.cwd() may be a subdirectory, a worktree, or a path outside the
// repo. Nothing path-related may depend on it.

const fs = require('fs');
const os = require('os');
const path = require('path');

const utilsPath = require.resolve('../../templates/hooks/hook-utils.cjs');
const { getProjectDir, getRepoRoot, execCommand } = require(utilsPath);
const repoRoot = path.resolve(__dirname, '..', '..');

/** Copy hook-utils into a throwaway <tmp>/.claude/hooks/ and load that copy. */
function loadInstalledCopy() {
  const project = fs.mkdtempSync(path.join(os.tmpdir(), 'cp-hooks-'));
  const hooks = path.join(project, '.claude', 'hooks');
  fs.mkdirSync(hooks, { recursive: true });
  const dest = path.join(hooks, 'hook-utils.cjs');
  fs.copyFileSync(utilsPath, dest);
  return { project, mod: require(dest) };
}

function withEnv(value, fn) {
  const saved = process.env.CLAUDE_PROJECT_DIR;
  if (value === undefined) delete process.env.CLAUDE_PROJECT_DIR;
  else process.env.CLAUDE_PROJECT_DIR = value;
  try {
    return fn();
  } finally {
    if (saved === undefined) delete process.env.CLAUDE_PROJECT_DIR;
    else process.env.CLAUDE_PROJECT_DIR = saved;
  }
}

function withCwd(dir, fn) {
  const saved = process.cwd();
  process.chdir(dir);
  try {
    return fn();
  } finally {
    process.chdir(saved);
  }
}

describe('getProjectDir', () => {
  it('prefers CLAUDE_PROJECT_DIR', () => {
    withEnv('M:/somewhere/else', () => {
      expect(getProjectDir()).toBe('M:/somewhere/else');
    });
  });

  it('falls back to the project that owns the hook file, not the cwd', () => {
    const { project, mod } = loadInstalledCopy();
    withEnv(undefined, () => {
      withCwd(os.tmpdir(), () => {
        expect(fs.realpathSync(mod.getProjectDir())).toBe(fs.realpathSync(project));
      });
    });
  });

  it('ignores the cwd even when it is a subdirectory of the project', () => {
    withEnv(undefined, () => {
      withCwd(path.join(repoRoot, 'templates', 'hooks'), () => {
        expect(fs.realpathSync(getProjectDir())).toBe(fs.realpathSync(repoRoot));
      });
    });
  });
});

describe('execCommand cwd anchoring', () => {
  it('asks git about the project, not about the inherited cwd', () => {
    withEnv(repoRoot, () => {
      withCwd(os.tmpdir(), () => {
        const root = getRepoRoot();
        expect(root).not.toBeNull();
        expect(fs.realpathSync(root)).toBe(fs.realpathSync(repoRoot));
      });
    });
  });

  it('still lets the caller override cwd explicitly', () => {
    const out = execCommand('git', ['rev-parse', '--show-toplevel'], { cwd: os.tmpdir() });
    // os.tmpdir() is not a repository, so git fails and execCommand returns null
    expect(out).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// splitCommandSegments
// ---------------------------------------------------------------------------

const { splitCommandSegments } = require('../../templates/hooks/hook-utils.cjs');

describe('splitCommandSegments', () => {
  it('returns a single command unchanged', () => {
    expect(splitCommandSegments('git status')).toEqual(['git status']);
  });

  it('splits on && so a guarded command cannot hide behind cd', () => {
    expect(splitCommandSegments('cd sub && git commit --no-verify'))
      .toEqual(['cd sub', 'git commit --no-verify']);
  });

  it('splits on ||, ; , | and newlines', () => {
    expect(splitCommandSegments('a || b ; c | d')).toEqual(['a', 'b', 'c', 'd']);
    expect(splitCommandSegments('a\nb')).toEqual(['a', 'b']);
  });

  it('splits on a single & (background)', () => {
    expect(splitCommandSegments('sleep 1 & git push')).toEqual(['sleep 1', 'git push']);
  });

  it('does not split inside double quotes', () => {
    expect(splitCommandSegments('echo "a && b"')).toEqual(['echo "a && b"']);
  });

  it('does not split inside single quotes', () => {
    expect(splitCommandSegments("git commit -m 'fix; also fix'"))
      .toEqual(["git commit -m 'fix; also fix'"]);
  });

  it('drops empty segments from trailing operators', () => {
    expect(splitCommandSegments('git status &&')).toEqual(['git status']);
    expect(splitCommandSegments('')).toEqual([]);
  });
});

// ---------------------------------------------------------------------------
// execCommand argument passing
// ---------------------------------------------------------------------------
// An args array combined with `shell: true` is concatenated, not escaped —
// that is what Node's DEP0190 warns about. Measured on Windows: a space splits
// one argument into two, quotes are stripped, `^` disappears, `%VAR%` expands,
// and `&&`, `|`, `>` execute as shell operators. These tests pin the fix down:
// every argument must reach the program exactly as it was written.

const { spawnSync } = require('child_process');

/** A throwaway script that prints each argv entry on its own line. */
function makeArgvPrinter() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'cp-argv-'));
  const file = path.join(dir, 'argv-print.js');
  fs.writeFileSync(file, 'process.argv.slice(2).forEach((a, i) => console.log(i + "=<" + a + ">"));\n');
  return file;
}

/** Split output on newlines without caring which line ending the OS used. */
function lines(out) {
  return String(out).split(/\r?\n/);
}

const onWindows = process.platform === 'win32';

describe('execCommand argument passing', () => {
  // process.execPath is "C:\Program Files\nodejs\node.exe" on Windows, so this
  // also covers a program whose own path contains a space.
  const printer = makeArgvPrinter();

  it('keeps an argument containing a space as one argument', () => {
    expect(lines(execCommand(process.execPath, [printer, 'two words'])))
      .toEqual(['0=<two words>']);
  });

  it('does not let shell operators inside an argument run as commands', () => {
    expect(lines(execCommand(process.execPath, [printer, 'zzz && echo PWNED'])))
      .toEqual(['0=<zzz && echo PWNED>']);
    expect(lines(execCommand(process.execPath, [printer, 'zzz | echo PWNED'])))
      .toEqual(['0=<zzz | echo PWNED>']);
  });

  it('keeps quotes, carets and percent signs intact', () => {
    expect(lines(execCommand(process.execPath, [printer, 'say "hi"', 'a^b', '%PATH%'])))
      .toEqual(['0=<say "hi">', '1=<a^b>', '2=<%PATH%>']);
  });

  it('finds a repository whose path contains a space', () => {
    const repo = path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'cp-space-')), 'dir with space');
    fs.mkdirSync(repo, { recursive: true });
    expect(execCommand('git', ['init', '-q', repo])).not.toBeNull();

    const root = execCommand('git', ['-C', repo, 'rev-parse', '--show-toplevel']);
    expect(root).not.toBeNull();
    expect(fs.realpathSync(root)).toBe(fs.realpathSync(repo));
  });

  // Guards the retry, not the old bug: a failed direct spawn now falls through
  // to cmd.exe, which must not turn "no such program" into an empty string.
  it('returns null for a program that does not exist', () => {
    expect(execCommand('cp-no-such-tool-xyz', ['--version'])).toBeNull();
  });

  /** A .cmd wrapper on PATH that forwards its arguments to the argv printer. */
  function wrapperOnPath() {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'cp-wrapper-'));
    fs.writeFileSync(path.join(dir, 'cp-printer.cmd'),
      `@echo off\r\n"${process.execPath}" "${printer}" %*\r\n`);
    return { env: { ...process.env, PATH: dir + path.delimiter + process.env.PATH } };
  }

  // .cmd/.bat wrappers cannot be spawned directly at all (Node refuses with
  // EINVAL/ENOENT), so they are the one case that still goes through cmd.exe —
  // and therefore the one case where a shell parser sees the arguments.
  // Windows-only by nature.
  (onWindows ? it : it.skip)('runs a .cmd wrapper and keeps its arguments intact', () => {
    const out = execCommand(
      'cp-printer',
      ['two words', 'a^b', 'C:\\Users\\R&D\\project', 'say "hi"'],
      wrapperOnPath(),
    );
    expect(lines(out)).toEqual([
      '0=<two words>', '1=<a^b>', '2=<C:\\Users\\R&D\\project>', '3=<say "hi">',
    ]);
  });

  // Node quotes an argument only when it contains whitespace, so a
  // metacharacter with no spaces around it reaches cmd.exe bare — `x&&echo.>f`
  // used to run as a second command and really created the file.
  (onWindows ? it : it.skip)('does not let a .cmd wrapper argument run a second command', () => {
    const opts = wrapperOnPath();
    const mark = path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'cp-mark-')), 'INJECTED.txt');

    const out = execCommand('cp-printer', [`x&&echo.>${mark}`, `y>${mark}`], opts);

    expect(fs.existsSync(mark)).toBe(false);
    expect(lines(out)).toEqual([`0=<x&&echo.>${mark}>`, `1=<y>${mark}>`]);
  });

  it('writes nothing to stderr — no DEP0190 deprecation noise', () => {
    const script = `require(${JSON.stringify(utilsPath)}).execCommand('git', ['--version']);`;
    const res = spawnSync(process.execPath, ['-e', script], { encoding: 'utf8' });
    expect(res.stderr).toBe('');
  });
});

// ---------------------------------------------------------------------------
// beads version
// ---------------------------------------------------------------------------
// An old bd does not announce itself: it fails one command at a time with
// "unknown command". These two functions turn that into one line at session
// start — so a false positive would nag every session, and a false negative
// only costs the warning.

const {
  BD_MIN_VERSION,
  parseBdVersion,
  versionBelow,
} = require('../../templates/hooks/hook-utils.cjs');

describe('parseBdVersion', () => {
  it('reads the version out of real `bd version` output', () => {
    expect(parseBdVersion('bd version 1.1.0 (8e4e59d39: HEAD@8e4e59d39f34)')).toBe('1.1.0');
  });

  it('reads a multi-digit version', () => {
    expect(parseBdVersion('bd version 10.2.13')).toBe('10.2.13');
  });

  it('returns null for empty output', () => {
    expect(parseBdVersion('')).toBeNull();
    expect(parseBdVersion(null)).toBeNull();
  });

  it('returns null when there is no version in the text', () => {
    expect(parseBdVersion('bd version unknown')).toBeNull();
  });
});

describe('versionBelow', () => {
  it('is true below the minimum', () => {
    expect(versionBelow('1.0.9', '1.1.0')).toBe(true);
    expect(versionBelow('0.9.0', '1.1.0')).toBe(true);
  });

  it('is false at or above the minimum', () => {
    expect(versionBelow('1.1.0', '1.1.0')).toBe(false);
    expect(versionBelow('1.1.1', '1.1.0')).toBe(false);
    expect(versionBelow('2.0.0', '1.1.0')).toBe(false);
  });

  it('compares numbers, not strings', () => {
    expect(versionBelow('1.10.0', '1.9.0')).toBe(false);
    expect(versionBelow('1.9.0', '1.10.0')).toBe(true);
  });

  it('stays silent on anything it cannot read', () => {
    expect(versionBelow(null, '1.1.0')).toBe(false);
    expect(versionBelow(undefined, '1.1.0')).toBe(false);
    expect(versionBelow('nonsense', '1.1.0')).toBe(false);
    expect(versionBelow('1.1', '1.1.0')).toBe(false);
  });
});

describe('BD_MIN_VERSION', () => {
  it('is a three-part version', () => {
    expect(BD_MIN_VERSION).toMatch(/^\d+\.\d+\.\d+$/);
  });
});

// ---------------------------------------------------------------------------
// Where a hook thinks it is, and whether beads lives there
// ---------------------------------------------------------------------------
// Started from the plugin, these files sit in the plugin's own checkout, which
// has a .claude/ and a .beads/ of its own. Walking up from __dirname would then
// answer with the plugin instead of the project being worked on, and every
// check built on the answer would be about the wrong place.

const { hasBeads, isPluginInstall } = require(utilsPath);

function withPluginRoot(value, run) {
  const saved = process.env.CLAUDE_PLUGIN_ROOT;
  if (value === undefined) delete process.env.CLAUDE_PLUGIN_ROOT;
  else process.env.CLAUDE_PLUGIN_ROOT = value;
  try {
    return run();
  } finally {
    if (saved === undefined) delete process.env.CLAUDE_PLUGIN_ROOT;
    else process.env.CLAUDE_PLUGIN_ROOT = saved;
  }
}

function askInSubprocess(expression, cwd, env) {
  const script = `const u=require(${JSON.stringify(utilsPath)});`
    + `process.stdout.write(String(${expression}));`;
  return spawnSync(process.execPath, ['-e', script], {
    cwd,
    encoding: 'utf8',
    env: { ...process.env, CLAUDE_PROJECT_DIR: '', CLAUDE_PLUGIN_ROOT: '', ...env },
  }).stdout;
}

describe('isPluginInstall', () => {
  it('is true only when a plugin root is in the environment', () => {
    expect(withPluginRoot('/x/plugins/claude-protocol',
                          () => isPluginInstall())).toBe(true);
    expect(withPluginRoot(undefined, () => isPluginInstall())).toBe(false);
  });
});

describe('hasBeads', () => {
  it('is true where the project tracks work in beads', () => {
    const project = fs.mkdtempSync(path.join(os.tmpdir(), 'hu-beads-'));
    fs.mkdirSync(path.join(project, '.beads'));

    expect(withEnv(project, () => hasBeads())).toBe(true);
  });

  it('is false where it does not', () => {
    const project = fs.mkdtempSync(path.join(os.tmpdir(), 'hu-plain-'));

    expect(withEnv(project, () => hasBeads())).toBe(false);
  });
});

describe('getProjectDir under a plugin', () => {
  it('answers with CLAUDE_PROJECT_DIR whenever it is set', () => {
    const project = fs.mkdtempSync(path.join(os.tmpdir(), 'hu-env-'));

    expect(askInSubprocess('u.getProjectDir()', os.tmpdir(),
                           { CLAUDE_PROJECT_DIR: project })).toBe(project);
  });

  it('walks up from the hook file for a copy installed in a project', () => {
    expect(askInSubprocess('u.getProjectDir()', os.tmpdir(), {})).toBe(repoRoot);
  });

  it('does not walk up to the plugin when it was started from one', () => {
    const elsewhere = fs.mkdtempSync(path.join(os.tmpdir(), 'hu-cwd-'));

    const answer = askInSubprocess('u.getProjectDir()', elsewhere,
                                   { CLAUDE_PLUGIN_ROOT: '/x/plugins/claude-protocol' });

    expect(answer).not.toBe(repoRoot);
  });
});
