#!/usr/bin/env bash
# Run once after a new container starts. Safe to rerun in the same container.
set -euo pipefail
# Do not expose credentials when invoked with bash -x or bash -v.
set +xv

repo_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
codex_version=${WEBSTUDIO_CODEX_VERSION:-0.166.0}
gh_version=${WEBSTUDIO_GH_VERSION:-2.103.3}
claude_version=${WEBSTUDIO_CLAUDE_VERSION:-2.1.322}
npm_registry=${WEBSTUDIO_NPM_REGISTRY:-https://registry.npmmirror.com}
agents=
use_openlux=ask
selection_explicit=0
skip_claude=0
skip_codex=0
skip_vscode=0
skip_gh_auth=0
start_tunnel=ask
tunnel_name=${WEBSTUDIO_TUNNEL_NAME:-}

usage() {
  cat <<'EOF'
Usage: ./setup_container.sh [--tunnel-name NAME] [--agents codex|claude|both|none] [--openlux | --official] [--skip-codex] [--skip-claude] [--skip-vscode] [--skip-gh-auth] [--start-tunnel[=background|foreground] | --no-start-tunnel]

Choose agents with Up/Down, Space to toggle, and Enter to continue.
Choose whether to override official endpoints with OpenLux (default: no).
Only OpenLux setup asks for an API key. Without a terminal, endpoints default
to official; use --openlux and OPENLUX_API_KEY to configure OpenLux.
Use --official to select official endpoints without a prompt.
GitHub login is required unless --skip-gh-auth is set. Interactive setup starts
browser login and saves the token in private persistent storage. Unattended
setup needs a saved GitHub login, GH_TOKEN, or GITHUB_TOKEN.
Install tmux in persistent storage using Conda, prepare agent tools, and install
the VS Code tunnel CLI. Interactive setup asks for a tunnel name (Enter keeps
the saved or default name) and whether to start the tunnel afterward: in a
background tmux session (default), in the terminal, or not at all.
Use --start-tunnel (background), --start-tunnel=foreground, or
--no-start-tunnel to choose without a prompt. Start the tunnel separately with:
  ./scripts/start_vscode_tunnel.sh --background
Command output is kept in $WEBSTUDIO_LOCAL_DIR/setup.log and shown on failure.

Set WEBSTUDIO_CODEX_VERSION to pin a different Codex CLI version.
Set WEBSTUDIO_CLAUDE_VERSION to pin Claude Code (default: 2.1.322).
Set WEBSTUDIO_NPM_REGISTRY to override https://registry.npmmirror.com.
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
    --agents)
      (($# >= 2)) || { echo 'Missing value for --agents' >&2; exit 2; }
      agents=$2; selection_explicit=1; shift 2 ;;
    --openlux) use_openlux=yes; shift ;;
    --official) use_openlux=no; shift ;;
    --skip-codex) skip_codex=1; selection_explicit=1; shift ;;
    --skip-claude) skip_claude=1; selection_explicit=1; shift ;;
    --skip-vscode) skip_vscode=1; shift ;;
    --skip-gh-auth) skip_gh_auth=1; shift ;;
    --start-tunnel|--start-tunnel=background) start_tunnel=background; shift ;;
    --start-tunnel=foreground) start_tunnel=foreground; shift ;;
    --no-start-tunnel) start_tunnel=no; shift ;;
    -h|--help) usage; exit 0 ;;
    *) printf 'Unknown option: %s\n' "$1" >&2; usage >&2; exit 2 ;;
  esac
done

if (( skip_vscode )) && [[ $start_tunnel == @(background|foreground) ]]; then
  echo '--start-tunnel cannot be combined with --skip-vscode.' >&2
  exit 2
fi

source "$repo_dir/scripts/ui.sh"
ui_setup
trap ui_cleanup EXIT
trap 'exit 130' INT TERM
source "$repo_dir/scripts/setup_prompts.sh"
if [[ -t 0 ]]; then ui_intro 'WebStudio container setup' 'Safe to rerun; answers are saved'; fi

if [[ -n $agents ]]; then
  case $agents in
    codex) skip_claude=1 ;;
    claude) skip_codex=1 ;;
    both) ;;
    none) skip_codex=1; skip_claude=1 ;;
    *) echo '--agents must be codex, claude, both, or none.' >&2; exit 2 ;;
  esac
elif (( ! selection_explicit )) && [[ -t 0 ]]; then
  choose_agents
