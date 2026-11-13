#!/usr/bin/env bash
# Laptop/Mac/VPS entry point using the submodule pinned by this checkout.
set -euo pipefail
repo_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
source "$repo_dir/scripts/ui.sh"
source "$repo_dir/scripts/setup_prompts.sh"
ui_setup
trap ui_cleanup EXIT
if [[ ${1:-} == --language ]]; then export WEBSTUDIO_LANGUAGE=${2:?en or zh}; shift 2; fi
choose_language
ui_intro 'Personal egress'
git -C "$repo_dir" submodule update --init -- vendor/codex-local-egress
# Preserve vendor host output (including the generated configuration location).
bash "$repo_dir/vendor/codex-local-egress/local.sh" "$@" 2>&1 | python3 -u "$repo_dir/scripts/egress_output.py" "$WEBSTUDIO_LANGUAGE"
