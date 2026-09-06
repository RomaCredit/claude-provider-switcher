# Changelog

## 0.1.5

- Make the overview and quick start provider-neutral while retaining the
  configured APIMaster preset and its one-time credential prompt.
- Add bilingual navigation, troubleshooting, verified scope, contribution
  guidance, issue forms, citation metadata, and package discovery keywords.
- Prepare tag-based PyPI trusted publishing gated by a cross-platform test matrix.
  PyPI publication requires a separate project-level Trusted Publisher.
- Provider switching, credentials, and conservative history behavior are unchanged.

## 0.1.4

- Make the post-switch history check read-only. Explicit repair now requires
  confirmation that Claude Code and related desktop sessions are closed;
  use `--yes` only after stopping those writers.
- Replace the richest-record-wins policy with conservative conflict handling:
  conflicting folders and their prompt labels are untouched. Only agreed
  bookkeeping fields can fill missing entries. Never infer trust, union
  allowed tools, or replace MCP configurations.
- Correct `--check` to report actual pending changes or unresolved conflicts,
  not the number of path aliases. A second check after successful repair exits 0.
- Snapshot file bytes and identity; check all sources after staging and before
  each replacement. Abort on detected concurrent changes and report partial
  progress without overwriting newer state with a rollback.
- Back up exact source bytes with private permissions before any repair.
  Reject symlinks/hard links and preserve BOM, line endings, malformed JSONL
  lines and missing final newline. Preserve literal POSIX backslashes.
- A failed post-switch check warns without claiming the provider switch failed.
- These checks are not a cross-process transaction; close Claude before repair.
  Existing `history-*` backups are restored manually, not by `ccs backup restore`.

## 0.1.3

- Add `ccs repair-history`, which merges the per-project records that Windows
  entry points duplicate under `D:/path` and `D:\path`, splitting trust
  approval, allowed tools, MCP settings, and prompt recall. Records are
  mirrored rather than collapsed, the richest record wins a conflict, and both
  `.claude.json` and `history.jsonl` are backed up before any write.
- Run that reconciliation after `ccs use`; opt out with `--no-repair-history`.
- Allow `--resume`, `--continue`, `-c`, and `-r` in `ccs run`. It already
  pinned `CLAUDE_CONFIG_DIR` to the same session store, so rejecting them only
  prevented continuing a conversation started under another profile.
  `--settings`, `--setting-sources`, `--model`, and `--bare` remain rejected.
- Conversation transcripts are still never read, rewritten, or deleted.

## 0.1.2

- Add the APIMaster Claude Code preset with the site-root URL, Sonnet model,
  token authentication, and documented compatibility flags.
- Upgrade version-1 profiles once, retaining a private original-file backup,
  preserving custom same-name profiles, and respecting subsequent deletions.
- Prompt for a missing credential on interactive `use` and menu switching;
  noninteractive use still requires an explicitly saved credential.
- Store optional, allowlisted compatibility flags in profiles without
  provider-name branches. Clear those flags when switching away.
- Profiles now use schema version 2. For a downgrade to 0.1.1 or earlier,
  restore the saved version-1 profiles file first.
- Reinstall the requested version in the Windows installer's pipx path
  instead of silently retaining an older installed release.

## 0.1.1

- Prefer PATH Python on Windows and validate the created virtual environment.
- Allow an explicit isolated installation directory without changing LOCALAPPDATA.
- Exercise tagged release installation twice on Windows, macOS, and Linux.

## 0.1.0

- Initial Claude Code provider profile manager.
- Add subscription/API profiles, secure credential storage, atomic settings
  backups, restore points, conflict diagnostics, explicit provider probes, and
  isolated `ccs run`.