fi
[[ $claude_version =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || {
  echo 'WEBSTUDIO_CLAUDE_VERSION must be a numeric release.' >&2; exit 2
}

[[ $codex_version =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || {
  echo 'WEBSTUDIO_CODEX_VERSION must be a numeric release, such as 0.166.0.' >&2
  exit 2
}
[[ $gh_version =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || {
  echo 'WEBSTUDIO_GH_VERSION must be a numeric release, such as 2.103.3.' >&2
  exit 2
}

persist_root=${WEBSTUDIO_PERSIST_ROOT:-$(cd -- "$repo_dir/.." && pwd -P)}
export WEBSTUDIO_SETUP_RUNNING=1
WEBSTUDIO_REPORT_LINK_CONFLICTS=1 source "$repo_dir/shell/init.sh"
setup_api_key=
export -n setup_api_key
if (( ! skip_codex || ! skip_claude )); then
  command -v node >/dev/null || { echo 'node is required to configure agents.' >&2; exit 1; }
  if [[ $use_openlux == ask ]]; then
    use_openlux=no
    if [[ -t 0 ]] && prompt_yes_no 'Override official endpoints with OpenLux? [y/N] '; then
      use_openlux=yes
    fi
  fi
  if [[ $use_openlux == yes ]]; then
  saved_auth=$(node "$repo_dir/scripts/has_saved_agent_auth.cjs" "$CODEX_HOME" "$CLAUDE_CONFIG_DIR" "$skip_codex" "$skip_claude")
  prompt_openlux_key "$saved_auth"
  fi
fi
# Keep the key in a non-exported shell variable until it is piped to each CLI.
unset OPENLUX_API_KEY

tunnel_dir="$WEBSTUDIO_PERSIST_ROOT/.webstudio-tunnel"
mkdir -p -m 700 -- "$tunnel_dir/cli-data"
chmod 700 -- "$tunnel_dir" "$tunnel_dir/cli-data"
if [[ -z $tunnel_name ]]; then
  if [[ -s $tunnel_dir/name ]]; then
    IFS= read -r tunnel_name < "$tunnel_dir/name"
  else
    tunnel_name=$(basename -- "$WEBSTUDIO_PERSIST_ROOT" | tr -c 'A-Za-z0-9-\n' - | cut -c 1-10)
    tunnel_name="webstudio-$tunnel_name"
  fi
  if (( ! skip_vscode )) && [[ -t 0 ]]; then
    [[ $tunnel_name =~ ^[A-Za-z0-9][A-Za-z0-9-]{0,19}$ ]] || tunnel_name=webstudio
    prompt_tunnel_name "$tunnel_name"
  fi
fi
[[ $tunnel_name =~ ^[A-Za-z0-9][A-Za-z0-9-]{0,19}$ ]] || {
  echo 'Tunnel name must contain only letters, digits, and hyphens (up to 20 characters).' >&2
  exit 2
}
printf '%s\n' "$tunnel_name" > "$tunnel_dir/name"
chmod 600 -- "$tunnel_dir/name"
if (( ! skip_vscode )) && [[ $start_tunnel == ask && -t 0 ]]; then
  choose_tunnel_start
fi

mkdir -p -- "$WEBSTUDIO_LOCAL_DIR/bin"
chmod 700 -- "$WEBSTUDIO_LOCAL_DIR"
UI_LOG="$WEBSTUDIO_LOCAL_DIR/setup.log"
: > "$UI_LOG"
chmod 600 -- "$UI_LOG"
if [[ -t 0 ]]; then ui_step 'Installing'; fi

# Install the official GitHub CLI archive once on the persistent mount.
gh_root="$WEBSTUDIO_PERSIST_ROOT/tools/gh"
gh_release="$gh_root/$gh_version"
mkdir -p -- "$gh_root"
install_gh() {
  command -v curl >/dev/null || { echo 'curl is required to install gh.' >&2; exit 1; }
  command -v sha256sum >/dev/null || { echo 'sha256sum is required to verify gh.' >&2; exit 1; }
  gh_stage=$(mktemp -d "$gh_root/.install.XXXXXX")
  gh_base="https://github.com/cli/cli/releases/download/v$gh_version/gh_${gh_version}"
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
}
if [[ ! -x $gh_release/bin/gh ]]; then
  ui_run "Installing GitHub CLI $gh_version" install_gh
fi
ln -sfnT -- "$gh_version" "$gh_root/current"
# The first shell init ran before gh existed; expose the new install now.
export PATH="$gh_root/current/bin:$PATH"
ui_ok "GitHub CLI $gh_version" "$gh_root/current/bin/gh"
if (( ! skip_gh_auth )); then
  if ! gh auth status --hostname github.com >/dev/null 2>&1; then
    if [[ ! -t 0 ]]; then
      echo 'GitHub login required. Rerun setup in a terminal, supply GH_TOKEN or GITHUB_TOKEN, or use --skip-gh-auth.' >&2
      exit 2
    fi
    ui_bar
    ui_step 'Sign in to GitHub.'
    ui_note 'The token is stored in the private persistent gh directory.'
    (umask 077; gh auth login --hostname github.com --git-protocol https --web --insecure-storage)
    ui_bar
  fi
  # Restore Git's credential helper even when the container home is new.
  gh auth setup-git --hostname github.com
  if [[ -f $GH_CONFIG_DIR/hosts.yml ]]; then
    chmod 600 -- "$GH_CONFIG_DIR/hosts.yml"
  fi
  ui_ok 'GitHub authentication ready' 'Git uses gh for HTTPS credentials'
fi

# Keep tmux and its libraries together on the persistent mount.
tmux_prefix="$WEBSTUDIO_PERSIST_ROOT/tools/tmux"
if [[ ! -x $tmux_prefix/bin/tmux ]]; then
  conda_bin=${CONDA_EXE:-}
  if [[ -z $conda_bin ]]; then
    if command -v conda >/dev/null 2>&1; then
      conda_bin=conda
    elif [[ -x /opt/huawei/miniconda/envs/python39/bin/conda ]]; then
      conda_bin=/opt/huawei/miniconda/envs/python39/bin/conda
    else
      echo 'Conda is required to install tmux. Set CONDA_EXE=/path/to/conda and rerun.' >&2
      exit 1
    fi
  fi
  conda_action=create
  [[ ! -d $tmux_prefix/conda-meta ]] || conda_action=install
  ui_run 'Installing tmux with Conda' "$conda_bin" "$conda_action" --yes --prefix "$tmux_prefix" --solver classic \
    --override-channels --channel conda-forge --repodata-fn current_repodata.json tmux
fi
ui_ok "$("$tmux_prefix/bin/tmux" -V)" "$tmux_prefix/bin/tmux"
export PATH="$tmux_prefix/bin:$PATH"

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

install_agent() {
  local agent_name=$1 agent_package=$2 agent_version=$3 agent_label=$4
  local agent_root agent_cache install_stage local_agent_root local_agent local_stage
  command -v npm >/dev/null || { echo "npm is required to install ${agent_label}." >&2; exit 1; }
  command -v node >/dev/null || { echo "node is required to run ${agent_label}." >&2; exit 1; }
  agent_root="$WEBSTUDIO_PERSIST_ROOT/tools/$agent_name"
  agent_cache="$agent_root/$agent_version"
  mkdir -p -- "$agent_root" "$WEBSTUDIO_PERSIST_ROOT/cache/npm"
  if [[ ! -x $agent_cache/node_modules/.bin/$agent_name ]]; then
    install_stage=$(mktemp -d "$agent_root/.install.XXXXXX")
    if ! npm_config_cache="$WEBSTUDIO_PERSIST_ROOT/cache/npm" npm install --registry "$npm_registry" \
      --prefix "$install_stage" --no-save --no-audit --no-fund \
      "${agent_package}@$agent_version"; then
      rm -rf -- "$install_stage"
      exit 1
    fi
    if [[ ! -x $install_stage/node_modules/.bin/$agent_name ]]; then
      rm -rf -- "$install_stage"
      echo "${agent_label} install did not produce a CLI." >&2
      exit 1
    fi
    if [[ -e $agent_cache ]]; then
      echo "Incomplete ${agent_label} cache at $agent_cache; move it aside and rerun." >&2
      exit 1
    fi
    mv -- "$install_stage" "$agent_cache"
  fi

  local_agent_root="$WEBSTUDIO_LOCAL_DIR/$agent_name"
  local_agent="$local_agent_root/$agent_version"
  mkdir -p -- "$local_agent_root"
  if [[ ! -x $local_agent/node_modules/.bin/$agent_name ]]; then
    local_stage=$(mktemp -d "$local_agent_root/.stage.XXXXXX")
    cp -a -- "$agent_cache/node_modules" "$local_stage/"
    if [[ ! -x $local_stage/node_modules/.bin/$agent_name ]]; then
      rm -rf -- "$local_stage"
      echo "Local ${agent_label} copy is incomplete." >&2
      exit 1
    fi
    if [[ -e $local_agent ]]; then
      echo "Incomplete local ${agent_label} copy at $local_agent; move it aside and rerun." >&2
      exit 1
    fi
    mv -- "$local_stage" "$local_agent"
  fi
  ln -sfnT -- "$local_agent/node_modules/.bin/$agent_name" "$WEBSTUDIO_LOCAL_DIR/bin/$agent_name"
}

codex_login() {
  printf '%s' "$setup_api_key" | "$WEBSTUDIO_LOCAL_DIR/bin/codex" login --with-api-key
}

if (( ! skip_codex )); then
  ui_run "Installing Codex $codex_version" install_agent codex "@openai/codex" "$codex_version" Codex
  if [[ $use_openlux == yes ]]; then
  # Keep this setting at TOML's top level, before any table headers.
  codex_config="$CODEX_HOME/config.toml"
  config_stage=$(mktemp "${codex_config%/*}/.config.XXXXXX")
  awk '
    BEGIN {
      print "openai_base_url = \"https://api.openlux.ai/v1\""
      print "cli_auth_credentials_store = \"file\""
    }
    /^[[:space:]]*\[/ { in_table = 1 }
    !in_table && /^[[:space:]]*openai_base_url[[:space:]]*=/ { next }
    !in_table && /^[[:space:]]*cli_auth_credentials_store[[:space:]]*=/ { next }
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
  if [[ -n $setup_api_key ]]; then
    ui_run 'Saving the OpenLux key for Codex' codex_login
  fi
  chmod 600 -- "$CODEX_HOME/auth.json"
  else
    node "$repo_dir/scripts/restore_official.cjs" codex "$CODEX_HOME"
  fi
  ui_ok "Codex $codex_version ready" "$WEBSTUDIO_LOCAL_DIR/bin/codex"
fi

if (( ! skip_claude )); then
  ui_run "Installing Claude Code $claude_version" install_agent claude "@anthropic-ai/claude-code" "$claude_version" 'Claude Code'
  if [[ $use_openlux == yes ]]; then
  printf '%s' "$setup_api_key" | node "$repo_dir/scripts/configure_claude.cjs" "$CLAUDE_CONFIG_DIR/settings.json" --key-stdin
  else
    node "$repo_dir/scripts/restore_official.cjs" claude "$CLAUDE_CONFIG_DIR"
  fi
  ui_ok "Claude Code $claude_version ready" "$WEBSTUDIO_LOCAL_DIR/bin/claude"
fi
unset setup_api_key

if (( ! skip_vscode )); then
  ui_run 'Installing the VS Code tunnel CLI' "$repo_dir/scripts/start_vscode_tunnel.sh" --install-only
  ui_ok 'VS Code tunnel CLI ready' "tunnel name: $tunnel_name"
fi

installed=()
(( skip_codex )) || installed+=(codex)
(( skip_claude )) || installed+=(claude)
printf -v init_command 'source %q' "$repo_dir/shell/init.sh"
ui_bar
summary=("Agents     ${installed[*]:-none}")
(( skip_vscode )) || summary+=("Tunnel     $tunnel_name")
summary+=("Storage    $WEBSTUDIO_PERSIST_ROOT" "Setup log  $UI_LOG" ''
  'New terminals load the environment automatically.' 'In this terminal, run first:' "  $init_command")
if (( ! skip_vscode )) && [[ $start_tunnel != @(background|foreground) ]]; then
  summary+=('' 'Start VS Code later:' "  $repo_dir/scripts/start_vscode_tunnel.sh --background")
fi
ui_box 'Setup complete' "${summary[@]}"

# Only mark a fully completed setup; local storage is reset on replacement.
printf '%s\n' "$repo_dir" > "$WEBSTUDIO_LOCAL_DIR/.setup-complete"
chmod 600 -- "$WEBSTUDIO_LOCAL_DIR/.setup-complete"
unset WEBSTUDIO_SETUP_RUNNING
if (( ! skip_vscode )); then
  case $start_tunnel in
    background)
      "$repo_dir/scripts/start_vscode_tunnel.sh" --background
      ;;
    foreground)
      ui_note 'Keep this terminal open while using the tunnel. Ctrl+C stops it.'
      exec "$repo_dir/scripts/start_vscode_tunnel.sh"
      ;;
  esac
fi
