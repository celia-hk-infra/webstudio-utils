# webstudio-utils

Bootstrap a new WebStudio container from a checkout on any filesystem. The setup
script uses the checkout's parent directory for persistent data; set
`WEBSTUDIO_PERSIST_ROOT` to use a different location.

## New container

```bash
cd /path/to/webstudio-utils
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

## What lives where

| Location | Contents |
| --- | --- |
| `gabriel-mlops/.webstudio-agent-home` | Codex sessions, history, configuration, and other agent state |
| `gabriel-mlops/.webstudio-tunnel` | Tunnel name and VS Code CLI identity/sign-in data |
| `gabriel-mlops/tools` and `cache` | Pinned Codex package and VS Code runtime/download cache |
| `gabriel-mlops/tools/gh` | GitHub CLI binary, shared by new shells and containers |
| `gabriel-mlops/.webstudio-agent-home/gh` | GitHub CLI login data |
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

`shell/init.sh` links the persistent agent directories and `shell/.bash_profile`
into `$HOME` when those paths are absent. It leaves existing home files in place
and reports any conflicts. It sets `CODEX_HOME` to the persistent directory, clears
the container's Bash `TMOUT`, and puts the staged Codex CLI on `PATH`. Source it
again in JupyterLab terminals that do not read the login profile. Set
`WEBSTUDIO_PERSIST_ROOT`, `WEBSTUDIO_AGENT_STATE_DIR`, or `WEBSTUDIO_LOCAL_DIR`
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
  /home/ma-user/work/dataset/gabriel-mlops/.webstudio-agent-home/.codex/
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
setup, use `--skip-vscode`; for a tunnel-only setup, use `--skip-codex`.
