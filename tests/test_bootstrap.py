"""Tests for bootstrap.py — project name inference, copy_and_replace, setup_gitignore, manifest."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

# Add project root to path so we can import bootstrap
sys.path.insert(0, str(Path(__file__).parent.parent))

import bootstrap
from bootstrap import (
    infer_project_name,
    copy_and_replace,
    setup_gitignore,
    configure_beads_export,
    _from_package_json,
    _from_pyproject,
    _from_cargo,
    _from_go_mod,
    file_sha256,
    content_sha256,
    load_manifest,
    save_manifest,
    should_update_file,
    save_upgrade,
    cleanup_obsolete,
    run_bd_doctor,
    _auto_inject_legacy_files,
    _memory_dir_should_skip,
    _cleanup_empty_local_settings,
    _manifest_key,
    _has_existing_install,
    copy_settings_and_claude_md,
    _hook_basename,
    _entry_key,
    canonical_hook_commands,
    migrate_hook_commands,
    migrate_local_settings_hooks,
    merge_hooks,
    TEMPLATES_DIR,
)


# ============================================================================
# infer_project_name
# ============================================================================

class TestInferProjectName:
    def test_from_package_json(self, tmp_path):
        (tmp_path / "package.json").write_text(json.dumps({"name": "my-cool-app"}))
        assert infer_project_name(tmp_path) == "My Cool App"

    def test_from_package_json_with_scope(self, tmp_path):
        (tmp_path / "package.json").write_text(json.dumps({"name": "@org/my-package"}))
        assert infer_project_name(tmp_path) == "@Org/My Package"

    def test_from_package_json_underscores(self, tmp_path):
        (tmp_path / "package.json").write_text(json.dumps({"name": "my_cool_app"}))
        assert infer_project_name(tmp_path) == "My Cool App"

    def test_from_package_json_empty_name(self, tmp_path):
        (tmp_path / "package.json").write_text(json.dumps({"name": ""}))
        # Falls through to directory name
        result = infer_project_name(tmp_path)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_from_package_json_malformed(self, tmp_path):
        (tmp_path / "package.json").write_text("not json {{{")
        # Falls through to directory name
        result = infer_project_name(tmp_path)
        assert isinstance(result, str)

    def test_from_go_mod(self, tmp_path):
        (tmp_path / "go.mod").write_text("module github.com/user/my-project\n\ngo 1.21\n")
        assert infer_project_name(tmp_path) == "My Project"

    def test_from_go_mod_simple_module(self, tmp_path):
        (tmp_path / "go.mod").write_text("module myapp\n")
        assert infer_project_name(tmp_path) == "Myapp"

    def test_fallback_to_directory_name(self, tmp_path):
        result = infer_project_name(tmp_path)
        # tmp_path has a generated name, but it should be titlecased
        assert isinstance(result, str)
        assert len(result) > 0

    def test_directory_name_dashes_to_spaces(self, tmp_path):
        project_dir = tmp_path / "my-awesome-project"
        project_dir.mkdir()
        assert infer_project_name(project_dir) == "My Awesome Project"

    def test_directory_name_underscores_to_spaces(self, tmp_path):
        project_dir = tmp_path / "my_awesome_project"
        project_dir.mkdir()
        assert infer_project_name(project_dir) == "My Awesome Project"

    def test_priority_package_json_over_go_mod(self, tmp_path):
        (tmp_path / "package.json").write_text(json.dumps({"name": "node-app"}))
        (tmp_path / "go.mod").write_text("module github.com/user/go-app\n")
        assert infer_project_name(tmp_path) == "Node App"


class TestFromPackageJson:
    def test_returns_none_when_missing(self, tmp_path):
        assert _from_package_json(tmp_path) is None

    def test_returns_none_for_empty_json(self, tmp_path):
        (tmp_path / "package.json").write_text("{}")
        assert _from_package_json(tmp_path) is None


class TestFromPyproject:
    def test_returns_none_when_missing(self, tmp_path):
        assert _from_pyproject(tmp_path) is None

    @pytest.mark.skipif(sys.version_info < (3, 11), reason="tomllib requires Python 3.11+")
    def test_reads_project_name(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "my-python-lib"\n'
        )
        assert _from_pyproject(tmp_path) == "My Python Lib"

    @pytest.mark.skipif(sys.version_info < (3, 11), reason="tomllib requires Python 3.11+")
    def test_reads_poetry_name(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text(
            '[tool.poetry]\nname = "poetry-project"\n'
        )
        assert _from_pyproject(tmp_path) == "Poetry Project"


class TestFromCargo:
    def test_returns_none_when_missing(self, tmp_path):
        assert _from_cargo(tmp_path) is None

    @pytest.mark.skipif(sys.version_info < (3, 11), reason="tomllib requires Python 3.11+")
    def test_reads_package_name(self, tmp_path):
        (tmp_path / "Cargo.toml").write_text(
            '[package]\nname = "rust-cli"\nversion = "0.1.0"\n'
        )
        assert _from_cargo(tmp_path) == "Rust Cli"


class TestFromGoMod:
    def test_returns_none_when_missing(self, tmp_path):
        assert _from_go_mod(tmp_path) is None

    def test_extracts_last_segment(self, tmp_path):
        (tmp_path / "go.mod").write_text("module github.com/org/my-service\n")
        assert _from_go_mod(tmp_path) == "My Service"


# ============================================================================
# copy_and_replace
# ============================================================================

class TestCopyAndReplace:
    def test_replaces_placeholder(self, tmp_path):
        source = tmp_path / "template.md"
        source.write_text("# [Project] Guide\n\nWelcome to [Project].")
        dest = tmp_path / "output" / "guide.md"

        copy_and_replace(source, dest, {"[Project]": "My App"})

        result = dest.read_text()
        assert result == "# My App Guide\n\nWelcome to My App."

    def test_creates_parent_dirs(self, tmp_path):
        source = tmp_path / "src.txt"
        source.write_text("content")
        dest = tmp_path / "a" / "b" / "c" / "file.txt"

        copy_and_replace(source, dest, {})

        assert dest.exists()
        assert dest.read_text() == "content"

    def test_multiple_replacements(self, tmp_path):
        source = tmp_path / "tmpl.txt"
        source.write_text("[Name] uses [Lang]")
        dest = tmp_path / "out.txt"

        copy_and_replace(source, dest, {"[Name]": "MyApp", "[Lang]": "Python"})

        assert dest.read_text() == "MyApp uses Python"

    def test_no_replacements(self, tmp_path):
        source = tmp_path / "tmpl.txt"
        source.write_text("unchanged content")
        dest = tmp_path / "out.txt"

        copy_and_replace(source, dest, {})

        assert dest.read_text() == "unchanged content"


# ============================================================================
# setup_gitignore
# ============================================================================

class TestSetupGitignore:
    def test_creates_gitignore_when_missing(self, tmp_path, capsys):
        setup_gitignore(tmp_path)

        gitignore = tmp_path / ".gitignore"
        assert gitignore.exists()
        content = gitignore.read_text()
        assert ".worktrees/" in content
        assert "/issues.jsonl" in content

    def test_does_not_ignore_whole_beads_dir(self, tmp_path, capsys):
        """The tracker travels with the repo — .beads/ must NOT be ignored
        (that would hide the canonical .beads/issues.jsonl)."""
        setup_gitignore(tmp_path)

        lines = (tmp_path / ".gitignore").read_text().splitlines()
        assert ".beads/" not in lines
        assert ".beads" not in lines

    def test_ignores_root_issues_jsonl(self, tmp_path, capsys):
        """A stray /issues.jsonl export at repo root must be ignored."""
        setup_gitignore(tmp_path)

        content = (tmp_path / ".gitignore").read_text()
        assert "/issues.jsonl" in content

    def test_appends_missing_entries(self, tmp_path, capsys):
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text("node_modules/\n.env\n")

        setup_gitignore(tmp_path)

        content = gitignore.read_text()
        assert "node_modules/" in content
        assert ".env" in content
        assert ".worktrees/" in content
        assert "/issues.jsonl" in content

    def test_skips_when_already_configured(self, tmp_path, capsys):
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text(
            "node_modules/\n.worktrees/\n.claude/.upgrades/\n/issues.jsonl\n"
        )

        setup_gitignore(tmp_path)

        content = gitignore.read_text()
        # Should not duplicate entries
        assert content.count(".worktrees/") == 1
        assert content.count("/issues.jsonl") == 1

    def test_adds_newline_if_missing(self, tmp_path, capsys):
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text("node_modules/")  # no trailing newline

        setup_gitignore(tmp_path)

        content = gitignore.read_text()
        assert ".worktrees/" in content
        # Should have added a newline before the section
        assert "node_modules/\n" in content

    def test_idempotent_no_duplicates(self, tmp_path, capsys):
        """Running setup_gitignore twice must not duplicate any entry."""
        setup_gitignore(tmp_path)
        setup_gitignore(tmp_path)

        content = (tmp_path / ".gitignore").read_text()
        assert content.count(".worktrees/") == 1
        assert content.count("/issues.jsonl") == 1
        assert content.count(".claude/.upgrades/") == 1

    def test_detects_entries_without_trailing_slash(self, tmp_path, capsys):
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text(".worktrees\n.claude/.upgrades\n/issues.jsonl\n")

        setup_gitignore(tmp_path)

        content = gitignore.read_text()
        # Should detect ".worktrees" matches ".worktrees/" and not add duplicate
        assert content.count(".worktrees") == 1

    def test_adds_upgrades_entry_on_first_run(self, tmp_path, capsys):
        """setup_gitignore writes .claude/.upgrades/ when it's missing."""
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text("node_modules/\n")

        setup_gitignore(tmp_path)

        content = gitignore.read_text()
        assert ".claude/.upgrades/" in content

    def test_upgrades_entry_not_duplicated_on_rerun(self, tmp_path, capsys):
        """Running setup_gitignore twice must not duplicate .claude/.upgrades/."""
        setup_gitignore(tmp_path)
        setup_gitignore(tmp_path)

        content = (tmp_path / ".gitignore").read_text()
        assert content.count(".claude/.upgrades/") == 1


