#!/usr/bin/env python3
"""
Bootstrap script for beads-based orchestration.

Creates:
- .beads/ directory with beads CLI
- .claude/agents/ with code-reviewer and merge-supervisor
- .claude/hooks/ with enforcement hooks (Node.js)
- .claude/rules/ with beads-workflow and optional dev rules
- .claude/skills/ with project-discovery
- .claude/settings.json with hook configuration
- .claude/.manifest.json with file hashes for safe upgrades
- .claude/.upgrades/ with new versions of user-modified files
- CLAUDE.md with orchestrator instructions

Usage:
    python bootstrap.py [--project-name NAME] [--project-dir DIR] [--with-rules] [--force]
"""

import os
import re
import sys
import json
import difflib
import hashlib
import shutil
import subprocess
from collections import namedtuple
from datetime import datetime, timezone
from pathlib import Path

try:
    import tomllib
except ImportError:
    tomllib = None

_SHELL = sys.platform == "win32"
SCRIPT_DIR = Path(__file__).parent.resolve()
TEMPLATES_DIR = SCRIPT_DIR / "templates"


# ============================================================================
# OBSOLETE ITEMS (per-release cleanup targets)
# ============================================================================
# v3.3.0 removes the memory-capture / recall.cjs knowledge-base system.
# Pre-manifest installs have these paths on disk but no manifest entry;
# _auto_inject_legacy_files retro-registers them before _cleanup_file runs.

# File paths relative to project_dir. Removed by cleanup_obsolete() ONLY IF
# the path is a key in manifest["files"] (i.e. we installed it — never touch
# user-created files). Backed up before deletion.
OBSOLETE_FILES: list[str] = [
    ".claude/hooks/memory-capture.cjs",
    ".claude/hooks/recall.cjs",
    ".beads/memory/recall.cjs",
    # v3.6.0 hook revision:
    # - enforce-branch-before-edit: branch protection now lives in the rules,
    #   not in a tool-level block on every Edit/Write.
    # - nudge-claude-md-update: asked the model to copy state into CLAUDE.md,
    #   which works against "beads is the single source of truth".
    ".claude/hooks/enforce-branch-before-edit.cjs",
    ".claude/hooks/nudge-claude-md-update.cjs",
]

# Directory paths relative to project_dir. Removed if they exist (no manifest
# check — directories aren't tracked individually). Always backed up before
# deletion. NOTE: .beads/memory is skipped if a non-empty knowledge.jsonl is
# still present — user data is preserved, warning printed.
OBSOLETE_DIRS: list[str] = [
    ".beads/memory",
]

# Substrings matched against hook command strings in .claude/settings.json.
# Any hook entry whose "hooks[0].command" contains one of these substrings
# is stripped. Original settings.json is backed up before writing.
OBSOLETE_SETTINGS_HOOKS: list[str] = [
    "memory-capture.cjs",
    # Shell hooks from the pre-v3 fork. v3 ships no .sh hooks, so these
    # entries point at files that do not exist — every matching tool call
    # paid for a failed spawn and the event ran with one hook missing.
    "block-branch-for-epic-child.sh",
    "clarify-vague-request.sh",
    # v3.6.0 hook revision — see OBSOLETE_FILES above.
    "enforce-branch-before-edit",
    "nudge-claude-md-update",
]

# Substrings matched against hook command strings in
# .claude/settings.local.json. Same semantics as OBSOLETE_SETTINGS_HOOKS.
# `bd prime` used to be a SessionStart hook there; the templated global
# settings.json now owns session bootstrapping, so legacy local entries go.
OBSOLETE_LOCAL_SETTINGS_PATTERNS: list[str] = [
    "bd prime",
]


# ============================================================================
# HOOK COMMAND PATHS
# ============================================================================
# A hook process does NOT run in the project root — it inherits the working
# directory of the last Bash tool call. A relative command path
# (`node .claude/hooks/bash-guard.cjs`) therefore resolves against a
# subdirectory or a worktree, Node exits with "Cannot find module", and Claude
# Code treats it as non-blocking: the tool call proceeds with that hook
# silently absent. templates/settings.json holds the fix — a `node -e` wrapper
# that resolves the project root from CLAUDE_PROJECT_DIR, falling back to
# `git rev-parse --show-toplevel`, then cwd.
#
# The wrapper deliberately avoids `$CLAUDE_PROJECT_DIR` inside the command:
# variable expansion is the shell's job, and hook commands run under
# PowerShell when Git Bash is absent, where `$CLAUDE_PROJECT_DIR` is an
# undefined variable that collapses to an empty string (measured — it fails
# even from the project root).

_HOOK_FILE_RE = re.compile(r"([A-Za-z0-9._-]+\.cjs)")


def _hook_basename(command: str) -> str:
    """Last *.cjs file name referenced by a hook command ('' if none).

    Works for every form the command has taken across versions: a bare
    relative path, an absolute path, a `$CLAUDE_PROJECT_DIR/...` path, or the
    current wrapper where the file name is the trailing argument.
    """
    found = _HOOK_FILE_RE.findall(command or "")
    return found[-1] if found else ""


def canonical_hook_commands() -> dict:
    """hook file name -> canonical command, read from templates/settings.json.

    The template is the single source of truth: bootstrap never hardcodes a
    command string, so template and installed projects cannot drift.
    """
    src = TEMPLATES_DIR / "settings.json"
    if not src.exists():
        return {}
    try:
        data = json.loads(src.read_text(encoding="utf-8"))
    except Exception:
        return {}
    mapping: dict = {}
    for entries in (data.get("hooks") or {}).values():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            try:
                cmd = entry["hooks"][0].get("command", "") or ""
            except Exception:
                continue
            name = _hook_basename(cmd)
            if name:
                mapping[name] = cmd
    return mapping


def _is_our_hook_path(command: str) -> bool:
    """True if the command points into a project's own .claude/hooks/.

    Guards the rewrite against a false positive: a user may keep their own
    `session-start.cjs` under `scripts/`, and matching on the file name alone
    would repoint their hook at ours. Every form we have ever written names
    both path segments — as a path (`.claude/hooks/x.cjs`) or as join()
    arguments inside the wrapper.
    """
    norm = (command or "").replace("\\", "/")
    return ".claude" in norm and "hooks" in norm


def _entry_key(entry) -> tuple:
    """(matcher, command) identity of a hook entry.

    Matcher is part of the key: one command may legitimately be registered for
    several matchers under the same event (Edit and Write, say), and
    deduplicating on the command alone would drop all but the first.
    """
    if not isinstance(entry, dict):
        return "", ""
    matcher = entry.get("matcher", "") or ""
    try:
        cmd = entry["hooks"][0].get("command", "") or ""
    except Exception:
        cmd = ""
    return matcher, cmd


def migrate_hook_commands(hooks: dict, canonical: dict) -> list:
    """Rewrite stale command paths for hooks we own. Mutates `hooks` in place.

    Matches by hook file name, so any older form is recognised. Entries that
    reference a file we do not own (a user's own hook) are left untouched.
    Returns [(old_command, new_command)] for reporting.
    """
    migrated: list = []
    if not isinstance(hooks, dict) or not canonical:
        return migrated
    for entries in hooks.values():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            try:
                spec = entry["hooks"][0]
                old = spec.get("command", "") or ""
            except Exception:
                continue
            if not _is_our_hook_path(old):
                continue
            new = canonical.get(_hook_basename(old))
            if new and new != old:
                spec["command"] = new
                migrated.append((old, new))
    return migrated


def _dedupe_entries(entries: list) -> list:
    """Drop repeated (matcher, command) entries, keeping the first."""
    seen, kept = set(), []
    for entry in entries:
        if not isinstance(entry, dict):
            kept.append(entry)  # malformed — not ours to collapse
            continue
        key = _entry_key(entry)
        if key in seen:
            continue
        seen.add(key)
        kept.append(entry)
    return kept


