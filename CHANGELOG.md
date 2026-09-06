# Changelog

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