# ============================================================================
# configure_beads_export
# ============================================================================

class TestConfigureBeadsExport:
    def test_runs_bd_config_set_git_add_false(self, tmp_path, monkeypatch, capsys):
        """Should call `bd config set export.git-add false` in the project dir."""
        calls = []

        class FakeResult:
            returncode = 0
            stdout = ""
            stderr = ""

        def fake_run(cmd, **kwargs):
            calls.append((cmd, kwargs.get("cwd")))
            return FakeResult()

        monkeypatch.setattr(bootstrap.subprocess, "run", fake_run)
        monkeypatch.setattr(bootstrap.shutil, "which", lambda _: "/usr/bin/bd")

        result = configure_beads_export(tmp_path)

        assert result is True
        assert calls == [
            (["bd", "config", "set", "export.git-add", "false"], tmp_path)
        ]

    def test_returns_false_when_bd_missing(self, tmp_path, monkeypatch, capsys):
        """If bd is not on PATH, do not crash — return False."""
        monkeypatch.setattr(bootstrap.shutil, "which", lambda _: None)

        result = configure_beads_export(tmp_path)

        assert result is False

    def test_does_not_raise_on_nonzero_exit(self, tmp_path, monkeypatch, capsys):
        """A failing bd config must not raise — log and return False."""
        class FakeResult:
            returncode = 1
            stdout = ""
            stderr = "boom"

        monkeypatch.setattr(bootstrap.subprocess, "run", lambda *a, **k: FakeResult())
        monkeypatch.setattr(bootstrap.shutil, "which", lambda _: "/usr/bin/bd")

        result = configure_beads_export(tmp_path)

        assert result is False

    def test_does_not_raise_on_timeout(self, tmp_path, monkeypatch, capsys):
        """A timeout must not raise — log and return False."""
        def fake_run(*a, **k):
            raise bootstrap.subprocess.TimeoutExpired(cmd="bd", timeout=15)

        monkeypatch.setattr(bootstrap.subprocess, "run", fake_run)
        monkeypatch.setattr(bootstrap.shutil, "which", lambda _: "/usr/bin/bd")

        result = configure_beads_export(tmp_path)

        assert result is False


# ============================================================================
# Templates directory
# ============================================================================

class TestTemplatesDir:
    def test_templates_dir_exists(self):
        assert TEMPLATES_DIR.exists(), f"Templates dir not found: {TEMPLATES_DIR}"

    def test_has_hooks(self):
        """The shared library plus at least one hook. The exact set is pinned
        against settings.json in TestHookCommandShape, so no count lives here."""
        hooks_dir = TEMPLATES_DIR / "hooks"
        assert hooks_dir.exists()
        assert (hooks_dir / "hook-utils.cjs").exists()
        assert {f.name for f in hooks_dir.glob("*.cjs")} - {"hook-utils.cjs"}

    def test_has_agents(self):
        agents_dir = TEMPLATES_DIR / "agents"
        assert agents_dir.exists()
        agents = list(agents_dir.glob("*.md"))
        assert len(agents) >= 2  # code-reviewer + merge-supervisor

    def test_has_settings_json(self):
        assert (TEMPLATES_DIR / "settings.json").exists()

    def test_has_claude_md(self):
        assert (TEMPLATES_DIR / "CLAUDE.md").exists()

    def test_has_beads_workflow_rule(self):
        assert (TEMPLATES_DIR / "rules" / "beads-workflow.md").exists()


# ============================================================================
# Manifest functions
# ============================================================================

