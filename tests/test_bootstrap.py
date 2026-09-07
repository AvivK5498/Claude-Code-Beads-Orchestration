"""Tests for bootstrap.py — project name inference, the installer, setup_gitignore, manifest."""

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

# Add project root to path so we can import bootstrap
sys.path.insert(0, str(Path(__file__).parent.parent))

import bootstrap
from bootstrap import (
    infer_project_name,
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
    plugin_active_for,
    copy_settings_and_claude_md,
    copy_rules_and_skills,
    marked_span,
    unmarked_span,
    splice,
    update_claude_md,
    read_verbatim,
    write_verbatim,
    _hook_basename,
    _entry_key,
    canonical_hook_commands,
    migrate_hook_commands,
    migrate_local_settings_hooks,
    merge_hooks,
    TEMPLATES_DIR,
)


def _installer(project_dir, manifest=None, *, force=False, prompt=None,
               dry_run=False):
    """An Installer for a test that cares about one or two of its fields."""
    return bootstrap.Installer(project_dir, manifest, force=force,
                               prompt=prompt, dry_run=dry_run)


def _claude_md(tmp_path, manifest, *, asks=None, dry_run=False):
    """update_claude_md with the installer it now takes.

    asks=True gives it a prompt that questions the user, asks=False one that
    never does, and leaving asks out gives it no prompt at all.
    """
    prompt = None if asks is None else bootstrap.ConflictPrompt(interactive=asks)
    update_claude_md(_template_text(),
                     _installer(tmp_path, manifest, prompt=prompt, dry_run=dry_run))


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
# setup_gitignore
# ============================================================================

class TestSetupGitignore:
    def test_creates_gitignore_when_missing(self, tmp_path, capsys):
        setup_gitignore(_installer(tmp_path))

        gitignore = tmp_path / ".gitignore"
        assert gitignore.exists()
        content = gitignore.read_text()
        assert ".worktrees/" in content
        assert "/issues.jsonl" in content

    def test_does_not_ignore_whole_beads_dir(self, tmp_path, capsys):
        """The tracker travels with the repo — .beads/ must NOT be ignored
        (that would hide the canonical .beads/issues.jsonl)."""
        setup_gitignore(_installer(tmp_path))

        lines = (tmp_path / ".gitignore").read_text().splitlines()
        assert ".beads/" not in lines
        assert ".beads" not in lines

    def test_ignores_root_issues_jsonl(self, tmp_path, capsys):
        """A stray /issues.jsonl export at repo root must be ignored."""
        setup_gitignore(_installer(tmp_path))

        content = (tmp_path / ".gitignore").read_text()
        assert "/issues.jsonl" in content

    def test_appends_missing_entries(self, tmp_path, capsys):
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text("node_modules/\n.env\n")

        setup_gitignore(_installer(tmp_path))

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

        setup_gitignore(_installer(tmp_path))

        content = gitignore.read_text()
        # Should not duplicate entries
        assert content.count(".worktrees/") == 1
        assert content.count("/issues.jsonl") == 1

    def test_anchored_entries_are_the_same_entries(self, tmp_path, capsys):
        """git reads '/x/', 'x/' and 'x' as covering the same path at the repo
        root, so a project that anchored its entries with a slash used to get a
        second copy of every one of them appended."""
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text(
            "\n".join(["/.worktrees/", "/.claude/.upgrades/", "issues.jsonl", ""])
        )

        setup_gitignore(_installer(tmp_path))

        content = gitignore.read_text()
        assert "# Beads orchestration" not in content
        assert content.count(".worktrees") == 1
        assert content.count(".claude/.upgrades") == 1
        assert content.count("issues.jsonl") == 1

    def test_a_comment_naming_an_entry_is_not_the_entry(self, tmp_path, capsys):
        """Stripping slashes must not turn '# .worktrees/ is deliberate' into
        the entry itself — that would leave the path unignored."""
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text("# .worktrees/ left out on purpose" + "\n")

        setup_gitignore(_installer(tmp_path))

        assert ".worktrees/" in gitignore.read_text().splitlines()

    def test_adds_newline_if_missing(self, tmp_path, capsys):
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text("node_modules/")  # no trailing newline

        setup_gitignore(_installer(tmp_path))

        content = gitignore.read_text()
        assert ".worktrees/" in content
        # Should have added a newline before the section
        assert "node_modules/\n" in content

    def test_idempotent_no_duplicates(self, tmp_path, capsys):
        """Running setup_gitignore twice must not duplicate any entry."""
        setup_gitignore(_installer(tmp_path))
        setup_gitignore(_installer(tmp_path))

        content = (tmp_path / ".gitignore").read_text()
        assert content.count(".worktrees/") == 1
        assert content.count("/issues.jsonl") == 1
        assert content.count(".claude/.upgrades/") == 1

    def test_detects_entries_without_trailing_slash(self, tmp_path, capsys):
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text(".worktrees\n.claude/.upgrades\n/issues.jsonl\n")

        setup_gitignore(_installer(tmp_path))

        content = gitignore.read_text()
        # Should detect ".worktrees" matches ".worktrees/" and not add duplicate
        assert content.count(".worktrees") == 1

    def test_adds_upgrades_entry_on_first_run(self, tmp_path, capsys):
        """setup_gitignore writes .claude/.upgrades/ when it's missing."""
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text("node_modules/\n")

        setup_gitignore(_installer(tmp_path))

        content = gitignore.read_text()
        assert ".claude/.upgrades/" in content

    def test_upgrades_entry_not_duplicated_on_rerun(self, tmp_path, capsys):
        """Running setup_gitignore twice must not duplicate .claude/.upgrades/."""
        setup_gitignore(_installer(tmp_path))
        setup_gitignore(_installer(tmp_path))

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
# install_beads: consent, PATH, version, and a bd init that failed
# ============================================================================
# The step used to put a global program on the machine without asking, call it
# a success without checking the system could find it, and hand-make an empty
# .beads/ when `bd init` failed — a project that looks installed and answers
# every bd command with an error.


class _Machine:
    """A fake machine: which() answers per program, run() records commands.

    `bd` is absent until a package manager installs it, unless
    `installs_to_path=False` — that is the `go install` case, where the command
    succeeds and the binary still is not on this process's PATH.
    """

    MANAGERS = ("brew", "npm", "go")

    def __init__(self, bd_present=False, installs_to_path=True,
                 version_out="bd version 1.1.0 (abc123)", init_rc=0,
                 init_err="", managers=MANAGERS, init_creates_beads=True):
        self.calls = []
        self.bd_present = bd_present
        self.installs_to_path = installs_to_path
        self.version_out = version_out
        self.init_rc = init_rc
        self.init_err = init_err
        self.managers = managers
        self.init_creates_beads = init_creates_beads

    def which(self, name):
        if name == "bd":
            return "/usr/bin/bd" if self.bd_present else None
        return f"/usr/bin/{name}" if name in self.managers else None

    def run(self, cmd, **kwargs):
        cmd = list(cmd)
        self.calls.append(cmd)
        if cmd[0] in self.MANAGERS:
            self.bd_present = self.installs_to_path
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if cmd[:2] == ["bd", "version"]:
            return SimpleNamespace(returncode=0, stdout=self.version_out, stderr="")
        if cmd[:2] == ["bd", "init"]:
            if self.init_rc == 0 and self.init_creates_beads:
                Path(kwargs["cwd"], ".beads").mkdir(parents=True, exist_ok=True)
            return SimpleNamespace(returncode=self.init_rc, stdout="", stderr=self.init_err)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    def install(self, monkeypatch, someone_is_here=False):
        monkeypatch.setattr(bootstrap.shutil, "which", self.which)
        monkeypatch.setattr(bootstrap.subprocess, "run", self.run)
        monkeypatch.setattr(bootstrap, "_stdin_is_a_person",
                            lambda: someone_is_here)
        return self

    @property
    def manager_calls(self):
        return [c for c in self.calls if c[0] in self.MANAGERS]


class TestInstallBeadsAsksFirst:
    def test_nobody_to_ask_installs_nothing(self, tmp_path, monkeypatch, capsys):
        """A batch upgrade, CI, or an agent driving the CLI: no person, no
        global install. The command to run by hand is printed instead."""
        machine = _Machine().install(monkeypatch, someone_is_here=False)

        assert bootstrap.install_beads(tmp_path) is False
        assert machine.manager_calls == [], "installed something with nobody to ask"
        assert "--install-beads" in capsys.readouterr().out

    def test_the_flag_installs_without_asking(self, tmp_path, monkeypatch):
        machine = _Machine().install(monkeypatch, someone_is_here=False)

        assert bootstrap.install_beads(tmp_path, install_bd=True) is True
        assert machine.manager_calls, "the flag did not install anything"

    def test_a_no_at_the_prompt_installs_nothing(self, tmp_path, monkeypatch):
        machine = _Machine().install(monkeypatch, someone_is_here=True)
        monkeypatch.setattr("builtins.input", lambda _: "n")

        assert bootstrap.install_beads(tmp_path) is False
        assert machine.manager_calls == []

    def test_a_yes_at_the_prompt_installs(self, tmp_path, monkeypatch):
        machine = _Machine().install(monkeypatch, someone_is_here=True)
        monkeypatch.setattr("builtins.input", lambda _: "y")

        assert bootstrap.install_beads(tmp_path) is True
        assert machine.manager_calls

    def test_no_package_manager_at_all(self, tmp_path, monkeypatch, capsys):
        machine = _Machine(managers=()).install(monkeypatch, someone_is_here=True)

        assert bootstrap.install_beads(tmp_path) is False
        assert machine.manager_calls == []
        assert bootstrap.BD_DOCS_URL in capsys.readouterr().out


class TestInstallBeadsChecksItsWork:
    def test_installed_but_not_on_path_is_not_success(self, tmp_path, monkeypatch, capsys):
        """`go install` writes to a directory that is often outside PATH, and
        a PATH just extended is not this process's PATH."""
        _Machine(installs_to_path=False).install(monkeypatch)

        assert bootstrap.install_beads(tmp_path, install_bd=True) is False
        assert "PATH" in capsys.readouterr().out

    def test_failed_bd_init_leaves_no_half_made_beads(self, tmp_path, monkeypatch, capsys):
        _Machine(bd_present=True, init_rc=1,
                 init_err="dolt: connection refused").install(monkeypatch)

        assert bootstrap.install_beads(tmp_path) is False
        assert not (tmp_path / ".beads").exists(), "made a .beads that bd cannot use"
        assert "dolt: connection refused" in capsys.readouterr().out

    def test_old_bd_warns_and_keeps_going(self, tmp_path, monkeypatch, capsys):
        _Machine(bd_present=True,
                 version_out="bd version 0.9.0 (abc)").install(monkeypatch)

        assert bootstrap.install_beads(tmp_path) is True
        out = capsys.readouterr().out
        assert "0.9.0" in out and bootstrap.BD_MIN_VERSION in out

    def test_current_bd_says_nothing_about_versions(self, tmp_path, monkeypatch, capsys):
        _Machine(bd_present=True).install(monkeypatch)

        assert bootstrap.install_beads(tmp_path) is True
        assert "older than" not in capsys.readouterr().out

    def test_a_normal_run_still_initializes(self, tmp_path, monkeypatch):
        machine = _Machine(bd_present=True).install(monkeypatch)

        assert bootstrap.install_beads(tmp_path) is True
        assert ["bd", "init"] in machine.calls
        assert ["bd", "config", "set", "export.git-add", "false"] in machine.calls

    def test_bd_init_that_says_yes_and_makes_nothing_is_a_failure(
            self, tmp_path, monkeypatch, capsys):
        """`bd init` inside an existing beads repository exits 0 and
        initializes nothing here. Everything downstream expects .beads/ here."""
        _Machine(bd_present=True, init_creates_beads=False).install(monkeypatch)

        assert bootstrap.install_beads(tmp_path) is False
        assert "left no .beads/" in capsys.readouterr().out


