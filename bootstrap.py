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

# The oldest beads CLI the rules work against: they call bd memories, bd
# remember, bd worktree and bd prime. Keep in sync with BD_MIN_VERSION in
# templates/hooks/hook-utils.cjs — a test asserts the two agree, because two
# copies of a constant in two languages drift silently.
BD_MIN_VERSION = "1.1.0"


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

def content_sha256_bytes(data: bytes) -> str:
    """Return hex SHA-256 digest of raw bytes."""
    h = hashlib.sha256()
    h.update(data)
    return f"sha256:{h.hexdigest()}"


def file_sha256(path: Path) -> str:
    """Return hex SHA-256 digest of a file's contents."""
    return content_sha256_bytes(path.read_bytes())


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
    recorded_hash = manifest.get("files", {}).get(relative_key)
    if recorded_hash is None:
        # Legacy install — treat as user-modified (safe default)
        return False, "no_manifest"
    if file_sha256(file_path) == recorded_hash:
        return True, "unchanged"
    return False, "modified"


def upgrades_path(project_dir: Path, relative_path: str) -> Path:
    """Where a version we are not installing is kept for the user to look at."""
    return project_dir / ".claude" / ".upgrades" / relative_path


def save_upgrade(project_dir: Path, relative_path: str, content: str) -> None:
    """Save new version of a user-modified file to .claude/.upgrades/."""
    write_verbatim(upgrades_path(project_dir, relative_path), content)


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
    dest = upgrades_path(project_dir, rel_key + ".mine")
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
    headline=("{rel} — our instructions are in there unmarked.\n"
              "    Marking them lets every upgrade refresh just that block and "
              "leave the rest of your file alone."),
    keep="leave it alone   (ours goes to .claude/.upgrades/CLAUDE.md)",
    take="mark and update  (yours goes to .claude/.upgrades/CLAUDE.md.mine)",
)