class TestFileSha256:
    def test_returns_sha256_prefixed_hash(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("hello world")
        result = file_sha256(f)
        assert result.startswith("sha256:")
        assert len(result) == 7 + 64  # "sha256:" + 64 hex chars

    def test_same_content_same_hash(self, tmp_path):
        f1 = tmp_path / "a.txt"
        f2 = tmp_path / "b.txt"
        f1.write_text("identical")
        f2.write_text("identical")
        assert file_sha256(f1) == file_sha256(f2)

    def test_different_content_different_hash(self, tmp_path):
        f1 = tmp_path / "a.txt"
        f2 = tmp_path / "b.txt"
        f1.write_text("content A")
        f2.write_text("content B")
        assert file_sha256(f1) != file_sha256(f2)


class TestContentSha256:
    def test_matches_file_sha256(self, tmp_path):
        text = "hello world"
        f = tmp_path / "test.txt"
        f.write_text(text, encoding="utf-8")
        assert content_sha256(text) == file_sha256(f)


class TestLoadManifest:
    def test_returns_empty_when_no_manifest(self, tmp_path):
        m = load_manifest(tmp_path)
        assert m["version"] is None
        assert m["files"] == {}

    def test_reads_existing_manifest(self, tmp_path):
        manifest_dir = tmp_path / ".claude"
        manifest_dir.mkdir()
        data = {"version": "3.1.0", "installed_at": "2026-01-01", "files": {"a": "sha256:abc"}}
        (manifest_dir / ".manifest.json").write_text(json.dumps(data))
        m = load_manifest(tmp_path)
        assert m["version"] == "3.1.0"
        assert m["files"]["a"] == "sha256:abc"

    def test_returns_empty_on_corrupt_json(self, tmp_path):
        manifest_dir = tmp_path / ".claude"
        manifest_dir.mkdir()
        (manifest_dir / ".manifest.json").write_text("not json {{{")
        m = load_manifest(tmp_path)
        assert m["files"] == {}


class TestSaveManifest:
    def test_creates_manifest_file(self, tmp_path):
        data = {"version": "3.2.0", "installed_at": "now", "files": {"x": "sha256:123"}}
        save_manifest(tmp_path, data)
        path = tmp_path / ".claude" / ".manifest.json"
        assert path.exists()
        loaded = json.loads(path.read_text())
        assert loaded["version"] == "3.2.0"
        assert loaded["files"]["x"] == "sha256:123"

    def test_overwrites_existing_manifest(self, tmp_path):
        save_manifest(tmp_path, {"version": "1", "installed_at": "", "files": {}})
        save_manifest(tmp_path, {"version": "2", "installed_at": "", "files": {"a": "b"}})
        loaded = json.loads((tmp_path / ".claude" / ".manifest.json").read_text())
        assert loaded["version"] == "2"


class TestShouldUpdateFile:
    def test_new_file(self, tmp_path):
        f = tmp_path / "new.md"
        ok, reason = should_update_file(f, "rules/new.md", {"files": {}}, False)
        assert ok is True
        assert reason == "new"

    def test_unchanged_file(self, tmp_path):
        f = tmp_path / "rule.md"
        f.write_text("original content", encoding="utf-8")
        h = file_sha256(f)
        manifest = {"files": {"rules/rule.md": h}}
        ok, reason = should_update_file(f, "rules/rule.md", manifest, False)
        assert ok is True
        assert reason == "unchanged"

    def test_modified_file(self, tmp_path):
        f = tmp_path / "rule.md"
        f.write_text("original content", encoding="utf-8")
        h = file_sha256(f)
        manifest = {"files": {"rules/rule.md": h}}
        # User modifies the file
        f.write_text("user modified content", encoding="utf-8")
        ok, reason = should_update_file(f, "rules/rule.md", manifest, False)
        assert ok is False
        assert reason == "modified"

    def test_force_overrides_modified(self, tmp_path):
        f = tmp_path / "rule.md"
        f.write_text("user modified", encoding="utf-8")
        manifest = {"files": {"rules/rule.md": "sha256:old"}}
        ok, reason = should_update_file(f, "rules/rule.md", manifest, True)
        assert ok is True
        assert reason == "forced"

    def test_legacy_install_no_manifest_entry(self, tmp_path):
        f = tmp_path / "rule.md"
        f.write_text("some content", encoding="utf-8")
        manifest = {"files": {}}
        ok, reason = should_update_file(f, "rules/rule.md", manifest, False)
        assert ok is False
        assert reason == "no_manifest"

    def test_force_overrides_legacy(self, tmp_path):
        f = tmp_path / "rule.md"
        f.write_text("some content", encoding="utf-8")
        manifest = {"files": {}}
        ok, reason = should_update_file(f, "rules/rule.md", manifest, True)
        assert ok is True
        assert reason == "forced"


class TestSaveUpgrade:
    def test_saves_to_upgrades_dir(self, tmp_path):
        save_upgrade(tmp_path, "rules/beads-workflow.md", "new content")
        dest = tmp_path / ".claude" / ".upgrades" / "rules" / "beads-workflow.md"
        assert dest.exists()
        assert dest.read_text() == "new content"

    def test_creates_nested_dirs(self, tmp_path):
        save_upgrade(tmp_path, "agents/code-reviewer.md", "v2 content")
        dest = tmp_path / ".claude" / ".upgrades" / "agents" / "code-reviewer.md"
        assert dest.exists()


# ============================================================================
# cleanup_obsolete
# ============================================================================

class TestCleanupObsolete:
    def test_empty_lists_noop(self, tmp_path, monkeypatch):
        """Empty OBSOLETE_* lists → empty report, no backup dir, no changes."""
        monkeypatch.setattr(bootstrap, "OBSOLETE_FILES", [])
        monkeypatch.setattr(bootstrap, "OBSOLETE_DIRS", [])
        monkeypatch.setattr(bootstrap, "OBSOLETE_SETTINGS_HOOKS", [])
        monkeypatch.setattr(bootstrap, "OBSOLETE_LOCAL_SETTINGS_PATTERNS", [])

        (tmp_path / "foo.txt").write_text("hello")
        manifest = {"files": {"foo.txt": "sha256:abc"}}

        report = cleanup_obsolete(tmp_path, manifest, dry_run=False)

        assert report["removed_files"] == []
        assert report["removed_dirs"] == []
        assert report["stripped_settings_hooks"] == []
        assert report["stripped_local_patterns"] == []
        assert report["backups"][0] is None
        assert not (tmp_path / ".claude" / ".upgrades").exists()
        # File untouched, manifest untouched
        assert (tmp_path / "foo.txt").exists()
        assert manifest["files"] == {"foo.txt": "sha256:abc"}

    def test_removes_manifest_file(self, tmp_path, monkeypatch):
        """File in OBSOLETE_FILES + manifest → removed and backed up."""
        monkeypatch.setattr(bootstrap, "OBSOLETE_FILES", ["foo.txt"])
        monkeypatch.setattr(bootstrap, "OBSOLETE_DIRS", [])
        monkeypatch.setattr(bootstrap, "OBSOLETE_SETTINGS_HOOKS", [])
        monkeypatch.setattr(bootstrap, "OBSOLETE_LOCAL_SETTINGS_PATTERNS", [])

        target = tmp_path / "foo.txt"
        target.write_text("obsolete content")
        manifest = {"files": {"foo.txt": "sha256:abc"}}

        report = cleanup_obsolete(tmp_path, manifest, dry_run=False)

        assert "foo.txt" in report["removed_files"]
        assert not target.exists()
        assert "foo.txt" not in manifest["files"]
        # Backup exists
        backup_root = Path(report["backups"][0])
        assert backup_root.exists()
        backup_file = backup_root / "obsolete" / "foo.txt"
        assert backup_file.exists()
        assert backup_file.read_text() == "obsolete content"

    def test_skips_non_manifest_file(self, tmp_path, monkeypatch):
        """A user file NOT listed in OBSOLETE_FILES and not in manifest → untouched.

        The safety guarantee is: files not enumerated in OBSOLETE_FILES are never
        inspected. Auto-inject only fires on OBSOLETE_FILES entries; paths outside
        that list remain fully protected regardless of manifest state.
        """
        monkeypatch.setattr(bootstrap, "OBSOLETE_FILES", ["some/obsolete.txt"])
        monkeypatch.setattr(bootstrap, "OBSOLETE_DIRS", [])
        monkeypatch.setattr(bootstrap, "OBSOLETE_SETTINGS_HOOKS", [])
        monkeypatch.setattr(bootstrap, "OBSOLETE_LOCAL_SETTINGS_PATTERNS", [])

        # This file is NOT in OBSOLETE_FILES — cleanup must not even look at it.
        target = tmp_path / "user.txt"
        target.write_text("user file, not ours")
        manifest = {"files": {}}

        report = cleanup_obsolete(tmp_path, manifest, dry_run=False)

        assert report["removed_files"] == []
        assert target.exists()
        assert target.read_text() == "user file, not ours"
        assert not (tmp_path / ".claude" / ".upgrades").exists()

    def test_dry_run(self, tmp_path, monkeypatch):
        """dry_run=True → report populated, disk unchanged."""
        monkeypatch.setattr(bootstrap, "OBSOLETE_FILES", ["foo.txt"])
        monkeypatch.setattr(bootstrap, "OBSOLETE_DIRS", ["old_dir"])
        monkeypatch.setattr(bootstrap, "OBSOLETE_SETTINGS_HOOKS", [])
        monkeypatch.setattr(bootstrap, "OBSOLETE_LOCAL_SETTINGS_PATTERNS", [])

        (tmp_path / "foo.txt").write_text("obsolete")
        (tmp_path / "old_dir").mkdir()
        (tmp_path / "old_dir" / "nested.txt").write_text("data")
        manifest = {"files": {"foo.txt": "sha256:abc"}}

        report = cleanup_obsolete(tmp_path, manifest, dry_run=True)

        assert "foo.txt" in report["removed_files"]
        assert "old_dir" in report["removed_dirs"]
        assert report["backups"][0] is None
        # Nothing removed on disk
        assert (tmp_path / "foo.txt").exists()
        assert (tmp_path / "old_dir").exists()
        assert not (tmp_path / ".claude" / ".upgrades").exists()
        # Manifest unchanged
        assert manifest["files"] == {"foo.txt": "sha256:abc"}

    def test_strips_settings_hooks(self, tmp_path, monkeypatch):
        """Hook with matching command substring gets stripped, original backed up."""
        monkeypatch.setattr(bootstrap, "OBSOLETE_FILES", [])
        monkeypatch.setattr(bootstrap, "OBSOLETE_DIRS", [])
        monkeypatch.setattr(bootstrap, "OBSOLETE_SETTINGS_HOOKS", ["memory-capture.cjs"])
        monkeypatch.setattr(bootstrap, "OBSOLETE_LOCAL_SETTINGS_PATTERNS", [])

        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        settings = claude_dir / "settings.json"
        settings.write_text(json.dumps({
            "hooks": {
                "PostToolUse": [
                    {"matcher": "Bash", "hooks": [{"type": "command", "command": "node .claude/hooks/memory-capture.cjs"}]},
                    {"matcher": "Edit", "hooks": [{"type": "command", "command": "node .claude/hooks/keep.cjs"}]},
                ]
            }
        }))
        manifest = {"files": {}}

        report = cleanup_obsolete(tmp_path, manifest, dry_run=False)

        assert len(report["stripped_settings_hooks"]) == 1
        assert "memory-capture.cjs" in report["stripped_settings_hooks"][0]
        # Settings file updated
        updated = json.loads(settings.read_text())
        commands = [h["hooks"][0]["command"] for h in updated["hooks"]["PostToolUse"]]
        assert commands == ["node .claude/hooks/keep.cjs"]
        # Backup exists
        backup_root = Path(report["backups"][0])
        assert (backup_root / "obsolete" / "settings.json").exists()

    def test_removes_manifest_dir_with_nested_entries(self, tmp_path, monkeypatch):
        """Directory removal also strips matching manifest entries."""
        monkeypatch.setattr(bootstrap, "OBSOLETE_FILES", [])
        monkeypatch.setattr(bootstrap, "OBSOLETE_DIRS", [".beads/memory"])
        monkeypatch.setattr(bootstrap, "OBSOLETE_SETTINGS_HOOKS", [])
        monkeypatch.setattr(bootstrap, "OBSOLETE_LOCAL_SETTINGS_PATTERNS", [])

        mem_dir = tmp_path / ".beads" / "memory"
        mem_dir.mkdir(parents=True)
        (mem_dir / "knowledge.jsonl").write_text("")
        (mem_dir / "recall.cjs").write_text("// old")
        manifest = {"files": {".beads/memory/recall.cjs": "sha256:x", "other.md": "sha256:y"}}

        report = cleanup_obsolete(tmp_path, manifest, dry_run=False)

        assert ".beads/memory" in report["removed_dirs"]
        assert not mem_dir.exists()
        assert ".beads/memory/recall.cjs" not in manifest["files"]
        assert "other.md" in manifest["files"]

    def test_rejects_relative_traversal(self, tmp_path, monkeypatch, capsys):
        """OBSOLETE_FILES entry with ../ → skipped, external file untouched, no backup."""
        # project_dir must be a subdir of tmp_path so `../escape.txt` lands in tmp_path
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        external = tmp_path / "escape.txt"
        external.write_text("external content — do not touch")

        monkeypatch.setattr(bootstrap, "OBSOLETE_FILES", ["../escape.txt"])
        monkeypatch.setattr(bootstrap, "OBSOLETE_DIRS", [])
        monkeypatch.setattr(bootstrap, "OBSOLETE_SETTINGS_HOOKS", [])
        monkeypatch.setattr(bootstrap, "OBSOLETE_LOCAL_SETTINGS_PATTERNS", [])

        manifest = {"files": {"../escape.txt": "sha256:abc"}}

        try:
            report = cleanup_obsolete(project_dir, manifest, dry_run=False)

            assert report["removed_files"] == []
            # External file still exists, content unchanged
            assert external.exists()
            assert external.read_text() == "external content — do not touch"
            # Manifest entry not removed
            assert "../escape.txt" in manifest["files"]
            # No backup dir was created
            assert not (project_dir / ".claude" / ".upgrades").exists()
            # Warning printed
            out = capsys.readouterr().out
            assert "Skipping suspicious path" in out
        finally:
            if external.exists():
                external.unlink()

    def test_rejects_absolute_path_outside_project(self, tmp_path, monkeypatch, capsys):
        """OBSOLETE_FILES entry with absolute path outside project_dir → skipped."""
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        outside = tmp_path / "outside.txt"
        outside.write_text("outside content")

        monkeypatch.setattr(bootstrap, "OBSOLETE_FILES", [str(outside)])
        monkeypatch.setattr(bootstrap, "OBSOLETE_DIRS", [])
        monkeypatch.setattr(bootstrap, "OBSOLETE_SETTINGS_HOOKS", [])
        monkeypatch.setattr(bootstrap, "OBSOLETE_LOCAL_SETTINGS_PATTERNS", [])

        manifest = {"files": {str(outside): "sha256:abc"}}

        try:
            report = cleanup_obsolete(project_dir, manifest, dry_run=False)

            assert report["removed_files"] == []
            assert outside.exists()
            assert outside.read_text() == "outside content"
            assert str(outside) in manifest["files"]
            assert not (project_dir / ".claude" / ".upgrades").exists()
            out = capsys.readouterr().out
            assert "Skipping suspicious path" in out
        finally:
            if outside.exists():
                outside.unlink()

    def test_rejects_traversal_for_dirs(self, tmp_path, monkeypatch, capsys):
        """OBSOLETE_DIRS entry with ../ → skipped, external dir untouched, no backup."""
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        external_dir = tmp_path / "escape_dir"
        external_dir.mkdir()
        (external_dir / "nested.txt").write_text("nested")

        monkeypatch.setattr(bootstrap, "OBSOLETE_FILES", [])
        monkeypatch.setattr(bootstrap, "OBSOLETE_DIRS", ["../escape_dir"])
        monkeypatch.setattr(bootstrap, "OBSOLETE_SETTINGS_HOOKS", [])
        monkeypatch.setattr(bootstrap, "OBSOLETE_LOCAL_SETTINGS_PATTERNS", [])

        manifest = {"files": {}}

        try:
            report = cleanup_obsolete(project_dir, manifest, dry_run=False)

            assert report["removed_dirs"] == []
            # External dir + its contents untouched
            assert external_dir.exists()
            assert (external_dir / "nested.txt").exists()
            assert (external_dir / "nested.txt").read_text() == "nested"
            # No backup dir was created
            assert not (project_dir / ".claude" / ".upgrades").exists()
            out = capsys.readouterr().out
            assert "Skipping suspicious path" in out
        finally:
            if external_dir.exists():
                import shutil as _sh
                _sh.rmtree(external_dir)


    def test_clean_upgrade_leaves_no_empty_backup_folder(self, tmp_path, monkeypatch):
        """An upgrade with nothing to clean used to create an empty timestamped
        directory anyway, because the backup path was computed eagerly."""
        monkeypatch.setattr(bootstrap, "OBSOLETE_FILES", [])
        monkeypatch.setattr(bootstrap, "OBSOLETE_DIRS", [])
        monkeypatch.setattr(bootstrap, "OBSOLETE_SETTINGS_HOOKS", ["nothing-matches-this"])
        monkeypatch.setattr(bootstrap, "OBSOLETE_LOCAL_SETTINGS_PATTERNS", [])
        claude = tmp_path / ".claude"
        claude.mkdir()
        (claude / "settings.json").write_text(json.dumps({"hooks": {"PreToolUse": [
            {"matcher": "Bash", "hooks": [{"type": "command", "command": "node keep.cjs"}]}]}}),
            encoding="utf-8")

        report = cleanup_obsolete(tmp_path, {"files": {}}, dry_run=False)

        assert report["backups"] == [None]
        assert not (claude / ".upgrades").exists()

# ============================================================================
# bd-3 logic: legacy auto-inject, knowledge.jsonl guard, empty-settings cleanup
# ============================================================================

class TestBd3Logic:
    # --- _auto_inject_legacy_files --------------------------------------

    def test_auto_inject_legacy_files_adds_existing_unmanaged(self, tmp_path, monkeypatch):
        """File exists on disk, not in manifest → injected with sentinel hash.

        The injected key is .claude-relative, the same shape copy_hooks writes,
        so cleanup later removes the real entry instead of adding a second one.
        """
        monkeypatch.setattr(bootstrap, "OBSOLETE_FILES", [".claude/hooks/memory-capture.cjs"])
        target = tmp_path / ".claude" / "hooks" / "memory-capture.cjs"
        target.parent.mkdir(parents=True)
        target.write_text("// legacy")
        manifest = {"files": {}}

        injected = _auto_inject_legacy_files(tmp_path, manifest, dry_run=False)

        assert injected == [".claude/hooks/memory-capture.cjs"]
        assert manifest["files"]["hooks/memory-capture.cjs"] == "sha256:legacy-auto-injected"

    def test_auto_inject_legacy_files_skips_missing(self, tmp_path, monkeypatch):
        """Path not on disk → not injected."""
        monkeypatch.setattr(bootstrap, "OBSOLETE_FILES", [".claude/hooks/memory-capture.cjs"])
        manifest = {"files": {}}

        injected = _auto_inject_legacy_files(tmp_path, manifest, dry_run=False)

        assert injected == []
        assert manifest["files"] == {}

    def test_auto_inject_legacy_files_skips_already_in_manifest(self, tmp_path, monkeypatch):
        """Path already a manifest key → not touched."""
        monkeypatch.setattr(bootstrap, "OBSOLETE_FILES", [".claude/hooks/memory-capture.cjs"])
        target = tmp_path / ".claude" / "hooks" / "memory-capture.cjs"
        target.parent.mkdir(parents=True)
        target.write_text("// legacy")
        manifest = {"files": {".claude/hooks/memory-capture.cjs": "sha256:real-hash"}}

        injected = _auto_inject_legacy_files(tmp_path, manifest, dry_run=False)

        assert injected == []
        # Original hash preserved
        assert manifest["files"][".claude/hooks/memory-capture.cjs"] == "sha256:real-hash"

    def test_auto_inject_dry_run_does_not_mutate(self, tmp_path, monkeypatch):
        """dry_run=True → manifest unchanged, but result still reports what would be injected."""
        monkeypatch.setattr(bootstrap, "OBSOLETE_FILES", [".claude/hooks/memory-capture.cjs"])
        target = tmp_path / ".claude" / "hooks" / "memory-capture.cjs"
        target.parent.mkdir(parents=True)
        target.write_text("// legacy")
        manifest = {"files": {}}

        injected = _auto_inject_legacy_files(tmp_path, manifest, dry_run=True)

        assert injected == [".claude/hooks/memory-capture.cjs"]
        assert manifest["files"] == {}

    # --- _memory_dir_should_skip ----------------------------------------

    def test_memory_dir_skipped_if_knowledge_nonempty(self, tmp_path, monkeypatch):
        """Non-empty knowledge.jsonl → .beads/memory preserved, report.skipped_dirs populated."""
        monkeypatch.setattr(bootstrap, "OBSOLETE_FILES", [])
        monkeypatch.setattr(bootstrap, "OBSOLETE_DIRS", [".beads/memory"])
        monkeypatch.setattr(bootstrap, "OBSOLETE_SETTINGS_HOOKS", [])
        monkeypatch.setattr(bootstrap, "OBSOLETE_LOCAL_SETTINGS_PATTERNS", [])

        mem_dir = tmp_path / ".beads" / "memory"
        mem_dir.mkdir(parents=True)
        (mem_dir / "knowledge.jsonl").write_text("data\n")
        manifest = {"files": {}}

        report = cleanup_obsolete(tmp_path, manifest, dry_run=False)

        assert mem_dir.exists()
        assert (mem_dir / "knowledge.jsonl").exists()
        assert report["removed_dirs"] == []
        assert len(report["skipped_dirs"]) == 1
        rel, reason = report["skipped_dirs"][0]
        assert rel == ".beads/memory"
        assert "knowledge.jsonl" in reason

    def test_memory_dir_removed_if_knowledge_empty(self, tmp_path, monkeypatch):
        """Empty (0-byte) knowledge.jsonl → dir removed normally."""
        monkeypatch.setattr(bootstrap, "OBSOLETE_FILES", [])
        monkeypatch.setattr(bootstrap, "OBSOLETE_DIRS", [".beads/memory"])
        monkeypatch.setattr(bootstrap, "OBSOLETE_SETTINGS_HOOKS", [])
        monkeypatch.setattr(bootstrap, "OBSOLETE_LOCAL_SETTINGS_PATTERNS", [])

        mem_dir = tmp_path / ".beads" / "memory"
        mem_dir.mkdir(parents=True)
        (mem_dir / "knowledge.jsonl").write_text("")
        manifest = {"files": {}}

        report = cleanup_obsolete(tmp_path, manifest, dry_run=False)

        assert not mem_dir.exists()
        assert ".beads/memory" in report["removed_dirs"]
        assert report["skipped_dirs"] == []

    def test_memory_dir_removed_if_knowledge_missing(self, tmp_path, monkeypatch):
        """No knowledge.jsonl at all → dir removed normally."""
        monkeypatch.setattr(bootstrap, "OBSOLETE_FILES", [])
        monkeypatch.setattr(bootstrap, "OBSOLETE_DIRS", [".beads/memory"])
        monkeypatch.setattr(bootstrap, "OBSOLETE_SETTINGS_HOOKS", [])
        monkeypatch.setattr(bootstrap, "OBSOLETE_LOCAL_SETTINGS_PATTERNS", [])

        mem_dir = tmp_path / ".beads" / "memory"
        mem_dir.mkdir(parents=True)
        (mem_dir / "filler.cjs").write_text("// other")
        manifest = {"files": {}}

        report = cleanup_obsolete(tmp_path, manifest, dry_run=False)

        assert not mem_dir.exists()
        assert ".beads/memory" in report["removed_dirs"]
        assert report["skipped_dirs"] == []

    # --- _cleanup_empty_local_settings ----------------------------------

    def test_cleanup_empty_local_settings_removes_file(self, tmp_path, monkeypatch):
        """settings.local.json with only empty hook lists → file deleted."""
        monkeypatch.setattr(bootstrap, "OBSOLETE_FILES", [])
        monkeypatch.setattr(bootstrap, "OBSOLETE_DIRS", [])
        monkeypatch.setattr(bootstrap, "OBSOLETE_SETTINGS_HOOKS", [])
        monkeypatch.setattr(bootstrap, "OBSOLETE_LOCAL_SETTINGS_PATTERNS", [])

        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        settings = claude_dir / "settings.local.json"
        settings.write_text(json.dumps({"hooks": {"SessionStart": []}}))
        manifest = {"files": {}}

        report = cleanup_obsolete(tmp_path, manifest, dry_run=False)

        assert not settings.exists()
        assert report["removed_local_settings"] is True
        # Backup was made
        backup_root = Path(report["backups"][0])
        assert (backup_root / "obsolete" / ".claude" / "settings.local.json").exists()

    def test_cleanup_empty_local_settings_keeps_if_other_hooks(self, tmp_path, monkeypatch):
        """settings.local.json still has real hook entries → file kept."""
        monkeypatch.setattr(bootstrap, "OBSOLETE_FILES", [])
        monkeypatch.setattr(bootstrap, "OBSOLETE_DIRS", [])
        monkeypatch.setattr(bootstrap, "OBSOLETE_SETTINGS_HOOKS", [])
        monkeypatch.setattr(bootstrap, "OBSOLETE_LOCAL_SETTINGS_PATTERNS", [])

        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        settings = claude_dir / "settings.local.json"
        settings.write_text(json.dumps({
            "hooks": {
                "SessionStart": [
                    {"matcher": "*", "hooks": [{"type": "command", "command": "echo hi"}]},
                ]
            }
        }))
        manifest = {"files": {}}

        report = cleanup_obsolete(tmp_path, manifest, dry_run=False)

        assert settings.exists()
        assert report["removed_local_settings"] is False

    def test_cleanup_empty_local_settings_dry_run(self, tmp_path, monkeypatch):
        """dry_run=True → report says True but file untouched."""
        monkeypatch.setattr(bootstrap, "OBSOLETE_FILES", [])
        monkeypatch.setattr(bootstrap, "OBSOLETE_DIRS", [])
        monkeypatch.setattr(bootstrap, "OBSOLETE_SETTINGS_HOOKS", [])
        monkeypatch.setattr(bootstrap, "OBSOLETE_LOCAL_SETTINGS_PATTERNS", [])

        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        settings = claude_dir / "settings.local.json"
        settings.write_text(json.dumps({"hooks": {"SessionStart": []}}))
        manifest = {"files": {}}

        report = cleanup_obsolete(tmp_path, manifest, dry_run=True)

        assert settings.exists()
        assert report["removed_local_settings"] is True

    def test_cleanup_empty_local_settings_missing_file(self, tmp_path):
        """File absent → no-op, helper returns False."""
        result = _cleanup_empty_local_settings(
            tmp_path, lambda: tmp_path / ".bk", dry_run=False,
        )
        assert result is False


# ============================================================================
# main() flags: --upgrade, --all
# ============================================================================

class TestUpgradeFlag:
    def test_upgrade_flag_calls_cleanup(self, tmp_path, monkeypatch):
        """main() with --upgrade invokes cleanup_obsolete when manifest exists."""
        # Seed manifest so upgrade path runs
        save_manifest(tmp_path, {"version": "3.0.0", "installed_at": "t", "files": {}})

        calls = []

        def fake_cleanup(project_dir, manifest, dry_run):
            calls.append({"project_dir": project_dir, "dry_run": dry_run})
            return {
                "removed_files": [], "removed_dirs": [],
                "stripped_settings_hooks": [], "stripped_local_patterns": [],
                "backups": [None],
            }

        # Stub out heavy steps so test stays fast & offline
        monkeypatch.setattr(bootstrap, "cleanup_obsolete", fake_cleanup)
        monkeypatch.setattr(bootstrap, "install_beads", lambda pd: True)
        monkeypatch.setattr(bootstrap, "copy_agents", lambda *a, **kw: [])
        monkeypatch.setattr(bootstrap, "copy_hooks", lambda *a, **kw: None)
        monkeypatch.setattr(bootstrap, "copy_rules_and_skills", lambda *a, **kw: [])
        monkeypatch.setattr(bootstrap, "copy_settings_and_claude_md", lambda *a, **kw: None)
        monkeypatch.setattr(bootstrap, "setup_gitignore", lambda *a, **kw: None)
        monkeypatch.setattr(bootstrap, "run_bd_doctor", lambda *a, **kw: None)

        monkeypatch.setattr(sys, "argv", ["bootstrap.py", "--project-dir", str(tmp_path), "--upgrade"])
        with pytest.raises(SystemExit) as exc:
            bootstrap.main()
        assert exc.value.code == 0
        assert len(calls) == 1
        assert calls[0]["dry_run"] is False

    def test_upgrade_runs_cleanup_without_manifest(self, tmp_path, monkeypatch):
        """--upgrade must still run cleanup_obsolete for legacy installs (no
        manifest). _auto_inject_legacy_files handles the no-manifest case;
        skipping cleanup would leave pre-manifest OBSOLETE_* files on disk."""
        calls = []

        def fake_cleanup(*args, **kw):
            calls.append(args)
            return {
                "removed_files": [], "removed_dirs": [],
                "stripped_settings_hooks": [], "stripped_local_patterns": [],
                "backups": [None],
            }

        monkeypatch.setattr(bootstrap, "cleanup_obsolete", fake_cleanup)
        monkeypatch.setattr(bootstrap, "install_beads", lambda pd: True)
        monkeypatch.setattr(bootstrap, "copy_agents", lambda *a, **kw: [])
        monkeypatch.setattr(bootstrap, "copy_hooks", lambda *a, **kw: None)
        monkeypatch.setattr(bootstrap, "copy_rules_and_skills", lambda *a, **kw: [])
        monkeypatch.setattr(bootstrap, "copy_settings_and_claude_md", lambda *a, **kw: None)
        monkeypatch.setattr(bootstrap, "setup_gitignore", lambda *a, **kw: None)
        monkeypatch.setattr(bootstrap, "run_bd_doctor", lambda *a, **kw: None)

        monkeypatch.setattr(sys, "argv", ["bootstrap.py", "--project-dir", str(tmp_path), "--upgrade"])
        with pytest.raises(SystemExit) as exc:
            bootstrap.main()
        assert exc.value.code == 0
        assert len(calls) == 1


class TestAllFlag:
    def test_iterates_subdirs_with_beads(self, tmp_path, monkeypatch):
        """--all <parent> processes direct subdirs containing .beads/, skips others."""
        parent = tmp_path / "workspace"
        parent.mkdir()
        good1 = parent / "proj_a"
        good1.mkdir()
        (good1 / ".beads").mkdir()
        good2 = parent / "proj_b"
        good2.mkdir()
        (good2 / ".beads").mkdir()
        bad = parent / "proj_c"
        bad.mkdir()  # no .beads/
        # file (not a directory) — must not break iteration
        (parent / "stray.txt").write_text("")

        processed: list = []

        def fake_bootstrap_project(**kwargs):
            processed.append(kwargs["project_dir"])
            return 0

        monkeypatch.setattr(bootstrap, "bootstrap_project", fake_bootstrap_project)

        monkeypatch.setattr(sys, "argv", ["bootstrap.py", "--all", str(parent)])
        with pytest.raises(SystemExit) as exc:
            bootstrap.main()
        assert exc.value.code == 0
        names = sorted(p.name for p in processed)
        assert names == ["proj_a", "proj_b"]

    def test_missing_parent_dir_fails_cleanly(self, tmp_path, monkeypatch):
        """--all with a non-existent parent returns exit 1."""
        missing = tmp_path / "does_not_exist"
        monkeypatch.setattr(sys, "argv", ["bootstrap.py", "--all", str(missing)])
        with pytest.raises(SystemExit) as exc:
            bootstrap.main()
        assert exc.value.code == 1


class TestBdDoctorSoftFailure:
    def test_missing_bd_is_soft_failure(self, tmp_path, monkeypatch, capsys):
        """bd not on PATH → prints warning, does not raise."""
        monkeypatch.setattr(bootstrap.shutil, "which", lambda name: None)
        # Must not raise
        run_bd_doctor(tmp_path)
        out = capsys.readouterr().out
        assert "bd doctor unavailable" in out

    def test_nonzero_exit_is_soft_failure(self, tmp_path, monkeypatch, capsys):
        """bd doctor returning non-zero → prints warning, does not raise."""
        monkeypatch.setattr(bootstrap.shutil, "which", lambda name: "/usr/bin/bd")

        class FakeResult:
            returncode = 2
            stdout = ""
            stderr = "no dolt server\n"

        monkeypatch.setattr(
            bootstrap.subprocess, "run",
            lambda *a, **kw: FakeResult(),
        )
        run_bd_doctor(tmp_path)
        out = capsys.readouterr().out
        assert "bd doctor unavailable" in out

    def test_timeout_is_soft_failure(self, tmp_path, monkeypatch, capsys):
        """bd doctor timeout → prints warning, does not raise."""
        monkeypatch.setattr(bootstrap.shutil, "which", lambda name: "/usr/bin/bd")

        def fake_run(*a, **kw):
            raise bootstrap.subprocess.TimeoutExpired(cmd="bd", timeout=15)

        monkeypatch.setattr(bootstrap.subprocess, "run", fake_run)
        run_bd_doctor(tmp_path)
        out = capsys.readouterr().out
        assert "bd doctor unavailable" in out

    def test_success_prints_first_lines(self, tmp_path, monkeypatch, capsys):
        """Successful bd doctor → first 20 lines of stdout printed under header."""
        monkeypatch.setattr(bootstrap.shutil, "which", lambda name: "/usr/bin/bd")

        class FakeResult:
            returncode = 0
            stdout = "\n".join(f"line {i}" for i in range(30))
            stderr = ""

        monkeypatch.setattr(
            bootstrap.subprocess, "run",
            lambda *a, **kw: FakeResult(),
        )
        run_bd_doctor(tmp_path)
        out = capsys.readouterr().out
        assert "bd doctor:" in out
        assert "line 0" in out
        assert "line 19" in out
        assert "line 20" not in out  # Truncated at 20

# ============================================================================
# Hook command paths (CLAUDE_PROJECT_DIR resolution)
# ============================================================================
# A hook process inherits the cwd of the last Bash tool call, so a relative
# command path breaks as soon as the agent works in a subdirectory or a
# worktree — and Claude Code reports that failure as non-blocking, i.e. the
# tool call proceeds with the hook silently absent. These tests pin the fix
# from both ends: the shape of the command we write, and the rewrite of stale
# commands on upgrade.

OLD_COMMAND_FORMS = [
    "node .claude/hooks/bash-guard.cjs",
    "node ./.claude/hooks/bash-guard.cjs",
    'node "$CLAUDE_PROJECT_DIR/.claude/hooks/bash-guard.cjs"',
    "node C:/repos/demo/.claude/hooks/bash-guard.cjs",
]


def _template_hooks():
    return json.loads(
        (TEMPLATES_DIR / "settings.json").read_text(encoding="utf-8")
    )["hooks"]


class TestHookCommandShape:
    def test_no_command_uses_a_relative_path(self):
        """Relative command paths are the bug — none may survive in the template."""
        for event, entries in _template_hooks().items():
            for entry in entries:
                cmd = entry["hooks"][0]["command"]
                assert "CLAUDE_PROJECT_DIR" in cmd, f"{event}: {cmd}"
                assert not cmd.startswith("node .claude"), f"{event}: {cmd}"
                assert not cmd.startswith("node ./"), f"{event}: {cmd}"

    def test_no_command_relies_on_shell_variable_expansion(self):
        """`$CLAUDE_PROJECT_DIR` is expanded by the shell, and hook commands run
        under PowerShell when Git Bash is absent — there it collapses to an
        empty string. The variable must be read inside Node instead."""
        for entries in _template_hooks().values():
            for entry in entries:
                cmd = entry["hooks"][0]["command"]
                assert "$CLAUDE_PROJECT_DIR" not in cmd
                assert "process.env.CLAUDE_PROJECT_DIR" in cmd

    def test_no_command_contains_a_raw_newline(self):
        """A newline inside the JS string literal turns the command into a
        syntax error — easy to introduce when escaping the JSON by hand."""
        for entries in _template_hooks().values():
            for entry in entries:
                assert chr(10) not in entry["hooks"][0]["command"]

    def test_canonical_map_covers_every_shipped_hook(self):
        """Every hook file we install needs a command; hook-utils is a shared
        library, not a hook."""
        shipped = {
            f.name for f in (TEMPLATES_DIR / "hooks").glob("*.cjs")
            if f.name != "hook-utils.cjs"
        }
        assert shipped == set(canonical_hook_commands())

    @pytest.mark.parametrize("cmd", OLD_COMMAND_FORMS)
    def test_hook_basename_recognises_old_forms(self, cmd):
        assert _hook_basename(cmd) == "bash-guard.cjs"

    def test_hook_basename_ignores_foreign_commands(self):
        assert _hook_basename("./scripts/my-own-hook.sh") == ""
        assert _hook_basename("") == ""

    def test_entry_key_separates_matchers(self):
        """Edit and Write carry the same command — keying on the command alone
        would drop one of the two entries."""
        spec = {"hooks": [{"type": "command", "command": "node x.cjs"}]}
        assert _entry_key(dict(spec, matcher="Edit")) != _entry_key(dict(spec, matcher="Write"))


class TestHookPathMigration:
    @pytest.mark.parametrize("cmd", OLD_COMMAND_FORMS)
    def test_rewrites_every_old_form(self, cmd):
        hooks = {"PreToolUse": [
            {"matcher": "Bash", "hooks": [{"type": "command", "command": cmd}]},
        ]}
        canonical = canonical_hook_commands()

        migrated = migrate_hook_commands(hooks, canonical)

        assert migrated == [(cmd, canonical["bash-guard.cjs"])]
        assert hooks["PreToolUse"][0]["hooks"][0]["command"] == canonical["bash-guard.cjs"]

    def test_leaves_a_user_hook_that_shares_our_file_name(self):
        """A user's own scripts/session-start.cjs is not ours to repoint —
        matching on the file name alone would hijack it."""
        own = "node scripts/session-start.cjs"
        hooks = {"SessionStart": [{"hooks": [
            {"type": "command", "command": own}]}]}

        assert migrate_hook_commands(hooks, canonical_hook_commands()) == []
        assert hooks["SessionStart"][0]["hooks"][0]["command"] == own

    def test_keeps_malformed_entries_instead_of_collapsing_them(self):
        existing = {"hooks": {"PreToolUse": ["broken-one", "broken-two"]}}
        merge_hooks(existing, _template_hooks())
        assert "broken-one" in existing["hooks"]["PreToolUse"]
        assert "broken-two" in existing["hooks"]["PreToolUse"]

    def test_leaves_a_user_own_hook_untouched(self):
        own = "node scripts/my-own-hook.cjs"
        hooks = {"PreToolUse": [
            {"matcher": "Bash", "hooks": [{"type": "command", "command": own}]},
        ]}

        assert migrate_hook_commands(hooks, canonical_hook_commands()) == []
        assert hooks["PreToolUse"][0]["hooks"][0]["command"] == own

    def test_rewrites_our_hook_under_an_unexpected_event(self):
        """An older install may have put our hook on a different event."""
        hooks = {"PostToolUse": [
            {"matcher": "Bash", "hooks": [
                {"type": "command", "command": "node .claude/hooks/session-start.cjs"}]},
        ]}

        migrated = migrate_hook_commands(hooks, canonical_hook_commands())

        assert len(migrated) == 1
        assert "CLAUDE_PROJECT_DIR" in hooks["PostToolUse"][0]["hooks"][0]["command"]

    def test_already_canonical_is_not_reported(self):
        canonical = canonical_hook_commands()
        hooks = {"PreToolUse": [
            {"matcher": "Bash", "hooks": [
                {"type": "command", "command": canonical["bash-guard.cjs"]}]},
        ]}
        assert migrate_hook_commands(hooks, canonical) == []

    def test_tolerates_malformed_entries(self):
        hooks = {"PreToolUse": ["not-a-dict", {}, {"hooks": []}], "Bogus": "not-a-list"}
        assert migrate_hook_commands(hooks, canonical_hook_commands()) == []


class TestMergeHooks:
    def test_upgrade_rewrites_instead_of_duplicating(self):
        """The upgrade trap: deduplicating by command string alone keeps the old
        relative entry and appends the new one, so the broken hook keeps firing
        next to the fixed one."""
        existing = {"hooks": {
            "PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command",
                            "command": "node .claude/hooks/bash-guard.cjs"}]}],
            "SessionStart": [{"hooks": [{"type": "command",
                              "command": "node .claude/hooks/session-start.cjs"}]}],
            "SubagentStop": [{"hooks": [{"type": "command",
                              "command": "node .claude/hooks/validate-completion.cjs"}]}],
        }}

        migrated = merge_hooks(existing, _template_hooks())

        assert len(migrated) == 3
        for event, entries in existing["hooks"].items():
            assert len(entries) == 1, f"{event} gained a duplicate entry"
            assert "CLAUDE_PROJECT_DIR" in entries[0]["hooks"][0]["command"]

    def test_keeps_one_command_registered_under_two_matchers(self):
        """Deduplicating on the command alone would drop one of the two."""
        spec = [{"type": "command", "command": "node scripts/mine.cjs"}]
        existing = {"hooks": {"PreToolUse": [
            {"matcher": "Edit", "hooks": spec},
            {"matcher": "Write", "hooks": spec},
        ]}}

        merge_hooks(existing, _template_hooks())

        matchers = [e.get("matcher") for e in existing["hooks"]["PreToolUse"]]
        assert matchers.count("Edit") == 1
        assert matchers.count("Write") == 1

    def test_merge_is_idempotent(self):
        template = _template_hooks()
        existing = {"hooks": {}}
        merge_hooks(existing, template)
        first = json.dumps(existing, sort_keys=True)

        merge_hooks(existing, template)

        assert json.dumps(existing, sort_keys=True) == first

    def test_preserves_foreign_hooks_and_other_settings(self):
        own = {"matcher": "Bash", "hooks": [{"type": "command", "command": "./my.sh"}]}
        existing = {"permissions": {"allow": ["Bash(ls)"]},
                    "hooks": {"PreToolUse": [own]}}

        merge_hooks(existing, _template_hooks())

        assert own in existing["hooks"]["PreToolUse"]
        assert existing["permissions"] == {"allow": ["Bash(ls)"]}

    def test_collapses_pre_existing_duplicates(self):
        dup = {"matcher": "Bash", "hooks": [{"type": "command",
               "command": "node .claude/hooks/bash-guard.cjs"}]}
        existing = {"hooks": {"PreToolUse": [dict(dup), dict(dup)]}}

        merge_hooks(existing, _template_hooks())

        bash_entries = [e for e in existing["hooks"]["PreToolUse"]
                        if e.get("matcher") == "Bash"]
        assert len(bash_entries) == 1

    def test_repairs_non_dict_hooks_section(self):
        existing = {"hooks": "broken"}
        merge_hooks(existing, _template_hooks())
        assert isinstance(existing["hooks"], dict)
        assert "PreToolUse" in existing["hooks"]