def merge_hooks(existing: dict, new_hooks: dict) -> list:
    """Merge template hooks into an existing settings dict. Mutates `existing`.

    1. Rewrite stale paths for hooks we own (all events, not just templated
       ones — an older install may have put ours under UserPromptSubmit).
    2. Collapse duplicates that step 1 may have produced.
    3. Append templated entries that are still missing.

    Returns the migration list from step 1.
    """
    hooks = existing.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        hooks = existing["hooks"] = {}
    migrated = migrate_hook_commands(hooks, canonical_hook_commands())

    for event, template_entries in (new_hooks or {}).items():
        current = hooks.setdefault(event, [])
        if not isinstance(current, list):
            current = hooks[event] = []
        merged = _dedupe_entries(current)
        keys = {_entry_key(e) for e in merged}
        for entry in template_entries:
            if _entry_key(entry) not in keys:
                merged.append(entry)
                keys.add(_entry_key(entry))
        hooks[event] = merged
    return migrated


def migrate_local_settings_hooks(project_dir: Path) -> list:
    """Rewrite stale hook paths in .claude/settings.local.json.

    The personal settings file is never templated, but an older install may
    have our hooks in it — a stale path there fails just as silently.
    """
    path = project_dir / ".claude" / "settings.local.json"
    data, hooks = _load_hooks_section(path)
    if data is None:
        return []
    migrated = migrate_hook_commands(hooks, canonical_hook_commands())
    if migrated:
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return migrated


# ============================================================================
# PROJECT NAME INFERENCE
# ============================================================================

def infer_project_name(project_dir: Path) -> str:
    """Auto-infer project name from package files or directory name."""
    for detect_fn in [_from_package_json, _from_pyproject, _from_cargo, _from_go_mod]:
        name = detect_fn(project_dir)
        if name:
            return name
    return project_dir.name.replace("-", " ").replace("_", " ").title()


def _from_package_json(project_dir: Path) -> str | None:
    p = project_dir / "package.json"
    if not p.exists():
        return None
    try:
        name = json.loads(p.read_text(encoding='utf-8')).get("name")
        return name.replace("-", " ").replace("_", " ").title() if name else None
    except Exception:
        return None


def _from_pyproject(project_dir: Path) -> str | None:
    if not tomllib:
        return None
    p = project_dir / "pyproject.toml"
    if not p.exists():
        return None
    try:
        data = tomllib.loads(p.read_text(encoding='utf-8'))
        name = data.get("project", {}).get("name") or data.get("tool", {}).get("poetry", {}).get("name")
        return name.replace("-", " ").replace("_", " ").title() if name else None
    except Exception:
        return None


def _from_cargo(project_dir: Path) -> str | None:
    if not tomllib:
        return None
    p = project_dir / "Cargo.toml"
    if not p.exists():
        return None
    try:
        name = tomllib.loads(p.read_text(encoding='utf-8')).get("package", {}).get("name")
        return name.replace("-", " ").replace("_", " ").title() if name else None
    except Exception:
        return None


def _from_go_mod(project_dir: Path) -> str | None:
    p = project_dir / "go.mod"
    if not p.exists():
        return None
    try:
        for line in p.read_text(encoding='utf-8').splitlines():
            if line.startswith("module "):
                name = line.split()[1].split("/")[-1]
                return name.replace("-", " ").replace("_", " ").title()
    except Exception:
        pass
    return None


# ============================================================================
# HELPERS
# ============================================================================

def copy_and_replace(source: Path, dest: Path, replacements: dict) -> None:
    content = source.read_text(encoding='utf-8')
    for placeholder, value in replacements.items():
        content = content.replace(placeholder, value)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(content, encoding='utf-8')


def read_verbatim(path: Path) -> str:
    """Read a text file without translating its line endings.

    Path.read_text() turns CRLF into LF. Writing that back on Windows turns it
    into CRLF again — a whole-file diff for a two-line edit. Every read that
    feeds an edit-in-place goes through here.
    """
    with open(path, "r", encoding="utf-8", newline="") as f:
        return f.read()


def write_verbatim(path: Path, text: str) -> None:
    """Write text exactly as given — no newline translation on any platform."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)


# ============================================================================
# MANIFEST (upgrade tracking)
# ============================================================================

def file_sha256(path: Path) -> str:
    """Return hex SHA-256 digest of a file's contents."""
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return f"sha256:{h.hexdigest()}"


def content_sha256(content: str) -> str:
    """Return hex SHA-256 digest of string content."""
    h = hashlib.sha256()
    h.update(content.encode("utf-8"))
    return f"sha256:{h.hexdigest()}"


def load_manifest(project_dir: Path) -> dict:
    """Load .claude/.manifest.json or return empty structure."""
    manifest_path = project_dir / ".claude" / ".manifest.json"
    if manifest_path.exists():
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("manifest is not an object")
            # A hand-edited manifest can carry "files": null or a list. Every
            # step downstream reads and writes it as a dict; normalise once
            # here rather than guard at a dozen call sites.
            if not isinstance(data.get("files"), dict):
                data["files"] = {}
            return data
        except Exception:
            pass
    return {"version": None, "installed_at": None, "files": {}}


def save_manifest(project_dir: Path, manifest: dict) -> None:
    """Write .claude/.manifest.json."""
    manifest_path = project_dir / ".claude" / ".manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )


def should_update_file(
    file_path: Path, relative_key: str, manifest: dict, force: bool
) -> tuple:
    """Decide whether to overwrite a file.

    Returns (should_update: bool, reason: str) where reason is one of:
    "new", "unchanged", "modified", "forced", "no_manifest".
    """
    if force:
        return True, "forced"
    if not file_path.exists():
        return True, "new"
    current_hash = file_sha256(file_path)
    recorded_hash = (manifest.get("files") or {}).get(relative_key)
    if recorded_hash is None:
        # Legacy install — treat as user-modified (safe default)
        return False, "no_manifest"
    if current_hash == recorded_hash:
        return True, "unchanged"
    return False, "modified"


def save_upgrade(project_dir: Path, relative_path: str, content: str) -> None:
    """Save new version of a user-modified file to .claude/.upgrades/."""
    dest = project_dir / ".claude" / ".upgrades" / relative_path
    write_verbatim(dest, content)


def _free_spare_slot(dest: Path) -> Path:
    """A <name>.<timestamp> path next to dest that nothing occupies yet."""
    stamp, n = _upgrade_timestamp(), 0
    spare = dest.with_name(f"{dest.name}.{stamp}")
    while spare.exists():
        n += 1
        spare = dest.with_name(f"{dest.name}.{stamp}-{n}")
    return spare


def save_replaced_version(project_dir: Path, rel_key: str, content: str) -> None:
    """Save the version we are about to replace, never overwriting an earlier one.

    Our version in .upgrades/<rel> may be a single slot: it ships with the
    package and can always be had again. The user's cannot, so an earlier .mine
    is copied aside first and only then written over — the order matters, since
    a step that destroys before its replacement exists can fail in between.
    Identical content is not saved twice; that would only add noise.
    """
    dest = project_dir / ".claude" / ".upgrades" / (rel_key + ".mine")
    if not dest.exists():
        write_verbatim(dest, content)
        return
    try:
        previous = read_verbatim(dest)
    except Exception:
        # Bytes we cannot decode, or a directory. Still the user's, so leave it
        # exactly where it is and put ours beside it.
        write_verbatim(_free_spare_slot(dest), content)
        return
    if previous == content:
        return
    write_verbatim(_free_spare_slot(dest), previous)
    write_verbatim(dest, content)


PromptWording = namedtuple("PromptWording", "headline keep take")

# Most conflicts are "you edited this file and we ship a new one". CLAUDE.md is
# not one of those: only a marked block inside it belongs to us, so the same
# k/t/d/K/T question needs different words.
FILE_CONFLICT = PromptWording(
    headline="{rel} — you edited this file, and this version ships a new one.",
    keep="keep yours (ours goes to .claude/.upgrades/{rel})",
    take="take ours  (yours goes to .claude/.upgrades/{rel}.mine)",
)

CLAUDE_MD_UNMARKED = PromptWording(
    headline=("CLAUDE.md — our instructions are in there unmarked.\n"
              "    Marking them lets every upgrade refresh just that block and "
              "leave the rest of your file alone."),
    keep="leave it alone   (ours goes to .claude/.upgrades/CLAUDE.md)",
    take="mark and update  (yours goes to .claude/.upgrades/CLAUDE.md.mine)",
)

