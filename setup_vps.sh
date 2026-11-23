#!/usr/bin/env bash
# Standalone Ubuntu VPS entry point. No WebStudio environment required.
set -euo pipefail
set +xv
repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
exec python3 "$repo/scripts/setup_vps.py" "$@"
