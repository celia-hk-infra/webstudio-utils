[简体中文](README.md) | English

# webstudio-utils

Bootstrap a new WebStudio container from a checkout on any filesystem. The setup
script uses the checkout's parent directory for persistent data; set
`WEBSTUDIO_PERSIST_ROOT` to use a different location.

- [New container](#new-container)
- [What lives where](#what-lives-where)
- [Choosing agents](#choosing-agents)
- [Credentials and gateway configuration](#credentials-and-gateway-configuration)
- [After a container restart](#after-a-container-restart)
- [Moving existing Codex history](#moving-existing-codex-history)
- [Troubleshooting](#troubleshooting)
- [Options](#options)

## New container

Keep the checkout on a persistent mount that preserves Unix permissions, for
example `/home/user/work/dataset/user-sfs/webstudio-utils`:

```bash
cd /home/user/work/dataset/user-sfs/webstudio-utils
./setup_container.sh --tunnel-name my-jupyter  # choose a name on the first run
source shell/init.sh                           # for this terminal's environment
codex resume                                   # or simply: codex
```

Setup also installs tmux with its dependencies under `tools/tmux` on persistent
storage and makes it available in new shells. Conda is required for the first
installation, including when using `--skip-vscode`. Existing tmux installations
in that directory are reused. Running tmux sessions end when the container is
replaced.

Interactive setup prompts for a tunnel name (Enter keeps the saved or default
name) and then asks how to start the tunnel: in the background (default),
in the terminal, or not at all. The background option runs the tunnel in a
detached tmux session named `vscode-tunnel`; it keeps running after the
terminal closes. Use `--start-tunnel` (background) or
`--start-tunnel=foreground` to choose without the prompt, or
`--no-start-tunnel` to skip it. Unattended runs do not start the tunnel
unless explicitly requested. `--skip-vscode` skips tunnel installation and the
start question, and cannot be combined with `--start-tunnel`.

The setup script saves the tunnel name, so later containers can run
`./setup_container.sh` without `--tunnel-name`. It is safe to rerun.

After setup, manage the tunnel directly:

```bash
./scripts/start_vscode_tunnel.sh --background   # start in the background
./scripts/start_vscode_tunnel.sh --status       # show whether it is connected
./scripts/start_vscode_tunnel.sh --stop         # stop the background session
./scripts/start_vscode_tunnel.sh                # run in this terminal (Ctrl+C stops)
```

The tunnel launcher also sources `shell/init.sh`, so it passes the agent
environment to VS Code terminals. It preserves the tunnel's CLI identity and
sign-in data on persistent storage, and reuses the saved name. The server
installation runs on local `/tmp` storage and is rebuilt when a container is
replaced. A sign-in may still be needed if the stored credential expires or is
revoked. Do not run the same tunnel identity from two containers at once.

Tunnel names can be at most 20 letters, digits, or hyphens. Use
`./setup_container.sh --tunnel-name SHORT-NAME` to change a saved name.

## What lives where

| Location | Contents |
| --- | --- |
| `user-sfs/.webstudio-agent-home` | Codex sessions, history, configuration, and other agent state |
| `user-sfs/.webstudio-agent-home/gh` | GitHub CLI login data |
| `user-sfs/.webstudio-tunnel` | Tunnel name and VS Code CLI identity/sign-in data |
| `user-sfs/tools` and `cache` | Pinned CLI packages, VS Code runtime, and download cache |
| `user-sfs/tools/gh` | GitHub CLI binary, shared by new shells and containers |
| `user-sfs/tools/tmux` | tmux and its Conda dependencies |
| `/tmp/webstudio-$UID` | Local CLI copies, VS Code CLI, and VS Code server |

Pinned versions live in `setup_container.sh`:

| Tool | Version | Override |
| --- | --- | --- |
| Codex CLI | `0.166.0` | `WEBSTUDIO_CODEX_VERSION` |
| Claude Code | `2.1.322` | `WEBSTUDIO_CLAUDE_VERSION` |
| GitHub CLI | `2.103.3` | `WEBSTUDIO_GH_VERSION` |

The first setup downloads each package to persistent storage; every fresh
container copies it to local disk. The VS Code CLI download is also cached on
persistent storage, then extracted locally. The Conda runtime for the VS Code
server stays on persistent storage. The script needs `node`, `npm`, `conda`,
`curl`, and `tar` in the container; the tunnel launcher checks its platform
requirements.

## Choosing agents

Setup displays a checklist in a terminal: use Up/Down to move, Space to select
or deselect, and Enter to continue. Both agents are selected initially; press
`q` to cancel. Next, enter your OpenLux API key at the hidden prompt. Setup
saves it for every selected agent, so no separate login is needed. On reruns,
Enter keeps existing credentials if all selected agents have keys.

For scripts (no selection menu), use:

```bash
./setup_container.sh --agents both --skip-vscode
# Other choices: --agents codex, --agents claude, --agents none
source shell/init.sh
```

Without a terminal, setup defaults to both. Supply `OPENLUX_API_KEY` through
your environment or secret manager unless all selected agents already have
saved keys. Missing credentials stop setup before downloads. Selecting
`--agents none` skips the key prompt. `--skip-codex` and `--skip-claude`
exclude an agent without showing the menu. Skipping an agent does not uninstall
it.

Both CLIs are cached under `tools/<agent>/<version>` and staged locally under
`/tmp/webstudio-$UID`. Downloads use `https://registry.npmmirror.com` by
default; set `WEBSTUDIO_NPM_REGISTRY=https://registry.npmjs.org` to use the
official registry instead. This does not change global npm settings.

## Credentials and gateway configuration

Both agents are configured for OpenLux.

**Codex.** Setup sets the top-level `openai_base_url` in `$CODEX_HOME/config.toml`
to `"https://api.openlux.ai/v1"`, preserving other settings, and sets
`cli_auth_credentials_store = "file"` so authentication persists in
`$CODEX_HOME/auth.json`. The key is passed with
`codex login --with-api-key` over stdin. Rerunning setup reapplies this URL;
`--skip-codex` skips it.

**Claude Code.** Setup sets `https://api.openlux.ai` as `ANTHROPIC_BASE_URL` in
both persistent `$CLAUDE_CONFIG_DIR/settings.json` and the shell environment.
Claude appends `/v1/messages` itself. `CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=1`
loads available Claude models from OpenLux's authenticated `/v1/models`
endpoint into `/model`, including newly advertised releases. Setup removes the
old `CLAUDE_CODE_USE_GATEWAY` setting, which disables discovery in this CLI
version.

A few details worth knowing:

- Discovery requires `ANTHROPIC_AUTH_TOKEN` containing your OpenLux key. Setup
  saves the entered key there as `env.ANTHROPIC_AUTH_TOKEN`.
- Discovery updates the picker; it does not automatically switch your selected
  model. Setup does not pin model IDs. Existing model preferences are
  preserved, so remove any old 4.x pins yourself to stop using those defaults.
- Setup marks first-run onboarding complete in the persistent
  `$CLAUDE_CONFIG_DIR/.claude.json`. Otherwise onboarding checks Anthropic's
  OAuth endpoints even when the OpenLux API URL is configured.

Credentials are saved outside Git with mode `600` in the private persistent
agent directory. A new key replaces the selected agents' API credentials; other
preferences are preserved. Setup never prints the key or passes it as a command
argument. Model availability depends on your OpenLux account.

GitHub CLI is installed under `tools/gh` after verifying the official release
checksum. `shell/init.sh` puts it on `PATH` and sets `GH_CONFIG_DIR` to
persistent private storage. Setup starts GitHub browser login if no valid login
is available, saves the token as a file in that private directory with mode
`600`, and configures Git to use `gh` for HTTPS authentication. Later setup runs
reuse the saved login and restore Git's credential helper after container
replacement. An expired or revoked token requires login again.

Unattended setup requires a saved login, `GH_TOKEN`, or `GITHUB_TOKEN`.
Environment tokens must be supplied again in new containers. Use
`--skip-gh-auth` to install the CLI without setting up GitHub authentication.

## After a container restart

When you source `shell/init.sh` before setup, it checks for a completion marker
in `WEBSTUDIO_LOCAL_DIR` and offers to run setup. Choosing No leaves the shell
usable and prints the command to run later. Without a terminal, it prints the
command and returns a nonzero status instead of prompting. The marker is written
only after successful setup; keep `WEBSTUDIO_LOCAL_DIR` on local, disposable
storage so a replacement container is detected.

Container replacement wipes home-directory links and local executable copies.
Rerunning setup restores those from the persistent mount. It does not recover
state that was stored only in the wiped home directory.

`shell/init.sh` links persistent agent directories into `$HOME` and appends an
idempotent startup hook to `.bashrc` and the active Bash login profile,
preserving existing configuration. This supports both login and regular
interactive terminals, including root containers. It sets `CODEX_HOME`,
`CLAUDE_CONFIG_DIR`, and `GH_CONFIG_DIR`, clears Bash `TMOUT`, and puts staged
CLIs on `PATH`. The setup also checks that Codex's daemon control directory is
private and repairs a migrated daemon package link that still points to the
previous mount.

Source `shell/init.sh` in the current terminal after setup; future Bash
terminals load it automatically. Terminals launched with `--norc` need explicit
sourcing. New Bash terminals load this environment automatically, and saved
credentials survive container restarts, so no key export or separate login is
needed:

```bash
source shell/init.sh
codex  # or: claude
```

Run setup as the user who will run the agents. Each user needs their own setup
and private local staging directory (`/tmp/webstudio-$UID` by default). Setup
does not change another user's home or share private agent state between users.
If switching users on the same mount, set `WEBSTUDIO_AGENT_STATE_DIR` to a
separate directory owned by that user.

## Moving existing Codex history

A container may have used both `$HOME/.codex` and an older init script's
`user/.webstudio-agent-home/.codex`. The new setup does not merge these live
directories automatically. Identify which one contains the sessions you want,
stop all Codex processes using that directory, run the new setup once, then copy
that directory's contents to the new mount:

```bash
cp -a /home/user/work/dataset/user/.webstudio-agent-home/.codex/. \
  /home/user/work/dataset/user-sfs/.webstudio-agent-home/.codex/
```

To migrate `$HOME/.codex` instead, replace the source path with
`$HOME/.codex/.`. Do not copy one source over the other without deciding how to
handle duplicate database and session files. Copy while Codex is stopped so its
SQLite and session files stay consistent. Codex can reopen saved conversations
with `codex resume`, but an in-progress command ends when the container dies.

## Troubleshooting

### Setup reports mode 700

The previous mount reports the agent home as `777`, even after `chmod`.
Changing permissions repeatedly cannot fix a mount that does not preserve them,
and credentials must not be kept there. Use a mount that supports private
directory permissions, such as `user-sfs`. If your shell still carries
overrides from an older checkout, clear them first:

```bash
unset WEBSTUDIO_PERSIST_ROOT WEBSTUDIO_AGENT_STATE_DIR WEBSTUDIO_LOCAL_DIR
cd /home/user/work/dataset/user-sfs/webstudio-utils
./setup_container.sh
source shell/init.sh
```

### Something else went wrong

Incomplete installs are never reused. If setup reports a partial `tools/<agent>`
cache or local staging copy, move that directory aside and rerun. The setup
replaces files atomically, so an interrupted run leaves no half-written
configuration.

## Options

```bash
./setup_container.sh --help
./scripts/start_vscode_tunnel.sh --help
```

For a quick agent-only setup, use `--skip-vscode`; for a tunnel-only setup, use
`--agents none`. Set `WEBSTUDIO_PERSIST_ROOT`, `WEBSTUDIO_AGENT_STATE_DIR`, or
`WEBSTUDIO_LOCAL_DIR` before sourcing `shell/init.sh` to override the defaults.
The tunnel launcher accepts `CONDA_EXE`, `VSCODE_INSTALL_DIR`,
`VSCODE_LOCAL_DIR`, `VSCODE_GLIBC_LINKER`, and `VSCODE_CONDA_SOLVER`.
