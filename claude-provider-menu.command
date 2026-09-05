#!/bin/sh
set -eu
cd "$(dirname "$0")"
exec python3 -m claude_provider_switcher menu
