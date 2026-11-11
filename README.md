# webstudio-utils

Bootstrap a new WebStudio container from a checkout on any filesystem. The setup
script uses the checkout's parent directory for persistent data; set
`WEBSTUDIO_PERSIST_ROOT` to use a different location.

## New container

```bash
cd /home/ma-user/work/dataset/gabriel-sfs/webstudio-utils
./setup_container.sh --tunnel-name my-jupyter  # choose a name on the first run
source shell/init.sh                         # for this terminal's environment
codex resume                                 # or simply: codex
```

The setup script saves the tunnel name. On later containers, run
`./setup_container.sh` without `--tunnel-name`. It is safe to rerun. To start
the tunnel in a terminal, run:

```bash
./scripts/start_vscode_tunnel.sh
```

Keep that process running while using VS Code. The tunnel launcher also sources
`shell/init.sh`, so it passes the agent environment to VS Code terminals. It
preserves the tunnel's CLI identity and sign-in data on NFS, and reuses the saved
name. The server installation runs on local `/tmp` storage; it is rebuilt when a
container is replaced. A sign-in may still be needed if the stored credential
expires or is revoked. Do not run the same tunnel identity from two containers
at once.
Tunnel names can be at most 20 letters, digits, or hyphens. Use
`./setup_container.sh --tunnel-name SHORT-NAME` to change a saved name.

## If setup reports mode 700

The old `gabriel` mount reports the agent home as `777`, even after chmod.
Changing permissions repeatedly cannot fix a mount that does not preserve them.
Use this checkout on `gabriel-sfs`, which supports private directory permissions.
If your shell still has overrides from the old checkout, clear them first:

```bash
unset WEBSTUDIO_PERSIST_ROOT WEBSTUDIO_AGENT_STATE_DIR WEBSTUDIO_LOCAL_DIR
cd /home/ma-user/work/dataset/gabriel-sfs/webstudio-utils
./setup_container.sh
source shell/init.sh
```

Container replacement wipes home-directory links and local executable copies.
Rerunning setup restores those from the persistent mount. It does not recover
state that was stored only in the wiped home directory.

## What lives where

| Location | Contents |
| --- | --- |
| `gabriel-sfs/.webstudio-agent-home` | Codex sessions, history, configuration, and other agent state |
| `gabriel-sfs/.webstudio-tunnel` | Tunnel name and VS Code CLI identity/sign-in data |
| `gabriel-sfs/tools` and `cache` | Pinned Codex package and VS Code runtime/download cache |
| `gabriel-sfs/tools/gh` | GitHub CLI binary, shared by new shells and containers |
| `gabriel-sfs/.webstudio-agent-home/gh` | GitHub CLI login data |
| `/tmp/webstudio-$UID` | Local Codex executable copy, VS Code CLI, and VS Code server |

Codex is pinned to version `0.166.0` in `setup_container.sh`. Set
`WEBSTUDIO_CODEX_VERSION` for an intentional upgrade. The first setup downloads
the package to persistent storage; each fresh container copies it to local disk. The VS Code
CLI download is also cached on persistent storage, then extracted locally. The Conda runtime
for the VS Code server stays on NFS. The script needs `node`, `npm`, `conda`,
`curl`, and `tar` in the container; the tunnel launcher checks its platform
requirements.

After installing Codex, setup sets top-level `openai_base_url` in
`$CODEX_HOME/config.toml` to `"https://api.openlux.ai/v1"`, preserving other
settings. Rerunning setup reapplies this URL; `--skip-codex` skips it.

GitHub CLI is pinned to version `2.103.3`. The setup verifies the official
release checksum and installs it under `tools/gh`; `shell/init.sh` puts it on
`PATH` and sets `GH_CONFIG_DIR` to persistent private storage. Authenticate once
with `gh auth login`; later shells and containers reuse that login.

`shell/init.sh` links persistent agent directories into `$HOME` and appends an
idempotent startup hook to `.bashrc` and the active Bash login profile, preserving
existing configuration. This supports both login and regular interactive
terminals, including root containers. Run setup as the user who will run the
agents; each user needs their own setup and private local staging directory
(`/tmp/webstudio-$UID` by default). Setup does not change another user's home or
share private agent state between users. If switching users on the same mount,
set `WEBSTUDIO_AGENT_STATE_DIR` to a separate directory owned by that user.
It sets `CODEX_HOME`, clears Bash `TMOUT`, and puts staged CLIs on `PATH`.
Source `shell/init.sh` in the current terminal after setup; future Bash terminals
load it automatically. Terminals launched with `--norc` need explicit sourcing.
Set `WEBSTUDIO_PERSIST_ROOT`, `WEBSTUDIO_AGENT_STATE_DIR`, or `WEBSTUDIO_LOCAL_DIR`
before sourcing to override the defaults.
The setup checks that Codex's daemon control directory is private and repairs a
migrated daemon package link that still points to the previous mount.

