#!/usr/bin/env bash
# Source this once in the shell that starts your editor/tunnel:
#   source /path/to/webstudio-utils/shell/init.sh
# Replace /path/to with the directory containing your clone.
# Source it directly in JupyterLab terminals that skip Bash startup files.
# Run it again after a container restart to restore links in the temporary home.

if [[ ${BASH_SOURCE[0]} == "$0" ]]; then
    printf 'Source this file so its environment reaches child processes: source %s\n' "$0" >&2
    exit 2
fi

# Store private agent state on the mount containing this repository, outside Git.
_webstudio_shell_dir=$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}")") || return 1
WEBSTUDIO_PERSIST_ROOT=${WEBSTUDIO_PERSIST_ROOT:-$(cd -- "$_webstudio_shell_dir/../.." && pwd -P)}
export WEBSTUDIO_PERSIST_ROOT
WEBSTUDIO_AGENT_STATE_DIR=${WEBSTUDIO_AGENT_STATE_DIR:-$WEBSTUDIO_PERSIST_ROOT/.webstudio-agent-home}
export WEBSTUDIO_AGENT_STATE_DIR
if ! mkdir -p -m 700 -- "$WEBSTUDIO_AGENT_STATE_DIR"; then
    printf 'Could not create persistent agent directory: %s\n' "$WEBSTUDIO_AGENT_STATE_DIR" >&2
    return 1
fi
chmod 700 -- "$WEBSTUDIO_AGENT_STATE_DIR" || return 1

_webstudio_restore_link() {
    local target=$1 link=$2
    if [[ -e $link || -L $link ]]; then
        if [[ ! -L $link || $(readlink -- "$link") != "$target" ]]; then
            printf 'Keeping existing %s; migrate it to %s before removing it.\n' "$link" "$target" >&2
        fi
    else
        ln -s -- "$target" "$link" || return 1
    fi
}

# Add a line for any future tool that stores its state in a home directory.
for agent_dir in .codex .claude .cursor .gemini; do
    mkdir -p -m 700 -- "$WEBSTUDIO_AGENT_STATE_DIR/$agent_dir" || return 1
    _webstudio_restore_link "$WEBSTUDIO_AGENT_STATE_DIR/$agent_dir" "${HOME%/}/$agent_dir" || return 1
done
unset agent_dir

# This link makes later login Bash shells load the persistent profile.
_webstudio_restore_link \
    "$_webstudio_shell_dir/.bash_profile" \
    "${HOME%/}/.bash_profile" || return 1
unset -f _webstudio_restore_link
unset _webstudio_shell_dir

# Override a CODEX_HOME inherited from the disposable container home.
export CODEX_HOME="$WEBSTUDIO_AGENT_STATE_DIR/.codex"

# Keep GitHub CLI credentials on the persistent mount.
export GH_CONFIG_DIR="$WEBSTUDIO_AGENT_STATE_DIR/gh"
mkdir -p -m 700 -- "$GH_CONFIG_DIR" || return 1
chmod 700 -- "$GH_CONFIG_DIR" || return 1
_webstudio_gh_bin="$WEBSTUDIO_PERSIST_ROOT/tools/gh/current/bin"
if [[ -x "$_webstudio_gh_bin/gh" ]]; then
    case ":$PATH:" in
        *":$_webstudio_gh_bin:"*) ;;
        *) export PATH="$_webstudio_gh_bin:$PATH" ;;
    esac
fi
unset _webstudio_gh_bin

# /etc/profile sets TMOUT=300, which closes an idle interactive Bash shell.
unset TMOUT

# Global npm CLI installs made with `npm install -g` also survive restarts.
export npm_config_prefix="$WEBSTUDIO_AGENT_STATE_DIR/npm"
mkdir -p -m 700 -- "$npm_config_prefix/bin" || return 1
case ":$PATH:" in
    *":$npm_config_prefix/bin:"*) ;;
    *) export PATH="$npm_config_prefix/bin:$PATH" ;;
esac

# setup_container.sh stages Codex locally for faster startup.
WEBSTUDIO_LOCAL_DIR=${WEBSTUDIO_LOCAL_DIR:-/tmp/webstudio-${UID}}
export WEBSTUDIO_LOCAL_DIR
_webstudio_project_bin="$WEBSTUDIO_LOCAL_DIR/bin"
if [[ -x "$_webstudio_project_bin/codex" ]]; then
    case ":$PATH:" in
        *":$_webstudio_project_bin:"*) ;;
        *) export PATH="$_webstudio_project_bin:$PATH" ;;
    esac
fi
unset _webstudio_project_bin
