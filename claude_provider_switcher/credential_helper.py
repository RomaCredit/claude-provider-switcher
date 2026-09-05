"""Machine-to-machine stdout credential channel for Claude's apiKeyHelper."""

import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from claude_provider_switcher.credentials import Credentials


def main():
    try:
        if len(sys.argv) != 3:
            raise ValueError()
        secret = Credentials(Path(sys.argv[1]).resolve()).get(sys.argv[2])
        if not secret:
            raise ValueError()
        sys.stdout.write(secret)
        return 0
    except Exception:
        print("Credential unavailable. Run 'ccs profile key <name>'.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
