# Contributing to PortKit

Thanks for helping improve the UE5 → UE 4.27 migration workflow.

## Before opening an issue

- Search existing issues for the same engine version and workflow stage.
- Run a read-only probe first and include the relevant report excerpt.
- Remove usernames, local absolute paths, proprietary asset names and project
  metadata before posting a log.
- State whether the problem occurs in **UE5 export**, **UE 4.27 import**,
  **material transplant**, **placement** or **diagnostics**.

## Pull requests

1. Keep changes focused on one workflow or compatibility issue.
2. Preserve existing config fields unless the change is explicitly a migration.
3. Add or update a test when changing parsers, planning rules or shared helpers.
4. Run:

   ```powershell
   python -m unittest discover -s scripts/tests -v
   ```

5. Update `CHANGELOG.md` for user-visible changes.
6. Explain which Unreal Engine versions and assets were used for manual testing.

## Safety and privacy

- Never commit third-party asset packs or exported `.uasset` files.
- Never commit `config.json`, local logs, `Saved/`, `Intermediate/`, generated
  reports, material dumps or Unreal cache directories.
- Use generalized paths such as `C:/path/to/project` and synthetic or
  permission-cleared test data.
- Mutating workflows must preserve a dry-run, report or restore path.

## Development checks

The GitHub Actions test workflow runs on pull requests and pushes to `main`.
Tests that require private reference corpora skip cleanly; new deterministic tests
should run with the repository alone.