## Moving existing Codex history

This container has used both `$HOME/.codex` and the previous init script's
`/home/ma-user/work/dataset/gabriel/.webstudio-agent-home/.codex`. The new
setup does not merge these live directories automatically. Identify which one
contains the sessions you want, stop all Codex processes using that directory,
run the new setup once, then copy that directory's contents to NFS. For the
previous `gabriel` state, the command is:

```bash
cp -a /home/ma-user/work/dataset/gabriel/.webstudio-agent-home/.codex/. \
  /home/ma-user/work/dataset/gabriel-sfs/.webstudio-agent-home/.codex/
```

To migrate `$HOME/.codex` instead, replace the source path with
`$HOME/.codex/.`. Do not copy one source over the other without deciding how to
handle duplicate database and session files. Copy while Codex is stopped so
its SQLite files and session files are consistent. The old `gabriel` mount
reported mode `777` even after `chmod 600`; avoid keeping credentials there.
Codex can reopen saved conversations with `codex resume`, but an in-progress
command ends when the container dies.

## Options

Run `./setup_container.sh --help` and
`./scripts/start_vscode_tunnel.sh --help` for overrides. For a quick agent-only
setup, use `--skip-vscode`; for a tunnel-only setup, use `--agents none`.

## Choose Codex, Claude Code, or both

Setup displays a checkbox menu in a terminal: type `1` or `2` to toggle an
agent, then press Enter to install the selection. Both are selected initially.
For scripts (no menu), use:

```bash
./setup_container.sh --agents both --skip-vscode
# Other choices: --agents codex, --agents claude, --agents none
source shell/init.sh
```

Without a terminal, setup defaults to both. `--skip-codex` and `--skip-claude`
exclude an agent without showing the menu. Skipping an agent does not uninstall it.
Claude Code is pinned to `2.1.322`; override with `WEBSTUDIO_CLAUDE_VERSION`.
Both CLIs are cached under `tools/<agent>/<version>` and staged locally under
`/tmp/webstudio-$UID`. Downloads use `https://registry.npmmirror.com` for faster
access from China. Set `WEBSTUDIO_NPM_REGISTRY=https://registry.npmjs.org` to
use the official registry instead; this does not change global npm settings.

Both agents are configured for OpenLux:

- Codex: `https://api.openlux.ai/v1` in its existing TOML configuration.
- Claude Code: `https://api.openlux.ai` via `ANTHROPIC_BASE_URL` in persistent
  `$CLAUDE_CONFIG_DIR/settings.json` and the shell environment. Claude appends
  `/v1/messages` itself. `CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=1` loads
  available Claude models from OpenLux's authenticated `/v1/models` endpoint
  into `/model`, including newly advertised releases. Setup removes the old
  `CLAUDE_CODE_USE_GATEWAY` setting, which disables discovery in this CLI version.
  This requires `ANTHROPIC_AUTH_TOKEN` containing your OpenLux key. Discovery
  updates the picker; it does not automatically switch your selected model.
  Setup does not pin model IDs. Existing model preferences and credentials are
  preserved; remove any old 4.x pins yourself to stop using those defaults.

Supply your OpenLux API key before starting. For Codex, read it privately and
save it using its login command; for Claude, export it in the terminal:

```bash
read -rsp 'OpenLux API key: ' OPENLUX_API_KEY; printf '\n'
printf '%s' "$OPENLUX_API_KEY" | codex login --with-api-key  # if Codex is installed
export ANTHROPIC_AUTH_TOKEN="$OPENLUX_API_KEY"
unset OPENLUX_API_KEY
claude  # or: codex
```

To persist Claude credentials across containers, add `ANTHROPIC_AUTH_TOKEN` to
`env` in `$CLAUDE_CONFIG_DIR/settings.json` (keep this file private and outside
Git). `shell/init.sh` sets `CLAUDE_CONFIG_DIR` to the persistent `.claude`
directory, so Claude uses the same settings after a restart. Setup never asks
for or prints API keys. Availability of models depends on your OpenLux account.