CLAUDE_MD_EDITED = PromptWording(
    headline=("CLAUDE.md — what sits between our markers is not what we installed:\n"
              "    either it was edited, or we have no record of installing it."),
    keep="keep your block  (ours goes to .claude/.upgrades/CLAUDE.md)",
    take="take our block   (yours goes to .claude/.upgrades/CLAUDE.md.mine)",
)


class ConflictPrompt:
    """Decides what happens to a file the user has edited and we ship anew.

    Leaving the file alone and dropping the new version in .upgrades/ turns an
    upgrade into homework: the user has to notice, diff and merge by hand. So
    ask — but only when a person is actually there to answer.

    Nobody is there during a batch upgrade over many projects, in CI, or when
    an agent drives the CLI. In those runs the answer stays what it has always
    been: keep the user's file, save ours next to it.
    """

    KEEP, TAKE = "keep", "take"
    _DIFF_LINES = 60

    def __init__(self, interactive: bool = False, sticky: str | None = None):
        self._interactive = interactive
        self._sticky = sticky if sticky in (self.KEEP, self.TAKE) else None
        if not interactive and self._sticky is None:
            self._sticky = self.KEEP

    @property
    def will_ask(self) -> bool:
        return self._interactive and self._sticky is None

    def ask(self, rel_key: str, current: Path, new_text: str,
            wording: PromptWording = None) -> str:
        """Return KEEP or TAKE for one file."""
        if self._sticky:
            return self._sticky
        wording = wording or FILE_CONFLICT
        print(f"\n  {wording.headline.format(rel=rel_key)}")
        print(f"    k  {wording.keep.format(rel=rel_key)}")
        print(f"    t  {wording.take.format(rel=rel_key)}")
        print("    d  show what changed")
        print("    K  keep yours for every remaining file")
        print("    T  take ours for every remaining file")
        while True:
            try:
                answer = input("  [k]: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\n  (no answer — keeping yours)")
                return self.KEEP
            if answer == "d":
                self._show_diff(rel_key, current, new_text)
                continue
            if answer in ("K", "T"):
                self._sticky = self.KEEP if answer == "K" else self.TAKE
                return self._sticky
            if answer == "t":
                return self.TAKE
            if answer in ("", "k"):
                return self.KEEP
            print(f"  '{answer}' is not one of k, t, d, K, T")

    def _show_diff(self, rel_key: str, current: Path, new_text: str) -> None:
        try:
            old_text = current.read_text(encoding="utf-8")
        except Exception as e:
            print(f"  cannot read {rel_key}: {e}")
            return
        diff = list(difflib.unified_diff(
            old_text.splitlines(), new_text.splitlines(),
            fromfile="yours", tofile="ours", lineterm="",
        ))
        if not diff:
            print("  no textual difference (only the recorded hash differs)")
            return
        for line in diff[:self._DIFF_LINES]:
            print(f"  {line}")
        if len(diff) > self._DIFF_LINES:
            print(f"  ... {len(diff) - self._DIFF_LINES} more lines")


def _preserve_before_force(project_dir: Path, rel_key: str, dest: Path,
                           manifest: dict, dry_run: bool) -> bool:
    """--force keeps what it overwrites too. True when a copy was made.

    should_update_file answers "forced" before the conflict prompt is ever
    reached, so this is the only place a --force run can save the user's
    version — and without it an edited rule was simply gone. A file that still
    matches the manifest is ours, and a copy of it would only bury the ones
    that matter.
    """
    if dry_run or not dest.exists():
        return False
    try:
        if file_sha256(dest) == ((manifest or {}).get("files") or {}).get(rel_key):
            return False
        save_replaced_version(project_dir, rel_key, read_verbatim(dest))
    except Exception:
        return False  # unreadable file: overwriting is still what --force means
    return True


def _dry(dry_run: bool) -> str:
    """Prefix for a line describing a write that a dry run did not make."""
    return "[DRY-RUN] " if dry_run else ""


def _stdin_is_a_person() -> bool:
    """True when a human can answer a prompt."""
    try:
        return sys.stdin.isatty() and sys.stdout.isatty()
    except Exception:
        return False


def _resolve_modified(prompt, project_dir: Path, rel_key: str, dest: Path,
                      new_text: str, *, wording: PromptWording = None,
                      dry_run: bool = False) -> bool:
    """Ask (or apply the standing answer). True → write ours over theirs.

    Whichever way it goes, the version that loses is preserved under
    .claude/.upgrades/ — an upgrade never destroys text a person wrote. Except
    in a dry run: saving the loser is itself a write, and a preview writes
    nothing at all.
    """
    if prompt is None:
        prompt = ConflictPrompt(interactive=False)
    if prompt.ask(rel_key, dest, new_text, wording) == ConflictPrompt.TAKE:
        if not dry_run:
            try:
                save_replaced_version(project_dir, rel_key, read_verbatim(dest))
            except Exception:
                pass  # unreadable file: taking ours is still the user's choice
        return True
    if not dry_run:
        save_upgrade(project_dir, rel_key, new_text)
    return False


# ============================================================================
# UPGRADE CLEANUP
# ============================================================================

def _has_existing_install(project_dir: Path) -> bool:
    """True if this project already carries our files.

    Covers pre-manifest installs too: those have no .manifest.json but do have
    the hooks directory, and they are exactly the ones needing cleanup most.
    """
    claude = project_dir / ".claude"
    if (claude / ".manifest.json").exists():
        return True
    hooks = claude / "hooks"
    return hooks.is_dir() and any(hooks.glob("*.cjs"))


def _upgrade_timestamp() -> str:
    """YYYYMMDDTHHMMSSZ — one folder per cleanup_obsolete call."""
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _hook_command_matches(hook_entry: dict, patterns: list) -> tuple:
    """Return (command_str, matched) for a hook entry dict.

    Tolerant of malformed entries — returns ("", False) on any structural error.
    """
    try:
        cmd = hook_entry.get("hooks", [{}])[0].get("command", "") or ""
    except Exception:
        return "", False
    return cmd, any(p in cmd for p in patterns)


def _load_hooks_section(settings_path: Path) -> tuple:
    """Load (data, hooks_dict) from settings file. Returns (None, None) on any failure."""
    if not settings_path.exists():
        return None, None
    try:
        data = json.loads(settings_path.read_text(encoding="utf-8"))
    except Exception:
        return None, None
    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        return None, None
    return data, hooks


def _partition_entries(entries: list, patterns: list) -> tuple:
    """Split hook entries into (kept_entries, stripped_commands) for one event."""
    kept, stripped = [], []
    for entry in entries:
        cmd, matched = _hook_command_matches(entry, patterns)
        if matched:
            stripped.append(cmd)
        else:
            kept.append(entry)
    return kept, stripped


def _strip_obsolete_hooks(
    settings_path: Path, patterns: list, backup_fn, dry_run: bool
) -> list:
    """Strip hook entries whose command contains any of `patterns`. Returns stripped cmds."""
    if not patterns:
        return []
    data, hooks = _load_hooks_section(settings_path)
    if data is None:
        return []
    all_stripped: list = []
    for event, entries in list(hooks.items()):
        if not isinstance(entries, list):
            continue
        kept, stripped = _partition_entries(entries, patterns)
        hooks[event] = kept
        all_stripped.extend(stripped)
    if all_stripped and not dry_run:
        # Ask for the backup directory only now — calling backup_fn() eagerly
        # created an empty timestamped folder on every upgrade that cleaned
        # nothing.
        backup_dir = backup_fn()
        backup_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(settings_path, backup_dir / settings_path.name)
        settings_path.write_text(
            json.dumps(data, indent=2) + "\n", encoding="utf-8"
        )
    return all_stripped


def _iter_hook_commands(settings_path: Path):
    """Yield every hook command string in a settings.json file (tolerant)."""
    if not settings_path.exists():
        return
    try:
        data = json.loads(settings_path.read_text(encoding="utf-8"))
    except Exception:
        return
    for entries in (data.get("hooks") or {}).values():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            try:
                cmd = entry.get("hooks", [{}])[0].get("command", "") or ""
            except Exception:
                cmd = ""
            if cmd:
                yield cmd


