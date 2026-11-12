#!/usr/bin/env bash
# VS Code tunnel launcher for x86_64 Linux JupyterLab instances.
set -euo pipefail

if [[ "${1:-}" == --help ]]; then
  cat <<'EOF'
Usage: bash start_vscode_tunnel.sh [--install-only | --prefetch | --background | --status | --stop | tunnel options...]
First run installs a small Conda runtime and downloads the VS Code CLI.
Default: run the tunnel in this terminal using the name saved by
setup_tools.sh; on a fresh container you are prompted for a name (Enter accepts a unique default).
Ctrl+C stops it.
--background  sign in if needed, then run the tunnel in the detached tmux
              session "vscode-tunnel" and print its URL once it connects.
              It keeps running after the terminal closes, until --stop or a
              container restart. View it with: tmux attach -t vscode-tunnel
--status      show whether a tunnel is connected.
--stop        stop the background session and any running tunnel.
--prefetch    cache the latest stable server using verified parallel downloads.
Example: bash start_vscode_tunnel.sh --background
Overrides: WEBSTUDIO_TUNNEL_DIR (default /home/ma-user/work/.webstudio-tunnel),
           WEBSTUDIO_TUNNEL_NAME, VSCODE_CLI_DATA_DIR,
           CONDA_EXE, VSCODE_INSTALL_DIR, VSCODE_LOCAL_DIR,
           VSCODE_PERSISTENT_DATA_DIR, VSCODE_DOWNLOAD_CACHE,
           VSCODE_DOWNLOAD_WORKERS (default 32, maximum 32),
           VSCODE_GLIBC_LINKER (default /lib64/ld-linux-x86-64.so.2),
           VSCODE_CONDA_SOLVER (default classic),
           VSCODE_TUNNEL_PROVIDER (sign-in for --background: github or microsoft).
Keep VSCODE_LOCAL_DIR on local disk. Editor data/extensions and compressed
server archives persist; deleted local servers are restored from the cache.
EOF
  exit 0
fi

