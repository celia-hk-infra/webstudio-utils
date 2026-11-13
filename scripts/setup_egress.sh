#!/usr/bin/env bash
# Sourced after agent installation. Never runs on ordinary shell startup.
setup_egress() {
  local egress="$repo_dir/vendor/codex-local-egress" input stage answer
  [[ -t 0 ]] || return 0
  prompt_yes_no 'Configure personal egress now? [y/N] ' || return 0
  git -C "$repo_dir" submodule update --init -- vendor/codex-local-egress || return
  export EGRESS_STATE_DIR="$WEBSTUDIO_AGENT_STATE_DIR/egress"
  mkdir -p -m 700 "$EGRESS_STATE_DIR"
  cat <<'EOF'
On your laptop/VPS, install GOST and Microsoft Dev Tunnels as described in:
https://github.com/celia-hk-infra/codex-local-egress
Then run:
  git clone https://github.com/celia-hk-infra/codex-local-egress.git
  cd codex-local-egress
  bash local.sh
Keep it running. Copy its connection.env to this container, or paste its three
lines below. Both endpoints must use the same Dev Tunnels identity.
EOF
  read -r -p 'Path to connection.env (Enter to paste; type skip to defer): ' input
  [[ $input != skip ]] || return 0
  stage=$(mktemp "$EGRESS_STATE_DIR/.connection.XXXXXX")
  chmod 600 "$stage"
  if [[ -n $input ]]; then cat -- "$input" > "$stage" || { rm -f "$stage"; return 1; }
  else
    echo 'Paste the three lines; finish with an empty line (input hidden).'
    while IFS= read -rs input && [[ -n $input ]]; do printf '%s\n' "$input" >> "$stage"; done
    echo
  fi
  if ! python3 "$egress/connection.py" "$stage" >/dev/null; then rm -f "$stage"; return 1; fi
  if [[ -f $EGRESS_STATE_DIR/connection.env ]] && ! cmp -s "$stage" "$EGRESS_STATE_DIR/connection.env" && tmux has-session -t webstudio-egress 2>/dev/null; then
    rm -f "$stage"; echo 'An existing egress session uses different settings. Stop that session deliberately before replacing them.' >&2; return 1
  fi
  mv "$stage" "$EGRESS_STATE_DIR/connection.env"
  command -v devtunnel >/dev/null || bash "$egress/install_dev_tunnel.sh"
  command -v tmux >/dev/null || { echo 'Install tmux or run remote.sh manually to connect egress.' >&2; return 1; }
  if ! tmux has-session -t webstudio-egress 2>/dev/null; then
    read -r -p 'Dev Tunnels login provider (github/microsoft): ' answer
    bash "$egress/remote.sh" devtunnel login "$answer"
    local command
    printf -v command 'EGRESS_STATE_DIR=%q bash %q' "$EGRESS_STATE_DIR" "$egress/remote.sh"
    tmux new-session -d -s webstudio-egress "$command"
  fi
  for ((attempt=0; attempt<10; attempt++)); do
    if bash "$egress/remote.sh" check >/dev/null 2>&1; then
      echo 'Personal egress ready. Use codex login or claude auth login after setup.'
      return 0
    fi
    sleep 1
  done
  echo 'Egress not ready. Inspect: tmux attach -t webstudio-egress' >&2
  return 1
}
