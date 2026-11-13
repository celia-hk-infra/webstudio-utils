#!/usr/bin/env bash
# Sourced by setup_tools.sh after scripts/ui.sh and ui_setup; uses its
# skip_codex, skip_claude, tunnel_name, and start_tunnel variables.
# prompt_yes_no is also used by shell/init.sh and needs nothing else.
if ! declare -F ui_text >/dev/null; then
  source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/i18n.sh"
fi

choose_agents() {
  UI_MENU=($((1 - skip_codex)) $((1 - skip_claude)))
  ui_menu multi 'Which coding agents should be installed?' \
    'Codex|OpenAI Codex CLI' 'Claude Code|Anthropic Claude Code' || return
  skip_codex=$((1 - UI_MENU[0]))
  skip_claude=$((1 - UI_MENU[1]))
  local chosen=()
  (( skip_codex )) || chosen+=(Codex)
  (( skip_claude )) || chosen+=('Claude Code')
  if (( ${#chosen[@]} == 2 )); then
    ui_answer 'Coding agents' 'Codex, Claude Code'
  else
    ui_answer 'Coding agents' "${chosen[0]:-None (tools only)}"
  fi
}

choose_tools() {
  UI_MENU=($((1 - skip_tmux)) $((1 - skip_gh)))
  ui_menu multi 'Which optional tools should be installed?' \
    'tmux|Terminal sessions and background VS Code tunnels' \
    'GitHub CLI|gh commands and GitHub authentication' || return
  skip_tmux=$((1 - UI_MENU[0]))
  skip_gh=$((1 - UI_MENU[1]))
  local chosen=()
  (( skip_tmux )) || chosen+=(tmux)
  (( skip_gh )) || chosen+=(gh)
  ui_answer 'Optional tools' "${chosen[*]:-None}"
}

prompt_openlux_key() {
  local saved_auth=$1 title='OpenLux API key' valid='.'
  if [[ -n ${OPENLUX_API_KEY:-} ]]; then
    setup_api_key=$OPENLUX_API_KEY
  elif [[ -t 0 ]]; then
    if [[ $saved_auth == true ]]; then
      title+=" ${UI_DIM}(input hidden; Enter keeps saved credentials)${UI_RESET}"
      valid=''
    else
      title+=" ${UI_DIM}(input hidden)${UI_RESET}"
    fi
    ui_input setup_api_key "$title" '' '' 0 1 "$valid" \
      'A key is required for the selected agents' || { ui_error 'Setup cancelled.'; return 130; }
    if [[ -n $setup_api_key ]]; then
      ui_answer 'OpenLux API key' "Saved for the selected agents (${#setup_api_key} characters)"
    else
      ui_answer 'OpenLux API key' 'Keeping saved credentials'
    fi
  elif [[ $saved_auth != true ]]; then
    printf 'Set OPENLUX_API_KEY for unattended setup; selected agents have no saved API key.\n' >&2
    return 2
  fi
  if [[ $setup_api_key == *[$'\r\n\t ']* ]]; then
    printf 'The API key must not contain whitespace. Rerun setup with the key only.\n' >&2
    return 2
  fi
}

# VS Code limits tunnel names to 20 characters.
prompt_tunnel_name() {
  local default=$1
  ui_input tunnel_name "VS Code tunnel name ${UI_DIM}(Enter keeps ${default}; letters, digits, hyphens)${UI_RESET}" \
    "$default" '[A-Za-z0-9-]' 20 0 '^[A-Za-z0-9][A-Za-z0-9-]{0,19}$' 'must start with a letter or digit' ||
    { ui_error 'Setup cancelled.'; return 130; }
  ui_answer 'VS Code tunnel name' "$tunnel_name"
}

choose_tunnel_start() {
  local choices=(background foreground no)
  if (( ${skip_tmux:-0} )) && ! command -v tmux >/dev/null 2>&1; then
    UI_MENU=(0)
    ui_menu single 'Start the VS Code tunnel when setup finishes?' \
      'In this terminal|shows tunnel logs here; Ctrl+C stops it' \
      'Not now|start it later with scripts/start_vscode_tunnel.sh' || return
    choices=(foreground no)
  else
  UI_MENU=(0)
  ui_menu single 'Start the VS Code tunnel when setup finishes?' \
    'In the background|keeps running after you close this terminal (recommended)' \
    'In this terminal|shows tunnel logs here; Ctrl+C stops it' \
    'Not now|start it later with scripts/start_vscode_tunnel.sh' || return
  fi
  start_tunnel=${choices[UI_MENU[0]]}
  case $start_tunnel in
    background) ui_answer 'Start VS Code tunnel' 'In the background (tmux session vscode-tunnel)' ;;
    foreground) ui_answer 'Start VS Code tunnel' 'In this terminal' ;;
    no) ui_answer 'Start VS Code tunnel' 'Not now' ;;
  esac
}

# Default to no on Enter or EOF; retry unrecognized answers.
prompt_yes_no() {
  local answer
  while :; do
    printf '%s%s%s  %s' "${UI_MUTED:-}" "${UI_BAR:-|}" "${UI_RESET:-}" "$(ui_text "$1")"
    IFS= read -r answer || { printf '\n'; return 1; }
    case $answer in
      y|Y|yes|YES|Yes) return 0 ;;
      ''|n|N|no|NO|No) return 1 ;;
      *) printf '%s\n' "$(ui_text 'Please enter y or n.')" ;;
    esac
  done
}

choose_language() {
  if [[ -z ${WEBSTUDIO_LANGUAGE:-} && -t 0 ]]; then
    UI_MENU=(0)
    ui_menu single 'Language / 语言' 'English|Setup in English' '中文|使用中文安装' || return
    if (( UI_MENU[0] == 1 )); then WEBSTUDIO_LANGUAGE=zh; else WEBSTUDIO_LANGUAGE=en; fi
  fi
  export WEBSTUDIO_LANGUAGE=${WEBSTUDIO_LANGUAGE:-en}
  case $WEBSTUDIO_LANGUAGE in en|zh) ;; *) ui_error '--language must be en or zh'; return 2 ;; esac
}
