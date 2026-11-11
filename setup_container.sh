#!/usr/bin/env bash
# Run once after a new container starts. Safe to rerun in the same container.
set -euo pipefail

repo_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
codex_version=${WEBSTUDIO_CODEX_VERSION:-0.166.0}
gh_version=${WEBSTUDIO_GH_VERSION:-2.103.3}
skip_codex=0
skip_vscode=0
tunnel_name=${WEBSTUDIO_TUNNEL_NAME:-}

usage() {
  cat <<'EOF'
Usage: ./setup_container.sh [--tunnel-name NAME] [--skip-codex] [--skip-vscode]

Prepare persistent Codex state and tools, stage Codex on local disk, and install
the VS Code tunnel CLI. Start the tunnel separately with:
  ./scripts/start_vscode_tunnel.sh

Set WEBSTUDIO_CODEX_VERSION to pin a different Codex CLI version.
Set WEBSTUDIO_GH_VERSION to pin a different GitHub CLI version.
Set WEBSTUDIO_PERSIST_ROOT and WEBSTUDIO_LOCAL_DIR to override storage locations.
EOF
}

while (($#)); do
  case $1 in
    --tunnel-name)
      (($# >= 2)) || { echo 'Missing value for --tunnel-name' >&2; exit 2; }
      tunnel_name=$2
      shift 2
      ;;
    --skip-codex) skip_codex=1; shift ;;
    --skip-vscode) skip_vscode=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) printf 'Unknown option: %s\n' "$1" >&2; usage >&2; exit 2 ;;
  esac
done

