# Remaining account and community actions

Status checked on 2026-09-06. These are not runtime requirements.

## PyPI authorization: completed

The account holder configured the Trusted Publisher and the v0.1.5 upload
succeeded on retry:
https://github.com/RomaCredit/claude-provider-switcher/actions/runs/34030865108

PyPI now distributes the package at
https://pypi.org/project/claude-provider-switcher/.
The 0.1.6 documentation release removes the old unpublished notice from package
metadata and adds pip/pipx installation instructions and badges. See
[RELEASE.md](../RELEASE.md) for future releases; no new authorization is required
while the publisher binding remains unchanged.

## Social preview

The reviewed PNG is `docs/social-preview.png` (1280 x 640), generated with
`scripts/render-social-preview.ps1`. In repository Settings > General >
Social preview, upload this image. Committing it does not set GitHub's preview.

## Awesome Claude Code

The current rules at
https://github.com/hesreallyhim/awesome-claude-code/blob/main/CONTRIBUTING.md
require either 14 days since the first default-branch commit with continued
development, or 100 stars. Recommendations must be submitted by a human using
the web form, not an agent, API, or PR. No recommendation has been submitted.
Recheck eligibility and rules before a human recommendation.

Suggested category: Providers, Runtime & Integration Infrastructure.
Describe the actual provider/profile, private-credential, backup, and diagnostic
scope. Do not claim transcript migration, universal compatibility, or acceptance.
