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
    if [[ -z $name ]]; then name=$(webstudio_default_tunnel_name); fi
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
