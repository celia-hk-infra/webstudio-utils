# webstudio-utils

Bootstrap a new WebStudio container from the persistent `gabriel-mlops` NFS
mount. Keep this checkout at
`/home/ma-user/work/dataset/gabriel-mlops/webstudio-utils`; the setup script
uses the checkout's parent directory for persistent data. The old `gabriel`
mount is `fuse.obsfs` and was much slower for small files in this environment.

## New container

```bash
cd /home/ma-user/work/dataset/gabriel-mlops/webstudio-utils
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

## What lives where

| Location | Contents |
| --- | --- |
| `gabriel-mlops/.webstudio-agent-home` | Codex sessions, history, configuration, and other agent state |
| `gabriel-mlops/.webstudio-tunnel` | Tunnel name and VS Code CLI identity/sign-in data |
| `gabriel-mlops/tools` and `cache` | Pinned Codex package and VS Code runtime/download cache |
| `/tmp/webstudio-$UID` | Local Codex executable copy, VS Code CLI, and VS Code server |

Codex is pinned to version `0.166.0` in `setup_container.sh`. Set
`WEBSTUDIO_CODEX_VERSION` for an intentional upgrade. The first setup downloads
the package to NFS; each fresh container copies it to local disk. The VS Code
CLI download is also cached on NFS, then extracted locally. The Conda runtime
for the VS Code server stays on NFS. The script needs `node`, `npm`, `conda`,
`curl`, and `tar` in the container; the tunnel launcher checks its platform
requirements.

`shell/init.sh` links the persistent agent directories and `shell/.bash_profile`
into `$HOME` when those paths are absent. It leaves existing home files in place
and reports any conflicts. It sets `CODEX_HOME` to the NFS directory, clears
the container's Bash `TMOUT`, and puts the staged Codex CLI on `PATH`. Source it
again in JupyterLab terminals that do not read the login profile. Set
`WEBSTUDIO_PERSIST_ROOT`, `WEBSTUDIO_AGENT_STATE_DIR`, or `WEBSTUDIO_LOCAL_DIR`
before sourcing to override the defaults.

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
