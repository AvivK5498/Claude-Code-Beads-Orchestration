# Claude Protocol v3 — Design Decisions

Every decision made during the v2 → v3 rewrite. Context, alternatives, rationale.

---

## 1. What Works and What Doesn't for Claude Code

### 1.1 Personas — useless

**Before:** 7 agents with names and personalities (Rex — code reviewer, Mira — merge supervisor, Scout, Detective, Architect, Scribe, Discovery).

**Decision:** Removed all personas. Kept 2 agents (code-reviewer, merge-supervisor) with no names — only technical instructions.

**Why:** Personas come from GPT-3 era prompting ("you are a senior developer"). Claude Code has strong built-in instructions. "You are Rex, an adversarial code reviewer" doesn't improve review quality. A concrete checklist (check SQL injection, check error handling) does. Personas just fill context.

### 1.2 Multi-level agent hierarchy — overkill

**Before:** Orchestrator → Tech Supervisor (generated dynamically per-stack) → Worker. Plus 5 specialized agents (Scout for search, Detective for debugging, Architect for design, etc.).

**Decision:** Orchestrator → `Task(subagent_type="general-purpose")`. No intermediate supervisors. No specialized agents.

**Why:**
- Specialized agents duplicate built-in Claude Code tools (Glob, Grep, Read = "Scout")
- Tech Supervisors were generated from external sources (Apple Web Interface Guidelines, React best practices) — 500+ lines of context each, while Claude already knows these technologies
- Each intermediate agent = context loss and data transfer overhead
- Project conventions belong in `.claude/rules/` (auto-loaded) — they reach every agent context automatically

### 1.3 Constraints > Instructions

**Key principle:** Blocking bad actions via hooks is more effective than asking "please don't do that."

**Examples:**
- "Don't commit to main" (instruction) → `enforce-branch-before-edit.cjs` physically blocks Edit/Write on main (constraint)
- "Use description when creating bead" (instruction) → `bash-guard.cjs` blocks `bd create` without `-d` (constraint)
- "Don't skip pre-commit hooks" (instruction) → hook blocks `git --no-verify` (constraint)

**Why:** Claude may ignore an instruction in a long context or after compaction. A hook fires every time.

### 1.4 Trigger-based rules > Reference documents

**Before:** Long standard documents (200+ lines each) that Claude should "remember."

**Decision:** Rules rewritten as triggers — "when you do X, stop and do Y."

**Why:** Claude doesn't re-read rules on every action. But a trigger ("creating API endpoint → add logging") fires at code-writing time — closer to muscle memory than a reference doc.

### 1.5 INoT (Instruction, Nudge, output Template) — partially useful

**Discussed:** Prompt structuring method with Instruction, Nudge, and Template.

**Decision:** Not adopted as a standalone methodology. But the output template principle is already in use — subagent completion report has a fixed format (BEAD COMPLETE, Worktree, Checklist, Files, Tests, Summary) verified by a hook.

**Why:** INoT works for one-shot prompts. For system rules (rules, hooks), triggers work better.

---

## 2. Development Rules

### 2.1 implementation-standard.md

**Kept:**
- User-facing process (discussion → spec → confirmation → implementation)
- Code metrics (CC < 10, function < 30 lines, class < 200, nesting < 4)
- Rule of 3 alternatives for architectural decisions
- Self-review by subagent after task completion
- `/simplify` trigger when >3 files or >50 lines changed

**Removed:**
- Everything that duplicates built-in Claude Code instructions (don't modify unread files, prefer Edit, don't create unnecessary files)
- Generic phrases ("write quality code")

### 2.2 logging-standard.md

**Decision:** Trigger-based — list of situations to stop and think about logging (API endpoint, external call, payments, catch/except, etc.).

**Why:** Logging is exactly what gets forgotten. Not because developers don't know how — because they don't think about it at code-writing time. Triggers fix this.

### 2.3 tdd-workflow.md

**Decision:** Triggers + exceptions. When TDD activates (new function, bug fix, behavior change). When NOT needed (configs, DTOs, migrations).

**Why:** TDD as an absolute rule doesn't work — Claude would write tests for config files. Triggers + exceptions provide balance.

### 2.4 `/simplify` (Boris Cherny)

**Decision:** Integrated as a mandatory self-review step: if >3 files or >50 lines changed — invoke `/simplify`.

**Why:** Built-in Claude Code skill that finds duplication, dead code, simplification opportunities. Free and effective.

---

## 3. Beads Workflow

### 3.1 Beads as single source of truth

**Decision:** ALL tasks are created in beads. Not in markdown, not in TodoWrite, not "in your head." Beads survive compaction, session restarts, context switches.

**Why:** The main Claude Code problem is context loss. After compaction or a new session, the agent doesn't remember what it planned. Beads = persistent storage always available via `bd list`, `bd ready`.

### 3.2 Mandatory size check after planning

**Decision:** After plan approval — mandatory check before creating beads:
- >3 files or >1 domain → epic with children
- >50 lines → consider decomposition
- Otherwise → single bead

**Why:** Without this, Claude either creates one giant bead or splits trivial work into 10 subtasks. Concrete criteria remove subjectivity.

### 3.3 Plan → Beads → Work (strict order)

**Decision:** After plan mode, ALL tasks from the plan must be created as beads BEFORE implementation starts.

**Why:** Starting work before creating beads = losing tasks on compaction. Plan lives only in context. Beads live in the database.

### 3.4 Status discipline

**Decision:**
- `open` → created
- `in_progress` → work started
- `inreview` → submitted for review (enforced by validate-completion hook)
- `done` → closed

