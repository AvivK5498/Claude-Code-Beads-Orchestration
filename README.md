# Beads Orchestration

Multi-agent orchestration for Claude Code. An orchestrator investigates issues, manages tasks automatically, and delegates implementation to specialized supervisors.

**[Beads Kanban UI](https://github.com/AvivK5498/Beads-Kanban-UI)** — Visual task management fully compatible with this workflow. Supports tasks, epics, subtasks, dependencies, and design docs.

## Installation

```bash
npx skills add AvivK5498/Claude-Code-Beads-Orchestration
```

Or via npm:

```bash
npm install -g @avivkaplan/beads-orchestration
```

> macOS and Linux only.

## Quick Start

```bash
# In any Claude Code session
/create-beads-orchestration
```

The skill walks you through setup, runs the bootstrap via `npx`, then creates tech-specific supervisors based on your codebase.

### Requirements

- Claude Code with hooks support
- Node.js (for npx)
- Python 3 (for bootstrap)
- beads CLI (installed automatically by bootstrap)

## Key Features

**Orchestrator / Supervisor separation** — The orchestrator investigates with Grep, Read, Glob, then delegates implementation to tech-specific supervisors via `Task()`. It never edits code directly. Hooks enforce this.

**Worktree isolation** — Every task gets its own git worktree at `.worktrees/bd-{BEAD_ID}/`. Main stays clean. Multiple tasks can run in parallel without branch conflicts.

**Automatic task tracking** — The orchestrator creates and manages [beads](https://github.com/steveyegge/beads) automatically. You don't touch task management — it creates beads, tracks progress, marks completion, and closes them.

**Epics with dependencies** — Cross-domain features (DB + API + Frontend) become epics with child tasks. Dependencies are enforced — hooks block dispatch of children whose dependencies haven't merged yet.

**Persistent knowledge base** — Agents capture conventions, gotchas, and patterns as they work via `bd comment` with `LEARNED:` and `INVESTIGATION:` prefixes. An async hook extracts these into `.beads/memory/knowledge.jsonl`. Supervisors are blocked from completing without a `LEARNED:` entry. Session start surfaces recent knowledge so agents don't re-investigate solved problems.

**12 enforcement hooks** — Every step of the workflow is enforced. Orchestrator can't edit files. Supervisors can't start without a bead. Edits require a worktree. Completions are verified. Responses stay concise. See [Hooks](#hooks) for the full list.

**Tech stack discovery** — A discovery agent scans your codebase and creates the right supervisors (react-supervisor, python-supervisor, etc.) with best practices injected.

## How It Works

```
┌─────────────────────────────────────────┐
│            ORCHESTRATOR                 │
│  Investigates with Grep/Read/Glob       │
│  Manages tasks automatically (beads)    │
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

**Orchestrator:** Investigates the issue, identifies root cause, logs findings to bead, delegates with brief fix instructions.

**Supervisors:** Read bead comments for context, create isolated worktrees, execute the fix confidently. Created by discovery agent based on your tech stack.

## Knowledge Base

Agents build a persistent knowledge base as they work. No extra steps — it piggybacks on `bd comment`.

```bash
# Supervisor finishes a task and records what it learned
bd comment BD-001 "LEARNED: TaskGroup requires @Sendable closures in strict concurrency mode."

# Orchestrator logs investigation findings
bd comment BD-002 "INVESTIGATION: Root cause: SparkleAdapter.swift:45 - nil SUFeedURL crashes XMLParser."
```

An async hook intercepts these comments and extracts them into `.beads/memory/knowledge.jsonl`. Each entry is auto-tagged by keyword and attributed to its source (orchestrator vs supervisor).

**Why this works:**
- Zero friction — agents already use `bd comment`, they just add a prefix
- No database, no embeddings, no external services — one JSONL file, grep + jq to search
- Enforced — supervisors are blocked from completing without a `LEARNED:` comment
- Surfaces automatically — session start shows recent knowledge so agents don't re-investigate solved problems

```bash
# Search the knowledge base
.beads/memory/recall.sh "concurrency"
.beads/memory/recall.sh --recent 10
.beads/memory/recall.sh --stats
```

See [docs/memory-architecture.md](docs/memory-architecture.md) for the full design.

## What Gets Installed

```
.claude/
├── agents/           # Supervisors (discovery creates tech-specific ones)
├── hooks/            # Workflow enforcement (12 hooks)
├── skills/           # subagents-discipline, react-best-practices
└── settings.json
CLAUDE.md             # Orchestrator instructions
.beads/               # Task database
  memory/             # Knowledge base (knowledge.jsonl + recall.sh)
.worktrees/           # Isolated worktrees for each task (created dynamically)
```

## Hooks

12 hooks enforce the workflow at every step. Grouped by lifecycle event:

**PreToolUse** — Block before action happens:

| Hook | Trigger | Purpose |
|------|---------|---------|
| `block-orchestrator-tools.sh` | Edit, Write | Orchestrator can't modify code directly |
| `enforce-bead-for-supervisor.sh` | Task | Supervisors require BEAD_ID in prompt |
| `enforce-branch-before-edit.sh` | Edit, Write | Must be in a worktree, not main |
| `enforce-sequential-dispatch.sh` | Task | Blocks epic children with unresolved deps |
| `validate-epic-close.sh` | Bash | Can't close epic with open children |
| `inject-discipline-reminder.sh` | Task | Injects discipline skill context |
| `remind-inprogress.sh` | Task | Warns about existing in-progress beads |

**PostToolUse** — React after action completes:

| Hook | Trigger | Purpose |
|------|---------|---------|
| `enforce-concise-response.sh` | Task | Limits supervisor response verbosity |
| `memory-capture.sh` | Bash | Captures LEARNED/INVESTIGATION into knowledge base |

**SubagentStop** — Validate before supervisor exits:

| Hook | Trigger | Purpose |
|------|---------|---------|
| `validate-completion.sh` | Any | Verifies worktree, push, bead status, LEARNED comment |

**SessionStart** — Run when a new session begins:

| Hook | Trigger | Purpose |
|------|---------|---------|
| `session-start.sh` | Any | Shows task status, recent knowledge, cleanup suggestions |

**UserPromptSubmit** — Filter user input:

| Hook | Trigger | Purpose |
|------|---------|---------|
| `clarify-vague-request.sh` | Any | Prompts for clarification on ambiguous requests |

## Advanced: External Providers

By default, all agents run via Claude's Task(). If you want to delegate read-only agents (scout, detective, etc.) to Codex/Gemini instead:

```bash
/create-beads-orchestration --external-providers
```

**Additional requirements:**
- Codex CLI: `codex login`
- Gemini CLI (optional fallback)
- uv: [install](https://github.com/astral-sh/uv)

This creates `.mcp.json` with provider-delegator config.

## License

MIT

## Credits

- [beads](https://github.com/steveyegge/beads) - Git-native task tracking by Steve Yegge
- [sub-agents.directory](https://github.com/ayush-that/sub-agents.directory) - External agent templates
