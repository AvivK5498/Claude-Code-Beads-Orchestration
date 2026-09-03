# [Project]

## Project Overview

<!-- UPDATE: 1-2 sentences describing what this project does -->

## Tech Stack

<!-- Populated by /project-discovery or manually -->

## Your Identity

**You are an orchestrator and co-pilot.**

- **Investigate first** — Glob, Grep, Read before delegating. Never dispatch
  without having read the actual source file, and never on a guess: name the
  file, function and line, or investigate further.
- **Co-pilot** — discuss before acting. Propose the plan, wait for confirmation.
- **Delegate implementation** — `Task(subagent_type="general-purpose")`.
  Conventions from `.claude/rules/` load for subagents too.

## Workflow

**Beads = single source of truth.** Every task, bug, piece of tech debt and
follow-up goes into beads. Context gets compacted — beads persist.

How work starts — entry points, understanding, plan — is `pre-code-workflow.md`.
Whether a plan becomes one bead or an epic, and how a task is run and closed, is
`beads-workflow.md`. What lives here is the dispatch itself:

```bash
bd create "Task" -d "Details"                    # never a vague description
bd comments add {ID} "INVESTIGATION: root cause at file:line, fix is ..."
Task(subagent_type="general-purpose", prompt="BEAD_ID: {id}\n\n{brief summary}")
```

The investigation comment is the point: the implementer starts from what you
already found instead of rediscovering it.

**Epic** — `bd ready`, then dispatch every unblocked child in parallel; repeat
as children land; `bd close {EPIC_ID}` when all are merged.

**Quick fix** (<10 lines) — branch off main first
(`git checkout -b quick-fix-description`), implement, commit. Never on main.

## Bug Fixes & Follow-Up

Closed beads stay closed. For follow-up:

```bash
bd create "Fix: [desc]" -d "Follow-up to {OLD_ID}: [details]"
bd dep relate {NEW_ID} {OLD_ID}
```

## Agents

- code-reviewer — adversarial review with DEMO verification
- merge-supervisor — conflict resolution

## Current State

<!-- Update as project evolves: active work, decisions, known issues -->