def _is_within(child: Path, root: Path) -> bool:
    """Return True if `child` resolves to `root` or any descendant of `root`."""
    try:
        c = child.resolve()
        r = root.resolve()
    except Exception:
        return False
    return c == r or r in c.parents


def _manifest_key(rel: str) -> str:
    """Manifest key for a project-relative path.

    OBSOLETE_FILES holds paths from the project root (`.claude/hooks/x.cjs`)
    because that is what the filesystem operations need, while the manifest is
    keyed from `.claude/` (`hooks/x.cjs`). Without translating between the two,
    cleanup deletes the file and leaves its manifest entry behind for good.
    """
    prefix = ".claude/"
    return rel[len(prefix):] if rel.startswith(prefix) else rel


def _auto_inject_legacy_files(project_dir: Path, manifest: dict,
                              dry_run: bool) -> list:
    """Register OBSOLETE_FILES that exist on disk but pre-date the manifest."""
    injected: list = []
    existing = manifest.get("files", {})
    for rel in OBSOLETE_FILES:
        target = project_dir / rel
        if _manifest_key(rel) in existing or rel in existing:
            continue
        if not target.exists() or not _is_within(target, project_dir):
            continue
        if not dry_run:
            manifest.setdefault("files", {})[_manifest_key(rel)] = "sha256:legacy-auto-injected"
        injected.append(rel)
    return injected


def _memory_dir_should_skip(project_dir: Path) -> tuple:
    """Skip `.beads/memory` removal if knowledge.jsonl has user LEARNED data."""
    knowledge = project_dir / ".beads" / "memory" / "knowledge.jsonl"
    try:
        if knowledge.exists() and knowledge.stat().st_size > 0:
            return True, f"knowledge.jsonl contains {knowledge.stat().st_size} bytes of LEARNED data — preserved for manual review"
    except Exception:
        return False, ""
    return False, ""


def _cleanup_empty_local_settings(project_dir: Path, backup_fn,
                                  dry_run: bool) -> bool:
    """Delete .claude/settings.local.json if no real hook entries remain."""
    path = project_dir / ".claude" / "settings.local.json"
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return False
    if data == {}:
        empty = True
    elif list(data.keys()) == ["hooks"] and isinstance(data.get("hooks"), dict):
        empty = all(isinstance(v, list) and not v for v in data["hooks"].values())
    else:
        empty = False
    if not empty:
        return False
    if dry_run:
        return True
    backup_path = backup_fn() / ".claude" / "settings.local.json"
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, backup_path)
    path.unlink()
    return True


def _cleanup_file(rel: str, project_dir: Path, manifest: dict,
                  backup_fn, dry_run: bool) -> bool:
    """Remove one obsolete file (manifest-gated). Returns True if it was listed."""
    keys = [k for k in (_manifest_key(rel), rel) if k in manifest.get("files", {})]
    if not keys:
        return False
    target = project_dir / rel
    if not _is_within(target, project_dir):
        print(f"[UPGRADE] Skipping suspicious path: {rel} (escapes project_dir)")
        return False
    if not target.exists():
        for key in keys:
            manifest["files"].pop(key, None)
        return False
    if dry_run:
        return True
    backup_path = backup_fn() / rel
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(target, backup_path)
    target.unlink()
    for key in keys:
        manifest["files"].pop(key, None)
    return True


def _cleanup_dir(rel: str, project_dir: Path, manifest: dict,
                 backup_fn, dry_run: bool) -> bool:
    """Remove one obsolete directory. Returns True if it was listed."""
    target = project_dir / rel
    if not _is_within(target, project_dir):
        print(f"[UPGRADE] Skipping suspicious path: {rel} (escapes project_dir)")
        return False
    if not target.exists() or not target.is_dir():
        return False
    if dry_run:
        return True
    backup_path = backup_fn() / rel
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    if backup_path.exists():
        shutil.rmtree(backup_path)
    shutil.copytree(target, backup_path)
    shutil.rmtree(target)
    prefix = rel.rstrip("/") + "/"
    for key in list(manifest.get("files", {}).keys()):
        if key.startswith(prefix):
            manifest["files"].pop(key, None)
    return True


def _cleanup_settings(settings_path: Path, patterns: list,
                      backup_fn, dry_run: bool) -> list:
    """Strip obsolete hooks from one settings file, return list of stripped commands."""
    if not patterns:
        return []
    if dry_run:
        return [c for c in _iter_hook_commands(settings_path)
                if any(p in c for p in patterns)]
    stripped = _strip_obsolete_hooks(
        settings_path, patterns, backup_fn, dry_run
    )
    return stripped


def cleanup_obsolete(project_dir: Path, manifest: dict, dry_run: bool) -> dict:
    """Remove obsolete files/dirs and strip obsolete settings hook entries.

    Safety rules:
    - File is removed only if its relative path is a manifest["files"] key
      (legacy installs get pre-registered via _auto_inject_legacy_files).
    - Directories are removed if they exist, except .beads/memory which is
      preserved when knowledge.jsonl still has user LEARNED data.
    - Every removal is backed up into .claude/.upgrades/<timestamp>/obsolete/<rel>.
    - Settings files are backed up before editing.
    - settings.local.json is removed outright if stripping leaves it with no
      real hook entries.
    - dry_run=True → compute report, touch nothing on disk.
    - manifest is mutated in place; caller is responsible for save_manifest.
    """
    report = {
        "removed_files": [], "removed_dirs": [], "skipped_dirs": [],
        "stripped_settings_hooks": [], "stripped_local_patterns": [],
        "removed_local_settings": False, "legacy_injected": [],
        "backups": [None],
    }

    upgrades_root = project_dir / ".claude" / ".upgrades" / _upgrade_timestamp()
    obsolete_backup = upgrades_root / "obsolete"
    state = {"created": False}

    def backup_fn() -> Path:
        if not state["created"] and not dry_run:
            obsolete_backup.mkdir(parents=True, exist_ok=True)
            state["created"] = True
            report["backups"][0] = str(upgrades_root)
        return obsolete_backup

    report["legacy_injected"] = _auto_inject_legacy_files(
        project_dir, manifest, dry_run,
    )
    # For accurate dry-run preview, register legacy files in manifest temporarily
    # so _cleanup_file's safety gate allows them through. Rolled back after loop.
    dry_run_injected = report["legacy_injected"] if dry_run else []
    for rel in dry_run_injected:
        manifest.setdefault("files", {})[_manifest_key(rel)] = "sha256:legacy-auto-injected"

    for rel in OBSOLETE_FILES:
        if _cleanup_file(rel, project_dir, manifest, backup_fn, dry_run):
            report["removed_files"].append(rel)

    # Roll back the dry-run temporary injection so the caller's manifest is pristine.
    for rel in dry_run_injected:
        manifest.get("files", {}).pop(_manifest_key(rel), None)

    report["stripped_settings_hooks"] = _cleanup_settings(
        project_dir / ".claude" / "settings.json",
        OBSOLETE_SETTINGS_HOOKS, backup_fn, dry_run,
    )
    report["stripped_local_patterns"] = _cleanup_settings(
        project_dir / ".claude" / "settings.local.json",
        OBSOLETE_LOCAL_SETTINGS_PATTERNS, backup_fn, dry_run,
    )
    report["removed_local_settings"] = _cleanup_empty_local_settings(
        project_dir, backup_fn, dry_run,
    )

    for rel in OBSOLETE_DIRS:
        if rel == ".beads/memory":
            skip, reason = _memory_dir_should_skip(project_dir)
            if skip:
                print(f"[UPGRADE] Skipping .beads/memory/: {reason}")
                report["skipped_dirs"].append((rel, reason))
                continue
        if _cleanup_dir(rel, project_dir, manifest, backup_fn, dry_run):
            report["removed_dirs"].append(rel)
    return report


