#!/usr/bin/env bash
# Sourced after shell/init.sh; keep tunnel identity on container-local storage.
webstudio_default_tunnel_name() {
    # Random suffix avoids collisions even when containers share a hostname.
    printf 'webstudio-%s' "$(od -An -N5 -tx1 /dev/urandom | tr -d ' \n')"
}

webstudio_ensure_tunnel_name() {
    local name=${WEBSTUDIO_TUNNEL_NAME:-} stage
    if [[ -z $name && -s $WEBSTUDIO_TUNNEL_DIR/name ]]; then
        IFS= read -r name < "$WEBSTUDIO_TUNNEL_DIR/name"
    fi
    if [[ -z $name ]]; then
        name=$(webstudio_default_tunnel_name)
        if [[ -t 0 ]]; then
            local answer
            while :; do
                printf 'VS Code tunnel name [Enter keeps %s]: ' "$name"
                IFS= read -r answer || return 130
                answer=${answer:-$name}
                if [[ $answer =~ ^[A-Za-z0-9][A-Za-z0-9-]{0,19}$ ]]; then
                    name=$answer
                    break
                fi
                printf 'Use up to 20 letters, digits, or hyphens, starting with a letter or digit.\n'
            done
        fi
    fi
    [[ $name =~ ^[A-Za-z0-9][A-Za-z0-9-]{0,19}$ ]] || {
        echo 'Tunnel name must contain only letters, digits, and hyphens (up to 20 characters).' >&2
        return 2
    }
    mkdir -p -m 700 -- "$WEBSTUDIO_TUNNEL_DIR" || return 1
    chmod 700 -- "$WEBSTUDIO_TUNNEL_DIR" || return 1
    stage=$(mktemp "$WEBSTUDIO_TUNNEL_DIR/.name.XXXXXX") || return 1
    printf '%s\n' "$name" > "$stage"
    mv -- "$stage" "$WEBSTUDIO_TUNNEL_DIR/name"
}

# Run only from terminal initialization; never install tools just to check status.
webstudio_offer_tunnel() {
    local repo=$1 name= cli data prompt
    cli="${VSCODE_LOCAL_DIR:-$WEBSTUDIO_LOCAL_DIR/vscode}/bin/code"
    data="${VSCODE_CLI_DATA_DIR:-$WEBSTUDIO_TUNNEL_DIR/cli-data}"
    if [[ -x $cli ]] && "$cli" tunnel status --cli-data-dir "$data" 2>/dev/null |
        grep -Eq '"tunnel"[[:space:]]*:[[:space:]]*"Connected"'; then
        printf 'VS Code tunnel is already connected.\n'
        return 0
    fi
    if command -v tmux >/dev/null 2>&1 && tmux has-session -t '=vscode-tunnel' 2>/dev/null; then
        printf 'VS Code tunnel session is running. View it with: tmux attach -t vscode-tunnel\n'
        return 0
    fi
    name=${WEBSTUDIO_TUNNEL_NAME:-}
    if [[ -z $name && -s $WEBSTUDIO_TUNNEL_DIR/name ]]; then
        IFS= read -r name < "$WEBSTUDIO_TUNNEL_DIR/name"
    fi
    if [[ -n $name ]]; then
        prompt="Resume VS Code tunnel $name? [y/N] "
    else
        prompt='Create and start a VS Code tunnel for this container? [y/N] '
    fi
    source "$repo/scripts/setup_prompts.sh"
    if prompt_yes_no "$prompt"; then
        if command -v tmux >/dev/null 2>&1; then
            bash "$repo/scripts/start_vscode_tunnel.sh" --background
        else
            printf 'tmux is unavailable; the tunnel will run in this terminal (Ctrl+C stops it).\n'
            bash "$repo/scripts/start_vscode_tunnel.sh"
        fi
    fi
    return 0
}
