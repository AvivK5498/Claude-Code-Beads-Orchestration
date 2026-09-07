<div align="center">

# CLAUDE PROTOCOL

**Structure that survives context loss. Every task tracked. Every decision logged.**

[![npm version](https://img.shields.io/npm/v/claude-protocol?style=for-the-badge&logo=npm&logoColor=white&color=CB3837)](https://www.npmjs.com/package/claude-protocol)
[![GitHub stars](https://img.shields.io/github/stars/weselow/claude-protocol?style=for-the-badge&logo=github&color=181717)](https://github.com/weselow/claude-protocol)
[![License](https://img.shields.io/badge/license-MIT-blue?style=for-the-badge)](LICENSE)

<br>

```bash
npx claude-protocol init
```

or inside Claude Code from marketplace:

```
/plugin marketplace add weselow/claude-protocol
/plugin install claude-protocol@claude-protocol
/claude-protocol:init
```

<br>

![The Claude Protocol](screenshots/kanbanui.png)

<br>

[Why](#why) · [What Changed](#what-changed-in-v3) · [How It Works](#how-it-works) · [Installation](#installation) · [Workflow](#workflow) · [Hooks](#hooks) · [FAQ](#faq)

**[Русская версия](README-ru.md)**

</div>

---

## Why

Claude Code loses context. Plans disappear after compaction. Tasks are forgotten between sessions. Changes go straight to main with no traceability.

Claude Protocol fixes this with three things:

- **Beads** — persistent task tracking. One task = one worktree = one PR. Survives restarts and compaction.
- **Hooks** — enforcement, not instructions. Edits on main are blocked. Completion without checklist is blocked. `git --no-verify` is blocked.
- **bd prime** — session start hook loads recent beads so state survives context loss.

Constraints over instructions. What's blocked can't be ignored.

## Origin

This project started as a fork of [The Claude Protocol](https://github.com/AvivK5498/The-Claude-Protocol) by Aviv Kaplan. The original author appears to have stopped development — PRs go unreviewed, and the underlying tools (beads CLI, Claude Code hooks API) have changed significantly.

v3 is a ground-up rewrite. Different architecture, different philosophy. See [decisions.md](docs/decisions-en.md) for full rationale.

## What Changed in v3

### Unreleased

- **An entry already anchored with a slash is not added again** — `.gitignore`
  entries were compared as written, so a project spelling them `/.worktrees/`
  and `/.claude/.upgrades/` got a second, unanchored copy of each appended on
  every install. git reads both spellings as the same path at the repository
  root.

### v3.9.0 (2026-09-07)

- **One source supplies the hooks, whichever order you install in** — the
  plugin and `npx claude-protocol init` wire the same three hooks, and Claude
  Code merges hooks from every source, so a project carrying both ran each one
  twice. Now the copy installed in a project stands down while the plugin is
  active, `npx claude-protocol init` installs only the project half when the
  plugin is already there, and the session-start hook says the leftovers exist
  and names the command that removes them. All three read Claude Code's own
  plugin registry; a registry that is missing, unreadable or shaped
  unfamiliarly, or a plugin switched off in settings, installs and runs exactly
  as before.

- **The plugin loads without a duplicate-hooks error** — `plugin.json` named
  `hooks/hooks.json`, the one file Claude Code loads by itself, so every
  startup reported `Duplicate hooks file detected`. The manifest field is for
  hook files *besides* the standard one. The line is gone and a test keeps it
  from coming back; the hooks themselves were never affected, because the
  automatic load is the one that won.

### v3.8.1 (2026-09-05)

- **The release build runs on the Node 24 action runtime** — `checkout`,
  `setup-node`, `setup-python` and `action-gh-release` were still declaring
  Node 20, which GitHub has deprecated. Nothing in the package changed.

### v3.8.0 (2026-09-05)

- **Install as a plugin** — the repository is now also a Claude Code
  marketplace. The plugin carries the hooks, agents and skill and updates them
  itself; `/claude-protocol:init` lays down the half a plugin cannot carry
  (beads, rules, `CLAUDE.md`) and unwires an earlier `npx` install so no hook
  fires twice. `npx claude-protocol init` is unchanged.
- **The enforcement hooks stand down in a project without `.beads/`** — they
  had nothing to check there, and a plugin at user scope is loaded everywhere.
- **`bd` is asked about, not installed behind your back** — the installer
  prints the command for your machine and waits; `--install-beads` answers yes
  in advance. It then checks the system can actually find `bd`, warns when it
  is older than 1.1.0, and no longer hand-makes an empty `.beads/` when
  `bd init` fails.
- **You are told when a newer claude-protocol is out** — once a week, at
  session start, from a process with a time limit, silent on any failure.
- **`CLAUDE.md` arrives in your language** — `--lang ru` used to install
  Russian rules and English orchestrator instructions, because no Russian
  template existed. There is one now, with English as the fallback wherever a
  translation is missing.
- **Small findings get fixed, not filed** — `beads-workflow.md` used to make a
  bead of everything stumbled on; now the default is to fix it in the same
  branch, with a bead only for what will not fit inside the current work.
- **The hooks stopped losing their arguments on Windows** — commands went
  through `cmd.exe`, which split an argument on spaces, ate quotes and would
  have run whatever followed a `&&`. For some people the hooks did not work at
  all.
- **`--force` no longer destroys a rule you edited** — the flag skipped the one
  place that kept your version. What it overwrites now goes to
  `.claude/.upgrades/<path>.mine` first.
- **A path of the wrong kind stops one file, not the whole install** — a
  directory where our file belongs, or a file where our directory belongs, used
  to end the upgrade mid-way with a stack trace, leaving `settings.json`,
  `CLAUDE.md` and the manifest unwritten.

### v3.7.0 (2026-09-03)

- **The upgrade asks instead of leaving homework** — a file you edited that we
  also changed becomes a question, one at a time, with a diff on request; `K`
  and `T` answer for everything remaining. Whichever version loses is kept
  under `.claude/.upgrades/`.
- **Questions only where someone can answer** — stdin and stdout must both be a
  terminal. Batch runs, CI and an agent driving the CLI keep the silent
  behaviour rather than hanging on input that will never come. `--keep-mine`
  is the counterpart to `--force`.
- **`--dry-run` wrote files** — the flag reached only the cleanup pass, so the
  preview the README tells you to run first modified the project it was
  previewing.

### v3.6.0 (2026-09-03)

- **Hook commands stopped using relative paths** — a hook process inherits the
  working directory of the last Bash call, so `node .claude/hooks/x.cjs` went
  silently missing as soon as work moved into a subdirectory or a worktree.
  Commands now resolve the project root inside Node, and an upgrade rewrites
  stale ones instead of appending duplicates.
- **Five hooks down to three** — `enforce-branch-before-edit` and
  `nudge-claude-md-update` removed, and upgrades clean them out of existing
  installs. `bash-guard` now checks every command in a chain: `cd sub && git
  commit --no-verify` used to slip through.
- **New rule `pre-code-workflow.md`** in both languages, plus
  `repository-scope.md`. Raw `git worktree add` is blocked — it creates a
  shadow `.beads/`.

### v3.5.0 (2026-05-27)

- **New rule `communication-style.md`** — plain language over jargon, in both
  language sets.

### v3.4.0 (2026-05-15)

- **New rule `debugging-standard.md`** — the same error surviving a deliberate
  fix is the trigger to stop repeating and change approach.

### v3.3.0 (2026-04-22)

- **Upgrade mechanism** — new `npx claude-protocol upgrade` command with
  `--dry-run` and `--all <parent>` for batch runs across workspaces. Every
  removal is backed up to `.claude/.upgrades/<timestamp>/`.
- **Memory system removed** — `knowledge.jsonl`, `memory-capture.cjs`, and
  `recall.cjs` are gone. bd's native `bd remember` / `bd memories` takes
  over. Legacy files are cleaned up automatically during upgrade.
- **bd 1.0.2 compatibility** — bd repo moved to gastownhall; install URLs
  updated. Workflow no longer uses the obsolete `inreview` status.
- **Path traversal guard** — upgrade never writes or deletes outside the
  project directory.

Stripped everything that doesn't improve output. Added everything that does.

**Removed:**
- 5 specialized agents (Scout, Detective, Architect, Scribe, Discovery) — duplicated built-in Claude Code capabilities
- Per-tech supervisor generation — 500+ lines of context per stack, Claude already knows these technologies
- Agent personas ("Rex the reviewer") — based on outdated prompting patterns, just fills context
- MCP Provider Delegator, Kanban UI, Web Interface Guidelines — unnecessary infrastructure
- 19 bash hooks — replaced with 3 cross-platform Node.js hooks

**Added:**
- Checklist verification — hook blocks completion if requirements from description aren't checked off
- Session-start dashboard — shows what the task tracker cannot: dirty main checkout, merged PRs awaiting cleanup, worktrees left behind
- Mandatory size check — automatic decision: single bead or epic with children
- Plan-to-beads requirement — all planned tasks must be created as beads before implementation starts
- LEARNED quality enforcement — specific format: problem → solution → context
- Safe install and upgrade — SHA-256 manifest tracks user modifications, `--force` for clean reinstall
- bd command reference in rules — prevents Claude from inventing nonexistent commands

**Changed:**
- Rules are trigger-based ("when you create an API endpoint → add logging") instead of reference documents
- Knowledge base search is mandatory before every investigation
- Dev rules (implementation, logging, TDD) included by default

Full details: [docs/decisions-en.md](docs/decisions-en.md)

## How It Works

### What gets installed

```
.claude/
  agents/
    code-reviewer.md        # Adversarial 3-phase review
    merge-supervisor.md     # Conflict resolution protocol
  hooks/                    # 3 Node.js enforcement hooks, shared utils,
                            # and the update checker they spawn
  rules/
    beads-workflow.md       # Task lifecycle, bd command reference
    pre-code-workflow.md    # Three gates before any edit
    implementation-standard.md
    communication-style.md
    debugging-standard.md
    logging-standard.md
    tdd-workflow.md
    resilience-standard.md
  skills/
    project-discovery/      # Extracts project conventions
  settings.json             # Hook configuration
  .manifest.json            # File hashes for safe upgrades
CLAUDE.md                   # Orchestrator instructions
.beads/                     # Task database + knowledge base
```

That is the `npx` install. As a plugin, only `rules/`, `.manifest.json`,
`CLAUDE.md` and `.beads/` land in the project — the hooks, the agents and the
skill stay in the plugin, which is what lets them update on their own.

### Safe for existing projects — and for upgrades

First install and re-install use the same command: `npx claude-protocol init`.

- **Hooks** — always updated to the latest version (enforcement code). Only files we ship are replaced; a hook of your own is untouched.
- **Rules, agents and the project-discovery skill** — updated only if you haven't modified them. A file you edited becomes a question; the version you don't pick is kept under `.claude/.upgrades/`. Files of your own inside the skill directory are never touched.
- **CLAUDE.md** — only the block between `<!-- claude-protocol:begin -->` and `<!-- claude-protocol:end -->` is ours, and only that block is refreshed. Your overview, tech stack and current state are never touched.
- **settings.json** — hooks merged by event type. Your existing hooks stay.
- **.gitignore** — missing entries appended. Nothing removed.

Use `--force` to take our version of every file. Rules, agents, the skill and the CLAUDE.md block are copied to `.claude/.upgrades/<path>.mine` first, and an earlier copy is never overwritten, so every version you replace is still there. Hooks are replaced outright with no copy — they are enforcement code, replaced on every run anyway.

### What happens at session start

The `session-start` hook says only what the task tracker cannot. `bd prime`
already prints the beads — in progress, ready, blocked, stale — so repeating
them here would cost a second listing and tell you nothing new.

What it does report:

- **ACTION REQUIRED** — a branch that was merged while its worktree and bead
  are still open, with the command to close both
- **WARNING** — uncommitted changes in the main checkout, because agents would
  branch off them
- **Open PRs** — yours, still awaiting review
- **An outdated `bd`** — older than the version the rules rely on, with the
  command to update it
- **A newer claude-protocol** — checked at most once a week, in a process of
  its own with a time limit, and silent on any failure

Nothing to report means nothing printed.

### Project discovery

After installation, run `/project-discovery` in Claude Code. It scans your codebase and writes `.claude/rules/project-conventions.md` with:

- Tech stack and frameworks detected
- Naming conventions and patterns
- Testing setup and commands
- Anti-patterns specific to your project

This file is auto-loaded into every agent context. No per-tech supervisor generation needed.

## Installation

### Prerequisites

- Python 3.11+
- Node.js 20+
- git
- [beads CLI](https://github.com/gastownhall/beads#-installation) (`bd`) 1.1.0
  or newer

### Install

```bash
npx claude-protocol init
```

Restart Claude Code. Run `/project-discovery`.

**When `bd` is missing**, the installer prints the command for your machine and
asks before running it — a global program is your decision. A run nobody can
answer (CI, a batch upgrade, an agent driving the CLI) installs nothing and
prints the command instead; `--install-beads` says yes ahead of time. An
installed `bd` the system still cannot find stops the run: the install
directory is not on this shell's PATH, so open a new terminal and try again.

**When `bd` is older than 1.1.0**, the installer warns and keeps going, and the
session-start hook repeats the warning once per session. Nothing is updated for
you — the rules need `bd memories`, `bd remember`, `bd worktree` and `bd prime`,
and an old `bd` fails those one at a time with no explanation.

### Install as a plugin

The same thing, installed through Claude Code's own plugin system. The plugin
carries the hooks, the agents and the project-discovery skill, and updates them
for you. What a plugin cannot carry is the half that has to live in the
project — the beads database, `.claude/rules/*.md` and the block in
`CLAUDE.md` — so one command lays that half down.

```
/plugin marketplace add weselow/claude-protocol
/plugin install claude-protocol@claude-protocol
/claude-protocol:init
```

Choose the scope when installing: **user** for every project you open,
**project** to share it with everyone on the repository through
`.claude/settings.json`, **local** for this repository and only you. The hooks
stand down in any project that has no `.beads/`, so user scope does not police
your unrelated repositories.

**Auto-update is off by default** for a third-party marketplace — the plugin
stays at the version you installed until you turn it on in `/plugin` →
**Marketplaces** → **claude-protocol** → **Enable auto-update**. Whether it is
on or off, the session-start hook tells you once a week when a newer version is
out.

**Already installed with `npx`?** Nothing runs twice. Hooks merge from every
source, so the copies in `.claude/hooks/` would fire alongside the plugin's —
instead they stand down while the plugin is the active one, and the
session-start hook says the leftovers are there. `/claude-protocol:init`
removes them: it takes out the copies it installed, unwires them from
`settings.json`, and lists what it took; copies of everything removed go to
`.claude/.upgrades/`. Files you added yourself are left alone. Running `npx
claude-protocol init` in a project that has the plugin installs only the
project half, for the same reason — whichever order you install them in, one
source ends up supplying the hooks.

### Options

| Flag | Description |
|------|-------------|
| `--project-dir PATH` | Target directory (default: current) |
| `--project-name NAME` | Project name for CLAUDE.md (auto-inferred from package.json / pyproject.toml / Cargo.toml / go.mod) |
| `--no-rules` | Skip dev rules (implementation, logging, TDD, resilience) |
| `--lang en\|ru` | Language for the dev rules and CLAUDE.md (default: en) |
| `--force` | Take our version of every file, no questions asked (yours is kept in `.claude/.upgrades/`) |
| `--keep-mine` | Keep your version of every file you edited, no questions asked |
| `--install-beads` | Install the beads CLI without asking (default: ask, and install nothing when nobody can answer) |
| `--project-only` | Install only what a plugin cannot carry — beads, rules, CLAUDE.md — and hand hooks, agents and the skill over to the plugin. This is what `/claude-protocol:init` runs |

### Local development (before npm publish)

```bash
cd /path/to/claude-protocol && npm link
npx claude-protocol init  # works in any project
```

## Upgrade

Existing projects upgrade safely: only claude-protocol's own artifacts are
cleaned up, and every removal is backed up first.

When a file you edited also changed on our side, the upgrade asks — per file,
with a diff on request, and `K`/`T` to answer for all the rest at once. The
version you do not choose is kept next to the file under `.claude/.upgrades/`,
so nothing you wrote is ever lost. Where no one can answer — batch upgrades,
CI, an agent driving the CLI — your files are kept and ours are saved beside
them. `--force` and `--keep-mine` answer for every file up front.

**CLAUDE.md is different: it is yours, and only a marked block inside it is
ours.** Everything between `<!-- claude-protocol:begin -->` and
`<!-- claude-protocol:end -->` is replaced on upgrade; the project overview,
tech stack and current state around it are never read, never rewritten. A
project installed before the markers existed is asked once — with a diff —
whether to mark the block it already carries. Say no and nothing changes: the
current template lands in `.claude/.upgrades/CLAUDE.md`, exactly as before.

### Preview (recommended first)

```bash
npx claude-protocol@latest upgrade --dry-run
```

Prints the exact list of files, directories, and settings-hook entries that
would change, and writes nothing at all — every line of the preview is
prefixed `[DRY-RUN]`.

### Apply

```bash
npx claude-protocol@latest upgrade
```

Runs the init flow and then strips obsolete artifacts. Every removal is
backed up under `.claude/.upgrades/<UTC-timestamp>/` so you can roll back by
copying files out of the backup directory.

### Batch (multiple projects)

```bash
npx claude-protocol@latest upgrade --all /path/to/parent
```

Iterates every direct subdirectory of the parent that contains a `.beads/`
folder and upgrades each one. Combine with `--dry-run` to audit before
applying.

### Rollback

The backup directory `.claude/.upgrades/<timestamp>/obsolete/` mirrors the
project tree. Copy the file(s) you want back into place. Nothing is ever
hard-deleted.

## Workflow

### Every task goes through beads

```
Plan → Size check → Create beads → bd ready → Dispatch → Worktree → PR → Merge → Close
```

**Size check** runs automatically before creating beads:
- More than 3 files or multiple domains (DB + API + frontend) → epic with children
- More than 50 lines estimated → consider splitting
- Otherwise → single bead

One bead = one worktree = one PR = one reviewable diff.

### Parallel work

```bash
bd dep add TASK-2 TASK-1    # TASK-2 is blocked by TASK-1
bd close TASK-1              # TASK-2 becomes ready
bd ready                     # shows all unblocked tasks
```

Orchestrator dispatches all ready tasks in parallel via `Task()`.

### Quick fix

For changes under 10 lines on a feature branch. Hard blocked on main.

```bash
git checkout -b fix-typo     # must be off main
# edit → commit
```

### Completion verification

Subagents are blocked from finishing unless:
- `Checklist:` section present with all `[x]` items checked
- Bead status set to `inreview`
- Code committed and pushed
- Comment left on bead
- Response within verbosity limits (25 lines / 1200 chars)

## Hooks

| Hook | Event | Enforcement |
|------|-------|-------------|
| bash-guard | PreToolUse (Bash) | Blocks `--no-verify` and raw `git worktree add`. Requires description on `bd create`. Validates epic close (all children done, PR merged). Every command in a chain is checked, not just the first. |
| validate-completion | SubagentStop | Checks worktree, push, status, checklist, comment, verbosity. |
| session-start | SessionStart | Dirty main checkout, worktrees of merged branches, open PRs, a `bd` older than the rules need, a newer claude-protocol. Task listing is left to `bd prime`. |
| update-check | — | Not a hook: the helper `session-start` spawns so the version check gets a time limit of its own. Answer cached for a week; silent on any failure. |
| hook-utils | — | Shared utilities: project-dir resolution, command splitting, deny/ask/block, execCommand. |

**In a project without `.beads/`, the enforcement hooks stand down.** They act
on a bead lifecycle that is not there, and refusing `--no-verify` in a
repository that never asked for any of this is not their call. It matters for a
plugin installed at user scope, which is loaded for every project you open.

Installed from npm, hook commands resolve `.claude/hooks/` from
`CLAUDE_PROJECT_DIR` rather than a relative path: a hook process inherits the
working directory of the last Bash call, so a relative path stops resolving as
soon as work moves into a subdirectory — and Claude Code reports that as
non-blocking, leaving the hook silently absent. Installed as a plugin, Claude
Code resolves them itself from `hooks/hooks.json` through
`CLAUDE_PLUGIN_ROOT`, and none of that wiring is written into your project.

## Dev Rules

Included by default. Skip with `--no-rules`. Russian version: `npx claude-protocol init --lang ru`.

| Rule | What it does |
|------|-------------|
| pre-code-workflow | Trigger-based: three gates before touching code — entry points and an understanding table, reuse-or-write with `file:line` risks, a 7–15 item plan with an explicit out-of-scope section. Hands off to beads-workflow once the plan is accepted. |
| implementation-standard | Applies while writing code. Metrics (function < 30 lines, class < 200, nesting < 4). Rule of 3 alternatives. Self-review with `/simplify` trigger. |
| communication-style | Trigger-based: fires before every reply. Plain words over jargon, explain a term at first use, numbers instead of adjectives. |
| debugging-standard | Trigger-based: "the same error survived a deliberate fix" → stop repeating, search memory, read the source, then three alternatives. |
| logging-standard | Trigger-based: "creating API endpoint → add logging". Covers external calls, payments, auth, background jobs. Sentry + Seq. |
| tdd-workflow | Trigger-based: "new function → write test first". RED → GREEN → REFACTOR cycle. Clear exceptions (configs, DTOs, migrations). |
| resilience-standard | Trigger-based: "calling external API → what if timeout/5xx?". Covers DB, payments, files, background jobs. Strategies: retry, fallback, circuit breaker, compensation. |

## FAQ

**Q: `bd init` hangs during installation.**
A: Dolt server is not running. Bootstrap creates `.beads/` manually after 15s timeout. Run `bd init` later when Dolt is available, or use SQLite backend.

**Q: Hooks don't work after installation.**
A: Restart Claude Code. Hooks load from `settings.json` at startup.

**Q: Claude invents commands like `bd export`.**
A: `beads-workflow.md` includes a full command reference table. If Claude still invents commands, it didn't read the rules — check that `.claude/rules/` exists.

**Q: What happens if I run `init` again after updating claude-protocol?**
A: Rules, agents and the skill you edited become a question, one file at a time, with a diff on request; the version you do not pick is kept under `.claude/.upgrades/`. Hooks are always updated. In CLAUDE.md only our marked block is refreshed — the rest of the file stays yours. `--force` and `--keep-mine` answer for everything up front.

**Q: Can I use this without Dolt?**
A: Yes. Beads works with SQLite by default. Dolt adds version history and branching for the task database.

## Credits

- [The Claude Protocol](https://github.com/AvivK5498/The-Claude-Protocol) by Aviv Kaplan — original project
- [beads](https://github.com/steveyegge/beads) by Steve Yegge — git-native task tracking
- [`/simplify`](https://github.com/anthropics/claude-code-skills) by Boris Cherny — code simplification skill

## License

MIT