def run_bd_doctor(project_dir: Path) -> None:
    """Run `bd doctor` and print first 20 lines. Soft-fail on any error."""
    if not shutil.which("bd"):
        print("  bd doctor unavailable: bd not found in PATH")
        return
    try:
        result = subprocess.run(
            ["bd", "doctor"], cwd=project_dir,
            capture_output=True, text=True, shell=_SHELL,
            stdin=subprocess.DEVNULL, timeout=15,
        )
    except subprocess.TimeoutExpired:
        print("  bd doctor unavailable: timed out after 15s")
        return
    except Exception as e:
        print(f"  bd doctor unavailable: {e}")
        return

    if result.returncode != 0:
        reason = (result.stderr or result.stdout or "non-zero exit").strip().splitlines()
        reason_first = reason[0] if reason else f"exit {result.returncode}"
        print(f"  bd doctor unavailable: {reason_first}")
        return

    print("  bd doctor:")
    for line in (result.stdout or "").splitlines()[:20]:
        print(f"    {line}")


# ============================================================================
# STEPS
# ============================================================================

def install_beads(project_dir: Path, dry_run: bool = False) -> bool:
    """Install beads CLI and initialize .beads directory."""
    print("\n[1/6] Installing beads...")

    if dry_run:
        # A preview writes nothing and shells out to nothing. This step used to
        # ignore the flag and create .beads/ on the project it was previewing.
        have_bd = bool(shutil.which("bd"))
        print(f"  - beads CLI {'already installed' if have_bd else 'would be installed'}")
        if not (project_dir / ".beads").exists():
            print("  - [DRY-RUN] would run 'bd init' in this project")
        print("  DONE")
        return True

    if not shutil.which("bd"):
        print("  - beads CLI (bd) not found, installing...")
        for method, cmd in [
            ("Homebrew", ["brew", "install", "gastownhall/beads/bd"]),
            ("npm", ["npm", "install", "-g", "@beads/bd"]),
            ("go", ["go", "install", "github.com/gastownhall/beads/cmd/bd@latest"]),
        ]:
            if shutil.which(cmd[0]):
                result = subprocess.run(cmd, capture_output=True, text=True, shell=_SHELL)
                if result.returncode == 0:
                    print(f"  - Installed via {method}")
                    break
        else:
            print("  ERROR: Could not install beads CLI (bd)")
            print("  Install manually: https://github.com/gastownhall/beads#-installation")
            return False
    else:
        print("  - beads CLI already installed")

    beads_dir = project_dir / ".beads"
    if not beads_dir.exists():
        print("  - Initializing .beads directory...")
        try:
            result = subprocess.run(
                ["bd", "init"], cwd=project_dir,
                capture_output=True, text=True, shell=_SHELL,
                stdin=subprocess.DEVNULL, timeout=15,
            )
        except subprocess.TimeoutExpired:
            result = None
            print("  - bd init timed out (Dolt server not running?)")
        if result is None or result.returncode != 0:
            beads_dir.mkdir(exist_ok=True)
            (beads_dir / "issues.jsonl").touch()
            print("  - Created .beads manually (run 'bd init' later with Dolt server running)")

    # Stop bd's pre-commit shim from force-staging issues.jsonl (bd >=1.0.2
    # defaults export.git-add=true, which re-stages the JSONL on every commit
    # and can drop a duplicate /issues.jsonl at the repo root). Best-effort:
    # never fail the whole bootstrap on this.
    configure_beads_export(project_dir)

    print("  DONE")
    return True


def configure_beads_export(project_dir: Path) -> bool:
    """Disable bd's auto-staging of issues.jsonl (export.git-add=false).

    Returns True on success. Never raises — if bd is missing or the command
    fails/times out, logs a warning and returns False so bootstrap can continue.
    """
    if not shutil.which("bd"):
        print("  - bd not available, skipping export.git-add config "
              "(run 'bd config set export.git-add false' later)")
        return False
    try:
        result = subprocess.run(
            ["bd", "config", "set", "export.git-add", "false"],
            cwd=project_dir, capture_output=True, text=True,
            shell=_SHELL, stdin=subprocess.DEVNULL, timeout=15,
        )
    except subprocess.TimeoutExpired:
        print("  - bd config set export.git-add timed out (Dolt server not running?)")
        return False
    except OSError as exc:
        print(f"  - bd config set export.git-add failed to start: {exc}")
        return False
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        print("  - WARNING: bd config set export.git-add false failed"
              + (f": {detail}" if detail else ""))
        return False
    print("  - Set export.git-add=false (prevents duplicate /issues.jsonl)")
    return True


def copy_agents(
    project_dir: Path, project_name: str,
    manifest: dict, force: bool = False, prompt=None, dry_run: bool = False,
) -> list:
    """Copy code-reviewer and merge-supervisor templates."""
    print("\n[2/6] Copying agents...")
    agents_dir = project_dir / ".claude" / "agents"
    if not dry_run:
        agents_dir.mkdir(parents=True, exist_ok=True)
    skipped = []

    replacements = {"[Project]": project_name}
    for agent_file in (TEMPLATES_DIR / "agents").glob("*.md"):
        dest = agents_dir / agent_file.name
        rel_key = f"agents/{agent_file.name}"
        ok, reason = should_update_file(dest, rel_key, manifest, force)
        new_content = agent_file.read_text(encoding="utf-8")
        for placeholder, value in replacements.items():
            new_content = new_content.replace(placeholder, value)
        if not ok:
            ok = _resolve_modified(prompt, project_dir, rel_key, dest, new_content,
                                   dry_run=dry_run)
            reason = "replaced on request" if ok else reason
        if ok:
            if reason == "forced" and _preserve_before_force(
                    project_dir, rel_key, dest, manifest, dry_run):
                print(f"    yours saved to: .claude/.upgrades/{rel_key}.mine")
            if not dry_run:
                copy_and_replace(agent_file, dest, replacements)
                manifest["files"][rel_key] = file_sha256(dest)
            print(f"  - {_dry(dry_run)}{agent_file.name}"
                  + (f" ({reason})" if reason != "new" else ""))
        else:
            skipped.append(rel_key)
            print(f"  - {agent_file.name} (yours kept)")
    print("  DONE")
    return skipped


def copy_hooks(project_dir: Path, manifest: dict, dry_run: bool = False) -> None:
    """Copy Node.js hooks (always overwrite — enforcement code)."""
    print("\n[3/6] Copying hooks...")
    hooks_dir = project_dir / ".claude" / "hooks"
    if not dry_run:
        hooks_dir.mkdir(parents=True, exist_ok=True)

    for hook_file in (TEMPLATES_DIR / "hooks").glob("*.cjs"):
        dest = hooks_dir / hook_file.name
        if not dry_run:
            shutil.copy2(hook_file, dest)
            manifest["files"][f"hooks/{hook_file.name}"] = file_sha256(dest)
        print(f"  - {_dry(dry_run)}{hook_file.name}")
    print("  DONE")


