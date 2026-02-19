#!/usr/bin/env python3
"""
Bootstrap script for beads-based orchestration.

Creates:
- .beads/ directory with beads CLI
- .claude/agents/ with agent templates (copied, not generated)
- .claude/hooks/ with hook scripts
- .claude/settings.json with hook configuration
- .mcp.json with provider-delegator configuration (only with --external-providers)

Usage:
    python bootstrap.py [--project-name NAME] [--project-dir DIR] [--with-kanban-ui] [--with-mux]

Modes:
    Default: All agents use Claude Task() directly (claude-only)
    --external-providers: Sets up provider_delegator MCP for Codex/Gemini delegation
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

CORE_AGENTS = ["scout", "detective", "architect", "scribe", "discovery", "merge-supervisor", "code-reviewer"]

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

# Shared location for provider-delegator (installed once, used by all projects)
SHARED_MCP_DIR = Path.home() / ".claude" / "mcp-servers" / "provider-delegator"


def setup_provider_delegator() -> Path:
    """Set up provider-delegator in shared location (~/.claude/mcp-servers/provider-delegator/).

    This installs once and is reused by all projects.
    Returns path to venv python.
    """
    print("\n[0/8] Setting up provider-delegator (shared)...")

    source_dir = SCRIPT_DIR / "mcp-provider-delegator"
    venv_dir = SHARED_MCP_DIR / ".venv"
    venv_python = venv_dir / "bin" / "python"

    # Check if already installed in shared location
    if venv_python.exists():
        print(f"  - Already installed at {SHARED_MCP_DIR}")
        return venv_python

    # Verify source exists
    if not source_dir.exists():
        print(f"  ERROR: mcp-provider-delegator not found at {source_dir}")
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

    print(f"  DONE: provider-delegator installed at {SHARED_MCP_DIR}")
    return venv_python


# ============================================================================
# BEADS INSTALLATION
# ============================================================================

def install_beads(project_dir: Path, claude_only: bool = False) -> bool:
    """Install beads CLI and initialize .beads directory."""
    step = "[1/7]" if claude_only else "[1/8]"
    print(f"\n{step} Installing beads...")

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


def setup_memory(project_dir: Path) -> None:
    """Create .beads/memory/ directory with knowledge store and recall script."""
    memory_dir = project_dir / ".beads" / "memory"
    memory_dir.mkdir(parents=True, exist_ok=True)

    # Create empty knowledge store
    knowledge_file = memory_dir / "knowledge.jsonl"
    if not knowledge_file.exists():
        knowledge_file.touch()
        print("  - Created .beads/memory/knowledge.jsonl")

    # Copy recall script
    recall_src = TEMPLATES_DIR / "memory" / "recall.sh"
    recall_dest = memory_dir / "recall.sh"
    if recall_src.exists():
        shutil.copy2(recall_src, recall_dest)
        recall_dest.chmod(recall_dest.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
        print("  - Copied .beads/memory/recall.sh")
    else:
        print("  - WARNING: recall.sh template not found")


# ============================================================================
# RAMS INSTALLATION (Accessibility Review)
# ============================================================================

def install_rams() -> bool:
    """Install RAMS accessibility review tool if not already installed."""
    print("\n  Checking RAMS (accessibility review tool)...")

    # Check if rams is already installed
    if shutil.which("rams"):
        print("  - RAMS already installed")
        return True

    print("  - RAMS not found, installing...")

    # Install via curl
    if sys.platform != "win32":
        result = subprocess.run(
            ["bash", "-c", "curl -fsSL https://rams.ai/install | bash"],
            capture_output=True,
            text=True
        )
        if result.returncode == 0:
            print("  - RAMS installed successfully")
            return True
        else:
            print(f"  - Warning: Could not install RAMS: {result.stderr}")
            print("  - Frontend supervisors will still work but RAMS review enforcement may fail")
            print("  - Install manually: curl -fsSL https://rams.ai/install | bash")
            return False

    print("  - Warning: RAMS installation not supported on Windows")
    return False


# ============================================================================
# WEB INTERFACE GUIDELINES INSTALLATION
# ============================================================================

def install_web_interface_guidelines() -> bool:
    """Install Web Interface Guidelines review tool if not already installed."""
    print("\n  Checking Web Interface Guidelines (design review tool)...")

    # Check if wig is already installed
    if shutil.which("wig"):
        print("  - Web Interface Guidelines already installed")
        return True

    print("  - Web Interface Guidelines not found, installing...")

    # Install via curl
    if sys.platform != "win32":
        result = subprocess.run(
            ["bash", "-c", "curl -fsSL https://vercel.com/design/guidelines/install | bash"],
            capture_output=True,
            text=True
        )
        if result.returncode == 0:
            print("  - Web Interface Guidelines installed successfully")
            return True
        else:
            print(f"  - Warning: Could not install Web Interface Guidelines: {result.stderr}")
            print("  - Frontend supervisors will still work but WIG review enforcement may fail")
            print("  - Install manually: curl -fsSL https://vercel.com/design/guidelines/install | bash")
            return False

    print("  - Warning: Web Interface Guidelines installation not supported on Windows")
    return False


# ============================================================================
# AGENTS (TEMPLATE COPYING)
# ============================================================================

def copy_agents(project_dir: Path, project_name: str, claude_only: bool = False, with_kanban_ui: bool = False) -> list:
    """Copy core agent templates from templates/ directory.

    NOTE: Supervisors are NOT copied here - they are created dynamically
    by the discovery agent based on detected tech stack.
    """
    step = "[2/7]" if claude_only else "[2/8]"
    print(f"\n{step} Copying core agent templates...")

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
    # Select API version (with git fallback) or git-only version based on flag
    if with_kanban_ui:
        beads_workflow_src = TEMPLATES_DIR / "beads-workflow-injection-api.md"
        workflow_type = "API + git fallback"
    else:
        beads_workflow_src = TEMPLATES_DIR / "beads-workflow-injection-git.md"
        workflow_type = "git only"
    beads_workflow_dest = project_dir / ".claude" / "beads-workflow-injection.md"
    if beads_workflow_src.exists():
        shutil.copy2(beads_workflow_src, beads_workflow_dest)
        print(f"  - Copied beads-workflow-injection.md ({workflow_type})")

    # Copy UI constraints (used by discovery agent for frontend supervisors)
    ui_constraints_src = TEMPLATES_DIR / "ui-constraints.md"
    ui_constraints_dest = project_dir / ".claude" / "ui-constraints.md"
    if ui_constraints_src.exists():
        shutil.copy2(ui_constraints_src, ui_constraints_dest)
        print("  - Copied ui-constraints.md")

    # Copy frontend reviews requirement (RAMS + Web Interface Guidelines)
    frontend_reviews_src = TEMPLATES_DIR / "frontend-reviews-requirement.md"
    frontend_reviews_dest = project_dir / ".claude" / "frontend-reviews-requirement.md"
    if frontend_reviews_src.exists():
        shutil.copy2(frontend_reviews_src, frontend_reviews_dest)
        print("  - Copied frontend-reviews-requirement.md")

    print(f"  DONE: {len(copied)} core agents copied")
    print("  NOTE: Supervisors will be created by discovery agent based on tech stack")
    return copied


# ============================================================================
# SKILLS (TEMPLATE COPYING)
# ============================================================================

def copy_skills(project_dir: Path, claude_only: bool = False) -> list:
    """Copy skill templates from templates/ directory.

    Skills are copied so discovery agent can install them when tech stack is detected.
    """
    step = "[3/7]" if claude_only else "[3/8]"
    print(f"\n{step} Copying skill templates...")

    skills_template_dir = TEMPLATES_DIR / "skills"
    if not skills_template_dir.exists():
        print("  - No skill templates found, skipping")
        return []

    skills_dir = project_dir / ".claude" / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)

    copied = []

    for skill_dir in skills_template_dir.iterdir():
        if skill_dir.is_dir():
            dest_dir = skills_dir / skill_dir.name
            if dest_dir.exists():
                shutil.rmtree(dest_dir)
            shutil.copytree(skill_dir, dest_dir)
            copied.append(skill_dir.name)
            print(f"  - Copied {skill_dir.name}/ skill")

    print(f"  DONE: {len(copied)} skill templates copied")
    return copied


# ============================================================================
# HOOKS (TEMPLATE COPYING)
# ============================================================================

def copy_hooks(project_dir: Path, claude_only: bool = False) -> list:
    """Copy hook templates from templates/ directory.

    Args:
        project_dir: Target project directory
        claude_only: If True, skip provider delegation enforcement hooks
    """
    step = "[4/7]" if claude_only else "[4/8]"
    print(f"\n{step} Copying hook templates...")

    hooks_dir = project_dir / ".claude" / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)

    hooks_template_dir = TEMPLATES_DIR / "hooks"
    copied = []

    # Hooks to skip in claude-only mode (none currently - all hooks apply to both modes)
    skip_in_claude_only = set()

    for hook_file in hooks_template_dir.glob("*.sh"):
        # Skip provider enforcement hooks in claude-only mode
        if claude_only and hook_file.name in skip_in_claude_only:
            print(f"  - Skipped {hook_file.name} (claude-only mode)")
            continue

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

def copy_settings(project_dir: Path, claude_only: bool = False) -> None:
    """Copy settings.json template, optionally removing provider enforcement hooks.

    Args:
        project_dir: Target project directory
        claude_only: If True, remove provider delegation enforcement from settings
    """
    step = "[5/7]" if claude_only else "[5/8]"
    print(f"\n{step} Copying settings...")

    settings_template = TEMPLATES_DIR / "settings.json"
    settings_dest = project_dir / ".claude" / "settings.json"

    # Settings are the same for both modes now (no provider-specific hooks)
    shutil.copy2(settings_template, settings_dest)
    if claude_only:
        print("  - Copied settings.json (claude-only mode)")
    else:
        print("  - Copied settings.json")

    print("  DONE: settings configured")


# ============================================================================
# CLAUDE.MD
# ============================================================================

def copy_claude_md(project_dir: Path, project_name: str, claude_only: bool = False) -> None:
    """Copy CLAUDE.md template with project name replacement."""
    step = "[6/7]" if claude_only else "[6/8]"
    print(f"\n{step} Copying CLAUDE.md...")

    claude_template = TEMPLATES_DIR / "CLAUDE.md"
    claude_dest = project_dir / "CLAUDE.md"

    replacements = {"[Project]": project_name}
    copy_and_replace(claude_template, claude_dest, replacements)

    print("  - Copied CLAUDE.md")
    print("  DONE: CLAUDE.md copied")


# ============================================================================
# MUX WORKSPACE FILES
# ============================================================================

def copy_mux_workspace_files(project_dir: Path, project_name: str) -> None:
    """Install Mux workspace integration files (.mux/init, .mux/tool_post, .mux/tool_env, .mux/AGENTS.md)."""
    print("\n[MUX] Installing Mux workspace files...")

    mux_template_dir = TEMPLATES_DIR / "mux"
    mux_dir = project_dir / ".mux"
    mux_dir.mkdir(parents=True, exist_ok=True)

    # Copy instruction layer
    agents_template = mux_template_dir / "AGENTS.md"
    agents_dest = mux_dir / "AGENTS.md"
    if agents_template.exists():
        copy_and_replace(agents_template, agents_dest, {"[Project]": project_name})
        print("  - Copied .mux/AGENTS.md")
    else:
        print("  - WARNING: Missing template templates/mux/AGENTS.md")

    # Copy Mux hooks
    init_src = mux_template_dir / "init"
    init_dest = mux_dir / "init"
    if init_src.exists():
        shutil.copy2(init_src, init_dest)
        init_dest.chmod(init_dest.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
        print("  - Copied .mux/init")
    else:
        print("  - WARNING: Missing template templates/mux/init")

    tool_post_src = mux_template_dir / "tool_post"
    tool_post_dest = mux_dir / "tool_post"
    if tool_post_src.exists():
        shutil.copy2(tool_post_src, tool_post_dest)
        tool_post_dest.chmod(tool_post_dest.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
        print("  - Copied .mux/tool_post")
    else:
        print("  - WARNING: Missing template templates/mux/tool_post")

    tool_env_src = mux_template_dir / "tool_env"
    tool_env_dest = mux_dir / "tool_env"
    if tool_env_src.exists():
        shutil.copy2(tool_env_src, tool_env_dest)
        tool_env_dest.chmod(0o644)
        print("  - Copied .mux/tool_env")
    else:
        print("  - WARNING: Missing template templates/mux/tool_env")

    print("  DONE: Mux workspace files installed")


# ============================================================================
# GITIGNORE
# ============================================================================

def setup_gitignore(project_dir: Path, claude_only: bool = False, with_mux: bool = False) -> None:
    """Ensure ephemeral files are in .gitignore. .claude/ and .mux/ are tracked."""
    step = "[7/7]" if claude_only else "[7/8]"
    print(f"\n{step} Setting up .gitignore...")

    gitignore_path = project_dir / ".gitignore"
    # Ignore ephemeral task/runtime data and local instruction overrides.
    # .claude/ and .mux/ are tracked so configuration survives git operations.
    entries_to_add = [".beads/", ".mcp.json"]
    if with_mux:
        entries_to_add.append(".mux/AGENTS.local.md")

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
                if with_mux:
                    f.write("\n# Beads and local agent runtime state (ephemeral)\n")
                else:
                    f.write("\n# Beads task tracking (ephemeral)\n")
                for entry in missing:
                    f.write(f"{entry}\n")
                    print(f"  - Added {entry} to .gitignore")
        else:
            if with_mux:
                print("  - .beads/, .mcp.json, and .mux/AGENTS.local.md already in .gitignore")
            else:
                print("  - .beads/ and .mcp.json already in .gitignore")
    else:
        # Create new .gitignore
        content = """# Beads task tracking (ephemeral)