class TestBdVersionReading:
    @pytest.mark.parametrize("text,expected", [
        ("bd version 1.1.0 (8e4e59d39: HEAD@8e4e59d39f34)", "1.1.0"),
        ("bd version 10.2.13", "10.2.13"),
        ("", None),
        ("bd version unknown", None),
    ])
    def test_parse(self, text, expected):
        assert bootstrap.parse_bd_version(text) == expected

    @pytest.mark.parametrize("current,expected", [
        ("1.0.9", True),
        ("0.9.0", True),
        ("1.1.0", False),
        ("1.1.1", False),
        ("2.0.0", False),
        (None, False),
        ("nonsense", False),
    ])
    def test_below_minimum(self, current, expected):
        assert bootstrap.version_below(current, "1.1.0") is expected


class TestMinimumVersionIsStatedOnce:
    def test_python_and_the_hook_agree(self):
        """The constant lives in two languages. Two copies drift silently, so
        the test is the thing that keeps them equal."""
        hook = (Path(__file__).parent.parent / "templates" / "hooks"
                / "hook-utils.cjs").read_text(encoding="utf-8")
        match = re.search(r"BD_MIN_VERSION\s*=\s*['\"]([\d.]+)['\"]", hook)

        assert match, "hook-utils.cjs no longer declares BD_MIN_VERSION"
        assert match.group(1) == bootstrap.BD_MIN_VERSION


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
        monkeypatch.setattr(bootstrap, "install_beads", lambda pd, *a, **kw: True)
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
        monkeypatch.setattr(bootstrap, "install_beads", lambda pd, *a, **kw: True)
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
        """Every hook file we install needs a command. Two files in there are
        not hooks: hook-utils is the shared library, and update-check is the
        helper session-start spawns so a network call can be given a hard time
        limit of its own."""
        helpers = {"hook-utils.cjs", "update-check.cjs"}
        shipped = {
            f.name for f in (TEMPLATES_DIR / "hooks").glob("*.cjs")
            if f.name not in helpers
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
    _stub_external(monkeypatch)
    monkeypatch.setattr(bootstrap, "copy_agents", lambda *a, **kw: [])
    monkeypatch.setattr(bootstrap, "copy_hooks", lambda *a, **kw: None)
    monkeypatch.setattr(bootstrap, "copy_rules_and_skills", lambda *a, **kw: [])
    monkeypatch.setattr(bootstrap, "copy_settings_and_claude_md", lambda *a, **kw: None)
    monkeypatch.setattr(bootstrap, "setup_gitignore", lambda *a, **kw: None)


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

        def record_lang(with_rules, lang, installer, **kwargs):
            seen.setdefault("lang", lang)

        _stub_heavy_steps(monkeypatch)
        monkeypatch.setattr(bootstrap, "copy_rules_and_skills", record_lang)
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

        copy_settings_and_claude_md("Demo", _installer(tmp_path))

        backup = claude / ".upgrades" / "settings.json.before-merge"
        assert backup.exists()
        assert backup.read_text(encoding="utf-8") == original
        assert "CLAUDE_PROJECT_DIR" in (claude / "settings.json").read_text(encoding="utf-8")

    def test_an_unparseable_settings_json_is_kept_before_replacing_it(self, tmp_path):
        """Merging is impossible, replacing is fine — losing it silently is not."""
        claude = tmp_path / ".claude"
        claude.mkdir()
        broken = b'{"hooks": {  <- someone was editing this\r\n'
        (claude / "settings.json").write_bytes(broken)

        copy_settings_and_claude_md("Demo", _installer(tmp_path))

        assert "CLAUDE_PROJECT_DIR" in read_verbatim(claude / "settings.json")
        kept = claude / ".upgrades" / "settings.json.before-merge"
        assert kept.exists(), "the file we could not parse was replaced with no copy"
        assert kept.read_bytes() == broken, "the copy is not byte-for-byte"

    def test_existing_claude_md_is_kept_and_template_offered(self, tmp_path):
        """A CLAUDE.md a human has edited is never rewritten — but the current
        template has to reach them somehow."""
        mine = "# My project\n\n## Workflow\n\nbeads all the way\n"
        (tmp_path / "CLAUDE.md").write_text(mine, encoding="utf-8")
        (tmp_path / ".claude").mkdir()

        copy_settings_and_claude_md("Demo", _installer(tmp_path))

        assert (tmp_path / "CLAUDE.md").read_text(encoding="utf-8") == mine
        offered = tmp_path / ".claude" / ".upgrades" / "CLAUDE.md"
        assert offered.exists()
        assert "Demo" in offered.read_text(encoding="utf-8")


# ============================================================================
# What happens to a file the user edited
# ============================================================================
# Silently keeping it and dropping ours in .upgrades/ turned every upgrade into
# homework. Now it is a question — but only where someone can answer it.


def _stub_external(monkeypatch):
    """bd and bd doctor — everything that leaves the process."""
    monkeypatch.setattr(bootstrap, "install_beads", lambda pd, *a, **kw: True)
    monkeypatch.setattr(bootstrap, "run_bd_doctor", lambda *a, **kw: None)


def _snapshot(root):
    """Every file under root, by path, as bytes."""
    return {str(f.relative_to(root)): f.read_bytes()
            for f in root.rglob('*') if f.is_file()}


def _explode(_):
    """input() for a run where nobody should be asked anything."""
    raise AssertionError("asked a question that nobody should have been asked")


def _copy_rules(tmp_path, manifest, *, force=False, prompt=None, dry_run=False):
    """copy_rules_and_skills, and the installer it takes, in one call."""
    installer = _installer(tmp_path, manifest, force=force, prompt=prompt,
                           dry_run=dry_run)
    copy_rules_and_skills(True, "en", installer)
    return installer.skipped


def _modified_rule(tmp_path, name="implementation-standard.md", text="mine\n"):
    """A project with one rule the user has edited (hash no longer matches)."""
    rules = tmp_path / ".claude" / "rules"
    rules.mkdir(parents=True)
    (rules / name).write_text(text, encoding="utf-8")
    return {"files": {f"rules/{name}": "sha256:something-else"}}


class TestConflictPromptDecides:
    def test_keeps_yours_by_default_on_empty_answer(self, tmp_path, monkeypatch):
        prompt = bootstrap.ConflictPrompt(interactive=True)
        monkeypatch.setattr("builtins.input", lambda _: "")
        target = tmp_path / "f.md"
        target.write_text("mine", encoding="utf-8")

        assert prompt.ask("rules/x.md", target, "ours") == bootstrap.ConflictPrompt.KEEP

    def test_takes_ours_on_t(self, tmp_path, monkeypatch):
        prompt = bootstrap.ConflictPrompt(interactive=True)
        monkeypatch.setattr("builtins.input", lambda _: "t")
        target = tmp_path / "f.md"
        target.write_text("mine", encoding="utf-8")

        assert prompt.ask("rules/x.md", target, "ours") == bootstrap.ConflictPrompt.TAKE

    def test_capital_answer_sticks_for_the_rest(self, tmp_path, monkeypatch):
        """Eight edited rules must not mean eight questions."""
        prompt = bootstrap.ConflictPrompt(interactive=True)
        answers = iter(["T"])
        monkeypatch.setattr("builtins.input", lambda _: next(answers))
        target = tmp_path / "f.md"
        target.write_text("mine", encoding="utf-8")

        assert prompt.ask("rules/a.md", target, "ours") == bootstrap.ConflictPrompt.TAKE
        # input() would raise StopIteration if it were consulted again
        assert prompt.ask("rules/b.md", target, "ours") == bootstrap.ConflictPrompt.TAKE
        assert not prompt.will_ask

    def test_unknown_answer_asks_again(self, tmp_path, monkeypatch):
        prompt = bootstrap.ConflictPrompt(interactive=True)
        answers = iter(["what?", "t"])
        monkeypatch.setattr("builtins.input", lambda _: next(answers))
        target = tmp_path / "f.md"
        target.write_text("mine", encoding="utf-8")

        assert prompt.ask("rules/x.md", target, "ours") == bootstrap.ConflictPrompt.TAKE

    def test_diff_then_decide(self, tmp_path, monkeypatch, capsys):
        prompt = bootstrap.ConflictPrompt(interactive=True)
        answers = iter(["d", "k"])
        monkeypatch.setattr("builtins.input", lambda _: next(answers))
        target = tmp_path / "f.md"
        target.write_text("line one\nline two\n", encoding="utf-8")

        assert prompt.ask("rules/x.md", target, "line one\nline three\n") == "keep"
        shown = capsys.readouterr().out
        assert "-line two" in shown and "+line three" in shown

    def test_no_answer_available_keeps_yours(self, tmp_path, monkeypatch):
        """Ctrl-C or a closed stdin must never mean 'overwrite my work'."""
        prompt = bootstrap.ConflictPrompt(interactive=True)

        def refuse(_):
            raise EOFError

        monkeypatch.setattr("builtins.input", refuse)
        target = tmp_path / "f.md"
        target.write_text("mine", encoding="utf-8")

        assert prompt.ask("rules/x.md", target, "ours") == bootstrap.ConflictPrompt.KEEP

    def test_non_interactive_never_asks(self, tmp_path, monkeypatch):
        prompt = bootstrap.ConflictPrompt(interactive=False)

        monkeypatch.setattr("builtins.input", _explode)
        target = tmp_path / "f.md"
        target.write_text("mine", encoding="utf-8")

        assert prompt.ask("rules/x.md", target, "ours") == bootstrap.ConflictPrompt.KEEP
        assert not prompt.will_ask


# ==========================================================================
# Nothing is ever lost, whichever kind of file it is
# ==========================================================================
# Agents, rules and the skill were three copies of the same eighteen lines, and
# each grew its own test class around its own copy. They are one method now, so
# what they promise is proved once, over all three — and a fourth kind of file
# costs one line here instead of eighty.

MINE = "MY OWN version, edited by hand\n"

MANAGED = {
    "agent": "agents/code-reviewer.md",
    "rule": "rules/implementation-standard.md",
    "skill": "skills/project-discovery/SKILL.md",
}


def _edited(tmp_path, kind):
    """A project carrying one file of ours that its owner has since edited."""
    rel_key = MANAGED[kind]
    dest = tmp_path / ".claude" / rel_key
    dest.parent.mkdir(parents=True, exist_ok=True)
    write_verbatim(dest, MINE)
    return {"files": {rel_key: "sha256:something-else"}}


def _install_kind(tmp_path, kind, manifest, *, force=False, prompt=None,
                  dry_run=False):
    """Run the step that installs that kind of file. Returns the installer."""
    installer = _installer(tmp_path, manifest, force=force, prompt=prompt,
                           dry_run=dry_run)
    if kind == "agent":
        bootstrap.copy_agents("Demo", installer)
    else:  # the rule and the skill both arrive through this one step
        copy_rules_and_skills(True, "en", installer)
    return installer


def _answering(answer, monkeypatch):
    """A prompt that a person answers with `answer`."""
    monkeypatch.setattr("builtins.input", lambda _: answer)
    return bootstrap.ConflictPrompt(interactive=True)


@pytest.mark.parametrize("kind", list(MANAGED))
class TestEveryManagedFileKeepsThePromise:
    def test_an_edit_is_a_question(self, tmp_path, kind, monkeypatch):
        manifest = _edited(tmp_path, kind)
        asked = []
        monkeypatch.setattr("builtins.input", lambda _: asked.append(1) or "k")

        _install_kind(tmp_path, kind, manifest,
                      prompt=bootstrap.ConflictPrompt(interactive=True))

        assert asked, "a file the user edited was replaced without asking"
        assert read_verbatim(tmp_path / ".claude" / MANAGED[kind]) == MINE

    def test_keeping_yours_saves_ours_beside_it(self, tmp_path, kind, monkeypatch):
        manifest = _edited(tmp_path, kind)

        installer = _install_kind(tmp_path, kind, manifest,
                                  prompt=_answering("k", monkeypatch))

        rel_key = MANAGED[kind]
        assert read_verbatim(tmp_path / ".claude" / rel_key) == MINE
        assert rel_key in installer.skipped
        assert (tmp_path / ".claude" / ".upgrades" / rel_key).exists()

    def test_taking_ours_saves_yours_beside_it(self, tmp_path, kind, monkeypatch):
        manifest = _edited(tmp_path, kind)

        _install_kind(tmp_path, kind, manifest, prompt=_answering("t", monkeypatch))

        rel_key = MANAGED[kind]
        assert read_verbatim(tmp_path / ".claude" / rel_key) != MINE
        mine = tmp_path / ".claude" / ".upgrades" / (rel_key + ".mine")
        assert read_verbatim(mine) == MINE, "the copy is not byte-for-byte"

    def test_taking_ours_records_the_new_hash(self, tmp_path, kind, monkeypatch):
        """Otherwise the same file is reported as modified on the next upgrade."""
        manifest = _edited(tmp_path, kind)

        _install_kind(tmp_path, kind, manifest, prompt=_answering("t", monkeypatch))

        rel_key = MANAGED[kind]
        dest = tmp_path / ".claude" / rel_key
        assert manifest["files"][rel_key] == file_sha256(dest)

    def test_no_terminal_keeps_yours(self, tmp_path, kind, monkeypatch):
        """Batch upgrades, CI and agent-driven runs must not block on input."""
        monkeypatch.setattr("builtins.input", _explode)
        manifest = _edited(tmp_path, kind)

        _install_kind(tmp_path, kind, manifest,
                      prompt=bootstrap.ConflictPrompt(interactive=False))

        assert read_verbatim(tmp_path / ".claude" / MANAGED[kind]) == MINE

    def test_force_replaces_it_and_keeps_a_copy(self, tmp_path, kind):
        """should_update_file answers "forced" without ever looking at the file."""
        manifest = _edited(tmp_path, kind)

        _install_kind(tmp_path, kind, manifest, force=True)

        rel_key = MANAGED[kind]
        assert read_verbatim(tmp_path / ".claude" / rel_key) != MINE
        mine = tmp_path / ".claude" / ".upgrades" / (rel_key + ".mine")
        assert read_verbatim(mine) == MINE, "the copy is not byte-for-byte"

    def test_a_preview_with_force_writes_nothing(self, tmp_path, kind):
        manifest = _edited(tmp_path, kind)
        before = _snapshot(tmp_path)

        _install_kind(tmp_path, kind, manifest, force=True, dry_run=True)

        assert _snapshot(tmp_path) == before
        assert not (tmp_path / ".claude" / ".upgrades").exists()

    def test_an_untouched_file_is_updated_silently(self, tmp_path, kind, monkeypatch):
        monkeypatch.setattr("builtins.input", _explode)
        manifest = {"files": {}}

        _install_kind(tmp_path, kind, manifest)

        rel_key = MANAGED[kind]
        dest = tmp_path / ".claude" / rel_key
        assert dest.exists()
        assert manifest["files"][rel_key] == file_sha256(dest)


class TestPromptWiring:
    def _run(self, tmp_path, monkeypatch, argv, isatty=True):
        asked = []
        monkeypatch.setattr(bootstrap, "_stdin_is_a_person", lambda: isatty)

        def record_prompt(with_rules, lang, installer, **kwargs):
            asked.append(installer.prompt.will_ask)

        _stub_heavy_steps(monkeypatch)
        monkeypatch.setattr(bootstrap, "copy_rules_and_skills", record_prompt)
        monkeypatch.setattr(sys, "argv",
                            ["bootstrap.py", "--project-dir", str(tmp_path)] + argv)
        with pytest.raises(SystemExit):
            bootstrap.main()
        return asked[0]

    def test_asks_on_a_terminal(self, tmp_path, monkeypatch):
        assert self._run(tmp_path, monkeypatch, []) is True

    def test_silent_without_a_terminal(self, tmp_path, monkeypatch):
        """Batch upgrades, CI and agent-driven runs must not block on input."""
        assert self._run(tmp_path, monkeypatch, [], isatty=False) is False

    def test_force_does_not_ask(self, tmp_path, monkeypatch):
        assert self._run(tmp_path, monkeypatch, ["--force"]) is False

    def test_keep_mine_does_not_ask(self, tmp_path, monkeypatch):
        assert self._run(tmp_path, monkeypatch, ["--keep-mine"]) is False

    def test_dry_run_does_not_ask(self, tmp_path, monkeypatch):
        assert self._run(tmp_path, monkeypatch, ["--dry-run"]) is False


# ============================================================================
# --dry-run
# ============================================================================
# The flag says "print the plan without writing anything", and the README tells
# people to run it first. Only the cleanup pass honoured it: the copy steps
# wrote files regardless, so the preview changed the project it previewed.


class TestDryRunWritesNothing:
    def test_fresh_project_stays_empty(self, tmp_path, monkeypatch):
        _stub_external(monkeypatch)

        rc = bootstrap.bootstrap_project(
            project_dir=tmp_path, project_name="Demo", with_rules=True,
            lang="en", force=False, upgrade=False, dry_run=True,
        )

        assert rc == 0
        assert list(tmp_path.rglob("*")) == [], "dry run created files"

    def test_existing_install_is_left_byte_for_byte(self, tmp_path, monkeypatch):
        _stub_external(monkeypatch)
        # A real install first...
        bootstrap.bootstrap_project(
            project_dir=tmp_path, project_name="Demo", with_rules=True,
            lang="en", force=False, upgrade=False, dry_run=False,
        )
        before = _snapshot(tmp_path)
        assert before, "nothing was installed, the test proves nothing"

        # ...then a preview of the next upgrade
        bootstrap.bootstrap_project(
            project_dir=tmp_path, project_name="Demo", with_rules=True,
            lang="en", force=False, upgrade=True, dry_run=True,
        )

        assert _snapshot(tmp_path) == before

    def test_preview_still_reports_what_would_happen(self, tmp_path, monkeypatch, capsys):
        _stub_external(monkeypatch)

        bootstrap.bootstrap_project(
            project_dir=tmp_path, project_name="Demo", with_rules=True,
            lang="en", force=False, upgrade=False, dry_run=True,
        )

        out = capsys.readouterr().out
        assert "[DRY-RUN] settings.json" in out
        assert "[DRY-RUN] rules/beads-workflow.md" in out
        assert "[DRY-RUN] CLAUDE.md" in out

    def test_a_modified_rule_leaves_no_upgrade_file(self, tmp_path):
        """Saving the losing version is a write too, and a preview makes none."""
        manifest = _modified_rule(tmp_path)

        _copy_rules(tmp_path, manifest, force=False,
                    prompt=bootstrap.ConflictPrompt(interactive=False),
                    dry_run=True)

        assert not (tmp_path / ".claude" / ".upgrades").exists()


# ============================================================================
# CLAUDE.md — our block, and only our block
# ============================================================================
# CLAUDE.md carries the project overview, the tech stack and the current state,
# so it is never overwritten wholesale. Until now that also meant our
# instructions inside it were never updated: the template landed in .upgrades/
# and a human merged it by hand. Markers make the replacement automatic and
# bounded — everything outside them is not ours to touch.


LEGACY_CLAUDE_MD = """# Demo

## Project Overview

We sell widgets, and only this file says so.

## Tech Stack

- Rust

## Your Identity

**You are an orchestrator and co-pilot.**

- wording from 3.5 that nobody ships any more

## Workflow

old workflow text

### Quick Fix (<10 lines, feature branch only)

branch off main first

## Investigation Before Delegation

lead with evidence

## Bug Fixes & Follow-Up

closed beads stay closed

## Agents

- code-reviewer

## Current State

Mid-migration, and this sentence must survive.
"""


def _template_text(name="Demo"):
    return read_verbatim(TEMPLATES_DIR / "CLAUDE.md").replace("[Project]", name)


def _template_region():
    text = _template_text()
    start, end = marked_span(text)
    return text[start:end]


def _installed_project(tmp_path, block="## Your Identity\n\nwhat 3.7 shipped\n"):
    """A CLAUDE.md we installed and nobody has edited since."""
    region = ("<!-- claude-protocol:begin · managed block -->\n\n"
              + block + "\n<!-- claude-protocol:end -->")
    write_verbatim(tmp_path / "CLAUDE.md",
                   "# Demo\n\n## Project Overview\n\nWe sell widgets.\n\n"
                   + region + "\n\n## Current State\n\nMid-migration.\n")
    (tmp_path / ".claude").mkdir(exist_ok=True)
    return {"files": {}, "regions": {"CLAUDE.md": content_sha256(region)}}


class TestClaudeMdSpans:
    def test_marked_span_covers_both_markers(self):
        text = ("before\n<!-- claude-protocol:begin -->\nours\n"
                "<!-- claude-protocol:end -->\nafter\n")
        start, end = marked_span(text)
        assert text[start:end] == ("<!-- claude-protocol:begin -->\nours\n"
                                   "<!-- claude-protocol:end -->")

    def test_marked_span_is_none_without_markers(self):
        assert marked_span("just a file\n") is None

    def test_marked_span_needs_the_closing_marker(self):
        """Half a pair is not a block — falling back beats guessing an end."""
        assert marked_span("<!-- claude-protocol:begin -->\nours\n") is None

    def test_the_shipped_template_carries_the_markers(self):
        region = _template_region()
        assert "## Your Identity" in region and "## Agents" in region
        assert "## Project Overview" not in region, "the user's own section is inside ours"
        assert "## Current State" not in region, "the user's own section is inside ours"

    def test_unmarked_span_finds_a_v3_block(self):
        start, end = unmarked_span(LEGACY_CLAUDE_MD)
        block = LEGACY_CLAUDE_MD[start:end]
        assert block.startswith("## Your Identity")
        assert block.endswith("- code-reviewer\n")
        assert "We sell widgets" not in block
        assert "Mid-migration" not in block

    def test_unmarked_span_stops_at_a_foreign_heading(self):
        """A section the user put between ours must never be swallowed."""
        text = "## Your Identity\n\nours\n\n## Deployment\n\nmine\n\n## Agents\n\nours\n"
        start, end = unmarked_span(text)
        assert text[start:end] == "## Your Identity\n\nours\n"

    def test_unmarked_span_keeps_level_three_headings_inside(self):
        start, end = unmarked_span(LEGACY_CLAUDE_MD)
        assert "### Quick Fix" in LEGACY_CLAUDE_MD[start:end]

    def test_unmarked_span_is_none_without_our_first_heading(self):
        assert unmarked_span("# Mine\n\n## Workflow\n\nbeads all the way\n") is None

    def test_splice_keeps_crlf(self):
        text = ("a\r\n<!-- claude-protocol:begin -->\r\nold\r\n"
                "<!-- claude-protocol:end -->\r\nb\r\n")
        out = splice(text, marked_span(text),
                     "<!-- claude-protocol:begin -->\nnew\n<!-- claude-protocol:end -->")
        assert "new" in out
        assert "\n" not in out.replace("\r\n", ""), "a lone LF crept into a CRLF file"

    def test_splice_keeps_lf(self):
        text = "a\n<!-- claude-protocol:begin -->\nold\n<!-- claude-protocol:end -->\nb\n"
        out = splice(text, marked_span(text),
                     "<!-- claude-protocol:begin -->\r\nnew\r\n<!-- claude-protocol:end -->")
        assert "\r" not in out, "a CR crept into an LF file"


class TestClaudeMdBlockIsRefreshed:
    def test_a_new_file_gets_the_markers_and_is_recorded(self, tmp_path):
        manifest = {"files": {}}

        _claude_md(tmp_path, manifest)

        assert marked_span(read_verbatim(tmp_path / "CLAUDE.md")) is not None
        assert manifest["regions"]["CLAUDE.md"] == content_sha256(_template_region())

    def test_the_block_is_refreshed_without_a_question(self, tmp_path, monkeypatch):
        manifest = _installed_project(tmp_path)
        monkeypatch.setattr("builtins.input", _explode)

        _claude_md(tmp_path, manifest, asks=True)

        text = read_verbatim(tmp_path / "CLAUDE.md")
        assert "what 3.7 shipped" not in text
        assert "**You are an orchestrator and co-pilot.**" in text
        assert manifest["regions"]["CLAUDE.md"] == content_sha256(_template_region())

    def test_the_users_own_text_is_left_alone(self, tmp_path):
        manifest = _installed_project(tmp_path)

        _claude_md(tmp_path, manifest)

        text = read_verbatim(tmp_path / "CLAUDE.md")
        assert text.startswith("# Demo\n\n## Project Overview\n\nWe sell widgets.\n\n")
        assert text.endswith("\n\n## Current State\n\nMid-migration.\n")

    def test_a_crlf_file_stays_crlf(self, tmp_path):
        manifest = _installed_project(tmp_path)
        path = tmp_path / "CLAUDE.md"
        write_verbatim(path, read_verbatim(path).replace("\n", "\r\n"))

        _claude_md(tmp_path, manifest)

        text = read_verbatim(path)
        assert "**You are an orchestrator and co-pilot.**" in text
        assert "\n" not in text.replace("\r\n", ""), "the file was flipped to LF"

    def test_appending_writes_only_our_block(self, tmp_path):
        write_verbatim(tmp_path / "CLAUDE.md", "# Demo\n\n## Build\n\nmake all\n")
        manifest = {"files": {}}

        _claude_md(tmp_path, manifest)

        text = read_verbatim(tmp_path / "CLAUDE.md")
        assert "## Build" in text and "# Beads Orchestration" in text
        assert marked_span(text) is not None
        assert "## Tech Stack" not in text, "the template's own sections leaked in"
        assert manifest["regions"]["CLAUDE.md"] == content_sha256(_template_region())


class TestClaudeMdAsksBeforeTouchingYourEdits:
    def _edited_inside(self, tmp_path):
        manifest = _installed_project(tmp_path)
        path = tmp_path / "CLAUDE.md"
        write_verbatim(path, read_verbatim(path).replace(
            "what 3.7 shipped", "what 3.7 shipped, plus a rule I added"))
        return manifest

    def _legacy(self, tmp_path):
        write_verbatim(tmp_path / "CLAUDE.md", LEGACY_CLAUDE_MD)
        (tmp_path / ".claude").mkdir(exist_ok=True)
        return {"files": {}}

    def test_an_edit_inside_the_block_is_a_question(self, tmp_path, monkeypatch):
        manifest = self._edited_inside(tmp_path)
        asked = []
        monkeypatch.setattr("builtins.input", lambda _: asked.append(1) or "k")

        _claude_md(tmp_path, manifest, asks=True)

        assert asked, "an edited block was replaced without asking"
        assert "plus a rule I added" in read_verbatim(tmp_path / "CLAUDE.md")

    def test_keeping_your_block_saves_ours_beside_it(self, tmp_path, monkeypatch):
        manifest = self._edited_inside(tmp_path)
        monkeypatch.setattr("builtins.input", lambda _: "k")

        _claude_md(tmp_path, manifest, asks=True)

        ours = read_verbatim(tmp_path / ".claude" / ".upgrades" / "CLAUDE.md")
        assert "**You are an orchestrator and co-pilot.**" in ours
        assert "We sell widgets." in ours, "the offer dropped the user's own sections"

    def test_taking_our_block_saves_your_whole_file(self, tmp_path, monkeypatch):
        manifest = self._edited_inside(tmp_path)
        monkeypatch.setattr("builtins.input", lambda _: "t")

        _claude_md(tmp_path, manifest, asks=True)

        text = read_verbatim(tmp_path / "CLAUDE.md")
        assert "plus a rule I added" not in text
        assert "We sell widgets." in text and "Mid-migration." in text
        mine = read_verbatim(tmp_path / ".claude" / ".upgrades" / "CLAUDE.md.mine")
        assert "plus a rule I added" in mine
        assert manifest["regions"]["CLAUDE.md"] == content_sha256(_template_region())

    def test_an_unmarked_block_asks_before_marking(self, tmp_path, monkeypatch):
        manifest = self._legacy(tmp_path)
        monkeypatch.setattr("builtins.input", lambda _: "t")

        _claude_md(tmp_path, manifest, asks=True)

        text = read_verbatim(tmp_path / "CLAUDE.md")
        assert marked_span(text) is not None
        assert "wording from 3.5" not in text
        assert "We sell widgets, and only this file says so." in text
        assert "Mid-migration, and this sentence must survive." in text

    def test_refusing_to_mark_leaves_the_file_alone(self, tmp_path, monkeypatch):
        manifest = self._legacy(tmp_path)
        monkeypatch.setattr("builtins.input", lambda _: "k")

        _claude_md(tmp_path, manifest, asks=True)

        assert read_verbatim(tmp_path / "CLAUDE.md") == LEGACY_CLAUDE_MD
        assert (tmp_path / ".claude" / ".upgrades" / "CLAUDE.md").exists()

    def test_no_terminal_never_asks_and_keeps_your_file(self, tmp_path, monkeypatch):
        manifest = self._legacy(tmp_path)
        monkeypatch.setattr("builtins.input", _explode)

        _claude_md(tmp_path, manifest, asks=False)

        assert read_verbatim(tmp_path / "CLAUDE.md") == LEGACY_CLAUDE_MD

    def test_markers_without_a_recorded_hash_are_a_question(self, tmp_path, monkeypatch):
        """Markers alone do not prove the block is ours.

        The manifest can be lost, unreadable or hand-edited, and a file can
        quote both marker strings in its own prose. Replacing what sits between
        them on that evidence deletes text nobody agreed to lose.
        """
        manifest = _installed_project(tmp_path)
        del manifest["regions"]["CLAUDE.md"]
        asked = []
        monkeypatch.setattr("builtins.input", lambda _: asked.append(1) or "k")

        _claude_md(tmp_path, manifest, asks=True)

        assert asked, "replaced a block we have no record of installing"
        assert "what 3.7 shipped" in read_verbatim(tmp_path / "CLAUDE.md")

    def test_prose_quoting_the_markers_is_not_gutted(self, tmp_path, monkeypatch):
        """A 'how upgrades work' section mentioning both markers is still text."""
        write_verbatim(tmp_path / "CLAUDE.md",
                       "# Demo\n\n## How upgrades work\n\n"
                       "Our block starts at <!-- claude-protocol:begin --> and\n"
                       "runs to <!-- claude-protocol:end -->, and nothing else moves.\n")
        (tmp_path / ".claude").mkdir(exist_ok=True)
        monkeypatch.setattr("builtins.input", _explode)

        _claude_md(tmp_path, {"files": {}}, asks=False)

        text = read_verbatim(tmp_path / "CLAUDE.md")
        assert "runs to <!-- claude-protocol:end -->, and nothing else moves." in text

    def test_an_unreadable_manifest_does_not_cost_you_the_block(self, tmp_path, monkeypatch):
        """load_manifest swallows a parse error and returns an empty manifest."""
        _stub_external(monkeypatch)
        monkeypatch.setattr("builtins.input", _explode)
        _installed_project(tmp_path, block="## Your Identity\n\nMY OWN RULE: no Friday deploys.\n")
        (tmp_path / ".claude" / ".manifest.json").write_text("{ broken", encoding="utf-8")

        bootstrap.bootstrap_project(
            project_dir=tmp_path, project_name="Demo", with_rules=True,
            lang="en", force=False, upgrade=False, dry_run=False, keep_mine=True,
        )

        assert "MY OWN RULE" in read_verbatim(tmp_path / "CLAUDE.md")

    def test_force_marks_the_block_without_asking(self, tmp_path, monkeypatch):
        """--force answers 'take ours' in advance, for CLAUDE.md too."""
        _stub_external(monkeypatch)
        monkeypatch.setattr("builtins.input", _explode)
        write_verbatim(tmp_path / "CLAUDE.md", LEGACY_CLAUDE_MD)

        bootstrap.bootstrap_project(
            project_dir=tmp_path, project_name="Demo", with_rules=True,
            lang="en", force=True, upgrade=False, dry_run=False,
        )

        text = read_verbatim(tmp_path / "CLAUDE.md")
        assert marked_span(text) is not None
        assert "Mid-migration, and this sentence must survive." in text
        assert load_manifest(tmp_path).get("regions", {}).get("CLAUDE.md")

    def test_keep_mine_leaves_the_block_unmarked(self, tmp_path, monkeypatch):
        _stub_external(monkeypatch)
        monkeypatch.setattr("builtins.input", _explode)
        write_verbatim(tmp_path / "CLAUDE.md", LEGACY_CLAUDE_MD)

        bootstrap.bootstrap_project(
            project_dir=tmp_path, project_name="Demo", with_rules=True,
            lang="en", force=False, upgrade=False, dry_run=False,
            keep_mine=True,
        )

        assert read_verbatim(tmp_path / "CLAUDE.md") == LEGACY_CLAUDE_MD


# ============================================================================
# --force still keeps what it overwrites
# ============================================================================
# should_update_file answers "forced" before the conflict prompt is ever
# reached, so under --force nothing saved the user's version and an edited rule
# was simply gone. Everywhere else in the upgrade the losing version survives.
# That --force keeps a copy is proved for every kind of file above; what is left
# here is the awkward company it keeps — an untouched file, a manifest someone
# hand-edited, a path we cannot read.


class TestForceKeepsWhatItOverwrites:
    def test_a_file_you_never_touched_leaves_no_copy(self, tmp_path, monkeypatch):
        """A .mine for every untouched file would bury the ones that matter."""
        _stub_external(monkeypatch)
        bootstrap.bootstrap_project(
            project_dir=tmp_path, project_name="Demo", with_rules=True,
            lang="en", force=False, upgrade=False, dry_run=False,
        )

        bootstrap.bootstrap_project(
            project_dir=tmp_path, project_name="Demo", with_rules=True,
            lang="en", force=True, upgrade=False, dry_run=False,
        )

        upgrades = tmp_path / ".claude" / ".upgrades"
        assert not list(upgrades.rglob("*.mine"))

    def test_a_hand_broken_manifest_does_not_crash_the_run(self, tmp_path, monkeypatch):
        """A hand-edited .manifest.json can carry "files": null."""
        _stub_external(monkeypatch)
        _modified_rule(tmp_path, text="my own standard\n")
        (tmp_path / ".claude" / ".manifest.json").write_text(
            '{"version": "3.7.0", "files": null}', encoding="utf-8")

        rc = bootstrap.bootstrap_project(
            project_dir=tmp_path, project_name="Demo", with_rules=True,
            lang="en", force=True, upgrade=False, dry_run=False,
        )

        assert rc == 0
        mine = tmp_path / ".claude" / ".upgrades" / "rules" / "implementation-standard.md.mine"
        assert mine.exists()

    def test_a_file_that_cannot_be_read_is_not_a_crash(self, tmp_path):
        """The docstring promises this; the hashing call used to sit outside the try.

        A directory where we ship a file is the honest way to make the read
        fail on every platform — no mock required.
        """
        dest = tmp_path / "rules" / "x.md"
        dest.mkdir(parents=True)

        assert _installer(tmp_path).keep_theirs("rules/x.md", dest) is False


# ============================================================================
# The project-discovery skill is a prompt, not enforcement code
# ============================================================================
# It used to be rmtree + copytree, "always overwrite — our code". SKILL.md is
# text people tune the way they tune a rule, and it is now asked about exactly
# like one, above. What only a directory can do is carry a file we never
# shipped — and that file was deleted with no copy, on a plain run, no flags.


SKILL_KEY = "skills/project-discovery/SKILL.md"


def _installed_skill(tmp_path, text="MY OWN discovery prompt\n"):
    """A project where the user has edited SKILL.md and left a file beside it."""
    skill = tmp_path / ".claude" / "skills" / "project-discovery"
    skill.mkdir(parents=True)
    write_verbatim(skill / "SKILL.md", text)
    write_verbatim(skill / "our-notes.md", "notes I keep here\n")
    return {"files": {SKILL_KEY: "sha256:something-else"}}


class TestSkillIsNotBulldozed:
    def test_a_file_of_yours_beside_it_survives(self, tmp_path):
        manifest = _installed_skill(tmp_path)

        _copy_rules(tmp_path, manifest, force=False, dry_run=False)

        notes = tmp_path / ".claude" / "skills" / "project-discovery" / "our-notes.md"
        assert notes.exists(), "a file we never shipped was deleted"
        assert read_verbatim(notes) == "notes I keep here\n"


# ============================================================================
# Something a person made stands where one of our files goes
# ============================================================================
# A directory named like a file we ship, or a plain file named like one of our
# directories. Hashing the first raised, creating the second raised, and the
# traceback took the whole run down with it — settings.json, CLAUDE.md and the
# manifest were never written, so half an upgrade was applied and the person
# was left with a stack trace instead of a sentence.


def _run_bootstrap(tmp_path, monkeypatch, **kw):
    """A full run with only the steps that leave the process stubbed out."""
    _stub_external(monkeypatch)
    monkeypatch.setattr("builtins.input", _explode)
    opts = dict(project_name="Demo", with_rules=True, lang="en",
                force=False, upgrade=False, dry_run=False)
    opts.update(kw)
    return bootstrap.bootstrap_project(project_dir=tmp_path, **opts)


def _finished(tmp_path):
    """Both of these land after every copy step: proof the run was not cut off."""
    return ((tmp_path / ".claude" / "settings.json").exists()
            and load_manifest(tmp_path).get("installed_at") is not None)


@pytest.mark.parametrize("kind", list(MANAGED))
class TestADirectoryWhereOurFileGoes:
    def test_the_rest_of_the_upgrade_still_lands(self, tmp_path, kind, monkeypatch):
        """The manifest knowing the key is what sent should_update_file hashing."""
        rel_key = MANAGED[kind]
        (tmp_path / ".claude" / rel_key).mkdir(parents=True)
        save_manifest(tmp_path, {"files": {rel_key: "sha256:whatever"}})

        rc = _run_bootstrap(tmp_path, monkeypatch)

        assert rc == 0
        assert _finished(tmp_path), "the upgrade stopped half-way"

    def test_what_is_inside_it_is_untouched(self, tmp_path, kind, monkeypatch):
        rel_key = MANAGED[kind]
        theirs = tmp_path / ".claude" / rel_key
        theirs.mkdir(parents=True)
        write_verbatim(theirs / "note.txt", "a file they put there\n")
        save_manifest(tmp_path, {"files": {rel_key: "sha256:whatever"}})

        _run_bootstrap(tmp_path, monkeypatch)

        assert theirs.is_dir(), "we replaced a directory of theirs with our file"
        assert read_verbatim(theirs / "note.txt") == "a file they put there\n"

    def test_force_does_not_reach_the_write(self, tmp_path, kind, monkeypatch):
        """--force answers before the manifest is read, so it used to crash on
        the write itself rather than on the hash."""
        rel_key = MANAGED[kind]
        theirs = tmp_path / ".claude" / rel_key
        theirs.mkdir(parents=True)

        rc = _run_bootstrap(tmp_path, monkeypatch, force=True)

        assert rc == 0
        assert theirs.is_dir()
        assert _finished(tmp_path), "the upgrade stopped half-way"

    def test_a_preview_says_so_too(self, tmp_path, kind, monkeypatch):
        rel_key = MANAGED[kind]
        (tmp_path / ".claude" / rel_key).mkdir(parents=True)
        save_manifest(tmp_path, {"files": {rel_key: "sha256:whatever"}})
        before = _snapshot(tmp_path)

        rc = _run_bootstrap(tmp_path, monkeypatch, dry_run=True)

        assert rc == 0
        assert _snapshot(tmp_path) == before

    def test_the_closing_report_names_it(self, tmp_path, kind, monkeypatch, capsys):
        rel_key = MANAGED[kind]
        (tmp_path / ".claude" / rel_key).mkdir(parents=True)

        _run_bootstrap(tmp_path, monkeypatch, force=True)

        out = capsys.readouterr().out
        assert "we could not install" in out
        assert rel_key in out.split("we could not install")[1]


class TestAFileWhereOurDirectoryGoes:
    """The blocker is not the destination but one of its parents, so a check on
    the destination alone would walk straight past it."""

    @pytest.mark.parametrize("rel_dir", ["rules", "agents", "hooks",
                                         "skills/project-discovery"])
    def test_the_rest_of_the_upgrade_still_lands(self, tmp_path, monkeypatch,
                                                 rel_dir):
        blocker = tmp_path / ".claude" / rel_dir
        blocker.parent.mkdir(parents=True, exist_ok=True)
        write_verbatim(blocker, "a file they put there\n")

        rc = _run_bootstrap(tmp_path, monkeypatch)

        assert rc == 0
        assert _finished(tmp_path), "the upgrade stopped half-way"
        assert read_verbatim(blocker) == "a file they put there\n"


class TestADirectoryWhereClaudeMdGoes:
    """CLAUDE.md never goes through Installer.install, so it needs its own."""

    def test_the_rest_of_the_upgrade_still_lands(self, tmp_path, monkeypatch):
        (tmp_path / "CLAUDE.md").mkdir()

        rc = _run_bootstrap(tmp_path, monkeypatch)

        assert rc == 0
        assert (tmp_path / "CLAUDE.md").is_dir()
        assert _finished(tmp_path), "the upgrade stopped half-way"

    def test_it_is_named_in_the_closing_report(self, tmp_path, monkeypatch, capsys):
        (tmp_path / "CLAUDE.md").mkdir()

        _run_bootstrap(tmp_path, monkeypatch)

        out = capsys.readouterr().out
        assert "CLAUDE.md" in out.split("we could not install")[1]


class TestAFileEditedIntoInvalidUtf8:
    """Reported with pzd, but every read of the user's file was already
    wrapped; the loops read our own template, which is always valid UTF-8."""

    def test_a_plain_run_keeps_it_and_carries_on(self, tmp_path, monkeypatch):
        rules = tmp_path / ".claude" / "rules"
        rules.mkdir(parents=True)
        theirs = rules / "tdd-workflow.md"
        theirs.write_bytes(b"\xff\xfe not utf-8 \x80\n")
        save_manifest(tmp_path, {"files": {"rules/tdd-workflow.md": "sha256:stale"}})

        rc = _run_bootstrap(tmp_path, monkeypatch)

        assert rc == 0
        assert theirs.read_bytes() == b"\xff\xfe not utf-8 \x80\n"
        assert _finished(tmp_path)

    def test_force_replaces_it_without_a_crash(self, tmp_path, monkeypatch):
        """The copy aside cannot be made — decoding it is what fails — and
        --force still means take ours."""
        rules = tmp_path / ".claude" / "rules"
        rules.mkdir(parents=True)
        theirs = rules / "tdd-workflow.md"
        theirs.write_bytes(b"\xff\xfe not utf-8 \x80\n")

        rc = _run_bootstrap(tmp_path, monkeypatch, force=True)

        assert rc == 0
        assert "TDD" in read_verbatim(theirs)
        assert _finished(tmp_path)


# ============================================================================
# The write paths that do not go through install()
# ============================================================================
# copy_hooks, _install_settings and setup_gitignore each write on their own, and
# .claude/.upgrades is written to from two more places. A check inside install()
# does nothing for any of them.


class TestAHookThatIsADirectory:
    def test_the_rest_of_the_upgrade_still_lands(self, tmp_path, monkeypatch):
        theirs = tmp_path / ".claude" / "hooks" / "bash-guard.cjs"
        theirs.mkdir(parents=True)

        rc = _run_bootstrap(tmp_path, monkeypatch)

        assert rc == 0
        assert theirs.is_dir()
        assert _finished(tmp_path), "the upgrade stopped half-way"

    def test_the_other_hooks_are_still_installed(self, tmp_path, monkeypatch):
        (tmp_path / ".claude" / "hooks" / "bash-guard.cjs").mkdir(parents=True)

        _run_bootstrap(tmp_path, monkeypatch)

        assert (tmp_path / ".claude" / "hooks" / "session-start.cjs").is_file()


class TestSettingsJsonThatIsADirectory:
    def test_ours_is_not_filed_inside_theirs(self, tmp_path, monkeypatch):
        """shutil.copy2 onto a directory copies into it, quietly and wrongly."""
        theirs = tmp_path / ".claude" / "settings.json"
        theirs.mkdir(parents=True)

        rc = _run_bootstrap(tmp_path, monkeypatch)

        assert rc == 0
        assert list(theirs.iterdir()) == [], "we filed our settings inside theirs"
        assert _finished(tmp_path), "the upgrade stopped half-way"


class TestAManifestThatIsADirectory:
    """The last write of the run, and the record of which files are ours."""

    def test_the_run_says_so_instead_of_crashing(self, tmp_path, monkeypatch,
                                                 capsys):
        (tmp_path / '.claude' / '.manifest.json').mkdir(parents=True)

        rc = _run_bootstrap(tmp_path, monkeypatch)

        assert rc == 1
        assert (tmp_path / '.claude' / '.manifest.json').is_dir()
        out = capsys.readouterr().out
        assert 'could not write .claude/.manifest.json' in out

    def test_everything_else_was_still_installed(self, tmp_path, monkeypatch):
        (tmp_path / '.claude' / '.manifest.json').mkdir(parents=True)

        _run_bootstrap(tmp_path, monkeypatch)

        assert (tmp_path / '.claude' / 'settings.json').is_file()
        assert (tmp_path / 'CLAUDE.md').is_file()


class TestAGitignoreThatIsADirectory:
    def test_the_rest_of_the_upgrade_still_lands(self, tmp_path, monkeypatch):
        theirs = tmp_path / ".gitignore"
        theirs.mkdir()

        rc = _run_bootstrap(tmp_path, monkeypatch)

        assert rc == 0
        assert theirs.is_dir()
        assert _finished(tmp_path), "the upgrade stopped half-way"


class TestClaudeItselfIsAFile:
    """Not a clash to work around: it is every file at once, and the manifest
    we write at the end would have nowhere to go either."""

    def test_the_run_stops_with_a_sentence(self, tmp_path, monkeypatch, capsys):
        theirs = tmp_path / ".claude"
        write_verbatim(theirs, "not a directory\n")

        rc = _run_bootstrap(tmp_path, monkeypatch)

        assert rc == 1
        assert read_verbatim(theirs) == "not a directory\n"
        out = capsys.readouterr().out
        assert "is a file, not a directory" in out
        assert "Move it aside" in out


# ---------------------------------------------------------------------------
# .claude/.upgrades is where every version that loses is parked. If it cannot
# hold anything, the promise cannot be kept — and the answer is to touch
# nothing, not to overwrite and hope.


def _upgrades_blocked(tmp_path, rule_text="mine\n"):
    """A project with an edited rule and nowhere to park a copy of it."""
    rules = tmp_path / ".claude" / "rules"
    rules.mkdir(parents=True)
    write_verbatim(rules / "tdd-workflow.md", rule_text)
    write_verbatim(tmp_path / ".claude" / ".upgrades", "not a directory\n")
    save_manifest(tmp_path, {"files": {"rules/tdd-workflow.md": "sha256:stale"}})
    return rules / "tdd-workflow.md"


class TestNowhereToParkTheLosingVersion:
    def test_keeping_yours_still_finishes_the_run(self, tmp_path, monkeypatch):
        """Ours is the version that cannot be parked here, and ours ships with
        the package — so the run says so and carries on."""
        theirs = _upgrades_blocked(tmp_path)

        rc = _run_bootstrap(tmp_path, monkeypatch)

        assert rc == 0
        assert read_verbatim(theirs) == "mine\n"
        assert _finished(tmp_path), "the upgrade stopped half-way"

    def test_force_does_not_overwrite_what_it_cannot_save(self, tmp_path,
                                                          monkeypatch):
        """The one outcome this whole file exists to prevent. --force used to
        swallow the failed copy and write over the edit regardless."""
        theirs = _upgrades_blocked(tmp_path)

        rc = _run_bootstrap(tmp_path, monkeypatch, force=True)

        assert rc == 0
        assert read_verbatim(theirs) == "mine\n", "the edit was destroyed"
        assert _finished(tmp_path), "the upgrade stopped half-way"

    def test_it_is_named_in_the_closing_report(self, tmp_path, monkeypatch,
                                               capsys):
        _upgrades_blocked(tmp_path)

        _run_bootstrap(tmp_path, monkeypatch, force=True)

        out = capsys.readouterr().out
        assert "rules/tdd-workflow.md" in out.split("we could not install")[1]

    def test_a_file_we_can_park_is_still_installed(self, tmp_path, monkeypatch):
        """Only the file whose copy failed is held back, not the whole run."""
        _upgrades_blocked(tmp_path)

        _run_bootstrap(tmp_path, monkeypatch, force=True)

        assert "IMPLEMENTATION STANDARD" in read_verbatim(
            tmp_path / ".claude" / "rules" / "implementation-standard.md")


# ============================================================================
# .upgrades/<path>.mine keeps every version it was handed
# ============================================================================
# Our version in .upgrades/<path> can be a single slot — it ships with the
# package and is always recoverable. Theirs is not.


class TestReplacedVersionsAccumulate:
    def test_a_second_different_version_does_not_clobber_the_first(self, tmp_path):
        bootstrap.save_replaced_version(tmp_path, "rules/x.md", "edit A\n")
        bootstrap.save_replaced_version(tmp_path, "rules/x.md", "edit B\n")

        saved = sorted(p.name for p in
                       (tmp_path / ".claude" / ".upgrades" / "rules").iterdir())
        assert len(saved) == 2, saved
        contents = {read_verbatim(tmp_path / ".claude" / ".upgrades" / "rules" / n)
                    for n in saved}
        assert contents == {"edit A\n", "edit B\n"}
        assert read_verbatim(
            tmp_path / ".claude" / ".upgrades" / "rules" / "x.md.mine") == "edit B\n"

    def test_a_failed_write_does_not_cost_you_the_older_copy(self, tmp_path, monkeypatch):
        """Nothing is destroyed before the copy that replaces it exists."""
        bootstrap.save_replaced_version(tmp_path, "rules/x.md", "edit A\n")
        mine = tmp_path / ".claude" / ".upgrades" / "rules" / "x.md.mine"
        real = bootstrap.write_verbatim

        def fail_on_the_spare(path, text):
            if path != mine:
                raise PermissionError("locked")
            return real(path, text)

        monkeypatch.setattr(bootstrap, "write_verbatim", fail_on_the_spare)

        with pytest.raises(PermissionError):
            bootstrap.save_replaced_version(tmp_path, "rules/x.md", "edit B\n")

        assert read_verbatim(mine) == "edit A\n", "the older copy was destroyed"

    def test_an_unreadable_older_copy_is_left_where_it_is(self, tmp_path):
        """Bytes we cannot decode are still the user's text — put ours beside them."""
        mine = tmp_path / ".claude" / ".upgrades" / "rules" / "x.md.mine"
        mine.parent.mkdir(parents=True)
        mine.write_bytes(b"\xff\xfe not utf-8 at all")

        bootstrap.save_replaced_version(tmp_path, "rules/x.md", "edit B\n")

        assert mine.read_bytes() == b"\xff\xfe not utf-8 at all"
        saved = [p for p in mine.parent.iterdir() if p != mine]
        assert len(saved) == 1 and read_verbatim(saved[0]) == "edit B\n"

    def test_the_same_version_twice_leaves_one_file(self, tmp_path):
        bootstrap.save_replaced_version(tmp_path, "rules/x.md", "same\n")
        bootstrap.save_replaced_version(tmp_path, "rules/x.md", "same\n")

        saved = list((tmp_path / ".claude" / ".upgrades" / "rules").iterdir())
        assert len(saved) == 1, [p.name for p in saved]

    def test_two_rounds_of_force_keep_both_edits(self, tmp_path, monkeypatch):
        _stub_external(monkeypatch)
        rule = tmp_path / ".claude" / "rules" / "implementation-standard.md"

        def force_run():
            bootstrap.bootstrap_project(
                project_dir=tmp_path, project_name="Demo", with_rules=True,
                lang="en", force=True, upgrade=False, dry_run=False,
            )

        force_run()
        write_verbatim(rule, "EDIT A: six months of tuning\n")
        force_run()
        write_verbatim(rule, "EDIT B: a different note\n")
        force_run()

        kept = {read_verbatim(p) for p in
                (tmp_path / ".claude" / ".upgrades" / "rules").iterdir() if p.is_file()}
        assert "EDIT A: six months of tuning\n" in kept, "the first edit was clobbered"
        assert "EDIT B: a different note\n" in kept


# ============================================================================
# --dry-run and beads
# ============================================================================
# Every copy step honours the flag; install_beads never took it, so a preview
# of a project without .beads/ created the directory and shelled out to bd.


class _FakeRun:
    returncode = 0
    stdout = ""
    stderr = ""


class TestDryRunDoesNotInstallBeads:
    def test_preview_neither_creates_beads_nor_shells_out(self, tmp_path, monkeypatch):
        ran = []
        monkeypatch.setattr(bootstrap.subprocess, "run",
                            lambda cmd, *a, **kw: ran.append(cmd) or _FakeRun())
        monkeypatch.setattr(bootstrap.shutil, "which", lambda name: "bd")
        monkeypatch.setattr(bootstrap, "run_bd_doctor", lambda pd: None)

        rc = bootstrap.bootstrap_project(
            project_dir=tmp_path, project_name="Demo", with_rules=True,
            lang="en", force=False, upgrade=False, dry_run=True,
        )

        assert rc == 0
        assert ran == [], f"a preview ran {ran}"
        assert list(tmp_path.rglob("*")) == [], "a preview created files"

    def test_preview_does_not_create_the_project_directory(self, tmp_path, monkeypatch):
        """Zero bytes is not zero writes: the mkdir ran before the flag was read."""
        monkeypatch.setattr(bootstrap.subprocess, "run",
                            lambda cmd, *a, **kw: _FakeRun())
        monkeypatch.setattr(bootstrap.shutil, "which", lambda name: "bd")
        monkeypatch.setattr(bootstrap, "run_bd_doctor", lambda pd: None)
        target = tmp_path / "not" / "there" / "yet"

        rc = bootstrap.bootstrap_project(
            project_dir=target, project_name="Demo", with_rules=True,
            lang="en", force=False, upgrade=False, dry_run=True,
        )

        assert rc == 0
        assert not target.exists()

    def test_a_real_run_still_installs(self, tmp_path, monkeypatch):
        ran = []

        def fake_run(cmd, *a, **kw):
            ran.append(cmd)
            # `bd init` is what creates .beads/, and install_beads now checks
            # that it really did rather than trusting the exit code.
            if list(cmd)[:2] == ["bd", "init"]:
                Path(kw["cwd"], ".beads").mkdir(parents=True, exist_ok=True)
            return _FakeRun()

        monkeypatch.setattr(bootstrap.subprocess, "run", fake_run)
        monkeypatch.setattr(bootstrap.shutil, "which", lambda name: "bd")

        assert bootstrap.install_beads(tmp_path) is True
        assert ran, "a real run did not call bd at all"


# ============================================================================
# --all: a batch upgrade does not interrogate
# ============================================================================
# README has always said a batch upgrade keeps your files and saves ours beside
# them. The code only checked isatty, so upgrading twenty projects from your own
# terminal meant twenty rounds of questions.


class TestBatchUpgradeDoesNotAsk:
    def _run(self, tmp_path, monkeypatch, force=False):
        (tmp_path / "proj" / ".beads").mkdir(parents=True, exist_ok=True)
        prompts = []
        monkeypatch.setattr(bootstrap, "_stdin_is_a_person", lambda: True)
        _stub_heavy_steps(monkeypatch)

        def record(with_rules, lang, installer, **kwargs):
            prompts.append(installer.prompt)

        monkeypatch.setattr(bootstrap, "copy_rules_and_skills", record)
        bootstrap.run_batch_upgrade(tmp_path, True, "en", force, False)
        assert len(prompts) == 1
        return prompts[0]

    def test_no_questions_even_at_a_terminal(self, tmp_path, monkeypatch):
        prompt = self._run(tmp_path, monkeypatch)

        assert not prompt.will_ask
        assert prompt.ask("rules/x.md", tmp_path, "ours") == bootstrap.ConflictPrompt.KEEP

    def test_force_still_takes_ours(self, tmp_path, monkeypatch):
        prompt = self._run(tmp_path, monkeypatch, force=True)

        assert not prompt.will_ask
        assert prompt.ask("rules/x.md", tmp_path, "ours") == bootstrap.ConflictPrompt.TAKE

    def test_the_banner_says_what_will_actually_happen(self, tmp_path, monkeypatch,
                                                       capsys):
        """One line tells the operator what is about to hit twenty projects."""
        self._run(tmp_path, monkeypatch)
        kept = capsys.readouterr().out

        self._run(tmp_path, monkeypatch, force=True)
        forced = capsys.readouterr().out

        assert "Files you edited are kept" in kept
        assert "Files you edited are kept" not in forced, "banner contradicts --force"
        assert "Taking our version of every file" in forced


class TestClaudeMdDryRunWritesNothing:
    def _start(self, tmp_path, kind):
        if kind == "installed":
            return _installed_project(tmp_path)
        if kind == "legacy":
            write_verbatim(tmp_path / "CLAUDE.md", LEGACY_CLAUDE_MD)
        elif kind == "plain":
            write_verbatim(tmp_path / "CLAUDE.md", "# Demo\n\n## Build\n\nmake all\n")
        elif kind == "unknown":
            write_verbatim(tmp_path / "CLAUDE.md",
                           "# Mine\n\n## Workflow\n\nbeads all the way\n")
        return {"files": {}}

    @pytest.mark.parametrize("kind",
                             ["missing", "installed", "legacy", "plain", "unknown"])
    def test_every_path_writes_nothing(self, tmp_path, monkeypatch, kind):
        manifest = self._start(tmp_path, kind)
        monkeypatch.setattr("builtins.input", _explode)
        before = _snapshot(tmp_path)

        _claude_md(tmp_path, manifest, asks=False, dry_run=True)

        after = _snapshot(tmp_path)
        assert after == before
        assert ("CLAUDE.md" in manifest.get("regions", {})) is (kind == "installed")


# ============================================================================
# Plugin manifests
# ============================================================================
# The repository is both a marketplace and the plugin it lists: .claude-plugin/
# holds marketplace.json and plugin.json side by side, and the plugin manifest
# points at directories that already exist (templates/agents, templates/hooks)
# rather than a second copy of them. Two copies of a hook would drift.

REPO_ROOT = bootstrap.SCRIPT_DIR
PLUGIN_DIR = REPO_ROOT / ".claude-plugin"


def _read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


class TestPluginManifests:
    def test_both_manifests_parse(self):
        assert _read_json(PLUGIN_DIR / "marketplace.json")["name"] == "claude-protocol"
        assert _read_json(PLUGIN_DIR / "plugin.json")["name"] == "claude-protocol"

    def test_the_marketplace_lists_this_repository_as_the_plugin(self):
        entries = _read_json(PLUGIN_DIR / "marketplace.json")["plugins"]

        assert len(entries) == 1
        assert entries[0]["source"] == "./"

    def test_one_version_in_three_places(self):
        """A marketplace entry whose version does not grow leaves every user on
        the copy in their cache, so the three files have to move together."""
        pkg = _read_json(REPO_ROOT / "package.json")["version"]
        market = _read_json(PLUGIN_DIR / "marketplace.json")

        assert _read_json(PLUGIN_DIR / "plugin.json")["version"] == pkg
        assert market["metadata"]["version"] == pkg
        assert market["plugins"][0]["version"] == pkg

    @pytest.mark.parametrize("key", ["agents", "commands", "skills"])
    def test_every_declared_path_exists(self, key):
        declared = _read_json(PLUGIN_DIR / "plugin.json")[key]
        paths = declared if isinstance(declared, list) else [declared]

        for path in paths:
            assert (REPO_ROOT / path).exists(), \
                f"plugin.json points {key} at {path}, which is not there"

    def test_the_manifest_leaves_the_standard_hooks_file_alone(self):
        """Claude Code loads hooks/hooks.json at the plugin root by itself, and
        the manifest field is for hook files BESIDES that one. Naming it there
        made every plugin load report 'Duplicate hooks file detected' — the
        automatic load won, the manifest one failed, and the noise reached
        everyone who installed the plugin."""
        declared = _read_json(PLUGIN_DIR / "plugin.json").get("hooks")
        paths = [] if declared is None else (
            declared if isinstance(declared, list) else [declared])

        standard = (REPO_ROOT / "hooks" / "hooks.json").resolve()
        for path in paths:
            assert (REPO_ROOT / path).resolve() != standard, \
                "plugin.json declares the hooks file Claude Code already loads"

    def test_the_manifest_lists_every_agent_we_ship(self):
        """`claude plugin validate` rejects a directory here, so agents are
        listed one file at a time — and a new agent is then one edit away from
        shipping through npx and not through the plugin."""
        declared = {Path(p).name
                    for p in _read_json(PLUGIN_DIR / "plugin.json")["agents"]}
        on_disk = {p.name for p in (REPO_ROOT / "templates" / "agents").glob("*.md")}

        assert declared == on_disk, "plugin.json and templates/agents disagree"

    def test_hooks_json_runs_files_that_are_there(self):
        hooks = _read_json(REPO_ROOT / "hooks" / "hooks.json")["hooks"]

        assert set(hooks) == {"PreToolUse", "SubagentStop", "SessionStart"}
        for groups in hooks.values():
            for group in groups:
                for hook in group["hooks"]:
                    command = hook["command"]
                    found = re.search(r"\$\{CLAUDE_PLUGIN_ROOT\}/([^\"]+)", command)
                    assert found, f"hook command without a plugin root: {command}"
                    assert (REPO_ROOT / found.group(1)).exists(), \
                        f"hooks.json runs {found.group(1)}, which is not there"

    def test_the_package_ships_what_the_plugin_needs(self):
        """A plugin installed from npm is the published package: a directory
        left out of `files` simply is not there."""
        shipped = _read_json(REPO_ROOT / "package.json")["files"]

        for needed in (".claude-plugin/", "hooks/", "templates/"):
            assert needed in shipped, f"package.json does not ship {needed}"


# ============================================================================
# --project-only: the half a plugin cannot carry
# ============================================================================
# Installed as a plugin, Claude Code loads the hooks, agents and skill itself.
# Hooks merge from every source, so a copy left in the project does not sit
# quietly beside the plugin — every hook fires twice.


class TestProjectOnlyInstall:
    def _install(self, tmp_path, monkeypatch, **kwargs):
        monkeypatch.setattr(bootstrap, "install_beads", lambda pd, *a, **kw: True)
        monkeypatch.setattr(bootstrap, "run_bd_doctor", lambda pd: None)
        return bootstrap.bootstrap_project(
            project_dir=tmp_path, project_name="Demo", with_rules=True,
            lang="en", force=False, upgrade=False, dry_run=False, **kwargs,
        )

    def test_it_installs_only_what_the_plugin_cannot_carry(self, tmp_path, monkeypatch):
        assert self._install(tmp_path, monkeypatch, project_only=True) == 0

        claude = tmp_path / ".claude"
        assert (claude / "rules" / "beads-workflow.md").exists()
        assert (tmp_path / "CLAUDE.md").exists()
        for carried_by_the_plugin in ("hooks", "agents", "skills", "settings.json"):
            assert not (claude / carried_by_the_plugin).exists(), \
                f"{carried_by_the_plugin} is the plugin's job now"

    def test_a_plain_install_still_brings_everything(self, tmp_path, monkeypatch):
        assert self._install(tmp_path, monkeypatch) == 0

        claude = tmp_path / ".claude"
        for rel in ("hooks", "agents", "skills", "settings.json", "rules"):
            assert (claude / rel).exists(), f"a plain install lost {rel}"

    def test_it_takes_over_from_an_earlier_npx_install(self, tmp_path, monkeypatch, capsys):
        assert self._install(tmp_path, monkeypatch) == 0
        assert list((tmp_path / ".claude" / "hooks").glob("*.cjs"))
        capsys.readouterr()

        assert self._install(tmp_path, monkeypatch, project_only=True) == 0

        claude = tmp_path / ".claude"
        assert not list((claude / "hooks").glob("*.cjs")), "hooks would fire twice"
        assert not list((claude / "agents").glob("*.md"))
        assert (claude / "rules" / "beads-workflow.md").exists(), "rules are ours to keep"
        assert "Handed over to the plugin" in capsys.readouterr().out

    def test_taking_over_unwires_the_hooks_from_settings(self, tmp_path, monkeypatch):
        self._install(tmp_path, monkeypatch)
        settings_path = tmp_path / ".claude" / "settings.json"
        before = json.loads(settings_path.read_text(encoding="utf-8"))
        assert _hook_commands(before), "the fixture has no hooks to unwire"

        self._install(tmp_path, monkeypatch, project_only=True)

        after = json.loads(settings_path.read_text(encoding="utf-8"))
        assert _hook_commands(after) == []

    def test_it_leaves_alone_a_file_it_did_not_install(self, tmp_path, monkeypatch):
        """The manifest is the gate: a file with one of our names that we never
        wrote belongs to whoever put it there."""
        hooks = tmp_path / ".claude" / "hooks"
        hooks.mkdir(parents=True)
        theirs = hooks / "bash-guard.cjs"
        theirs.write_text("// not ours\n", encoding="utf-8")

        assert self._install(tmp_path, monkeypatch, project_only=True) == 0

        assert theirs.read_text(encoding="utf-8") == "// not ours\n"


def _hook_commands(settings: dict) -> list:
    return [hook["command"]
            for entries in (settings.get("hooks") or {}).values()
            for entry in entries
            for hook in entry.get("hooks", [])]


class TestPluginProvidedPaths:
    def test_it_is_derived_from_what_we_ship(self):
        """Listed by hand, a new hook could be provided by the plugin and left
        behind in projects at the same time."""
        rels = set(bootstrap.plugin_provided_relpaths())

        for hook in (bootstrap.TEMPLATES_DIR / "hooks").glob("*.cjs"):
            assert f".claude/hooks/{hook.name}" in rels
        for agent in (bootstrap.TEMPLATES_DIR / "agents").glob("*.md"):
            assert f".claude/agents/{agent.name}" in rels
        assert ".claude/skills/project-discovery/SKILL.md" in rels

    def test_it_claims_nothing_that_lives_in_the_project(self):
        rels = bootstrap.plugin_provided_relpaths()

        assert not [r for r in rels if r.startswith(".claude/rules/")]
        assert "CLAUDE.md" not in rels

    def test_the_paths_are_the_ones_cleanup_can_find(self):
        """_cleanup_file resolves against the project root and translates to
        the manifest key itself. Handing it a manifest key instead removed
        nothing and dropped the manifest entry on the way out."""
        for rel in bootstrap.plugin_provided_relpaths():
            assert rel.startswith(".claude/"), rel
            assert (bootstrap.SCRIPT_DIR / "templates"
                    / rel[len(".claude/"):]).exists() or "skills/" in rel


# ============================================================================
# CLAUDE.md ships in both languages
# ============================================================================
# The rules already did; CLAUDE.md did not. A project installed with --lang ru
# got Russian rules sitting next to English orchestrator instructions.

CLAUDE_EN = TEMPLATES_DIR / "CLAUDE.md"
CLAUDE_RU = TEMPLATES_DIR / "CLAUDE-ru.md"


class TestClaudeMdTemplates:
    def test_both_templates_ship(self):
        assert CLAUDE_EN.exists()
        assert CLAUDE_RU.exists()

    def test_the_english_one_is_in_english(self):
        assert not _cyrillic(CLAUDE_EN.read_text(encoding="utf-8"))

    def test_the_russian_one_is_translated(self):
        assert _cyrillic(CLAUDE_RU.read_text(encoding="utf-8"))

    @pytest.mark.parametrize("path", [CLAUDE_EN, CLAUDE_RU], ids=["en", "ru"])
    def test_both_keep_the_managed_block_markers(self, path):
        """Without the markers an upgrade cannot tell our block from the text
        around it, and hands the whole template over instead of refreshing."""
        assert bootstrap.marked_span(path.read_text(encoding="utf-8")) is not None

    @pytest.mark.parametrize("path", [CLAUDE_EN, CLAUDE_RU], ids=["en", "ru"])
    def test_both_keep_the_project_placeholder(self, path):
        assert "[Project]" in path.read_text(encoding="utf-8")


class TestClaudeMdFollowsTheLanguage:
    def _install(self, tmp_path, monkeypatch, lang):
        monkeypatch.setattr(bootstrap, "install_beads", lambda pd, *a, **kw: True)
        monkeypatch.setattr(bootstrap, "run_bd_doctor", lambda pd: None)
        bootstrap.bootstrap_project(
            project_dir=tmp_path, project_name="Demo", with_rules=True,
            lang=lang, force=False, upgrade=False, dry_run=False,
        )
        return (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")

    def test_ru_installs_the_russian_one(self, tmp_path, monkeypatch):
        assert _cyrillic(self._install(tmp_path, monkeypatch, "ru"))

    def test_en_installs_the_english_one(self, tmp_path, monkeypatch):
        assert not _cyrillic(self._install(tmp_path, monkeypatch, "en"))

    def test_the_project_name_still_lands_in_it(self, tmp_path, monkeypatch):
        text = self._install(tmp_path, monkeypatch, "ru")

        assert "Demo" in text
        assert "[Project]" not in text

    def test_the_language_is_remembered_for_the_next_upgrade(self, tmp_path, monkeypatch):
        """--lang is optional on an upgrade, and the manifest is what keeps a
        project from silently switching back to English."""
        self._install(tmp_path, monkeypatch, "ru")

        manifest = json.loads(
            (tmp_path / ".claude" / ".manifest.json").read_text(encoding="utf-8"))

        assert manifest["lang"] == "ru"



# ============================================================================
# Is the plugin already supplying the hooks here?
# ============================================================================
# npx and the plugin wire the same three hooks, and Claude Code merges hooks
# from every source, so a project carrying both runs each one twice. When the
# plugin is the active source, an npx install stops before the hooks.


def _write_registry(config_dir, contents):
    plugins = config_dir / "plugins"
    plugins.mkdir(parents=True, exist_ok=True)
    path = plugins / "installed_plugins.json"
    path.write_text(contents if isinstance(contents, str) else json.dumps(contents),
                    encoding="utf-8")
    return path


def _registry_with(*entries):
    return {"version": 2, "plugins": {"claude-protocol@claude-protocol": list(entries)}}


class TestPluginActiveFor:
    @pytest.fixture(autouse=True)
    def _config_dir(self, tmp_path, monkeypatch):
        self.config = tmp_path / "config"
        self.config.mkdir()
        self.project = tmp_path / "project"
        self.project.mkdir()
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(self.config))

    def test_a_user_scope_install_covers_every_project(self):
        _write_registry(self.config, _registry_with({"scope": "user"}))

        assert plugin_active_for(self.project) is True

    def test_a_project_scope_install_covers_the_project_it_names(self):
        _write_registry(self.config, _registry_with(
            {"scope": "project", "projectPath": str(self.project)}))

        assert plugin_active_for(self.project) is True

    def test_a_project_scope_install_covers_no_other_project(self, tmp_path):
        other = tmp_path / "other"
        other.mkdir()
        _write_registry(self.config, _registry_with(
            {"scope": "project", "projectPath": str(other)}))

        assert plugin_active_for(self.project) is False

    def test_a_trailing_separator_is_the_same_directory(self):
        _write_registry(self.config, _registry_with(
            {"scope": "project", "projectPath": str(self.project) + os.sep}))

        assert plugin_active_for(self.project) is True

    def test_other_plugins_are_not_this_one(self):
        _write_registry(self.config, {"version": 2, "plugins": {
            "feature-dev@somewhere": [{"scope": "user"}]}})

        assert plugin_active_for(self.project) is False

    def test_a_name_that_merely_starts_the_same_is_not_this_one(self):
        _write_registry(self.config, {"version": 2, "plugins": {
            "claude-protocol-extras@x": [{"scope": "user"}]}})

        assert plugin_active_for(self.project) is False

    def test_no_registry_at_all(self):
        assert plugin_active_for(self.project) is False

    def test_a_registry_that_is_not_json(self):
        _write_registry(self.config, "not json {{{")

        assert plugin_active_for(self.project) is False

    @pytest.mark.parametrize("registry", [
        {"version": 9},
        {"plugins": "nope"},
        {"version": 2, "plugins": {"claude-protocol@x": "nope"}},
        {"version": 2, "plugins": {"claude-protocol@x": [None, 7]}},
        _registry_with(),
    ])
    def test_a_shape_we_do_not_recognise(self, registry):
        """Fail open, every time. An installer that strips someone's hooks
        because a file it half-understands changed shape is worse than one that
        installs a hook they did not need."""
        _write_registry(self.config, registry)

        assert plugin_active_for(self.project) is False


class TestPluginSwitchedOff:
    """Installed is not enabled. Standing down for a plugin that never runs
    leaves the project with no hooks at all, so an explicit false outranks the
    registry — while a missing entry stays a missing entry, because a
    project-scope install writes none."""

    @pytest.fixture(autouse=True)
    def _config_dir(self, tmp_path, monkeypatch):
        self.config = tmp_path / "config"
        self.config.mkdir()
        self.project = tmp_path / "project"
        (self.project / ".claude").mkdir(parents=True)
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(self.config))
        _write_registry(self.config, _registry_with({"scope": "user"}))

    def _settings(self, where, contents):
        path = (self.config / "settings.json" if where == "user"
                else self.project / ".claude" / where)
        path.write_text(contents if isinstance(contents, str) else json.dumps(contents),
                        encoding="utf-8")

    OFF = {"enabledPlugins": {"claude-protocol@claude-protocol": False}}
    ON = {"enabledPlugins": {"claude-protocol@claude-protocol": True}}

    @pytest.mark.parametrize("where", ["user", "settings.json", "settings.local.json"])
    def test_switched_off_anywhere_means_not_active(self, where):
        self._settings(where, self.OFF)

        assert plugin_active_for(self.project) is False

    def test_switched_on_means_active(self):
        self._settings("user", self.ON)

        assert plugin_active_for(self.project) is True

    def test_settings_saying_nothing_leave_the_registry_to_decide(self):
        self._settings("user", {"permissions": {}})

        assert plugin_active_for(self.project) is True

    def test_settings_we_cannot_read_say_nothing(self):
        self._settings("user", "not json {{{")

        assert plugin_active_for(self.project) is True


