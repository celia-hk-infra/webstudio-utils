#!/usr/bin/env bash
# Official Codex and personal egress for persistent HKSTP machines.
set -euo pipefail
set +xv
repo_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
command -v python3 >/dev/null || { echo 'Python 3 is required.' >&2; exit 1; }
exec python3 "$repo_dir/scripts/hkstp.py" setup "$@"