.beads/

# MCP config (user-specific paths)
.mcp.json
"""
        if with_mux:
            content = """# Beads and local agent runtime state (ephemeral)
.beads/
.mux/AGENTS.local.md

# MCP config (user-specific paths)
.mcp.json
"""

        gitignore_path.write_text(content)
        if with_mux:
            print("  - Created .gitignore with .beads/, .mcp.json, and .mux/AGENTS.local.md")
        else:
            print("  - Created .gitignore with .beads/ and .mcp.json")

    print("  DONE: .gitignore configured")
    if with_mux:
        print("  NOTE: .claude/ and .mux/ are tracked (not ignored) to prevent accidental loss")
    else:
        print("  NOTE: .claude/ is tracked (not ignored) to prevent accidental loss")


# ============================================================================
# MCP CONFIG
# ============================================================================

def create_mcp_config(project_dir: Path, venv_python: Path) -> None:
    """Add provider-delegator to .mcp.json, preserving existing servers."""
    print("\n[8/8] Configuring MCP...")

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

    # Add/update provider_delegator
    existing["mcpServers"]["provider_delegator"] = {
        "type": "stdio",
        "command": str(venv_python),
        "args": ["-m", "mcp_provider_delegator.server"],
        "env": {
            "AGENT_TEMPLATES_PATH": ".claude/agents"
        }
    }

    mcp_dest.write_text(json.dumps(existing, indent=2))

    server_count = len(existing["mcpServers"])
    print(f"  - Added provider-delegator to .mcp.json ({server_count} total servers)")
    print(f"    Command: {venv_python}")
    print(f"    Agents: .claude/agents (relative)")
    print("  DONE: MCP config updated")


# ============================================================================
# VERIFICATION
# ============================================================================

def verify_installation(project_dir: Path, claude_only: bool = False, with_mux: bool = False) -> bool:
    """Verify all components were installed correctly."""
    checks = {
        ".claude/hooks": "Hooks directory",
        ".claude/agents": "Agents directory",
        ".claude/settings.json": "Settings file",
        ".beads": "Beads directory",
        "CLAUDE.md": "CLAUDE.md",
        ".gitignore": ".gitignore",
    }

    if with_mux:
        checks[".mux/AGENTS.md"] = "Mux workspace AGENTS.md"
        checks[".mux/init"] = "Mux init hook"
        checks[".mux/tool_post"] = "Mux tool_post hook"
        checks[".mux/tool_env"] = "Mux tool_env hook"

    # Only check for .mcp.json in external providers mode
    if not claude_only:
        checks[".mcp.json"] = "MCP config"

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

    skills_dir = project_dir / ".claude/skills"
    if skills_dir.exists():
        skill_count = len(list(skills_dir.iterdir()))
        if skill_count > 0:
            print(f"  - Skills: {skill_count}")

    return all_good


# ============================================================================
# MAIN
# ============================================================================

def main():
    import argparse

    parser = argparse.ArgumentParser(description="Bootstrap beads-based orchestration")
    parser.add_argument("--project-name", default=None, help="Project name (auto-inferred if not provided)")
    parser.add_argument("--project-dir", default=".", help="Project directory")
    parser.add_argument("--external-providers", action="store_true",
                        help="Use Codex/Gemini for delegation (default: Claude-only)")
    parser.add_argument("--with-kanban-ui", action="store_true",
                        help="Use Beads Kanban UI API for worktree creation (with git fallback)")
    parser.add_argument("--with-mux", action="store_true",
                        help="Install Mux workspace files (.mux/AGENTS.md, .mux/init, .mux/tool_post, .mux/tool_env)")
    args = parser.parse_args()

    project_dir = Path(args.project_dir).resolve()
    claude_only = not args.external_providers  # Default is now claude-only
    with_kanban_ui = args.with_kanban_ui
    with_mux = args.with_mux

    # Ensure project directory exists
    project_dir.mkdir(parents=True, exist_ok=True)

    # Auto-infer project name if not provided
    if args.project_name:
        project_name = args.project_name
    else:
        project_name = infer_project_name(project_dir)
        print(f"Auto-inferred project name: {project_name}")

    mode_str = "CLAUDE-ONLY" if claude_only else "EXTERNAL PROVIDERS"
    worktree_str = "API + git fallback" if with_kanban_ui else "git only"
    mux_str = "enabled" if with_mux else "disabled"
    print(f"\nBootstrapping beads orchestration for: {project_name}")
    print(f"Directory: {project_dir}")
    print(f"Mode: {mode_str}")
    print(f"Worktrees: {worktree_str}")
    print(f"Mux workspace files: {mux_str}")
    print("=" * 60)

    # Verify templates exist
    if not TEMPLATES_DIR.exists():
        print(f"\nERROR: Templates directory not found: {TEMPLATES_DIR}")
        print("Make sure you cloned the full lean-orchestration repo")
        sys.exit(1)

    venv_python = None

    # Step 0: Setup bundled provider-delegator (skip in claude-only mode)
    if not claude_only:
        venv_python = setup_provider_delegator()
        if not venv_python:
            print("\nERROR: Failed to setup provider-delegator. Aborting.")
            sys.exit(1)

        # Run remaining steps with provider support
        if not install_beads(project_dir, claude_only=False):
            print("\nERROR: Beads CLI is required. Aborting bootstrap.")
            sys.exit(1)

        # Install frontend review tools (optional, won't block)
        install_rams()
        install_web_interface_guidelines()

        copy_agents(project_dir, project_name, claude_only=False, with_kanban_ui=with_kanban_ui)
        copy_skills(project_dir, claude_only=False)
        copy_hooks(project_dir, claude_only=False)
        copy_settings(project_dir, claude_only=False)
        copy_claude_md(project_dir, project_name, claude_only=False)
        setup_memory(project_dir)
        if with_mux:
            copy_mux_workspace_files(project_dir, project_name)
        setup_gitignore(project_dir, claude_only=False, with_mux=with_mux)
        create_mcp_config(project_dir, venv_python)
    else:
        # Claude-only mode: skip provider setup
        print("\n[0/7] Skipping provider-delegator setup (claude-only mode)")

        if not install_beads(project_dir, claude_only=True):
            print("\nERROR: Beads CLI is required. Aborting bootstrap.")
            sys.exit(1)

        # Install frontend review tools (optional, won't block)
        install_rams()
        install_web_interface_guidelines()

        copy_agents(project_dir, project_name, claude_only=True, with_kanban_ui=with_kanban_ui)
        copy_skills(project_dir, claude_only=True)
        copy_hooks(project_dir, claude_only=True)
        copy_settings(project_dir, claude_only=True)
        copy_claude_md(project_dir, project_name, claude_only=True)
        setup_memory(project_dir)
        if with_mux:
            copy_mux_workspace_files(project_dir, project_name)
        setup_gitignore(project_dir, claude_only=True, with_mux=with_mux)

    # Verify
    if not verify_installation(project_dir, claude_only, with_mux=with_mux):
        print("\nWARNING: Installation incomplete - check errors above")

    # Optional Mux init hook execution (matches Mux init behavior for new workspaces)
    run_mux_init_if_present(project_dir, with_mux)

    print("\n" + "=" * 60)
    print("BOOTSTRAP COMPLETE")
    print("=" * 60)

    if claude_only:
        print(f"""
