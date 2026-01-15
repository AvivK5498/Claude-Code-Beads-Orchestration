#!/usr/bin/env python3
"""
Bootstrap script for beads-based orchestration.

Creates:
- .beads/ directory with beads CLI
- .claude/agents/ with agent templates (copied, not generated)
- .claude/hooks/ with hook scripts
- .claude/settings.json with hook configuration
- .mcp.json with codex-delegator configuration

Usage:
    python bootstrap.py [--project-name NAME] [--project-dir DIR]
"""

import os
import sys
import json
import shutil
import stat
import subprocess
try:
    import tomllib
except ImportError:
    tomllib = None
from pathlib import Path
from datetime import datetime
import random

# Get the directory where this script lives (lean-orchestration repo)
SCRIPT_DIR = Path(__file__).parent.resolve()
TEMPLATES_DIR = SCRIPT_DIR / "templates"

# ============================================================================
# CONFIGURATION
# ============================================================================

CORE_AGENTS = ["scout", "detective", "architect", "worker-supervisor", "scribe", "discovery", "merge-supervisor"]

# NOTE: Supervisors are NOT bootstrapped - they are created dynamically by the
# discovery agent which fetches specialists from the external agents directory
# and injects the beads workflow.


# ============================================================================
# PROJECT NAME INFERENCE
# ============================================================================

def infer_project_name(project_dir: Path) -> str:
    """Auto-infer project name from package files or directory name."""

    # Try package.json (Node.js)
    package_json = project_dir / "package.json"
    if package_json.exists():
        try:
            data = json.loads(package_json.read_text())
            if name := data.get("name"):
                return name.replace("-", " ").replace("_", " ").title()
        except (json.JSONDecodeError, KeyError):
            pass

    # Try pyproject.toml (Python)
    if tomllib:
        pyproject = project_dir / "pyproject.toml"
        if pyproject.exists():
            try:
                data = tomllib.loads(pyproject.read_text())
                if name := data.get("project", {}).get("name"):
                    return name.replace("-", " ").replace("_", " ").title()
                if name := data.get("tool", {}).get("poetry", {}).get("name"):
                    return name.replace("-", " ").replace("_", " ").title()
            except Exception:
                pass

        # Try Cargo.toml (Rust)
        cargo = project_dir / "Cargo.toml"
        if cargo.exists():
            try:
                data = tomllib.loads(cargo.read_text())
                if name := data.get("package", {}).get("name"):
                    return name.replace("-", " ").replace("_", " ").title()
            except Exception:
                pass

    # Try go.mod (Go)
    go_mod = project_dir / "go.mod"
    if go_mod.exists():
        try:
            content = go_mod.read_text()
            for line in content.splitlines():
                if line.startswith("module "):
                    module_path = line.split()[1]
                    name = module_path.split("/")[-1]
                    return name.replace("-", " ").replace("_", " ").title()
        except Exception:
            pass

    # Fallback to directory name
    return project_dir.name.replace("-", " ").replace("_", " ").title()


# ============================================================================
# PLACEHOLDER REPLACEMENT
# ============================================================================

def replace_placeholders(content: str, replacements: dict) -> str:
    """Replace all placeholders in content."""
    for placeholder, value in replacements.items():
        content = content.replace(placeholder, value)
    return content


