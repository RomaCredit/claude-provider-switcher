# Security

Do not include API keys, settings backups, OAuth files, proxy credentials or
unredacted logs in public issues. Report a vulnerability through GitHub's
private vulnerability reporting when available; otherwise open an issue with
only a request for a private contact, without exploit details or secrets.

The switcher stores no secrets in profiles or generated settings. The
`credential_helper.py` entry point is explicitly a machine credential channel:
its stdout contains the credential for Claude Code. Do not invoke or log it as
a diagnostic command. All human CLI error paths omit raw exceptions.

Local settings backups can contain secrets already present in pre-existing
settings and are protected like credentials. POSIX files are mode 0600;
Windows files have a current-user-only ACL. A compromised process running as
the same user, an administrator, or Claude's own tools can still access secrets.

History repair has a separate safety boundary: normal switching only checks
history. Explicit repair requires stopping Claude first and confirming this,
interactively or with `--yes`. File snapshot guards detect changes but cannot
eliminate races with a writer that does not share our locks. Writes across
`.claude.json` and `history.jsonl` are not one atomic transaction. Partial
failures retain private source backups and report progress, without rollback.
Conflicting trust, tool, MCP or unknown settings remain untouched. These
backups can contain prompts and credentials; restore them manually with all
Claude processes closed and after preserving the current files separately.

No tool in this project overrides organization-managed Claude policies.
`ccs run` is a provider launcher, not a security sandbox. It preserves unrelated
user hooks and permission choices and does not suppress Claude's own telemetry.

Only explicit provider tests send network requests. Redirects are rejected so a
gateway cannot redirect a credential to another origin. Remote HTTP is refused;
loopback HTTP is permitted for development. TLS verification remains enabled.
Installers download source over HTTPS and validate the release structure; this
is not a cryptographic signature or protection against a compromised upstream.
