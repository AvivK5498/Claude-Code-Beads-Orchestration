# IMPLEMENTATION STANDARD

## Core Development Principles (HIGHEST PRIORITY)

**CRITICAL:** These principles take highest priority over detailed practices.

### Key fundamentals:

1. **Write elegant code that solves the task**
2. **Do not add backward compatibility unless explicitly requested**
3. **After each code block:** lint → compile → test → run
4. **Code must be:** clean, readable, DRY, prefer editing over adding
5. **Avoid:** unnecessary rollbacks, excessive versioning, over-testing
6. **Quality over speed** — better to spend time and write well
7. **When uncertain — ask** while stating your recommendations

## Process with User

1. **Discussion** — explore options, clarifying questions
2. **Specification** — formulate, break into tasks, get confirmation
3. **Implementation** — ask **"Shall we proceed?"**, wait for confirmation

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

After each code block: lint → compile → test → run

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

## Quality Over Speed

Better to spend time and write well than rush and redo later.
