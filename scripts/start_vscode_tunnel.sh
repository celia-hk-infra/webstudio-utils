#!/usr/bin/env bash
# VS Code tunnel launcher for x86_64 Linux JupyterLab instances.
set -euo pipefail

if [[ "${1:-}" == --help ]]; then
  cat <<'EOF'
Usage: bash start_vscode_tunnel.sh [--install-only | tunnel options...]
First run installs a small Conda runtime and downloads the VS Code CLI.
Default: start the tunnel using the name saved by setup_container.sh.
Example: bash start_vscode_tunnel.sh
Overrides: CONDA_EXE, VSCODE_INSTALL_DIR, VSCODE_LOCAL_DIR,
           VSCODE_GLIBC_LINKER (default /lib64/ld-linux-x86-64.so.2),
           VSCODE_CONDA_SOLVER (default classic).
Keep VSCODE_LOCAL_DIR on local disk; the server is rebuilt after a restart.
EOF
  exit 0
fi

source "$(dirname -- "${BASH_SOURCE[0]}")/../shell/init.sh"
INSTALL_DIR="${VSCODE_INSTALL_DIR:-$WEBSTUDIO_PERSIST_ROOT/tools/vscode}"
RUNTIME="$INSTALL_DIR/runtime"
LOCAL_DIR="${VSCODE_LOCAL_DIR:-$WEBSTUDIO_LOCAL_DIR/vscode}"
CLI="$LOCAL_DIR/bin/code"
CLI_ARCHIVE="$INSTALL_DIR/cli-alpine-x64.tar.gz"
CLI_DATA_DIR="$WEBSTUDIO_PERSIST_ROOT/.webstudio-tunnel/cli-data"

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
  if [[ ! -s "$CLI_ARCHIVE" ]]; then
    archive_staging="$(mktemp "$INSTALL_DIR/.vscode_cli.XXXXXX")"
    echo 'Downloading VS Code CLI to NFS cache...'
    if ! "$CURL_BIN" --fail --location --retry 3 --connect-timeout 30 \
      'https://code.visualstudio.com/sha/download?build=stable&os=cli-alpine-x64' \
      --output "$archive_staging"; then
      rm -f -- "$archive_staging"
      exit 1
    fi
    if ! tar -tf "$archive_staging" >/dev/null; then
      rm -f -- "$archive_staging"
      echo 'VS Code CLI download is not a valid archive.' >&2
      exit 1
    fi
    mv -- "$archive_staging" "$CLI_ARCHIVE"
  fi
  staging="$(mktemp -d "$LOCAL_DIR/download.XXXXXX")"
  trap 'rm -rf -- "$staging"' EXIT
  tar -xf "$CLI_ARCHIVE" -C "$staging"
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
  echo "Installed. Start with: bash $0"
  exit 0
fi

# Keep identity and sign-in data on NFS; install server files on local disk.
mkdir -p -m 700 -- "$CLI_DATA_DIR"
chmod 700 -- "$CLI_DATA_DIR"
tunnel_args=("$@")
has_name=0
for arg in "${tunnel_args[@]}"; do
  if [[ $arg == --name || $arg == --name=* ]]; then
    has_name=1
  fi
done
if (( ! has_name )); then
  name_file="$WEBSTUDIO_PERSIST_ROOT/.webstudio-tunnel/name"
  [[ -s $name_file ]] || {
    echo 'Tunnel name is missing. Run setup_container.sh first.' >&2
    exit 1
  }
  IFS= read -r tunnel_name < "$name_file"
  [[ $tunnel_name =~ ^[A-Za-z0-9][A-Za-z0-9-]{0,19}$ ]] || {
    echo "Invalid saved tunnel name '$tunnel_name' (maximum 20 letters, digits, or hyphens)." >&2
    echo 'Run setup_container.sh --tunnel-name SHORT-NAME to replace it.' >&2
    exit 2
  }
  tunnel_args=(--name "$tunnel_name" "${tunnel_args[@]}")
fi
echo 'Starting tunnel. Follow the license and sign-in prompts; Ctrl+C stops it.'
exec "$CLI" tunnel --cli-data-dir "$CLI_DATA_DIR" \
  --server-data-dir "$LOCAL_DIR/server-data" "${tunnel_args[@]}"
