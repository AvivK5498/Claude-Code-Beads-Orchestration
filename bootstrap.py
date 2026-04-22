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
import sys
import json
import hashlib
import shutil
import subprocess
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
]

# Substrings matched against hook command strings in
# .claude/settings.local.json. Same semantics as OBSOLETE_SETTINGS_HOOKS.
# `bd prime` used to be a SessionStart hook there; the templated global
# settings.json now owns session bootstrapping, so legacy local entries go.
OBSOLETE_LOCAL_SETTINGS_PATTERNS: list[str] = [
    "bd prime",
]


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
            return json.loads(manifest_path.read_text(encoding="utf-8"))
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
    recorded_hash = manifest.get("files", {}).get(relative_key)
    if recorded_hash is None:
        # Legacy install — treat as user-modified (safe default)
        return False, "no_manifest"
    if current_hash == recorded_hash:
        return True, "unchanged"
    return False, "modified"


def save_upgrade(project_dir: Path, relative_path: str, content: str) -> None:
    """Save new version of a user-modified file to .claude/.upgrades/."""
    dest = project_dir / ".claude" / ".upgrades" / relative_path
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(content, encoding="utf-8")


# ============================================================================
# UPGRADE CLEANUP
# ============================================================================

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
    settings_path: Path, patterns: list, backup_dir: Path, dry_run: bool
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


def _auto_inject_legacy_files(project_dir: Path, manifest: dict,
                              dry_run: bool) -> list:
    """Register OBSOLETE_FILES that exist on disk but pre-date the manifest."""
    injected: list = []
    existing = manifest.get("files", {})
    for rel in OBSOLETE_FILES:
        target = project_dir / rel
        if rel in existing:
            continue
        if not target.exists() or not _is_within(target, project_dir):
            continue
        if not dry_run:
            manifest.setdefault("files", {})[rel] = "sha256:legacy-auto-injected"
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
    if rel not in manifest.get("files", {}):
        return False
    target = project_dir / rel
    if not _is_within(target, project_dir):
        print(f"[UPGRADE] Skipping suspicious path: {rel} (escapes project_dir)")
        return False
    if not target.exists():
        manifest["files"].pop(rel, None)
        return False
    if dry_run:
        return True
    backup_path = backup_fn() / rel
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(target, backup_path)
    target.unlink()
    manifest["files"].pop(rel, None)
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
        settings_path, patterns, backup_fn(), dry_run
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
        manifest.setdefault("files", {})[rel] = "sha256:legacy-auto-injected"

    for rel in OBSOLETE_FILES:
        if _cleanup_file(rel, project_dir, manifest, backup_fn, dry_run):
            report["removed_files"].append(rel)

    # Roll back the dry-run temporary injection so the caller's manifest is pristine.
    for rel in dry_run_injected:
        manifest.get("files", {}).pop(rel, None)

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

def install_beads(project_dir: Path) -> bool:
    """Install beads CLI and initialize .beads directory."""
    print("\n[1/6] Installing beads...")

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

    print("  DONE")
    return True


def copy_agents(
    project_dir: Path, project_name: str,
    manifest: dict, force: bool = False,
) -> list:
    """Copy code-reviewer and merge-supervisor templates."""
    print("\n[2/6] Copying agents...")
    agents_dir = project_dir / ".claude" / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    skipped = []

    replacements = {"[Project]": project_name}
    for agent_file in (TEMPLATES_DIR / "agents").glob("*.md"):
        dest = agents_dir / agent_file.name
        rel_key = f"agents/{agent_file.name}"
        ok, reason = should_update_file(dest, rel_key, manifest, force)
        if ok:
            copy_and_replace(agent_file, dest, replacements)
            manifest["files"][rel_key] = file_sha256(dest)
            print(f"  - {agent_file.name}" + (f" ({reason})" if reason != "new" else ""))
        else:
            # Save new version to .upgrades/
            new_content = agent_file.read_text(encoding="utf-8")
            for placeholder, value in replacements.items():
                new_content = new_content.replace(placeholder, value)
            save_upgrade(project_dir, rel_key, new_content)
            skipped.append(rel_key)
            print(f"  - {agent_file.name} (MODIFIED by user — skipped)")
            print(f"    New version saved to: .claude/.upgrades/{rel_key}")
    print("  DONE")
    return skipped


