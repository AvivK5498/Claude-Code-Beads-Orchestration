# Release Process

## First-time setup

1. `npm login` and `npm publish --access public` — first publish must be manual with OTP
2. On npmjs.com → package Settings → Publishing access → add Trusted Publisher:
   - Repository: `{owner}/{repo}`
   - Workflow: `release.yml`
3. After that — all publishing is automatic via OIDC (no NPM_TOKEN needed)

## How to publish a new version

1. Update version in `package.json`
2. Commit: `git commit -am "release: v3.x.x"`
3. Tag: `git tag v3.x.x`
4. Push: `git push && git push --tags`

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
