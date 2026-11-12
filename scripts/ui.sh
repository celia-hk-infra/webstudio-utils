#!/usr/bin/env bash
# Terminal styling shared by the setup scripts. Source it, then call ui_setup.
# Color and animation are used only on terminals; NO_COLOR or redirected
# output falls back to plain text.

ui_setup() {
  UI_TTY=0
  if [[ -t 1 && ${TERM:-dumb} != dumb ]]; then UI_TTY=1; fi
  UI_RESET= UI_BOLD= UI_DIM= UI_RED= UI_GREEN= UI_YELLOW= UI_ACCENT= UI_MUTED= UI_BADGE=
  if (( UI_TTY )) && [[ -z ${NO_COLOR:-} ]]; then
    UI_RESET=$'\033[0m' UI_BOLD=$'\033[1m' UI_DIM=$'\033[2m'
    UI_RED=$'\033[31m' UI_GREEN=$'\033[32m' UI_YELLOW=$'\033[33m'
    UI_ACCENT=$'\033[36m' UI_MUTED=$'\033[90m' UI_BADGE=$'\033[1;30;46m'
    if [[ ${TERM:-} == *256color* || ${COLORTERM:-} == @(truecolor|24bit) ]]; then
      UI_ACCENT=$'\033[38;5;75m' UI_MUTED=$'\033[38;5;242m' UI_GREEN=$'\033[38;5;78m'
      UI_RED=$'\033[38;5;203m' UI_YELLOW=$'\033[38;5;221m' UI_BADGE=$'\033[1;38;5;16;48;5;75m'
    fi
  fi
  local charmap=${LC_ALL:-${LC_CTYPE:-${LANG:-}}}
  if command -v locale >/dev/null 2>&1; then charmap=$(locale charmap 2>/dev/null); fi
  if [[ ${charmap^^} == *UTF-8* || ${charmap^^} == *UTF8* ]]; then
    UI_BAR='│' UI_START='┌' UI_END='└' UI_ACTIVE='◆' UI_DONE='◇' UI_OK='✔' UI_FAIL='✖'
    UI_WARN='▲' UI_POINTER='❯' UI_ON='◼' UI_OFF='◻' UI_RADIO_ON='●' UI_RADIO_OFF='○'
    UI_DOT='•' UI_SEP='·' UI_SPIN=(⠋ ⠙ ⠹ ⠸ ⠼ ⠴ ⠦ ⠧ ⠇ ⠏)
  else
    UI_BAR='|' UI_START='+' UI_END='+' UI_ACTIVE='*' UI_DONE='o' UI_OK='ok' UI_FAIL='x'
    UI_WARN='!' UI_POINTER='>' UI_ON='[x]' UI_OFF='[ ]' UI_RADIO_ON='(*)' UI_RADIO_OFF='( )'
    UI_DOT='*' UI_SEP='-' UI_SPIN=('|' '/' '-' '\')
  fi
  UI_RUN_PID=
}

ui_cols() {
  local rows cols
  if read -r rows cols < <(stty size 2>/dev/null </dev/tty) && (( cols > 20 )); then
    printf '%s' "$cols"
  else
    printf '80'
  fi
}

ui_intro() {
  printf '\n%s%s%s  %s %s %s' "$UI_MUTED" "$UI_START" "$UI_RESET" "${UI_BADGE:-$UI_BOLD}" "$1" "$UI_RESET"
  if [[ -n ${2:-} ]]; then printf '  %s%s%s' "$UI_DIM" "$2" "$UI_RESET"; fi
  printf '\n%s%s%s\n' "$UI_MUTED" "$UI_BAR" "$UI_RESET"
}

ui_outro() {
  printf '%s%s%s  %s\n\n' "$UI_MUTED" "$UI_END" "$UI_RESET" "$1"
}

ui_bar() {
  printf '%s%s%s\n' "$UI_MUTED" "$UI_BAR" "$UI_RESET"
}

ui_note() {
  local line
  for line in "$@"; do
    printf '%s%s%s  %s%s%s\n' "$UI_MUTED" "$UI_BAR" "$UI_RESET" "$UI_DIM" "$line" "$UI_RESET"
  done
}

# A completed question: title, then its answer underneath.
ui_answer() {
  printf '%s%s%s  %s\n' "$UI_GREEN" "$UI_DONE" "$UI_RESET" "$1"
  printf '%s%s%s  %s%s%s\n' "$UI_MUTED" "$UI_BAR" "$UI_RESET" "$UI_DIM" "$2" "$UI_RESET"
  ui_bar
}

ui_ok() {
  printf '%s%s%s  %s' "$UI_GREEN" "$UI_OK" "$UI_RESET" "$1"
  if [[ -n ${2:-} ]]; then printf '  %s%s%s' "$UI_MUTED" "$2" "$UI_RESET"; fi
  printf '\n'
}

ui_step() {
  printf '%s%s%s  %s%s%s\n' "$UI_ACCENT" "$UI_ACTIVE" "$UI_RESET" "$UI_BOLD" "$1" "$UI_RESET"
}

ui_warn() {
  printf '%s%s%s  %s\n' "$UI_YELLOW" "$UI_WARN" "$UI_RESET" "$1" >&2
}

ui_error() {
  printf '%s%s  %s%s\n' "$UI_RED" "$UI_FAIL" "$1" "$UI_RESET" >&2
}

# Rounded box for the final summary; arguments are plain-text lines. Falls back
# to railed lines when the box would wrap in a narrow terminal.
ui_box() {
  local title=$1 line width=${#1}
  shift
  for line in "$@"; do (( ${#line} > width )) && width=${#line}; done
  if (( width + 4 > $(ui_cols) )); then
    ui_ok "$title"
    for line in "$@"; do printf '%s%s%s  %s\n' "$UI_MUTED" "$UI_BAR" "$UI_RESET" "$line"; done
    return
  fi
  if [[ $UI_BAR == '│' ]]; then
    local h='─' tl='╭' tr='╮' bl='╰' br='╯' v='│'
  else
    local h='-' tl='+' tr='+' bl='+' br='+' v='|'
  fi
  local rule
  printf -v rule '%*s' $((width + 2)) ''
  rule=${rule// /$h}
  printf '%s%s%s %s%s%s %s%s%s\n' "$UI_MUTED" "$tl$h" "$UI_RESET" "$UI_BOLD" "$title" "$UI_RESET" \
    "$UI_MUTED" "${rule:0:$((width - ${#title}))}$tr" "$UI_RESET"
  for line in "$@"; do
    printf '%s%s%s %s%*s %s%s%s\n' "$UI_MUTED" "$v" "$UI_RESET" "$line" $((width - ${#line})) '' \
      "$UI_MUTED" "$v" "$UI_RESET"
  done
  printf '%s%s%s%s%s\n' "$UI_MUTED" "$bl" "$rule" "$br" "$UI_RESET"
}

# Last visible line of a log, for showing live progress next to the spinner.
ui_last_line() {
  tail -c 600 -- "$1" 2>/dev/null | tr '\r' '\n' | sed 's/\x1b\[[0-9;?]*[A-Za-z]//g; s/[[:space:]]\+/ /g' |
    grep -v '^ *$' | tail -n 1 || true
}

# Run a noisy command with a spinner, keeping its output in a log that is shown
# only on failure. Call it as a plain statement, never after || or &&: Bash
# ignores set -e inside such contexts, and setup steps rely on set -e.
ui_run() {
  local label=$1 log status=0 pid frame=0 start=$SECONDS hint= cols room
  shift
  log=$(mktemp "${TMPDIR:-/tmp}/webstudio-step.XXXXXX")
  if (( ! UI_TTY )); then printf '%s...\n' "$label"; fi
  "$@" >"$log" 2>&1 </dev/null &
  pid=$!
  UI_RUN_PID=$pid
  if (( UI_TTY )); then
    cols=$(ui_cols)
    printf '\033[?25l'
    while kill -0 "$pid" 2>/dev/null; do
      if (( frame % 5 == 0 )); then hint=$(ui_last_line "$log"); fi
      room=$((cols - ${#label} - 16))
      printf '\r\033[2K%s%s%s  %s %s%ss%s' "$UI_ACCENT" "${UI_SPIN[frame % ${#UI_SPIN[@]}]}" "$UI_RESET" \
        "$label" "$UI_MUTED" $((SECONDS - start)) "$UI_RESET"
      if [[ -n $hint ]] && (( room > 10 )); then
        printf '  %s%s%s' "$UI_DIM" "${hint:0:room}" "$UI_RESET"
      fi
      sleep 0.08
      frame=$((frame + 1))
    done
  fi
  wait "$pid" || status=$?
  UI_RUN_PID=
  UI_ELAPSED="$((SECONDS - start))s"
  if (( UI_TTY )); then printf '\r\033[2K\033[?25h'; fi
  if [[ -n ${UI_LOG:-} ]]; then
    { printf '\n==> %s (exit %s)\n' "$label" "$status"; cat -- "$log"; } >> "$UI_LOG"
  fi
  if (( status != 0 )); then
    ui_error "$label failed"
    sed 's/^/   /' < <(tail -n 20 -- "$log") >&2
    if [[ -n ${UI_LOG:-} ]]; then printf '   %sFull log: %s%s\n' "$UI_DIM" "$UI_LOG" "$UI_RESET" >&2; fi
  fi
  rm -f -- "$log"
  return "$status"
}

# Restore the terminal and stop a running step when the script is interrupted.
ui_cleanup() {
  if [[ -n ${UI_RUN_PID:-} ]]; then
    pkill -TERM -P "$UI_RUN_PID" 2>/dev/null || true
    kill -TERM "$UI_RUN_PID" 2>/dev/null || true
    UI_RUN_PID=
  fi
  if (( ${UI_TTY:-0} )); then printf '\033[?25h'; fi
}

# Arrow-key menu. ui_menu multi|single TITLE OPTION... where each option is
# "Label|description". Selection state is read from and written to UI_MENU
# (an array of 0/1 for multi, the chosen index for single).
ui_menu() {
  local mode=$1 title=$2 key suffix i mark pointer label desc width=0 drawn=0 cursor=0 lines
  shift 2
  local -a options=("$@")
  for i in "${!options[@]}"; do
    label=${options[i]%%|*}
    (( ${#label} > width )) && width=${#label}
  done
  if [[ $mode == single ]]; then cursor=${UI_MENU[0]:-0}; fi
  lines=$(( ${#options[@]} + 2 ))
  printf '\033[?25l'
  while :; do
    if (( drawn )); then printf '\033[%dA' "$lines"; fi
    drawn=1
    printf '\r\033[2K%s%s%s  %s%s%s\n' "$UI_ACCENT" "$UI_ACTIVE" "$UI_RESET" "$UI_BOLD" "$title" "$UI_RESET"
    for i in "${!options[@]}"; do
      label=${options[i]%%|*} desc=${options[i]#*|}
      if [[ $mode == multi ]]; then
        if (( UI_MENU[i] )); then mark="$UI_GREEN$UI_ON$UI_RESET"; else mark="$UI_MUTED$UI_OFF$UI_RESET"; fi
      else
        if (( i == cursor )); then mark="$UI_GREEN$UI_RADIO_ON$UI_RESET"; else mark="$UI_MUTED$UI_RADIO_OFF$UI_RESET"; fi
      fi
      if (( i == cursor )); then
        pointer="$UI_ACCENT$UI_POINTER$UI_RESET"
        printf '\r\033[2K%s%s%s  %s %s %s%-*s%s  %s%s%s\n' "$UI_MUTED" "$UI_BAR" "$UI_RESET" "$pointer" "$mark" \
          "$UI_BOLD" "$width" "$label" "$UI_RESET" "$UI_DIM" "$desc" "$UI_RESET"
      else
        printf '\r\033[2K%s%s%s    %s %-*s  %s%s%s\n' "$UI_MUTED" "$UI_BAR" "$UI_RESET" "$mark" \
          "$width" "$label" "$UI_MUTED" "$desc" "$UI_RESET"
      fi
    done
    if [[ $mode == multi ]]; then
      printf '\r\033[2K%s%s  ↑/↓ move %s space toggle %s a all %s enter confirm %s q cancel%s\n' "$UI_MUTED" "$UI_BAR" \
        "$UI_SEP" "$UI_SEP" "$UI_SEP" "$UI_SEP" "$UI_RESET"
    else
      printf '\r\033[2K%s%s  ↑/↓ move %s enter select %s q cancel%s\n' "$UI_MUTED" "$UI_BAR" "$UI_SEP" "$UI_SEP" "$UI_RESET"
    fi
    IFS= read -rsn1 key || { printf '\033[?25h'; return 130; }
    case $key in
      $'\033')
        suffix=
        IFS= read -rsn2 -t 0.2 suffix || true
        case $suffix in
          '[A'|'OA') cursor=$(( (cursor + ${#options[@]} - 1) % ${#options[@]} )) ;;
          '[B'|'OB') cursor=$(( (cursor + 1) % ${#options[@]} )) ;;
        esac
        ;;
      k) cursor=$(( (cursor + ${#options[@]} - 1) % ${#options[@]} )) ;;
      j) cursor=$(( (cursor + 1) % ${#options[@]} )) ;;
      ' ') if [[ $mode == multi ]]; then UI_MENU[cursor]=$((1 - UI_MENU[cursor])); fi ;;
      a|A)
        if [[ $mode == multi ]]; then
          mark=0
          for i in "${!options[@]}"; do (( UI_MENU[i] )) || mark=1; done
          for i in "${!options[@]}"; do UI_MENU[i]=$mark; done
        fi
        ;;
      '')
        if [[ $mode == single ]]; then UI_MENU=("$cursor"); fi
        printf '\033[%dA\r\033[J\033[?25h' "$lines"
        return 0
        ;;
      q|Q)
        printf '\033[%dA\r\033[J\033[?25h' "$lines"
        printf '%s%s  Setup cancelled.%s\n' "$UI_RED" "$UI_FAIL" "$UI_RESET"
        return 130
        ;;
    esac
  done
}

# Single-line input read key by key. Masked input shows bullets; otherwise only
# characters matching the glob ALLOWED are accepted, up to MAX characters.
# Enter submits the value (or DEFAULT when empty) only if it matches the regex
# VALID; otherwise ERROR is shown and editing continues.
# ui_input RESULT_VAR TITLE DEFAULT ALLOWED MAX MASK VALID ERROR
ui_input() {
  local -n _ui_result=$1
  local title=$2 default=$3 allowed=$4 max=$5 mask=$6 valid=$7 error=$8
  local value= key shown count problem= submitted
  printf '%s%s%s  %s%s%s\n' "$UI_ACCENT" "$UI_ACTIVE" "$UI_RESET" "$UI_BOLD" "$title" "$UI_RESET"
  while :; do
    if [[ $mask == 1 ]]; then
      printf -v shown '%*s' $(( ${#value} > 32 ? 32 : ${#value} )) ''
      shown=${shown// /$UI_DOT}
      count=
      if (( ${#value} )); then count="  $UI_MUTED${#value} characters$UI_RESET"; fi
    else
      shown=$value
      count="  $UI_MUTED${#value}/$max$UI_RESET"
    fi
    if [[ -n $problem ]]; then count="  $UI_RED$problem$UI_RESET"; fi
    printf '\r\033[2K%s%s%s  %s%s%s ' "$UI_MUTED" "$UI_BAR" "$UI_RESET" "$UI_ACCENT" "$UI_POINTER" "$UI_RESET"
    if [[ -z $value && -n $default ]]; then
      printf '%s%s%s' "$UI_DIM" "$default" "$UI_RESET"
      if [[ -n $problem ]]; then printf '%s' "$count"; fi
      printf '\r\033[5C'
    else
      printf '%s%s' "$shown" "$count"
      printf '\r\033[%dC' $((5 + ${#shown}))
    fi
    IFS= read -rsn1 key || { printf '\n'; return 130; }
    problem=
    case $key in
      '')
        submitted=${value:-$default}
        if [[ $submitted =~ $valid ]]; then break; fi
        problem=$error
        ;;
      $'\177'|$'\b') value=${value%?} ;;
      $'\025') value= ;;
      $'\004') printf '\n'; return 130 ;;
      $'\033') IFS= read -rsn2 -t 0.05 _ || true ;;
      *)
        if [[ $mask == 1 ]]; then
          if [[ $key == [[:print:]] ]]; then value+=$key; fi
        elif [[ $key == $allowed ]] && (( ${#value} < max )); then
          value+=$key
        elif (( ${#value} >= max )); then
          problem="maximum $max characters"
        else
          problem="'$key' is not allowed"
        fi
        ;;
    esac
  done
  printf '\r\033[2K\033[1A\r\033[2K'
  _ui_result=$submitted
}
