# Release

1. Update package, pyproject, installers, README URLs, citation, and changelog.
   Never replace a published tag or wheel.
2. Run `python -m unittest discover -s tests -v` and the cross-platform matrix.
3. Build with `python -m build` and validate with `python -m twine check dist/*`.
   Use a clean output directory for every version.
4. Push reviewed main, configure the Trusted Publisher below, and push `v0.1.5`.
5. The tag workflow tests all three OSes on Python 3.10/3.13 before OIDC upload.
6. Confirm PyPI actually lists the version before advertising package-name installs.
   Verify both `ccs` and `claude-provider-switcher` in a clean environment.
7. Create a GitHub Release with installation, changes, limitations, and CI links.
8. Update the Homebrew formula from the downloaded archive's SHA256, not the
   commit SHA. Validate installation and `brew test` on macOS/Linux.

## First PyPI publication

The account holder must sign in to
[PyPI publishing](https://pypi.org/manage/account/publishing/) and add a pending publisher:

| Field | Value |
| --- | --- |
| PyPI project name | `claude-provider-switcher` |
| Owner | `RomaCredit` |
| Repository | `claude-provider-switcher` |
| Workflow filename | `publish.yml` |
| Environment | `pypi` |

The Codex project's publisher does not grant access to this package. No token
is needed in GitHub. If uploading fails before authorization, configure the
publisher and rerun failed jobs for the existing tag; do not move it.
Manual workflow dispatch is supported on version tags, not main.

For a deliberate manual publication, the PyPI owner may use
`python -m twine upload dist/*` from a clean build directory with a securely
supplied scoped token. Never commit or paste the token into logs or issues.