def copy_rules_and_skills(
    project_dir: Path, with_rules: bool, lang: str = "en",
    manifest: dict = None, force: bool = False, prompt=None,
    dry_run: bool = False,
) -> list:
    """Copy beads-workflow rule, project-discovery skill, and optional dev rules."""
    print("\n[4/6] Copying rules and skills...")
    rules_dir = project_dir / ".claude" / "rules"
    if not dry_run:
        rules_dir.mkdir(parents=True, exist_ok=True)
    skipped = []

    # Determine source directory based on language
    rules_src_dir = TEMPLATES_DIR / ("rules-ru" if lang == "ru" else "rules")

    # Always copy beads workflow — it is the one rule that is not optional.
    # Use the translated file when the language has one; every translation keeps
    # the completion-report strings verbatim (`BEAD {ID} COMPLETE`, `Checklist:`)
    # because validate-completion.cjs matches on them.
    beads_src = rules_src_dir / "beads-workflow.md"
    if not beads_src.exists():
        beads_src = TEMPLATES_DIR / "rules" / "beads-workflow.md"
    if beads_src.exists():
        dest = rules_dir / "beads-workflow.md"
        rel_key = "rules/beads-workflow.md"
        ok, reason = should_update_file(dest, rel_key, manifest, force)
        if not ok:
            ok = _resolve_modified(prompt, project_dir, rel_key, dest,
                                   beads_src.read_text(encoding="utf-8"),
                                   dry_run=dry_run)
            reason = "replaced on request" if ok else reason
        if ok:
            if reason == "forced" and _preserve_before_force(
                    project_dir, rel_key, dest, manifest, dry_run):
                print(f"    yours saved to: .claude/.upgrades/{rel_key}.mine")
            if not dry_run:
                shutil.copy2(beads_src, dest)
                manifest["files"][rel_key] = file_sha256(dest)
            print(f"  - {_dry(dry_run)}rules/beads-workflow.md"
                  + (f" ({reason})" if reason != "new" else ""))
        else:
            skipped.append(rel_key)
            print(f"  - rules/beads-workflow.md (yours kept)")
            print(f"    {_dry(dry_run)}Ours saved to: .claude/.upgrades/{rel_key}")

    # Optional dev rules (from language-specific directory)
    if with_rules:
        for rule_file in rules_src_dir.glob("*.md"):
            if rule_file.name != "beads-workflow.md":
                dest = rules_dir / rule_file.name
                rel_key = f"rules/{rule_file.name}"
                ok, reason = should_update_file(dest, rel_key, manifest, force)
                if not ok:
                    ok = _resolve_modified(prompt, project_dir, rel_key, dest,
                                           rule_file.read_text(encoding="utf-8"),
                                           dry_run=dry_run)
                    reason = "replaced on request" if ok else reason
                if ok:
                    if reason == "forced" and _preserve_before_force(
                            project_dir, rel_key, dest, manifest, dry_run):
                        print(f"    yours saved to: .claude/.upgrades/{rel_key}.mine")
                    if not dry_run:
                        shutil.copy2(rule_file, dest)
                        manifest["files"][rel_key] = file_sha256(dest)
                    suffix = f" ({lang})" if lang != "en" else ""
                    suffix += f" ({reason})" if reason != "new" else ""
                    print(f"  - {_dry(dry_run)}rules/{rule_file.name}{suffix}")
                else:
                    skipped.append(rel_key)
                    print(f"  - rules/{rule_file.name} (yours kept)")
                    print(f"    {_dry(dry_run)}Ours saved to: .claude/.upgrades/{rel_key}")

    skipped += copy_skill(project_dir, manifest, force, prompt, dry_run)

    print("  DONE")
    return skipped


def copy_skill(project_dir: Path, manifest: dict, force: bool = False,
               prompt=None, dry_run: bool = False) -> list:
    """Copy the project-discovery skill, one file at a time.

    It used to be rmtree + copytree, on the grounds that the directory is our
    code. It is not: SKILL.md is a prompt people tune the way they tune a rule,
    and anything they kept beside it was deleted with no copy — on a plain run,
    no flag, no question. So each file we ship goes through the same question a
    rule does, and a file we do not ship is left where its owner put it.
    """
    skill_src = TEMPLATES_DIR / "skills" / "project-discovery"
    if not skill_src.exists():
        return []
    skipped = []
    for src in sorted(p for p in skill_src.rglob("*") if p.is_file()):
        rel = str(src.relative_to(skill_src)).replace("\\", "/")
        rel_key = f"skills/project-discovery/{rel}"
        dest = project_dir / ".claude" / rel_key
        ok, reason = should_update_file(dest, rel_key, manifest, force)
        if not ok:
            ok = _resolve_modified(prompt, project_dir, rel_key, dest,
                                   read_verbatim(src), dry_run=dry_run)
            reason = "replaced on request" if ok else reason
        if ok:
            if reason == "forced" and _preserve_before_force(
                    project_dir, rel_key, dest, manifest, dry_run):
                print(f"    yours saved to: .claude/.upgrades/{rel_key}.mine")
            if not dry_run:
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dest)
                manifest["files"][rel_key] = file_sha256(dest)
            print(f"  - {_dry(dry_run)}{rel_key}"
                  + (f" ({reason})" if reason != "new" else ""))
        else:
            skipped.append(rel_key)
            print(f"  - {rel_key} (yours kept)")
            print(f"    {_dry(dry_run)}Ours saved to: .claude/.upgrades/{rel_key}")
    return skipped


# ============================================================================
# CLAUDE.md — the one block in it that is ours
# ============================================================================
# CLAUDE.md belongs to the project: overview, tech stack, current state. Only
# what sits between our two markers is ours, and only that is replaced on an
# upgrade. Everything a person wrote around the markers is never touched.

_BEGIN_RE = re.compile(r"<!--\s*claude-protocol:begin\b.*?-->", re.DOTALL)
_END_RE = re.compile(r"<!--\s*claude-protocol:end\s*-->")
_HEADING_RE = re.compile(r"^(#{1,2})\s+(.+?)\s*$")

# Installs made before the markers existed. The block starts at "Your Identity"
# and runs on while the headings are ours; the set covers every 3.x template,
# including sections since dropped (Knowledge Base, Investigation Before
# Delegation) — a project can still be carrying them.
CLAUDE_MD_BLOCK_START = "Your Identity"
CLAUDE_MD_BLOCK_HEADINGS = {
    "Your Identity", "Workflow", "Investigation Before Delegation",
    "Bug Fixes & Follow-Up", "Knowledge Base", "Agents",
}

_CLAUDE_MD_NOTE = {
    "marked": "our block refreshed",
    "unmarked": "our block marked and refreshed",
    "appended": "our block appended",
}


def _lf(text: str) -> str:
    """Line endings normalised, so a CRLF checkout hashes like an LF one."""
    return text.replace("\r\n", "\n")


def marked_span(text: str) -> tuple:
    """(start, end) of our marked region, markers included, or None."""
    begin = _BEGIN_RE.search(text)
    if not begin:
        return None
    end = _END_RE.search(text, begin.end())
    return (begin.start(), end.end()) if end else None


def _block_end(lines: list, offsets: list, start: int, stop: int) -> int:
    """Offset just past the block's last non-blank line."""
    while stop > start + 1 and not lines[stop - 1].strip():
        stop -= 1
    return offsets[stop]


def unmarked_span(text: str) -> tuple:
    """(start, end) of our block in a CLAUDE.md written before the markers.

    Walks forward only while the headings are ours and stops at the first one
    that is not, so a section the user added between ours is never swallowed.
    """
    lines = text.splitlines(keepends=True)
    offsets, pos = [], 0
    for line in lines:
        offsets.append(pos)
        pos += len(line)
    offsets.append(pos)

    start = None
    for i, line in enumerate(lines):
        heading = _HEADING_RE.match(line.rstrip("\r\n"))
        if not heading:
            continue
        level, title = len(heading.group(1)), heading.group(2)
        if start is None:
            if level == 2 and title == CLAUDE_MD_BLOCK_START:
                start = i
        elif title not in CLAUDE_MD_BLOCK_HEADINGS:
            return offsets[start], _block_end(lines, offsets, start, i)
    if start is None:
        return None
    return offsets[start], _block_end(lines, offsets, start, len(lines))


def splice(text: str, span: tuple, region: str) -> str:
    """Replace text[span] with region, in the line endings the file already uses."""
    region = _lf(region)
    if "\r\n" in text:
        region = region.replace("\n", "\r\n")
    return text[:span[0]] + region + text[span[1]:]


def _claude_md_proposal(current: str, region: str) -> tuple:
    """(whole proposed file, kind) for a CLAUDE.md that already exists.

    kind is "marked" (our region is in there), "unmarked" (our block is there
    without markers), "appended" (nothing of ours yet) or "unknown"
    (orchestration text we cannot delimit — nothing is proposed for that one).
    """
    span = marked_span(current)
    if span:
        return splice(current, span, region), "marked"
    span = unmarked_span(current)
    if span:
        return splice(current, span, region), "unmarked"
    if "## Workflow" in current and "beads" in current.lower():
        return None, "unknown"
    addition = "\n\n---\n\n# Beads Orchestration\n\n" + _lf(region) + "\n"
    if "\r\n" in current:
        addition = addition.replace("\n", "\r\n")
    return current.rstrip("\r\n") + addition, "appended"


def _block_is_ours(current: str, manifest: dict) -> bool:
    """True when the marked region is what we last installed, byte for byte.

    Only a recorded hash proves that. Without one the markers could be anything
    — a lost or unreadable manifest, a pair typed by hand, a file whose prose
    quotes both marker strings — and replacing what sits between them would
    delete text nobody agreed to lose. So: no hash, no silent replacement.
    """
    span = marked_span(current)
    recorded = manifest.get("claude_md_block")
    if not span or not recorded:
        return False
    return content_sha256(_lf(current[span[0]:span[1]])) == recorded


