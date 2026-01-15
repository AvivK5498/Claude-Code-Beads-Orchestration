# Beads Orchestration

A lightweight multi-agent orchestration framework for Claude Code that enables parallel development workflows with mandatory code review gates.

## Two Modes of Operation

Beads Orchestration supports two modes for running read-only agents (scout, detective, architect, scribe, code-reviewer):

| Mode | Flag | Read-only Agents | Requirements |
|------|------|------------------|--------------|
| **Claude-only** | `--claude-only` | Run via Claude Task() | beads CLI only |
| **External Providers** | (default) | Run via Codex/Gemini | Codex CLI, Gemini CLI, uv |

**Claude-only mode** is simpler to set up and has no external dependencies. **External providers mode** offloads read-only work to Codex/Gemini, reducing Claude token usage.

## Requirements

### Claude-only Mode (Recommended for simplicity)

- **Claude Code** with hooks support
- **beads CLI** - Installed automatically by the skill, or manually:
  - macOS: `brew install steveyegge/beads/bd`
  - npm: `npm install -g @beads/bd`
  - Go: `go install github.com/steveyegge/beads/cmd/bd@latest`

### External Providers Mode (For reduced Claude usage)

All of the above, plus:
- **Codex CLI** - Run `codex login` to authenticate (primary provider)
- **Gemini CLI** - Optional fallback when Codex hits rate limits
- **uv** - Python package manager ([install](https://github.com/astral-sh/uv))

## Getting Started

The easiest way to set up Beads Orchestration is through the Claude Code skill. The skill provides a guided walkthrough that:

1. Asks for your project details
2. Clones and runs the bootstrap script
3. Installs all agents, hooks, and MCP configuration
4. Guides you through running discovery to create tech-specific supervisors

### Installing the Skill

```bash
# Clone this repo
git clone https://github.com/AvivK5498/Claude-Code-Beads-Orchestration

# Copy the skill to your Claude skills directory
mkdir -p ~/.claude/skills/create-beads-orchestration
cp Claude-Code-Beads-Orchestration/skills/create-beads-orchestration/SKILL.md ~/.claude/skills/create-beads-orchestration/
```

### Running the Skill

In any Claude Code session:

```
/create-beads-orchestration
```

The skill will walk you through the entire setup process interactively. You can run it on:
- **An existing project** - The skill detects your tech stack and creates appropriate supervisors
- **A new project** - Start fresh and supervisors will be created based on what you build

After the skill completes and you restart Claude Code, your project will have full orchestration capabilities with enforced workflows.

---

## Overview

Beads Orchestration turns a single Claude Code session into a coordinated team of specialized agents. An orchestrator delegates tasks to supervisors who work on isolated feature branches, with all work validated by a code review agent before completion.

**Key Design Principles:**
- **Orchestrators delegate, they don't implement** - Enforced by hooks
- **One bead = one branch = one task** - Git-native task isolation
- **Mandatory code review** - No completion without approval
- **Minimal context overhead** - Uses `beads` CLI instead of heavy MCP servers

## Architecture

### Claude-only Mode

```
┌─────────────────────────────────────────────────────────────────┐
│                         ORCHESTRATOR                            │
│  (Main Claude session - delegates only, blocked from coding)    │
└──────────────────────────┬──────────────────────────────────────┘
                           │
           ┌───────────────┼───────────────┐
           │               │               │
           ▼               ▼               ▼
    ┌──────────┐    ┌──────────┐    ┌──────────┐
    │   Task   │    │   Task   │    │   Task   │
    │ Subagent │    │ Subagent │    │ Subagent │
    └────┬─────┘    └────┬─────┘    └────┬─────┘
         │               │               │
    Read-only:      Implements      Implements
    - scout         on branch:      on branch:
    - detective     bd-BD-001       bd-BD-002
    - architect         │               │
    - scribe            └───────┬───────┘
    - code-reviewer             │
                          Code Review
                          (Required)
```

All agents run via Claude Task() - simple and no external dependencies.

### External Providers Mode

```
┌─────────────────────────────────────────────────────────────────┐
│                         ORCHESTRATOR                            │
│  (Main Claude session - delegates only, blocked from coding)    │
└──────────────────────────┬──────────────────────────────────────┘
                           │
           ┌───────────────┼───────────────┐
           │               │               │
           ▼               ▼               ▼
    ┌──────────┐    ┌──────────┐    ┌──────────┐
    │ Provider │    │   Task   │    │   Task   │
    │ Delegator│    │ Subagent │    │ Subagent │
    └────┬─────┘    └────┬─────┘    └────┬─────┘
         │               │               │
    Codex/Gemini    Implements      Implements
    agents:         on branch:      on branch:
    - scout         bd-BD-001       bd-BD-002
    - detective         │               │
    - architect         └───────┬───────┘
    - scribe                    │
    - code-reviewer       Code Review
                          (Required)
```

Read-only agents run on Codex (primary) with Gemini fallback, reducing Claude token usage.

## What Gets Installed

### Claude-only Mode

```
your-project/
├── .beads/                           # Git-native task tracking
├── .claude/
│   ├── agents/
│   │   ├── scout.md                  # Codebase exploration (Task)
│   │   ├── detective.md              # Bug investigation (Task)
│   │   ├── architect.md              # Design & planning (Task)
│   │   ├── scribe.md                 # Documentation (Task)
│   │   ├── code-reviewer.md          # Code review gate (Task)
│   │   ├── discovery.md              # Tech detection (Task)
│   │   ├── worker-supervisor.md      # Small tasks (Task)
│   │   └── merge-supervisor.md       # Conflict resolution (Task)
│   ├── hooks/                        # 7 enforcement hooks
│   ├── beads-workflow-injection.md   # Workflow injected into supervisors
│   └── settings.json                 # Hook configuration
├── CLAUDE.md                         # Orchestrator instructions
└── .gitignore                        # Excludes .beads/
```

### External Providers Mode

```
your-project/
├── .beads/                           # Git-native task tracking
├── .mcp.json                         # Provider delegator MCP config
├── .claude/
│   ├── agents/
│   │   ├── scout.md                  # Codebase exploration (Codex)
│   │   ├── detective.md              # Bug investigation (Codex)
│   │   ├── architect.md              # Design & planning (Codex)
│   │   ├── scribe.md                 # Documentation (Codex)
│   │   ├── code-reviewer.md          # Code review gate (Codex)
│   │   ├── discovery.md              # Tech detection (Task)
│   │   ├── worker-supervisor.md      # Small tasks (Task)
│   │   └── merge-supervisor.md       # Conflict resolution (Task)
│   ├── hooks/                        # 8 enforcement hooks (includes enforce-codex-delegation.sh)
│   ├── beads-workflow-injection.md   # Workflow injected into supervisors
│   └── settings.json                 # Hook configuration
├── CLAUDE.md                         # Orchestrator instructions
└── .gitignore                        # Excludes .beads/ and .mcp.json
```

Tech-specific supervisors (e.g., `react-supervisor`, `python-backend-supervisor`) are created dynamically by the discovery agent based on your codebase.

## Core Concepts

### Beads

[Beads](https://github.com/steveyegge/beads) is a git-native task tracker. Each "bead" represents a unit of work.

```bash
bd create "Add user authentication" -d "Implement JWT-based auth"  # Create bead
bd list                              # List all beads
bd show BD-001                       # Show bead details
bd comment BD-001 "Started work"     # Add progress comment
bd update BD-001 --status inreview   # Mark ready for merge
bd close BD-001                      # Close completed bead
```

### Agent Types

| Agent | Claude-only | External Providers | Purpose | Can Write Code? |
|-------|-------------|-------------------|---------|-----------------|
| scout | Task | Codex | Find files, explore structure | No |
| detective | Task | Codex | Investigate bugs, trace issues | No |
| architect | Task | Codex | Design solutions, plan approach | No |
| scribe | Task | Codex | Write documentation | No |
| code-reviewer | Task | Codex | Review code, approve completion | No |
| discovery | Task | Task | Detect tech stack, create supervisors | Yes |
| *-supervisor | Task | Task | Implement features, fix bugs | Yes |

### Delegation Patterns (Enforced)

The orchestration workflow **enforces** delegation through hooks and subagent configuration. The orchestrator cannot bypass these patterns.

#### Claude-only Mode

**All agents use Task():**
```python
# Read-only task
Task(
    subagent_type="scout",
    prompt="Find all authentication-related files"
)

# Implementation task
Task(
    subagent_type="react-supervisor",
    prompt="BEAD_ID: BD-001\n\nImplement login component with form validation"
)
```

#### External Providers Mode

**Read-only tasks → Provider Delegator (enforced by hook):**
```python
mcp__provider_delegator__invoke_agent(
    agent="scout",
    task_prompt="Find all authentication-related files"
)
```

**Implementation tasks → Task Subagents:**
```python
Task(
    subagent_type="react-supervisor",
    prompt="BEAD_ID: BD-001\n\nImplement login component with form validation"
)
```

Hooks block the orchestrator from using implementation tools directly. Supervisors are required to follow the beads workflow, request code review, and use proper completion formats.

## Workflow

### Standard Development Flow

```
1. Create bead         → bd create "Feature X" -d "Details"
2. Dispatch supervisor → Orchestrator delegates with BEAD_ID
3. Supervisor works    → Creates branch bd-BD-001, implements, commits
4. Code review         → Supervisor calls code-reviewer (mandatory)
5. Mark complete       → bd update BD-001 --status inreview
6. Orchestrator merges → git merge bd-BD-001
7. Close bead          → bd close BD-001
```

### Supervisor Workflow (Enforced)

Every supervisor follows the beads workflow automatically:

```
ON START:
  1. Receive BEAD_ID from orchestrator
  2. Create branch: git checkout -b bd-{BEAD_ID}

DURING WORK:
  3. Implement using specialty knowledge
  4. Commit frequently
  5. Log progress: bd comment {BEAD_ID} "..."

ON COMPLETION:
  6. Run tests
  7. Request code review (MANDATORY)
  8. If approved → Mark: bd update {BEAD_ID} --status inreview
  9. If not approved → Fix issues, repeat code review
```

### Parallel Work

The branch-per-bead model enables parallel development:

```
main
  │
  ├─── bd-BD-001 (react-supervisor: login page)
  │
  ├─── bd-BD-002 (python-backend-supervisor: auth API)
  │
  └─── bd-BD-003 (infra-supervisor: CI pipeline)
```

When supervisors complete, the orchestrator merges branches. Conflicts trigger `merge-supervisor`.

### Branch Strategy

All branches are **local only**. The workflow intentionally keeps branches local to:
- Avoid authentication complexity in automated workflows
- Prevent race conditions with remote repositories
- Simplify conflict resolution

Push to remote when you're ready, after the orchestrator has merged completed work to main.

## Code Review Gate

**All supervisors must pass code review before completion.**

### How Code Review Works

The code-reviewer agent always gathers context from the bead first:

```bash
# Step 0: Gather context (always done first)
bd show {BEAD_ID}           # Task description
bd comments {BEAD_ID}       # Supervisor's implementation notes
git diff main...bd-{BEAD_ID}  # Actual code changes
```

This ensures the code-reviewer has full context regardless of how it was invoked (Claude-only or external providers).

### Two-Phase Review

1. **Phase 1: Spec Compliance**
   - Did they implement all requirements?
   - Did they add unrequested features (over-engineering)?
   - Did they misunderstand the task?

2. **Phase 2: Code Quality** (only if Phase 1 passes)
   - Logic errors, bugs
   - Security vulnerabilities
   - Pattern violations
   - Maintainability issues

**Approval:**
- Reviewer adds: `bd comment {BEAD_ID} "CODE REVIEW: APPROVED - [summary]"`
- Supervisor can now complete

**Rejection:**
- Reviewer lists issues with `file:line` references
- Supervisor must fix and request review again

### Mode-Specific Behavior

| Mode | Code Review Invocation |
|------|----------------------|
| Claude-only | Orchestrator dispatches via `Task(subagent_type="code-reviewer", prompt="Review BEAD_ID: BD-001")` |
| External Providers | Supervisor calls `mcp__provider_delegator__invoke_agent(agent="code-reviewer", ...)` |

In both modes, the code-reviewer reads context from the bead, not from the prompt. This ensures consistent reviews.

## Hooks

| Hook | Lifecycle | Mode | Purpose |
|------|-----------|------|---------|
| `block-orchestrator-tools.sh` | PreToolUse | Both | Prevents orchestrator from using Edit/Write/etc. |
| `enforce-codex-delegation.sh` | PreToolUse (Task) | External only | Forces read-only agents to use provider_delegator |
| `enforce-bead-for-supervisor.sh` | PreToolUse (Task) | Both | Requires BEAD_ID for supervisors |
| `remind-inprogress.sh` | PreToolUse (Task) | Both | Warns about in-progress beads |
| `enforce-concise-response.sh` | PostToolUse (Task) | Both | Limits response verbosity |
| `validate-completion.sh` | SubagentStop | Both | Blocks completion without code review |
| `session-start.sh` | SessionStart | Both | Session initialization |
| `clarify-vague-request.sh` | UserPromptSubmit | Both | Prompts for clarification on vague requests |

**Note:** In Claude-only mode, `enforce-codex-delegation.sh` is not installed since all agents use Task() directly.

## MCP Provider Delegator (External Providers Mode Only)

> **Note:** This section only applies to External Providers mode. In Claude-only mode, the provider_delegator is not installed and all agents use Task() directly.

The `provider_delegator` MCP server runs read-only agents with automatic fallback:

```
┌─────────────────────────────────────────┐
│           Claude Code Session           │
│                                         │
│  mcp__provider_delegator__invoke_agent()│
│               │                         │
└───────────────┼─────────────────────────┘
                │
                ▼
┌─────────────────────────────────────────┐
│       MCP Provider Delegator Server     │
│                                         │
│  1. Load agent template (.md file)      │
│  2. Try Codex (primary)                 │
│  3. If rate limited → Try Gemini        │
│  4. If both fail → Return fallback hint │
└─────────────────────────────────────────┘
```

**Fallback Chain:** Codex → Gemini → Claude Task (with fallback hint)

**Supported Agents:** scout, detective, architect, scribe, code-reviewer

**Fallback Scenarios:**
| Situation | Behavior |
|-----------|----------|
| Codex works | Uses Codex |
| Codex rate limited | Falls back to Gemini |
| Codex not installed | Falls back to Gemini |
| Both rate limited | Returns Claude Task() fallback hint |
| Both not installed | Returns Claude Task() fallback hint |

The delegator gracefully handles missing CLIs - if Codex isn't installed but Gemini is, it automatically uses Gemini.

## Discovery Agent

The discovery agent scans your codebase and creates appropriate supervisors:

| Detected | Creates Supervisor |
|----------|-------------------|
| package.json + React/Next | react-supervisor |
| package.json + Vue/Nuxt | vue-supervisor |
| package.json + Express/Fastify | node-backend-supervisor |
| requirements.txt + FastAPI/Django | python-backend-supervisor |
| go.mod | go-supervisor |
| Cargo.toml | rust-supervisor |
| Dockerfile | infra-supervisor |
| pubspec.yaml | flutter-supervisor |

Supervisors are sourced from [sub-agents.directory](https://github.com/ayush-that/sub-agents.directory) with the beads workflow injected.

---

## Advanced: Manual Bootstrap

If you prefer not to use the skill, you can run the bootstrap script directly:

```bash
git clone --depth=1 https://github.com/AvivK5498/Claude-Code-Beads-Orchestration "${TMPDIR:-/tmp}/beads-orchestration"
```

### Claude-only Mode (Recommended)

```bash
python3 "${TMPDIR:-/tmp}/beads-orchestration/bootstrap.py" \
  --project-name "MyProject" \
  --project-dir /path/to/your/project \
  --claude-only
```

### External Providers Mode

```bash
python3 "${TMPDIR:-/tmp}/beads-orchestration/bootstrap.py" \
  --project-name "MyProject" \
  --project-dir /path/to/your/project
```

### Bootstrap Options

| Flag | Description |
|------|-------------|
| `--project-name` | Project name for agent templates (auto-inferred if not provided) |
| `--project-dir` | Target project directory (default: current directory) |
| `--claude-only` | Use Claude Task() for all agents, no external providers |

After bootstrap completes:
1. Restart Claude Code to load hooks and configuration
2. Run the discovery agent to create tech-specific supervisors

---

## License

MIT

## Credits

- [beads](https://github.com/steveyegge/beads) - Git-native task tracking by Steve Yegge
- [sub-agents.directory](https://github.com/ayush-that/sub-agents.directory) - External agent templates
