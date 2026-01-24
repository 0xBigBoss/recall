# Release Process

## Versioning
- Use semantic versioning.
- Update `packages/recall/pyproject.toml`.
- Tags use `vX.Y.Z`.

## Checklist
1. Bump version in `packages/recall/pyproject.toml`.
2. Run tests: `uv run pytest`.
3. Run type check: `uvx ty check`.
4. Commit with `chore(release): prepare vX.Y.Z`.
5. Tag: `git tag vX.Y.Z`.
6. Push: `git push origin main --tags`.
7. Create GitHub release with notes.

## Release Notes Template
- Highlights
- Fixes
- Maintenance
- Upgrade notes (if needed)
