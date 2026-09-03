import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { execFileSync } from 'child_process';
import path from 'path';

const HOOK_PATH = path.resolve(__dirname, '../../templates/hooks/bash-guard.cjs');

/**
 * Run the bash-guard hook as a subprocess with given stdin JSON.
 * Returns { stdout, stderr, exitCode }.
 */
function runHook(stdinData, env = {}) {
  const input = JSON.stringify(stdinData);
  try {
    const stdout = execFileSync('node', [HOOK_PATH], {
      input,
      encoding: 'utf8',
      timeout: 5000,
      env: { ...process.env, ...env },
      stdio: ['pipe', 'pipe', 'pipe'],
    });
    return { stdout, exitCode: 0 };
  } catch (err) {
    return { stdout: err.stdout || '', stderr: err.stderr || '', exitCode: err.status };
  }
}

function makeInput(command) {
  return {
    tool_name: 'Bash',
    tool_input: { command },
  };
}

describe('bash-guard hook', () => {
  describe('git safety', () => {
    it('denies git commit --no-verify', () => {
      const result = runHook(makeInput('git commit --no-verify -m "skip hooks"'));
      expect(result.exitCode).toBe(0);
      expect(result.stdout).toContain('deny');
      expect(result.stdout).toContain('--no-verify');
    });

    it('allows normal git commit', () => {
      const result = runHook(makeInput('git commit -m "normal commit"'));
      expect(result.exitCode).toBe(0);
      expect(result.stdout).toBe(''); // exit(0) with no output = allow
    });

    it('allows git status', () => {
      const result = runHook(makeInput('git status'));
      expect(result.exitCode).toBe(0);
      expect(result.stdout).toBe('');
    });
  });

  describe('git worktree guard', () => {
    it('denies git worktree add', () => {
      const result = runHook(makeInput('git worktree add ../foo -b mybranch'));
      expect(result.exitCode).toBe(0);
      expect(result.stdout).toContain('deny');
      expect(result.stdout).toContain('bd worktree create');
    });

    it('denies git worktree add with extra flags and paths', () => {
      const result = runHook(makeInput('git worktree add --detach .worktrees/bd-1 HEAD'));
      expect(result.exitCode).toBe(0);
      expect(result.stdout).toContain('deny');
    });

    it('allows git worktree remove', () => {
      const result = runHook(makeInput('git worktree remove --force .worktrees/bd-1'));
      expect(result.exitCode).toBe(0);
      expect(result.stdout).toBe('');
    });

    it('allows git worktree prune', () => {
      const result = runHook(makeInput('git worktree prune'));
      expect(result.exitCode).toBe(0);
      expect(result.stdout).toBe('');
    });

    it('allows git worktree list', () => {
      const result = runHook(makeInput('git worktree list'));
      expect(result.exitCode).toBe(0);
      expect(result.stdout).toBe('');
    });

    it('does not match "add" appearing elsewhere (e.g. branch named add)', () => {
      const result = runHook(makeInput('git worktree remove add-feature'));
      expect(result.exitCode).toBe(0);
      expect(result.stdout).toBe('');
    });

    it('does not block plain git add', () => {
      const result = runHook(makeInput('git add -A'));
      expect(result.exitCode).toBe(0);
      expect(result.stdout).toBe('');
    });
  });

  describe('bd create validation', () => {
    it('denies bd create without description', () => {
      const result = runHook(makeInput('bd create --title="My task"'));
      expect(result.exitCode).toBe(0);
      expect(result.stdout).toContain('deny');
      expect(result.stdout).toContain('description');
    });

    it('allows bd create with -d flag', () => {
      const result = runHook(makeInput('bd create --title="Task" -d "Description here"'));
      expect(result.exitCode).toBe(0);
      expect(result.stdout).not.toContain('deny');
    });

    it('allows bd create with --description flag', () => {
      const result = runHook(makeInput('bd create --title="Task" --description "Full desc"'));
      expect(result.exitCode).toBe(0);
      expect(result.stdout).not.toContain('deny');
    });

    it('allows bd create with --description= flag', () => {
      const result = runHook(makeInput('bd create --title="Task" --description="Full desc"'));
      expect(result.exitCode).toBe(0);
      expect(result.stdout).not.toContain('deny');
    });
  });

  describe('non-git non-bd commands', () => {
    it('allows arbitrary commands', () => {
      const result = runHook(makeInput('npm test'));
      expect(result.exitCode).toBe(0);
      expect(result.stdout).toBe('');
    });

    it('allows ls', () => {
      const result = runHook(makeInput('ls -la'));
      expect(result.exitCode).toBe(0);
      expect(result.stdout).toBe('');
    });
  });

  describe('CLAUDE_TOOL_INPUT env var', () => {
    it('reads command from env var when present', () => {
      const result = runHook(
        { tool_name: 'Bash' },
        { CLAUDE_TOOL_INPUT: JSON.stringify({ command: 'git commit --no-verify' }) }
      );
      expect(result.exitCode).toBe(0);
      expect(result.stdout).toContain('deny');
    });
  });

  describe('command chains', () => {
    it('denies git commit --no-verify hidden behind cd', () => {
      const result = runHook(makeInput('cd packages/db && git commit --no-verify -m "x"'));
      expect(result.exitCode).toBe(0);
      expect(result.stdout).toContain('deny');
      expect(result.stdout).toContain('--no-verify');
    });

    it('denies git worktree add hidden behind cd', () => {
      const result = runHook(makeInput('cd .. && git worktree add ../foo -b mybranch'));
      expect(result.stdout).toContain('deny');
      expect(result.stdout).toContain('bd worktree create');
    });

    it('denies bd create without description later in a chain', () => {
      const result = runHook(makeInput('git status && bd create "Task"'));
      expect(result.stdout).toContain('deny');
      expect(result.stdout).toContain('description');
    });

    it('checks every command, not just the first guarded one', () => {
      const result = runHook(makeInput('git status && echo ok && bd create "Task"'));
      expect(result.stdout).toContain('deny');
    });

    it('allows a chain where every command is fine', () => {
      const result = runHook(makeInput('cd packages/db && git status && ls'));
      expect(result.stdout).toBe('');
    });

    it('does not deny --no-verify quoted inside another command', () => {
      const result = runHook(makeInput('echo "--no-verify is blocked" && git status'));
      expect(result.stdout).toBe('');
    });

    it('does not deny a flag that belongs to a different command', () => {
      const result = runHook(makeInput('npm test --no-verify'));
      expect(result.stdout).toBe('');
    });
  });

});