Mode: CLAUDE-ONLY (all agents use Claude Task)

Next steps:

1. Restart Claude Code to load new hooks and agents

2. (Optional) If you enabled Mux integration, restart your Mux workspace session
   so .mux/init/.mux/tool_post/.mux/tool_env and .mux/AGENTS.md are loaded.

3. **REQUIRED: Run discovery to create supervisors**
   Discovery will scan your codebase and fetch specialist agents:

   Task(
       subagent_type="discovery",
       prompt="Detect tech stack and create supervisors for {project_name}"
   )

4. Create your first bead:
   bd create "First task"

5. Dispatch work to supervisors:
   Task(subagent_type="<supervisor-name>", prompt="BEAD_ID: BD-001\\n\\nImplement...")

NOTE: All agents (scout, detective, architect, etc.) run via Claude Task().
No external providers (Codex/Gemini) are configured.
""")
    else:
        print(f"""
Mode: EXTERNAL PROVIDERS (Codex → Gemini → Claude fallback)

Next steps:

1. Restart Claude Code to load new hooks and agents

2. (Optional) If you enabled Mux integration, restart your Mux workspace session
   so .mux/init/.mux/tool_post/.mux/tool_env and .mux/AGENTS.md are loaded.

3. **REQUIRED: Run discovery to create supervisors**
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