**Enforcement:**
- `inreview` on completion — hook blocks subagent if not set
- `in_progress` on start — instruction only (no enforcement, bd doesn't store status history)
- Close after merge — `session-start.cjs` shows ACTION REQUIRED for merged worktrees and beads in `inreview`

### 3.5 Checklist verification on completion

**Decision:** Subagent must before closing:
1. Re-read `bd show {ID}` — compare description with results
2. Include `Checklist:` section in completion report with `[x]` marks

**Enforcement:** Hook `validate-completion.cjs` blocks if no `Checklist:` or unchecked `[ ]` items.

**Why:** Without this, Claude often says "done" having completed 3 of 5 items. Especially after compaction.

### 3.6 Discovered tech debt → bead

**Decision:** If tech debt, bug, or improvement is found during work — immediately `bd create`, don't try to fix inline.

**Why:** "I'll fix it later" = never. A bead won't be forgotten.

### 3.7 LEARNED comments — specific, not formal

**Decision:** LEARNED comment must contain: problem → solution → context.

**BAD:** `LEARNED: fixed async issue`
**GOOD:** `LEARNED: pg connection pool exhaustion under load → set max=20 and idle_timeout=30s. Default max=10 caused 503s at >50 rps`

**Why:** Vague entries are useless for recall. Specific ones are found by keywords and contain ready solutions.

### 3.8 bd command reference in rules

**Decision:** Added available bd commands table to `beads-workflow.md` with note "use ONLY these — do NOT invent commands."

**Why:** Claude invents nonexistent commands (e.g. `bd export`). An explicit list solves the problem.

---

## 4. Knowledge Base

### 4.1 Recall before every investigation

**Decision:** Before any investigation — mandatory `node .beads/memory/recall.cjs "keyword"`.

**Why:** Without this, Claude re-solves problems that were already solved in previous sessions.

### 4.2 docs/issues/*.md — rejected

**Discussed:** Creating a markdown note after each closed task.

**Decision:** Not doing it. Beads + LEARNED comments + recall.cjs cover this without duplication.

**Why:** `bd show {ID}` + `bd comments {ID}` already contain everything. Markdown = double work with no additional value for the agent.

---

## 5. Infrastructure

### 5.1 Node.js hooks (.cjs), not bash

**Decision:** All hooks are CommonJS Node.js. Not bash, not ESM.

**Why:** Cross-platform (Windows). CommonJS because Claude Code hooks run via `node`, ESM would require package.json with `"type": "module"` in the hooks directory.

### 5.2 Bootstrap doesn't overwrite existing files

**Decision:**
- `CLAUDE.md` — if exists, appends beads section via separator
- `settings.json` — merges hooks by event type, doesn't duplicate existing ones
- `.gitignore` — appends missing entries

**Why:** Users may install beads into an existing project with configured CLAUDE.md and hooks.

### 5.3 `bd init` with timeout

**Decision:** `subprocess.run` with `timeout=15, stdin=DEVNULL`. On timeout — create `.beads/` manually.

**Why:** `bd init` can hang if Dolt server isn't running. Bootstrap must not block.

### 5.4 npm link for local development

**Decision:** `npm link` — one-time command, after which `npx claude-protocol init` works from any project.

**Why:** Package not yet published to npm. `npm link` creates a symlink to current code — changes take effect without rebuilding.

### 5.5 `/create-beads-orchestration` skill — removed

**Decision:** Removed. Installation only via `npx claude-protocol init`.

**Why:** The skill duplicated CLI. One installation method is simpler to maintain.

---

## 6. What Was Removed and Why

| Removed | Why |
|---------|-----|
| 5 agents (Scout, Detective, Architect, Scribe, Discovery) | Duplicate built-in Claude Code capabilities |
| Tech Supervisor generation | 500+ lines of context with no benefit, conventions belong in `.claude/rules/` |
| MCP Provider Delegator | Separate infrastructure for external providers, unnecessary |
| Web Interface Guidelines, React Best Practices | Claude already knows these, just fills context |
| Beads workflow injection (3 files) | Replaced by single `beads-workflow.md` in rules (auto-loaded) |
| 19 bash hooks | Replaced by 8 Node.js hooks (cross-platform) |
| `skills/subagents-discipline/` | Subagent rules work better via rules + hooks |
| `templates/ui-constraints.md` | Specific to Apple/SwiftUI, not universal |
| `scripts/postinstall.js` | Removed automatic installation on npm install |
| SKILL.md (root + skills/) | Installation only via CLI, skill not needed |

---

## 7. Final v3 Architecture

```
npx claude-protocol init
  |
  +-- .beads/                    # Task database (Dolt/SQLite)
  |   +-- memory/knowledge.jsonl # Knowledge base
  |
  +-- .claude/
  |   +-- agents/
  |   |   +-- code-reviewer.md   # Adversarial review (no persona)
  |   |   +-- merge-supervisor.md # Conflict resolution (no persona)
  |   +-- hooks/                 # 8 Node.js enforcement hooks
  |   +-- rules/
  |   |   +-- beads-workflow.md  # Auto-loaded: workflow + bd reference
  |   |   +-- [dev rules]
  |   +-- skills/
  |   |   +-- project-discovery/ # Extract project conventions
  |   +-- settings.json          # Hook configuration
  |
  +-- CLAUDE.md                  # Orchestrator instructions
```

**Principle:** Minimum files, maximum enforcement. Constraints > Instructions. Beads = single source of truth.
