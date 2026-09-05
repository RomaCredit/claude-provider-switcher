# Claude Provider Switcher

`claude-provider-switcher` (`ccs`) manages Claude Code provider profiles without
editing conversation history. It switches the user-level Claude Code settings
that control `ANTHROPIC_BASE_URL`, model selection, and authentication, while
preserving unrelated settings and creating a restore point before every change.

It is intentionally **not** a Claude Desktop conversation migrator. Claude Code
settings have multiple sources and precedence levels; managed settings, project
settings, shell variables, CLI flags, and a running session can still override
the user settings. Use `ccs doctor` and Claude Code `/status` to verify the
effective configuration.

## Install

Python 3.10+ is required. This initial release is available from GitHub;
**it has not been published to PyPI**. Install with pipx:

```bash
pipx install git+https://github.com/RomaCredit/claude-provider-switcher.git
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
curl -fsSL https://raw.githubusercontent.com/RomaCredit/claude-provider-switcher/v0.1.0/install.sh | sh
ccs --version
```

The standalone installer requires Python 3.10+, installs both command names,
and never changes Claude settings during installation. Windows users can run:

```powershell
irm https://raw.githubusercontent.com/RomaCredit/claude-provider-switcher/v0.1.0/install.ps1 | iex
```

## Quick start

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
  "version": 1,
  "profiles": {
    "official": {"type": "subscription", "base_url": "", "model": "", "auth_kind": "api_key"},
    "anthropic": {
      "type": "api",
      "base_url": "https://api.anthropic.com",
      "model": "claude-sonnet-4-6",
      "auth_kind": "api_key"
    }
  }
}
```

API profiles must expose the Anthropic Messages API at a base URL. Claude Code
uses `/v1/messages`; an OpenAI-only `/v1/chat/completions` endpoint is not
compatible unless a gateway translates the protocol. `auth_token` sends a
Bearer token, while `api_key` sends an `x-api-key` credential in `ccs profile
test` and `ccs run`.

## Commands

```text
ccs use <name>                         Back up and update user settings
ccs run <name> [-- claude options]     Start one isolated Claude process
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

## Configuration safety

Every `use` or restore operation creates a timestamped backup under
`~/.claude-provider-switcher/backups/`. Updates are atomic and protected by a
lock. The tool refuses to replace a symlinked `settings.json`, refuses unsafe
remote HTTP URLs, rejects credentials embedded in URLs, and masks credentials
from errors. It never reads or modifies conversation history.

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

Reference: [Claude Code gateway configuration](https://code.claude.com/docs/en/llm-gateway-connect).

## License

MIT
