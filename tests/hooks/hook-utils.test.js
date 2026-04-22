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