CLAUDE_MD_EDITED = PromptWording(
    headline=("{rel} — what sits between our markers is not what we installed:\n"
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
            old_text = read_verbatim(current)
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


def _dry(dry_run: bool) -> str:
    """Prefix for a line describing a write that a dry run did not make."""
    return "[DRY-RUN] " if dry_run else ""


def _stdin_is_a_person() -> bool:
    """True when a human can answer a prompt."""
    try:
        return sys.stdin.isatty() and sys.stdout.isatty()
    except Exception:
        return False


class Installer:
    """What one run knows, and the one way a file we ship reaches its place.

    Agents, rules and the skill each used to spell the same sequence out in
    full — ask should_update_file, put a conflict to the user, save whatever is
    about to be lost, write, record the hash, print. Four copies of eighteen
    lines, and by the time this replaced them two had already drifted from the
    other two. A fifth kind of file is now four lines, not a fifth copy.
    """

    def __init__(self, project_dir: Path, manifest: dict = None, *,
                 force: bool = False, prompt=None, dry_run: bool = False):
        self.project_dir = project_dir
        self.manifest = manifest if manifest is not None else {}
        if not isinstance(self.manifest.get("files"), dict):
            self.manifest["files"] = {}
        self.force = force
        self.prompt = prompt
        self.dry_run = dry_run
        self.skipped = []
        self.clashes = []

    def path(self, rel_key: str) -> Path:
        """Where a manifest key lives. One rule for both, so a file and the
        hash recorded for it can never end up describing different places."""
        return self.project_dir / ".claude" / rel_key

    def blocked_by(self, dest: Path) -> str | None:
        """What stands in the way of writing dest, or None when nothing does.

        Two shapes, both of them something a person made: a directory named
        like a file we ship, and a plain file named like a directory of ours.
        Hashing the first raises, creating the second raises, and the traceback
        used to take the whole upgrade down with it.
        """
        if dest.exists() and not dest.is_file():
            return "a directory sits where we ship a file"
        for parent in dest.parents:
            if parent == self.project_dir:
                break
            if parent.exists() and not parent.is_dir():
                inside = str(parent.relative_to(self.project_dir)).replace("\\", "/")
                return f"{inside} is a file, and our files go inside it"
        return None

    def clash(self, rel_key: str, label: str, why: str) -> None:
        """Report what we found and move on, leaving it exactly where it is.

        Never overwritten, never deleted, and never a reason to abandon the
        rest of the run: half an upgrade applied because of a traceback is
        worse than one file left uninstalled.
        """
        self.clashes.append((rel_key, why))
        print(f"  - {label} (skipped — {why})")

    def install(self, rel_key: str, text: str, *,
                label: str = None, note: str = "") -> None:
        """Install one file we ship, or keep the one the project already has.

        What was kept instead of installed lands in self.skipped, what could
        not be installed at all in self.clashes, and the run's closing report
        reads both from there.
        """
        dest = self.path(rel_key)
        label = label or rel_key
        blocked = self.blocked_by(dest)
        if blocked:
            self.clash(rel_key, label, blocked)
            return
        ok, reason = should_update_file(dest, rel_key, self.manifest, self.force)
        if not ok:
            ok = self.resolve(rel_key, dest, text)
            reason = "replaced on request" if ok else reason
        if not ok:
            self.keep_yours(rel_key, label, text)
            return
        if not self.take_ours(rel_key, label, dest):
            return
        if not self.dry_run:
            write_verbatim(dest, text)
            self.manifest["files"][rel_key] = file_sha256(dest)
        print(f"  - {_dry(self.dry_run)}{label}{note}"
              + (f" ({reason})" if reason != "new" else ""))

    def resolve(self, rel_key: str, dest: Path, new_text: str,
                wording: PromptWording = None) -> bool:
        """Ask (or apply the standing answer). True → write ours over theirs."""
        prompt = self.prompt or ConflictPrompt(interactive=False)
        return prompt.ask(rel_key, dest, new_text, wording) == ConflictPrompt.TAKE

    def keep_yours(self, rel_key: str, label: str, text: str) -> None:
        """Their file stays; ours goes where they can compare the two.

        Failing to park ours costs nothing that cannot be had again — it ships
        with the package — so the run says so and carries on.
        """
        self.skipped.append(rel_key)
        print(f"  - {label} (yours kept)")
        try:
            if not self.dry_run:
                save_upgrade(self.project_dir, rel_key, text)
        except OSError as e:
            print(f"    We could not put ours beside it: {e.strerror or e}")
            return
        print(f"    {_dry(self.dry_run)}Ours saved to: .claude/.upgrades/{rel_key}")

    def take_ours(self, rel_key: str, label: str, dest: Path) -> bool:
        """Copy theirs aside before ours goes in. False → do not write.

        Theirs cannot be had again. So if the copy cannot be made, the file is
        left exactly as it is: overwriting what we failed to save is the one
        outcome this whole file exists to prevent, and --force does not mean
        "destroy it if the shelf is missing".
        """
        try:
            if self.keep_theirs(rel_key, dest):
                print(f"    Yours saved to: .claude/.upgrades/{rel_key}.mine")
        except OSError as e:
            self.clash(rel_key, label,
                       f"we could not copy yours aside first: {e.strerror or e}")
            return False
        return True

    def keep_theirs(self, rel_key: str, dest: Path) -> bool:
        """Save what we are about to overwrite. True when a copy was made.

        Only what is not already ours: a file still matching the manifest is
        our own last version, and copies of those would bury the ones that
        matter. This is also the only place a --force run can save the user's
        work, because should_update_file answers "forced" without ever looking
        at the file.

        Raises OSError when the copy cannot be parked — see take_ours, which is
        the only caller and the one that decides what that means.
        """
        if self.dry_run or not dest.exists():
            return False
        try:
            raw = dest.read_bytes()
        except OSError:
            return False  # unreadable: overwriting is still what was asked
        if content_sha256_bytes(raw) == self.manifest["files"].get(rel_key):
            return False
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            return False  # not text; there is no version of it we can park
        save_replaced_version(self.project_dir, rel_key, text)
        return True


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

def install_beads(project_dir: Path, dry_run: bool = False,
                  install_bd: bool = False) -> bool:
    """Make sure a usable beads CLI is here, then initialize .beads/."""
    print("\n[1/6] Installing beads...")

    if dry_run:
        _preview_beads(project_dir, install_bd)
        return True

    if shutil.which("bd"):
        print("  - beads CLI already installed")
    elif not _obtain_bd(install_bd):
        return False

    warn_if_bd_outdated()

    if not _init_beads_dir(project_dir):
        return False

    # Stop bd's pre-commit shim from force-staging issues.jsonl (bd >=1.0.2
    # defaults export.git-add=true, which re-stages the JSONL on every commit
    # and can drop a duplicate /issues.jsonl at the repo root). Best-effort:
    # never fail the whole bootstrap on this.
    configure_beads_export(project_dir)

    print("  DONE")
    return True


# Ways to install bd, best first. Only the ones this machine has are offered.
BD_INSTALLERS = [
    ("Homebrew", ["brew", "install", "gastownhall/beads/bd"]),
    ("npm", ["npm", "install", "-g", "@beads/bd"]),
    ("go", ["go", "install", "github.com/gastownhall/beads/cmd/bd@latest"]),
]
BD_DOCS_URL = "https://github.com/gastownhall/beads#-installation"


def _available_bd_installers() -> list:
    """The ways to install bd that this machine actually has."""
    return [(method, cmd) for method, cmd in BD_INSTALLERS if shutil.which(cmd[0])]


def _print_bd_install_help() -> None:
    """Every way we know, for someone who has to do it by hand."""
    print("  Install the beads CLI yourself, then run this again:")
    for method, cmd in BD_INSTALLERS:
        print(f"    {method}: {' '.join(cmd)}")
    print(f"    docs: {BD_DOCS_URL}")


def _ask_to_install_bd(method: str, cmd: list) -> bool:
    """A global program on someone's machine is their decision, not ours.

    Nobody is there during a batch upgrade, in CI, or when an agent drives the
    CLI. Those runs install nothing; --install-beads is how to say yes ahead of
    time.
    """
    print("  - beads CLI (bd) not found, and this project needs it.")
    print(f"    We would install it with {method}: {' '.join(cmd)}")
    if not _stdin_is_a_person():
        print("    Nobody is here to answer, so nothing is installed.")
        print("    Re-run with --install-beads to allow it without asking.")
        return False
    while True:
        try:
            answer = input("    Install it now? [y/N]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\n    (no answer - nothing installed)")
            return False
        if answer in ("", "n", "no"):
            return False
        if answer in ("y", "yes"):
            return True
        print(f"    '{answer}' is not one of y, n")


def _obtain_bd(install_bd: bool) -> bool:
    """Install bd with consent. True only when bd is callable afterwards."""
    candidates = _available_bd_installers()
    if not candidates:
        print("  ERROR: bd is missing and no package manager we know is available.")
        _print_bd_install_help()
        return False

    if not install_bd and not _ask_to_install_bd(*candidates[0]):
        _print_bd_install_help()
        return False

    for method, cmd in candidates:
        result = subprocess.run(cmd, capture_output=True, text=True, shell=_SHELL)
        if result.returncode == 0:
            print(f"  - Installed via {method}")
            break
        print(f"  - {method} could not install it, trying the next way")
    else:
        print("  ERROR: every way we could try failed.")
        _print_bd_install_help()
        return False

    # `go install` writes to a directory that is often outside PATH, and a PATH
    # a package manager just extended is not the PATH of this process. Printing
    # success here used to hand the next step a bd that is not there.
    if not shutil.which("bd"):
        print("  ERROR: bd was installed, but this shell still cannot find it.")
        print("    The install directory is not on PATH. Open a new terminal")
        print("    (or add that directory to PATH) and run this again.")
        return False
    return True


def parse_bd_version(text: str) -> str | None:
    """First dotted version in `bd version` output: 'bd version 1.1.0 (...)'."""
    if not text:
        return None
    match = re.search(r"\d+\.\d+\.\d+", text)
    return match.group(0) if match else None


def version_below(current: str | None, minimum: str) -> bool:
    """True when current is older than minimum.

    Anything unreadable is False: a version we cannot parse is not evidence of
    an old one, and a false alarm every session start is worse than silence.
    """
    try:
        return (tuple(int(p) for p in current.split("."))
                < tuple(int(p) for p in minimum.split(".")))
    except (AttributeError, ValueError):
        return False


def read_bd_version() -> str | None:
    """The installed bd's version, or None when bd cannot answer."""
    try:
        result = subprocess.run(
            ["bd", "version"], capture_output=True, text=True,
            shell=_SHELL, stdin=subprocess.DEVNULL, timeout=15,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    if result.returncode != 0:
        return None
    return parse_bd_version(result.stdout or result.stderr or "")


def warn_if_bd_outdated() -> bool:
    """Warn about a bd older than the rules rely on. Never blocks.

    An old bd still runs most of the workflow; it just fails one command at a
    time with "unknown command" and no explanation. This line is the
    explanation.
    """
    found = read_bd_version()
    if found is None:
        print("  - could not read the bd version, skipping the version check")
        return True
    if version_below(found, BD_MIN_VERSION):
        print(f"  - WARNING: bd {found} is older than {BD_MIN_VERSION}, which the"
              " rules rely on (bd memories, bd remember, bd worktree, bd prime)")
        print("    Update it: npm install -g @beads/bd@latest")
        return False
    return True


def _init_beads_dir(project_dir: Path) -> bool:
    """Run `bd init` when there is no .beads/ yet. True when .beads/ is usable."""
    if (project_dir / ".beads").exists():
        return True

    print("  - Initializing .beads directory...")
    try:
        result = subprocess.run(
            ["bd", "init"], cwd=project_dir,
            capture_output=True, text=True, shell=_SHELL,
            stdin=subprocess.DEVNULL, timeout=15,
        )
    except subprocess.TimeoutExpired:
        result = None

    if result is not None and result.returncode == 0:
        if (project_dir / ".beads").exists():
            return True
        # A zero exit code is not the same as a .beads/ in this directory —
        # `bd init` run inside an existing beads repository reports success and
        # initializes nothing here. Everything downstream expects it here.
        print("  ERROR: 'bd init' reported success but left no .beads/ here.")
        print(f"    Expected: {project_dir / '.beads'}")
        print("    Run 'bd init' in this directory yourself, then run this again.")
        return False

    # An empty .beads/ used to be created here so the run could report success.
    # It cannot: every bd command the rules use fails against it, and the
    # session-start hook only checks that the directory exists — so the project
    # looked installed until the first command failed.
    if result is None:
        reason = "timed out after 15s (Dolt server not running?)"
    else:
        detail = (result.stderr or result.stdout or "").strip().splitlines()
        reason = detail[0] if detail else f"exit code {result.returncode}"
    print(f"  ERROR: 'bd init' failed: {reason}")
    print("    Run 'bd init' in this project yourself, then run this again.")
    return False


def _preview_beads(project_dir: Path, install_bd: bool) -> None:
    """What --dry-run says about this step.

    A preview writes nothing and shells out to nothing — not even to read a
    version, which is why this says what would be checked instead of checking.
    """
    if shutil.which("bd"):
        print("  - beads CLI already installed")
        print(f"  - [DRY-RUN] would check bd is at least {BD_MIN_VERSION}")
    elif install_bd:
        print("  - [DRY-RUN] would install the beads CLI without asking (--install-beads)")
    else:
        print("  - [DRY-RUN] would ask before installing the beads CLI")
    if not (project_dir / ".beads").exists():
        print("  - [DRY-RUN] would run 'bd init' in this project")
    print("  - [DRY-RUN] would run 'bd config set export.git-add false'")
    print("  DONE")


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


def copy_agents(project_name: str, installer: Installer) -> None:
    """Copy code-reviewer and merge-supervisor templates."""
    print("\n[2/6] Copying agents...")
    for src in sorted((TEMPLATES_DIR / "agents").glob("*.md")):
        text = read_verbatim(src).replace("[Project]", project_name)
        installer.install(f"agents/{src.name}", text, label=src.name)
    print("  DONE")


def copy_hooks(installer: Installer) -> None:
    """Copy Node.js hooks (always overwrite — enforcement code).

    The one kind of file that is never a question: hooks are enforcement code,
    not text anyone is meant to tune, so this stays outside Installer.install.
    What it does share is the check for something else standing in the way —
    a file named .claude/hooks, or a directory named like a hook.
    """
    print("\n[3/6] Copying hooks...")
    for src in sorted((TEMPLATES_DIR / "hooks").glob("*.cjs")):
        rel_key = f"hooks/{src.name}"
        dest = installer.path(rel_key)
        blocked = installer.blocked_by(dest)
        if blocked:
            installer.clash(rel_key, src.name, blocked)
            continue
        if not installer.dry_run:
            write_verbatim(dest, read_verbatim(src))
            installer.manifest["files"][rel_key] = file_sha256(dest)
        print(f"  - {_dry(installer.dry_run)}{src.name}")
    print("  DONE")


def copy_rules_and_skills(with_rules: bool, lang: str,
                          installer: Installer,
                          with_skill: bool = True) -> None:
    """Copy beads-workflow rule, project-discovery skill, and optional dev rules."""
    print("\n[4/6] Copying rules and skills...")

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
        installer.install("rules/beads-workflow.md", read_verbatim(beads_src))

    # Optional dev rules (from language-specific directory)
    if with_rules:
        note = f" ({lang})" if lang != "en" else ""
        for src in sorted(rules_src_dir.glob("*.md")):
            if src.name != "beads-workflow.md":
                installer.install(f"rules/{src.name}", read_verbatim(src),
                                  note=note)

    if with_skill:
        copy_skill(installer)
    print("  DONE")


def copy_skill(installer: Installer) -> None:
    """Copy the project-discovery skill, one file at a time.

    It used to be rmtree + copytree, on the grounds that the directory is our
    code. It is not: SKILL.md is a prompt people tune the way they tune a rule,
    and anything they kept beside it was deleted with no copy — on a plain run,
    no flag, no question. So each file we ship goes through the same question a
    rule does, and a file we do not ship is left where its owner put it.
    """
    skill_src = TEMPLATES_DIR / "skills" / "project-discovery"
    if not skill_src.exists():
        return
    for src in sorted(p for p in skill_src.rglob("*") if p.is_file()):
        rel = str(src.relative_to(skill_src)).replace("\\", "/")
        installer.install(f"skills/project-discovery/{rel}", read_verbatim(src))


# ============================================================================
# Handing the executable half over to the plugin
# ============================================================================
# Installed as a plugin, Claude Code loads the hooks, agents and skill itself.
# A copy of them left in the project does not sit quietly beside the plugin:
# hooks merge from every source, so each one fires twice.


def plugin_provided_relpaths() -> list:
    """What the plugin supplies, as paths from the project root.

    Project-root paths, not manifest keys — that is what _cleanup_file needs to
    find the file, and it translates to the manifest key itself. Derived rather
    than listed, so a new hook or agent cannot be provided by the plugin and
    left behind in projects at the same time.
    """
    rels = [f".claude/hooks/{p.name}"
            for p in sorted((TEMPLATES_DIR / "hooks").glob("*.cjs"))]
    rels += [f".claude/agents/{p.name}"
             for p in sorted((TEMPLATES_DIR / "agents").glob("*.md"))]
    skill_src = TEMPLATES_DIR / "skills" / "project-discovery"
    if skill_src.exists():
        rels += [
            ".claude/skills/project-discovery/"
            + str(p.relative_to(skill_src)).replace("\\", "/")
            for p in sorted(skill_src.rglob("*")) if p.is_file()
        ]
    return rels


def _claude_config_dir() -> Path:
    """Where Claude Code keeps its own settings and plugin records."""
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or (Path.home() / ".claude"))


def _same_dir(a, b) -> bool:
    """The same directory, however either side happened to spell it.

    resolve() follows symlinks and expands Windows short names, so /tmp and
    /private/tmp are one directory. A relative path matches nothing at all:
    resolving it would use whatever directory this process was started in,
    which is not what the registry meant to record.
    """
    resolved = []
    for value in (a, b):
        if not value:
            return False
        candidate = Path(str(value).rstrip("\\/"))
        if not candidate.is_absolute():
            return False
        try:
            resolved.append(candidate.resolve())
        except (OSError, ValueError):
            return False
    if os.name == "nt":
        return str(resolved[0]).lower() == str(resolved[1]).lower()
    return resolved[0] == resolved[1]


def _plugin_switched_off(project_dir: Path) -> bool:
    """True when settings anywhere switch our plugin off.

    Installed is not enabled. Skipping the hooks for a plugin that never runs
    would leave the project with nothing, so an explicit false outranks the
    registry — while a missing entry stays missing, because a project-scope
    install writes no enabledPlugins entry at all.
    """
    for settings in (_claude_config_dir() / "settings.json",
                     project_dir / ".claude" / "settings.json",
                     project_dir / ".claude" / "settings.local.json"):
        try:
            enabled = json.loads(settings.read_text(encoding="utf-8")).get("enabledPlugins")
        except Exception:
            continue  # Absent or unreadable settings say nothing either way.
        if not isinstance(enabled, dict):
            continue
        for name, on in enabled.items():
            if name.split("@")[0] == "claude-protocol" and on is False:
                return True
    return False


def plugin_active_for(project_dir: Path) -> bool:
    """True when the plugin is the one supplying hooks in this project.

    Read from Claude Code's own record, plugins/installed_plugins.json: an
    entry at user scope covers every project, one at project scope only the
    path it names.

    Every failure answers false and installs everything, deliberately. A
    registry we half-understand is not grounds to strip someone's hooks, and
    the cost of the opposite mistake is one hook they did not need.
    """
    if not _registry_says_active(project_dir):
        return False
    return not _plugin_switched_off(project_dir)


def _registry_says_active(project_dir: Path) -> bool:
    """Installed, and covering this project. Asked before the settings files
    because that is the cheap question: on a machine with no such plugin it is
    one missing file instead of four."""
    try:
        registry = json.loads(
            (_claude_config_dir() / "plugins" / "installed_plugins.json")
            .read_text(encoding="utf-8"))
    except Exception:
        return False
    plugins = registry.get("plugins") if isinstance(registry, dict) else None
    if not isinstance(plugins, dict):
        return False
    for name, entries in plugins.items():
        if name.split("@")[0] != "claude-protocol" or not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            if entry.get("scope") == "user":
                return True
            if (entry.get("scope") == "project"
                    and _same_dir(entry.get("projectPath"), project_dir)):
                return True
    return False


def hand_over_to_plugin(project_dir: Path, manifest: dict,
                        dry_run: bool = False) -> dict:
    """Remove the copies the plugin now provides, and unwire our hooks.

    Only files this project's manifest says we installed are touched, and each
    one is copied into .claude/.upgrades/<timestamp>/obsolete/ first. A file
    someone else put there is not ours to remove.
    """
    report = {"removed": [], "unwired": []}
    upgrades_root = project_dir / ".claude" / ".upgrades" / _upgrade_timestamp()
    state = {"created": False}

    def backup_fn() -> Path:
        target = upgrades_root / "obsolete"
        if not state["created"] and not dry_run:
            target.mkdir(parents=True, exist_ok=True)
            state["created"] = True
        return target

    for rel in plugin_provided_relpaths():
        if _cleanup_file(rel, project_dir, manifest, backup_fn, dry_run):
            report["removed"].append(rel)

    hook_names = [Path(rel).name for rel in plugin_provided_relpaths()
                  if rel.startswith(".claude/hooks/")]
    for name in ("settings.json", "settings.local.json"):
        settings_path = project_dir / ".claude" / name
        if settings_path.exists():
            report["unwired"] += _strip_obsolete_hooks(
                settings_path, hook_names, backup_fn, dry_run,
            )
    return report


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

# What update_claude_md decided to do. `wording` None means replacing destroys
# nothing a person wrote, and only then does it go ahead without asking.
ClaudeMdPlan = namedtuple("ClaudeMdPlan", "text note wording")


def _lf(text: str) -> str:
    """Line endings normalised, so a CRLF checkout hashes like an LF one."""
    return text.replace("\r\n", "\n")


def _in_style_of(text: str, addition: str) -> str:
    """`addition` written in the line endings `text` already uses."""
    addition = _lf(addition)
    return addition.replace("\n", "\r\n") if "\r\n" in text else addition


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
    return text[:span[0]] + _in_style_of(text, region) + text[span[1]:]


def _claude_md_plan(current: str, region: str, manifest: dict):
    """What to write over an existing CLAUDE.md, or None when we cannot tell.

    `wording` is None when replacing destroys nothing a person wrote, and that
    is the only case that goes ahead without asking: either the file carries no
    block of ours yet, or the marked region hashes to what we last installed.

    A recorded hash is the only proof of that. Without one the markers could be
    anything — a lost or unreadable manifest, a pair typed by hand, a file whose
    own prose quotes both marker strings — and replacing what sits between them
    would delete text nobody agreed to lose. So: no hash, no silent replacement.
    """
    span = marked_span(current)
    if span:
        recorded = (manifest.get("regions") or {}).get("CLAUDE.md")
        ours = bool(recorded) and content_sha256(
            _lf(current[span[0]:span[1]])) == recorded
        return ClaudeMdPlan(splice(current, span, region), "our block refreshed",
                            None if ours else CLAUDE_MD_EDITED)
    span = unmarked_span(current)
    if span:
        return ClaudeMdPlan(splice(current, span, region),
                            "our block marked and refreshed", CLAUDE_MD_UNMARKED)
    if "## Workflow" in current and "beads" in current.lower():
        return None  # orchestration text we cannot delimit
    addition = _in_style_of(
        current, "\n\n---\n\n# Beads Orchestration\n\n" + region + "\n")
    return ClaudeMdPlan(current.rstrip("\r\n") + addition, "our block appended", None)


def _write_claude_md(installer: Installer, text: str, region: str) -> None:
    """Write the file and remember the block, so the next upgrade knows it is ours."""
    if installer.dry_run:
        return
    write_verbatim(installer.project_dir / "CLAUDE.md", text)
    if region is not None:
        installer.manifest.setdefault("regions", {})["CLAUDE.md"] = \
            content_sha256(_lf(region))


def _hand_over_template(installer: Installer, template_text: str,
                        why: str) -> None:
    """Cannot tell where our part ends: leave the file, drop the template beside it."""
    if not installer.dry_run:
        save_upgrade(installer.project_dir, "CLAUDE.md", template_text)
    print(f"  - CLAUDE.md (kept — {why})")
    print(f"    {_dry(installer.dry_run)}Current template saved to: "
          ".claude/.upgrades/CLAUDE.md")


def update_claude_md(template_text: str, installer: Installer) -> None:
    """Refresh our block in CLAUDE.md without touching a line the user wrote.

    The one file that does not go through Installer.install: it lives outside
    .claude/, only a marked block inside it is ours, and the question it puts
    to the user is worded for that. What it does share is the promise — the
    version that loses is kept — so it uses the same two halves of it.
    """
    dest = installer.project_dir / "CLAUDE.md"
    span = marked_span(template_text)
    region = template_text[span[0]:span[1]] if span else None

    if not dest.exists():
        _write_claude_md(installer, template_text, region)
        print(f"  - {_dry(installer.dry_run)}CLAUDE.md (created)")
        return
    if not dest.is_file():  # a directory of that name — reading it raises
        installer.clash("CLAUDE.md", "CLAUDE.md",
                        "a directory sits where the file goes")
        return
    if region is None:  # the template lost its markers — never guess
        _hand_over_template(installer, template_text, "template has no markers")
        return

    current = read_verbatim(dest)
    plan = _claude_md_plan(current, region, installer.manifest)
    if plan is None:
        _hand_over_template(installer, template_text,
                            "our block is not marked and not recognisable")
        return
    if plan.wording:
        if not installer.resolve("CLAUDE.md", dest, plan.text, plan.wording):
            installer.keep_yours("CLAUDE.md", "CLAUDE.md", plan.text)
            return
        if not installer.take_ours("CLAUDE.md", "CLAUDE.md", dest):
            return
    _write_claude_md(installer, plan.text, region)
    print(f"  - {_dry(installer.dry_run)}CLAUDE.md ({plan.note})")


def _install_settings(installer: Installer) -> None:
    """Merge our hook entries into .claude/settings.json, or replace it.

    The merge is the only write we make into a file the user owns, so the
    previous version is kept either way — including when the file does not
    parse, which usually means someone was editing it rather than that it is
    worthless.
    """
    project_dir, dry_run = installer.project_dir, installer.dry_run
    dest = project_dir / ".claude" / "settings.json"
    src = TEMPLATES_DIR / "settings.json"
    if not src.exists():
        return
    blocked = installer.blocked_by(dest)
    if blocked:
        # shutil.copy2 onto a directory would quietly file ours inside theirs.
        installer.clash("settings.json", "settings.json", blocked)
        return
    if not dest.exists():
        if not dry_run:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
        print(f"  - {_dry(dry_run)}settings.json")
        return
    try:
        before = read_verbatim(dest)
        existing = json.loads(before)
        migrated = merge_hooks(existing, json.loads(read_verbatim(src)).get("hooks", {}))
    except Exception:
        _replace_unparseable_settings(project_dir, dest, src, dry_run)
        return
    if not dry_run:
        try:
            save_upgrade(project_dir, "settings.json.before-merge", before)
        except OSError as e:
            print(f"    We could not keep a copy first: {e.strerror or e}")
        write_verbatim(dest, json.dumps(existing, indent=2) + "\n")
    print(f"  - {_dry(dry_run)}settings.json (merged hooks)")
    for old_cmd, _ in migrated:
        print(f"    rewrote hook path: {old_cmd[:70]}")


def _replace_unparseable_settings(project_dir: Path, dest: Path, src: Path,
                                  dry_run: bool) -> None:
    """Copy the bytes out, then install ours. A byte copy survives any encoding."""
    kept = True
    if not dry_run:
        try:
            backup = upgrades_path(project_dir, "settings.json.before-merge")
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(dest, backup)
        except Exception:
            kept = False
        shutil.copy2(src, dest)
    print(f"  - {_dry(dry_run)}settings.json (replaced — could not merge)")
    if kept:
        print(f"    {_dry(dry_run)}Yours saved to: "
              ".claude/.upgrades/settings.json.before-merge")
    else:
        print("    WARNING: could not keep a copy of your settings.json")


def copy_settings_and_claude_md(project_name: str,
                                installer: Installer,
                                with_settings: bool = True,
                                lang: str = "en") -> None:
    """Copy settings.json (merge hooks) and refresh our block in CLAUDE.md.

    `with_settings` is off when the plugin supplies the hooks: writing our
    entries into the project would then run every hook twice.
    """
    print("\n[5/6] Copying settings and CLAUDE.md...")

    if with_settings:
        _install_settings(installer)

        # --- settings.local.json: same stale-path rewrite, never templated ---
        migrated = ([] if installer.dry_run
                    else migrate_local_settings_hooks(installer.project_dir))
        for old_cmd, _ in migrated:
            print(f"  - settings.local.json: rewrote hook path: {old_cmd[:70]}")

    # --- CLAUDE.md: refresh our marked block, leave the rest of the file alone ---
    # The rules ship in the chosen language and CLAUDE.md did not, so a project
    # installed with --lang ru got Russian rules and English orchestrator
    # instructions. Fall back to English when a translation is missing, the way
    # the beads-workflow rule does.
    claude_src = TEMPLATES_DIR / ("CLAUDE-ru.md" if lang == "ru" else "CLAUDE.md")
    if not claude_src.exists():
        claude_src = TEMPLATES_DIR / "CLAUDE.md"
    if claude_src.exists():
        template_text = read_verbatim(claude_src).replace("[Project]", project_name)
        update_claude_md(template_text, installer)

    print("  DONE")


def _gitignore_key(line: str) -> str:
    """One .gitignore line reduced to what two spellings of it have in common.

    git reads `/.worktrees/`, `.worktrees/` and `.worktrees` as covering the
    same path at the repository root — and an unanchored entry covers the root
    as well — so all three mean the path is already ignored. Comparing the
    written form instead appended a second copy of every entry a project had
    anchored with a leading slash.

    A comment keeps its `#`, so `# .worktrees/ on purpose` never reads as the
    entry itself; that would leave the path unignored on the strength of a
    sentence about it.
    """
    return line.strip().lstrip("/").rstrip("/")


def setup_gitignore(installer: Installer) -> None:
    """Ensure .worktrees/, .claude/.upgrades/, and /issues.jsonl are in .gitignore.

    NOTE: the beads tracker travels with the repo, so .beads/ is intentionally
    NOT ignored — the canonical .beads/issues.jsonl must stay under git. Dolt
    runtime/binary files are excluded by .beads/.gitignore (written by bd init).
    /issues.jsonl guards against an export that lands at the repo root.
    """
    print("\n[6/6] Setting up .gitignore...")
    project_dir, dry_run = installer.project_dir, installer.dry_run
    gitignore_path = project_dir / ".gitignore"
    entries = [".worktrees/", ".claude/.upgrades/", "/issues.jsonl"]

    blocked = installer.blocked_by(gitignore_path)
    if blocked:
        installer.clash(".gitignore", ".gitignore", blocked)
        print("  DONE")
        return

    if gitignore_path.exists():
        content = gitignore_path.read_text(encoding='utf-8')
        lines = content.splitlines()
        present = {_gitignore_key(line) for line in lines}
        missing = [e for e in entries if _gitignore_key(e) not in present]
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


def _report_handover(report: dict, dry_run: bool) -> None:
    """Say what the plugin took over, file by file. Silence would leave someone
    wondering where their hooks went."""
    if not (report["removed"] or report["unwired"]):
        return
    print(f"\n{_dry(dry_run)}Handed over to the plugin:")
    for rel in report["removed"]:
        print(f"  - removed {rel}")
    for command in report["unwired"]:
        print(f"  - unwired hook: {str(command)[:70]}")
    print("  (copies of everything removed are in .claude/.upgrades/)")


def bootstrap_project(
    project_dir: Path, project_name: str | None, with_rules: bool,
    lang: str, force: bool, upgrade: bool, dry_run: bool,
    keep_mine: bool = False, install_bd: bool = False,
    project_only: bool = False,
) -> int:
    """Run bootstrap for a single project. Returns exit code (0 = success)."""
    if not dry_run:
        project_dir.mkdir(parents=True, exist_ok=True)
    resolved_name = project_name or infer_project_name(project_dir)

    # An upgrade must not silently switch a project's language back to English:
    # --lang is optional, and the manifest remembers what was installed.
    manifest = load_manifest(project_dir)
    lang = lang or manifest.get("lang") or "en"

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

    # Everything we install lives inside .claude/. A file of that name is not a
    # clash we can report per file and work around — it is every file at once,
    # and the manifest we would write at the end has nowhere to go either.
    claude_dir = project_dir / ".claude"
    if claude_dir.exists() and not claude_dir.is_dir():
        print(f"\nERROR: {claude_dir} is a file, not a directory.")
        print("Everything we install lives inside it. Move it aside and run again.")
        return 1

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

    installer = Installer(project_dir, manifest, force=force, prompt=prompt,
                          dry_run=dry_run)

    if not install_beads(project_dir, dry_run, install_bd):
        return 1

    # Both routes wire the same hooks, and Claude Code merges hooks from every
    # source — installing ours on top of an active plugin makes each one fire
    # twice. The plugin is already newer than whatever we would write, so it
    # wins, and this run installs only what a plugin cannot carry.
    if not project_only and plugin_active_for(project_dir):
        project_only = True
        print("\nClaude Protocol is installed here as a plugin, and it carries the")
        print("hooks, agents and skill. Installing only what it cannot: beads,")
        print("rules and CLAUDE.md.")

    # Installed as a plugin, Claude Code loads the hooks, agents and skill
    # itself; a copy of them in the project makes every hook fire twice.
    if not project_only:
        copy_agents(resolved_name, installer)
        copy_hooks(installer)
    copy_rules_and_skills(with_rules, lang, installer, with_skill=not project_only)
    copy_settings_and_claude_md(resolved_name, installer,
                                with_settings=not project_only, lang=lang)
    setup_gitignore(installer)

    if project_only:
        _report_handover(hand_over_to_plugin(project_dir, manifest, dry_run),
                         dry_run)

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
        try:
            save_manifest(project_dir, manifest)
        except OSError as e:
            # The last write of the run, and the one that cannot be shrugged
            # off: it is the record of which files are ours.
            print(f"\nERROR: could not write .claude/.manifest.json: "
                  f"{e.strerror or e}")
            print("Everything else is installed. Without that record the next "
                  "run treats every file as yours and asks before touching it.")
            return 1

    print("\n" + "=" * 60)
    print("BOOTSTRAP COMPLETE")
    print("=" * 60)

    if installer.skipped:
        print(f"\n  {len(installer.skipped)} file(s) kept as yours:")
        for rel in installer.skipped:
            print(f"    - {rel}")
            print(f"      {_dry(dry_run)}Ours is next to it: .claude/.upgrades/{rel}")
        print("    Re-run with --force to take ours for all of them.")

    if installer.clashes:
        print(f"\n  {len(installer.clashes)} file(s) we could not install:")
        for rel, why in installer.clashes:
            print(f"    - {rel} — {why}")
        print("    Nothing there was touched. Move it aside and run again.")

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
) -> int:
    """Iterate direct subdirs of parent_dir that contain .beads/ and upgrade each."""
    if not parent_dir.exists() or not parent_dir.is_dir():
        print(f"ERROR: --all parent directory not found: {parent_dir}")
        return 1

    # Nobody upgrading twenty projects reads twenty diffs. A batch upgrade
    # keeps every file the user edited and saves ours beside it — which is what
    # the README has always promised. Only --force overrides that.
    print(f"\n[BATCH UPGRADE] Scanning {parent_dir}")
    print("  Taking our version of every file; yours go to .claude/.upgrades/"
          if force else
          "  Files you edited are kept; ours go to .claude/.upgrades/"
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
                keep_mine=not force,
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
    parser.add_argument("--lang", default=None, choices=["en", "ru"], help="Language for the dev rules and CLAUDE.md (default: the language this project was installed with, else en)")
    parser.add_argument("--force", action="store_true", help="Take our version of every file, no questions asked")
    parser.add_argument("--keep-mine", dest="keep_mine", action="store_true", help="Keep your version of every file you edited, no questions asked")
    parser.add_argument("--upgrade", action="store_true", help="Run init flow then cleanup obsolete items (uses existing manifest)")
    parser.add_argument("--dry-run", action="store_true", help="Print plan without writing anything")
    parser.add_argument("--install-beads", dest="install_bd", action="store_true", help="Install the beads CLI without asking (default: ask, and install nothing when nobody can answer)")
    parser.add_argument("--project-only", dest="project_only", action="store_true", help="Install only what a plugin cannot carry: beads, rules, CLAUDE.md. Hooks, agents and the skill come from the plugin, and copies of them already in the project are removed")
    parser.add_argument("--all", dest="all_parent", default=None, metavar="PARENT_DIR", help="Batch upgrade: iterate direct subdirs of PARENT_DIR that contain .beads/. Implies --upgrade.")
    args = parser.parse_args()

    if args.all_parent:
        parent = Path(args.all_parent).resolve()
        sys.exit(run_batch_upgrade(
            parent_dir=parent, with_rules=args.with_rules, lang=args.lang,
            force=args.force, dry_run=args.dry_run,
        ))

    project_dir = Path(args.project_dir).resolve()
    sys.exit(bootstrap_project(
        project_dir=project_dir, project_name=args.project_name,
        with_rules=args.with_rules, lang=args.lang, force=args.force,
        upgrade=args.upgrade, dry_run=args.dry_run, keep_mine=args.keep_mine,
        install_bd=args.install_bd, project_only=args.project_only,
    ))


if __name__ == "__main__":
    main()
