#!/usr/bin/env bash
set -euo pipefail
set +xv
repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
agent=${1:?agent required}; shift
case $agent in codex|claude) ;; *) exit 2;; esac
state=${WEBSTUDIO_AGENT_STATE_DIR:?}
real="$state/bin/$agent-real"
provider=${WEBSTUDIO_PROVIDER:-auto}
if [[ ${1:-} == --provider ]]; then provider=${2:?}; shift 2; fi
case ${1:-} in --help|-h|--version|-V) exec "$real" "$@";; esac
export EGRESS_STATE_DIR="$state/egress"
egress="$repo/vendor/codex-local-egress/remote.sh"
if [[ $provider == auto ]]; then
  if [[ -f $EGRESS_STATE_DIR/connection.env ]]; then
    if bash "$egress" check >/dev/null 2>&1; then provider=official
    elif [[ -f $state/providers/openlux/$agent.ready && -t 0 ]]; then
      read -r -p 'Personal egress unavailable. Use OpenLux for this session? [y/N] ' reply
      case $reply in y|Y|yes) provider=openlux;; *) exit 1;; esac
    else
      echo 'Personal egress unavailable. Reconnect it or explicitly select --provider openlux.' >&2; exit 1
    fi
  else provider=official; fi
fi
unset OPENAI_API_KEY OPENAI_BASE_URL CODEX_API_KEY ANTHROPIC_API_KEY ANTHROPIC_AUTH_TOKEN ANTHROPIC_BASE_URL CLAUDE_CODE_USE_GATEWAY CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY
case $provider in
 official)
  export CODEX_HOME="$state/.codex" CLAUDE_CONFIG_DIR="$state/.claude"
  route='official authentication'
  ;;
 openlux)
  [[ -f $state/providers/openlux/$agent.ready ]] || { echo 'Configure OpenLux backup first.' >&2; exit 2; }
  export CODEX_HOME="$state/providers/openlux/codex" CLAUDE_CONFIG_DIR="$state/providers/openlux/claude"
  unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy
  route='OpenLux · separate session history'
  ;;
 *) echo 'Provider must be auto, official, or openlux.' >&2; exit 2;;
esac
args=("$@")
# This flag belongs to interactive Codex, not login/exec and other subcommands.
if [[ $agent == codex ]]; then
  subcommand=0
  for arg in "$@"; do
    case $arg in login|logout|exec|review|mcp|plugin|app-server|remote-control|completion|update|doctor|sandbox|debug|apply|queue|archive|delete|migrate-rollouts|migrate-nfs-db|unarchive|cloud|exec-server|features|help) subcommand=1; break;; esac
  done
  (( subcommand )) || args=(--no-daemon "${args[@]}")
fi
if [[ $provider == official && -f $EGRESS_STATE_DIR/connection.env ]]; then
  echo 'Using personal egress · official authentication' >&2
  exec bash "$egress" exec -- "$real" "${args[@]}"
fi
echo "Using $route" >&2
exec "$real" "${args[@]}"