script_path=$(readlink -f -- "${BASH_SOURCE[0]}")
WEBSTUDIO_SKIP_TUNNEL_PROMPT=1 source "$(dirname -- "${BASH_SOURCE[0]}")/../shell/init.sh"
source "$(dirname -- "${BASH_SOURCE[0]}")/ui.sh"
source "$(dirname -- "${BASH_SOURCE[0]}")/tunnel_config.sh"
ui_setup
mode=foreground
case "${1:-}" in
  --background|--status|--stop) mode=${1#--}; shift ;;
esac
session=vscode-tunnel
INSTALL_DIR="${VSCODE_INSTALL_DIR:-$WEBSTUDIO_PERSIST_ROOT/tools/vscode}"
RUNTIME="$INSTALL_DIR/runtime"
LOCAL_DIR="${VSCODE_LOCAL_DIR:-$WEBSTUDIO_LOCAL_DIR/vscode}"
CLI="$LOCAL_DIR/bin/code"
CLI_ARCHIVE="$INSTALL_DIR/cli-alpine-x64.tar.gz"
CLI_DATA_DIR="${VSCODE_CLI_DATA_DIR:-$WEBSTUDIO_TUNNEL_DIR/cli-data}"
SERVER_DATA_DIR="${VSCODE_PERSISTENT_DATA_DIR:-$WEBSTUDIO_AGENT_STATE_DIR/vscode-server}"
DOWNLOAD_CACHE="${VSCODE_DOWNLOAD_CACHE:-$INSTALL_DIR/server-archives}"
download_helper="$(dirname -- "$script_path")/vscode_downloads.py"

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
for required_tool in tar curl mktemp python3; do
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
# --server-data-dir controls editor data, but the CLI installs server binaries
# under its own data directory. Keep those thousands of files on local disk too.
mkdir -p -m 700 -- "$CLI_DATA_DIR" "$LOCAL_DIR/servers"
if [[ ! -e "$CLI_DATA_DIR/servers" && ! -L "$CLI_DATA_DIR/servers" ]]; then
  ln -s -- "$LOCAL_DIR/servers" "$CLI_DATA_DIR/servers"
fi
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

tunnel_connected() {
  "$CLI" tunnel status --cli-data-dir "$CLI_DATA_DIR" 2>/dev/null | grep -q '"tunnel":"Connected"'
}

session_running() {
  command -v tmux >/dev/null 2>&1 && tmux has-session -t "=$session" 2>/dev/null
}

saved_name() {
  local name=${WEBSTUDIO_TUNNEL_NAME:-}
  if [[ -n $name ]]; then printf '%s' "$name"; return; fi
  if [[ -s $WEBSTUDIO_TUNNEL_DIR/name ]]; then
    IFS= read -r name < "$WEBSTUDIO_TUNNEL_DIR/name"
  fi
  printf '%s' "$name"
}

# The CLI prints the editor URL when it connects; fall back to the tunnel root.
tunnel_url() {
  local url=
  if [[ -f $TUNNEL_LOG ]]; then
    url=$(sed 's/\x1b\[[0-9;?]*[A-Za-z]//g' "$TUNNEL_LOG" | grep -o 'https://vscode\.dev/tunnel/[^[:space:]]*' | tail -n 1)
  fi
  printf '%s' "${url:-https://vscode.dev/tunnel/$(saved_name)}"
}

# Mirror new tunnel output so ui_run shows it beside the spinner.
wait_for_tunnel() {
  local offset=0 size waited
  for ((waited = 0; waited < 180; waited++)); do
    size=$(stat -c %s -- "$TUNNEL_LOG" 2>/dev/null || echo 0)
    if (( size > offset )); then
      tail -c +$((offset + 1)) -- "$TUNNEL_LOG" | head -c $((size - offset))
      offset=$size
    fi
    if tunnel_connected; then return 0; fi
    if ! session_running; then
      echo 'The tunnel exited before it connected.'
      return 1
    fi
    sleep 1
  done
  echo "The tunnel did not connect within 3 minutes. Inspect it with: tmux attach -t $session"
  return 1
}

print_tunnel_access() {
  printf '%s%s%s  Open   %s%s%s%s\n' "$UI_MUTED" "$UI_BAR" "$UI_RESET" "$UI_BOLD" "$UI_ACCENT" "$(tunnel_url)" "$UI_RESET"
  if session_running; then
    ui_note "Logs   tmux attach -t $session   (detach: Ctrl+B, then D)"
  fi
  ui_note "Stop   $script_path --stop"
}

TUNNEL_LOG="$LOCAL_DIR/tunnel.log"
trap ui_cleanup EXIT
trap 'exit 130' INT TERM
case $mode in
  status)
    if tunnel_connected; then
      ui_ok "VS Code tunnel $(saved_name) is connected"
      print_tunnel_access
    else
      printf 'No VS Code tunnel is connected. Start one with: %s --background\n' "$script_path"
      exit 1
    fi
    exit 0
    ;;
  stop)
    if session_running; then tmux kill-session -t "=$session"; fi
    "$CLI" tunnel kill --cli-data-dir "$CLI_DATA_DIR" >/dev/null 2>&1 || true
    ui_ok 'VS Code tunnel stopped'
    exit 0
    ;;
  background)
    if (( $# )); then
      echo '--background does not accept tunnel options; edit the saved name with setup_tools.sh --tunnel-name.' >&2
      exit 2
    fi
    command -v tmux >/dev/null 2>&1 || {
      echo 'tmux is required for --background; rerun setup_tools.sh or start without --background.' >&2
      exit 1
    }
    webstudio_ensure_tunnel_name
    ui_bar
    if tunnel_connected; then
      ui_ok 'VS Code tunnel is already running'
      print_tunnel_access
      ui_outro 'Done'
      exit 0
    fi
    mkdir -p -m 700 -- "$CLI_DATA_DIR"
    # Sign in here so the device code is visible; the detached session cannot prompt.
    if ! "$CLI" tunnel user show --cli-data-dir "$CLI_DATA_DIR" >/dev/null 2>&1; then
      if [[ ! -t 0 ]]; then
        echo 'The tunnel is not signed in. Run start_vscode_tunnel.sh --background in a terminal once.' >&2
        exit 1
      fi
      ui_step 'Sign in to authorize the VS Code tunnel'
      ui_note "Open the link below and enter the code. The sign-in is kept in this container's tunnel directory."
      "$CLI" tunnel user login --provider "${VSCODE_TUNNEL_PROVIDER:-github}" --cli-data-dir "$CLI_DATA_DIR"
      ui_bar
    fi
    if ! session_running; then
      : > "$TUNNEL_LOG"
      chmod 600 -- "$TUNNEL_LOG"
      tmux_env=()
      for name in WEBSTUDIO_PERSIST_ROOT WEBSTUDIO_LOCAL_DIR VSCODE_INSTALL_DIR VSCODE_LOCAL_DIR \
        VSCODE_GLIBC_LINKER VSCODE_CONDA_SOLVER CONDA_EXE VSCODE_CLI_DATA_DIR WEBSTUDIO_TUNNEL_NAME WEBSTUDIO_TUNNEL_DIR \
        WEBSTUDIO_AGENT_STATE_DIR VSCODE_PERSISTENT_DATA_DIR VSCODE_DOWNLOAD_CACHE VSCODE_DOWNLOAD_WORKERS; do
        if [[ -n ${!name:-} ]]; then tmux_env+=(-e "$name=${!name}"); fi
      done
      printf -v pipe_command 'cat >> %q' "$TUNNEL_LOG"
      # Chain pipe-pane so logging starts before the pane prints anything.
      tmux new-session -d -s "$session" -c "$PWD" "${tmux_env[@]}" -- "$script_path" \; \
        pipe-pane -o "$pipe_command"
    fi
    ui_run "Starting VS Code tunnel $(saved_name)" wait_for_tunnel
    ui_ok 'VS Code tunnel is running in the background' "tmux session $session"
    print_tunnel_access
    ui_outro 'Done'
    exit 0
    ;;
esac

# Supply a newer C++ runtime while using the instance's existing glibc/linker.
# No conda activation is required.
export LD_LIBRARY_PATH="$RUNTIME/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export VSCODE_SERVER_CUSTOM_GLIBC_LINKER="$LINKER"
export VSCODE_SERVER_CUSTOM_GLIBC_PATH="$RUNTIME/lib:/lib64:/usr/lib64"
export VSCODE_SERVER_PATCHELF_PATH="$RUNTIME/bin/patchelf"

download_args=(--cache "$DOWNLOAD_CACHE" --local "$LOCAL_DIR/downloads" --workers "${VSCODE_DOWNLOAD_WORKERS:-32}")
if [[ "${1:-}" == --install-only || "${1:-}" == --prefetch ]]; then
  "$CLI" --version
  python3 "$download_helper" "${download_args[@]}" --prefetch
  echo "Installed. Start with: bash $0"
  exit 0
fi

# Identity stays separate from portable editor data and the archive cache.
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
  webstudio_ensure_tunnel_name
  tunnel_name=$(saved_name)
  [[ $tunnel_name =~ ^[A-Za-z0-9][A-Za-z0-9-]{0,19}$ ]] || {
    echo "Invalid saved tunnel name '$tunnel_name' (maximum 20 letters, digits, or hyphens)." >&2
    echo 'Run setup_tools.sh --tunnel-name SHORT-NAME to replace it.' >&2
    exit 2
  }
  tunnel_args=(--name "$tunnel_name" "${tunnel_args[@]}")
fi
echo 'Starting tunnel. Follow the license and sign-in prompts; Ctrl+C stops it.'
# Do not migrate live editor databases. Normal startup after --stop is safe;
# invoking foreground a second time must leave the running editor untouched.
if tunnel_connected; then
  echo 'VS Code tunnel is already connected. Stop it before starting another foreground instance.' >&2
  exit 1
fi
exec python3 "$download_helper" "${download_args[@]}" \
  --migrate-data "$LOCAL_DIR/server-data" "$SERVER_DATA_DIR" -- \
  "$CLI" tunnel --cli-data-dir "$CLI_DATA_DIR" \
  --server-data-dir "$SERVER_DATA_DIR" --extensions-dir "$SERVER_DATA_DIR/extensions" "${tunnel_args[@]}"
