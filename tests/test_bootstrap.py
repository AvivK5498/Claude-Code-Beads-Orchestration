"""Tests for bootstrap.py — project name inference, copy_and_replace, setup_gitignore, manifest."""

import json
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
        assert ".beads/" in content
        assert ".worktrees/" in content

    def test_appends_missing_entries(self, tmp_path, capsys):
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text("node_modules/\n.env\n")

        setup_gitignore(tmp_path)

        content = gitignore.read_text()
        assert "node_modules/" in content
        assert ".env" in content
        assert ".beads/" in content
        assert ".worktrees/" in content

    def test_skips_when_already_configured(self, tmp_path, capsys):
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text("node_modules/\n.beads/\n.worktrees/\n")

        setup_gitignore(tmp_path)

        content = gitignore.read_text()
        # Should not duplicate entries
        assert content.count(".beads/") == 1

    def test_adds_newline_if_missing(self, tmp_path, capsys):
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text("node_modules/")  # no trailing newline

        setup_gitignore(tmp_path)

        content = gitignore.read_text()
        assert ".beads/" in content
        # Should have added a newline before the section
        assert "node_modules/\n" in content

    def test_detects_entries_without_trailing_slash(self, tmp_path, capsys):
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text(".beads\n.worktrees\n.claude/.upgrades\n")

        setup_gitignore(tmp_path)

        content = gitignore.read_text()
        # Should detect ".beads" matches ".beads/" and not add duplicate
        assert content.count("beads") == 1

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
# Templates directory
# ============================================================================

class TestTemplatesDir:
    def test_templates_dir_exists(self):
        assert TEMPLATES_DIR.exists(), f"Templates dir not found: {TEMPLATES_DIR}"

    def test_has_hooks(self):
        hooks_dir = TEMPLATES_DIR / "hooks"
        assert hooks_dir.exists()
        hooks = list(hooks_dir.glob("*.cjs"))
        assert len(hooks) >= 6  # At least 6 hook files

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


# ============================================================================
# bd-3 logic: legacy auto-inject, knowledge.jsonl guard, empty-settings cleanup
# ============================================================================

class TestBd3Logic:
    # --- _auto_inject_legacy_files --------------------------------------

    def test_auto_inject_legacy_files_adds_existing_unmanaged(self, tmp_path, monkeypatch):
        """File exists on disk, not in manifest → injected with sentinel hash."""
        monkeypatch.setattr(bootstrap, "OBSOLETE_FILES", [".claude/hooks/memory-capture.cjs"])
        target = tmp_path / ".claude" / "hooks" / "memory-capture.cjs"
        target.parent.mkdir(parents=True)
        target.write_text("// legacy")
        manifest = {"files": {}}

        injected = _auto_inject_legacy_files(tmp_path, manifest, dry_run=False)

        assert injected == [".claude/hooks/memory-capture.cjs"]
        assert manifest["files"][".claude/hooks/memory-capture.cjs"] == "sha256:legacy-auto-injected"

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