[[ $codex_version =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || {
  echo 'WEBSTUDIO_CODEX_VERSION must be a numeric release, such as 0.166.0.' >&2
  exit 2
}
[[ $gh_version =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || {
  echo 'WEBSTUDIO_GH_VERSION must be a numeric release, such as 2.103.3.' >&2
  exit 2
}

persist_root=${WEBSTUDIO_PERSIST_ROOT:-$(cd -- "$repo_dir/.." && pwd -P)}
source "$repo_dir/shell/init.sh"
mkdir -p -- "$WEBSTUDIO_LOCAL_DIR/bin"
chmod 700 -- "$WEBSTUDIO_LOCAL_DIR"

# Install the official GitHub CLI archive once on the persistent mount.
gh_root="$WEBSTUDIO_PERSIST_ROOT/tools/gh"
gh_release="$gh_root/$gh_version"
mkdir -p -- "$gh_root"
if [[ ! -x $gh_release/bin/gh ]]; then
  command -v curl >/dev/null || { echo 'curl is required to install gh.' >&2; exit 1; }
  command -v sha256sum >/dev/null || { echo 'sha256sum is required to verify gh.' >&2; exit 1; }
  gh_stage=$(mktemp -d "$gh_root/.install.XXXXXX")
  gh_base="https://github.com/cli/cli/releases/download/v$gh_version/gh_${gh_version}"
  echo "Installing gh $gh_version to persistent storage..."
  curl -fL --retry 3 -o "$gh_stage/gh.tar.gz" "${gh_base}_linux_amd64.tar.gz"
  curl -fL --retry 3 -o "$gh_stage/checksums.txt" "${gh_base}_checksums.txt"
  (cd "$gh_stage" && grep " gh_${gh_version}_linux_amd64.tar.gz\$" checksums.txt | sed "s/ gh_${gh_version}_linux_amd64.tar.gz\$/ gh.tar.gz/" | sha256sum -c -)
  tar -xzf "$gh_stage/gh.tar.gz" -C "$gh_stage"
  if [[ -e $gh_release ]]; then
    echo "Incomplete gh install at $gh_release; move it aside and rerun." >&2
    exit 1
  fi
  mv -- "$gh_stage/gh_${gh_version}_linux_amd64" "$gh_release"
  rm -f -- "$gh_stage/gh.tar.gz" "$gh_stage/checksums.txt"
  rmdir -- "$gh_stage"
fi
ln -sfnT -- "$gh_version" "$gh_root/current"
echo "GitHub CLI ready: $gh_root/current/bin/gh"

# The daemon requires its control directory to be private. A migrated Codex
# install may also retain an absolute link to the previous mount's package.
codex_control_dir="$CODEX_HOME/app-server-control"
if [[ -L $codex_control_dir ]]; then
  echo "Codex control directory must be a real directory: $codex_control_dir" >&2
  exit 1
fi
mkdir -p -m 700 -- "$codex_control_dir"
chmod 700 -- "$codex_control_dir"
if [[ $(stat -c %a -- "$codex_control_dir") != 700 ]]; then
  echo "Codex control directory must have mode 700: $codex_control_dir" >&2
  exit 1
fi
daemon_package_dir="$CODEX_HOME/packages/app-server-daemon"
if [[ -L $daemon_package_dir/current ]]; then
  daemon_target=$(readlink -- "$daemon_package_dir/current")
  if [[ $daemon_target == /*/packages/app-server-daemon/releases/* ]]; then
    daemon_release=${daemon_target##*/}
    if [[ -x $daemon_package_dir/releases/$daemon_release/bin/codex ]]; then
      ln -sfnT -- "releases/$daemon_release" "$daemon_package_dir/current"
    fi
  fi
fi

tunnel_dir="$WEBSTUDIO_PERSIST_ROOT/.webstudio-tunnel"
mkdir -p -m 700 -- "$tunnel_dir/cli-data"
chmod 700 -- "$tunnel_dir" "$tunnel_dir/cli-data"
if [[ -z $tunnel_name ]]; then
  if [[ -s $tunnel_dir/name ]]; then
    IFS= read -r tunnel_name < "$tunnel_dir/name"
  else
    tunnel_name="webstudio-$(basename -- "$WEBSTUDIO_PERSIST_ROOT" | cut -c 1-10)"
  fi
fi
[[ $tunnel_name =~ ^[A-Za-z0-9][A-Za-z0-9-]{0,19}$ ]] || {
  echo 'Tunnel name must contain only letters, digits, and hyphens (up to 20 characters).' >&2
  exit 2
}
printf '%s\n' "$tunnel_name" > "$tunnel_dir/name"
chmod 600 -- "$tunnel_dir/name"

if (( ! skip_codex )); then
  command -v npm >/dev/null || { echo 'npm is required to install Codex.' >&2; exit 1; }
  command -v node >/dev/null || { echo 'node is required to run Codex.' >&2; exit 1; }
  codex_root="$WEBSTUDIO_PERSIST_ROOT/tools/codex"
  codex_cache="$codex_root/$codex_version"
  mkdir -p -- "$codex_root" "$WEBSTUDIO_PERSIST_ROOT/cache/npm"
  if [[ ! -x $codex_cache/node_modules/.bin/codex ]]; then
    install_stage=$(mktemp -d "$codex_root/.install.XXXXXX")
    echo "Installing @openai/codex@$codex_version to persistent cache..."
    if ! npm_config_cache="$WEBSTUDIO_PERSIST_ROOT/cache/npm" npm install \
      --prefix "$install_stage" --no-save --no-audit --no-fund \
      "@openai/codex@$codex_version"; then
      rm -rf -- "$install_stage"
      exit 1
    fi
    if [[ ! -x $install_stage/node_modules/.bin/codex ]]; then
      rm -rf -- "$install_stage"
      echo 'Codex install did not produce a CLI.' >&2
      exit 1
    fi
    if [[ -e $codex_cache ]]; then
      echo "Incomplete Codex cache at $codex_cache; move it aside and rerun." >&2
      exit 1
    fi
    mv -- "$install_stage" "$codex_cache"
  fi

  local_codex_root="$WEBSTUDIO_LOCAL_DIR/codex"
  local_codex="$local_codex_root/$codex_version"
  mkdir -p -- "$local_codex_root"
  if [[ ! -x $local_codex/node_modules/.bin/codex ]]; then
    local_stage=$(mktemp -d "$local_codex_root/.stage.XXXXXX")
    echo 'Copying Codex CLI from persistent storage to local disk...'
    cp -a -- "$codex_cache/node_modules" "$local_stage/"
    if [[ ! -x $local_stage/node_modules/.bin/codex ]]; then
      rm -rf -- "$local_stage"
      echo 'Local Codex copy is incomplete.' >&2
      exit 1
    fi
    if [[ -e $local_codex ]]; then
      echo "Incomplete local Codex copy at $local_codex; move it aside and rerun." >&2
      exit 1
    fi
    mv -- "$local_stage" "$local_codex"
  fi
  ln -sfnT -- "$local_codex/node_modules/.bin/codex" "$WEBSTUDIO_LOCAL_DIR/bin/codex"
  # Keep this setting at TOML's top level, before any table headers.
  codex_config="$CODEX_HOME/config.toml"
  config_stage=$(mktemp "${codex_config%/*}/.config.XXXXXX")
  awk '
    BEGIN { print "openai_base_url = \"https://api.openlux.ai/v1\"" }
    /^[[:space:]]*\[/ { in_table = 1 }
    !in_table && /^[[:space:]]*openai_base_url[[:space:]]*=/ { next }
    { print }
  ' "$codex_config" > "$config_stage" 2>/dev/null || {
    if [[ -e $codex_config ]]; then
      rm -f -- "$config_stage"
      echo "Could not read Codex configuration: $codex_config" >&2
      exit 1
    fi
  }
  cat -- "$config_stage" > "$codex_config"
  chmod 600 -- "$codex_config"
  rm -f -- "$config_stage"
  echo "Codex ready: $WEBSTUDIO_LOCAL_DIR/bin/codex"
fi

if (( ! skip_vscode )); then
  "$repo_dir/scripts/start_vscode_tunnel.sh" --install-only
fi

printf 'Persistent state: %s\nTunnel name: %s\n' "$WEBSTUDIO_PERSIST_ROOT" "$tunnel_name"
printf 'For this shell: source %q\n' "$repo_dir/shell/init.sh"
printf 'To start VS Code: %q\n' "$repo_dir/scripts/start_vscode_tunnel.sh"
echo 'To reopen a saved Codex session: codex resume'
