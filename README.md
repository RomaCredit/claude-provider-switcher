# Claude Provider Switcher: switch Claude Code API profiles safely

[![Tests](https://github.com/RomaCredit/claude-provider-switcher/actions/workflows/test.yml/badge.svg)](https://github.com/RomaCredit/claude-provider-switcher/actions/workflows/test.yml)
[![PyPI](https://img.shields.io/pypi/v/claude-provider-switcher)](https://pypi.org/project/claude-provider-switcher/)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green)](https://github.com/RomaCredit/claude-provider-switcher/blob/main/LICENSE)

[中文文档](https://github.com/RomaCredit/claude-provider-switcher/blob/main/README.zh-CN.md) |
[Releases](https://github.com/RomaCredit/claude-provider-switcher/releases) |
[Changelog](https://github.com/RomaCredit/claude-provider-switcher/blob/main/CHANGELOG.md)

Switch Claude Code between Claude.ai subscription login, Anthropic's API, and
Anthropic-compatible gateways without repeatedly editing `ANTHROPIC_BASE_URL`,
models, and authentication. `claude-provider-switcher` (`ccs`) manages named
profiles, stores credentials privately, and backs up settings before changes.
It preserves unrelated user settings and does not edit conversation transcripts.
History diagnostics and conservative repairs are described in
[Conversation history](#conversation-history); visibility in every client is not guaranteed.

It is intentionally **not** a Claude Desktop conversation migrator. Claude Code
settings have multiple sources and precedence levels; managed settings, project
settings, shell variables, CLI flags, and a running session can still override
the user settings. Use `ccs doctor` and Claude Code `/status` to verify the
effective configuration.

## Is this for you?

Use it for repeatable Claude Code provider switches, private credentials,
settings backups, and conservative project-history diagnostics. It does not
migrate Claude Desktop cloud conversations, translate an OpenAI-only API,
increase subscription quotas, or bypass organization policy. Third-party APIs
have separate billing. This is an independent community project, not an
Anthropic product.

## Install

### PyPI / pipx

Python 3.10+ is required. The package is
[published on PyPI](https://pypi.org/project/claude-provider-switcher/).
For an isolated CLI installation:

```bash
pipx install claude-provider-switcher
ccs --version
```

In an activated virtual environment or another pip-managed Python environment:

```bash
python -m pip install --upgrade claude-provider-switcher
ccs --version
```

Ubuntu/Debian may reject system `pip` with `externally-managed-environment`
(PEP 668). Use pipx, a virtual environment, Homebrew, or the standalone installer
below; do not use `--break-system-packages`. Installation does not switch
providers or modify Claude settings.

### Homebrew (macOS / Linux)

```bash
brew tap RomaCredit/codex
brew install RomaCredit/codex/claude-provider-switcher
ccs --version
```

The shared tap keeps its existing name but installs this tool independently
from Codex Provider Switcher. Both formulas are
[installation-tested on macOS and Linux](https://github.com/RomaCredit/homebrew-codex/actions/workflows/test.yml).
If your Homebrew requires tap trust, inspect the formula first and trust only
this formula with `brew trust --formula RomaCredit/codex/claude-provider-switcher`.

### Versioned source and standalone installers

For a specific GitHub release:

```bash
pipx install https://github.com/RomaCredit/claude-provider-switcher/archive/refs/tags/v0.1.6.zip
ccs --version
```

Or from source in an isolated environment:

```bash
git clone https://github.com/RomaCredit/claude-provider-switcher.git
cd claude-provider-switcher
python3 -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/ccs --version
```

On Windows use `.venv\Scripts\python.exe` and `.venv\Scripts\ccs.exe`.
Ubuntu/Debian may reject system `pip` with `externally-managed-environment`;
do not disable that protection. Alternatively use the standalone installer:

```bash
curl -fsSL https://raw.githubusercontent.com/RomaCredit/claude-provider-switcher/v0.1.6/install.sh | sh
ccs --version
```

The standalone installer requires Python 3.10+, installs both command names,
and never changes Claude settings during installation. Windows users can run:

```powershell
irm https://raw.githubusercontent.com/RomaCredit/claude-provider-switcher/v0.1.6/install.ps1 | iex
```

## Quick start

Choose a profile, switch, then inspect the effective configuration:

```bash
ccs profile list
ccs use anthropic
ccs status
ccs doctor
ccs use official
```

The first interactive switch to an API profile asks only for your API key,
with input hidden; later switches reuse the saved credential. `ccs` opens the
same flow in a menu. Restart Claude Code and check `/status`; subscription
login must already be available or completed in Claude Code.

APIMaster is another editable preset: `ccs use apimaster` provides the same
one-time key prompt. Its endpoint and compatibility options follow its
[Claude Code setup guide](https://apimaster.ai/docs/en/cli/claude-code).
No profile bundles a shared or free API key.

For another Anthropic-compatible provider:

```bash
ccs profile list
ccs profile add gateway --base-url https://gateway.example.com --model your-model --auth-kind auth_token
ccs use gateway
ccs status
ccs doctor
```

Replace the example URL and model with your gateway's values. `profile add`
prompts for a credential unless `--key-stdin` is supplied. Keys
are stored in macOS Keychain or Windows Credential Manager when available, with
a `0600` JSON fallback on POSIX systems. Credentials never go in
`profiles.json`, status output, diagnostics, or URLs.

## Profiles

The default file is:

```text
macOS/Linux: ~/.claude-provider-switcher/profiles.json
Windows:     %USERPROFILE%\.claude-provider-switcher\profiles.json
```

The default profiles are:

```json
{
  "version": 2,
  "profiles": {
    "official": {"type": "subscription", "base_url": "", "model": "", "auth_kind": "api_key"},
    "anthropic": {
      "type": "api",
      "base_url": "https://api.anthropic.com",
      "model": "claude-sonnet-4-6",
      "auth_kind": "api_key"
    },
    "apimaster": {
      "type": "api",
      "base_url": "https://apimaster.ai",
      "model": "claude-sonnet-4-6",
      "auth_kind": "auth_token",
      "env": {
        "CLAUDE_CODE_ATTRIBUTION_HEADER": "0",
        "CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS": "1"
      }
    }
  }
}
```

The APIMaster URL deliberately has **no `/v1` suffix**: Claude Code appends
`/v1/messages` itself. This differs from the Codex preset's OpenAI base URL.
All three presets are ordinary, editable and removable profiles. The optional
`env` object only accepts the two compatibility flags above with string values
`"0"` or `"1"`; it cannot carry keys or arbitrary environment variables.

### Upgrading from 0.1.0 or 0.1.1

Rerun the new standalone installer above. For a PyPI-based pipx installation:

```bash
pipx upgrade claude-provider-switcher
ccs --version
ccs profile list
```

To move an existing GitHub-URL pipx installation to PyPI, run
`pipx install --force claude-provider-switcher` once. This changes the installed
package source, not your profiles or credentials. Run `ccs use <profile>` again
if the installation path changes, so the credential helper points to that path.

The first profile load migrates `profiles.json` from schema 1 to schema 2 and
adds only missing newly introduced presets. It first saves the original bytes
as `profiles-v1-<id>.backup.json` in the switcher data directory. Existing
same-name profiles and saved credentials are preserved; Claude settings are
not switched by this migration. Deleting a preset after migration is permanent
until you add it again. Do not delete your profiles file to upgrade.
An older switcher cannot read schema 2; restore the version-1 backup before
downgrading. Noninteractive users can save a credential with
`ccs profile key apimaster --key-stdin` before `ccs use apimaster`.

API profiles must expose the Anthropic Messages API at a base URL. Claude Code
uses `/v1/messages`; an OpenAI-only `/v1/chat/completions` endpoint is not
compatible unless a gateway translates the protocol. `auth_token` sends a
Bearer token, while `api_key` sends an `x-api-key` credential in `ccs profile
test` and `ccs run`.

## Commands

```text
ccs use <name>                         Back up settings, switch, check history read-only
ccs run <name> [-- claude options]     Start one isolated Claude process
ccs repair-history [--check | --yes] [--json]
ccs status [--json]                    Show local settings and credential backend
ccs doctor [--json]                    Find shell/project/managed conflicts
ccs profile list
ccs profile add <name> [options]
ccs profile edit <name> [options]
ccs profile key <name> [--key-stdin]
ccs profile test <name> [--inference]
ccs profile remove <name> --yes
ccs backup list
ccs backup restore <id> --yes
```

`profile test` uses a no-body `/v1/models` probe. Some Anthropic-compatible
gateways do not expose that endpoint; use `--inference` for an explicit
one-token `/v1/messages` request, which may incur provider charges. A successful
probe does not prove streaming, tools, model aliases, or all Claude Code
features.

`ccs use official` selects Claude.ai login mode in the user settings, but it
does not log in, log out, delete OAuth files, or override organization-managed
policy. Restart Claude Code and inspect `/status`.

## Conversation history

The switcher does not migrate or rewrite transcripts under
`<claude-home>/projects/`. `ccs run` passes the same `CLAUDE_CONFIG_DIR` and permits
`--resume` and `--continue`; actual session compatibility and visibility remain
Claude Code's responsibility. This is not Codex's `model_provider` synchronization.

Project bookkeeping can contain both `D:/WorkSpace/app` and `D:\WorkSpace\app`
for one Windows directory. These records may differ in session metadata,
trust, allowed tools or MCP settings. Since 0.1.4, `ccs use` and menu switching
only **inspect** these records; no history files are written automatically.

```text
ccs repair-history --check --json   Read-only report; creates no files or locks
ccs repair-history                  Confirm Claude is closed, then repair
ccs repair-history --yes            Noninteractive confirmation that Claude is closed
ccs use <name> --no-repair-history  Switch without the read-only history check
```

Close **all** Claude Code and related desktop sessions before applying a repair.
Only missing, agreed session bookkeeping (such as `lastSessionId`) can be filled.
Conflicting values, or missing trust/tool/MCP/unknown settings, leave that entire
folder and its prompt path labels untouched and produce a conflict report.
The tool neither unions permissions nor chooses a winner based on record size.
Resolve those conflicts manually with Claude closed; no values are printed.

For non-conflicting folders, existing path aliases are retained. Prompt labels
adopt a spelling already present in `history.jsonl`. No prompts are deleted;
malformed lines, BOM, CRLF/LF endings and a missing final newline are preserved.
The transcript-directory inventory is advisory, based on a legacy encoding,
not proof that unmatched directories are invalid or lost.

`--check` exits 1 for pending changes **or conflicts**, and 0 when neither exists,
even if identical aliases remain. Applying safe changes while conflicts remain
also exits 1. `pending_changes` describes the analyzed input; `applied` indicates
whether it was written. Rerun `--check` to inspect the current state.

Both existing source files are backed up byte-for-byte in
`~/.claude-provider-switcher/backups/history-<id>/`, with private permissions,
before writing. File identity and contents are checked after staging and before
each replacement. Concurrent edits, deletion, replacement or linked files abort
the operation. Partial failures identify already replaced files and the backup;
there is no automatic rollback that could erase new external writes.

**This is not a multi-file transaction or a lock honored by Claude.** A writer
can still race after the last check, so `--yes` is an acknowledgement to stop
Claude, not a force override. Backups named `history-*` are not accepted by
`ccs backup restore`. To recover manually, close Claude, separately preserve
the current files, compare the backup's `claude.json` and `history.jsonl` to the
reported source paths, and restore only the intended files. Backups may contain
secrets; never post them in an issue. A failed read-only post-switch check is a
warning and does not undo or misreport a successful provider switch.

## Configuration safety

Every `use` or restore operation creates a timestamped backup under
`~/.claude-provider-switcher/backups/`. Updates are atomic and protected by a
lock. The tool refuses to replace a symlinked `settings.json`, refuses unsafe
remote HTTP URLs, rejects credentials embedded in URLs, and masks credentials
from errors. It never reads or modifies conversation transcripts. Explicit
history repair can update the project metadata and prompt path labels above.

Persistent `use` installs an `apiKeyHelper` command containing only the Python
path, helper path, switcher home and profile name. Claude executes it to read the
secret over stdout. This machine-only credential channel is intentionally not a
normal CLI display command. Claude's helper sends **both** `x-api-key` and Bearer
headers; for gateways requiring exactly one, use `ccs run`. A reinstall to a
different location requires another `ccs use` to update the helper path.

Backups may contain secrets from pre-existing settings. They are private too.
Windows files receive a current-user-only ACL; POSIX files use `0600`. Deleting
a profile does not erase old backups or history. Treat backups as sensitive.
The standalone installer retains old version directories for existing helpers.

`ccs run` removes provider-related
variables inherited from the shell, supplies only the selected profile to the
child process, and uses a sanitized user settings copy with project/local setting
sources disabled. It preserves unrelated user customizations, including hooks
and permissions; it is not a sandbox. It does not bypass organization-managed
policy. No settings are persisted by the switcher for this command; Claude may
still save session data normally. `ccs doctor` reports likely local conflicts but
cannot inspect MDM, registry policy, remote policy, or interactive CLI flags.

The switcher collects no telemetry and makes no network requests except explicit
provider probes. Installers fetch releases; `ccs run` starts Claude Code, whose
network behavior and data policies are separate. No actual subscription login or
third-party model compatibility is guaranteed by local tests.

## Troubleshooting

### Claude Code still uses the old ANTHROPIC_BASE_URL after switching

Run `ccs doctor`, restart Claude Code, and inspect `/status`. Shell variables,
project settings, CLI flags, or managed policy may override user settings.
`ccs run <profile>` provides an isolated launch for supported local settings;
it is not a policy bypass.

### Can I continue a Claude Code conversation after switching providers?

The switcher leaves transcripts in place. Resume with Claude Code's
`--resume` or `--continue` using the same project and `CLAUDE_CONFIG_DIR`.
Actual visibility and provider compatibility remain Claude Code's responsibility.
Use `ccs repair-history --check` for project metadata diagnostics, not transcript
recovery. See [Conversation history](#conversation-history) before any repair.

### Does a successful provider test prove the gateway works with Claude Code?

No. `/v1/models` only tests that endpoint and authentication. Messages,
streaming, tools, and model aliases need separate verification. `--inference`
is an explicit, potentially billable test, never part of the default probe.

### Why does pip report externally-managed-environment on Ubuntu?

This is system Python's PEP 668 protection. Use pipx, a virtual environment,
or the standalone installer above; do not use `--break-system-packages`.

## Development

```bash
python -m unittest discover -s tests -v
```

The suite uses temporary directories and mock credentials, and tests HTTP probes
only against loopback. `CCS_TEST_REAL_CLAUDE=1` additionally tests a locally
installed Claude Code with fake credentials and `auth status`, not inference.
POSIX installers are exercised on Linux/macOS CI. Claude's own auth files and
conversation files are never migration targets.
Native Windows Credential Manager is tested with a disposable credential;
macOS CI enables `CCS_TEST_NATIVE_KEYCHAIN=1` for the equivalent Keychain check.
Release tags additionally exercise online installation on all three platforms.

Reference: [Claude Code gateway configuration](https://code.claude.com/docs/en/llm-gateway-connect).

The CI matrix covers Windows, macOS, and Linux with Python 3.10 and 3.13.
It is evidence for these local operations, not certification of every Claude
Code version or live gateway.

For **Codex Desktop**, see
[Codex Provider Switcher](https://github.com/RomaCredit/codex-provider-switcher).
Its provider-index synchronization is different from Claude's project-record
repair. The tools do not share credentials or migrate each other's sessions.

[Contributing](https://github.com/RomaCredit/claude-provider-switcher/blob/main/CONTRIBUTING.md) |
[Report an issue](https://github.com/RomaCredit/claude-provider-switcher/issues/new/choose) |
[Security](https://github.com/RomaCredit/claude-provider-switcher/blob/main/SECURITY.md)

## License

MIT. See [LICENSE](https://github.com/RomaCredit/claude-provider-switcher/blob/main/LICENSE).
