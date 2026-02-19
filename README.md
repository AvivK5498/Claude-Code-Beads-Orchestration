<div align="center">

# THE CLAUDE PROTOCOL

**Enforcement-first orchestration for Claude Code, with optional Mux workspace integration. Every agent tracked. Every decision logged. Nothing gets lost.**

**Claude Code plans great. Without structure, nothing survives past one session.**

[![npm version](https://img.shields.io/npm/v/beads-orchestration?style=for-the-badge&logo=npm&logoColor=white&color=CB3837)](https://www.npmjs.com/package/beads-orchestration)
[![GitHub stars](https://img.shields.io/github/stars/AvivK5498/The-Claude-Protocol?style=for-the-badge&logo=github&color=181717)](https://github.com/AvivK5498/The-Claude-Protocol)
[![License](https://img.shields.io/badge/license-MIT-blue?style=for-the-badge)](LICENSE)

<br>

```bash
npx skills add AvivK5498/The-Claude-Protocol
```

**macOS and Linux.**

<br>

![The Claude Protocol — Kanban UI](screenshots/kanbanui.png)

<br>

[Why This Exists](#why-this-exists) · [How It Works](#how-it-works) · [Getting Started](#getting-started) · [Hooks](#hooks)

</div>

---

## Why This Exists

Claude Code is the best coding agent out there. But let it run unsupervised and you get agents editing main, commits without PRs, lost context every session, and zero traceability on what was done and why.

Plan mode helps — until you need to coordinate across files, track what was planned vs what shipped, or pick up a task three sessions later. Plans vanish. Context resets. Investigation gets redone from scratch.

The Claude Protocol is the enforcement layer. It wraps Claude Code with 13 hooks that physically block bad actions, isolates every task in its own git worktree, and documents everything automatically — dispatch prompts, agent knowledge, decisions, all of it. [Beads](https://github.com/steveyegge/beads) (git-native tickets) track every unit of work from creation to merge.

The complexity is in the system. What you see: Claude plans with you, you approve, agents execute in isolation, PRs get merged. Done.

---

## How It Works

```
┌─────────────────────────────────────────┐
│         ORCHESTRATOR (Co-Pilot)         │
│  Plans with you (Plan mode)            │
│  Investigates with Grep/Read/Glob       │
│  Delegates implementation via Task()    │
└──────────────────┬──────────────────────┘
                   │
       ┌───────────┼───────────┐
       ▼           ▼           ▼
  ┌─────────┐ ┌─────────┐ ┌─────────┐
  │ react-  │ │ python- │ │ nextjs- │
  │supervisor│ │supervisor│ │supervisor│
  └────┬────┘ └────┬────┘ └────┬────┘
       │           │           │
  .worktrees/ .worktrees/ .worktrees/
  bd-BD-001   bd-BD-002   bd-BD-003
```

**The orchestrator** investigates, discusses with you, and plans. It never writes code. Dispatch prompts are auto-logged to the bead so nothing gets lost.

**Supervisors** are created automatically based on your tech stack. They read bead comments for full context, work in isolated worktrees, and push clean PRs.

**Beads** are git-native tickets. Every task, every epic, every dependency — tracked in your repo, not a third-party service. One bead = one unit of work = one worktree = one PR.

### Workflow

**Standalone** — Investigate → plan → approve → create bead → dispatch supervisor → worktree → PR → merge.

**Epics** — Cross-domain work (DB + API + frontend) becomes an epic with enforced child dependencies. Each child gets its own worktree. Dependencies prevent dispatching out of order.

**Quick Fix** — For trivial changes (<10 lines), the orchestrator can edit directly on a feature branch. The hook prompts the user for approval with file name and change size. Hard blocked on main — must use bead workflow there.

Every task goes through beads — unless the user explicitly approves a quick fix.

### Kanban UI

The Claude Protocol pairs with the [Beads Kanban UI](https://github.com/AvivK5498/Beads-Kanban-UI) for visual task management and GitOps directly from the browser. Track epics, subtasks, dependencies, and PR status across columns — without leaving the board.

### Mux Integration (Optional)

You can also bootstrap **Mux-compatible workspace files** to align with Mux's instruction and hook model:

- `.mux/AGENTS.md` (workspace instruction layer)
- `.mux/init` (runs `bd prime --stealth`)
- `.mux/tool_post` (syncs beads after edits)
- `.mux/tool_env` (ensures `~/bin` is on `PATH` for bash tool calls)

These files match the concepts documented in `https://mux.coder.com/` (instruction files + init/tool hooks) while keeping beads as the source of truth for task tracking.

---

## Getting Started

```bash
npx skills add AvivK5498/The-Claude-Protocol
```

Or via npm:

```bash
npm install -g beads-orchestration
```

Then in any Claude Code session:

```bash
/create-beads-orchestration
```

For Mux-oriented projects, pass `--with-mux` in the bootstrap command prompted by the skill (or run `beads-orchestration bootstrap --with-mux`) to install `.mux/*` workspace files.

The skill walks you through setup, scans your tech stack, and creates supervisors with best practices injected.

### Requirements

- Claude Code with hooks support
- Node.js (for npx)
- Python 3 (for bootstrap)
- beads CLI (installed automatically)

---

## What Makes This Different

### Enforcement, Not Suggestions

13 hooks across 5 lifecycle events. They don't warn — they block. The orchestrator can't edit code on main. Supervisors can't skip beads. Epics can't close with open children. `git commit --no-verify` is blocked — pre-commit hooks always run.

### Investigation-First, Constraint-Driven

The orchestrator must read the actual source file before delegating — no guessing. Constraints ("never dispatch without reading the source") outperform instructions ("remember to investigate"), inspired by [Cursor's multi-agent research](https://cursor.com/blog/self-driving-codebases). The orchestrator also maintains persistent memory across sessions.

### Documentation That Writes Itself

Every supervisor dispatch prompt is automatically captured as a bead comment. Agents voluntarily log conventions and gotchas into a persistent knowledge base. Session start surfaces recent knowledge so agents don't re-investigate solved problems.

```bash
# Agent captures an insight
bd comment BD-001 "LEARNED: TaskGroup requires @Sendable closures in strict concurrency mode."

# Search the knowledge base
.beads/memory/recall.sh "concurrency"
```

### Follow-Up Traceability

Closed beads are immutable. Bug fixes become new beads linked via `bd dep relate` — full history, no reopening. Merged branches don't get reused. Each fix gets its own worktree and PR.

---

## What Gets Installed

```
.claude/
├── agents/           # Supervisors (auto-created for your tech stack)
├── hooks/            # Workflow enforcement (13 hooks)
├── skills/           # subagents-discipline, react-best-practices
└── settings.json
CLAUDE.md             # Orchestrator instructions
.beads/               # Task database
  memory/             # Knowledge base (knowledge.jsonl + recall.sh)
.worktrees/           # Isolated worktrees per task (created dynamically)

# Optional with --with-mux
.mux/
├── AGENTS.md         # Mux workspace instruction layer
├── init              # Workspace init hook (bd prime --stealth)
├── tool_post         # Post-tool hook (bd sync on file edits)
└── tool_env          # Bash env hook (adds ~/bin to PATH)
```

---

## Hooks

13 hooks enforce every workflow step. They block before bad actions happen, auto-log after good ones, and validate before supervisors exit.

**PreToolUse** (7 hooks) — Block orchestrator from writing code on main. Prompt for quick-fix approval on feature branches. Block `--no-verify` on commits. Allow memory file writes. Require beads for supervisor dispatch. Enforce worktree isolation. Block closing epics with open children. Enforce sequential dependency dispatch.

**PostToolUse** (3 hooks) — Auto-log dispatch prompts as bead comments. Capture knowledge base entries. Enforce concise supervisor responses.

**SubagentStop** (1 hook) — Verify worktree exists, code is pushed, bead status is updated.

**SessionStart** (1 hook) — Surface task status, recent knowledge, and cleanup suggestions.

**UserPromptSubmit** (1 hook) — Prompt for clarification on ambiguous requests.

---

## Advanced: Mux Workspace Mode

Use bootstrap with Mux files:

```bash
beads-orchestration bootstrap --project-dir . --with-mux
```

This installs `.mux/AGENTS.md`, `.mux/init`, `.mux/tool_post`, and `.mux/tool_env` in addition to the standard Claude/beads setup.

## Advanced: External Providers

By default, all agents run via Claude's Task(). To delegate read-only agents (scout, detective, etc.) to Codex/Gemini:

```bash
/create-beads-orchestration --external-providers
```

Requires Codex CLI (`codex login`), optionally Gemini CLI, and [uv](https://github.com/astral-sh/uv).

---

## License

MIT

## Credits

- [beads](https://github.com/steveyegge/beads) — Git-native task tracking by Steve Yegge
- [sub-agents.directory](https://github.com/ayush-that/sub-agents.directory) — External agent templates
