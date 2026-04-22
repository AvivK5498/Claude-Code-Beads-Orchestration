import { describe, it, expect } from 'vitest';
import { execFileSync } from 'child_process';
import path from 'path';

const HOOK_PATH = path.resolve(__dirname, '../../templates/hooks/enforce-branch-before-edit.cjs');

// The hook bails out early when process.cwd() contains '.worktrees' (see
// enforce-branch-before-edit.cjs). If vitest runs from inside a bd worktree,
// that bypass fires and the hook exits with no stdout, breaking the branch-
// protection tests. Pin the subprocess cwd to the main repo root so the tests
// exercise realistic non-worktree behavior regardless of where vitest starts.
const MAIN_REPO_ROOT = path.dirname(
  execFileSync('git', ['rev-parse', '--path-format=absolute', '--git-common-dir'], {
    encoding: 'utf8',
  }).trim()
);

function runHook(stdinData) {
  const input = JSON.stringify(stdinData);
  try {
    const stdout = execFileSync('node', [HOOK_PATH], {
      input,
      cwd: MAIN_REPO_ROOT,
      encoding: 'utf8',
      timeout: 5000,
      stdio: ['pipe', 'pipe', 'pipe'],
    });
    return { stdout, exitCode: 0 };
  } catch (err) {
    return { stdout: err.stdout || '', stderr: err.stderr || '', exitCode: err.status };
  }
}

describe('enforce-branch-before-edit hook', () => {
  describe('always-allowed paths', () => {
    it('allows CLAUDE.md edits', () => {
      const result = runHook({
        tool_name: 'Edit',
        tool_input: { file_path: '/project/CLAUDE.md', old_string: 'a', new_string: 'b' },
      });
      expect(result.exitCode).toBe(0);
      expect(result.stdout).not.toContain('deny');
    });

    it('allows CLAUDE.local.md edits', () => {
      const result = runHook({
        tool_name: 'Write',
        tool_input: { file_path: '/project/CLAUDE.local.md', content: 'test' },
      });
      expect(result.exitCode).toBe(0);
      expect(result.stdout).not.toContain('deny');
    });

    it('allows .claude/plans edits', () => {
      const result = runHook({
        tool_name: 'Write',
        tool_input: { file_path: '/project/.claude/plans/plan.md', content: 'test' },
      });
      expect(result.exitCode).toBe(0);
      expect(result.stdout).not.toContain('deny');
    });

    it('allows git-issues.md edits', () => {
      const result = runHook({
        tool_name: 'Edit',
        tool_input: { file_path: '/project/git-issues.md', old_string: 'a', new_string: 'b' },
      });
      expect(result.exitCode).toBe(0);
      expect(result.stdout).not.toContain('deny');
    });

    it('allows edits inside .worktrees', () => {
      const result = runHook({
        tool_name: 'Edit',
        tool_input: { file_path: '/project/.worktrees/bd-001/src/file.ts', old_string: 'a', new_string: 'b' },
      });
      expect(result.exitCode).toBe(0);
      expect(result.stdout).not.toContain('deny');
    });

    it('allows .claude memory files', () => {
      const result = runHook({
        tool_name: 'Write',
        tool_input: { file_path: '/project/.claude/projects/abc/memory/MEMORY.md', content: 'test' },
      });
      expect(result.exitCode).toBe(0);
      expect(result.stdout).not.toContain('deny');
    });
  });

  describe('branch protection', () => {
    // These tests run in the actual git context of this repo.
    // The repo is on some branch — behavior depends on that branch.
    // We test that the hook produces output (ask or deny) for non-exempt files.

    it('produces output for non-exempt files on any branch', () => {
      const result = runHook({
        tool_name: 'Edit',
        tool_input: { file_path: '/tmp/some-project/src/app.ts', old_string: 'a', new_string: 'b' },
      });
      expect(result.exitCode).toBe(0);
      // On main → deny, on feature branch → ask. Either way, stdout is non-empty.
      expect(result.stdout.length).toBeGreaterThan(0);
    });

    it('denies on main branch or asks on feature branch', () => {
      const result = runHook({
        tool_name: 'Write',
        tool_input: { file_path: '/tmp/project/src/component.tsx', content: 'export default {}' },
      });
      expect(result.exitCode).toBe(0);
      // On main → deny with branch message, on feature → ask with file info
      const parsed = JSON.parse(result.stdout);
      const decision = parsed.hookSpecificOutput.permissionDecision;
      expect(['deny', 'ask']).toContain(decision);
    });
  });

  describe('Edit vs Write size info', () => {
    it('reports line count for Edit tool', () => {
      const result = runHook({
        tool_name: 'Edit',
        tool_input: {
          file_path: '/tmp/project/src/file.ts',
          old_string: 'line1\nline2',
          new_string: 'line1\nline2\nline3\nline4',
        },
      });
      // On feature branch, should include size info in ask message
      if (result.stdout.includes('ask')) {
        expect(result.stdout).toMatch(/~\d+ lines/);
      }
    });

    it('reports "new file" for Write tool', () => {
      const result = runHook({
        tool_name: 'Write',
        tool_input: {
          file_path: '/tmp/project/src/new.ts',
          content: 'const x = 1;\nconst y = 2;\n',
        },
      });
      if (result.stdout.includes('ask')) {
        expect(result.stdout).toContain('new file');
      }
    });
  });
});
