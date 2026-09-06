# Remaining account and community actions

Status checked on 2026-09-06. These are not runtime requirements.

## Authorize PyPI

The v0.1.5 build and test jobs passed, but upload failed with
`invalid-publisher`: PyPI has no matching Trusted Publisher. This is not a
package test failure. See [RELEASE.md](../RELEASE.md) for the exact five fields.

1. Sign in at https://pypi.org/manage/account/publishing/.
2. Add pending project `claude-provider-switcher`, owner `RomaCredit`,
   repository `claude-provider-switcher`, workflow `publish.yml`, environment `pypi`.
3. Open https://github.com/RomaCredit/claude-provider-switcher/actions/runs/34030865108
   and rerun failed jobs. Do not replace the tag.
4. Confirm version 0.1.5 on PyPI and test a fresh package-name installation.
5. Only then replace the GitHub-only installation notice and add a PyPI badge.

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
