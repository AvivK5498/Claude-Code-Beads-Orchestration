# IMPLEMENTATION STANDARD

Applies once you are writing code. How work *starts* — understanding, reuse or
write, plan — is `pre-code-workflow.md`.

## Code Metrics

- Cyclomatic Complexity < 10
- Function length < 30 lines
- Class length < 200 lines
- Parameters < 5 (use object for >5)
- Nesting < 4 levels

## Rule of 3 Alternatives (for architectural decisions)

1. Come up with 3 solutions
2. Pick the simplest that works
3. Avoid the first thing that comes to mind

## Verification Cycle

After each code block: lint → compile → test → run. Not at the end of the task —
after each block, so a failure points at the last thing you wrote.

## Self-review (after completing a task)

Launch a subagent to review written code. Checklist:

- Are there unhandled errors being silently swallowed?
- Are there SQL injection, XSS, or other vulnerabilities at input boundaries?
- Are metrics met (function <30, class <200, nesting <4)?
- Is there duplication worth extracting?
- Is logging added per logging-standard triggers?
- Are tests written per tdd-workflow triggers?
- Does code match project conventions (project CLAUDE.md)?

If >3 files or >50 lines changed — run `/simplify` for cleanup and refactoring.

## Banned

- Backward compatibility that nobody asked for
- Leaving code "for reference" — deleted means deleted
- Rushing: better to spend the time and write it well than redo it later
- Guessing when uncertain — ask, and state your recommendation with the question
