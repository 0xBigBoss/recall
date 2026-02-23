# Release Process

## Versioning
- Use semantic versioning.
- Update `packages/recall/pyproject.toml`.
- Update `.claude-plugin/plugin.json` version to match package version.
- Tags use `vX.Y.Z`.

## Checklist
1. Bump version in `packages/recall/pyproject.toml`.
2. Bump version in `.claude-plugin/plugin.json`.
3. Run tests: `uv run pytest`.
4. Run type check: `uvx ty check`.
5. Commit with `chore(release): prepare vX.Y.Z`.
6. Tag: `git tag vX.Y.Z`.
7. Push: `git push origin main --tags`.
8. Create GitHub release with notes.

## Release Notes Template
- Highlights
- Fixes
- Maintenance
- Upgrade notes (if needed)