def _write_claude_md(dest: Path, text: str, region: str, manifest: dict,
                     dry_run: bool) -> None:
    """Write the file and remember the block, so the next upgrade knows it is ours."""
    if dry_run:
        return
    write_verbatim(dest, text)
    manifest["claude_md_block"] = content_sha256(_lf(region))


def _hand_over_template(project_dir: Path, template_text: str, why: str,
                        dry_run: bool) -> None:
    """Cannot tell where our part ends: leave the file, drop the template beside it."""
    if not dry_run:
        save_upgrade(project_dir, "CLAUDE.md", template_text)
    print(f"  - CLAUDE.md (kept — {why})")
    print(f"    {_dry(dry_run)}Current template saved to: .claude/.upgrades/CLAUDE.md")


def update_claude_md(project_dir: Path, template_text: str, manifest: dict = None,
                     prompt=None, dry_run: bool = False) -> None:
    """Refresh our block in CLAUDE.md without touching a line the user wrote."""
    dest = project_dir / "CLAUDE.md"
    manifest = manifest if manifest is not None else {}
    span = marked_span(template_text)
    region = template_text[span[0]:span[1]] if span else None

    if not dest.exists():
        _write_claude_md(dest, template_text, region or template_text, manifest, dry_run)
        print(f"  - {_dry(dry_run)}CLAUDE.md (created)")
        return
    if region is None:  # the template lost its markers — never guess
        _hand_over_template(project_dir, template_text, "template has no markers", dry_run)
        return

    current = read_verbatim(dest)
    proposed, kind = _claude_md_proposal(current, region)
    if kind == "unknown":
        _hand_over_template(project_dir, template_text,
                            "our block is not marked and not recognisable", dry_run)
        return

    # Nothing of ours in the file yet, or our block still exactly as installed:
    # replacing it destroys nothing, so it needs no question.
    silent = kind == "appended" or (kind == "marked" and _block_is_ours(current, manifest))
    wording = CLAUDE_MD_EDITED if kind == "marked" else CLAUDE_MD_UNMARKED
    if not silent and not _resolve_modified(prompt, project_dir, "CLAUDE.md", dest,
                                            proposed, wording=wording, dry_run=dry_run):
        print("  - CLAUDE.md (yours kept)")
        print(f"    {_dry(dry_run)}Ours saved to: .claude/.upgrades/CLAUDE.md")
        return
    _write_claude_md(dest, proposed, region, manifest, dry_run)
    print(f"  - {_dry(dry_run)}CLAUDE.md ({_CLAUDE_MD_NOTE[kind]})")


def copy_settings_and_claude_md(project_dir: Path, project_name: str,
                                dry_run: bool = False, manifest: dict = None,
                                prompt=None) -> None:
    """Copy settings.json (merge hooks) and refresh our block in CLAUDE.md."""
    print("\n[5/6] Copying settings and CLAUDE.md...")

    # --- settings.json: merge hooks into existing ---
    settings_dest = project_dir / ".claude" / "settings.json"
    settings_src = TEMPLATES_DIR / "settings.json"
    if settings_src.exists():
        new_settings = json.loads(settings_src.read_text(encoding='utf-8'))
        if settings_dest.exists():
            try:
                before = settings_dest.read_text(encoding='utf-8')
                existing = json.loads(before)
                migrated = merge_hooks(existing, new_settings.get("hooks", {}))
                if not dry_run:
                    # The only write we make into a file the user owns. Keep the
                    # previous version reachable before touching it.
                    save_upgrade(project_dir, "settings.json.before-merge", before)
                    settings_dest.write_text(json.dumps(existing, indent=2) + "\n", encoding='utf-8')
                print(f"  - {_dry(dry_run)}settings.json (merged hooks)")
                for old_cmd, _ in migrated:
                    print(f"    rewrote hook path: {old_cmd[:70]}")
            except Exception:
                if not dry_run:
                    # Unparseable is not the same as worthless: someone was
                    # probably editing it. Copy the bytes out before replacing.
                    try:
                        kept = (project_dir / ".claude" / ".upgrades"
                                / "settings.json.before-merge")
                        kept.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(settings_dest, kept)
                    except Exception:
                        pass
                    shutil.copy2(settings_src, settings_dest)
                print(f"  - {_dry(dry_run)}settings.json (replaced — could not merge)")
                print(f"    {_dry(dry_run)}Yours saved to: "
                      ".claude/.upgrades/settings.json.before-merge")
        else:
            if not dry_run:
                settings_dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(settings_src, settings_dest)
            print(f"  - {_dry(dry_run)}settings.json")

    # --- settings.local.json: same stale-path rewrite, never templated ---
    for old_cmd, _ in (migrate_local_settings_hooks(project_dir) if not dry_run else []):
        print(f"  - settings.local.json: rewrote hook path: {old_cmd[:70]}")

    # --- CLAUDE.md: refresh our marked block, leave the rest of the file alone ---
    claude_src = TEMPLATES_DIR / "CLAUDE.md"
    if claude_src.exists():
        template_text = read_verbatim(claude_src).replace("[Project]", project_name)
        update_claude_md(project_dir, template_text, manifest, prompt, dry_run)

    print("  DONE")


def setup_gitignore(project_dir: Path, dry_run: bool = False) -> None:
    """Ensure .worktrees/, .claude/.upgrades/, and /issues.jsonl are in .gitignore.

    NOTE: the beads tracker travels with the repo, so .beads/ is intentionally
    NOT ignored — the canonical .beads/issues.jsonl must stay under git. Dolt
    runtime/binary files are excluded by .beads/.gitignore (written by bd init).
    /issues.jsonl guards against an export that lands at the repo root.
    """
    print("\n[6/6] Setting up .gitignore...")
    gitignore_path = project_dir / ".gitignore"
    entries = [".worktrees/", ".claude/.upgrades/", "/issues.jsonl"]

    if gitignore_path.exists():
        content = gitignore_path.read_text(encoding='utf-8')
        lines = content.splitlines()
        missing = [
            e for e in entries
            if e not in lines and e.rstrip("/") not in lines
        ]
        if missing:
            if dry_run:
                for entry in missing:
                    print(f"  - {_dry(dry_run)}Would add {entry}")
            else:
                with open(gitignore_path, "a", encoding="utf-8") as f:
                    if content and not content.endswith("\n"):
                        f.write("\n")
                    f.write("\n# Beads orchestration\n")
                    for entry in missing:
                        f.write(f"{entry}\n")
                        print(f"  - Added {entry}")
        else:
            print("  - Already configured")
    else:
        if not dry_run:
            gitignore_path.write_text(
                "# Beads orchestration\n.worktrees/\n.claude/.upgrades/\n/issues.jsonl\n",
                encoding='utf-8',
            )
        print(f"  - {_dry(dry_run)}Created .gitignore")

    print("  DONE")


# ============================================================================
# MAIN
# ============================================================================

def _print_cleanup_report(report: dict, dry_run: bool) -> None:
    """Print a [UPGRADE] Cleanup: block from cleanup_obsolete report."""
    prefix = "[DRY-RUN] " if dry_run else ""
    print("\n[UPGRADE] Cleanup:")
    for rel in report.get("legacy_injected", []):
        print(f"  {prefix}auto-injected legacy file into manifest: {rel}")
    for rel in report["removed_files"]:
        print(f"  {prefix}removed file: {rel}")
    for rel in report["removed_dirs"]:
        print(f"  {prefix}removed dir:  {rel}")
    for rel, reason in report.get("skipped_dirs", []):
        print(f"  {prefix}skipped dir:  {rel} ({reason})")
    for cmd in report["stripped_settings_hooks"]:
        print(f"  {prefix}stripped settings hook: {cmd}")
    for cmd in report["stripped_local_patterns"]:
        print(f"  {prefix}stripped local hook:    {cmd}")
    if report.get("removed_local_settings"):
        print(f"  {prefix}removed file: .claude/settings.local.json (no hooks left)")
    backup = report["backups"][0]
    if backup:
        print(f"  backup: {backup}")
    if not any([
        report["removed_files"], report["removed_dirs"],
        report.get("skipped_dirs"),
        report["stripped_settings_hooks"], report["stripped_local_patterns"],
        report.get("removed_local_settings"),
        report.get("legacy_injected"),
    ]):
        print("  nothing to clean")


