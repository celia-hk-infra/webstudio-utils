#!/usr/bin/env bash
# Sourced by setup_tools.sh; dependency output is logged by the shared UI.
setup_egress() {
  local egress="$repo_dir/vendor/codex-local-egress" input stage answer attempt
  [[ -t 0 ]] || return 0
  prompt_yes_no 'Configure personal egress now? [y/N] ' || return 0
  ui_step 'Personal egress'
  ui_run 'Preparing pinned egress tools' git -C "$repo_dir" submodule update --init -- vendor/codex-local-egress
  export EGRESS_STATE_DIR="$WEBSTUDIO_AGENT_STATE_DIR/egress"
  mkdir -p -m 700 "$EGRESS_STATE_DIR"
  ui_note 'On your laptop/Mac/VPS, clone this repository and start the egress host:' \
    '  git clone https://github.com/celia-hk-infra/webstudio-utils.git' \
    '  cd webstudio-utils' \
    'Install GOST v3, Python 3 and Dev Tunnels first; see vendor/codex-local-egress/README.md.' \
    "  bash scripts/start_egress_host.sh --language ${WEBSTUDIO_LANGUAGE:-en}" \
    'Keep it running. Copy connection.env from vendor/codex-local-egress, or paste its three lines below.' \
    'Both endpoints must sign in with the same Dev Tunnels account.'
  while :; do
    printf '%s  %s' "$UI_BAR" "$(ui_text 'Path to connection.env (Enter to paste; type skip to defer): ')"
    IFS= read -r input || return 0
    [[ $input != skip ]] || return 0
    [[ -z $input || -f $input && -r $input ]] && break
    ui_warn 'File not found; enter an absolute path or a path relative to this terminal.'
  done
  stage=$(mktemp "$EGRESS_STATE_DIR/.connection.XXXXXX")
  chmod 600 "$stage"
  if [[ -n $input ]]; then cat -- "$input" > "$stage" || { rm -f "$stage"; return 1; }
  else
    ui_note 'Paste the three lines; finish with an empty line (input hidden).'
    while IFS= read -rs input && [[ -n $input ]]; do printf '%s\n' "$input" >> "$stage"; done
    printf '\n'
  fi
  if ! python3 "$egress/connection.py" "$stage" >/dev/null; then rm -f "$stage"; return 1; fi
  if [[ -f $EGRESS_STATE_DIR/connection.env ]] && ! cmp -s "$stage" "$EGRESS_STATE_DIR/connection.env" && tmux has-session -t webstudio-egress 2>/dev/null; then
    rm -f "$stage"; ui_error 'An existing egress session uses different settings. Stop that session deliberately before replacing them.'; return 1
  fi
  mv "$stage" "$EGRESS_STATE_DIR/connection.env"
  if ! command -v devtunnel >/dev/null; then
    ui_run 'Installing Microsoft Dev Tunnels' bash "$egress/install_dev_tunnel.sh"
    export PATH="$HOME/.local/bin:$PATH"
  fi
  command -v tmux >/dev/null || { ui_error 'Install tmux or run remote.sh manually to connect egress.'; return 1; }
  if ! tmux has-session -t webstudio-egress 2>/dev/null; then
    UI_MENU=(0)
    ui_menu single 'Dev Tunnels login provider' 'GitHub|GitHub' 'Microsoft|Microsoft' || return
    answer=github
    (( UI_MENU[0] == 0 )) || answer=microsoft
    ui_note 'Sign in using the same account as your laptop/VPS. Open the URL and enter the code shown below.'
    # Use the pinned authentication helpers, while presenting our own UI.
    (
      DIR=$egress
      require() { command -v "$1" >/dev/null; }
      source "$egress/devtunnel-auth.sh"
      prepare_devtunnel
      local -a args=(user login -d)
      if [[ $answer == github ]]; then args+=(-g); else args+=(-e); fi
      devtunnel "${args[@]}" 2>&1 | python3 "$repo_dir/scripts/auth_output.py" "${WEBSTUDIO_LANGUAGE:-en}"
      chmod_devtunnel_state
    )
    local command
    printf -v command 'EGRESS_STATE_DIR=%q python3 %q' "$EGRESS_STATE_DIR" "$repo_dir/scripts/egress_supervisor.py"
    tmux new-session -d -s webstudio-egress "$command"
  fi
  for ((attempt=0; attempt<10; attempt++)); do
    if bash "$egress/remote.sh" check >/dev/null 2>&1; then
      ui_ok 'Personal egress ready. Use codex login or claude auth login after setup.'
      return 0
    fi
    sleep 1
  done
  ui_error 'Egress not ready. Inspect: tmux attach -t webstudio-egress'
  return 1
}