class TestFullInstallUnderAnActivePlugin:
    """The half that makes the doubled state impossible to create through npx."""

    @pytest.fixture(autouse=True)
    def _no_beads_needed(self, monkeypatch):
        monkeypatch.setattr(bootstrap, "install_beads", lambda *a, **k: True)
        self.copied = []
        for name in ("copy_hooks", "copy_agents"):
            monkeypatch.setattr(bootstrap, name,
                                lambda *a, _n=name, **k: self.copied.append(_n))

    def _run(self, project_dir):
        return bootstrap.bootstrap_project(
            project_dir, "proj", with_rules=False, lang="en", force=False,
            upgrade=False, dry_run=True,
        )

    def test_a_full_install_leaves_the_hooks_to_the_plugin(self, tmp_path, monkeypatch, capsys):
        config = tmp_path / "config"
        project = tmp_path / "project"
        project.mkdir()
        _write_registry(config, _registry_with(
            {"scope": "project", "projectPath": str(project)}))
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(config))

        assert self._run(project) == 0
        assert self.copied == []
        assert "plugin" in capsys.readouterr().out.lower()

    def test_a_full_install_without_the_plugin_is_unchanged(self, tmp_path, monkeypatch):
        config = tmp_path / "config"
        config.mkdir()
        project = tmp_path / "project"
        project.mkdir()
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(config))

        assert self._run(project) == 0
        assert sorted(self.copied) == ["copy_agents", "copy_hooks"]