def copy_and_replace(source: Path, dest: Path, replacements: dict) -> None:
    """Copy file and replace placeholders."""
    content = source.read_text()
    updated = replace_placeholders(content, replacements)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(updated)

    # Preserve executable permissions for shell scripts
    if source.suffix == '.sh':
        dest.chmod(dest.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


# ============================================================================
# CODEX DELEGATOR SETUP (SHARED LOCATION)
# ============================================================================

# Shared location for codex-delegator (installed once, used by all projects)
SHARED_MCP_DIR = Path.home() / ".claude" / "mcp-servers" / "codex-delegator"


def setup_codex_delegator() -> Path:
    """Set up codex-delegator in shared location (~/.claude/mcp-servers/codex-delegator/).

    This installs once and is reused by all projects.
    Returns path to venv python.
    """
    print("\n[0/6] Setting up codex-delegator (shared)...")

    source_dir = SCRIPT_DIR / "mcp-codex-delegator"
    venv_dir = SHARED_MCP_DIR / ".venv"
    venv_python = venv_dir / "bin" / "python"

    # Check if already installed in shared location
    if venv_python.exists():
        print(f"  - Already installed at {SHARED_MCP_DIR}")
        return venv_python

    # Verify source exists
    if not source_dir.exists():
        print(f"  ERROR: mcp-codex-delegator not found at {source_dir}")
        print("  Make sure you cloned the full lean-orchestration repo")
        return None

    # Check if uv is available
    if not shutil.which("uv"):
        print("  ERROR: 'uv' not found. Install with: curl -LsSf https://astral.sh/uv/install.sh | sh")
        return None

    # Create shared directory
    print(f"  - Installing to {SHARED_MCP_DIR}")
    SHARED_MCP_DIR.mkdir(parents=True, exist_ok=True)

    # Copy source to shared location
    print("  - Copying source files...")
    for item in source_dir.iterdir():
        if item.name == ".venv":
            continue  # Skip any existing venv in source
        dest = SHARED_MCP_DIR / item.name
        if item.is_dir():
            if dest.exists():
                shutil.rmtree(dest)
            shutil.copytree(item, dest)
        else:
            shutil.copy2(item, dest)

    # Create venv using uv
    print("  - Creating venv with uv...")
    result = subprocess.run(
        ["uv", "venv", str(venv_dir)],
        cwd=SHARED_MCP_DIR,
        capture_output=True,
        text=True
    )
    if result.returncode != 0:
        print(f"  ERROR: Failed to create venv: {result.stderr}")
        return None

    # Install dependencies
    print("  - Installing dependencies...")
    result = subprocess.run(
        ["uv", "pip", "install", "-e", "."],
        cwd=SHARED_MCP_DIR,
        capture_output=True,
        text=True,
        env={**os.environ, "VIRTUAL_ENV": str(venv_dir)}
    )
    if result.returncode != 0:
        print(f"  ERROR: Failed to install dependencies: {result.stderr}")
        return None

    print(f"  DONE: codex-delegator installed at {SHARED_MCP_DIR}")
    return venv_python


# ============================================================================
# BEADS INSTALLATION
# ============================================================================

def install_beads(project_dir: Path) -> bool:
    """Install beads CLI and initialize .beads directory."""
    print("\n[1/6] Installing beads...")

    beads_dir = project_dir / ".beads"

    # Check if beads is already installed globally
    beads_installed = shutil.which("bd") is not None

    if not beads_installed:
        print("  - beads CLI (bd) not found, installing...")

        # Try installation methods in order of preference
        installed = False

        # Method 1: Homebrew (macOS)
        if shutil.which("brew") and sys.platform == "darwin":
            print("  - Trying Homebrew...")
            result = subprocess.run(
                ["brew", "install", "steveyegge/beads/bd"],
                capture_output=True,
                text=True
            )
            if result.returncode == 0:
                installed = True
                print("  - Installed via Homebrew")

        # Method 2: npm (cross-platform)
        if not installed and shutil.which("npm"):
            print("  - Trying npm...")
            result = subprocess.run(
                ["npm", "install", "-g", "@beads/bd"],
                capture_output=True,
                text=True
            )
            if result.returncode == 0:
                installed = True
                print("  - Installed via npm")

        # Method 3: curl install script (Linux/macOS/FreeBSD)
        if not installed and sys.platform != "win32":
            print("  - Trying curl install script...")
            result = subprocess.run(
                ["bash", "-c", "curl -fsSL https://raw.githubusercontent.com/steveyegge/beads/main/scripts/install.sh | bash"],
                capture_output=True,
                text=True
            )
            if result.returncode == 0:
                installed = True
                print("  - Installed via curl script")

        # Method 4: Go install (if Go is available)
        if not installed and shutil.which("go"):
            print("  - Trying go install...")
            result = subprocess.run(
                ["go", "install", "github.com/steveyegge/beads/cmd/bd@latest"],
                capture_output=True,
                text=True
            )
            if result.returncode == 0:
                installed = True
                print("  - Installed via go install")

        if not installed:
            print("\n  ERROR: Could not install beads CLI (bd)")
            print("  The beads workflow requires the bd command.")
            print("  Please install manually: https://github.com/steveyegge/beads#-installation")
            print("\n  Installation options:")
            print("    macOS:   brew install steveyegge/beads/bd")
            print("    npm:     npm install -g @beads/bd")
            print("    Go:      go install github.com/steveyegge/beads/cmd/bd@latest")
            return False
    else:
        print("  - beads CLI already installed")

    beads_installed = True

    # Initialize .beads in project
    if not beads_dir.exists():
        print("  - Initializing .beads directory...")

        # Try bd init first
        if shutil.which("bd"):
            result = subprocess.run(
                ["bd", "init"],
                cwd=project_dir,
                capture_output=True,
                text=True
            )
            if result.returncode == 0:
                print("  - Initialized via 'bd init'")
            else:
                # Manual init as fallback
                _manual_beads_init(beads_dir)
        else:
            _manual_beads_init(beads_dir)
    else:
        print("  - .beads already exists")

    # Configure custom 'inreview' status for parallel work workflow
    if shutil.which("bd"):
        print("  - Configuring custom 'inreview' status...")
        result = subprocess.run(
            ["bd", "config", "set", "status.custom", "inreview"],
            cwd=project_dir,
            capture_output=True,
            text=True
        )
        if result.returncode == 0:
            print("  - Added 'inreview' custom status")
        else:
            print(f"  - Warning: Could not add custom status: {result.stderr}")

    print("  DONE: beads setup complete")
    return True


def _manual_beads_init(beads_dir: Path):
    """Manually create .beads directory structure."""
    beads_dir.mkdir(exist_ok=True)
    (beads_dir / "issues.jsonl").touch()
    # Create minimal config
    config = {
        "version": "1",
        "mode": "normal"
    }
    (beads_dir / "config.json").write_text(json.dumps(config, indent=2))
    print("  - Created .beads manually")


# ============================================================================
# AGENTS (TEMPLATE COPYING)
# ============================================================================

def copy_agents(project_dir: Path, project_name: str) -> list:
    """Copy core agent templates from templates/ directory.

    NOTE: Supervisors are NOT copied here - they are created dynamically
    by the discovery agent based on detected tech stack.
    """
    print("\n[2/6] Copying core agent templates...")

    agents_dir = project_dir / ".claude" / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)

    agents_template_dir = TEMPLATES_DIR / "agents"

    copied = []

    # Replacements for templates
    replacements = {
        "[Project]": project_name,
    }

    # Copy core agents ONLY (not supervisors)
    for agent_file in agents_template_dir.glob("*.md"):
        dest = agents_dir / agent_file.name
        copy_and_replace(agent_file, dest, replacements)
        copied.append(agent_file.name)
        print(f"  - Copied {agent_file.name}")

    # Copy beads workflow injection snippet (used by discovery agent)
    beads_workflow_src = TEMPLATES_DIR / "beads-workflow-injection.md"
    beads_workflow_dest = project_dir / ".claude" / "beads-workflow-injection.md"
    if beads_workflow_src.exists():
        shutil.copy2(beads_workflow_src, beads_workflow_dest)
        print("  - Copied beads-workflow-injection.md")

    print(f"  DONE: {len(copied)} core agents copied")
    print("  NOTE: Supervisors will be created by discovery agent based on tech stack")
    return copied


