---
description: Install the project half of Claude Protocol (beads, rules, CLAUDE.md) and hand the hooks, agents and skill over to this plugin
argument-hint: "[--lang ru] [--no-rules] [--install-beads]"
---

Install Claude Protocol into the current project.

The plugin already carries the hooks, the agents and the project-discovery
skill — Claude Code loads those itself. What it cannot carry is the part that
has to live in the project: the beads database, `.claude/rules/*.md` and the
block in `CLAUDE.md`. That is what this command installs.

Run the bootstrap from the plugin, in the project root:

```bash
python "${CLAUDE_PLUGIN_ROOT}/bootstrap.py" --project-dir . --project-only --with-rules $ARGUMENTS
```

Use `python3` instead of `python` on macOS and Linux.

Two things to pass on to the user when it finishes:

- If the output has a **Handed over to the plugin** section, this project had
  an older install from `npx claude-protocol init`. Those files are removed and
  the hook entries unwired, because hooks merge from every source and each one
  would otherwise fire twice. Copies of everything removed are under
  `.claude/.upgrades/`.
- If `bd` was missing, the bootstrap prints the command to install it and stops
  without installing anything. Re-run with `--install-beads` to allow it, or
  install `bd` first.

Do not edit files by hand to work around a failure — report what the bootstrap
said.