4. Create your first bead:
   bd create "First task"

5. Dispatch work to supervisors:
   Task(subagent_type="<supervisor-name>", prompt="BEAD_ID: BD-001\\n\\nImplement...")

NOTE: Read-only agents (scout, detective, architect, scribe, code-reviewer)
are delegated via provider_delegator MCP (Codex → Gemini fallback).
Supervisors are sourced from https://github.com/ayush-that/sub-agents.directory
with beads workflow injected.
""")




def run_mux_init_if_present(project_dir: Path, enabled: bool) -> None:
    """Run .mux/init after bootstrap when Mux integration is enabled."""
    if not enabled:
        return

    mux_init = project_dir / ".mux" / "init"
    if not mux_init.exists():
        print("\n[MUX] Skipping .mux/init (not found)")
        return

    print("\n[MUX] Running .mux/init...")
    result = subprocess.run(
        [str(mux_init)],
        cwd=project_dir,
        capture_output=True,
        text=True,
    )

    if result.returncode == 0:
        print("  - .mux/init completed successfully")
    else:
        print(f"  - WARNING: .mux/init exited with code {result.returncode}")

    if result.stdout:
        print("  - stdout:")
        for line in result.stdout.strip().splitlines():
            print(f"    {line}")

    if result.stderr:
        print("  - stderr:")
        for line in result.stderr.strip().splitlines():
            print(f"    {line}")

if __name__ == "__main__":
    main()