# ============================================================================
# HOOKS (TEMPLATE COPYING)
# ============================================================================

def copy_hooks(project_dir: Path) -> list:
    """Copy hook templates from templates/ directory."""
    print("\n[3/6] Copying hook templates...")

    hooks_dir = project_dir / ".claude" / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)

    hooks_template_dir = TEMPLATES_DIR / "hooks"
    copied = []

    for hook_file in hooks_template_dir.glob("*.sh"):
        dest = hooks_dir / hook_file.name
        shutil.copy2(hook_file, dest)
        dest.chmod(dest.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
        copied.append(hook_file.name)
        print(f"  - Copied {hook_file.name}")

    print(f"  DONE: {len(copied)} hooks copied")
    return copied


# ============================================================================
# SETTINGS
# ============================================================================

def copy_settings(project_dir: Path) -> None:
    """Copy settings.json template."""
    print("\n[4/6] Copying settings...")

    settings_template = TEMPLATES_DIR / "settings.json"
    settings_dest = project_dir / ".claude" / "settings.json"

    shutil.copy2(settings_template, settings_dest)
    print("  - Copied settings.json")
    print("  DONE: settings copied")


# ============================================================================
# CLAUDE.MD
# ============================================================================

def copy_claude_md(project_dir: Path, project_name: str) -> None:
    """Copy CLAUDE.md template with project name replacement."""
    print("\n[5/6] Copying CLAUDE.md...")

    claude_template = TEMPLATES_DIR / "CLAUDE.md"
    claude_dest = project_dir / "CLAUDE.md"

    replacements = {"[Project]": project_name}
    copy_and_replace(claude_template, claude_dest, replacements)

    print("  - Copied CLAUDE.md")
    print("  DONE: CLAUDE.md copied")


# ============================================================================
# GITIGNORE
# ============================================================================

def setup_gitignore(project_dir: Path) -> None:
    """Ensure .beads is in .gitignore. .claude/ is tracked (not ignored)."""
    print("\n[6/7] Setting up .gitignore...")

    gitignore_path = project_dir / ".gitignore"
    # Only ignore .beads/ (ephemeral task data)
    # .claude/ is tracked so it survives git operations
    entries_to_add = [".beads/"]

    if gitignore_path.exists():
        content = gitignore_path.read_text()
        lines = content.splitlines()

        # Check which entries are missing
        missing = []
        for entry in entries_to_add:
            # Check for exact match or without trailing slash
            entry_no_slash = entry.rstrip("/")
            if entry not in lines and entry_no_slash not in lines:
                missing.append(entry)

        if missing:
            # Append missing entries
            with open(gitignore_path, "a") as f:
                # Add newline if file doesn't end with one
                if content and not content.endswith("\n"):
                    f.write("\n")
                f.write("\n# Beads task tracking (ephemeral)\n")
                for entry in missing:
                    f.write(f"{entry}\n")
                    print(f"  - Added {entry} to .gitignore")
        else:
            print("  - .beads/ already in .gitignore")
    else:
        # Create new .gitignore
        content = """# Beads task tracking (ephemeral)
.beads/
"""
        gitignore_path.write_text(content)
        print("  - Created .gitignore with .beads/")

    print("  DONE: .gitignore configured")
    print("  NOTE: .claude/ is tracked (not ignored) to prevent accidental loss")


# ============================================================================
# MCP CONFIG
# ============================================================================

def create_mcp_config(project_dir: Path, venv_python: Path) -> None:
    """Add codex-delegator to .mcp.json, preserving existing servers."""
    print("\n[7/7] Configuring MCP...")

    mcp_dest = project_dir / ".mcp.json"

    # Load existing config or start fresh
    if mcp_dest.exists():
        try:
            existing = json.loads(mcp_dest.read_text())
            print("  - Found existing .mcp.json, merging...")
        except json.JSONDecodeError:
            print("  - Warning: Invalid .mcp.json, creating new one")
            existing = {}
    else:
        existing = {}

    # Ensure mcpServers key exists
    if "mcpServers" not in existing:
        existing["mcpServers"] = {}

    # Add/update codex_delegator
    existing["mcpServers"]["codex_delegator"] = {
        "type": "stdio",
        "command": str(venv_python),
        "args": ["-m", "mcp_codex_delegator.server"],
        "env": {
            "AGENT_TEMPLATES_PATH": ".claude/agents"
        }
    }

    mcp_dest.write_text(json.dumps(existing, indent=2))

    server_count = len(existing["mcpServers"])
    print(f"  - Added codex-delegator to .mcp.json ({server_count} total servers)")
    print(f"    Command: {venv_python}")
    print(f"    Agents: .claude/agents (relative)")
    print("  DONE: MCP config updated")


# ============================================================================
# VERIFICATION
# ============================================================================

def verify_installation(project_dir: Path) -> bool:
    """Verify all components were installed correctly."""
    checks = {
        ".claude/hooks": "Hooks directory",
        ".claude/agents": "Agents directory",
        ".claude/settings.json": "Settings file",
        ".beads": "Beads directory",
        ".mcp.json": "MCP config",
        "CLAUDE.md": "CLAUDE.md",
        ".gitignore": ".gitignore",
    }

    print("\n=== Verification ===")
    all_good = True

    for path, description in checks.items():
        full_path = project_dir / path
        if full_path.exists():
            print(f"  - {description}")
        else:
            print(f"  X {description} MISSING")
            all_good = False

    # Count files
    hooks_dir = project_dir / ".claude/hooks"
    if hooks_dir.exists():
        hook_count = len(list(hooks_dir.glob("*.sh")))
        print(f"  - Hooks: {hook_count}")

    agents_dir = project_dir / ".claude/agents"
    if agents_dir.exists():
        agent_count = len(list(agents_dir.glob("*.md")))
        print(f"  - Agents: {agent_count}")

    return all_good


# ============================================================================
# MAIN
# ============================================================================

def main():
    import argparse

    parser = argparse.ArgumentParser(description="Bootstrap beads-based orchestration")
    parser.add_argument("--project-name", default=None, help="Project name (auto-inferred if not provided)")
    parser.add_argument("--project-dir", default=".", help="Project directory")
    args = parser.parse_args()

    project_dir = Path(args.project_dir).resolve()

    # Ensure project directory exists
    project_dir.mkdir(parents=True, exist_ok=True)

    # Auto-infer project name if not provided
    if args.project_name:
        project_name = args.project_name
    else:
        project_name = infer_project_name(project_dir)
        print(f"Auto-inferred project name: {project_name}")

    print(f"\nBootstrapping beads orchestration for: {project_name}")
    print(f"Directory: {project_dir}")
    print("=" * 60)

    # Verify templates exist
    if not TEMPLATES_DIR.exists():
        print(f"\nERROR: Templates directory not found: {TEMPLATES_DIR}")
        print("Make sure you cloned the full lean-orchestration repo")
        sys.exit(1)

    # Step 0: Setup bundled codex-delegator
    venv_python = setup_codex_delegator()
    if not venv_python:
        print("\nERROR: Failed to setup codex-delegator. Aborting.")
        sys.exit(1)

    # Run remaining steps
    if not install_beads(project_dir):
        print("\nERROR: Beads CLI is required. Aborting bootstrap.")
        sys.exit(1)

    copy_agents(project_dir, project_name)
    copy_hooks(project_dir)
    copy_settings(project_dir)
    copy_claude_md(project_dir, project_name)
    setup_gitignore(project_dir)
    create_mcp_config(project_dir, venv_python)

    # Verify
    if not verify_installation(project_dir):
        print("\nWARNING: Installation incomplete - check errors above")

    print("\n" + "=" * 60)
    print("BOOTSTRAP COMPLETE")
    print("=" * 60)
    print(f"""
Next steps:

1. Restart Claude Code to load new hooks and agents

2. **REQUIRED: Run discovery to create supervisors**
   Discovery will scan your codebase and fetch specialist agents:

   Task(
       subagent_type="discovery",
       prompt="Detect tech stack and create supervisors for {project_name}"
   )

   This will:
   - Scan package.json, requirements.txt, Dockerfile, etc.
   - Fetch matching specialists from external agents directory
   - Inject beads workflow at the beginning of each agent
   - Write supervisors to .claude/agents/

3. Create your first bead:
   bd create "First task"

4. Dispatch work to supervisors:
   Task(subagent_type="<supervisor-name>", prompt="BEAD_ID: BD-001\\n\\nImplement...")

NOTE: Supervisors are sourced from https://github.com/ayush-that/sub-agents.directory
with beads workflow injected. No local supervisor templates are used.
""")


if __name__ == "__main__":
    main()