class TestPathsSpelledDifferently:
    """Two ways a recorded path can name the right directory in the wrong
    words, and one way it can name nothing at all."""

    @pytest.fixture(autouse=True)
    def _config_dir(self, tmp_path, monkeypatch):
        self.config = tmp_path / "config"
        self.config.mkdir()
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(self.config))

    def test_a_relative_path_matches_nothing(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        project = tmp_path / "somewhere"
        project.mkdir()
        _write_registry(self.config, _registry_with(
            {"scope": "project", "projectPath": "./somewhere"}))

        assert plugin_active_for(project) is False

    def test_a_symlink_is_the_directory_it_points_at(self, tmp_path):
        real = tmp_path / "real"
        real.mkdir()
        link = tmp_path / "as-seen"
        try:
            link.symlink_to(real, target_is_directory=True)
        except (OSError, NotImplementedError):
            pytest.skip("no privilege to create a symlink here")
        _write_registry(self.config, _registry_with(
            {"scope": "project", "projectPath": str(real)}))

        assert plugin_active_for(link) is True


class TestBothSidesReadTheRegistryTheSameWay:
    """The rule lives twice — plugin_active_for here, pluginActiveHere in
    templates/hooks/hook-utils.cjs — because one runs in the installer and the
    other inside a hook. Two copies of a rule in two languages drift silently,
    the way BD_MIN_VERSION would without the test that pins it, so both are
    asked the same questions and have to give the same answers."""

    @pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
    def test_node_and_python_agree(self, tmp_path, monkeypatch):
        utils = Path(__file__).parent.parent / "templates" / "hooks" / "hook-utils.cjs"
        project = tmp_path / "project"
        project.mkdir()
        other = tmp_path / "other"
        other.mkdir()

        cases = [
            ("user-scope", _registry_with({"scope": "user"}), True),
            ("this-project", _registry_with(
                {"scope": "project", "projectPath": str(project)}), True),
            ("another-project", _registry_with(
                {"scope": "project", "projectPath": str(other)}), False),
            ("relative-path", _registry_with(
                {"scope": "project", "projectPath": "./project"}), False),
            ("someone-else", {"version": 2, "plugins": {
                "other@x": [{"scope": "user"}]}}, False),
            ("broken-json", "not json {{{", False),
            ("unknown-shape", {"plugins": "nope"}, False),
        ]

        script = ("const u=require(process.argv[1]);"
                  "process.stdout.write(String(u.pluginActiveHere(process.argv[2])));")
        for name, registry, expected in cases:
            config = tmp_path / f"config-{name}"
            _write_registry(config, registry)
            monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(config))

            node_says = subprocess.run(
                ["node", "-e", script, str(utils), str(project)],
                capture_output=True, text=True, check=True,
                env={**os.environ, "CLAUDE_CONFIG_DIR": str(config),
                     "CLAUDE_PLUGIN_ROOT": ""},
            ).stdout

            assert plugin_active_for(project) is expected, f"python, {name}"
            assert node_says == str(expected).lower(), f"node, {name}"
