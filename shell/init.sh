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
if [[ $(stat -c %a -- "$WEBSTUDIO_AGENT_STATE_DIR") != 700 ]]; then
    printf 'Agent home must have mode 700: %s\n' "$WEBSTUDIO_AGENT_STATE_DIR" >&2
    printf '%s\n' 'This filesystem did not preserve chmod 700. Use a persistent mount that supports Unix permissions (such as gabriel-sfs).' >&2
    printf '%s\n' 'Check WEBSTUDIO_PERSIST_ROOT and WEBSTUDIO_AGENT_STATE_DIR for overrides pointing at an old mount.' >&2
    return 1
fi

_webstudio_restore_link() {
    local target=$1 link=$2 previous
    # Repair broken links left by a moved/deleted Webstudio state directory.
    # Real directories and links to unrelated locations remain untouched.
    if [[ -L $link && ! -e $link ]]; then
        previous=$(readlink -- "$link")
        if [[ $previous == */.webstudio-agent-home/"${link##*/}" ]]; then
            ln -sfnT -- "$target" "$link" || return 1
            return 0
        fi
    fi
    if [[ -e $link || -L $link ]]; then
        if [[ ${WEBSTUDIO_REPORT_LINK_CONFLICTS:-0} == 1 ]] &&
            [[ ! -L $link || $(readlink -- "$link") != "$target" ]]; then
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

# Bash uses HOME for startup files, even in containers running as root.
# Preserve vendor startup files and add the same hook to both shell modes.
_webstudio_install_hook() {
    local file=$1 hook
    printf -v hook 'source %q # webstudio shell init' "$_webstudio_shell_dir/init.sh"
    if [[ -L $file && ! -e $file ]]; then
        printf 'Broken startup symlink: %s; repair it before rerunning setup.\n' "$file" >&2
        return 1
    fi
    # ModelArts root homes may source a ma-user file that is absent.
    # Guard only the known vendor line, preserving other startup commands.
    if [[ -f $file ]] && grep -Fqx -- '[ "$DISABLE_MA_USER_BASHRC" != "true" ] && source /home/ma-user/.bashrc' "$file"; then
        sed -i --follow-symlinks 's|^\[ "$DISABLE_MA_USER_BASHRC" != "true" \] \&\& source /home/ma-user/.bashrc$|[ "$DISABLE_MA_USER_BASHRC" != "true" ] \&\& [ -f /home/ma-user/.bashrc ] \&\& source /home/ma-user/.bashrc|' "$file" || return 1
    fi
    if ! grep -Fqx -- "$hook" "$file" 2>/dev/null; then
        printf '\n%s\n' "$hook" >> "$file" || return 1
    fi
}
_webstudio_install_hook "${HOME%/}/.bashrc" || return 1
# Bash reads only the first existing login startup file.
_webstudio_login_file="${HOME%/}/.bash_profile"
if [[ ! -e $_webstudio_login_file && ! -L $_webstudio_login_file ]]; then
    for _webstudio_candidate in .bash_login .profile; do
        if [[ -f ${HOME%/}/$_webstudio_candidate ]]; then
            _webstudio_login_file="${HOME%/}/$_webstudio_candidate"
            break
        fi
    done
fi
# Older setups linked this repository's profile, which already sources init.sh.
if [[ $(readlink -f -- "$_webstudio_login_file") != "$_webstudio_shell_dir/.bash_profile" ]]; then
    _webstudio_install_hook "$_webstudio_login_file" || return 1
fi
unset -f _webstudio_install_hook _webstudio_restore_link
unset _webstudio_shell_dir _webstudio_login_file _webstudio_candidate

# Override a CODEX_HOME inherited from the disposable container home.
export CODEX_HOME="$WEBSTUDIO_AGENT_STATE_DIR/.codex"
export CLAUDE_CONFIG_DIR="$WEBSTUDIO_AGENT_STATE_DIR/.claude"
export ANTHROPIC_BASE_URL="https://api.openlux.ai"
# Explicit gateway mode disables model discovery in Claude Code 2.1.322.
unset CLAUDE_CODE_USE_GATEWAY
export CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=1

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

# setup_container.sh stages agent CLIs locally for faster startup.
WEBSTUDIO_LOCAL_DIR=${WEBSTUDIO_LOCAL_DIR:-/tmp/webstudio-${UID}}
export WEBSTUDIO_LOCAL_DIR
_webstudio_project_bin="$WEBSTUDIO_LOCAL_DIR/bin"
if [[ -d "$_webstudio_project_bin" ]]; then
    case ":$PATH:" in
        *":$_webstudio_project_bin:"*) ;;
        *) export PATH="$_webstudio_project_bin:$PATH" ;;
    esac
fi
unset _webstudio_project_bin
