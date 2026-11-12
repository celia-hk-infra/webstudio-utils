#!/usr/bin/env bash
# Sourced by setup_container.sh; uses its skip_codex/skip_claude variables.
choose_agents() {
  local selected=0 key suffix row mark pointer
  printf '\nChoose agents\nUp/Down: move   Space: toggle   Enter: continue   q: cancel\n'
  while :; do
    for row in 0 1; do
      mark=x; pointer=' '
      if (( row == 0 && skip_codex || row == 1 && skip_claude )); then mark=' '; fi
      if (( row == selected )); then pointer='>'; fi
      if (( row == 0 )); then
        printf '\r\033[2K%s [%s] Codex\n' "$pointer" "$mark"
      else
        printf '\r\033[2K%s [%s] Claude Code\n' "$pointer" "$mark"
      fi
    done
    IFS= read -rsn1 key || return 130
    case $key in
      $'\033')
        suffix=
        IFS= read -rsn2 -t 0.2 suffix || true
        case $suffix in '[A'|'OA') selected=$((1 - selected)) ;; '[B'|'OB') selected=$((1 - selected)) ;; esac
        ;;
      ' ')
        if (( selected == 0 )); then skip_codex=$((1 - skip_codex)); else skip_claude=$((1 - skip_claude)); fi
        ;;
      '') return 0 ;;
      q|Q) printf 'Setup cancelled.\n'; return 130 ;;
    esac
    printf '\033[2A'
  done
}

prompt_openlux_key() {
  local saved_auth=$1
  if [[ -n ${OPENLUX_API_KEY:-} ]]; then
    setup_api_key=$OPENLUX_API_KEY
  elif [[ -t 0 ]]; then
    printf '\nOpenLux API key (input hidden'
    if [[ $saved_auth == true ]]; then printf '; Enter keeps saved credentials'; fi
    printf '): '
    while :; do
      IFS= read -rs setup_api_key || { printf '\nSetup cancelled.\n' >&2; return 130; }
      printf '\n'
      if [[ -n $setup_api_key || $saved_auth == true ]]; then break; fi
      printf 'A key is required for the selected agents. OpenLux API key: '
    done
  elif [[ $saved_auth != true ]]; then
    printf 'Set OPENLUX_API_KEY for unattended setup; selected agents have no saved API key.\n' >&2
    return 2
  fi
  if [[ $setup_api_key == *[$'\r\n\t ']* ]]; then
    printf 'The API key must not contain whitespace. Rerun setup with the key only.\n' >&2
    return 2
  fi
}

# Default to no on Enter or EOF; retry unrecognized answers.
prompt_yes_no() {
  local answer
  while :; do
    printf '%s' "$1"
    IFS= read -r answer || { printf '\n'; return 1; }
    case $answer in
      y|Y|yes|YES|Yes) return 0 ;;
      ''|n|N|no|NO|No) return 1 ;;
      *) printf 'Please enter y or n.\n' ;;
    esac
  done
}