def bootstrap_project(
    project_dir: Path, project_name: str | None, with_rules: bool,
    lang: str, force: bool, upgrade: bool, dry_run: bool,
    keep_mine: bool = False,
) -> int:
    """Run bootstrap for a single project. Returns exit code (0 = success)."""
    if not dry_run:
        project_dir.mkdir(parents=True, exist_ok=True)
    resolved_name = project_name or infer_project_name(project_dir)

    # An upgrade must not silently switch a project's language back to English:
    # --lang is optional, and the manifest remembers what was installed.
    installed_lang = load_manifest(project_dir).get("lang")
    lang = lang or installed_lang or "en"

    # A project that already has our files gets the cleanup pass even without
    # --upgrade. Skipping it leaves a half-migrated mix: new hooks installed
    # next to entries for hooks this version no longer ships.
    if not upgrade and _has_existing_install(project_dir):
        upgrade = True
        print("Existing installation detected — running the upgrade cleanup too")

    print(f"\nBootstrapping beads orchestration for: {resolved_name}")
    print(f"Directory: {project_dir}")
    if force:
        print("Mode: FORCE (overwriting all files)")
    if upgrade:
        print("Mode: UPGRADE" + (" (dry-run)" if dry_run else ""))
    print("=" * 60)

    if not TEMPLATES_DIR.exists():
        print(f"\nERROR: Templates not found: {TEMPLATES_DIR}")
        return 1

    manifest = load_manifest(project_dir)
    all_skipped = []

    # Files the user edited are a question, not a silent skip. --force answers
    # "take ours" for all of them, --keep-mine answers "keep mine", a dry run
    # asks nothing, and a run with no person attached keeps the user's files.
    prompt = ConflictPrompt(
        interactive=not (force or keep_mine or dry_run) and _stdin_is_a_person(),
        sticky=(ConflictPrompt.TAKE if force
                else ConflictPrompt.KEEP if keep_mine or dry_run else None),
    )
    if prompt.will_ask:
        print("\nFiles you edited will be shown one by one — you decide each.")

    if not install_beads(project_dir, dry_run):
        return 1

    all_skipped += copy_agents(project_dir, resolved_name, manifest, force,
                               prompt, dry_run)
    copy_hooks(project_dir, manifest, dry_run)
    all_skipped += copy_rules_and_skills(
        project_dir, with_rules, lang, manifest, force, prompt, dry_run,
    )
    copy_settings_and_claude_md(project_dir, resolved_name, dry_run, manifest, prompt)
    setup_gitignore(project_dir, dry_run)

    # Read version from package.json (same package as bootstrap.py)
    pkg_json = SCRIPT_DIR / "package.json"
    pkg_version = None
    if pkg_json.exists():
        try:
            pkg_version = json.loads(pkg_json.read_text(encoding="utf-8")).get("version")
        except Exception:
            pass

    # Run upgrade cleanup AFTER init steps so manifest reflects our files.
    # Legacy installs without manifest are handled by _auto_inject_legacy_files
    # inside cleanup_obsolete — the OBSOLETE_* paths are dev-controlled and safe.
    if upgrade:
        report = cleanup_obsolete(project_dir, manifest, dry_run)
        _print_cleanup_report(report, dry_run)

    manifest["version"] = pkg_version
    manifest["lang"] = lang
    manifest["installed_at"] = datetime.now(timezone.utc).isoformat()
    if not dry_run:
        save_manifest(project_dir, manifest)

    print("\n" + "=" * 60)
    print("BOOTSTRAP COMPLETE")
    print("=" * 60)

    if all_skipped:
        print(f"\n  {len(all_skipped)} file(s) kept as yours:")
        for rel in all_skipped:
            print(f"    - {rel}")
            print(f"      {_dry(dry_run)}Ours is next to it: .claude/.upgrades/{rel}")
        print("    Re-run with --force to take ours for all of them.")

    # Post-upgrade health check — never fatal
    if upgrade and not dry_run:
        print("")
        run_bd_doctor(project_dir)

    print(f"""
Next steps:

1. Restart Claude Code to load hooks and agents
2. Run /project-discovery to extract project conventions
3. Create your first bead: bd create "Task" -d "Description"
4. Dispatch work: Task(subagent_type="general-purpose", prompt="BEAD_ID: ...")
""")
    return 0


def run_batch_upgrade(
    parent_dir: Path, with_rules: bool, lang: str, force: bool, dry_run: bool,
    keep_mine: bool = False,
) -> int:
    """Iterate direct subdirs of parent_dir that contain .beads/ and upgrade each."""
    if not parent_dir.exists() or not parent_dir.is_dir():
        print(f"ERROR: --all parent directory not found: {parent_dir}")
        return 1

    # Nobody upgrading twenty projects reads twenty diffs. A batch upgrade
    # keeps every file the user edited and saves ours beside it — which is what
    # the README has always promised. Only --force overrides that.
    if not force:
        keep_mine = True

    print(f"\n[BATCH UPGRADE] Scanning {parent_dir}")
    if force:
        print("  Taking our version of every file;"
              " yours go to .claude/.upgrades/")
    else:
        print("  Files you edited are kept; ours go to .claude/.upgrades/"
              " (--force to take ours)")
    candidates = sorted(p for p in parent_dir.iterdir() if p.is_dir())
    upgraded = 0
    skipped: list = []

    for child in candidates:
        if not (child / ".beads").is_dir():
            skipped.append((child.name, "no .beads/"))
            continue
        print(f"\n{'#' * 60}\n# {child.name}\n{'#' * 60}")
        try:
            rc = bootstrap_project(
                project_dir=child, project_name=None, with_rules=with_rules,
                lang=lang, force=force, upgrade=True, dry_run=dry_run,
                keep_mine=keep_mine,
            )
            if rc == 0:
                upgraded += 1
            else:
                skipped.append((child.name, f"exit {rc}"))
        except Exception as e:
            skipped.append((child.name, f"exception: {e}"))

    print("\n" + "=" * 60)
    print(f"BATCH UPGRADE SUMMARY: {upgraded} upgraded, {len(skipped)} skipped")
    print("=" * 60)
    for name, reason in skipped:
        print(f"  - {name}: {reason}")
    return 0


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Bootstrap beads orchestration")
    parser.add_argument("--project-name", default=None, help="Project name (auto-inferred if not provided)")
    parser.add_argument("--project-dir", default=".", help="Project directory")
    parser.add_argument("--with-rules", action="store_true", help="Also copy dev rules (implementation-standard, logging, tdd)")
    parser.add_argument("--lang", default=None, choices=["en", "ru"], help="Language for dev rules (default: the language this project was installed with, else en)")
    parser.add_argument("--force", action="store_true", help="Take our version of every file, no questions asked")
    parser.add_argument("--keep-mine", dest="keep_mine", action="store_true", help="Keep your version of every file you edited, no questions asked")
    parser.add_argument("--upgrade", action="store_true", help="Run init flow then cleanup obsolete items (uses existing manifest)")
    parser.add_argument("--dry-run", action="store_true", help="Print plan without writing anything")
    parser.add_argument("--all", dest="all_parent", default=None, metavar="PARENT_DIR", help="Batch upgrade: iterate direct subdirs of PARENT_DIR that contain .beads/. Implies --upgrade.")
    args = parser.parse_args()

    if args.all_parent:
        parent = Path(args.all_parent).resolve()
        sys.exit(run_batch_upgrade(
            parent_dir=parent, with_rules=args.with_rules, lang=args.lang,
            force=args.force, dry_run=args.dry_run, keep_mine=args.keep_mine,
        ))

    project_dir = Path(args.project_dir).resolve()
    sys.exit(bootstrap_project(
        project_dir=project_dir, project_name=args.project_name,
        with_rules=args.with_rules, lang=args.lang, force=args.force,
        upgrade=args.upgrade, dry_run=args.dry_run, keep_mine=args.keep_mine,
    ))


if __name__ == "__main__":
    main()