class TestMigrateLocalSettings:
    def test_rewrites_local_settings_and_keeps_the_rest(self, tmp_path):
        claude = tmp_path / ".claude"
        claude.mkdir()
        local = claude / "settings.local.json"
        local.write_text(json.dumps({
            "permissions": {"allow": ["Bash(ls)"]},
            "hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [
                {"type": "command", "command": "node .claude/hooks/bash-guard.cjs"}]}]},
        }), encoding="utf-8")

        migrated = migrate_local_settings_hooks(tmp_path)

        assert len(migrated) == 1
        data = json.loads(local.read_text(encoding="utf-8"))
        assert "CLAUDE_PROJECT_DIR" in data["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
        assert data["permissions"] == {"allow": ["Bash(ls)"]}

    def test_no_file_is_not_an_error(self, tmp_path):
        assert migrate_local_settings_hooks(tmp_path) == []

    def test_unreadable_file_is_not_an_error(self, tmp_path):
        claude = tmp_path / ".claude"
        claude.mkdir()
        (claude / "settings.local.json").write_text("{ not json", encoding="utf-8")
        assert migrate_local_settings_hooks(tmp_path) == []


class TestWrapperRunsFromAnyCwd:
    """The command string executed by the real platform shell.

    This is the test that would have caught the original bug: it runs the
    command from a subdirectory, which is exactly where the relative path
    failed while reporting success to the user.
    """

    def _probe_command(self, hook_name="probe.cjs"):
        canonical = canonical_hook_commands()["bash-guard.cjs"]
        return canonical.rsplit(" ", 1)[0] + " " + hook_name

    def _make_project(self, tmp_path):
        hooks = tmp_path / ".claude" / "hooks"
        hooks.mkdir(parents=True)
        (hooks / "probe.cjs").write_text(
            "process.stdout.write('PROBE_OK ' + process.cwd());", encoding="utf-8"
        )
        subdir = tmp_path / "packages" / "db"
        subdir.mkdir(parents=True)
        return subdir

    @pytest.mark.parametrize("where", ["root", "subdir"])
    def test_hook_is_found_from_root_and_from_subdirectory(self, tmp_path, where):
        if not shutil.which("node"):
            pytest.skip("node not available")
        subdir = self._make_project(tmp_path)
        cwd = tmp_path if where == "root" else subdir

        result = subprocess.run(
            self._probe_command(), cwd=cwd, shell=True,
            env=dict(os.environ, CLAUDE_PROJECT_DIR=str(tmp_path)),
            capture_output=True, text=True, timeout=60,
        )

        assert result.returncode == 0, result.stderr
        assert "PROBE_OK" in result.stdout, result.stderr

    def test_missing_hook_file_fails_open_with_one_line(self, tmp_path):
        """A stale entry must not print a Node stack trace: exit 0, and name the
        file that is missing."""
        if not shutil.which("node"):
            pytest.skip("node not available")
        subdir = self._make_project(tmp_path)

        result = subprocess.run(
            self._probe_command("not-installed.cjs"), cwd=subdir, shell=True,
            env=dict(os.environ, CLAUDE_PROJECT_DIR=str(tmp_path)),
            capture_output=True, text=True, timeout=60,
        )

        assert result.returncode == 0
        assert "hook not found" in result.stderr
        assert "Cannot find module" not in result.stderr


# ============================================================================
# Rule sets (en / ru)
# ============================================================================
# Rules are loaded into every session as project instructions, so drift between
# the two sets is invisible until someone reads the wrong language — and size
# is a permanent context cost paid by every user.

RULES_EN = TEMPLATES_DIR / "rules"
RULES_RU = TEMPLATES_DIR / "rules-ru"

# validate-completion.cjs matches these literally in a subagent's final report.
# A translation that localises them would block every completed task.
REPORT_MARKERS = ["BEAD {BEAD_ID} COMPLETE", "Checklist:"]


def _cyrillic(text):
    return [c for c in text if "Ѐ" <= c <= "ӿ"]


class TestRuleSets:
    def test_both_sets_hold_the_same_files(self):
        assert {f.name for f in RULES_EN.glob("*.md")} == {f.name for f in RULES_RU.glob("*.md")}

    def test_english_set_is_in_english(self):
        """communication-style once shipped an English rule demanding Russian
        prose, so English installs told the agent to answer in Russian."""
        for rule in RULES_EN.glob("*.md"):
            found = _cyrillic(rule.read_text(encoding="utf-8"))
            assert not found, f"{rule.name}: {len(found)} Cyrillic characters"

    def test_russian_set_is_in_russian(self):
        for rule in RULES_RU.glob("*.md"):
            assert _cyrillic(rule.read_text(encoding="utf-8")), f"{rule.name} is not translated"

    @pytest.mark.parametrize("rules_dir", [RULES_EN, RULES_RU], ids=["en", "ru"])
    def test_beads_workflow_keeps_the_report_format(self, rules_dir):
        """bootstrap installs the translated beads-workflow when one exists, so
        every translation must keep the strings the hook matches."""
        text = (rules_dir / "beads-workflow.md").read_text(encoding="utf-8")
        for marker in REPORT_MARKERS:
            assert marker in text, f"{rules_dir.name}/beads-workflow.md lost '{marker}'"

    @pytest.mark.parametrize("rules_dir", [RULES_EN, RULES_RU], ids=["en", "ru"])
    def test_every_rule_states_when_it_fires(self, rules_dir):
        """Rules are trigger-based: a rule with no trigger is a reference
        document, and reference documents belong in docs/, not in context."""
        for rule in rules_dir.glob("*.md"):
            text = (rule.read_text(encoding="utf-8")).lower()
            assert any(w in text for w in ("trigger", "триггер", "when", "когда")), rule.name

    def test_pre_code_workflow_defers_to_beads_workflow(self):
        """The gates end at the plan; sizing and bead creation live in
        beads-workflow.md. Restating them there would be a second copy."""
        for rules_dir in (RULES_EN, RULES_RU):
            text = (rules_dir / "pre-code-workflow.md").read_text(encoding="utf-8")
            assert "beads-workflow.md" in text

    def test_implementation_standard_defers_to_pre_code_workflow(self):
        """The 'process with user' section moved out; a pointer stays behind."""
        for rules_dir in (RULES_EN, RULES_RU):
            text = (rules_dir / "implementation-standard.md").read_text(encoding="utf-8")
            assert "pre-code-workflow.md" in text

    def test_rule_set_stays_within_its_context_budget(self):
        """A ceiling, not a target: rules are paid for on every single session,
        so growth has to be a deliberate decision, not a drift."""
        for rules_dir in (RULES_EN, RULES_RU):
            total = sum(len(f.read_text(encoding="utf-8")) for f in rules_dir.glob("*.md"))
            assert total < 20000, f"{rules_dir.name}: {total} characters"


# ============================================================================
# Upgrading an existing installation
# ============================================================================
# Measured against a synthetic v3.5.0 project: the gaps below all produced a
# half-migrated state that looked like a successful upgrade.


def _stub_heavy_steps(monkeypatch):
    """Everything that talks to the network, bd, or git."""
    monkeypatch.setattr(bootstrap, "install_beads", lambda pd: True)
    monkeypatch.setattr(bootstrap, "copy_agents", lambda *a, **kw: [])
    monkeypatch.setattr(bootstrap, "copy_hooks", lambda *a, **kw: None)
    monkeypatch.setattr(bootstrap, "copy_rules_and_skills", lambda *a, **kw: [])
    monkeypatch.setattr(bootstrap, "copy_settings_and_claude_md", lambda *a, **kw: None)
    monkeypatch.setattr(bootstrap, "setup_gitignore", lambda *a, **kw: None)
    monkeypatch.setattr(bootstrap, "run_bd_doctor", lambda *a, **kw: None)


class TestManifestKey:
    def test_strips_the_claude_prefix(self):
        """OBSOLETE_FILES are project-relative, manifest keys are .claude-relative."""
        assert _manifest_key(".claude/hooks/x.cjs") == "hooks/x.cjs"

    def test_leaves_other_paths_alone(self):
        assert _manifest_key(".beads/memory/recall.cjs") == ".beads/memory/recall.cjs"

    def test_cleanup_removes_the_manifest_entry_it_installed(self, tmp_path, monkeypatch):
        """Deleting the file but keeping its key left dead entries forever."""
        monkeypatch.setattr(bootstrap, "OBSOLETE_FILES", [".claude/hooks/gone.cjs"])
        monkeypatch.setattr(bootstrap, "OBSOLETE_DIRS", [])
        monkeypatch.setattr(bootstrap, "OBSOLETE_SETTINGS_HOOKS", [])
        monkeypatch.setattr(bootstrap, "OBSOLETE_LOCAL_SETTINGS_PATTERNS", [])
        hooks = tmp_path / ".claude" / "hooks"
        hooks.mkdir(parents=True)
        (hooks / "gone.cjs").write_text("// old hook", encoding="utf-8")
        manifest = {"files": {"hooks/gone.cjs": "sha256:abc"}}

        report = cleanup_obsolete(tmp_path, manifest, dry_run=False)

        assert report["removed_files"] == [".claude/hooks/gone.cjs"]
        assert not (hooks / "gone.cjs").exists()
        assert manifest["files"] == {}


class TestExistingInstallDetection:
    def test_manifest_marks_an_install(self, tmp_path):
        (tmp_path / ".claude").mkdir()
        (tmp_path / ".claude" / ".manifest.json").write_text("{}", encoding="utf-8")
        assert _has_existing_install(tmp_path)

    def test_hooks_directory_marks_a_pre_manifest_install(self, tmp_path):
        hooks = tmp_path / ".claude" / "hooks"
        hooks.mkdir(parents=True)
        (hooks / "bash-guard.cjs").write_text("//", encoding="utf-8")
        assert _has_existing_install(tmp_path)

    def test_empty_directory_is_a_fresh_project(self, tmp_path):
        assert not _has_existing_install(tmp_path)

    def test_init_on_an_existing_install_runs_cleanup(self, tmp_path, monkeypatch):
        """`npx claude-protocol init` passes no --upgrade. Without this, the
        project keeps hooks this version no longer ships, next to the new
        ones."""
        save_manifest(tmp_path, {"version": "3.5.0", "files": {}})
        calls = []
        monkeypatch.setattr(bootstrap, "cleanup_obsolete",
                            lambda *a, **kw: calls.append(a) or {
                                "removed_files": [], "removed_dirs": [],
                                "stripped_settings_hooks": [],
                                "stripped_local_patterns": [], "backups": [None]})
        _stub_heavy_steps(monkeypatch)

        monkeypatch.setattr(sys, "argv", ["bootstrap.py", "--project-dir", str(tmp_path)])
        with pytest.raises(SystemExit) as exc:
            bootstrap.main()

        assert exc.value.code == 0
        assert len(calls) == 1, "cleanup did not run on an existing install"

    def test_fresh_project_does_not_run_cleanup(self, tmp_path, monkeypatch):
        calls = []
        monkeypatch.setattr(bootstrap, "cleanup_obsolete", lambda *a, **kw: calls.append(a))
        _stub_heavy_steps(monkeypatch)

        monkeypatch.setattr(sys, "argv", ["bootstrap.py", "--project-dir", str(tmp_path)])
        with pytest.raises(SystemExit):
            bootstrap.main()

        assert calls == []


class TestLanguageIsRemembered:
    def _run(self, tmp_path, monkeypatch, argv):
        seen = {}
        monkeypatch.setattr(bootstrap, "copy_rules_and_skills",
                            lambda pd, wr, lang, m, f: seen.setdefault("lang", lang) or [])
        _stub_heavy_steps(monkeypatch)
        monkeypatch.setattr(bootstrap, "copy_rules_and_skills",
                            lambda pd, wr, lang, m, f: seen.setdefault("lang", lang) or [])
        monkeypatch.setattr(sys, "argv", ["bootstrap.py", "--project-dir", str(tmp_path)] + argv)
        with pytest.raises(SystemExit):
            bootstrap.main()
        return seen.get("lang")

    def test_install_records_the_language(self, tmp_path, monkeypatch):
        self._run(tmp_path, monkeypatch, ["--lang", "ru"])
        assert load_manifest(tmp_path)["lang"] == "ru"

    def test_upgrade_without_lang_keeps_the_installed_one(self, tmp_path, monkeypatch):
        """A Russian project used to flip back to English on every upgrade."""
        save_manifest(tmp_path, {"version": "3.5.0", "files": {}, "lang": "ru"})
        assert self._run(tmp_path, monkeypatch, []) == "ru"

    def test_explicit_lang_wins_over_the_manifest(self, tmp_path, monkeypatch):
        save_manifest(tmp_path, {"version": "3.5.0", "files": {}, "lang": "ru"})
        assert self._run(tmp_path, monkeypatch, ["--lang", "en"]) == "en"

    def test_fresh_project_defaults_to_english(self, tmp_path, monkeypatch):
        assert self._run(tmp_path, monkeypatch, []) == "en"


class TestSettingsAndClaudeMdSafety:
    def test_settings_json_is_backed_up_before_the_merge(self, tmp_path):
        """The merge is the only write into a file the user owns."""
        claude = tmp_path / ".claude"
        claude.mkdir()
        original = json.dumps({"hooks": {"PreToolUse": [
            {"matcher": "Bash", "hooks": [
                {"type": "command", "command": "node .claude/hooks/bash-guard.cjs"}]}]}},
            indent=2)
        (claude / "settings.json").write_text(original, encoding="utf-8")

        copy_settings_and_claude_md(tmp_path, "Demo")

        backup = claude / ".upgrades" / "settings.json.before-merge"
        assert backup.exists()
        assert backup.read_text(encoding="utf-8") == original
        assert "CLAUDE_PROJECT_DIR" in (claude / "settings.json").read_text(encoding="utf-8")

    def test_existing_claude_md_is_kept_and_template_offered(self, tmp_path):
        """A CLAUDE.md a human has edited is never rewritten — but the current
        template has to reach them somehow."""
        mine = "# My project\n\n## Workflow\n\nbeads all the way\n"
        (tmp_path / "CLAUDE.md").write_text(mine, encoding="utf-8")
        (tmp_path / ".claude").mkdir()

        copy_settings_and_claude_md(tmp_path, "Demo")

        assert (tmp_path / "CLAUDE.md").read_text(encoding="utf-8") == mine
        offered = tmp_path / ".claude" / ".upgrades" / "CLAUDE.md"
        assert offered.exists()
        assert "Demo" in offered.read_text(encoding="utf-8")
