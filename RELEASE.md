# Release

1. Update the version in the package, pyproject, and both installers.
2. Run `python -m unittest discover -s tests -v` and the six-platform CI matrix.
3. Build with `python -m build` and validate with `python -m twine check dist/*`.
4. Push the reviewed main branch and version tag, then verify installer URLs.
5. PyPI publishing is a separate action: configure ownership and a Trusted
   Publisher for this project before adding an OIDC upload workflow. Do not
   assume the Codex project's publisher grants access to the Claude project.
6. Verify in a clean environment that both `ccs` and
   `claude-provider-switcher` resolve to the released version.

The initial v0.1.0 is distributed from GitHub. This repository does not contain a
PyPI token or an automatically triggered upload workflow.
