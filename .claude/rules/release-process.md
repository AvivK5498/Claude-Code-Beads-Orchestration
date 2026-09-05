# Release Process

## First-time setup

1. `npm login` and `npm publish --access public` — first publish must be manual with OTP
2. On npmjs.com → package Settings → Publishing access → add Trusted Publisher:
   - Repository: `{owner}/{repo}`
   - Workflow: `release.yml`
3. After that — all publishing is automatic via OIDC (no NPM_TOKEN needed)

## How to publish a new version

1. Update the version in **three files** — `package.json`,
   `.claude-plugin/plugin.json`, and both `version` fields in
   `.claude-plugin/marketplace.json` (`metadata.version` and the plugin entry).
   A marketplace entry whose version does not grow leaves every plugin user on
   the copy in their cache, so the release simply does not reach them.
   `TestPluginManifests::test_one_version_in_three_places` fails when they
   disagree — run the tests before tagging and it cannot be forgotten.
2. Move the **Unreleased** section of "What Changed in v3" to `### v3.x.x
   (YYYY-MM-DD)` in `README.md` and `README-ru.md`, and start a fresh empty
   Unreleased above it. Nothing else keeps that section current: it once stood
   four releases behind and described a hook that had not existed for months.
3. Commit: `git commit -am "release: v3.x.x"`
4. Tag: `git tag v3.x.x`
5. Push: `git push && git push --tags`

The GitHub release the tag creates is also what the session-start update check
reads, so a version that never becomes a release is a version nobody is told
about.

GitHub Action (`.github/workflows/release.yml`) will:
- Run vitest + pytest
- Publish to npm as `claude-protocol` with provenance (OIDC, no token)
- Create GitHub Release with auto-generated notes

## Versioning

- Patch (3.0.x) — bug fixes, hook tweaks, rule wording
- Minor (3.x.0) — new hooks, new rules, new features
- Major (x.0.0) — breaking changes to bootstrap, hook API, or workflow

## Do NOT

- Publish manually after first time — always through tags
- Create tags without running tests first (`npm test && python -m pytest tests/test_bootstrap.py -v`)