def copy_hooks(project_dir: Path, manifest: dict) -> None:
    """Copy Node.js hooks (always overwrite — enforcement code)."""
    print("\n[3/6] Copying hooks...")
    hooks_dir = project_dir / ".claude" / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)

    for hook_file in (TEMPLATES_DIR / "hooks").glob("*.cjs"):
        dest = hooks_dir / hook_file.name
        shutil.copy2(hook_file, dest)
        rel_key = f"hooks/{hook_file.name}"
        manifest["files"][rel_key] = file_sha256(dest)
        print(f"  - {hook_file.name}")
    print("  DONE")


def copy_rules_and_skills(
    project_dir: Path, with_rules: bool, lang: str = "en",
    manifest: dict = None, force: bool = False,
) -> list:
    """Copy beads-workflow rule, project-discovery skill, and optional dev rules."""
    print("\n[4/6] Copying rules and skills...")
    rules_dir = project_dir / ".claude" / "rules"
    rules_dir.mkdir(parents=True, exist_ok=True)
    skipped = []

    # Determine source directory based on language
    rules_src_dir = TEMPLATES_DIR / ("rules-ru" if lang == "ru" else "rules")

    # Always copy beads workflow (always English — it's the canonical format)
    beads_src = TEMPLATES_DIR / "rules" / "beads-workflow.md"
    if beads_src.exists():
        dest = rules_dir / "beads-workflow.md"
        rel_key = "rules/beads-workflow.md"
        ok, reason = should_update_file(dest, rel_key, manifest, force)
        if ok:
            shutil.copy2(beads_src, dest)
            manifest["files"][rel_key] = file_sha256(dest)
            print(f"  - rules/beads-workflow.md" + (f" ({reason})" if reason != "new" else ""))
        else:
            save_upgrade(project_dir, rel_key, beads_src.read_text(encoding="utf-8"))
            skipped.append(rel_key)
            print(f"  - rules/beads-workflow.md (MODIFIED by user — skipped)")
            print(f"    New version saved to: .claude/.upgrades/{rel_key}")

    # Optional dev rules (from language-specific directory)
    if with_rules:
        for rule_file in rules_src_dir.glob("*.md"):
            if rule_file.name != "beads-workflow.md":
                dest = rules_dir / rule_file.name
                rel_key = f"rules/{rule_file.name}"
                ok, reason = should_update_file(dest, rel_key, manifest, force)
                if ok:
                    shutil.copy2(rule_file, dest)
                    manifest["files"][rel_key] = file_sha256(dest)
                    suffix = f" ({lang})" if lang != "en" else ""
                    suffix += f" ({reason})" if reason != "new" else ""
                    print(f"  - rules/{rule_file.name}{suffix}")
                else:
                    save_upgrade(project_dir, rel_key, rule_file.read_text(encoding="utf-8"))
                    skipped.append(rel_key)
                    print(f"  - rules/{rule_file.name} (MODIFIED by user — skipped)")
                    print(f"    New version saved to: .claude/.upgrades/{rel_key}")

    # Project discovery skill (always overwrite — our code)
    skills_dir = project_dir / ".claude" / "skills"
    skill_src = TEMPLATES_DIR / "skills" / "project-discovery"
    if skill_src.exists():
        dest = skills_dir / "project-discovery"
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(skill_src, dest)
        # Record skill files in manifest
        for skill_file in dest.rglob("*"):
            if skill_file.is_file():
                rel_key = str(skill_file.relative_to(project_dir / ".claude")).replace("\\", "/")
                manifest["files"][rel_key] = file_sha256(skill_file)
        print("  - skills/project-discovery/")

    print("  DONE")
    return skipped


