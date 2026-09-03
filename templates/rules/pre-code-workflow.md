# Pre-Code Workflow

## Core rule

No code until the task is understood. Three gates before edits: understanding,
reuse-or-write, plan. Passing them costs less than redoing the work.

## Trigger: when this rule fires

- **Full order** — the task touches production code, the database schema, an
  external integration, deployment, or it is your first work in an unfamiliar
  part of the project.
- **Short order (straight to step 3)** — documents, diagnostics, a repetitive
  mechanical edit, a repeat of something already investigated.
- **No order** — a one or two line edit with an obvious location. Just do it.

Steps 1–3 happen in plan mode. Leave it once, after step 3.

## Step 1 — understanding

- Do not read code until you have 2–3 entry points: a file, a database table, a
  handler route, a component. Not in the request — ask in one sentence. Do not
  pick them yourself.
- Read only what was named, plus one level deeper. Need another file — ask.
- Result is a table: what exists now / what the problem is / what changes / what
  it becomes, across three levels: interface, database, external links. A level
  is not involved — write "not affected". No empty cells.
- Questions are specific: one question = one fact that is not in the code.

## Step 2 — reuse or write

- Break the task into atoms. For each: reuse something existing (name the file)
  or write from scratch (roughly how many new lines).
- **What to watch** — only with a concrete `file:line` reference. There is no
  such thing as an abstract risk. None — write "none".
- **Out of scope** — what is deliberately left alone: neighbouring files, parts
  kept as they are, anything not in the request. None — write "none".

## Step 3 — plan

- 7–15 items. Fewer than seven — no plan needed, do the work. More than
  fifteen — the task is too big, propose splitting it.
- An item = verb + object + one sentence of substance.
- Required sections: **Risks** and **Out of scope**.
- Ask for the leash length: 1 — do it all; 2 — stop after each item; 3 — save
  the plan only, do nothing.
- Reworking the plan — show what changed against the previous version.

Plan accepted — continue with `beads-workflow.md`: size check, create beads,
dispatch. Not repeated here.

## After the work — worklog

Append a paragraph to `docs/worklog/YYYY-MM-DD-short-name.md`: what was done,
why this way, what to check first when it breaks, what was deliberately left
alone. One file per task, not per step.

**The worklog and the bead are different records — never write the same thing
twice:**

| Where | What | Why |
|---|---|---|
| Bead comments (`bd comments add`) | progress, findings, decisions for this task | lives with the bead, closes with it |
| `bd remember` | a lesson useful another time, in another project | found via `bd memories` from anywhere |
| `docs/worklog/` | what to check first when it breaks, what was left alone and why | found by grep six months later, long after the bead closed |

The repository may be public — before writing, check the paragraph for internal
addresses, keys, and customer names.

## Banned

- Searching the whole project "to see what else is there" instead of asking for
  entry points
- Questions like "tell me how this all works" — that is not a question, it is a
  request to retell the project
- Leaving plan mode before the plan is accepted
