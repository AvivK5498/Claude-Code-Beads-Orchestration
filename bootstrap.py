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
# STEPS
# ============================================================================

def install_beads(project_dir: Path) -> bool:
    """Install beads CLI and initialize .beads directory."""
    print("\n[1/6] Installing beads...")

    if not shutil.which("bd"):
        print("  - beads CLI (bd) not found, installing...")
        for method, cmd in [
            ("Homebrew", ["brew", "install", "steveyegge/beads/bd"]),
            ("npm", ["npm", "install", "-g", "@beads/bd"]),
            ("go", ["go", "install", "github.com/steveyegge/beads/cmd/bd@latest"]),
        ]:
            if shutil.which(cmd[0]):
                result = subprocess.run(cmd, capture_output=True, text=True, shell=_SHELL)
                if result.returncode == 0:
                    print(f"  - Installed via {method}")
                    break
        else:
            print("  ERROR: Could not install beads CLI (bd)")
            print("  Install manually: https://github.com/steveyegge/beads#-installation")
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

    # Setup memory/knowledge base
    memory_dir = beads_dir / "memory"
    memory_dir.mkdir(parents=True, exist_ok=True)
    knowledge_file = memory_dir / "knowledge.jsonl"
    if not knowledge_file.exists():
        knowledge_file.touch()

    recall_src = TEMPLATES_DIR / "hooks" / "recall.cjs"
    if recall_src.exists():
        shutil.copy2(recall_src, memory_dir / "recall.cjs")

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
    """Ensure .beads/ is in .gitignore."""
    print("\n[6/6] Setting up .gitignore...")
    gitignore_path = project_dir / ".gitignore"
    entries = [".beads/", ".worktrees/"]

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
        gitignore_path.write_text("# Beads orchestration\n.beads/\n.worktrees/\n", encoding='utf-8')
        print("  - Created .gitignore")

    print("  DONE")


# ============================================================================
# MAIN
# ============================================================================

def main():
    import argparse

    parser = argparse.ArgumentParser(description="Bootstrap beads orchestration")
    parser.add_argument("--project-name", default=None, help="Project name (auto-inferred if not provided)")
    parser.add_argument("--project-dir", default=".", help="Project directory")
    parser.add_argument("--with-rules", action="store_true", help="Also copy dev rules (implementation-standard, logging, tdd)")
    parser.add_argument("--lang", default="en", choices=["en", "ru"], help="Language for dev rules (default: en)")
    parser.add_argument("--force", action="store_true", help="Overwrite all files regardless of user modifications")
    args = parser.parse_args()

    project_dir = Path(args.project_dir).resolve()
    project_dir.mkdir(parents=True, exist_ok=True)

    project_name = args.project_name or infer_project_name(project_dir)
    print(f"\nBootstrapping beads orchestration for: {project_name}")
    print(f"Directory: {project_dir}")
    if args.force:
        print("Mode: FORCE (overwriting all files)")
    print("=" * 60)

    if not TEMPLATES_DIR.exists():
        print(f"\nERROR: Templates not found: {TEMPLATES_DIR}")
        sys.exit(1)

    manifest = load_manifest(project_dir)
    all_skipped = []

    if not install_beads(project_dir):
        sys.exit(1)

    all_skipped += copy_agents(project_dir, project_name, manifest, args.force)
    copy_hooks(project_dir, manifest)
    all_skipped += copy_rules_and_skills(
        project_dir, args.with_rules, args.lang, manifest, args.force,
    )
    copy_settings_and_claude_md(project_dir, project_name)
    setup_gitignore(project_dir)

    # Read version from package.json (same package as bootstrap.py)
    pkg_json = SCRIPT_DIR / "package.json"
    pkg_version = None
    if pkg_json.exists():
        try:
            pkg_version = json.loads(pkg_json.read_text(encoding="utf-8")).get("version")
        except Exception:
            pass

    manifest["version"] = pkg_version
    manifest["installed_at"] = datetime.now(timezone.utc).isoformat()
    save_manifest(project_dir, manifest)

    print("\n" + "=" * 60)
    print("BOOTSTRAP COMPLETE")
    print("=" * 60)

    if all_skipped:
        print(f"\n  {len(all_skipped)} file(s) skipped (user-modified):")
        for rel in all_skipped:
            print(f"    - {rel}")
            print(f"      Review: diff .claude/{rel} .claude/.upgrades/{rel}")

    print(f"""
Next steps:

1. Restart Claude Code to load hooks and agents
2. Run /project-discovery to extract project conventions
3. Create your first bead: bd create "Task" -d "Description"
4. Dispatch work: Task(subagent_type="general-purpose", prompt="BEAD_ID: ...")
""")


if __name__ == "__main__":
    main()
