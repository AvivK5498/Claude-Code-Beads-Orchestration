# AGENTS.md

## Project

[Project]

## Mux + beads workflow

This project uses `bd` (beads) for issue tracking and Mux for agent execution.

### Required workflow

1. `bd ready --json` to find unblocked work
2. `bd update <id> --status in_progress --json` when you start
3. Implement in the active workspace/worktree
4. Validate changes
5. `bd close <id> --reason "Completed" --json` when done

### Mux hook notes

- `.mux/init` primes beads context (`bd prime --stealth`) for new workspaces
- `.mux/tool_post` runs `bd sync` after file edits
- `.mux/tool_env` adds `~/bin` to `PATH` for shells that do not include it

### Instruction layering

Mux reads instruction layers from:
- `~/.mux/AGENTS.md` (global)
- `<workspace>/.mux/AGENTS.md` (workspace)

Use `.mux/AGENTS.local.md` for personal local overrides (gitignored).

### Rules

- Use `bd` for all task tracking
- Keep changes minimal and reviewable
- Run relevant validation before reporting done
