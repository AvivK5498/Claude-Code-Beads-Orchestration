# Beads Orchestration

Multi-agent orchestration for Claude Code. An orchestrator investigates issues, manages tasks automatically, and delegates implementation to specialized supervisors.

## Two Modes

| Mode | Flag | Read-only Agents | Requirements |
|------|------|------------------|--------------|
| **Claude-only** | `--claude-only` | Run via Claude Task() | beads CLI only |
| **External Providers** | (default) | Run via Codex/Gemini | Codex CLI, Gemini CLI, uv |

## Quick Start

```bash
# In any Claude Code session
/create-beads-orchestration
```

The skill walks you through setup, then creates tech-specific supervisors based on your codebase.

### Manual Installation

```bash
# Clone this repo
git clone https://github.com/AvivK5498/Claude-Code-Beads-Orchestration

# Copy the skill to your Claude skills directory
mkdir -p ~/.claude/skills/create-beads-orchestration
cp Claude-Code-Beads-Orchestration/skills/create-beads-orchestration/SKILL.md ~/.claude/skills/create-beads-orchestration/
```

### Requirements

**Claude-only mode:**
- Claude Code with hooks support
- beads CLI: `brew install steveyegge/beads/bd` or `npm install -g @beads/bd`

**External Providers mode (additional):**
- Codex CLI: `codex login`
- Gemini CLI (optional fallback)
- uv: [install](https://github.com/astral-sh/uv)

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
  │ react-  │ │ python- │ │ worker- │
  │supervisor│ │supervisor│ │supervisor│
  └────┬────┘ └────┬────┘ └────┬────┘
       │           │           │
   bd-BD-001   bd-BD-002   bd-BD-003
   (branch)    (branch)    (branch)
```

**Orchestrator:** Investigates the issue, identifies root cause, manages task lifecycle, delegates with specific fix instructions.

**Supervisors:** Execute the fix confidently on isolated branches. Created by discovery agent based on your tech stack.

## Automatic Task Management

The orchestrator handles task tracking automatically using [beads](https://github.com/steveyegge/beads). You don't need to manage tasks manually—the orchestrator creates beads, tracks progress, and closes them when work completes.

```bash
bd create "Add auth" -d "JWT-based authentication"  # Orchestrator creates
bd update BD-001 --status in_progress               # Supervisor marks started
bd comment BD-001 "Completed login endpoint"        # Progress logged
bd update BD-001 --status inreview                  # Supervisor marks done
bd close BD-001                                     # Orchestrator closes
```

## Delegation Format

```python
Task(
  subagent_type="react-supervisor",
  prompt="""BEAD_ID: BD-001

Problem: Login button doesn't redirect after success
Root cause: src/components/Login.tsx:45 - missing router.push()
Fix: Add router.push('/dashboard') after successful auth"""
)
```

## Epics (Cross-Domain Features)

When a feature spans multiple supervisors (e.g., DB + API + Frontend), the orchestrator automatically creates an epic with child tasks and manages dependencies. Children work on a shared epic branch and are dispatched sequentially.

You can also explicitly request an epic: *"Add user profiles and create an epic for it."*

## What Gets Installed

```
.claude/
├── agents/           # Supervisors (discovery creates tech-specific ones)
├── hooks/            # Workflow enforcement
├── skills/           # subagents-discipline
└── settings.json
CLAUDE.md             # Orchestrator instructions
.beads/               # Task database
.mcp.json             # Provider delegator config (External Providers mode)
```

## Hooks

| Hook | Purpose |
|------|---------|
| `block-orchestrator-tools.sh` | Orchestrator can't Edit/Write |
| `enforce-bead-for-supervisor.sh` | Supervisors need BEAD_ID |
| `enforce-branch-before-edit.sh` | Must be on feature branch to edit |
| `enforce-sequential-dispatch.sh` | Blocks epic children with unresolved deps |
| `block-branch-for-epic-child.sh` | Epic children use shared branch |
| `validate-epic-close.sh` | Can't close epic with open children |
| `enforce-codex-delegation.sh` | Read-only agents use provider_delegator (External mode) |
| `inject-discipline-reminder.sh` | Injects discipline skill reminder |
| `remind-inprogress.sh` | Warns about in-progress beads |
| `validate-completion.sh` | Completion format requirements |
| `enforce-concise-response.sh` | Limits response verbosity |
| `clarify-vague-request.sh` | Prompts for clarification |
| `session-start.sh` | Session initialization |

## License

MIT

## Credits

- [beads](https://github.com/steveyegge/beads) - Git-native task tracking by Steve Yegge
- [sub-agents.directory](https://github.com/ayush-that/sub-agents.directory) - External agent templates
