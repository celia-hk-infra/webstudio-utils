#!/usr/bin/env bash
# Standalone setup for x86_64 Linux JupyterLab instances; no dataset required.
set -euo pipefail

INSTALL_DIR="${VSCODE_INSTALL_DIR:-/home/ma-user/work/.vscode-standalone}"
RUNTIME="$INSTALL_DIR/runtime"
# Some shared work mounts reject the server installer's directory renames.
LOCAL_DIR="${VSCODE_LOCAL_DIR:-/tmp/vscode-tunnel-${UID}}"
CLI="$LOCAL_DIR/bin/code"

if [[ "${1:-}" == --help ]]; then
  cat <<'EOF'
Usage: bash start_vscode_tunnel.sh [--install-only | tunnel options...]
First run installs a small Conda runtime and the VS Code CLI.
Default: start the tunnel and prompt for license acceptance and sign-in.
Example: bash start_vscode_tunnel.sh --name my-jupyter
Overrides: CONDA_EXE, VSCODE_INSTALL_DIR, VSCODE_LOCAL_DIR,
           VSCODE_GLIBC_LINKER (default /lib64/ld-linux-x86-64.so.2),
           VSCODE_CONDA_SOLVER (default classic).
Keep VSCODE_LOCAL_DIR on local disk. /tmp may be cleared on restart.
EOF
  exit 0
fi

[[ "$(uname -s)" == Linux && "$(uname -m)" == x86_64 ]] || {
  echo 'This script requires x86_64 Linux.' >&2; exit 1;
}
glibc="$(getconf GNU_LIBC_VERSION | awk '{print $2}')"
IFS=. read -r glibc_major glibc_minor _ <<< "$glibc"
if (( glibc_major < 2 || (glibc_major == 2 && glibc_minor < 28) )); then
  echo "glibc $glibc is too old; use an instance image with glibc >= 2.28." >&2
  exit 1
fi
LINKER="${VSCODE_GLIBC_LINKER:-/lib64/ld-linux-x86-64.so.2}"
[[ -x "$LINKER" ]] || { echo "Missing dynamic linker: $LINKER" >&2; exit 1; }
for required_tool in tar curl mktemp; do
  command -v "$required_tool" >/dev/null 2>&1 || {
    echo "Required command not found: $required_tool" >&2; exit 1;
  }
done

mkdir -p "$INSTALL_DIR"
if [[ ! -x "$RUNTIME/bin/patchelf" || ! -f "$RUNTIME/lib/libstdc++.so.6" ]]; then
  CONDA_BIN="${CONDA_EXE:-}"
  if [[ -z "$CONDA_BIN" ]]; then
    if command -v conda >/dev/null 2>&1; then
      CONDA_BIN=conda
    elif [[ -x /opt/huawei/miniconda/envs/python39/bin/conda ]]; then
      CONDA_BIN=/opt/huawei/miniconda/envs/python39/bin/conda
    else
      echo 'Conda not found. Set CONDA_EXE=/path/to/conda and rerun.' >&2
      exit 1
    fi
  fi
  conda_action=create
  [[ ! -d "$RUNTIME/conda-meta" ]] || conda_action=install
  echo "Installing minimal runtime in $RUNTIME (first run may take several minutes)..."
  # Use classic explicitly: older libmamba versions may ignore current_repodata.
  if ! "$CONDA_BIN" "$conda_action" --yes --prefix "$RUNTIME" \
    --solver "${VSCODE_CONDA_SOLVER:-classic}" \
    --override-channels --channel conda-forge --repodata-fn current_repodata.json \
    'libstdcxx-ng>=12' 'patchelf>=0.18'; then
    echo 'Runtime installation failed. Check the Conda output and available RAM, then rerun.' >&2
    exit 1
  fi
fi

mkdir -p "$LOCAL_DIR"
chmod 700 "$LOCAL_DIR"
if [[ ! -x "$CLI" ]]; then
  # Relocated Conda curl installations can have invalid built-in CA paths.
  CURL_BIN="$(command -v curl)"
  [[ ! -x /usr/bin/curl ]] || CURL_BIN=/usr/bin/curl
  staging="$(mktemp -d "$LOCAL_DIR/download.XXXXXX")"
  trap 'rm -rf -- "$staging"' EXIT
  echo 'Downloading standalone VS Code CLI...'
  "$CURL_BIN" --fail --location --retry 3 --connect-timeout 30 \
    'https://code.visualstudio.com/sha/download?build=stable&os=cli-alpine-x64' \
    --output "$staging/vscode_cli.tar.gz"
  tar -xf "$staging/vscode_cli.tar.gz" -C "$staging"
  [[ -x "$staging/code" ]] || { echo 'Archive did not contain executable code.' >&2; exit 1; }
  mkdir -p "$LOCAL_DIR/bin"
  mv "$staging/code" "$CLI"
  rm -rf -- "$staging"
  trap - EXIT
fi

# Supply a newer C++ runtime while using the instance's existing glibc/linker.
# No conda activation is required.
export LD_LIBRARY_PATH="$RUNTIME/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export VSCODE_SERVER_CUSTOM_GLIBC_LINKER="$LINKER"
export VSCODE_SERVER_CUSTOM_GLIBC_PATH="$RUNTIME/lib:/lib64:/usr/lib64"
export VSCODE_SERVER_PATCHELF_PATH="$RUNTIME/bin/patchelf"

if [[ "${1:-}" == --install-only ]]; then
  "$CLI" --version
  echo "Installed. Start with: bash $0 --name my-jupyter"
  exit 0
fi

# Restore persistent agent homes and pass their environment to VS Code.
source "$(dirname -- "${BASH_SOURCE[0]}")/../shell/init.sh"

# Metadata and server installations stay on local disk. Sign in again if wiped.
echo 'Starting tunnel. Follow the license and sign-in prompts; Ctrl+C stops it.'
exec "$CLI" tunnel --cli-data-dir "$LOCAL_DIR/cli-data" \
  --server-data-dir "$LOCAL_DIR/server-data" "$@"