def copy_settings_and_claude_md(project_dir: Path, project_name: str) -> None:
    """Copy settings.json (merge hooks) and CLAUDE.md (append if exists)."""
    print("\n[5/6] Copying settings and CLAUDE.md...")

    # --- settings.json: merge hooks into existing ---
    settings_dest = project_dir / ".claude" / "settings.json"
    settings_src = TEMPLATES_DIR / "settings.json"
    if settings_src.exists():
        new_settings = json.loads(settings_src.read_text(encoding='utf-8'))
        if settings_dest.exists():
            try:
                existing = json.loads(settings_dest.read_text(encoding='utf-8'))
                # Merge hooks by event type
                for event, hooks_list in new_settings.get("hooks", {}).items():
                    existing.setdefault("hooks", {}).setdefault(event, [])
                    existing_commands = {
                        h["hooks"][0]["command"]
                        for h in existing["hooks"][event]
                        if h.get("hooks") and h["hooks"][0].get("command")
                    }
                    for hook in hooks_list:
                        cmd = hook.get("hooks", [{}])[0].get("command", "")
                        if cmd not in existing_commands:
                            existing["hooks"][event].append(hook)
                settings_dest.write_text(json.dumps(existing, indent=2) + "\n", encoding='utf-8')
                print("  - settings.json (merged hooks)")
            except Exception:
                shutil.copy2(settings_src, settings_dest)
                print("  - settings.json (replaced — could not merge)")
        else:
            settings_dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(settings_src, settings_dest)
            print("  - settings.json")

    # --- CLAUDE.md: append beads section if file exists ---
    claude_dest = project_dir / "CLAUDE.md"
    claude_src = TEMPLATES_DIR / "CLAUDE.md"
    if claude_src.exists():
        beads_content = claude_src.read_text(encoding='utf-8').replace("[Project]", project_name)
        if claude_dest.exists():
            existing_content = claude_dest.read_text(encoding='utf-8')
            if "## Workflow" in existing_content and "beads" in existing_content.lower():
                print("  - CLAUDE.md (already has beads section, skipped)")
            else:
                separator = "\n\n---\n\n# Beads Orchestration\n\n"
                with open(claude_dest, "a", encoding="utf-8") as f:
                    f.write(separator + beads_content)
                print("  - CLAUDE.md (appended beads section)")
        else:
            claude_dest.write_text(beads_content, encoding='utf-8')
            print("  - CLAUDE.md (created)")

    print("  DONE")


def setup_gitignore(project_dir: Path) -> None:
    """Ensure .beads/, .worktrees/, and .claude/.upgrades/ are in .gitignore."""
    print("\n[6/6] Setting up .gitignore...")
    gitignore_path = project_dir / ".gitignore"
    entries = [".beads/", ".worktrees/", ".claude/.upgrades/"]

    if gitignore_path.exists():
        content = gitignore_path.read_text(encoding='utf-8')
        missing = [e for e in entries if e not in content and e.rstrip("/") not in content]
        if missing:
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
        gitignore_path.write_text(
            "# Beads orchestration\n.beads/\n.worktrees/\n.claude/.upgrades/\n",
            encoding='utf-8',
        )
        print("  - Created .gitignore")

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
) -> int:
    """Run bootstrap for a single project. Returns exit code (0 = success)."""
    project_dir.mkdir(parents=True, exist_ok=True)
    resolved_name = project_name or infer_project_name(project_dir)

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

    if not install_beads(project_dir):
        return 1

    all_skipped += copy_agents(project_dir, resolved_name, manifest, force)
    copy_hooks(project_dir, manifest)
    all_skipped += copy_rules_and_skills(
        project_dir, with_rules, lang, manifest, force,
    )
    copy_settings_and_claude_md(project_dir, resolved_name)
    setup_gitignore(project_dir)

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
    manifest["installed_at"] = datetime.now(timezone.utc).isoformat()
    if not dry_run:
        save_manifest(project_dir, manifest)

    print("\n" + "=" * 60)
    print("BOOTSTRAP COMPLETE")
    print("=" * 60)

    if all_skipped:
        print(f"\n  {len(all_skipped)} file(s) skipped (user-modified):")
        for rel in all_skipped:
            print(f"    - {rel}")
            print(f"      Review: diff .claude/{rel} .claude/.upgrades/{rel}")

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

    print(f"\n[BATCH UPGRADE] Scanning {parent_dir}")
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
    parser.add_argument("--lang", default="en", choices=["en", "ru"], help="Language for dev rules (default: en)")
    parser.add_argument("--force", action="store_true", help="Overwrite all files regardless of user modifications")
    parser.add_argument("--upgrade", action="store_true", help="Run init flow then cleanup obsolete items (uses existing manifest)")
    parser.add_argument("--dry-run", action="store_true", help="Print plan without writing anything")
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
        upgrade=args.upgrade, dry_run=args.dry_run,
    ))


if __name__ == "__main__":
    main()
