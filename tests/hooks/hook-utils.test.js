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

  it('returns null for a program that does not exist', () => {
    expect(execCommand('cp-no-such-tool-xyz', ['--version'])).toBeNull();
  });

  // .cmd/.bat wrappers cannot be spawned directly at all (Node refuses with
  // EINVAL/ENOENT), so they go through cmd.exe. Windows-only by nature.
  (onWindows ? it : it.skip)('runs a .cmd wrapper and keeps its arguments intact', () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'cp-wrapper-'));
    const wrapper = path.join(dir, 'cp-printer.cmd');
    fs.writeFileSync(wrapper, `@echo off\r\n"${process.execPath}" "${printer}" %*\r\n`);

    const out = execCommand('cp-printer', ['two words', 'zzz && echo PWNED'], {
      env: { ...process.env, PATH: dir + path.delimiter + process.env.PATH },
    });
    expect(lines(out)).toEqual(['0=<two words>', '1=<zzz && echo PWNED>']);
  });

  it('writes nothing to stderr — no DEP0190 deprecation noise', () => {
    const script = `require(${JSON.stringify(utilsPath)}).execCommand('git', ['--version']);`;
    const res = spawnSync(process.execPath, ['-e', script], { encoding: 'utf8' });
    expect(res.stderr).toBe('');
  });
});
