# Contributing

Use Python 3.10+ on Windows, macOS, or Linux. Keep runtime dependencies limited
to the standard library. Build and test tools belong in a virtual environment.

```bash
python -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/python -m unittest discover -s tests -v
```

On Windows use `.venv\Scripts\python.exe`. CI covers Python 3.10 and 3.13 on
all three platforms, plus release-install checks on version tags.

## Test boundaries

Use temporary directories, fake credentials, and loopback HTTP servers.
Never read real transcripts, commit backups, or send billable inference requests.
Native credential tests use disposable entries and remove them afterward.
`CCS_TEST_REAL_CLAUDE=1` runs an optional installed Claude Code `auth status`
check with fake credentials, not inference. It does not certify gateway support.

History changes need tests for conflicts, byte preservation, concurrent edits,
link rejection, and read-only checks. Do not weaken trust, permission, or MCP
conflict handling to make a fixture pass. Tests must not modify a real Claude home.

## Pull requests

Describe the problem, scope, and verification. Include regression tests and
update both READMEs when behavior changes. Preserve unrelated settings and keep
runtime output in English for Windows console compatibility. Report actual
client versions for manually reproduced behavior; do not infer compatibility
from mocks or a successful models-list request.

Installation, provider, and history issues have separate templates. Never post
keys, OAuth data, settings dumps, transcripts, or backups. See
[SECURITY.md](SECURITY.md) for security reporting.
