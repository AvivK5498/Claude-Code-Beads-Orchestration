# Beads Workflow

## Beads = single source of truth. Nothing lives only in your head.

Context gets compacted. Sessions restart. Beads persist.

This rule is the workflow, not a bd tutorial — `bd prime` prints the command
reference at session start, and `bd <cmd> --help` covers the rest.

### When to create a bead

A bead is for what the user asked for, and for what will not fit inside the
current work. A bead costs: describe it, start it, create a worktree, open a
PR, wait for the merge, close it. For a three-line change that costs more than
the change itself.

Something you stumble on along the way has two outcomes, never a third.

**Fix it now, in the current branch**, when all of it holds:

- under 10 lines
- in a file you are already editing for the current bead
- one line in the commit message is enough for a reviewer to follow it

A fix unrelated to the current work goes in its own commit, so it stays visible
apart from the main change.

**Create a bead** when any of it holds:

- behaviour visible from the outside changes — that is a decision, not a fix
- database schema, a migration, a dependency, an external interface
- it needs tests of its own
- you would have to drop the current work to understand the cause

```bash
bd create "Fix: [what]" -d "Discovered while working on {CURRENT_BEAD}: [details]"
```

Never leave it silent: either the change is in a commit, or there is a bead.

**Stop signal:** about to file a third incidental bead during one task — stop.
Two of the three were probably meant to be done on the spot.

**Not a bead:** a quick fix the user approved (<10 lines, feature branch), and
research or discussion with no code changes planned.

### After planning — size check, then create beads

Plan finalized and confirmed, BEFORE implementation:

- >3 files OR >1 domain (DB + API, backend + frontend) → epic with children
  (`--type epic`, then children with `--parent` and `--deps`)
- "and then", "after that", multiple steps in the description → several beads
- >50 lines estimated → consider splitting
- Otherwise → one bead

Rule of thumb: 1 bead = 1 PR = 1 reviewable diff. Then `bd list` to confirm the
plan now lives in beads and not just in context, and `bd ready` → dispatch.

### Status discipline

`open` → `in_progress` when work starts → comment `AWAITING REVIEW` when it is
submitted, **still `in_progress`** → the user closes it after merging the PR.

An epic goes `in_progress` with its first child and stays there until every
child is done. Never leave a bead `in_progress` across sessions without a reason.

## Task Start

1. Parse BEAD_ID from dispatch prompt
2. Create worktree (MUST use bd, not raw git — see Banned):
   ```bash
   bd worktree create .worktrees/bd-{BEAD_ID} --branch bd-{BEAD_ID}
   cd .worktrees/bd-{BEAD_ID}
   ```
   It shares the main repo's database — labels like `none` or
   `local (no redirect)` are cosmetic, not breakage. Anything odd around
   worktrees and bd: `bd memories worktree` before investigating.
3. `bd update {BEAD_ID} --status in_progress` — and the parent epic too, if it
   is still `open`
4. Read the context you were given: `bd show {BEAD_ID}` and `bd comments {BEAD_ID}`

## During Implementation

- Work ONLY in your worktree: `.worktrees/bd-{BEAD_ID}/`
- Commit frequently with descriptive messages
- Log progress: `bd comments add {BEAD_ID} "Completed X, working on Y"`
- Do not file incidental findings as beads yourself — one line in the report,
  `Found along the way: …`; the orchestrator decides

## Task Completion

All of it, in order:

1. **Self-verify:** re-read the description with `bd show {BEAD_ID}` and check
   every requirement in it. Something missing — implement it now, do not skip.
2. `git add -A && git commit -m "..."` then `git push origin bd-{BEAD_ID}`
3. `bd comments add {BEAD_ID} "Completed: [summary]"`, then a second comment
   `AWAITING REVIEW`. Leave the bead `in_progress` — the user closes it.
4. Return the completion report (the checklist is MANDATORY — the hook blocks
   a report without it):
   ```
   BEAD {BEAD_ID} COMPLETE
   Worktree: .worktrees/bd-{BEAD_ID}
   Checklist:
   - [x] requirement 1 from description
   - [x] requirement 2 from description
   Files: [names only]
   Tests: pass
   Summary: [1 sentence]
   Found along the way: [one line, or no line at all]
   ```

## Banned

- Working directly on main branch
- Implementing without BEAD_ID
- Merging your own branch (user merges via PR)
- Editing files outside your worktree
- Filing incidental beads from a worktree — the finding goes in the report line
- Raw `git worktree add` — it creates a shadow `.beads/` copy, leaks dolt
  processes and loses bead data. Use `bd worktree create`. Removing one with
  raw `git worktree remove --force` + `git worktree prune` IS allowed, because
  `bd worktree remove` is broken on Windows (bug u51).
